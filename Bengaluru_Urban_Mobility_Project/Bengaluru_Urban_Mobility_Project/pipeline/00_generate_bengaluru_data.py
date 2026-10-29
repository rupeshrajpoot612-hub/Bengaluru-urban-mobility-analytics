"""
STAGE 0 — SYNTHETIC DATA GENERATION
Bengaluru Multi-Modal Urban Mobility Analytics (CA3 Activity 2)

No open trip-level dataset exists for Bengaluru bike-taxi / auto / cab
rides, so this script synthesises a realistic one from documented city
patterns (see pipeline/mobility_model.py for every rule):

  * 10 real hubs (Indiranagar, Koramangala, Whitefield, ... BLR airport)
  * hour-of-day demand that differs for residential vs tech-park vs
    transit zones (people leave home in the morning, tech parks at night)
  * morning (08:30-11:30) and evening (17:30-21:30) congestion peaks
  * mode choice driven by distance, rain and time of day
  * fares from the bike / auto / cab rate cards + surge + night charges

It also injects ~1.5% "dirty" records (duplicates, missing fares, bad
distances, typo'd vehicle names, absurd durations) so Stage 1 has real
preprocessing to do. Deterministic: seed 42 -> identical file every run.

Output:
  outputs/bengaluru_mobility_raw.csv

Run:
  python pipeline/00_generate_bengaluru_data.py
"""

import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mobility_model as mm  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
RAW_CSV = os.path.join(OUTPUT_DIR, "bengaluru_mobility_raw.csv")
os.makedirs(OUTPUT_DIR, exist_ok=True)

SEED = 42
TARGET_TRIPS = 250_000
START_DATE, END_DATE = "2025-01-01", "2025-06-30"

# Trips per hour (relative), weekday vs weekend.
WEEKDAY_HOURLY = np.array([
    0.20, 0.12, 0.08, 0.07, 0.10, 0.25, 0.55, 0.95, 1.45, 1.75, 1.60, 1.25,
    1.05, 1.00, 0.95, 1.00, 1.15, 1.45, 1.80, 1.90, 1.65, 1.20, 0.80, 0.45,
])
WEEKEND_HOURLY = np.array([
    0.40, 0.28, 0.18, 0.10, 0.08, 0.15, 0.30, 0.50, 0.75, 0.95, 1.10, 1.20,
    1.25, 1.20, 1.15, 1.15, 1.20, 1.35, 1.55, 1.65, 1.60, 1.40, 1.05, 0.70,
])


def zone_hour_weights(weekend):
    """(24, n_zones) pickup attractiveness, by zone kind and hour."""
    h = np.arange(24)
    morning = np.exp(-((h - 9.5) ** 2) / 6)
    evening = np.exp(-((h - 19) ** 2) / 6)
    late = np.exp(-((h - 23) ** 2) / 8) + np.exp(-((h + 1) ** 2) / 8)
    shapes = {
        "residential": 1 + 1.2 * morning - 0.2 * evening,
        "tech": 1 - 0.3 * morning + (0.6 if weekend else 1.4) * evening,
        "mixed": 1 + 0.3 * morning + 0.6 * evening + (1.0 if weekend else 0.5) * late,
        "transit": 1 + 0.4 * morning + 0.3 * evening + 0.8 * late,
    }
    pop = np.array([z["pop"] for z in mm.ZONES])
    return np.stack([shapes[z["kind"]] for z in mm.ZONES], axis=1) * pop


def main():
    t0 = time.time()
    rng = np.random.default_rng(SEED)
    print("=" * 70)
    print("STAGE 0: GENERATE SYNTHETIC BENGALURU MULTI-MODAL TRIPS")
    print("=" * 70)

    n_z = len(mm.ZONES)
    lat = np.array([z["lat"] for z in mm.ZONES])
    lon = np.array([z["lon"] for z in mm.ZONES])
    straight_km = mm.haversine_km(lat[:, None], lon[:, None], lat[None, :], lon[None, :])

    # ---- days: weekend dip, rainy days (pre-monsoon May, monsoon June) ----
    days = pd.date_range(START_DATE, END_DATE, freq="D")
    dow = days.dayofweek.values
    rain_p = np.where(days.month == 6, 0.45, np.where(days.month == 5, 0.25, 0.05))
    day_rain = rng.random(len(days)) < rain_p
    day_w = np.where(dow >= 5, 0.85, 1.0) * np.where(day_rain, 1.10, 1.0) * rng.normal(1, 0.05, len(days))

    # Expected demand intensity per (weekend, hour, zone) -> demand level for surge.
    zh = {wk: zone_hour_weights(wk) * (WEEKEND_HOURLY if wk else WEEKDAY_HOURLY)[:, None] for wk in (0, 1)}
    all_cells = np.concatenate([zh[0].ravel(), zh[1].ravel()])
    q33, q66 = np.quantile(all_cells, [0.33, 0.66])
    level_of = {wk: np.where(zh[wk] <= q33, "Low", np.where(zh[wk] <= q66, "Medium", "High")) for wk in (0, 1)}

    # ---- trips per (day, hour) ----
    cell_w = np.array([day_w[i] * (WEEKEND_HOURLY if dow[i] >= 5 else WEEKDAY_HOURLY) for i in range(len(days))])
    counts = rng.multinomial(TARGET_TRIPS, (cell_w / cell_w.sum()).ravel()).reshape(cell_w.shape)
    day_idx, hour = np.nonzero(counts)
    reps = counts[day_idx, hour]
    day_idx = np.repeat(day_idx, reps)
    hour = np.repeat(hour, reps)
    n = len(hour)
    minute = rng.integers(0, 60, n)
    second = rng.integers(0, 60, n)
    hour_frac = hour + minute / 60
    trip_dow = dow[day_idx]
    weekend = (trip_dow >= 5).astype(int)
    raining = day_rain[day_idx].astype(int)

    # ---- pickup zone: sampled per (weekend, hour) group ----
    pickup = np.empty(n, dtype=int)
    for wk in (0, 1):
        for h in range(24):
            m = (weekend == wk) & (hour == h)
            p = zh[wk][h] / zh[wk][h].sum()
            pickup[m] = rng.choice(n_z, m.sum(), p=p)

    # ---- dropoff zone: gravity model, tech parks pull in the morning ----
    attract = np.array([z["pop"] for z in mm.ZONES])
    is_tech = np.array([z["kind"] == "tech" for z in mm.ZONES])
    is_res = np.array([z["kind"] == "residential" for z in mm.ZONES])
    dropoff = np.empty(n, dtype=int)
    band = np.where(hour_frac < 12, 0, np.where(hour_frac < 17, 1, 2))
    for b in range(3):
        a = attract * np.where(is_tech, [1.8, 1.0, 0.6][b], 1.0) * np.where(is_res, [0.7, 1.0, 1.5][b], 1.0)
        for o in range(n_z):
            m = (band == b) & (pickup == o)
            w = a * np.exp(-straight_km[o] / 7)
            w[o] = w.sum() * 0.55  # ~45% of trips stay inside the hub area
            dropoff[m] = rng.choice(n_z, m.sum(), p=w / w.sum())

    # ---- distance ----
    intra = pickup == dropoff
    distance = straight_km[pickup, dropoff] * mm.ROAD_CIRCUITY * rng.lognormal(0, 0.10, n)
    distance[intra] = np.clip(rng.lognormal(np.log(2.8), 0.45, intra.sum()), 0.8, 8)
    distance = np.round(distance, 2)

    # ---- mode choice (softmax over utilities) ----
    airport = (pickup == mm.ZONE_INDEX["Kempegowda Airport (BLR)"]) | (dropoff == mm.ZONE_INDEX["Kempegowda Airport (BLR)"])
    night = mm.is_night(hour_frac)
    u = np.stack([
        1.2 - 0.10 * distance - 1.2 * raining - 0.4 * night,              # bike
        0.8 - 0.05 * distance - 0.1 * raining,                             # auto
        -0.5 + 0.06 * distance + 0.7 * raining + 0.4 * night + 1.5 * airport,  # cab
    ], axis=1)
    p = np.exp(u)
    p /= p.sum(axis=1, keepdims=True)
    vehicle_idx = (rng.random(n)[:, None] > np.cumsum(p, axis=1)).sum(axis=1)
    vehicle = np.array(mm.VEHICLES)[vehicle_idx]

    # ---- traffic, duration, fare ----
    tf = mm.traffic_factor(hour_frac, trip_dow, pickup, dropoff, raining)
    duration = mm.expected_duration_minutes(vehicle, distance, tf, raining) * rng.lognormal(0, 0.14, n)
    duration = np.round(duration, 2)

    demand_level = np.where(weekend == 1, level_of[1][hour, pickup], level_of[0][hour, pickup])
    surge = mm.surge_multiplier(demand_level, hour_frac, raining)
    surge = np.round(np.clip(surge + rng.choice([0, 0, 0, 0.05, 0.1], n), mm.SURGE_MIN, mm.SURGE_MAX), 2)
    fare = mm.fare_breakdown(vehicle, distance, duration, tf, hour_frac, surge)["total"]

    pickup_dt = (
        pd.to_datetime(days.values[day_idx])
        + pd.to_timedelta(hour, unit="h") + pd.to_timedelta(minute, unit="m") + pd.to_timedelta(second, unit="s")
    )
    dropoff_dt = pickup_dt + pd.to_timedelta(np.round(duration * 60), unit="s")

    df = pd.DataFrame({
        "vehicle_type": vehicle,
        "pickup_datetime": pickup_dt,
        "dropoff_datetime": dropoff_dt,
        "pickup_zone": np.array(mm.ZONE_NAMES)[pickup],
        "dropoff_zone": np.array(mm.ZONE_NAMES)[dropoff],
        "distance_km": distance,
        "duration_min": duration,
        "fare_inr": fare,
        "surge_multiplier": surge,
        "is_raining": raining,
    }).sort_values("pickup_datetime").reset_index(drop=True)
    df.insert(0, "trip_id", [f"BLR{i:07d}" for i in range(1, len(df) + 1)])

    # ---- inject dirty records for the cleaning stage ----
    k = len(df)
    dirty = rng.choice(k, int(k * 0.012), replace=False)
    parts = np.array_split(dirty, 5)
    df.loc[parts[0], "fare_inr"] = np.nan
    df.loc[parts[1], "distance_km"] = rng.choice([0.0, -1.0, -3.5], len(parts[1]))
    df.loc[parts[2], "vehicle_type"] = df.loc[parts[2], "vehicle_type"].str.upper() + " "
    df.loc[parts[3], "duration_min"] = rng.uniform(400, 900, len(parts[3]))
    df.loc[parts[4], "pickup_zone"] = np.nan
    df = pd.concat([df, df.sample(int(k * 0.003), random_state=SEED)]).reset_index(drop=True)

    df.to_csv(RAW_CSV, index=False)
    shares = pd.Series(vehicle).value_counts(normalize=True).round(3).to_dict()
    print(f"Days simulated: {len(days)} ({START_DATE} .. {END_DATE}), rainy days: {int(day_rain.sum())}")
    print(f"Raw rows written: {len(df):,} (incl. injected dirty/duplicate rows)")
    print(f"Mode shares: {shares}")
    print(f"Saved: {RAW_CSV}")
    print(f"\nStage 0 completed in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
