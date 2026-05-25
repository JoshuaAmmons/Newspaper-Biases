"""
LLM weak-labeling of the sampled passages, applying the CODEBOOK
(docs/CODEBOOK.md). Produces structured {relevance, bias, stance, intensity}
labels used to build the RoBERTa training set (rmd/05).

Usage:
    set GEMINI_API_KEY=...            (PowerShell: $env:GEMINI_API_KEY="...")
    python python/llm_label.py --in data_panels/label_queue.parquet \
                               --out data_panels/llm_labels.parquet \
                               --provider gemini --model gemini-2.0-flash

Design notes:
  * The prompt is the codebook's §6 template verbatim — keep them in sync.
  * Output is STRICT JSON per passage; we parse defensively and store raw text on
    parse failure for audit.
  * Checkpoints every N rows so a long run can resume (re-run skips done ids).
  * This produces WEAK labels. A human audits a stratified subset (rmd/05) before
    these are trusted at scale; target Cohen's kappa >= 0.6 on stance.
"""
import os, sys, json, time, argparse
import pandas as pd

SYSTEM_PROMPT = """You are a careful research annotator labeling historical U.S. newspaper passages (c. 1900-1945, possibly noisy OCR) for four economic biases. Apply the codebook exactly. Distinguish ENDORSEMENT of a biased view from neutral REPORTING, attributed QUOTATION, and explicit REJECTION. Never treat accurate reporting of real hardship as pessimistic bias, nor criticism of a specific fraud/monopoly as anti-market bias, nor merely mentioning immigration/trade as anti-foreign bias, nor reporting a layoff as make-work bias.

Return STRICT JSON only:
{ "relevance": 0|1,
  "labels": [ {"bias":"anti_market|anti_foreign|make_work|pessimistic",
               "stance":"endorse|report|quote|reject",
               "intensity":0|1|2|3} ],
  "quality":"ok|ocr_noisy|unusable",
  "rationale":"<=25 words" }

relevance=1 iff the passage concerns markets/profit, foreigners/immigration/trade, labor-saving technology/jobs, or economic conditions/outlook. If relevance=0, labels=[]. A passage may have multiple labels. Only stance="endorse" marks a bias as present."""

def build_prompt(text: str) -> str:
    return SYSTEM_PROMPT + "\n\nPASSAGE:\n" + (text or "")[:6000]

# ---- provider adapters ------------------------------------------------------
def gemini_client(model_name):
    import google.generativeai as genai
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    model = genai.GenerativeModel(model_name)
    def call(text):
        r = model.generate_content(build_prompt(text),
                                   generation_config={"temperature": 0,
                                                      "response_mime_type": "application/json"})
        return r.text
    return call

def anthropic_client(model_name):
    import anthropic
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    def call(text):
        msg = client.messages.create(
            model=model_name, max_tokens=400, temperature=0,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": "PASSAGE:\n" + (text or "")[:6000]}],
        )
        return msg.content[0].text
    return call

def parse_label(raw: str) -> dict:
    """Defensive JSON parse; return dict with a parse_ok flag."""
    try:
        s = raw.strip()
        if s.startswith("```"):
            s = s.strip("`")
            s = s[s.find("{"):s.rfind("}") + 1]
        obj = json.loads(s)
        return {"parse_ok": True, **obj}
    except Exception:
        return {"parse_ok": False, "raw": raw}

def flatten(obj: dict) -> dict:
    """Flatten the nested labels into one row per passage (max-stance per bias)."""
    row = {"relevance": obj.get("relevance"),
           "quality": obj.get("quality"),
           "rationale": obj.get("rationale"),
           "parse_ok": obj.get("parse_ok", False)}
    for b in ["anti_market", "anti_foreign", "make_work", "pessimistic"]:
        row[f"{b}_stance"] = None
        row[f"{b}_intensity"] = 0
    for lab in obj.get("labels", []) or []:
        b = lab.get("bias")
        if b in ("anti_market", "anti_foreign", "make_work", "pessimistic"):
            row[f"{b}_stance"] = lab.get("stance")
            row[f"{b}_intensity"] = lab.get("intensity", 0)
    return row

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", dest="out", required=True)
    ap.add_argument("--provider", default="gemini", choices=["gemini", "anthropic"])
    ap.add_argument("--model", default="gemini-2.0-flash")
    ap.add_argument("--text-col", default="article")
    ap.add_argument("--id-col", default="article_id")
    ap.add_argument("--checkpoint-every", type=int, default=50)
    ap.add_argument("--sleep", type=float, default=0.0, help="seconds between calls (rate limit)")
    args = ap.parse_args()

    df = pd.read_parquet(args.inp)
    done_ids = set()
    if os.path.exists(args.out):
        prev = pd.read_parquet(args.out)
        done_ids = set(prev[args.id_col].tolist())
        print(f"Resuming: {len(done_ids)} already labeled.")
    todo = df[~df[args.id_col].isin(done_ids)].reset_index(drop=True)
    print(f"Labeling {len(todo)} passages with {args.provider}:{args.model}")

    call = gemini_client(args.model) if args.provider == "gemini" else anthropic_client(args.model)

    out_rows, buffer = [], []
    for i, r in todo.iterrows():
        try:
            raw = call(r[args.text_col])
            obj = parse_label(raw)
        except Exception as e:
            obj = {"parse_ok": False, "raw": f"ERROR: {e}"}
        row = {args.id_col: r[args.id_col], **flatten(obj)}
        buffer.append(row)
        if args.sleep:
            time.sleep(args.sleep)
        if len(buffer) >= args.checkpoint_every or i == len(todo) - 1:
            out_rows.extend(buffer)
            combined = pd.concat(
                ([pd.read_parquet(args.out)] if os.path.exists(args.out) else []) +
                [pd.DataFrame(out_rows)], ignore_index=True
            ).drop_duplicates(subset=[args.id_col], keep="last")
            combined.to_parquet(args.out, index=False)
            print(f"  checkpoint: {len(combined)} labeled total")
            out_rows, buffer = [], []

    print(f"Done -> {args.out}")

if __name__ == "__main__":
    main()
