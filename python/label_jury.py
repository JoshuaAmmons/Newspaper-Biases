"""
Multi-provider "jury" labeling for Caplan's four economic biases (anti_market,
anti_foreign, make_work, pessimistic), with a THREE-LEVEL escalation.

Design (codebook prompts live in python/codebook_prompts.py; grounded in Caplan,
The Myth of the Rational Voter):

  Level 1 - CIRCUIT.  All competitor LLMs label every passage with the LEAN prompt
            (Caplan's verbatim definitions + decisive distinctions, ~200 wd/bias).
            If the competitors are UNANIMOUS (same relevance and same stance on every
            bias) the label is accepted -> confidence="high".
  Level 2 - APPEALS.  Any passage with ANY disagreement (even one dissenting vote) is
            re-labeled by ALL competitors again, this time with the FULL Caplan context
            (definitions + his illustrations + his non-instances). If now unanimous ->
            confidence="full_context_consensus".
  Level 3 - SUPREME COURT.  Passages still split after the full-context re-vote go to
            Claude (the adjudicator), with full Caplan context, for the final say. It
            overrides ONLY the biases still contested, keeping consensus on the rest ->
            confidence="adjudicated".

Fully automated; no human in the loop. Validity is anchored by the codebook gold/
adversarial suite (python/eval_gold.py), not a human audit.

All four competitors are reached through the OpenAI-compatible API (OpenAI, Grok via
api.x.ai, Gemini via its OpenAI-compatible endpoint, and local Llama via Ollama). The
adjudicator (Claude) uses the Anthropic SDK with prompt caching on the system block.

Keys are read from an ad-hoc keys file (default %CAPLAN_KEYS_FILE% or
C:\\Users\\jdamm\\Caplan\\LLM\\Keys.env.txt) and never written anywhere.

Subcommands:
  preflight   one tiny call per provider to confirm keys + model names work
  run         the full 3-level escalation, end to end (resumable) -> final.parquet
"""
from __future__ import annotations
import os, re, json, argparse
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import pandas as pd

from codebook_prompts import LEAN_SYSTEM, FULL_SYSTEM, ADJUDICATOR_SYSTEM

BIASES = ["anti_market", "anti_foreign", "make_work", "pessimistic"]
STANCES = ["endorse", "report", "quote", "reject"]

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
ADJUDICATOR_MODEL = "claude-opus-4-7"   # Supreme Court: strongest model, full Caplan context

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
def make_caller(comp: Competitor, keys: dict, system_prompt: str):
    """Returns f(text)->parsed dict for one OpenAI-compatible competitor.
    The static `system_prompt` is the cacheable prefix (OpenAI/xAI auto-cache it)."""
    from openai import OpenAI
    api_key = (keys.get(comp.key_field) if comp.key_field else "ollama") or "none"
    client = OpenAI(base_url=comp.base_url, api_key=api_key, timeout=90, max_retries=3)

    def call(text: str) -> dict:
        kw = dict(model=comp.model, temperature=0, max_tokens=500,
                  messages=[{"role": "system", "content": system_prompt},
                            {"role": "user", "content": "PASSAGE:\n" + (text or "")[:6000]}])
        try:
            r = client.chat.completions.create(response_format={"type": "json_object"}, **kw)
        except Exception:
            r = client.chat.completions.create(**kw)   # provider may not support response_format
        return parse_label(r.choices[0].message.content)

    return call

def make_adjudicator(keys: dict, model: str = ADJUDICATOR_MODEL):
    import anthropic
    client = anthropic.Anthropic(api_key=keys["anthropic"])
    # cache the long Caplan system block (90% cheaper on cache hits across the contested set)
    system_blocks = [{"type": "text", "text": ADJUDICATOR_SYSTEM,
                      "cache_control": {"type": "ephemeral"}}]

    def call(text: str, candidates: list[dict]) -> dict:
        lines = []
        for i, c in enumerate(candidates):
            tag = chr(ord("A") + i)
            stances = {b: c.get(f"{b}_stance") for b in BIASES}
            lines.append(f"Annotator {tag}: relevance={c.get('relevance')} stances={stances}")
        user = ("PASSAGE:\n" + (text or "")[:6000] +
                "\n\nThe annotators (identities hidden) saw full context and still disagreed:\n" +
                "\n".join(lines) +
                "\n\nDecide the correct label per Caplan's definitions. Return STRICT JSON only.")
        # NB: Opus 4.7 (the Supreme Court) deprecates `temperature`; do not send it.
        try:
            msg = client.messages.create(model=model, max_tokens=600,
                                         system=system_blocks,
                                         messages=[{"role": "user", "content": user}])
        except Exception:
            msg = client.messages.create(model=model, max_tokens=600,
                                         system=ADJUDICATOR_SYSTEM,
                                         messages=[{"role": "user", "content": user}])
        return parse_label(msg.content[0].text)

    return call

# --- preflight -------------------------------------------------------------------
def cmd_preflight(args):
    keys = load_keys(args.keys)
    print("keys present:", {k: bool(v) for k, v in keys.items()})
    sample = ("The merchant's profit is wrung from the toil of honest men; "
              "trade itself breeds corruption.")
    for comp in COMPETITORS:
        try:
            flat = flatten(make_caller(comp, keys, LEAN_SYSTEM)(sample))
            print(f"  [ok]   {comp.name:7s} ({comp.model}) -> relevance={flat['relevance']} "
                  f"anti_market={flat['anti_market_stance']} parse_ok={flat['parse_ok']}")
        except Exception as e:
            print(f"  [FAIL] {comp.name:7s} ({comp.model}): {type(e).__name__}: {str(e)[:160]}")
    try:
        adj = make_adjudicator(keys, args.adjudicator)
        cand = [flatten(parse_label('{"relevance":1,"labels":[{"bias":"anti_market","stance":"endorse"}]}')),
                flatten(parse_label('{"relevance":1,"labels":[{"bias":"anti_market","stance":"report"}]}'))]
        res = flatten(adj(sample, cand))
        print(f"  [ok]   adjudicator ({args.adjudicator}) -> parse_ok={res.get('parse_ok')} "
              f"anti_market={res['anti_market_stance']}")
    except Exception as e:
        print(f"  [FAIL] adjudicator ({args.adjudicator}): {type(e).__name__}: {str(e)[:160]}")

# --- one provider over a frame (resumable, checkpointed) -------------------------
def _label_one_provider(comp, keys, df, id_col, text_col, out_path, workers, system_prompt):
    done = set()
    if os.path.exists(out_path):
        done = set(pd.read_parquet(out_path)[id_col].tolist())
    todo = df[~df[id_col].isin(done)]
    if len(todo) == 0:
        print(f"    {comp.name}: nothing to do ({len(done)} done)")
        return
    caller = make_caller(comp, keys, system_prompt)
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
                print(f"    {comp.name}: {i}/{len(recs)} labeled")

def _label_set(df, system_prompt, level_dir, args):
    """Run every competitor over `df` with `system_prompt` -> level_dir/labels_<comp>.parquet."""
    keys = load_keys(args.keys)
    os.makedirs(level_dir, exist_ok=True)
    only = set(args.providers.split(",")) if args.providers else None
    for comp in COMPETITORS:
        if only and comp.name not in only:
            continue
        out = os.path.join(level_dir, f"labels_{comp.name}.parquet")
        print(f"  [{os.path.basename(level_dir)} | {comp.name}] -> {out}")
        _label_one_provider(comp, keys, df, args.id_col, args.text_col, out, args.workers, system_prompt)

# --- voting / merge --------------------------------------------------------------
def _vote_unanimous(votes):
    """Strict unanimity rule: ANY disagreement (even one dissenter) is contested.
    Returns (consensus_value, contested). None/''/'nan' are treated as 'none'."""
    vals = ["none" if v in (None, "", "nan") else v for v in votes]
    top = max(set(vals), key=vals.count)
    contested = len(set(vals)) > 1
    return top, contested

def _merge_level(level_dir, args):
    """Merge a level's competitor labels with the strict-unanimity rule.
    Returns a DataFrame: id, relevance, relevance_contested, <bias>_stance,
    <bias>_contested, contested, n_voters, votes_<comp>."""
    frames = {}
    for comp in COMPETITORS:
        p = os.path.join(level_dir, f"labels_{comp.name}.parquet")
        if os.path.exists(p):
            frames[comp.name] = pd.read_parquet(p).set_index(args.id_col)
    if not frames:
        raise SystemExit(f"no labels_*.parquet found in {level_dir}")
    ids = sorted(set().union(*[set(f.index) for f in frames.values()]))
    out = []
    for _id in ids:
        cands = {nm: (f.loc[_id].to_dict() if _id in f.index else {}) for nm, f in frames.items()}
        rel_top, rel_c = _vote_unanimous([c.get("relevance") for c in cands.values()])
        row = {args.id_col: _id, "n_voters": len(cands),
               "relevance": (None if rel_top == "none" else int(rel_top)),
               "relevance_contested": rel_c}
        contested = rel_c
        for b in BIASES:
            stance, c = _vote_unanimous([cands[nm].get(f"{b}_stance") for nm in cands])
            row[f"{b}_stance"] = (None if stance == "none" else stance)
            row[f"{b}_contested"] = c
            contested = contested or c
        row["contested"] = contested
        for nm in frames:
            row[f"votes_{nm}"] = json.dumps(
                {"relevance": cands[nm].get("relevance"),
                 **{b: cands[nm].get(f"{b}_stance") for b in BIASES}})
        out.append(row)
    return pd.DataFrame(out)

# --- the 3-level run -------------------------------------------------------------
def cmd_run(args):
    os.makedirs(args.outdir, exist_ok=True)
    queue = pd.read_parquet(args.queue)
    qx = queue.set_index(args.id_col)
    keys = load_keys(args.keys)

    # ---------- Level 1: CIRCUIT (lean prompt, whole queue) ----------
    print(f"=== LEVEL 1 (circuit): {len(queue)} passages, lean prompt ===")
    _label_set(queue, LEAN_SYSTEM, os.path.join(args.outdir, "L1"), args)
    m1 = _merge_level(os.path.join(args.outdir, "L1"), args)
    m1.to_parquet(os.path.join(args.outdir, "merged_L1.parquet"), index=False)
    esc1 = m1[m1["contested"]][args.id_col].tolist()
    print(f"  L1 unanimous: {len(m1) - len(esc1)}/{len(m1)} ; escalating {len(esc1)} to Level 2")

    # ---------- Level 2: APPEALS (full context, only L1-contested) ----------
    m2 = None
    if esc1:
        print(f"=== LEVEL 2 (appeals): {len(esc1)} passages, FULL Caplan context ===")
        sub = queue[queue[args.id_col].isin(esc1)]
        _label_set(sub, FULL_SYSTEM, os.path.join(args.outdir, "L2"), args)
        m2 = _merge_level(os.path.join(args.outdir, "L2"), args)
        m2.to_parquet(os.path.join(args.outdir, "merged_L2.parquet"), index=False)
        esc2 = m2[m2["contested"]][args.id_col].tolist()
        print(f"  L2 unanimous: {len(m2) - len(esc2)}/{len(m2)} ; escalating {len(esc2)} to Level 3")
    else:
        esc2 = []

    # ---------- assemble final, overlaying L2 on the escalated ids ----------
    cols = (["relevance", "relevance_contested", "contested"] +
            [f"{b}_stance" for b in BIASES] + [f"{b}_contested" for b in BIASES] +
            [f"votes_{c.name}" for c in COMPETITORS])
    final = m1.set_index(args.id_col).copy()
    final["confidence"] = final["contested"].map(lambda c: "escalated" if c else "high")
    if m2 is not None and len(m2):
        m2x = m2.set_index(args.id_col)
        for _id in m2x.index:
            for col in cols:
                if col in m2x.columns:
                    final.at[_id, col] = m2x.at[_id, col]
            final.at[_id, "confidence"] = ("adjudicated" if bool(m2x.at[_id, "contested"])
                                           else "full_context_consensus")

        # ---------- Level 3: SUPREME COURT (Opus 4.7, full context) ----------
        if esc2:
            print(f"=== LEVEL 3 (supreme court): adjudicating {len(esc2)} with {args.adjudicator} ===")
            contested2 = m2x[m2x["contested"]]
            adj_path = os.path.join(args.outdir, "adjudicated_L3.parquet")  # resumable checkpoint
            done = set()
            if os.path.exists(adj_path):
                done = set(pd.read_parquet(adj_path)[args.id_col].tolist())
            todo = [(i, r) for i, r in contested2.iterrows() if i not in done]
            print(f"  L3: {len(done)} already adjudicated, {len(todo)} to do")
            adj = make_adjudicator(keys, args.adjudicator)
            buf = []
            for pos, (_id, r) in enumerate(todo, 1):
                text = qx.at[_id, args.text_col] if _id in qx.index else ""
                cands = []
                for c in COMPETITORS:
                    col = f"votes_{c.name}"
                    if col in r and pd.notna(r[col]):
                        d = json.loads(r[col])
                        cands.append({**{f"{b}_stance": d.get(b) for b in BIASES},
                                      "relevance": d.get("relevance")})
                try:
                    res = flatten(adj(text, cands))
                except Exception as e:
                    print(f"  [warn] {_id}: {type(e).__name__}: {str(e)[:120]}")
                    continue
                buf.append({args.id_col: _id, "relevance": res.get("relevance"),
                            **{f"{b}_stance": res.get(f"{b}_stance") for b in BIASES}})
                if pos % 25 == 0 or pos == len(todo):
                    adf = pd.concat(([pd.read_parquet(adj_path)] if os.path.exists(adj_path) else []) +
                                    [pd.DataFrame(buf)], ignore_index=True
                                    ).drop_duplicates(subset=[args.id_col], keep="last")
                    adf.to_parquet(adj_path, index=False)
                    buf = []
                    print(f"    adjudicated {len(done) + pos}/{len(contested2)}")
            # apply all adjudications (this run + prior) to final, scoped to contested biases only
            if os.path.exists(adj_path):
                adf = pd.read_parquet(adj_path).set_index(args.id_col)
                for _id, r in contested2.iterrows():
                    if _id not in adf.index:
                        continue
                    a = adf.loc[_id]
                    if bool(r.get("relevance_contested", False)):
                        final.at[_id, "relevance"] = a["relevance"]
                    for b in BIASES:
                        if bool(r.get(f"{b}_contested", False)):
                            final.at[_id, f"{b}_stance"] = a[f"{b}_stance"]

    final = final.reset_index()
    final.to_parquet(os.path.join(args.outdir, "final.parquet"), index=False)
    vc = final["confidence"].value_counts().to_dict()
    print(f"wrote final.parquet ({len(final)} passages) | confidence: {vc}")

# --- CLI -------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("preflight", "run"):
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
    {"preflight": cmd_preflight, "run": cmd_run}[args.cmd](args)

if __name__ == "__main__":
    main()
