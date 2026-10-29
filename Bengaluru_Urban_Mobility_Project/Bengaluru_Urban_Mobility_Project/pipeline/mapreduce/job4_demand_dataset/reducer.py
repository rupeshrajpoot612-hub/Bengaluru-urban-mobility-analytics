#!/usr/bin/env python
"""
MapReduce Job 4 — Demand by Date + Hour + Pickup Zone (space-time grid)
Reducer: sums the 1s for each (date|hour|day_of_week|zone|is_raining) key
and splits the composite key back into columns on output.
"""
import sys


def emit(key, total):
    print("\t".join(key.split("|", 4)) + f"\t{total}")


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
