"""
Score the full cleaned corpus with the staged classifiers (batched GPU inference).
Emits RAW probabilities per article; isotonic calibration + thresholds are applied in
rmd/06_score_corpus.Rmd using dev-set fits.

Pipeline per article:
    p_relevance = softmax from roberta_relevance
    if p_relevance >= gate: run roberta_stance -> p_anti_market, p_anti_foreign,
                                                  p_make_work, p_pessimistic
    else: bias probs = 0   (irrelevant text contributes no bias signal)

Robustness carried over from the companion project: fp16 + autocast inference, atomic
per-file writes (.tmp then os.replace) so an interrupted run never leaves a half file, and
GPU memory cleanup between files. Re-running skips years already scored.

Usage:
    python python/score_corpus.py --gate 0.5 --batch-size 64
"""
import os, glob, gc, argparse
import numpy as np, pandas as pd
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification

# Portable root: env var override, else the parent of this script's directory.
ROOT = os.environ.get("CAPLAN_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(ROOT, "models")
BIASES = ["anti_market", "anti_foreign", "make_work", "pessimistic"]
MAXLEN = 512
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

def load(path):
    tok = AutoTokenizer.from_pretrained(path)
    model = AutoModelForSequenceClassification.from_pretrained(path).to(DEVICE).eval()
    if DEVICE == "cuda":
        model = model.half()
    return tok, model

@torch.no_grad()
def batched_probs(texts, tok, model, multilabel, bs):
    out = []
    for i in range(0, len(texts), bs):
        chunk = [t if isinstance(t, str) else "" for t in texts[i:i + bs]]
        enc = tok(chunk, truncation=True, max_length=MAXLEN, padding=True,
                  return_tensors="pt").to(DEVICE)
        if DEVICE == "cuda":
            with torch.autocast("cuda"):
                logits = model(**enc).logits.float()
        else:
            logits = model(**enc).logits.float()
        out.append((torch.sigmoid(logits) if multilabel
                    else torch.softmax(logits, -1)[:, 1]).cpu().numpy())
        del enc, logits
    if DEVICE == "cuda":
        torch.cuda.empty_cache()
    return np.concatenate(out, 0)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=os.path.join(ROOT, "data_parquet/articles_cleaned"))
    ap.add_argument("--out", dest="out", default=os.path.join(ROOT, "data_parquet/articles_scored"))
    ap.add_argument("--text-col", default="article")
    ap.add_argument("--id-col", default="article_id")
    ap.add_argument("--gate", type=float, default=0.5, help="min p_relevance to run stage 2")
    ap.add_argument("--batch-size", type=int, default=64)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    print(f"Device: {DEVICE}")

    tok_r, model_r = load(os.path.join(MODELS, "roberta_relevance"))
    tok_s, model_s = load(os.path.join(MODELS, "roberta_stance"))

    parts = sorted(glob.glob(os.path.join(a.inp, "**", "*.parquet"), recursive=True))
    print(f"{len(parts)} input parts")
    for pf in parts:
        tag = os.path.splitext(os.path.basename(pf))[0]
        outpath = os.path.join(a.out, f"scored_{tag}.parquet")
        if os.path.exists(outpath):
            print(f"  {tag}: already scored, skip"); continue
        df = pd.read_parquet(pf)
        texts = df[a.text_col].fillna("").tolist()
        print(f"  {tag}: {len(texts)} articles")

        p_rel = batched_probs(texts, tok_r, model_r, multilabel=False, bs=a.batch_size)
        bias_probs = np.zeros((len(texts), len(BIASES)), dtype=np.float32)
        idx = np.where(p_rel >= a.gate)[0]
        if len(idx):
            bias_probs[idx] = batched_probs([texts[i] for i in idx], tok_s, model_s,
                                            multilabel=True, bs=a.batch_size)

        res = pd.DataFrame({a.id_col: df[a.id_col].values, "p_relevance": p_rel})
        for j, b in enumerate(BIASES):
            res[f"p_{b}_raw"] = bias_probs[:, j]
        for k in ["lccn", "newspaper_name", "date", "year", "page"]:   # carry join keys
            if k in df.columns:
                res[k] = df[k].values

        tmp = outpath + ".tmp"                  # atomic write
        res.to_parquet(tmp, index=False); os.replace(tmp, outpath)
        print(f"    -> {outpath}  (relevant: {len(idx)}/{len(texts)})")
        del df, res, bias_probs, p_rel; gc.collect()

    print("Scoring complete. Calibrate + threshold in rmd/06_score_corpus.Rmd.")

if __name__ == "__main__":
    main()
