# Plan 04 — Why RoBERTa for the stance heads (and where RF/lexicon is fine)

The project's whole premise is separating **stance** (endorse / report / quote /
reject) from **topic**. A Random Forest on bag-of-words / TF-IDF features can only see
topic. RoBERTa sees the structure that determines stance.

## The decisive reason: stance is a word-order problem
BoW/TF-IDF is (near) order-invariant — it knows *which* words appear, not *how they
relate*. But stance hinges on negation, attribution, and framing. Near-identical bags
of words carry opposite labels:

- *"The new harvester throws good men out of work; better reaped by hand."* → `make_work = endorse`
- *"Those who say the harvester throws good men out of work have never balanced a ledger."* → `make_work = reject`

RF on BoW is structurally blind here; RoBERTa's self-attention models the negation and
attributing clause that flip the label.

## Other capabilities RF can't match
- **Contextual meaning + historical drift** (1900→1945): "trust", "speculator",
  "alien", "panic" shift valence by context/era; contextual embeddings adapt, fixed
  TF-IDF weights don't.
- **OCR + paraphrase via subwords:** mangled or unseen words degrade gracefully;
  paraphrases sharing no exact tokens still land close. For RF they're zero features.
- **Sample efficiency on rare positives:** pretraining lets fine-tuning reach subtle
  distinctions from ~10k labels; RF on sparse BoW overfits the minority `endorse` class.

## Where RF/lexicon is genuinely fine
- **The relevance gate** is largely a *topic* question → BoW/RF or even the seed
  lexicons do passably. That's why the design splits a cheap relevance gate from the
  stance heads (see [`02_efficiency_pipeline.md`](02_efficiency_pipeline.md)).
- RF is CPU-only, trains in seconds, interpretable — good for the prefilter/gate, wrong
  for stance.

## The predecessor's lesson
In `american-stories-incivility`, the RF was trained on **lexicon-derived pseudo-labels**
(≥p90 incivil / ≤p50 civil) and the corpus-scoring step actually fell back to the raw
lexicon (`p_incivil := uncivil_score`). So the deployed measure *was* the lexicon — no
stance, no independent ground truth. Caplan fixes both: independent LLM labels (Plan 01)
+ stance-aware RoBERTa; lexicons demoted to sampling/prefilter only.

## Robustness baseline (do last, if at all)
Report a TF-IDF+RF baseline alongside RoBERTa. Expectation: comparable on the relevance
gate, RoBERTa decisively ahead on the four stance heads — itself evidence the task is
about stance, not vocabulary. The predecessor repo is effectively this baseline already.
