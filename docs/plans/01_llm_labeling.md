# Plan 01 — Automated multi-LLM labeling (no human in the loop)

**Goal:** produce validated `train/dev/test` labels for all four biases
(anti-market, anti-foreign, make-work, pessimistic), fully automated, as the input
to the staged RoBERTa in [`../PROJECT_PLAN.md`](../PROJECT_PLAN.md) §6.

All four biases are labeled **jointly** in one multi-label pass over a single ~10k
queue — not four separate jobs.

## Architecture: a speed-tiered contestation cascade
Cheap fast models vote on everything; an expensive smart model adjudicates only the
contested slice. This honors the timeout lesson: slow/reasoning models never run on
the full corpus.

### Tier 1 — fast panel (votes on all ~10k passages)
Family diversity is what makes contestation meaningful (intra-vendor models share
errors). Representative roster:

| Model | Family | Access |
|---|---|---|
| Gemini 2.x Flash | Google | cloud batch |
| GPT-4.1-mini / o4-mini | OpenAI | cloud batch |
| Claude Haiku 4.5 | Anthropic | cloud batch |
| Llama / Qwen / Mistral-small (8–14B) | open | **local GPU via vLLM** |
| Mistral / DeepSeek (optional 5th) | other | cloud |

Each emits the codebook schema `{relevance, per-bias stance, intensity, rationale}`
in one multi-label call.

### Tier 2 — adjudicator (contested passages only)
**Claude** (Sonnet → Opus for the hardest), blind to provider identity
("Annotator A/B"), resolves only disagreements. Kept **out** of Tier 1 to avoid
self-grading.

## Escalation rule
The decisive class is `endorse` (the rare positive that defines the bias rate), so
escalate aggressively there.
- **Relevance:** accept if ≥4/5 agree; else escalate.
- **Per-bias stance:** accept only on ≥4/5 consensus; **escalate if any model votes
  `endorse` but it isn't unanimous**, or if no ≥4/5 majority exists.
- Accepted directly → `confidence=high`; T2-resolved → `confidence=adjudicated`.
- Expected escalation: ~15–30% → a few thousand T2 calls.

## Speed & timeout engineering
- **Batch endpoints** (OpenAI Batch / Anthropic Message Batches / Gemini batch) for
  the Tier-1 bulk pass — async, ~50% cheaper, no per-request timeout.
- **Self-hosted Llama via vLLM** on the local 24 GB GPU — full batching control.
- Live calls (if any): bounded async concurrency per provider, per-call timeout +
  exponential-backoff retries, then fall back / escalate rather than hang.
- Tiny JSON output, `temperature=0`, passage truncated ~6k chars; checkpoint per
  provider (resume).
- **Reasoning/thinking models stay in Tier 2 only.**

## Validity without humans (model-independent)
- **Codebook gold suite:** turn [`../CODEBOOK.md`](../CODEBOOK.md) §3 +/- examples into
  a labeled unit-test set every model + the pipeline must pass.
- **Adversarial minimal pairs:** same topic flipped across endorse/report/quote/reject,
  and warranted-negativity vs. excess-pessimism — stress-tests the stance≠topic core.
- **Canaries:** ~50 known-label passages seeded through the run → live per-model accuracy.
- **Reliability stats:** Krippendorff's α per bias + Tier-2 overturn rate; use per-model
  gold accuracy as Dawid–Skene vote weights.
- **Honest caveat:** this catches idiosyncratic error, not *correlated* cross-model
  error on historical phrasing — report the residual rather than hide it.

## Output
Labeled set with per-bias targets + a `confidence` column (high / adjudicated) and the
retained per-model votes (a ready-made "hard cases" set for error analysis). Downstream
RoBERTa can weight by confidence or drop the low-confidence tail.

## Code mapping
- Generalize [`../../python/llm_label.py`](../../python/llm_label.py) to N providers +
  a `vote-merge` step + an `adjudicate` step.
- Sampling in [`../../rmd/04_sample_for_labeling.Rmd`](../../rmd/04_sample_for_labeling.Rmd);
  splits/reliability in [`../../rmd/05_build_training_set.Rmd`](../../rmd/05_build_training_set.Rmd)
  (replace the human-κ gate with the agreement + adjudication + gold-suite checks).
