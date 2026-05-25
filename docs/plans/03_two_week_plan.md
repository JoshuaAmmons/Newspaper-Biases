# Plan 03 — Two-week labeling deliverable + hand-off

**Goal:** in ~2 weeks, produce the validated labeled training data for **all four
biases**, then hand off to longer-running agents for the GPU-heavy work.

## The hand-off boundary
```
   [ humans + this collaboration ]            [ longer-running agents ]
 ingest → clean → geolink → prefilter →     | train staged RoBERTa →
 sample → multi-LLM jury → adjudicate →     | calibrate → score FULL corpus →
 train/dev/test splits  ───────────────────►| build panel → merge shocks → DiD
```
Deliverable to hand off: frozen codebook + `label_queue.parquet` +
per-provider labels + adjudicated gold + `train/dev/test` parquets (4 targets +
`confidence`). That is exactly what `python/train_classifiers.py` consumes.

The genuinely long-running, GPU-bound work — full-corpus scoring over hundreds of
millions of articles — is what the later agents own.

## Why two weeks is realistic
The LLM labeling is **one multi-label ~10k pass** (hours of batch compute, a few
dollars), not four jobs. Removing the human audit loop (Plan 01) removes the slowest
dependency; the model-independent validity scaffold replaces it.

## What gates the timeline
1. **Environment + window-scoped corpus prep (days 1–3).** Nothing is installed yet
   (no Python/R/vLLM); corpus must be ingested + cleaned for the 1895–1945 window and
   geolinked enough for stratification.
2. **Iteration on the gold/adversarial suite** — tuning prompts until the panel passes
   the codebook unit tests per bias. Automated, so it iterates in hours, not days.

## Indicative schedule
- **Week 1:** env setup (d1–2) → ingest+clean 1895–1945 ∥ geolink (d2–4) → author gold
  + adversarial suite (d3–4) → build prefilter + queue, run Tier-1 batch labeling (d5).
- **Week 2:** vote-merge + Claude adjudication (d6–7) → gold/α/overturn validation,
  tune & re-run contested (d8–9) → finalize splits + reliability report + hand-off
  package (d10).

## Status note
Corpus download (~317 GB) runs to `C:\Users\jdamm\Caplan`; it finishes within hours and
is not the binding constraint. See [`02_efficiency_pipeline.md`](02_efficiency_pipeline.md)
for the streamed/resumable ingest.
