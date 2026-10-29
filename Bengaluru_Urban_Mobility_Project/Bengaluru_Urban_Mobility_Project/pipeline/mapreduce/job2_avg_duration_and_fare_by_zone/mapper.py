#!/usr/bin/env python
"""
MapReduce Job 2 — Average Duration & Fare by Pickup Zone and Vehicle
Mapper: (pickup_zone|vehicle_type) -> "duration_min,fare_inr"
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from schema import IDX_PICKUP_ZONE, IDX_VEHICLE_TYPE, IDX_DURATION_MIN, IDX_FARE_INR  # noqa: E402


def main():
    for line in sys.stdin:
        line = line.rstrip("\n")
        if not line:
            continue
        fields = line.split("\t")
        key = f"{fields[IDX_PICKUP_ZONE]}|{fields[IDX_VEHICLE_TYPE]}"
        print(f"{key}\t{fields[IDX_DURATION_MIN]},{fields[IDX_FARE_INR]}")


if __name__ == "__main__":
    main()
