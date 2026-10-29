#!/usr/bin/env python
"""
MapReduce Job 4 — Demand by Date + Hour + Pickup Zone (space-time grid)
Mapper: (pickup_date|hour|day_of_week|pickup_zone|is_raining) -> 1

The 10 hubs are the coarse spatial grid and date+hour is the time grid.
is_raining is a per-date attribute, so it rides along in the key without
splitting any cell. This job's reducer output becomes the training
dataset for the zone demand-level (Low/Medium/High) classifier that
drives surge pricing.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from schema import IDX_PICKUP_DATE, IDX_HOUR, IDX_DAY_OF_WEEK, IDX_PICKUP_ZONE, IDX_IS_RAINING  # noqa: E402


def main():
    for line in sys.stdin:
        line = line.rstrip("\n")
        if not line:
            continue
        fields = line.split("\t")
        key = "|".join([
            fields[IDX_PICKUP_DATE], fields[IDX_HOUR], fields[IDX_DAY_OF_WEEK],
            fields[IDX_PICKUP_ZONE], fields[IDX_IS_RAINING],
        ])
        print(f"{key}\t1")


if __name__ == "__main__":
    main()
