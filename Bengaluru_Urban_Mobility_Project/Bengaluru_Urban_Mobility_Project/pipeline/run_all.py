"""
Runs the full pipeline end to end:
  0. Generate the synthetic Bengaluru multi-modal trip dataset
  1. Clean + feature-engineer it
  2. Run the 4 MapReduce jobs
  3. Train the 2 ML models
  4. Precompute the role-based dashboard JSON

Run:
  python pipeline/run_all.py
"""

import runpy
import time

STEPS = [
    "00_generate_bengaluru_data.py",
    "01_clean_and_engineer.py",
    "02_run_mapreduce.py",
    "03_train_models.py",
    "04_precompute_dashboard.py",
]

if __name__ == "__main__":
    import os

    base = os.path.dirname(os.path.abspath(__file__))
    t0 = time.time()
    for step in STEPS:
        print("\n" + "#" * 70)
        print(f"# RUNNING {step}")
        print("#" * 70)
        runpy.run_path(os.path.join(base, step), run_name="__main__")
    print(f"\nFULL PIPELINE COMPLETE in {time.time() - t0:.1f}s")
