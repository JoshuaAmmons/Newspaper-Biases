"""03a — Parse newspaper publication geography (city / county / state) from the
American Stories `newspaper_name` title parenthetical. No LoC / network needed:
the geography is in the title string itself, e.g.

  "Evening star. [volume] (Washington, D.C.) 1854-1972"      -> city=Washington,            state=DC
  "Abbeville progress. (Abbeville, Vermilion Parish, La.)"   -> city=Abbeville, county=Vermilion Parish, state=LA

Reuses the incivility project's validated state parser (Geocode.zip /
extract_newspaper_states.py), EXTENDED to also capture county/parish when the title
carries it, and to keep the corpus `lccn` + `state` columns as cross-checks. The
county GAP (titles with only "(City, State)") is filled in a later step via a Census
city->county gazetteer.

Reads the RAW per-year ingest parquet (static; not the in-progress cleaned dir).
Output: <CAPLAN_DATA>/data_panels/newspaper_geo_raw.csv  (one row per distinct newspaper)
"""
import pyarrow.parquet as pq
import os, re, csv, sys, glob

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DATA = os.environ.get("CAPLAN_DATA", r"C:\Users\jdamm\Caplan")
parquet_dir = os.path.join(DATA, "data_parquet")
outdir = os.path.join(DATA, "data_panels")
os.makedirs(outdir, exist_ok=True)
outcsv = os.path.join(outdir, "newspaper_geo_raw.csv")

# Validated state-abbreviation table from the incivility project (longest-first so
# "W. Va." matches before "Va.", "N.C." before any "C.", etc.).
state_lookup = [
    ("W. Va.", "WV"), ("N.M.", "NM"), ("N.C.", "NC"), ("N.D.", "ND"), ("N.H.", "NH"),
    ("N.J.", "NJ"), ("N.Y.", "NY"), ("S.C.", "SC"), ("S.D.", "SD"), ("D.C.", "DC"), ("R.I.", "RI"),
    ("Ala.", "AL"), ("Ariz.", "AZ"), ("Ark.", "AR"), ("Calif.", "CA"), ("Colo.", "CO"),
    ("Conn.", "CT"), ("Del.", "DE"), ("Fla.", "FL"), ("Ga.", "GA"), ("Ill.", "IL"), ("Ind.", "IN"),
    ("Kan.", "KS"), ("Ky.", "KY"), ("La.", "LA"), ("Me.", "ME"), ("Md.", "MD"), ("Mass.", "MA"),
    ("Mich.", "MI"), ("Minn.", "MN"), ("Miss.", "MS"), ("Mo.", "MO"), ("Mont.", "MT"), ("Neb.", "NE"),
    ("Nev.", "NV"), ("Okla.", "OK"), ("Or.", "OR"), ("Pa.", "PA"), ("Tenn.", "TN"), ("Tex.", "TX"),
    ("Vt.", "VT"), ("Va.", "VA"), ("Wash.", "WA"), ("Wis.", "WI"), ("Wyo.", "WY"),
    ("Idaho", "ID"), ("Iowa", "IA"), ("Ohio", "OH"), ("Utah", "UT"), ("O.", "OH"),
]
loc_pattern = re.compile(r"\(([^)]+)\)")


def parse_loc(name):
    """Return (city, county, state_code) parsed from the title parenthetical."""
    m = loc_pattern.search(name or "")
    if not m:
        return ("", "", "")
    loc = m.group(1)
    parts = [p.strip() for p in loc.split(",")]
    city = parts[0] if parts else ""
    state = ""
    for abbr, code in state_lookup:
        if abbr in loc:
            state = code
            break
    county = ""
    for p in parts[1:]:           # a middle token like "Vermilion Parish" / "Cook County" / "X Co."
        pl = p.lower()
        if ("county" in pl) or ("parish" in pl) or pl.endswith(" co."):
            county = p
            break
    return (city, county, state)


# Accumulate distinct newspapers: newspaper_name -> [lccn, corpus_state]
papers = {}
files = sorted(glob.glob(os.path.join(parquet_dir, "articles_*.parquet")))
print(f"reading {len(files)} year files for distinct newspapers...", flush=True)
for fp in files:
    avail = set(pq.ParquetFile(fp).schema_arrow.names)
    cols = [c for c in ("lccn", "newspaper_name", "state") if c in avail]
    if "newspaper_name" not in cols:
        continue
    t = pq.read_table(fp, columns=cols)
    # Distinct newspapers WITHIN this file via Arrow (avoids per-row Python over 100M+ rows,
    # which made the first version take hours). Reduces to ~hundreds of distinct papers/year.
    aggs = [(c, "min") for c in cols if c != "newspaper_name"]
    d = t.group_by("newspaper_name").aggregate(aggs)
    names = d.column("newspaper_name").to_pylist()
    lc = d.column("lccn_min").to_pylist() if "lccn" in cols else [None] * len(names)
    st = d.column("state_min").to_pylist() if "state" in cols else [None] * len(names)
    for i, name in enumerate(names):
        if name and name not in papers:
            papers[name] = [lc[i], st[i]]
    del t, d, names, lc, st

N = len(papers)
print(f"distinct newspapers: {N}", flush=True)
for s in list(papers.keys())[:3]:
    print("  sample name:", repr(s), flush=True)

n_state = n_county = n_corpus_state = n_agree = 0
with open(outcsv, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["lccn", "newspaper_name", "city", "county_title", "state_title", "state_corpus", "state_final"])
    for name, (lccn, cstate) in sorted(papers.items()):
        city, county, stt = parse_loc(name)
        cstate = (cstate or "").strip()
        final = stt or cstate
        if final:
            n_state += 1
        if county:
            n_county += 1
        if cstate:
            n_corpus_state += 1
        if stt and cstate and stt == cstate:
            n_agree += 1
        w.writerow([lccn or "", name, city, county, stt, cstate, final])

pct = lambda x: f"{x}/{N} ({100*x/N:.1f}%)" if N else "0"
print(f"with final state   : {pct(n_state)}")
print(f"county in title    : {pct(n_county)}")
print(f"corpus state set   : {pct(n_corpus_state)}")
print(f"title==corpus state: {n_agree} (of rows where both present)")
print(f"wrote {outcsv}")
