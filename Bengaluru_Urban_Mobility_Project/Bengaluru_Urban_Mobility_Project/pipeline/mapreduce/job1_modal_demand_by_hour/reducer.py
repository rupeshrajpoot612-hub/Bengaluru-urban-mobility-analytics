#!/usr/bin/env python
"""
MapReduce Job 1 — Modal Demand by Hour
Reducer: sums the 1s for each (hour|vehicle_type) key and splits the
composite key back into columns on output.

Relies on the shuffle/sort stage having grouped identical keys together
(exactly what `sort` does locally, and what Hadoop's shuffle does on a
cluster) -- this is the standard Hadoop Streaming reducer pattern.
"""
import sys


def emit(key, total):
    hour, vehicle = key.split("|", 1)
    print(f"{hour}\t{vehicle}\t{total}")


def main():
    current_key = None
    current_total = 0

    for line in sys.stdin:
        line = line.rstrip("\n")
        if not line:
            continue
        key, value = line.split("\t", 1)

        if key == current_key:
            current_total += int(value)
        else:
            if current_key is not None:
                emit(current_key, current_total)
            current_key = key
            current_total = int(value)

    if current_key is not None:
        emit(current_key, current_total)


if __name__ == "__main__":
    main()
