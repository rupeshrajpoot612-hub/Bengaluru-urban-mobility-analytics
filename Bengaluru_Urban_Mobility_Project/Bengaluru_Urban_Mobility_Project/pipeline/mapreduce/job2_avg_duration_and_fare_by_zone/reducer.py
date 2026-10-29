#!/usr/bin/env python
"""
MapReduce Job 2 — Average Duration & Fare by Pickup Zone and Vehicle
Reducer: per (pickup_zone|vehicle_type) key, accumulates trip count,
total duration and total fare, then emits the averages.
"""
import sys


def emit(key, count, total_duration, total_fare):
    zone, vehicle = key.split("|", 1)
    print(f"{zone}\t{vehicle}\t{count}\t{total_duration / count:.2f}\t{total_fare / count:.2f}\t{total_fare:.0f}")


def main():
    current_key = None
    count = 0
    total_duration = 0.0
    total_fare = 0.0

    for line in sys.stdin:
        line = line.rstrip("\n")
        if not line:
            continue
        key, value = line.split("\t", 1)
        duration, fare = (float(x) for x in value.split(","))

        if key != current_key:
            if current_key is not None:
                emit(current_key, count, total_duration, total_fare)
            current_key = key
            count, total_duration, total_fare = 0, 0.0, 0.0

        count += 1
        total_duration += duration
        total_fare += fare

    if current_key is not None:
        emit(current_key, count, total_duration, total_fare)


if __name__ == "__main__":
    main()
