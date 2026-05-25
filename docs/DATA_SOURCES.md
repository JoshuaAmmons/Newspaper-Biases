# Data Sources

Every dataset the project needs: what it is, where it lives, its vintage and geography, the
**merge key**, and how to obtain it. The join key for *everything* is **county FIPS × period**
(year or month). Place raw downloads under `data_raw/<source>/` (created by `_config.R`).

> **Legend.** "Auto" = a script in this repo downloads it. "Manual extract" = you must log in
> / build an extract on the provider's site and drop the file in `data_raw/`. Mark each as
> done in your own `data_raw/MANIFEST.md`.

---

## A. Text corpus

### A1. American Stories (newspaper text) — **Auto**
- **What:** Article-level OCR'd U.S. newspaper text, 1774–1960, with title + scan metadata.
- **Where:** Hugging Face dataset `dell-research-harvard/AmericanStories`.
- **Geography/merge:** carries `newspaper_name` + LCCN + geonames IDs → links to county (see B1).
- **Vintage/grain:** article level; date down to the day; one Parquet per year.
- **How:** `download_data.py` (called by `rmd/01_download_data.Rmd`) pulls year-by-year via the
  `datasets` library and writes `data_parquet/articles_<year>.parquet`. Config:
  `subset_years`, `trust_remote_code=True`. Expect tens of GB; budget disk accordingly.

---

## B. Newspaper → geography crosswalk

### B1. Chronicling America newspaper title list + loc.gov API — **Auto/Manual**
- **What:** Authority list of newspaper titles with **place of publication** (state, county,
  city) keyed by **LCCN**.
- **Where:** Library of Congress *Chronicling America* — the full **titles list is downloadable
  as CSV/TXT**, and records are queryable through the `loc.gov` API (JSON).
- **Merge:** `LCCN` (preferred) and normalized `title` → place of publication → **county FIPS**.
- **How:** `rmd/03_geolink_newspapers.Rmd` downloads the titles list, joins to American Stories
  on LCCN/title, resolves place→county FIPS, and writes `data_panels/xwalk_lccn_county.parquet`.
  Unmatched titles are written to `data_panels/xwalk_unmatched.csv` for manual patching.
- **County FIPS authority:** use the NHGIS/Census county definitions for the relevant decade
  (county boundaries change; see note in §E).

---

## C. Shock datasets (one family per bias)

### C1. Anti-market — NHGIS county FDIC Bank Deposits, 1920–1936 — **Manual extract**
- **What:** County-level bank deposits (the series behind **ICPSR Study 7**), 1920–1936.
- **Where:** **NHGIS** (IPUMS National Historical GIS), `nhgis.org`. Search the FDIC Bank
  Deposit / banking tables; also see NHGIS time-series tables for banking.
- **Grain/merge:** county × year → `fips × year`.
- **Treatment built in `08`:** YoY log deposit change; binary = first year in top national
  decile of decline.
- **How:** Build an NHGIS extract (select the FDIC deposit dataset, all counties, 1920–1936),
  download the CSV + the **codebook**, save to `data_raw/nhgis_bank_deposits/`.

### C2. Pessimistic — NOAA county climate + NHGIS mortality — **Manual extract / Auto**
- **C2a. NOAA nClimDiv / nClimGrid (climate):** county **monthly** average temperature,
  precipitation, and drought indices (e.g., **PDSI**), **1895→present**. Source: NOAA NCEI.
  County files are published directly; can be scripted. Save to `data_raw/noaa_nclimdiv/`.
  Merge: `fips × year-month`. Z-score each variable against the county's own 1895–baseline
  climatology in `08`.
- **C2b. NHGIS births/deaths:** county/state **annual** birth and death counts, **1915→**.
  Source: NHGIS vital statistics tables. Merge: `fips × year`. Use for mortality / epidemic
  spikes (incl. 1918 influenza). Save to `data_raw/nhgis_vital/`.

### C3. Anti-foreign — county foreign-born exposure (pre-period) — **Manual extract**
- **What:** Pre-event county composition: **German-born share (1910)** for the WWI design;
  **foreign-born / southern-&-eastern-European share (≈1920)** for the 1924 design.
- **Where (pick one):**
  - **IPUMS Full Count** (`usa.ipums.org`): complete-count census microdata through 1950 —
    build county aggregates of birthplace shares. Most flexible.
  - **NHGIS** county census tabulations — pre-tabulated nativity by county/decade. Simpler.
- **Event dates (no download — constants in `_config.R`):** WWI entry **1917-04-06**;
  Immigration Act of 1924 (**Johnson–Reed**) enacted **1924**. (National Archives / Office of
  the Historian for documentation.)
- **Merge:** exposure is time-invariant `fips → exposure_share`; interacted with `post_event`.
- **How:** Build the IPUMS or NHGIS extract → county nativity shares → save to
  `data_raw/exposure_foreignborn/`.

### C4. Make-work — NHGIS Census of Agriculture (mechanization), 1925 & 1935 — **Manual extract**
- **What:** County agriculture tables — **tractors, machinery value, hired labor, crop mix** —
  for census years **1925 and 1935** (broader span available; USDA NASS historical AgCensus
  archive preserves originals from 1850).
- **Where:** **NHGIS** Census of Agriculture datasets; USDA **NASS** AgCensus archive as backup.
- **Grain/merge:** county × census-year → `fips × {1925,1935}`.
- **Treatment built in `08`:** large intercensal jump in mechanization (e.g., Δ tractors/farm)
  vs low-adoption counties.
- **How:** NHGIS extract for 1925 + 1935 Census of Agriculture, all counties; save to
  `data_raw/nhgis_agcensus/`.

### C5. Make-work backup — BLS strikes / work stoppages — **Manual extract (v2)**
- **What:** Strike / work-stoppage records back to the **1880s** (sharper events than
  mechanization).
- **Where:** Bureau of Labor Statistics historical work-stoppage data + historical bulletins.
- **Caveat:** reported by **city/industry**, not turnkey county-year → requires geocoding/
  county assignment. Deferred to v2 unless the mechanization design underperforms.

---

## D. Caplan source & framing

- Bryan Caplan, *The Myth of the Rational Voter: Why Democracies Choose Bad Policies*
  (Princeton, 2007) — the taxonomy of the four biases. Used for the codebook's conceptual
  definitions, not as data.

---

## E. Cross-cutting notes

- **County boundary changes.** County definitions change across decades. Use period-
  appropriate FIPS and a boundary crosswalk where a shock spans boundary changes; NHGIS GIS
  files document county geographies over the long run. Record the chosen vintage per design.
- **NHGIS = preferred hub.** It provides county tables since 1790 and long-run county/state
  GIS; most shocks (banking, vital stats, agriculture, nativity) can be pulled from one place
  with consistent county codes — minimizing merge headaches.
- **Citation/licensing.** NHGIS, IPUMS, NOAA, BLS, USDA, and LoC each have citation/usage
  terms; record required citations in the paper and check redistribution terms before
  including any raw extract in the public replication package.

---

## F. One-page source matrix

| Bias | Shock | Years | Geography | Treatment variable | Control group | Source |
|------|-------|-------|-----------|--------------------|---------------|--------|
| Anti-market | Bank deposit collapse | 1920–1936 | county-year | top-decile deposit decline / Δlog deposits | not-yet / never distressed | NHGIS FDIC (ICPSR 7) |
| Pessimistic | Drought / temp / precip | 1895→ | county-month | z-scored climate anomaly / PDSI | counties w/o anomaly | NOAA nClimDiv |
| Pessimistic | Mortality / epidemic | 1915→ | county-year | mortality-rate spike | non-spike counties | NHGIS vital stats |
| Anti-foreign | WWI entry | event 1917 | county exposure | post-1917 × German-born share 1910 | low-exposure counties | IPUMS/NHGIS + Nat'l Archives |
| Anti-foreign | Immigration Act 1924 | event 1924 | county exposure | post-1924 × foreign-born/SE-Euro share | low-exposure counties | IPUMS/NHGIS + Office of Historian |
| Make-work | Farm mechanization | 1925→1935 | county-census | Δ tractors/machinery (high vs low) | low-adoption counties | NHGIS Census of Agriculture |
| Make-work (v2) | Strikes / stoppages | 1880s→ | county (geocoded) | strike onset | non-strike counties | BLS |
