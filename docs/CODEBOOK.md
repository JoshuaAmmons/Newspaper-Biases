# Annotation Codebook — Four Economic Biases in Newspaper Text

This codebook defines what a human (or LLM applying these rules) labels. It is the
contract that makes the resulting RoBERTa measures **valid**. Read
[`PROJECT_PLAN.md`](PROJECT_PLAN.md) §2 first for the conceptual frame: **we measure
endorsement of a bias, not the topic, and not warranted negativity.**

All illustrative sentences below are **invented examples** written to mimic period phrasing —
they are not quotations from the corpus.

---

## 1. Unit of analysis

- **Passage** = one article, or a coherent paragraph-level span when articles are long. The
  pipeline labels at the passage level and aggregates upward.
- A passage can be labeled positive for **more than one** bias (multi-label).
- Default to **English**; flag non-English or unreadable-OCR passages as `unusable`.

## 2. Label schema (what every passage gets)

| Field | Values | Notes |
|-------|--------|-------|
| `relevance` | `0` / `1` | Is the passage *about* markets/profit, foreigners/immigration/trade, labor-saving technology/jobs, or economic conditions/outlook at all? Stage-1 gate. |
| `bias_category` | `anti_market`, `anti_foreign`, `make_work`, `pessimistic`, `none` | Which bias(es). Multi-label allowed. |
| `stance` | `endorse`, `report`, `quote`, `reject` | The passage's relation to the biased claim. **Only `endorse` counts as positive** for the outcome. |
| `intensity` | `0`–`3` | 0 none, 1 mild, 2 clear, 3 strong/strident. Used for robustness, not the primary outcome. |
| `quality` | `ok`, `ocr_noisy`, `unusable` | OCR/readability flag. |
| `notes` | free text | Coder rationale for hard cases (feeds codebook refinement). |

**Stance is decisive.** The same sentence about bankers can be `endorse` (the paper itself
condemns markets), `report` (it relays events), `quote` (it attributes the view to a named
speaker without endorsing), or `reject` (it argues against the biased view). We score
**`endorse`** as the bias signal.

---

## 3. The four biases — decision rules

For each: a one-line test, what **counts**, what **does not** (the critical non-equivalences),
and invented +/− examples.

### 3.1 Anti-market bias
- **Test:** Does the passage treat *markets, competition, profit, prices, middlemen, or
  voluntary exchange as harmful in themselves*?
- **Counts (+):** condemning "profit" or "the speculator" as inherently parasitic; claiming
  competition is ruinous by nature; treating merchants/middlemen as social ills.
  - *+ "The merchant's profit is wrung from the toil of honest men; trade itself breeds
    corruption."*
- **Does NOT count (−):** criticizing a *specific* fraud, monopoly privilege, or a particular
  bad actor; reporting a price change; supporting one policy over another.
  - *− "The grand jury indicted the firm for rigging the weighing scales."* (fraud, not
    markets-as-such)
  - *− "Wheat fell three cents on the Chicago exchange yesterday."* (reporting)

### 3.2 Anti-foreign bias
- **Test:** Does the passage portray *immigrants, foreign producers, imports, or external
  actors as inherently threatening* to domestic prosperity, jobs, or order?
- **Counts (+):** framing immigrants as a drain or menace by virtue of being foreign;
  imports as inherently injurious; "the foreigner" as a unit of threat.
  - *+ "These newcomers from abroad will undercut our wages and corrupt our institutions."*
- **Does NOT count (−):** neutral immigration statistics; advocating a trade policy on
  economic grounds; reporting a diplomatic event; criticizing a specific foreign government's
  action.
  - *− "Arrivals at the port numbered four thousand this week."* (reporting)

### 3.3 Make-work bias
- **Test:** Does the passage treat *labor-saving innovation/efficiency as harmful because it
  reduces employment*, or judge policy mainly by whether it preserves jobs regardless of
  productivity?
- **Counts (+):** lamenting machinery *because* it does the work of many hands; praising a
  measure *only* for "making work"; treating efficiency as a social evil.
  - *+ "The new harvester throws good men out of work; better the field were reaped by hand."*
- **Does NOT count (−):** reporting a layoff; describing a machine neutrally; safety/quality
  critiques of a technology; concern about transition with retraining.
  - *− "The mill installed two electric looms this spring."* (reporting)

### 3.4 Pessimistic bias
- **Test:** Does the passage depict conditions as *worsening, disastrous, or permanently
  precarious beyond what underlying conditions warrant*?
- **Counts (+):** declaring ruin/permanent decline out of proportion to events; catastrophizing
  ordinary fluctuation; "the country is finished" framing.
  - *+ "Trade will never recover; we are sliding into permanent ruin from which there is no
    return."*
- **Does NOT count (−):** **accurate** reporting of a real, severe downturn; sober forecasts;
  describing genuine local hardship.
  - *− "The bank closed Tuesday; depositors gathered at the door."* (accurate report of a
    real event → handled by **excess-pessimism residualization**, not by calling it bias)
- **Special:** because severe events *should* prompt negativity, pessimistic bias is measured
  net of local conditions downstream (residualize against deposits/crop/mortality). The coder
  still labels endorsement of disproportionate doom; the *model output* is later residualized.

---

## 4. Cross-cutting rules

- **Multiple voices.** If the passage relays a view it does not share, use `report`/`quote`;
  reserve `endorse` for the paper's own voice or clearly adopted framing.
- **Wire stories / reprints.** Label by content/stance as written; flag `notes="wire"` if
  identifiable (used to test syndication confounds).
- **Editorials vs news.** Don't assume editorials are always `endorse` or news always
  `report`; judge the text.
- **Advertisements / notices / market tables.** Usually `relevance=0`; never `endorse`.
- **Sarcasm/irony** that argues *against* a bias → `reject`.
- **OCR noise.** If meaning is recoverable, label and set `quality=ocr_noisy`; if not,
  `quality=unusable`, exclude from training/eval.
- **When unsure between `report` and `endorse`,** default to `report` (conservative: avoids
  inflating the bias rate).

---

## 5. Annotation workflow & reliability

1. **Pilot.** Code ~200 passages; meet; resolve disagreements; refine rules; freeze v1.
2. **LLM weak-labeling.** `python/llm_label.py` applies this codebook (see prompt template in
   §6) to the sampled queue → `{relevance, bias_category, stance, intensity}`.
3. **Human audit.** A human labels a **stratified subset** (by bias, era, region) blind to the
   LLM label; compute agreement (Cohen's κ for stance; F1 for relevance). Target κ ≥ 0.6 on
   stance before trusting LLM labels at scale; otherwise refine codebook/prompt and repeat.
4. **Splits.** Build `train/dev/test` split **by title and year** (no title or year in two
   splits) to prevent leakage from house style or era.
5. **Living document.** Every hard case resolved in audit is added to §3 as a new +/−
   example, versioned in git.

---

## 6. LLM labeling prompt template (used by `python/llm_label.py`)

```
SYSTEM: You are a careful research annotator labeling historical U.S. newspaper passages
(c. 1900–1945, possibly noisy OCR) for four economic biases. You apply the codebook exactly.
You distinguish ENDORSEMENT of a biased view from neutral REPORTING, attributed QUOTATION,
and explicit REJECTION. You never treat accurate reporting of real hardship as pessimistic
bias, nor criticism of a specific fraud/monopoly as anti-market bias, nor mentioning
immigration/trade as anti-foreign bias, nor reporting a layoff as make-work bias.

For the passage, return STRICT JSON:
{ "relevance": 0|1,
  "labels": [ {"bias":"anti_market|anti_foreign|make_work|pessimistic",
               "stance":"endorse|report|quote|reject",
               "intensity":0|1|2|3} ],
  "quality":"ok|ocr_noisy|unusable",
  "rationale":"<=25 words" }

Rules: relevance=1 if the passage concerns markets/profit, foreigners/immigration/trade,
labor-saving technology/jobs, or economic conditions/outlook. If relevance=0, labels=[].
A passage may have multiple labels. Only stance="endorse" marks the bias as present.

USER: <passage text>
```

The same definitions, examples, and non-equivalences must appear verbatim in the human
annotation instructions so humans and the LLM are graded against one standard.
