"""
STAGE 4 — PRECOMPUTE DASHBOARD DATA
Bengaluru Multi-Modal Urban Mobility Analytics (CA3 Activity 2)

Builds a single small JSON file (outputs/dashboard_data.json) holding
everything the front end needs, split by role:

  common  -> zones, vehicles, rate cards, headline KPIs, model metrics
  user    -> fare/ETA by vehicle and distance, surge by hour, best travel times
  driver  -> zone x hour demand, earning windows, yield matrix, top corridors
  admin   -> throughput, mode share, revenue, congestion, MapReduce outputs

Keeping the Flask app off the 250k-row CSV at request time is what makes
the dashboard load instantly.

Run:
  python pipeline/04_precompute_dashboard.py
"""

import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mobility_model as mm  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
MR_DIR = os.path.join(OUTPUT_DIR, "mapreduce")
MODELS_DIR = os.path.join(BASE_DIR, "models")
CLEANED_CSV = os.path.join(OUTPUT_DIR, "cleaned_bengaluru_mobility.csv")

DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
HOURS = list(range(24))
DURATION_BUCKETS = [0, 15, 30, 60, np.inf]
DURATION_LABELS = ["< 15 min", "15-30 min", "30-60 min", "60+ min"]


def records(frame, decimals=2):
    return json.loads(frame.round(decimals).to_json(orient="records"))


def per_vehicle_by_hour(frame, value):
    """{vehicle: [24 values]} from a frame with hour, vehicle_type, value columns."""
    wide = frame.pivot(index="hour", columns="vehicle_type", values=value).reindex(HOURS).fillna(0)
    return {v: wide[v].round(2).tolist() for v in mm.VEHICLES}


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    df = pd.read_csv(CLEANED_CSV)
    print(f"Loaded cleaned dataset: {len(df):,} rows")
    n_days = df["pickup_date"].nunique()

    job1 = pd.read_csv(os.path.join(MR_DIR, "job1_modal_demand_by_hour.csv"))
    job2 = pd.read_csv(os.path.join(MR_DIR, "job2_avg_duration_and_fare_by_zone.csv"))
    job3 = pd.read_csv(os.path.join(MR_DIR, "job3_top_congestion_corridors.csv")).sort_values("avg_speed_kmph")
    job4 = pd.read_csv(os.path.join(MR_DIR, "job4_demand_dataset.csv"))

    duration_metrics = load_json(os.path.join(MODELS_DIR, "trip_duration_metrics.json"))
    demand_metrics = load_json(os.path.join(MODELS_DIR, "demand_level_metrics.json"))

    # ------------------------------------------------------------------ common
    hourly_total = job1.groupby("hour")["total_trips"].sum()
    zone_trips = job2.groupby("pickup_zone")["trip_count"].sum()
    kpis = {
        "total_trips": int(len(df)),
        "total_revenue_inr": round(float(df["fare_inr"].sum()), 0),
        "avg_fare_inr": round(float(df["fare_inr"].mean()), 2),
        "avg_duration_min": round(float(df["duration_min"].mean()), 2),
        "avg_distance_km": round(float(df["distance_km"].mean()), 2),
        "avg_speed_kmph": round(float(df["distance_km"].sum() / (df["duration_min"].sum() / 60)), 2),
        "avg_surge": round(float(df["surge_multiplier"].mean()), 2),
        "peak_trip_share": round(float(df["is_peak_hour"].mean()), 3),
        "peak_hour": int(hourly_total.idxmax()),
        "busiest_zone": str(zone_trips.idxmax()),
        "busiest_day": str(df["day_name"].value_counts().idxmax()),
        "critical_corridors": int((job3["bottleneck_status"] == "CRITICAL").sum()),
        "days_covered": int(n_days),
        "date_range": {"start": str(df["pickup_datetime"].min()), "end": str(df["pickup_datetime"].max())},
    }

    common = {
        "kpis": kpis,
        "zones": [{k: z[k] for k in ("name", "lat", "lon", "kind")} for z in mm.ZONES],
        "vehicles": mm.VEHICLES,
        "fare_rules": mm.FARE_RULES,
        "night_surcharge": mm.NIGHT_SURCHARGE,
        "models": {"duration": duration_metrics, "demand": demand_metrics},
        "data_note": "Synthetic dataset generated from documented Bengaluru traffic and fare patterns "
                     "(pipeline/00_generate_bengaluru_data.py).",
    }

    # ------------------------------------------------------------------ user
    by_vehicle_dist = (
        df.groupby(["distance_category", "vehicle_type"])
        .agg(avg_fare_inr=("fare_inr", "mean"), avg_duration_min=("duration_min", "mean"), trips=("trip_id", "count"))
        .reset_index()
    )
    surge_by_hour = (
        df.groupby(["day_type", "hour"])["surge_multiplier"].mean().unstack(0).reindex(HOURS)
    )
    min_per_km = (
        df.assign(min_per_km=df["duration_min"] / df["distance_km"])
        .groupby(["hour", "vehicle_type"])["min_per_km"].mean().reset_index()
    )
    # Average trips per hour in each zone, from MapReduce Job 4 (zero cells included).
    zone_hour = (
        job4.groupby(["pickup_zone", "hour"])["trip_demand"].sum().unstack(fill_value=0)
        .reindex(index=mm.ZONE_NAMES, columns=HOURS, fill_value=0) / n_days
    )
    zone_hour_demand = {"zones": mm.ZONE_NAMES, "hours": HOURS, "matrix": zone_hour.round(2).values.tolist()}

    user = {
        "zone_hour_demand": zone_hour_demand,
        "estimates_by_distance": records(by_vehicle_dist),
        "distance_categories": ["Short", "Medium", "Long", "Very Long"],
        "surge_by_hour": {
            "weekday": surge_by_hour["Weekday"].round(2).tolist(),
            "weekend": surge_by_hour["Weekend"].round(2).tolist(),
        },
        "minutes_per_km_by_hour": per_vehicle_by_hour(min_per_km, "min_per_km"),
    }

    # ------------------------------------------------------------------ driver
    zone_hour_fare = (
        df.groupby(["pickup_zone", "hour"])["fare_inr"].mean().unstack()
        .reindex(index=mm.ZONE_NAMES, columns=HOURS).fillna(0)
    )
    fare_per_min_by_hour = df.groupby(["hour", "vehicle_type"])["fare_per_min"].mean().reset_index()
    demand_per_hour = job1.assign(trips_per_day=job1["total_trips"] / n_days)
    df["duration_bucket"] = pd.cut(df["duration_min"], DURATION_BUCKETS, labels=DURATION_LABELS, right=False)
    yield_matrix = (
        df.groupby(["duration_bucket", "vehicle_type"], observed=True)["fare_per_min"].mean().unstack()
        .reindex(index=DURATION_LABELS, columns=mm.VEHICLES)
    )
    corridors = (
        df[df["pickup_zone"] != df["dropoff_zone"]]
        .groupby(["vehicle_type", "pickup_zone", "dropoff_zone"])
        .agg(trips=("trip_id", "count"), avg_fare_inr=("fare_inr", "mean"),
             avg_duration_min=("duration_min", "mean"), fare_per_min=("fare_per_min", "mean"))
        .reset_index()
    )
    corridors = corridors[corridors["trips"] >= 150]
    top_corridors = {
        v: records(g.sort_values("fare_per_min", ascending=False).head(8).drop(columns="vehicle_type"))
        for v, g in corridors.groupby("vehicle_type")
    }
    driver = {
        "zone_hour_demand": zone_hour_demand,
        "zone_hour_avg_fare": zone_hour_fare.round(0).values.tolist(),
        "fare_per_min_by_hour": per_vehicle_by_hour(fare_per_min_by_hour, "fare_per_min"),
        "trips_per_day_by_hour": per_vehicle_by_hour(demand_per_hour, "trips_per_day"),
        "yield_matrix": {
            "buckets": DURATION_LABELS, "vehicles": mm.VEHICLES,
            "values": yield_matrix.round(2).values.tolist(),
        },
        "top_corridors": top_corridors,
    }

    # ------------------------------------------------------------------ admin
    mode = (
        df.groupby("vehicle_type")
        .agg(trips=("trip_id", "count"), revenue_inr=("fare_inr", "sum"), avg_fare_inr=("fare_inr", "mean"),
             avg_duration_min=("duration_min", "mean"), avg_distance_km=("distance_km", "mean"),
             distance_km=("distance_km", "sum"), duration_min=("duration_min", "sum"))
        .reindex(mm.VEHICLES).reset_index()
    )
    mode["avg_speed_kmph"] = mode["distance_km"] / (mode["duration_min"] / 60)
    mode["share"] = mode["trips"] / mode["trips"].sum()
    mode = mode.drop(columns=["distance_km", "duration_min"])

    revenue_by_zone = (
        job2.pivot(index="pickup_zone", columns="vehicle_type", values="total_fare_inr")
        .reindex(index=mm.ZONE_NAMES, columns=mm.VEHICLES).fillna(0)
    )
    congestion = df.groupby(["day_type", "hour"])["traffic_factor"].mean().unstack(0).reindex(HOURS)
    speed_by_hour = (
        df.groupby(["hour", "vehicle_type"]).agg(km=("distance_km", "sum"), mins=("duration_min", "sum")).reset_index()
    )
    speed_by_hour["speed"] = speed_by_hour["km"] / (speed_by_hour["mins"] / 60)
    rain = (
        df.assign(min_per_km=df["duration_min"] / df["distance_km"])
        .groupby(["vehicle_type", "is_raining"])["min_per_km"].mean().unstack()
        .reindex(mm.VEHICLES)
    )
    heatmap = df.groupby(["day_name", "hour"]).size().unstack(fill_value=0).reindex(DAY_ORDER)
    traffic_mix = df["traffic_level"].value_counts().reindex(["low", "med", "high"]).fillna(0).astype(int)

    admin = {
        "mode_share": records(mode, 3),
        "revenue_by_zone": {
            "zones": mm.ZONE_NAMES,
            "by_vehicle": {v: revenue_by_zone[v].round(0).tolist() for v in mm.VEHICLES},
        },
        "congestion_by_hour": {
            "weekday": congestion["Weekday"].round(3).tolist(),
            "weekend": congestion["Weekend"].round(3).tolist(),
        },
        "speed_by_hour": per_vehicle_by_hour(speed_by_hour, "speed"),
        "rain_impact_min_per_km": {
            "vehicles": mm.VEHICLES,
            "dry": rain[0].round(2).tolist(),
            "rain": rain[1].round(2).tolist(),
        },
        "traffic_level_mix": {k: int(v) for k, v in traffic_mix.items()},
        "heatmap": {
            "days": DAY_ORDER, "hours": HOURS,
            "matrix": heatmap.reindex(columns=HOURS, fill_value=0).values.tolist(),
        },
        "mapreduce": {
            "job1_modal_demand_by_hour": {
                "rows": len(job1), "hours": HOURS,
                "by_vehicle": {v: job1[job1["vehicle_type"] == v].set_index("hour")["total_trips"]
                               .reindex(HOURS, fill_value=0).astype(int).tolist() for v in mm.VEHICLES},
            },
            "job2_avg_duration_and_fare_by_zone": records(job2),
            "job3_top_congestion_corridors": records(job3, 3),
            "job4_demand_dataset": {
                "rows": len(job4),
                "sample": records(job4.sort_values("trip_demand", ascending=False).head(12)),
                "thresholds": demand_metrics["thresholds"],
                "class_counts": demand_metrics["class_counts"],
            },
        },
    }

    data = {"common": common, "user": user, "driver": driver, "admin": admin}
    out_path = os.path.join(OUTPUT_DIR, "dashboard_data.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, default=str, ensure_ascii=False)

    print(f"Saved: {out_path} ({os.path.getsize(out_path) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
