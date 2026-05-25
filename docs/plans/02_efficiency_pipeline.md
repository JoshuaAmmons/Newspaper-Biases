# Plan 02 — Efficiency pipeline (adopting the incivility repo's patterns)

**Goal:** run the Caplan measurement at corpus scale (hundreds of millions of
articles) on one workstation (24 GB GPU, 127 GB RAM), fast and resumably — by adopting
the proven engineering from `american-stories-incivility`, **without** inheriting its
correctness compromise (it let the lexicon *become* the measure and never deployed the RF).

## Primary principle: fidelity to the validated path
We follow the externally-validated `american-stories-incivility` pipeline
(download → parse → **lexicon → features → Random Forest** → panel → DiD) because it is
**proven**, not because it is fast. Efficiency is a *side benefit* of these patterns,
never the justification. **No validated step is dropped or reordered to save time or
money** — including the lexicon/RF measurement, which is a first-class step here
(validated measure + LLM candidate-selector + baseline; see
[`04_roberta_vs_random_forest.md`](04_roberta_vs_random_forest.md)). The LLM-jury →
RoBERTa is layered on top as an augmentation, validated against the RF baseline.

## Engineering principle
A **cheap → expensive cascade**: every expensive op is gated behind a cheap one. Every
stage is **year-partitioned, skip-if-exists, and `gc()`-bounded** so it survives
interruption.

## Hardware utilization (this machine: RTX PRO 5000 Blackwell 24 GB, 24-core Ultra 9, 127 GB)
The original repo ran on a weaker box. We keep its *methods identical* but execute them
faster on this hardware (a pure win, not a methodological shortcut):

| Stage | Method (unchanged) | Hardware use |
|---|---|---|
| Ingest tar.gz→parquet | flatten `full articles` | **CPU:** parallel across years (multiprocessing) |
| Clean / lexicon score | normalize, regex/1000 words | **CPU:** parallel across years |
| Features | TF-IDF → SVD (irlba) | **CPU:** multithreaded tokenize; keep TF-IDF/SVD (no reinvention) |
| Random Forest | ranger | **CPU:** `num.threads` = all cores |
| LLM jury | multi-model competition | local Llama on **GPU**; cloud calls high-concurrency |
| RoBERTa train + score | staged RoBERTa | **GPU:** CUDA torch, fp16/bf16, large batches on 24 GB — the biggest lever |
| DiD | `fect` bootstrap | **CPU:** `cores` = all |

The headline GPU win is **CUDA torch** for the RoBERTa phase (training + scoring hundreds of
millions of articles); on the CPU-only torch it would be the slowest stage by far.

## Redesigned pipeline (adoptions marked)

| Stage | What runs | Adopted pattern |
|---|---|---|
| 1. Ingest | Extract local `faro_*.tar.gz` → per-year `articles_YYYY.parquet` | Year-streamed + skip-if-exists + `gc()` (from `download_data.py`); **no re-download** — reuse the local tarballs at `C:\Users\jdamm\Caplan` |
| 2. Clean | Date/page parse, `n_words`, OCR quality, ≥10-word filter → `articles_cleaned/year=YYYY/` | **Lift `02_parse_articles` + `R/helpers.R` nearly verbatim**; partitioned parquet |
| 3. Geolink | LCCN → county FIPS crosswalk | cache + resume; parallel with clean |
| **3b. Prefilter** | Cheap seed-lexicon/regex pass over the whole corpus → `candidate_relevant` subset | **`lexicon_score` as a recall-tuned gate** — most text is irrelevant, cutting expensive-model load ~1–2 orders of magnitude |
| 4. Sample + label | Draw ~10k from the *prefiltered* pool; multi-LLM jury (Plan 01) | sample-then-score split; batch + vLLM |
| 5. Train | Staged RoBERTa: relevance gate + 4 stance heads | **grouped-CV-by-newspaper + isotonic calibration** lifted from `05_random_forest` |
| 6. Score corpus | Cheap relevance gate (DistilRoBERTa) on candidates → full stance heads only on relevance-positives | two-stage GPU cascade; fp16 batched; year-streamed skip/resume; `col_select` reads |
| 7. Panel | Aggregate to county/newspaper-period bias shares + controls + balanced-panel filter | **Lift `06_treatment_panel` structure**; swap Coughlin→4 shocks, incivility→4 bias shares |
| 8. DiD | Callaway–Sant'Anna / dCDH **+ `fect` (IFE/MC/TWFE/placebo/carryover)** | **Lift the working `07_did_estimation` `fect` code**; `panelView` subsampling for big panels |
| 0. Orchestrator | `reproduce_all.R` gains resume-from-step | **`run_pipeline.R` pattern:** `Rscript … 3` resumes at step 3, per-step logs + timing, fail-fast with resume hint |

## Where the speed comes from
- **Prefilter funnel (3b)** — the single biggest lever; GPU work runs on candidates, not everything.
- **Two-stage model cascade (6)** — cheap gate on many, expensive heads on few.
- **Stream + partition + skip/resume + `col_select`** — flat memory, crash-resumable, read only needed columns.
- **Code reuse** — parse/helpers/calibration/panel/`fect` are already debugged: fastest in calendar time.

## The one guardrail
The prefilter is **recall-validated**: measure on the labeled set what fraction of
LLM-positive passages it retains (target ≥ ~98% per bias). If a bias's recall is too
low, its relevance gate runs on everything and the lexicon only *prioritizes* — so the
lexicon never silently caps the final measure (the exact failure in the predecessor).
