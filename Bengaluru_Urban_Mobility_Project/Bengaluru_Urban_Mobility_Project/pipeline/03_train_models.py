"""
STAGE 3 — MACHINE LEARNING
Bengaluru Multi-Modal Urban Mobility Analytics (CA3 Activity 2)

Trains the two models the dashboard serves:

  Model A (Regression)      -> predicts trip duration (minutes) for a
                                vehicle type, distance, time and traffic
                                level. Fares are then computed from the
                                predicted duration with the bike / auto /
                                cab rate cards (pipeline/mobility_model.py).
  Model B (Classification)  -> predicts zone demand level (Low/Medium/High)
                                for a date+hour+zone cell, using the output
                                of MapReduce Job 4. Feeds surge pricing.

Saves both models + their metrics/feature lists to models/, which the
Flask backend loads at startup to serve live predictions.

Run:
  python pipeline/03_train_models.py
"""

import json
import os
import sys
import time

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    mean_absolute_error,
    r2_score,
)
from sklearn.model_selection import train_test_split
import joblib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mobility_model as mm  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
MODELS_DIR = os.path.join(BASE_DIR, "models")
CLEANED_CSV = os.path.join(OUTPUT_DIR, "cleaned_bengaluru_mobility.csv")
JOB4_CSV = os.path.join(OUTPUT_DIR, "mapreduce", "job4_demand_dataset.csv")

os.makedirs(MODELS_DIR, exist_ok=True)

# Cap training set size so this runs in reasonable time on a laptop.
MAX_TRAINING_ROWS = 300_000
RANDOM_STATE = 42

DURATION_FEATURES = [
    "vehicle_type_encoded", "distance_km", "hour", "day_of_week",
    "traffic_factor", "is_raining",
]
DEMAND_FEATURES = [
    "hour", "day_of_week", "is_weekend", "is_peak_hour", "zone_code", "is_raining",
]


def train_duration_model():
    print("=" * 70)
    print("MODEL A: TRIP DURATION PREDICTION (Regression, all 3 vehicle types)")
    print("=" * 70)

    df = pd.read_csv(CLEANED_CSV)
    if len(df) > MAX_TRAINING_ROWS:
        df = df.sample(MAX_TRAINING_ROWS, random_state=RANDOM_STATE)
    print(f"Training rows: {len(df):,}")

    df["vehicle_type_encoded"] = df["vehicle_type"].map(mm.VEHICLE_CODE)
    X = df[DURATION_FEATURES]
    y = df["duration_min"]
    # Physics-informed target: the forest learns actual / physics-ETA. Trees
    # can't extrapolate, and long bike/auto trips (e.g. to the airport) are
    # rare, so a raw-minutes target collapses all vehicles to the same ETA
    # there. Multiplying the learned ratio back onto the physics ETA keeps
    # predictions scaling correctly with distance for every vehicle.
    physics_eta = pd.Series(
        mm.expected_duration_minutes(df["vehicle_type"].values, df["distance_km"].values,
                                     df["traffic_factor"].values, df["is_raining"].values),
        index=df.index,
    )

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=RANDOM_STATE
    )

    model = RandomForestRegressor(
        n_estimators=80, max_depth=12, min_samples_leaf=5,
        n_jobs=-1, random_state=RANDOM_STATE
    )
    t0 = time.time()
    model.fit(X_train, y_train / physics_eta[X_train.index])
    print(f"Trained in {time.time() - t0:.1f}s")

    pred = model.predict(X_test) * physics_eta[X_test.index].values
    mae = mean_absolute_error(y_test, pred)
    r2 = r2_score(y_test, pred)
    physics_mae = mean_absolute_error(y_test, physics_eta[X_test.index])
    print(f"MAE: {mae:.2f} min   R2: {r2:.4f}   (physics formula alone: MAE {physics_mae:.2f} min)")

    test = X_test.assign(actual=y_test.values, pred=pred)
    per_vehicle = {
        v: round(float(mean_absolute_error(g["actual"], g["pred"])), 3)
        for v, g in ((v, test[test["vehicle_type_encoded"] == c]) for v, c in mm.VEHICLE_CODE.items())
    }
    print(f"MAE by vehicle: {per_vehicle}")

    joblib.dump(
        model, os.path.join(MODELS_DIR, "trip_duration_model.joblib"), compress=3
    )

    metrics = {
        "features": DURATION_FEATURES,
        "target": "duration_min / physics_eta (prediction = model output x mobility_model.expected_duration_minutes)",
        "vehicle_encoding": mm.VEHICLE_CODE,
        "mae_minutes": round(mae, 3),
        "physics_only_mae_minutes": round(physics_mae, 3),
        "mae_minutes_by_vehicle": per_vehicle,
        "r2_score": round(r2, 4),
        "feature_importance": dict(zip(DURATION_FEATURES, model.feature_importances_.round(4).tolist())),
        "training_rows": len(df),
    }
    with open(os.path.join(MODELS_DIR, "trip_duration_metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2)

    return metrics


def train_demand_model():
    print("\n" + "=" * 70)
    print("MODEL B: ZONE DEMAND LEVEL / SURGE PREDICTION (Classification)")
    print("=" * 70)

    if not os.path.exists(JOB4_CSV):
        raise FileNotFoundError(f"{JOB4_CSV} not found. Run pipeline/02_run_mapreduce.py first.")

    df = pd.read_csv(JOB4_CSV)
    print(f"Demand cells (from MapReduce Job 4): {len(df):,}")

    df["zone_code"] = df["pickup_zone"].map(mm.ZONE_INDEX)
    df = df.dropna(subset=["zone_code"])
    df["is_weekend"] = df["day_of_week"].isin([5, 6]).astype(int)
    # An hour counts as peak if its midpoint falls inside a peak window.
    df["is_peak_hour"] = mm.is_peak(df["hour"] + 0.5).astype(int)

    q33 = df["trip_demand"].quantile(0.33)
    q66 = df["trip_demand"].quantile(0.66)

    def classify(v):
        if v <= q33:
            return "Low"
        if v <= q66:
            return "Medium"
        return "High"

    df["demand_level"] = df["trip_demand"].apply(classify)
    print("Demand level distribution:")
    print(df["demand_level"].value_counts())

    X = df[DEMAND_FEATURES]
    y = df["demand_level"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=RANDOM_STATE, stratify=y
    )

    model = RandomForestClassifier(
        n_estimators=80, max_depth=12, min_samples_leaf=5,
        n_jobs=-1, random_state=RANDOM_STATE
    )
    t0 = time.time()
    model.fit(X_train, y_train)
    print(f"Trained in {time.time() - t0:.1f}s")

    pred = model.predict(X_test)
    acc = accuracy_score(y_test, pred)
    f1 = f1_score(y_test, pred, average="weighted")
    print(f"Accuracy: {acc:.4f}   Weighted F1: {f1:.4f}")

    joblib.dump(
        model, os.path.join(MODELS_DIR, "demand_level_model.joblib"), compress=3
    )

    metrics = {
        "features": DEMAND_FEATURES,
        "zone_encoding": mm.ZONE_INDEX,
        "accuracy": round(acc, 4),
        "f1_weighted": round(f1, 4),
        "thresholds": {"q33": round(float(q33), 2), "q66": round(float(q66), 2)},
        "class_counts": {k: int(v) for k, v in df["demand_level"].value_counts().items()},
        "training_rows": len(df),
    }
    with open(os.path.join(MODELS_DIR, "demand_level_metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2)

    return metrics


def main():
    duration_metrics = train_duration_model()
    demand_metrics = train_demand_model()

    print("\n" + "=" * 70)
    print("STAGE 3 COMPLETE")
    print("=" * 70)
    print(json.dumps({"duration_model": duration_metrics, "demand_model": demand_metrics}, indent=2))


if __name__ == "__main__":
    main()
