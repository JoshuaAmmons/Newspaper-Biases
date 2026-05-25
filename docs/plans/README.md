# Implementation Plans

Execution/implementation plans and design decisions layered on top of the master
design doc ([`../PROJECT_PLAN.md`](../PROJECT_PLAN.md)), the codebook
([`../CODEBOOK.md`](../CODEBOOK.md)), and data sources
([`../DATA_SOURCES.md`](../DATA_SOURCES.md)). These capture *how* we execute, not
*what* the paper argues.

## Lineage
This project evolved from **github.com/JoshuaAmmons/american-stories-incivility**
(the "Ideas Have Consequences" / Father-Coughlin paper, study window 1926–1942),
which measured incivility on the same *American Stories* corpus with a
**hand lexicon + Random Forest**. The Caplan project keeps that repo's proven,
resumable, single-workstation engineering but **upgrades the measurement layer** to
an automated multi-LLM labeling jury + stance-aware RoBERTa for Caplan's four
biases. The incivility repo stays as-is; nothing here modifies it.

## Index
- [`01_llm_labeling.md`](01_llm_labeling.md) — fully automated multi-LLM "jury"
  labeling: speed-tiered contestation + Claude adjudication, no human in the loop.
- [`02_efficiency_pipeline.md`](02_efficiency_pipeline.md) — the pipeline redesigned
  for speed/efficiency by adopting the incivility repo's patterns.
- [`03_two_week_plan.md`](03_two_week_plan.md) — the ~2-week labeling deliverable
  and the hand-off boundary to longer-running agents.
- [`04_roberta_vs_random_forest.md`](04_roberta_vs_random_forest.md) — why RoBERTa
  for the stance heads, and where RF/lexicon is still fine.

## Standing decisions (snapshot)
- **Labeling is fully automated — no human in the loop.** Validity is anchored by a
  model-independent scaffold (codebook gold suite, adversarial minimal pairs,
  canaries), not a human audit.
- **Multi-LLM contestation**, with **Claude as the blind adjudicator** of disagreements
  (kept out of the competitor pool to avoid self-grading).
- **Speed-tiered:** fast/cheap models vote on everything; smart/slow models touch only
  the contested subset (avoids the timeout problems slow models hit at scale).
- **Raw corpus lives OUTSIDE this repo** at `C:\Users\jdamm\Caplan`
  (`dell-research-harvard/AmericanStories`, ~317 GB) — re-downloadable, never committed.
