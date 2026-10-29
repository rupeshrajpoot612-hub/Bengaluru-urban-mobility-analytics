"""
Flask backend for the Bengaluru Multi-Modal Urban Mobility dashboard
(CA3 Activity 2).

Serves:
  GET  /                                  -> dashboard page
  GET  /api/dashboard?role=user|driver|admin
                                          -> precomputed data for that role
                                             (no role = everything)
  GET  /api/health                        -> readiness check (pipeline outputs/models built?)
  POST /api/predict/trip                  -> ETA + Bike/Auto/Cab fare comparison + surge
  POST /api/predict/demand                -> zone demand level (Low/Medium/High) + surge

Run (from the project root, C:\\all\\3 sem\\bda\\a2):
  python backend/app.py
Then open http://127.0.0.1:5000
"""

import datetime as dt
import json
import os
import sys

import joblib
import numpy as np
import pandas as pd
from flask import Flask, jsonify, render_template, request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "pipeline"))
import mobility_model as mm  # noqa: E402

OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
MODELS_DIR = os.path.join(BASE_DIR, "models")
DASHBOARD_JSON = os.path.join(OUTPUT_DIR, "dashboard_data.json")
DURATION_MODEL_PATH = os.path.join(MODELS_DIR, "trip_duration_model.joblib")
DEMAND_MODEL_PATH = os.path.join(MODELS_DIR, "demand_level_model.joblib")
DURATION_METRICS_PATH = os.path.join(MODELS_DIR, "trip_duration_metrics.json")
DEMAND_METRICS_PATH = os.path.join(MODELS_DIR, "demand_level_metrics.json")

ROLES = ("user", "driver", "admin")

app = Flask(__name__)

_dashboard_data = None
_duration_model = None
_demand_model = None
_duration_metrics = None
_demand_metrics = None


def _load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_artifacts():
    global _dashboard_data, _duration_model, _demand_model, _duration_metrics, _demand_metrics

    _dashboard_data = _load_json(DASHBOARD_JSON)
    _duration_metrics = _load_json(DURATION_METRICS_PATH)
    _demand_metrics = _load_json(DEMAND_METRICS_PATH)

    if os.path.exists(DURATION_MODEL_PATH):
        _duration_model = joblib.load(DURATION_MODEL_PATH)
    if os.path.exists(DEMAND_MODEL_PATH):
        _demand_model = joblib.load(DEMAND_MODEL_PATH)


load_artifacts()


class BadRequest(ValueError):
    pass


def _parse_common(body):
    """Validates the fields shared by both predict endpoints."""
    try:
        hour = int(body["hour"])
        minute = int(body.get("minute", 0) or 0)
        day_of_week = body.get("day_of_week")
        day_of_week = dt.date.today().weekday() if day_of_week in (None, "") else int(day_of_week)
        is_raining = 1 if str(body.get("is_raining", 0)).lower() in ("1", "true", "on", "yes") else 0
    except (KeyError, ValueError, TypeError) as exc:
        raise BadRequest(f"Invalid or missing field: {exc}")
    if not (0 <= hour <= 23):
        raise BadRequest("hour must be 0-23")
    if not (0 <= minute <= 59):
        raise BadRequest("minute must be 0-59")
    if not (0 <= day_of_week <= 6):
        raise BadRequest("day_of_week must be 0 (Mon) - 6 (Sun)")
    return hour, minute, day_of_week, is_raining


def _zone(body, field):
    name = body.get(field)
    if name not in mm.ZONE_INDEX:
        raise BadRequest(f"{field} must be one of: {', '.join(mm.ZONE_NAMES)}")
    return name


def _demand_level(zone, hour, day_of_week, is_raining):
    """Model B: zone demand level + class probabilities."""
    row = pd.DataFrame([{
        "hour": hour,
        "day_of_week": day_of_week,
        "is_weekend": int(day_of_week in (5, 6)),
        "is_peak_hour": int(mm.is_peak(hour + 0.5)),
        "zone_code": mm.ZONE_INDEX[zone],
        "is_raining": is_raining,
    }])[_demand_metrics["features"]]
    label = str(_demand_model.predict(row)[0])
    probs = dict(zip(_demand_model.classes_, _demand_model.predict_proba(row)[0].round(3)))
    return label, {str(k): float(v) for k, v in probs.items()}


@app.errorhandler(BadRequest)
def handle_bad_request(exc):
    return jsonify({"error": str(exc)}), 400


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health")
def health():
    return jsonify({
        "dashboard_data_ready": _dashboard_data is not None,
        "duration_model_ready": _duration_model is not None,
        "demand_model_ready": _demand_model is not None,
    })


@app.route("/api/dashboard")
def dashboard():
    if _dashboard_data is None:
        return jsonify({
            "error": "Dashboard data not found. Run: python pipeline/run_all.py"
        }), 503
    role = request.args.get("role")
    if role is None:
        return jsonify(_dashboard_data)
    if role not in ROLES:
        return jsonify({"error": f"role must be one of: {', '.join(ROLES)}"}), 400
    return jsonify({"role": role, "common": _dashboard_data["common"], role: _dashboard_data[role]})


@app.route("/api/predict/trip", methods=["POST"])
def predict_trip():
    if _duration_model is None or _demand_model is None:
        return jsonify({"error": "Models not trained yet. Run: python pipeline/run_all.py"}), 503

    body = request.get_json(force=True, silent=True) or {}
    hour, minute, day_of_week, is_raining = _parse_common(body)
    pickup, dropoff = _zone(body, "pickup_zone"), _zone(body, "dropoff_zone")

    distance_given = body.get("distance_km") not in (None, "")
    try:
        distance = float(body["distance_km"]) if distance_given else mm.zone_road_distance_km(pickup, dropoff)
    except (ValueError, TypeError):
        raise BadRequest("distance_km must be a number")
    if not (0.3 <= distance <= 80):
        raise BadRequest("distance_km must be between 0.3 and 80")

    selected = body.get("vehicle_type") or None
    if selected is not None and selected not in mm.VEHICLES:
        raise BadRequest(f"vehicle_type must be one of: {', '.join(mm.VEHICLES)}")

    hour_frac = hour + minute / 60
    tf = float(mm.traffic_factor(hour_frac, day_of_week, mm.ZONE_INDEX[pickup], mm.ZONE_INDEX[dropoff], is_raining))
    demand_level, demand_probs = _demand_level(pickup, hour, day_of_week, is_raining)
    surge = float(mm.surge_multiplier(demand_level, hour_frac, is_raining))

    # Model A: one row per vehicle type, same trip.
    X = pd.DataFrame([{
        "vehicle_type_encoded": mm.VEHICLE_CODE[v],
        "distance_km": distance,
        "hour": hour,
        "day_of_week": day_of_week,
        "traffic_factor": tf,
        "is_raining": is_raining,
    } for v in mm.VEHICLES])[_duration_metrics["features"]]
    # Model A predicts actual / physics ETA (see pipeline/03_train_models.py).
    physics_eta = mm.expected_duration_minutes(np.array(mm.VEHICLES), np.full(3, distance), np.full(3, tf),
                                               np.full(3, is_raining))
    eta = _duration_model.predict(X) * physics_eta
    fares = mm.fare_breakdown(np.array(mm.VEHICLES), np.full(3, distance), eta, np.full(3, tf),
                              np.full(3, hour_frac), np.full(3, surge))

    options = []
    for i, v in enumerate(mm.VEHICLES):
        options.append({
            "vehicle_type": v,
            "eta_min": round(float(eta[i]), 1),
            "fare_inr": int(fares["total"][i]),
            "breakdown": {
                "base": round(float(fares["base"][i]), 2),
                "distance_charge": round(float(fares["distance_charge"][i]), 2),
                "per_km_rate": round(float(fares["per_km_rate"][i]), 2),
                "delay_minutes": round(float(fares["delay_minutes"][i]), 1),
                "delay_charge": round(float(fares["delay_charge"][i]), 2),
                "night_surcharge": round(float(fares["night_surcharge"][i]), 2),
                "surge_charge": round(float(fares["surge_charge"][i]), 2),
            },
            "model_mae_min": _duration_metrics["mae_minutes_by_vehicle"].get(v),
        })

    return jsonify({
        "pickup_zone": pickup,
        "dropoff_zone": dropoff,
        "distance_km": round(distance, 2),
        "distance_source": "user" if distance_given else "estimated from zones",
        "hour": hour,
        "minute": minute,
        "day_of_week": day_of_week,
        "is_raining": is_raining,
        "is_peak_hour": bool(mm.is_peak(hour_frac)),
        "is_night": bool(mm.is_night(hour_frac)),
        "traffic_factor": round(tf, 2),
        "traffic_level": str(mm.traffic_level(tf)),
        "pickup_demand_level": demand_level,
        "pickup_demand_probabilities": demand_probs,
        "surge_multiplier": surge,
        "selected_vehicle": selected,
        "options": options,
        "cheapest": min(options, key=lambda o: o["fare_inr"])["vehicle_type"],
        "fastest": min(options, key=lambda o: o["eta_min"])["vehicle_type"],
    })


@app.route("/api/predict/demand", methods=["POST"])
def predict_demand():
    if _demand_model is None:
        return jsonify({"error": "Demand model not trained yet. Run: python pipeline/run_all.py"}), 503

    body = request.get_json(force=True, silent=True) or {}
    hour, minute, day_of_week, is_raining = _parse_common(body)
    zone = _zone(body, "pickup_zone")
    label, probs = _demand_level(zone, hour, day_of_week, is_raining)

    return jsonify({
        "pickup_zone": zone,
        "hour": hour,
        "day_of_week": day_of_week,
        "is_raining": is_raining,
        "is_peak_hour": bool(mm.is_peak(hour + minute / 60)),
        "predicted_demand_level": label,
        "probabilities": probs,
        "surge_multiplier": float(mm.surge_multiplier(label, hour + minute / 60, is_raining)),
        "model_accuracy": _demand_metrics.get("accuracy"),
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)
