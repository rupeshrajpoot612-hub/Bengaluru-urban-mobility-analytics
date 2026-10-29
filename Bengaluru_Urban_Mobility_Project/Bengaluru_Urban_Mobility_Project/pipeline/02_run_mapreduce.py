"""
STAGE 2 — MAPREDUCE EXECUTION
Bengaluru Multi-Modal Urban Mobility Analytics (CA3 Activity 2)

Runs each MapReduce job with the real Hadoop Streaming contract:

    mapper.py (stdin -> "key\\tvalue" stdout)
        -> SHUFFLE / SORT  (group identical keys together)
        -> reducer.py (grouped stdin -> aggregated stdout)

Each mapper/reducer pair is executed as its own subprocess, exactly as
Hadoop Streaming would invoke them, so the same files can later be handed
to a real Hadoop cluster unchanged:

    hadoop jar $HADOOP_HOME/share/hadoop/tools/lib/hadoop-streaming-*.jar \\
        -input /mobility/mapreduce_input.tsv -output /mobility/out/job1 \\
        -mapper mapper.py -reducer reducer.py \\
        -file pipeline/mapreduce/job1_modal_demand_by_hour/mapper.py \\
        -file pipeline/mapreduce/job1_modal_demand_by_hour/reducer.py \\
        -file pipeline/schema.py

The shuffle/sort step here is done with Python's sorted() (grouping by the
text of the key, which is also Hadoop Streaming's default sort behaviour)
so this script has no external dependency on Hadoop being installed.

Run:
  python pipeline/02_run_mapreduce.py
"""

import os
import subprocess
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
OUTPUT_DIR = os.path.join(PROJECT_DIR, "outputs")
MR_OUTPUT_DIR = os.path.join(OUTPUT_DIR, "mapreduce")
MR_INPUT_TSV = os.path.join(OUTPUT_DIR, "mapreduce_input.tsv")

os.makedirs(MR_OUTPUT_DIR, exist_ok=True)

JOBS = [
    {
        "name": "job1_modal_demand_by_hour",
        "columns": ["hour", "vehicle_type", "total_trips"],
    },
    {
        "name": "job2_avg_duration_and_fare_by_zone",
        "columns": ["pickup_zone", "vehicle_type", "trip_count", "avg_duration_min", "avg_fare_inr", "total_fare_inr"],
    },
    {
        "name": "job3_top_congestion_corridors",
        "columns": ["pickup_zone", "dropoff_zone", "peak_trips", "avg_speed_kmph", "avg_duration_min",
                    "avg_delay_min", "delay_share", "bottleneck_status"],
    },
    {
        "name": "job4_demand_dataset",
        "columns": ["pickup_date", "hour", "day_of_week", "pickup_zone", "is_raining", "trip_demand"],
    },
]


def run_stage(script_path, stdin_path, python_exe=sys.executable):
    with open(stdin_path, "r", encoding="utf-8") as f_in:
        result = subprocess.run(
            [python_exe, script_path],
            stdin=f_in,
            capture_output=True,
            text=True,
            check=True,
        )
    return result.stdout


def shuffle_sort(mapper_output_text):
    """Group identical keys together (Hadoop's shuffle/sort stage)."""
    lines = [line for line in mapper_output_text.split("\n") if line]
    lines.sort(key=lambda line: line.split("\t", 1)[0])
    return "\n".join(lines) + ("\n" if lines else "")


def run_job(job):
    name = job["name"]
    job_dir = os.path.join(BASE_DIR, "mapreduce", name)
    mapper_path = os.path.join(job_dir, "mapper.py")
    reducer_path = os.path.join(job_dir, "reducer.py")

    print(f"\n{'=' * 70}\nMAPREDUCE {name}\n{'=' * 70}")

    t0 = time.time()
    print("  [1/3] MAP phase ...")
    with open(MR_INPUT_TSV, "r", encoding="utf-8") as f_in:
        mapped = subprocess.run(
            [sys.executable, mapper_path],
            stdin=f_in,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    print(f"        mapped records: {mapped.count(chr(10)):,}  ({time.time() - t0:.1f}s)")

    t1 = time.time()
    print("  [2/3] SHUFFLE / SORT phase ...")
    shuffled = shuffle_sort(mapped)
    print(f"        sorted in {time.time() - t1:.1f}s")

    t2 = time.time()
    print("  [3/3] REDUCE phase ...")
    reduced = subprocess.run(
        [sys.executable, reducer_path],
        input=shuffled,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    reduced_lines = [line for line in reduced.split("\n") if line]
    print(f"        reduced groups: {len(reduced_lines):,}  ({time.time() - t2:.1f}s)")

    out_path = os.path.join(MR_OUTPUT_DIR, f"{name}.csv")
    with open(out_path, "w", encoding="utf-8", newline="") as f_out:
        f_out.write(",".join(job["columns"]) + "\n")
        for line in reduced_lines:
            f_out.write(",".join(line.split("\t")) + "\n")

    print(f"  Saved: {out_path}  ({len(reduced_lines):,} rows, total {time.time() - t0:.1f}s)")
    return out_path


def main():
    if not os.path.exists(MR_INPUT_TSV):
        raise FileNotFoundError(
            f"{MR_INPUT_TSV} not found. Run pipeline/01_clean_and_engineer.py first."
        )

    print("=" * 70)
    print("STAGE 2: MAPREDUCE EXECUTION (4 jobs)")
    print("=" * 70)

    t0 = time.time()
    for job in JOBS:
        run_job(job)

    print(f"\nAll MapReduce jobs completed in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
