"""
Multi-provider "jury" labeling for the four economic biases (anti_market,
anti_foreign, make_work, pessimistic).

Design (see docs/plans/01_llm_labeling.md):
  * Independent COMPETITOR LLMs (different families) each label every passage with
    the codebook prompt -> {relevance, per-bias stance}.
  * VOTE-MERGE: where competitors agree, accept (confidence=high); where they split
    -- especially on `endorse`, the decisive class -- mark the passage CONTESTED.
  * ADJUDICATE: Claude resolves only the contested passages, BLIND to provider
    identity (annotators shown as "Annotator A/B/..."). confidence=adjudicated.
  * Fully automated; no human in the loop. Validity is anchored separately by the
    codebook gold/adversarial suite, not a human audit.

All four competitors are reached through the OpenAI-compatible API (OpenAI, Grok via
api.x.ai, Gemini via its OpenAI-compatible endpoint, and the local Llama via Ollama).
The adjudicator (Claude) uses the Anthropic SDK.

Keys are read from an ad-hoc keys file (default %CAPLAN_KEYS_FILE% or
C:\\Users\\jdamm\\Caplan\\LLM\\Keys.env.txt) and never written anywhere.

Stages (subcommands):
  preflight   one tiny call per provider to confirm keys + model names work
  label       run each competitor over a queue.parquet -> labels_<name>.parquet
  merge       combine competitor votes -> merged.parquet (+ contested flag)
  adjudicate  Claude resolves contested rows -> final.parquet
  run         label -> merge -> adjudicate, end to end
"""
from __future__ import annotations
import os, re, json, argparse
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd

BIASES = ["anti_market", "anti_foreign", "make_work", "pessimistic"]
STANCES = ["endorse", "report", "quote", "reject"]

# --- codebook prompt (keep in sync with docs/CODEBOOK.md §6) ---------------------
SYSTEM_PROMPT = """You are a careful research annotator labeling historical U.S. newspaper passages (c. 1770-1964, possibly noisy OCR) for four economic biases. Apply the codebook exactly. Distinguish ENDORSEMENT of a biased view from neutral REPORTING, attributed QUOTATION, and explicit REJECTION. Never treat accurate reporting of real hardship as pessimistic bias, nor criticism of a specific fraud/monopoly as anti-market bias, nor merely mentioning immigration/trade as anti-foreign bias, nor reporting a layoff as make-work bias. Also: supporting trade restrictions/sanctions on GEOPOLITICAL, security, or moral grounds (e.g., embargoing a hostile power in wartime) is NOT anti-foreign bias -- anti-foreign bias is the ECONOMIC view that trade or dealing with foreigners is itself harmful.

Return STRICT JSON only:
{ "relevance": 0|1,
  "labels": [ {"bias":"anti_market|anti_foreign|make_work|pessimistic",
               "stance":"endorse|report|quote|reject",
               "intensity":0|1|2|3} ],
  "quality":"ok|ocr_noisy|unusable",
  "rationale":"<=25 words" }

relevance=1 iff the passage concerns markets/profit, foreigners/immigration/trade, labor-saving technology/jobs, or economic conditions/outlook. If relevance=0, labels=[]. A passage may have multiple labels. Only stance="endorse" marks a bias as present."""

ADJUDICATOR_SYSTEM = """You are the senior adjudicator for a panel of annotators labeling historical U.S. newspaper passages (c. 1770-1964) for four economic biases, under a fixed codebook. The annotators disagreed. Decide the correct label yourself, applying the codebook exactly:
- ENDORSEMENT of a bias is distinct from neutral REPORTING, attributed QUOTATION, and explicit REJECTION; only `endorse` counts as the bias being present.
- Accurate reporting of real hardship is NOT pessimistic bias.
- Criticism of a specific fraud/monopoly is NOT anti-market bias.
- Merely mentioning immigration/trade is NOT anti-foreign bias.
- Reporting a layoff is NOT make-work bias.
- Supporting trade restrictions/sanctions on geopolitical, security, or moral grounds (e.g., embargoing a hostile power in wartime) is NOT anti-foreign bias; anti-foreign bias is the economic view that trade with foreigners is itself harmful.
You are blind to which annotator said what; weigh the passage, not the labels. Return the SAME STRICT JSON schema the annotators used."""

# --- keys ------------------------------------------------------------------------
def load_keys(path: str | None = None) -> dict:
    path = path or os.environ.get("CAPLAN_KEYS_FILE",
                                  r"C:\Users\jdamm\Caplan\LLM\Keys.env.txt")
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        txt = fh.read()

    def grab(pat):
        m = re.search(pat, txt)
        return m.group(0) if m else None

    return {
        "gemini":    grab(r"AIza[0-9A-Za-z\-_]{35}"),
        "openai":    grab(r"sk-proj-[A-Za-z0-9\-_]+"),
        "anthropic": grab(r"sk-ant-[A-Za-z0-9\-_]+"),
        "xai":       grab(r"xai-[A-Za-z0-9\-_]+"),
    }

# --- roster ----------------------------------------------------------------------
@dataclass(frozen=True)
class Competitor:
    name: str
    base_url: str
    key_field: str | None   # which load_keys() field; None => local (Ollama)
    model: str

COMPETITORS = [
    Competitor("openai", "https://api.openai.com/v1",                          "openai", "gpt-4o-mini"),
    Competitor("gemini", "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini", "gemini-2.0-flash"),
    Competitor("grok",   "https://api.x.ai/v1",                                "xai",    "grok-4.20-0309-non-reasoning"),
    Competitor("llama",  "http://localhost:11434/v1",                          None,     "llama3.1:8b"),
]
ADJUDICATOR_MODEL = "claude-sonnet-4-6"

# --- parsing ---------------------------------------------------------------------
def parse_label(raw: str) -> dict:
    """Defensive JSON parse; tolerates code fences and surrounding prose."""
    try:
        s = (raw or "").strip()
        if s.startswith("```"):
            s = s.strip("`")
        if "{" in s and "}" in s:
            s = s[s.find("{"): s.rfind("}") + 1]
        return {"parse_ok": True, **json.loads(s)}
    except Exception:
        return {"parse_ok": False, "raw": raw}

def flatten(obj: dict) -> dict:
    row = {"relevance": obj.get("relevance"),
           "quality": obj.get("quality"),
           "rationale": obj.get("rationale"),
           "parse_ok": obj.get("parse_ok", False)}
    for b in BIASES:
        row[f"{b}_stance"] = None
    for lab in (obj.get("labels") or []):
        b = lab.get("bias")
        if b in BIASES:
            row[f"{b}_stance"] = lab.get("stance")
    return row

# --- callers ---------------------------------------------------------------------
def make_caller(comp: Competitor, keys: dict):
    """Returns f(text)->parsed dict for one OpenAI-compatible competitor."""
    from openai import OpenAI
    api_key = (keys.get(comp.key_field) if comp.key_field else "ollama") or "none"
    client = OpenAI(base_url=comp.base_url, api_key=api_key, timeout=60, max_retries=3)
    user_tmpl = "PASSAGE:\n{}"

    def call(text: str) -> dict:
        kw = dict(model=comp.model, temperature=0, max_tokens=400,
                  messages=[{"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_tmpl.format((text or "")[:6000])}])
        try:
            r = client.chat.completions.create(response_format={"type": "json_object"}, **kw)
        except Exception:
            r = client.chat.completions.create(**kw)   # provider may not support response_format
        return parse_label(r.choices[0].message.content)

    return call

def make_adjudicator(keys: dict, model: str = ADJUDICATOR_MODEL):
    import anthropic
    client = anthropic.Anthropic(api_key=keys["anthropic"])

    def call(text: str, candidates: list[dict]) -> dict:
        lines = []
        for i, c in enumerate(candidates):
            tag = chr(ord("A") + i)
            stances = {b: c.get(f"{b}_stance") for b in BIASES}
            lines.append(f"Annotator {tag}: relevance={c.get('relevance')} "
                         f"stances={stances} rationale={c.get('rationale')!r}")
        user = ("PASSAGE:\n" + (text or "")[:6000] +
                "\n\nThe annotators proposed (identities hidden):\n" + "\n".join(lines) +
                "\n\nDecide the correct label per the codebook. Return STRICT JSON only.")
        msg = client.messages.create(model=model, max_tokens=400, temperature=0,
                                     system=ADJUDICATOR_SYSTEM,
                                     messages=[{"role": "user", "content": user}])
        return parse_label(msg.content[0].text)

    return call

# --- stages ----------------------------------------------------------------------
def cmd_preflight(args):
    keys = load_keys(args.keys)
    print("keys present:", {k: bool(v) for k, v in keys.items()})
    sample = ("The merchant's profit is wrung from the toil of honest men; "
              "trade itself breeds corruption.")
    for comp in COMPETITORS:
        try:
            flat = flatten(make_caller(comp, keys)(sample))
            print(f"  [ok]   {comp.name:7s} ({comp.model}) -> relevance={flat['relevance']} "
                  f"anti_market={flat['anti_market_stance']} parse_ok={flat['parse_ok']}")
        except Exception as e:
            print(f"  [FAIL] {comp.name:7s} ({comp.model}): {type(e).__name__}: {str(e)[:160]}")
    try:
        adj = make_adjudicator(keys, args.adjudicator)
        cand = [flatten(parse_label('{"relevance":1,"labels":[{"bias":"anti_market","stance":"endorse","intensity":2}]}')),
                flatten(parse_label('{"relevance":1,"labels":[{"bias":"anti_market","stance":"report","intensity":0}]}'))]
        res = adj(sample, cand)
        print(f"  [ok]   adjudicator ({args.adjudicator}) -> parse_ok={res.get('parse_ok')} "
              f"anti_market={flatten(res)['anti_market_stance']}")
    except Exception as e:
        print(f"  [FAIL] adjudicator ({args.adjudicator}): {type(e).__name__}: {str(e)[:160]}")

def _label_one_provider(comp, keys, df, id_col, text_col, out_path, workers):
    done = set()
    if os.path.exists(out_path):
        done = set(pd.read_parquet(out_path)[id_col].tolist())
    todo = df[~df[id_col].isin(done)]
    if len(todo) == 0:
        print(f"  {comp.name}: nothing to do ({len(done)} done)")
        return
    caller = make_caller(comp, keys)
    rows = []

    def work(rec):
        try:
            obj = caller(rec[text_col])
        except Exception as e:
            obj = {"parse_ok": False, "raw": f"ERROR: {type(e).__name__}: {e}"}
        return {id_col: rec[id_col], **flatten(obj)}

    recs = todo.to_dict("records")
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, row in enumerate(ex.map(work, recs), 1):
            rows.append(row)
            if i % 50 == 0 or i == len(recs):
                combined = pd.concat(
                    ([pd.read_parquet(out_path)] if os.path.exists(out_path) else []) +
                    [pd.DataFrame(rows)], ignore_index=True
                ).drop_duplicates(subset=[id_col], keep="last")
                combined.to_parquet(out_path, index=False)
                rows = []
                print(f"  {comp.name}: {i}/{len(recs)} labeled")

def cmd_label(args):
    keys = load_keys(args.keys)
    df = pd.read_parquet(args.queue)
    os.makedirs(args.outdir, exist_ok=True)
    only = set(args.providers.split(",")) if args.providers else None
    for comp in COMPETITORS:
        if only and comp.name not in only:
            continue
        out = os.path.join(args.outdir, f"labels_{comp.name}.parquet")
        print(f"[{comp.name}] -> {out}")
        _label_one_provider(comp, keys, df, args.id_col, args.text_col, out, args.workers)

def _vote(stances: list[str | None]) -> tuple[str, bool]:
    """Return (consensus_stance, contested). None => bias absent ('none')."""
    vals = ["none" if s in (None, "", "nan") else s for s in stances]
    n = len(vals)
    endorse = sum(v == "endorse" for v in vals)
    contested = (0 < endorse < n)                          # split on the decisive class
    top = max(set(vals), key=vals.count)
    if vals.count(top) < (0.75 * n):                       # no >=75% majority
        contested = True
    return top, contested

def cmd_merge(args):
    frames = {}
    for comp in COMPETITORS:
        p = os.path.join(args.outdir, f"labels_{comp.name}.parquet")
        if os.path.exists(p):
            frames[comp.name] = pd.read_parquet(p).set_index(args.id_col)
    if not frames:
        raise SystemExit("no labels_*.parquet found; run `label` first")
    ids = sorted(set().union(*[set(f.index) for f in frames.values()]))
    out = []
    for _id in ids:
        cands = {nm: (f.loc[_id].to_dict() if _id in f.index else {}) for nm, f in frames.items()}
        rel_votes = [c.get("relevance") for c in cands.values()]
        rel_top, rel_contested = _vote([str(int(v)) if v in (0, 1) else None for v in rel_votes])
        row = {args.id_col: _id, "relevance": int(rel_top) if rel_top in ("0", "1") else None,
               "n_voters": len(cands)}
        contested = rel_contested
        row["relevance_contested"] = rel_contested
        for b in BIASES:
            stance, c = _vote([cands[nm].get(f"{b}_stance") for nm in cands])
            row[f"{b}_stance"] = stance
            row[f"{b}_contested"] = c
            contested = contested or c
        row["contested"] = contested
        row["confidence"] = "adjudicated" if contested else "high"
        for nm in frames:
            row[f"votes_{nm}"] = json.dumps({b: cands[nm].get(f"{b}_stance") for b in BIASES})
        out.append(row)
    merged = pd.DataFrame(out)
    os.makedirs(args.outdir, exist_ok=True)
    merged.to_parquet(os.path.join(args.outdir, "merged.parquet"), index=False)
    print(f"merged {len(merged)} passages; contested={int(merged['contested'].sum())} "
          f"({100*merged['contested'].mean():.1f}%)")

def cmd_adjudicate(args):
    keys = load_keys(args.keys)
    merged = pd.read_parquet(os.path.join(args.outdir, "merged.parquet"))
    queue = pd.read_parquet(args.queue).set_index(args.id_col)
    adj = make_adjudicator(keys, args.adjudicator)
    final = merged.copy()
    contested = merged[merged["contested"]]
    print(f"adjudicating {len(contested)} contested passages with {args.adjudicator}")
    for pos, (_, r) in enumerate(contested.iterrows(), 1):
        _id = r[args.id_col]
        text = queue.loc[_id, args.text_col] if _id in queue.index else ""
        cands = [json.loads(r[f"votes_{c.name}"]) | {"relevance": r["relevance"]}
                 for c in COMPETITORS if f"votes_{c.name}" in r and pd.notna(r[f"votes_{c.name}"])]
        cands = [{**{f"{b}_stance": d.get(b) for b in BIASES}, "relevance": d.get("relevance")} for d in cands]
        try:
            res = flatten(adj(text, cands))
        except Exception as e:
            print(f"  [warn] {_id}: {type(e).__name__}: {str(e)[:120]}")
            continue
        idx = final.index[final[args.id_col] == _id]
        # Override ONLY the biases that were actually contested; keep the competitor
        # consensus for the rest so adjudication can't clobber agreed-on labels.
        if bool(r.get("relevance_contested", True)):
            final.loc[idx, "relevance"] = res.get("relevance")
        for b in BIASES:
            if bool(r.get(f"{b}_contested", False)):
                final.loc[idx, f"{b}_stance"] = res.get(f"{b}_stance")
        if pos % 25 == 0:
            print(f"  adjudicated {pos}/{len(contested)}")
    final.to_parquet(os.path.join(args.outdir, "final.parquet"), index=False)
    print(f"wrote final.parquet ({len(final)} passages)")

def cmd_run(args):
    cmd_label(args); cmd_merge(args); cmd_adjudicate(args)

# --- CLI -------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    common = dict()
    for name in ("preflight", "label", "merge", "adjudicate", "run"):
        p = sub.add_parser(name)
        p.add_argument("--keys", default=None, help="keys file (default CAPLAN_KEYS_FILE)")
        p.add_argument("--queue", default="queue.parquet")
        p.add_argument("--outdir", default="label_out")
        p.add_argument("--id-col", dest="id_col", default="article_id")
        p.add_argument("--text-col", dest="text_col", default="text")
        p.add_argument("--providers", default=None, help="comma list to restrict competitors")
        p.add_argument("--workers", type=int, default=4)
        p.add_argument("--adjudicator", default=ADJUDICATOR_MODEL)
    args = ap.parse_args()
    {"preflight": cmd_preflight, "label": cmd_label, "merge": cmd_merge,
     "adjudicate": cmd_adjudicate, "run": cmd_run}[args.cmd](args)

if __name__ == "__main__":
    main()
