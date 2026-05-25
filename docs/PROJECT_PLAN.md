# Project Plan — The Political Economy of Newspaper Bias

**Measuring Anti-Market, Anti-Foreign, Make-Work, and Pessimistic Framing in Historical
American Newspapers, and Estimating the Causal Effect of Shocks on Framing.**

This is the master design document. It states the questions, the theory, the measurement
strategy, the four causal designs (in build order), the econometric specifications, the
five-phase work plan mapped to the pipeline, the robustness program, and the open decisions.

---

## 1. Research questions

1. **Validity.** Can Caplan's four biases be *validly detected* in historical newspaper
   language with a supervised ML framework that separates **stance** (endorse / report /
   reject) from **topic**?
2. **Description.** How common were each of the four biases across American newspapers, over
   time and across space?
3. **Causation.** Did external shocks *causally shift* newspapers toward or away from each
   form of biased framing?

The project's contribution is both **substantive** (new evidence on how the press framed
markets, foreigners, labor-saving technology, and crisis, and how those frames responded to
events) and **methodological** (a reusable template for recovering theory-grounded political-
economic concepts from noisy archival text at scale).

---

## 2. Theory: Caplan's four biases

From Bryan Caplan, *The Myth of the Rational Voter: Why Democracies Choose Bad Policies*
(2007). Caplan argues voters hold *systematically* biased economic beliefs (not random
error). We port his taxonomy from survey beliefs to **newspaper framing**. Operational
definitions (these are the measurement targets; the full coding rules are in
[`CODEBOOK.md`](CODEBOOK.md)):

- **Anti-market bias** — language treating markets, competition, profit, prices, middlemen,
  or voluntary exchange as *socially harmful in themselves*, rather than criticizing a
  specific abuse, fraud, or policy distortion.
- **Anti-foreign bias** — language portraying immigrants, foreign producers, imports, or
  other external actors as *inherently threatening* to domestic prosperity, employment, or
  social order.
- **Make-work bias** — language treating labor-saving innovation, productivity gains, or
  efficiency as *harmful because they reduce employment*, or evaluating policy primarily by
  whether it preserves jobs regardless of productivity.
- **Pessimistic bias** — language depicting the economic condition of a locality, sector, or
  nation as *broadly worsening, disastrous, or permanently precarious in ways that exceed
  what underlying conditions warrant*.

### The central conceptual move: stance, not topic

A newspaper article can mention prices, immigrants, machinery, or hardship **without
endorsing any bias**. The same article can contain multiple voices — it may quote a
politician, reprint a wire story, or describe an argument it rejects. It may also be
*accurately* negative during a genuine crisis. Therefore:

- The unit measured is **endorsement of the bias**, distinguished from neutral reporting,
  quotation, and rejection.
- **Pessimistic bias is not negativity.** **Anti-market bias is not criticism of fraud or
  monopoly.** **Anti-foreign bias is not mentioning trade or immigration.** These non-
  equivalences are the validity backbone of the whole project and must be enforced in the
  codebook, the annotation, and the model evaluation.
- For pessimistic bias (and partly anti-market), the outcome is constructed as **excess**
  bias: the portion of the framing *not* explained by observable local conditions, so that
  accurate reporting of real hardship is not coded as bias (see §6.3).

---

## 3. Data and geographic setting

### 3.1 Text corpus — *American Stories*

`dell-research-harvard/AmericanStories` on Hugging Face: a large, structured, article-level
corpus of OCR'd U.S. newspaper text derived from the Library of Congress *Chronicling
America* collection. We use article **text**, publication **title**, **date**, and the
**LCCN / scan-level metadata** (which carries title information and geonames IDs).

Practical span: the data run 1774–1960. The shock designs concentrate in **~1895–1945**
(when the external shock datasets exist at county resolution), so most analysis years are
1900–1945; earlier years are used for descriptive trends and pre-trend windows.

### 3.2 Geographic anchor — publication county

Inferring a newspaper's *readership territory* (circulation market) is intractable at this
scale. We therefore anchor every newspaper to its **place of publication**, specifically the
**publication county (FIPS)**. This is conservative and practical: it aligns with available
title metadata and lets us merge to county-year and county-month shocks **without speculative
circulation assumptions**.

**Link path:** American Stories `newspaper_name` / LCCN → *Chronicling America* newspaper
title list (downloadable CSV/TXT) and the `loc.gov` API → place of publication → county FIPS.
County FIPS is the join key to every shock dataset. Built in
[`rmd/03_geolink_newspapers.Rmd`](../rmd/03_geolink_newspapers.Rmd).

### 3.3 Panel grain

Default panel: **publication county × year**. Where article volume and shock timing allow
(climate), also build **county × month**. Newspaper-level fixed effects are carried where a
county has multiple titles; otherwise effects are absorbed at the county level. The choice
between newspaper-year and newspaper-month is made per design based on article counts.

---

## 4. The four causal designs (in build order)

Build in this order — ease of clean merge **and** plausibility of identification both
decline down the list. Full source details (URLs, vintages, variables) are in
[`DATA_SOURCES.md`](DATA_SOURCES.md). The shock construction code is in
[`rmd/08_build_shocks.Rmd`](../rmd/08_build_shocks.Rmd); estimation in
[`rmd/09_estimate_did.Rmd`](../rmd/09_estimate_did.Rmd).

### 4.1 Design 1 — Anti-market ← county banking distress, 1920–1936  *(best)*

- **Source.** NHGIS county-level **FDIC Bank Deposit** dataset, 1920–1936 (the same
  underlying series documented by ICPSR Study 7). Already county × year.
- **Treatment.** A sharp fall in county bank deposits. Two definitions:
  - *Continuous/intensity:* year-over-year log deposit change (or % decline).
  - *Binary/staggered:* county enters treatment the first year its deposit decline is in the
    **top decile** nationally (more conservative; gives clean event timing).
- **Controls.** Counties without distress that year, and — in the staggered setup —
  **not-yet-treated** counties.
- **Estimator.** Staggered DiD with heterogeneous timing (Callaway–Sant'Anna; de
  Chaisemartin–D'Haultfœuille; TWFE event study as a benchmark). See §5.
- **Why first.** Conceptually tight fit to anti-market/anti-finance rhetoric; annual timing;
  county geography; genuine untreated / later-treated comparison units rather than relying on
  exposure interactions.
- **Threats.** Deposit decline correlates with real local distress → control for local
  economic conditions; lean on the *endorsement* outcome (criticizing banks ≠ anti-market
  unless markets-as-such are condemned); placebo on pre-period.

### 4.2 Design 2 — Pessimistic ← county weather + mortality shocks  *(strong)*

- **Sources.** NOAA **nClimDiv / nClimGrid** county monthly temperature, precipitation, and
  drought indices (e.g., PDSI), 1895→. NHGIS county **births/deaths** annual, 1915→ (mortality
  / epidemic spikes, incl. the 1918 influenza).
- **Treatment.** Drought episodes, temperature/precipitation anomalies (z-scored vs the
  county's own long-run climatology), and mortality-rate spikes.
- **Estimator.** Paper-**month** DiD for climate shocks; paper-**year** DiD for mortality /
  epidemic shocks. Event-study leads/lags for dynamics.
- **Outcome.** **Excess pessimism** — pessimistic-framing share residualized against
  observable local distress (crop conditions, deposits, mortality), so the design measures
  bias beyond warranted negativity (§6.3).
- **Why strong.** Shocks are external, geographically clean, and flexible on timing.
- **Threats.** Real hardship *should* produce some negativity → residualization is essential;
  migration/attrition of titles during severe droughts (Dust Bowl) → composition checks.

### 4.3 Design 3 — Anti-foreign ← national event × pre-period county exposure

- **Events (fixed, external).** U.S. entry into **WWI, 6 April 1917**; the **Immigration Act
  of 1924** (Johnson–Reed).
- **Exposure (pre-period, county).** WWI × county **German-born share, 1910**; 1924 × county
  **foreign-born** / **southern-and-eastern-European** share just before the act. Exposure
  from **IPUMS Full Count** microdata (available through 1950) or **NHGIS** county census
  tabulations.
- **Design.** No search for "local foreign shocks." The only local ingredient is a
  **pre-period exposure** measure; the event date is common and external. Effects identified
  off **differential exposure**: high-German-born counties vs low, before/after 1917.
- **Controls.** Low-exposure counties (not literally untreated — acceptable because the shock
  is national and the identifying variation is exposure).
- **Estimator.** Exposure-interaction DiD / event study:
  `bias ~ (post_event × exposure) + county FE + year FE`.
- **Start with** WWI × 1910 German-born share (historically sharp, easy to explain).
- **Threats.** Exposure may proxy other county traits → control for baseline covariates,
  pre-trend tests on exposure; the war is a bundle of shocks → interpret as reduced-form
  "exposure to anti-German wartime climate."

### 4.4 Design 4 — Make-work ← county farm mechanization (Census of Agriculture)

- **Source.** NHGIS county **Census of Agriculture** tables, **1925 and 1935** (tractors,
  machinery value, hired labor, crop mix); USDA historical AgCensus archive for the broader
  span.
- **Treatment.** Counties with unusually **large jumps in mechanization** between censuses
  (e.g., tractors per farm, machinery value per acre) vs **low-adoption** counties.
- **Estimator.** DiD comparing high- vs low-mechanization-growth counties around the
  1925→1935 window; event study where intercensal interpolation allows.
- **Caveat.** Easier to *merge* than to *identify* — quinquennial timing is coarse and
  mechanization is endogenous to local conditions. Treat as the **make-work baseline**.
- **Backup design.** **BLS strike / work-stoppage** data (back to the 1880s) for a sharper
  event design, at the cost of city/industry→county location cleaning.

---

## 5. Econometric specifications

Let `Y_{i,t}` be a bias measure (e.g., share of articles endorsing anti-market framing) for
county/newspaper `i` in period `t`.

**(a) Staggered DiD (Designs 1, 2-mortality, 4)** — treatment turns on at county-specific
time `g_i`:
- **TWFE event study (benchmark):** `Y_{it} = α_i + λ_t + Σ_k β_k · 1{t − g_i = k} + ε_it`.
- **Heterogeneity-robust:** Callaway & Sant'Anna group-time ATT (`did`); de Chaisemartin &
  D'Haultfœuille (`DIDmultiplegt` / `did_multiplegt_dyn`); optionally interactive fixed
  effects (`fect`).

**(b) Exposure-interaction DiD (Design 3, national event):**
`Y_{it} = α_i + λ_t + Σ_k β_k · (1{t = year_0 + k} × Exposure_i) + ε_it`,
with `Exposure_i` the pre-period county German-born / foreign-born share. `β_k` for `k<0`
are the pre-trend test.

**(c) Climate paper-month DiD (Design 2-weather):** same as (a) at monthly frequency, with
shocks z-scored against the county's own monthly climatology; cluster by county; include
county-by-calendar-month FE to absorb seasonality.

**Fixed effects & inference.** County (or newspaper) FE absorb time-invariant title/place
differences; period FE absorb national shocks. Cluster standard errors by county (the
treatment-assignment unit). Weight by article volume in robustness, not baseline.

**Outcome construction.** For each bias, run every spec on (i) mean predicted probability,
(ii) share of articles above a calibrated threshold, and (iii) a top-score summary; report
the pre-registered primary (share-above-threshold) and show the others.

---

## 6. Measurement pipeline (text → bias scores)

Uses an LLM-label → fine-tuned-transformer strategy, adapted to a
**staged** architecture because most newspaper text is irrelevant to these biases.

### 6.1 Sampling for labels — [`rmd/04_sample_for_labeling.Rmd`](../rmd/04_sample_for_labeling.Rmd)

Stratified sample across **periods, regions, titles, and likely topic domains**, with
**oversampling of positives** using per-bias **seed lexicons** (see
[`R/helpers.R`](../R/helpers.R)) so each bias has enough positive cases. Lexicons are used
**only for sampling**, never as the final measure.

### 6.2 Labeling & training set — [`rmd/05_build_training_set.Rmd`](../rmd/05_build_training_set.Rmd)

Strategy: **LLM weak-labeling** (`python/llm_label.py`, Gemini/Claude)
applies the codebook to each sampled passage to produce `{relevance, bias_category, stance,
intensity}`; a **human audit** of a stratified subset establishes agreement and corrects
systematic errors; the codebook is refined iteratively (record intercoder/▲human-vs-LLM
reliability). Output: `train / dev / test` splits, split by **title and year** to prevent
leakage.

### 6.3 Models — [`python/train_classifiers.py`](../python/train_classifiers.py)

**Staged classifiers (RoBERTa fine-tuned):**
1. **Relevance gate** — is the passage about one of the four economic-framing domains at all?
2. **Per-bias stance heads** — conditional on relevance, `P(endorse anti-market)`,
   `P(endorse anti-foreign)`, `P(endorse make-work)`, `P(endorse pessimistic)`. A passage may
   be positive for more than one (multi-label).

Staged > single multiclass because the base rate of relevant text is low; a single model
would trade away recall and interpretability. Special handling for **OCR noise**, **historical
semantic drift** (terms shift meaning across 1900–1945), and the **stance vs topic** split.
**Probability calibration** (isotonic, via `R/helpers.R::fit_isotonic`) on the dev
set so aggregated shares are meaningful.

**Excess-bias residualization** (pessimistic, partly anti-market): regress the calibrated
bias share on observable local conditions and use the residual as the outcome, so the design
captures bias *beyond* warranted negativity.

### 6.4 Scoring & aggregation — [`python/score_corpus.py`](../python/score_corpus.py) → [`rmd/07_build_panel.Rmd`](../rmd/07_build_panel.Rmd)

Batched GPU inference over **all** relevant articles → per-article calibrated probabilities →
aggregate to article level then to **county-period**. Compare aggregation rules (mean prob /
share-above-threshold / top-k) and choose by validation performance + interpretability.

---

## 7. Work plan (five phases → pipeline steps)

| Phase | Goal | Pipeline steps | Main output |
|------:|------|----------------|-------------|
| 1 | **Data prep + annotation** — clean corpus, link titles→county, draft & pilot codebook | `01`,`02`,`03`,`04`,`05` | Validated labeled dataset + LCCN→county crosswalk |
| 2 | **Model development** — train/evaluate staged RoBERTa; handle OCR/drift/stance; calibrate | `06` | Validated classifiers + article/county bias measures |
| 3 | **External data integration** — compile shocks, match to publication counties, describe prevalence + merge diagnostics | `08`,`07` | County-period panel merged to 4 shock families |
| 4 | **Causal analysis** — DiD/event studies for the 4 shock families; alt. treatment/control/aggregation; robustness | `09`,`10` | ATT estimates + event studies + robustness |
| 5 | **Dissemination** — paper, documentation of codebook/pipeline/panel, replication package | `11` | Figures/tables (Overleaf) + replication materials |

---

## 8. Robustness & validation program — [`rmd/10_robustness.Rmd`](../rmd/10_robustness.Rmd)

- **Pre-trend / parallel-trends** checks (event-study leads; exposure pre-trends for Design 3).
- **HonestDiD** sensitivity (smoothness + relative-magnitude bounds) — `rmd/10_robustness.Rmd`.
- **Placebo shocks** — fake treatment years; unrelated shock families on the wrong bias.
- **Leave-one-out** jackknife over states/counties (forest plots) — `rmd/10_robustness.Rmd`.
- **Sensitivity to article volume** — weighting, minimum-article-count thresholds, composition.
- **Alternative outcomes** — mean prob vs share-above-threshold vs top-k; raw vs excess.
- **Measurement validation** — held-out test F1/PR by bias; calibration plots; human-vs-model
  agreement; qualitative reads of top-scored passages per bias/era.
- **Merge-quality diagnostics** — LCCN→county match rate, coverage by region/era.

---

## 9. Decisions & open questions

**Decisions made in this scaffold (change in `_config.R` / the relevant step):**
- Geographic anchor = **publication county** (not circulation market).
- Default panel grain = **county-year**; county-month only for climate.
- Labeling = **LLM weak-labels + human audit** (a pragmatic, validation-gated practice),
  not full hand-coding of the training set.
- Model = **staged RoBERTa** (relevance gate + 4 stance heads), multi-label at stage 2.
- Primary outcome = **share of articles above a calibrated threshold**; others shown.
- Build order = bank distress → climate/mortality → WWI/1924 exposure → mechanization.

**Open questions (`TODO(human)`):**
- Final period window per design (data availability vs power).
- Newspaper-year vs newspaper-month cutoffs (depend on realized article counts).
- Which 1924-exposure measure (total foreign-born vs S&E-European share).
- Whether to add the BLS strike backup design for make-work in v1 or v2.
- Annotation: number of labeled passages per bias to hit target dev-set precision.

---

## 10. Risks

| Risk | Mitigation |
|------|------------|
| OCR noise corrupts measurement | OCR-quality filter (`02`), drift-aware training, qualitative audits |
| Low base rate of biased passages | Positive oversampling via seed lexicons; staged relevance gate |
| LCCN→county match gaps | Multiple keys (LCCN, title, geonames); report coverage; manual patches |
| "Bias" conflated with warranted negativity | Stance-based codebook + excess-bias residualization |
| Staggered-DiD bias from TWFE | Use CS / dCDH estimators; event studies; HonestDiD |
| Compute limits | GPU workstation (≥128 GB RAM); per-step subprocess isolation; checkpointed scoring |

---

## 11. Expected contributions

1. **Novel measures** of historically grounded *economic framing* (not generic sentiment or
   broad ideology scores) — theoretically disciplined, empirically scalable.
2. **New causal evidence** on how public discourse responded to shocks: when did papers turn
   more hostile to markets, more suspicious of foreigners, more protective of jobs-for-jobs'-
   sake, or more economically pessimistic?
3. **A reusable computational framework** extensible to other ideological categories and
   historical corpora — anchoring LLMs/transformers in careful conceptualization, human
   annotation, and transparent validation.
