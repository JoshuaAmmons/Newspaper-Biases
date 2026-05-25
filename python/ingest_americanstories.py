"""
Ingest American Stories `faro_*.tar.gz` tarballs -> per-year `articles_YYYY.parquet`.

Each tarball holds one JSON per page-scan; we flatten its `full articles` list into one
row per article, attaching newspaper/lccn/date/page metadata. The output schema matches
what rmd/02_clean_articles.Rmd expects: article_id, lccn, newspaper_name, state, date,
page, headline, byline, article, year.

Parallel across years (one process per tarball) to use the CPU; per-year output is
skip-if-exists and written atomically, so the run is fully resumable.

Usage:
  python ingest_americanstories.py --src C:\\Users\\jdamm\\Caplan \\
      --out C:\\Users\\jdamm\\Caplan\\data_parquet [--workers N] [--years 1895-1945]
"""
import os, re, json, tarfile, argparse
from concurrent.futures import ProcessPoolExecutor

YEAR_RE = re.compile(r"faro_(\d{4})\.tar\.gz$")


def parse_tar(task):
    """Flatten one tarball -> articles_<year>.parquet. Returns (year, status, n_rows)."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    path, outdir = task
    m = YEAR_RE.search(os.path.basename(path))
    if not m:
        return (os.path.basename(path), "skip-noyear", 0)
    year = int(m.group(1))
    out = os.path.join(outdir, f"articles_{year}.parquet")
    if os.path.exists(out):
        return (year, "exists", 0)

    rows = []
    try:
        with tarfile.open(path, "r:gz") as tf:
            for mem in tf:
                if not mem.name.endswith(".json"):
                    continue
                try:
                    d = json.load(tf.extractfile(mem))
                except Exception:
                    continue
                lccn = d.get("lccn") or {}
                ed = d.get("edition") or {}
                scan = d.get("scan") or {}
                meta = dict(
                    lccn=lccn.get("lccn"),
                    newspaper_name=lccn.get("title"),
                    state=lccn.get("state"),
                    date=ed.get("date"),
                    page=str(scan.get("page") or d.get("page_number") or ""),
                )
                for a in (d.get("full articles") or []):
                    txt = a.get("article")
                    if not txt:
                        continue
                    rows.append({
                        "article_id": a.get("id"),
                        **meta,
                        "headline": a.get("headline") or "",
                        "byline": a.get("byline") or "",
                        "article": txt,
                        "year": year,
                    })
    except Exception as e:
        return (year, f"ERROR: {type(e).__name__}: {e}", 0)

    if not rows:
        return (year, "empty", 0)
    tmp = out + ".tmp"
    pq.write_table(pa.Table.from_pylist(rows), tmp)
    os.replace(tmp, out)   # atomic publish
    return (year, "ok", len(rows))


def select_years(files, spec):
    if not spec:
        return files
    keep = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            keep |= set(range(int(a), int(b) + 1))
        elif part:
            keep.add(int(part))
    return [f for f in files if int(YEAR_RE.search(f).group(1)) in keep]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=r"C:\Users\jdamm\Caplan")
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=8,
                    help="parallel tarballs; big years are RAM-heavy, so default modest")
    ap.add_argument("--years", default=None, help="e.g. 1895-1945 or 1774,1900")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    files = sorted(f for f in os.listdir(args.src) if YEAR_RE.search(f))
    files = select_years(files, args.years)
    tasks = [(os.path.join(args.src, f), args.out) for f in files]
    print(f"ingesting {len(tasks)} tarballs with {args.workers} workers -> {args.out}")

    total = 0
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for year, status, n in ex.map(parse_tar, tasks):
            total += n
            print(f"  {year}: {status} ({n} articles)")
    print(f"done; {total} articles ingested this run")


if __name__ == "__main__":
    main()
