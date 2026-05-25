# The Political Economy of Newspaper Bias

Measuring **Anti-Market**, **Anti-Foreign**, **Make-Work**, and **Pessimistic** framing in
historical American newspapers, and testing whether external shocks causally shifted
newspapers toward (or away from) these four biases.

> **One-line version.** Using RoBERTa on the *American Stories* newspaper archive, we test
> whether shocks — bank failures, war, immigration policy, farm mechanization, weather,
> mortality — shift newspapers toward Bryan Caplan's four biases from *The Myth of the
> Rational Voter*: anti-market, anti-foreign, make-work, and pessimistic framing.

This repository is the **full implementation plan and runnable scaffold** for that project.
It is **self-contained**: you do not need any other repository to run it. (Methodologically it
shares the proven design of a sibling project — same corpus, publication-county anchor,
LLM-label → RoBERTa measurement, and staggered-DiD + HonestDiD robustness — and the battle-
tested pieces of that machinery, e.g. `R/did_wrapper.R`, are vendored here directly.)

**New here? Start with [`docs/REPLICATION.md`](docs/REPLICATION.md)** — a step-by-step,
machine-agnostic "run it from zero" guide.

---

## What to read first

| If you want…                              | Read                                   |
|-------------------------------------------|----------------------------------------|
| To run it end-to-end on any machine       | [`docs/REPLICATION.md`](docs/REPLICATION.md) |
| The research design & identification      | [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md) |
| The pre-registered hypotheses & specs     | [`docs/PAP.md`](docs/PAP.md) |
| Every dataset, URL, vintage, merge key    | [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) |
| How "bias" is defined and hand-labeled    | [`docs/CODEBOOK.md`](docs/CODEBOOK.md) |
| The exact step order and what each produces | this file, "Pipeline" below          |

---

## The four bias × shock pairs (the heart of the project)

Each of Caplan's four biases is the **outcome** of one quasi-experimental design. Designs are
ranked below by *ease of clean county merge + plausibility of identification* — build them in
this order.

| # | Bias            | Primary shock (treatment)                                   | Geography / timing      | Identification |
|---|-----------------|-------------------------------------------------------------|-------------------------|----------------|
| 1 | **Anti-market** | County banking distress, 1920–1936 (deposit collapse)       | county × year           | Staggered DiD, not-yet-treated controls |
| 2 | **Pessimistic** | County weather (drought/temp/precip) + mortality shocks     | county × month / year   | DiD on external shocks; outcome = *excess* pessimism |
| 3 | **Anti-foreign**| National event × pre-period county exposure (WWI×German-born 1910; Immigration Act 1924×foreign-born) | county exposure, fixed event dates | Interaction / exposure DiD |
| 4 | **Make-work**   | County farm mechanization jumps (Census of Ag 1925→1935)    | county × (5-yr) census  | DiD high- vs low-adoption counties |

**Rule of thumb:** use county-year whenever possible; use national-shock × county-exposure
only when a clean local shock does not exist (anti-foreign).

---

## Pipeline (run order)

The pipeline mirrors the *Ideas* repo: numbered R Markdown notebooks orchestrate
deterministic R, and call into Python for the transformer steps. Run end-to-end with
`reproduce_all.R`, or render notebooks one at a time.

```
00_setup.Rmd              Verify R + Python + CUDA + packages
01_download_data.Rmd      American Stories -> data_parquet/articles_<year>.parquet   (download_data.py)
02_clean_articles.Rmd     OCR-quality filter, dedupe, normalize -> articles_cleaned/
03_geolink_newspapers.Rmd LCCN/title -> county FIPS via Chronicling America + loc.gov  -> xwalk_lccn_county.parquet
04_sample_for_labeling.Rmd Stratified + positive-oversampled sample -> label_queue.parquet
05_build_training_set.Rmd LLM weak-labels (python/llm_label.py) + human audit -> train/dev/test.parquet
06_score_corpus.Rmd       Train (python/train_classifiers.py) + score (python/score_corpus.py) + calibrate -> articles_scored/
07_build_panel.Rmd        Aggregate article scores -> county-year & county-month bias panel
08_build_shocks.Rmd       Build 4 shock datasets (NHGIS/NOAA/IPUMS) -> shocks merged to county
09_estimate_did.Rmd       Staggered DiD + interaction designs + event studies, per bias
10_robustness.Rmd         Pre-trends, placebos, HonestDiD, leave-one-out, excess-pessimism residualization
11_figures_tables.Rmd     Final figures + tables -> figures/, tables/, Overleaf sync
```

See [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md) §"Work plan" for the five-phase mapping and
[`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) for how to obtain each external dataset.

---

## Quickstart

No path edits needed — scripts auto-detect the project root (they search upward for
`_config.R`). `Rscript` and `python` are assumed on PATH; override with the `CAPLAN_*` env
vars if not (see [`_config.R`](_config.R) header). Full walkthrough:
[`docs/REPLICATION.md`](docs/REPLICATION.md).

```bash
# 1. Install dependencies (one time). Install the CUDA torch wheel first for GPU speed.
Rscript install_packages.R
python -m pip install torch --index-url https://download.pytorch.org/whl/cu121
python -m pip install -r requirements.txt

# 2. Confirm imports + GPU
python python/00_setup_check.py
Rscript -e "rmarkdown::render('rmd/00_setup.Rmd')"

# 3. Run the whole pipeline (each step in its own R process), or a slice
Rscript reproduce_all.R
Rscript reproduce_all.R 7 11
```

Configuration (registries, windows, optional Overleaf sync) lives in [`_config.R`](_config.R);
every path there is derived from the auto-detected root, so it works unchanged on a new machine.

---

## Hardware

This is a deliberately compute-heavy project (millions of OCR'd passages; RoBERTa fine-tuning
and batched inference; large R panel/econometrics). Target workstation:

- Modern dedicated **GPU** (≥12 GB VRAM) for transformer fine-tuning + large-batch inference
- High-core-count **CPU** for preprocessing and `fixest`/`did` panel work
- **≥128 GB RAM** (American Stories is large; R panel ops are memory-intensive)
- Fast **NVMe SSD** with room for the raw + intermediate Parquet (plan for ~0.5–1 TB)

The transformer steps degrade gracefully to CPU but are then ~10–100× slower; the
econometrics run on CPU.

---

## Status & assumptions

This repo is a **scaffold**: the deterministic stages (download, clean, geolink, sampling,
panel build, shock build, DiD, figures) are written as runnable-or-near-runnable code;
the stages that require human judgment or external downloads (annotation codebook,
LLM labeling keys, NHGIS/NOAA/IPUMS extracts) are written as detailed specs with explicit
`TODO(human)` markers. Key design choices and open questions are recorded in
[`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md) §"Decisions & open questions".
