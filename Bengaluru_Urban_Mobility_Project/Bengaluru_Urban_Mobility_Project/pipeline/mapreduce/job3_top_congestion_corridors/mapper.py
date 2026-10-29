#!/usr/bin/env python
"""
MapReduce Job 3 — Top Congestion Corridors (peak hours only)
Mapper: keeps only peak-hour trips (08:30-11:30, 17:30-21:30) and emits
(pickup_zone|dropoff_zone) -> "distance_km,duration_min,delay_min".
Intra-zone trips are skipped: a corridor needs two different hubs.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from schema import (  # noqa: E402
    IDX_PICKUP_ZONE, IDX_DROPOFF_ZONE, IDX_DISTANCE_KM, IDX_DURATION_MIN,
    IDX_DELAY_MIN, IDX_IS_PEAK_HOUR,
)


def main():
    for line in sys.stdin:
        line = line.rstrip("\n")
        if not line:
            continue
        fields = line.split("\t")
        if fields[IDX_IS_PEAK_HOUR] != "1":
            continue
        pickup, dropoff = fields[IDX_PICKUP_ZONE], fields[IDX_DROPOFF_ZONE]
        if pickup == dropoff:
            continue
        value = f"{fields[IDX_DISTANCE_KM]},{fields[IDX_DURATION_MIN]},{fields[IDX_DELAY_MIN]}"
        print(f"{pickup}|{dropoff}\t{value}")


if __name__ == "__main__":
    main()
