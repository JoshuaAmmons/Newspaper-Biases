"""
Download the American Stories newspaper dataset from Hugging Face year-by-year
and save one Parquet file per year under data_parquet/.

Usage:
    python download_data.py                # full 1774-1960
    python download_data.py 1895 1945      # a specific range (the primary analysis window)

Robust to batch failures: on a batch error it retries each year individually so one bad year
does not abort the run. Re-running skips years already on disk.
"""

import os
import sys
import gc
import pyarrow as pa
import pyarrow.parquet as pq
from datasets import load_dataset

# Portable root: env var override, else the directory this script lives in.
ROOT = os.environ.get("CAPLAN_ROOT") or os.path.dirname(os.path.abspath(__file__))
DATA_PARQUET = os.path.join(ROOT, "data_parquet")
os.makedirs(DATA_PARQUET, exist_ok=True)

# ---- year range -------------------------------------------------------------
if len(sys.argv) >= 3:
    start_year, end_year = int(sys.argv[1]), int(sys.argv[2])
else:
    start_year, end_year = 1774, 1960

all_years = [str(y) for y in range(start_year, end_year + 1)]

# ---- skip years already downloaded ------------------------------------------
existing = {
    f.replace("articles_", "").replace(".parquet", "")
    for f in os.listdir(DATA_PARQUET)
    if f.startswith("articles_") and f.endswith(".parquet")
}
to_download = [y for y in all_years if y not in existing]
print(f"{len(to_download)} years to download, {len(existing)} already done.")

def save_year(year_data, yr):
    n = len(year_data)
    if n == 0:
        print(f"  Year {yr} has 0 articles, skipping.")
        return
    outpath = os.path.join(DATA_PARQUET, f"articles_{yr}.parquet")
    table = pa.Table.from_pandas(year_data.to_pandas())
    pq.write_table(table, outpath)
    print(f"  Saved {n} articles for year {yr} -> {outpath}")

# ---- download in batches of 5 years -----------------------------------------
BATCH = 5
for i in range(0, len(to_download), BATCH):
    batch = to_download[i:i + BATCH]
    print(f"\n=== Batch {i // BATCH + 1}: years {batch[0]}-{batch[-1]} ===")
    try:
        ds = load_dataset(
            "dell-research-harvard/AmericanStories",
            "subset_years",
            year_list=batch,
            trust_remote_code=True,
        )
        for yr in ds.keys():
            if os.path.exists(os.path.join(DATA_PARQUET, f"articles_{yr}.parquet")):
                print(f"  Year {yr} already exists, skipping.")
                continue
            save_year(ds[yr], yr)
        del ds
        gc.collect()
    except Exception as e:
        print(f"  ERROR in batch: {e}")
        for yr in batch:  # retry individually
            if os.path.exists(os.path.join(DATA_PARQUET, f"articles_{yr}.parquet")):
                continue
            try:
                print(f"  Retrying year {yr} individually...")
                ds_single = load_dataset(
                    "dell-research-harvard/AmericanStories",
                    "subset_years",
                    year_list=[yr],
                    trust_remote_code=True,
                )
                save_year(ds_single[yr], yr)
                del ds_single
                gc.collect()
            except Exception as e2:
                print(f"    FAILED year {yr}: {e2}")

# ---- summary ----------------------------------------------------------------
files = [f for f in os.listdir(DATA_PARQUET)
         if f.startswith("articles_") and f.endswith(".parquet")]
total = sum(os.path.getsize(os.path.join(DATA_PARQUET, f)) for f in files)
print("\n=== Summary ===")
print(f"Total Parquet files: {len(files)}")
print(f"Total size: {total / 1e9:.2f} GB")
