#!/usr/bin/env python
"""
MapReduce Job 1 — Modal Demand by Hour
Mapper: (hour|vehicle_type) -> 1

Hadoop-Streaming compatible: reads records from stdin, writes
"key\tvalue" pairs to stdout. Runs unchanged under:
  hadoop jar hadoop-streaming.jar -mapper mapper.py -reducer reducer.py ...
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from schema import IDX_HOUR, IDX_VEHICLE_TYPE  # noqa: E402


def main():
    for line in sys.stdin:
        line = line.rstrip("\n")
        if not line:
            continue
        fields = line.split("\t")
        print(f"{fields[IDX_HOUR]}|{fields[IDX_VEHICLE_TYPE]}\t1")


if __name__ == "__main__":
    main()
