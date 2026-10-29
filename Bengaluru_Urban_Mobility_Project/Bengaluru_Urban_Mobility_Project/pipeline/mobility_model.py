"""
Shared Bengaluru mobility "physics": zones, traffic curve, vehicle speeds,
fare rules and surge. One source of truth used by:

  pipeline/00_generate_bengaluru_data.py   (to synthesise trips)
  backend/app.py                           (to price live predictions)

so a fare quoted in the dashboard is computed exactly like the fares in
the dataset. Every function accepts scalars or numpy arrays.
"""

import numpy as np

# ---------------------------------------------------------------------------
# Zones (pickup / drop hubs). choke = how badly the zone's approach roads
# amplify peak congestion (Silk Board / ORR / Hebbal flyover > highway).
# kind drives the hour-of-day demand pattern in the generator.
# ---------------------------------------------------------------------------
ZONES = [
    {"name": "Indiranagar",            "lat": 12.9784, "lon": 77.6408, "pop": 1.10, "choke": 1.05, "kind": "mixed"},
    {"name": "Koramangala",            "lat": 12.9352, "lon": 77.6245, "pop": 1.25, "choke": 1.10, "kind": "mixed"},
    {"name": "Whitefield",             "lat": 12.9698, "lon": 77.7500, "pop": 1.05, "choke": 1.18, "kind": "tech"},
    {"name": "HSR Layout",             "lat": 12.9116, "lon": 77.6474, "pop": 0.95, "choke": 1.10, "kind": "residential"},
    {"name": "Electronic City",        "lat": 12.8452, "lon": 77.6602, "pop": 0.90, "choke": 1.15, "kind": "tech"},
    {"name": "MG Road",                "lat": 12.9756, "lon": 77.6050, "pop": 1.00, "choke": 1.05, "kind": "mixed"},
    {"name": "Hebbal",                 "lat": 13.0358, "lon": 77.5970, "pop": 0.75, "choke": 1.12, "kind": "residential"},
    {"name": "Kempegowda Airport (BLR)", "lat": 13.1989, "lon": 77.7068, "pop": 0.55, "choke": 0.85, "kind": "transit"},
    {"name": "Majestic (KSR Station)", "lat": 12.9767, "lon": 77.5713, "pop": 0.85, "choke": 1.12, "kind": "transit"},
    {"name": "Jayanagar",              "lat": 12.9250, "lon": 77.5938, "pop": 0.80, "choke": 1.00, "kind": "residential"},
]
ZONE_NAMES = [z["name"] for z in ZONES]
ZONE_INDEX = {z["name"]: i for i, z in enumerate(ZONES)}
ZONE_CHOKE = np.array([z["choke"] for z in ZONES])

VEHICLES = ["bike", "auto", "cab"]
VEHICLE_CODE = {v: i for i, v in enumerate(VEHICLES)}

# Road distance is longer than straight-line distance.
ROAD_CIRCUITY = 1.32
INTRA_ZONE_DEFAULT_KM = 3.0

# Free-flow speed (km/h), how much of the congestion each mode "feels",
# speed retained in rain, and fixed in-trip overhead (signals, pickup).
FREE_FLOW_KMPH = {"bike": 27.0, "auto": 24.0, "cab": 28.0}
CONGESTION_SENSITIVITY = {"bike": 0.55, "auto": 0.80, "cab": 1.00}
RAIN_SPEED_RETAINED = {"bike": 0.75, "auto": 0.90, "cab": 0.95}
OVERHEAD_MIN = {"bike": 1.0, "auto": 1.5, "cab": 2.0}

# Fare rules (INR).
FARE_RULES = {
    "bike": {"base": 20.0, "included_km": 2.0, "per_km": 8.0,  "per_min_delay": 1.5},
    "auto": {"base": 30.0, "included_km": 1.8, "per_km": 15.0, "per_min_delay": 2.0},
    "cab":  {"base": 60.0, "included_km": 3.0, "per_km": 18.0, "per_min_delay": 3.0},  # per_km rises to 22 in heavy traffic
}
CAB_PER_KM_MAX = 22.0
# Late-night (22:00-06:00) surcharge. Auto mirrors Bengaluru's 1.5x night meter.
NIGHT_SURCHARGE = {"bike": 1.2, "auto": 1.5, "cab": 1.2}

SURGE_BY_DEMAND = {"Low": 1.0, "Medium": 1.1, "High": 1.3}
SURGE_MIN, SURGE_MAX = 1.0, 2.2


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return R * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def zone_road_distance_km(pickup_zone, dropoff_zone):
    """Typical road distance between two hubs (used when the user gives none)."""
    if pickup_zone == dropoff_zone:
        return INTRA_ZONE_DEFAULT_KM
    a, b = ZONES[ZONE_INDEX[pickup_zone]], ZONES[ZONE_INDEX[dropoff_zone]]
    return float(haversine_km(a["lat"], a["lon"], b["lat"], b["lon"]) * ROAD_CIRCUITY)


# ---------------------------------------------------------------------------
# Traffic
# ---------------------------------------------------------------------------
def is_peak(hour_frac):
    h = np.asarray(hour_frac, dtype=float)
    return ((h >= 8.5) & (h < 11.5)) | ((h >= 17.5) & (h < 21.5))


def is_night(hour_frac):
    h = np.asarray(hour_frac, dtype=float)
    return (h >= 22) | (h < 6)


def base_congestion(hour_frac):
    """City-wide congestion multiplier vs free flow, by time of day.

    Morning peak 08:30-11:30 rises 1.5x -> 2.2x (max ~10:00),
    evening peak 17:30-21:30 rises 1.6x -> 2.4x (max ~19:30),
    night 22:00-06:00 flows faster than free-flow (0.85x).
    """
    h = np.asarray(hour_frac, dtype=float) % 24
    cf = np.full(h.shape, 1.25)                                     # midday plateau
    cf = np.where(is_night(h), 0.85, cf)
    cf = np.where((h >= 6) & (h < 8.5), 0.85 + (h - 6) / 2.5 * 0.65, cf)
    m = (h >= 8.5) & (h < 11.5)
    cf = np.where(m, 1.5 + 0.7 * np.sin(np.pi * (h - 8.5) / 3), cf)
    cf = np.where((h >= 11.5) & (h < 13), 1.5 - (h - 11.5) / 1.5 * 0.25, cf)
    cf = np.where((h >= 16) & (h < 17.5), 1.25 + (h - 16) / 1.5 * 0.35, cf)
    e = (h >= 17.5) & (h < 21.5)
    cf = np.where(e, 1.6 + 0.8 * np.sin(np.pi * (h - 17.5) / 4), cf)
    cf = np.where((h >= 21.5) & (h < 22), 1.6 - (h - 21.5) / 0.5 * 0.75, cf)
    return cf


def traffic_factor(hour_frac, day_of_week, pickup_idx, dropoff_idx, is_raining):
    """Expected congestion factor for a corridor at a time (>1 = slower)."""
    cf = base_congestion(hour_frac)
    weekend = np.isin(np.asarray(day_of_week), [5, 6])
    cf = np.where(weekend & (cf > 1), 1 + (cf - 1) * 0.6, cf)
    choke = (ZONE_CHOKE[np.asarray(pickup_idx)] + ZONE_CHOKE[np.asarray(dropoff_idx)]) / 2
    cf = np.where(cf > 1, 1 + (cf - 1) * choke, cf)
    cf = cf * np.where(np.asarray(is_raining).astype(bool), 1.15, 1.0)
    return np.round(cf, 3)


def traffic_level(tf):
    tf = np.asarray(tf, dtype=float)
    return np.where(tf < 1.2, "low", np.where(tf < 1.7, "med", "high"))


def _per_vehicle(table, vehicle):
    v = np.asarray(vehicle)
    return np.select([v == k for k in VEHICLES], [table[k] for k in VEHICLES], default=np.nan)


def free_flow_minutes(vehicle, distance_km):
    """Trip time with no congestion; longer trips use faster roads."""
    d = np.asarray(distance_km, dtype=float)
    speed = _per_vehicle(FREE_FLOW_KMPH, vehicle) * (1 + 0.3 * np.minimum(d, 30) / 30)
    return d / speed * 60 + _per_vehicle(OVERHEAD_MIN, vehicle)


def expected_duration_minutes(vehicle, distance_km, tf, is_raining):
    """Physics-based ETA (no noise). The ML model learns this + real-world noise."""
    tf = np.asarray(tf, dtype=float)
    sens = _per_vehicle(CONGESTION_SENSITIVITY, vehicle)
    eff = np.where(tf > 1, 1 + (tf - 1) * sens, tf)
    # Cabs can't filter through choke points: extra slowdown in heavy jams.
    eff = eff * np.where((np.asarray(vehicle) == "cab") & (tf > 1.6), 1 + 0.15 * (tf - 1.6), 1.0)
    rain = np.where(np.asarray(is_raining).astype(bool), _per_vehicle(RAIN_SPEED_RETAINED, vehicle), 1.0)
    ff = free_flow_minutes(vehicle, distance_km)
    overhead = _per_vehicle(OVERHEAD_MIN, vehicle)
    return (ff - overhead) * eff / rain + overhead


# ---------------------------------------------------------------------------
# Fares
# ---------------------------------------------------------------------------
def surge_multiplier(demand_level, hour_frac, is_raining):
    """Surge 1.0x-2.2x from zone demand level + peak traffic + rain."""
    lvl = np.asarray(demand_level)
    s = np.select([lvl == k for k in SURGE_BY_DEMAND], list(SURGE_BY_DEMAND.values()), default=1.0)
    s = s + np.where(is_peak(hour_frac), 0.2, 0.0)
    s = s + np.where(np.asarray(is_raining).astype(bool), 0.3, 0.0)
    return np.round(np.clip(s, SURGE_MIN, SURGE_MAX), 2)


def fare_breakdown(vehicle, distance_km, duration_min, tf, hour_frac, surge):
    """Vectorised fare components (INR). Returns a dict of arrays."""
    v = np.asarray(vehicle)
    d = np.asarray(distance_km, dtype=float)
    base = _per_vehicle({k: r["base"] for k, r in FARE_RULES.items()}, v)
    incl = _per_vehicle({k: r["included_km"] for k, r in FARE_RULES.items()}, v)
    per_km = _per_vehicle({k: r["per_km"] for k, r in FARE_RULES.items()}, v)
    # Cab per-km slides 18 -> 22 as traffic worsens.
    tf = np.asarray(tf, dtype=float)
    cab_rate = 18.0 + (CAB_PER_KM_MAX - 18.0) * np.clip((tf - 1) / 1.4, 0, 1)
    per_km = np.where(v == "cab", cab_rate, per_km)
    per_min = _per_vehicle({k: r["per_min_delay"] for k, r in FARE_RULES.items()}, v)

    distance_charge = np.maximum(d - incl, 0) * per_km
    delay_min = np.maximum(np.asarray(duration_min, dtype=float) - free_flow_minutes(v, d), 0)
    delay_charge = delay_min * per_min
    subtotal = base + distance_charge + delay_charge

    night = np.where(is_night(hour_frac), _per_vehicle(NIGHT_SURCHARGE, v), 1.0)
    night_charge = subtotal * (night - 1)
    surge = np.asarray(surge, dtype=float)
    surge_charge = (subtotal + night_charge) * (surge - 1)
    total = subtotal + night_charge + surge_charge
    return {
        "base": base,
        "distance_charge": distance_charge,
        "delay_minutes": delay_min,
        "delay_charge": delay_charge,
        "night_surcharge": night_charge,
        "surge_charge": surge_charge,
        "per_km_rate": per_km,
        "total": np.round(total, 0),
    }
