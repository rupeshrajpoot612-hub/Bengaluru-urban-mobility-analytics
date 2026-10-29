#!/usr/bin/env python
"""
MapReduce Job 3 — Top Congestion Corridors (peak hours only)
Reducer: per (pickup_zone|dropoff_zone) corridor, computes peak-hour trip
count, average speed, average duration, average delay and the share of
travel time lost to delay, then flags bottlenecks:
  CRITICAL  avg peak speed < 13.75 km/h
  SEVERE    avg peak speed < 15 km/h
  MODERATE  otherwise
"""
import sys


def emit(key, count, total_km, total_min, total_delay):
    pickup, dropoff = key.split("|", 1)
    speed = total_km / (total_min / 60)
    status = "CRITICAL" if speed < 13.75 else "SEVERE" if speed < 15 else "MODERATE"
    print(
        f"{pickup}\t{dropoff}\t{count}\t{speed:.2f}\t{total_min / count:.2f}"
        f"\t{total_delay / count:.2f}\t{total_delay / total_min:.3f}\t{status}"
    )


def main():
    current_key = None
    count, total_km, total_min, total_delay = 0, 0.0, 0.0, 0.0

    for line in sys.stdin:
        line = line.rstrip("\n")
        if not line:
            continue
        key, value = line.split("\t", 1)
        km, minutes, delay = (float(x) for x in value.split(","))

        if key != current_key:
            if current_key is not None:
                emit(current_key, count, total_km, total_min, total_delay)
            current_key = key
            count, total_km, total_min, total_delay = 0, 0.0, 0.0, 0.0

        count += 1
        total_km += km
        total_min += minutes
        total_delay += delay

    if current_key is not None:
        emit(current_key, count, total_km, total_min, total_delay)


if __name__ == "__main__":
    main()
