"""
Run the multi-LLM jury on the codebook gold/adversarial suite and score it against the
hand-set gold labels. This is the model-independent validity check (no corpus needed):
  - relevance accuracy
  - per-bias ENDORSE precision / recall / F1 (the decisive class)
  - exact-stance accuracy (endorse/report/quote/reject/none)
  - how many passages the panel disagreed on (adjudicated)

Usage:  python eval/run_gold_eval.py
"""
import os, sys, subprocess
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GOLD = os.path.join(HERE, "gold_suite.csv")
OUTDIR = os.path.join(HERE, "gold_out")
QUEUE = os.path.join(OUTDIR, "queue.parquet")
LABEL_JURY = os.path.join(ROOT, "python", "label_jury.py")
BIASES = ["anti_market", "anti_foreign", "make_work", "pessimistic"]

os.makedirs(OUTDIR, exist_ok=True)
gold = pd.read_csv(GOLD)
gold[["id", "text"]].rename(columns={"id": "article_id"}).to_parquet(QUEUE, index=False)
print(f"queue: {len(gold)} gold passages -> {QUEUE}")

# Run the jury end to end (label -> merge -> adjudicate).
subprocess.run([sys.executable, LABEL_JURY, "run", "--queue", QUEUE, "--outdir", OUTDIR,
                "--id-col", "article_id", "--text-col", "text", "--workers", "6"], check=True)

final = pd.read_parquet(os.path.join(OUTDIR, "final.parquet")).set_index("article_id")
g = gold.set_index("id")

def is_endorse(x):
    return 1 if (isinstance(x, str) and x == "endorse") else 0

def norm(x):
    return x if (isinstance(x, str) and x) else "none"

common = [i for i in g.index if i in final.index]
rel_acc = sum(int(int(final.loc[i, "relevance"]) == int(g.loc[i, "relevance"])) for i in common) / len(common)
print(f"\nrelevance accuracy: {rel_acc:.3f}  ({len(common)} passages)")

rows = []
for b in BIASES:
    tp = fp = fn = exact = 0
    for i in common:
        gv, pv = g.loc[i, b], norm(final.loc[i, f"{b}_stance"])
        ge, pe = is_endorse(gv), is_endorse(pv)
        tp += ge and pe; fp += pe and not ge; fn += ge and not pe
        exact += int(pv == gv)
    prec = tp / (tp + fp) if (tp + fp) else float("nan")
    rec = tp / (tp + fn) if (tp + fn) else float("nan")
    f1 = (2 * prec * rec / (prec + rec)) if (prec == prec and rec == rec and (prec + rec)) else float("nan")
    rows.append(dict(bias=b, endorse_TP=tp, FP=fp, FN=fn,
                     precision=round(prec, 3), recall=round(rec, 3), F1=round(f1, 3),
                     stance_exact=f"{exact}/{len(common)}"))
print(pd.DataFrame(rows).to_string(index=False))
print(f"\nadjudicated (panel disagreed): {int((final['confidence'] == 'adjudicated').sum())}/{len(final)}")

# Show the misses (endorse disagreements) for inspection.
print("\n-- endorse misses --")
for b in BIASES:
    for i in common:
        gv, pv = g.loc[i, b], norm(final.loc[i, f"{b}_stance"])
        if is_endorse(gv) != is_endorse(pv):
            print(f"  [{b}] {i}: gold={gv} pred={pv}")
