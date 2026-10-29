"""
STAGE 1 — DATA CLEANING + FEATURE ENGINEERING
Bengaluru Multi-Modal Urban Mobility Analytics (CA3 Activity 2)

Reads the raw multi-modal trip file from Stage 0 and produces:

  outputs/cleaned_bengaluru_mobility.csv -> full cleaned dataset (ML + analytics)
  outputs/mapreduce_input.tsv            -> header-less TSV, fixed columns (see
                                            pipeline/schema.py), the input to
                                            the MapReduce jobs in Stage 2.

Run:
  python pipeline/01_clean_and_engineer.py
"""

import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mobility_model as mm  # noqa: E402
from schema import MR_INPUT_COLUMNS  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
RAW_CSV = os.path.join(OUTPUT_DIR, "bengaluru_mobility_raw.csv")
CLEANED_CSV = os.path.join(OUTPUT_DIR, "cleaned_bengaluru_mobility.csv")
MR_INPUT_TSV = os.path.join(OUTPUT_DIR, "mapreduce_input.tsv")

os.makedirs(OUTPUT_DIR, exist_ok=True)


def time_period(hour):
    if 5 <= hour < 12:
        return "Morning"
    if 12 <= hour < 17:
        return "Afternoon"
    if 17 <= hour < 22:
        return "Evening"
    return "Night"


def distance_category(km):
    if km < 3:
        return "Short"
    if km < 8:
        return "Medium"
    if km < 15:
        return "Long"
    return "Very Long"


def main():
    t0 = time.time()
    print("=" * 70)
    print("STAGE 1: DATA CLEANING & FEATURE ENGINEERING")
    print("=" * 70)

    if not os.path.exists(RAW_CSV):
        raise FileNotFoundError(f"{RAW_CSV} not found. Run pipeline/00_generate_bengaluru_data.py first.")

    df = pd.read_csv(RAW_CSV)
    print(f"Loaded raw data: {len(df):,} rows, {len(df.columns)} columns")

    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")

    before = len(df)
    df = df.drop_duplicates().reset_index(drop=True)
    print(f"Duplicates removed: {before - len(df):,}")

    df["vehicle_type"] = df["vehicle_type"].astype(str).str.strip().str.lower()
    before = len(df)
    df = df[df["vehicle_type"].isin(mm.VEHICLES)].copy()
    print(f"Vehicle names normalised (case/whitespace); unknown types removed: {before - len(df):,}")

    before = len(df)
    df = df.dropna(subset=["pickup_zone", "dropoff_zone"])
    df = df[df["pickup_zone"].isin(mm.ZONE_NAMES) & df["dropoff_zone"].isin(mm.ZONE_NAMES)].copy()
    print(f"Rows with missing/unknown zones removed: {before - len(df):,}")

    df["pickup_datetime"] = pd.to_datetime(df["pickup_datetime"], errors="coerce")
    df["dropoff_datetime"] = pd.to_datetime(df["dropoff_datetime"], errors="coerce")
    before = len(df)
    df = df.dropna(subset=["pickup_datetime", "dropoff_datetime"]).copy()
    print(f"Invalid datetime rows removed: {before - len(df):,}")

    before = len(df)
    df = df[df["distance_km"].notna() & (df["distance_km"] > 0)].copy()
    print(f"Zero/negative distance rows removed: {before - len(df):,}")

    # Duration must agree with the timestamps; corrupted durations don't.
    ts_minutes = (df["dropoff_datetime"] - df["pickup_datetime"]).dt.total_seconds() / 60
    before = len(df)
    df = df[(df["duration_min"] > 0) & ((df["duration_min"] - ts_minutes).abs() <= 1)].copy()
    print(f"Durations inconsistent with timestamps removed: {before - len(df):,}")

    df["hour"] = df["pickup_datetime"].dt.hour
    hour_frac = df["hour"] + df["pickup_datetime"].dt.minute / 60
    df["day_of_week"] = df["pickup_datetime"].dt.dayofweek
    df["day_name"] = df["pickup_datetime"].dt.day_name()
    df["pickup_date"] = df["pickup_datetime"].dt.date.astype(str)
    df["month"] = df["pickup_datetime"].dt.month
    df["is_weekend"] = df["day_of_week"].isin([5, 6]).astype(int)
    df["is_peak_hour"] = mm.is_peak(hour_frac).astype(int)
    df["is_night"] = mm.is_night(hour_frac).astype(int)
    df["time_period"] = df["hour"].apply(time_period)
    df["day_type"] = np.where(df["is_weekend"] == 1, "Weekend", "Weekday")

    pu = df["pickup_zone"].map(mm.ZONE_INDEX).values
    do = df["dropoff_zone"].map(mm.ZONE_INDEX).values
    df["traffic_factor"] = mm.traffic_factor(hour_frac, df["day_of_week"].values, pu, do, df["is_raining"].values)
    df["traffic_level"] = mm.traffic_level(df["traffic_factor"])
    df["free_flow_min"] = np.round(mm.free_flow_minutes(df["vehicle_type"].values, df["distance_km"].values), 2)
    df["delay_min"] = np.round(np.maximum(df["duration_min"] - df["free_flow_min"], 0), 2)
    df["avg_speed_kmph"] = np.round(df["distance_km"] / (df["duration_min"] / 60), 2)
    df["corridor"] = df["pickup_zone"] + " → " + df["dropoff_zone"]

    # Missing fares are recomputed from the published rate card (imputation
    # by business rule rather than by median — the rule is known exactly).
    missing_fare = df["fare_inr"].isna()
    if missing_fare.any():
        sub = df[missing_fare]
        df.loc[missing_fare, "fare_inr"] = mm.fare_breakdown(
            sub["vehicle_type"].values, sub["distance_km"].values, sub["duration_min"].values,
            sub["traffic_factor"].values, hour_frac[missing_fare].values, sub["surge_multiplier"].values,
        )["total"]
    print(f"Missing fares imputed from rate card: {int(missing_fare.sum()):,}")

    upper = df["duration_min"].quantile(0.999)
    before = len(df)
    df = df[df["duration_min"] <= upper].copy()
    print(f"Extreme outlier rows removed (>99.9th pct duration, {upper:.0f} min): {before - len(df):,}")

    df["distance_category"] = df["distance_km"].apply(distance_category)
    df["fare_per_km"] = np.round(df["fare_inr"] / df["distance_km"], 2)
    df["fare_per_min"] = np.round(df["fare_inr"] / df["duration_min"], 2)

    df = df.sort_values("pickup_datetime").reset_index(drop=True)

    print(f"\nFinal cleaned dataset: {len(df):,} rows, {len(df.columns)} columns")
    df.to_csv(CLEANED_CSV, index=False)
    print(f"Saved: {CLEANED_CSV}")

    df[MR_INPUT_COLUMNS].to_csv(MR_INPUT_TSV, sep="\t", index=False, header=False)
    print(f"Saved MapReduce input: {MR_INPUT_TSV}")

    print(f"\nStage 1 completed in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
