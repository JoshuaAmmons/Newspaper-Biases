"""
Gold / adversarial evaluation for the multi-LLM jury (docs/CODEBOOK.md sections 3 and 5).

Runs the FULL jury pipeline (label -> merge -> Claude adjudicates contested) on a small
set of hand-labeled passages with KNOWN answers, then reports, per bias, the precision /
recall / F1 of the decisive `endorse` class, plus relevance accuracy. This is the project's
validity anchor in place of a human audit: if the jury cannot reproduce the codebook's own
+/- examples and the critical non-equivalences (fraud != anti-market, wartime embargo !=
anti-foreign, layoff != make-work, accurate bad news != pessimism), the labels are not
trustworthy and the prompt/codebook must be refined before labeling at scale.

All passages are INVENTED to mimic period phrasing (per CODEBOOK section 0); none are corpus
quotations. Each carries an expected relevance and, for every bias, whether `endorse` is the
correct stance (True) or not (False = absent/report/quote/reject).

Usage:
  python eval_gold.py [--outdir <dir>] [--keys <file>] [--workers N] [--adjudicator MODEL]
"""
from __future__ import annotations
import os, sys, json, shutil, argparse
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import label_jury as lj  # reuse the exact prompts / callers / vote-merge / adjudication

# (id, text, expected_relevance, {bias: endorse_is_correct})
F = False; T = True
GOLD = [
    # --- anti_market ------------------------------------------------------------
    ("AM_pos_profit", "The merchant's profit is wrung from the toil of honest men; trade itself breeds corruption.",
     1, {"anti_market": T}),
    ("AM_pos_speculator", "Speculators are vultures who produce nothing and grow fat upon the ruin of the productive classes.",
     1, {"anti_market": T}),
    ("AM_neg_fraud", "The grand jury indicted the firm for rigging the weighing scales and cheating its customers.",
     1, {"anti_market": F}),                                   # specific fraud, not markets-as-such
    ("AM_neg_report", "Wheat fell three cents on the Chicago exchange yesterday on heavy receipts.",
     1, {"anti_market": F}),                                   # reporting a price change
    ("AM_neg_reject", "Those who call all profit theft forget that honest trade has lifted millions from want.",
     1, {"anti_market": F}),                                   # rejects the anti-market view
    # --- anti_foreign -----------------------------------------------------------
    ("AF_pos_wages", "These newcomers from abroad will undercut our wages and corrupt our free institutions.",
     1, {"anti_foreign": T}),
    ("AF_pos_flood", "Every shipload of foreign laborers is a fresh wound to the American workingman.",
     1, {"anti_foreign": T}),
    ("AF_neg_report", "Arrivals at the port numbered four thousand this week, the collector reported.",
     1, {"anti_foreign": F}),                                  # neutral statistic
    ("AF_pos_sanction_geo", "Congress should embargo all trade with the Kaiser's empire until it ceases its attacks on neutral shipping.",
     1, {"anti_foreign": T}),                                  # RULING (Caplan as arbiter): endorsing a trade restriction is anti-foreign regardless of the (here wartime/security) justification
    ("AF_pos_protection_econ", "Foreign goods are a poison to our prosperity; we must bar all imports, for trade with foreigners only enriches them at our expense.",
     1, {"anti_foreign": T}),                                  # economic view that trade itself is harmful
    ("AF_neg_criticize_act", "The foreign minister's speech was full of bluster, and his government's seizure of the steamer was an outrage.",
     1, {"anti_foreign": F}),                                  # criticizing a foreign govt's specific act, no economic-restriction view -> not the bias
    # --- make_work --------------------------------------------------------------
    ("MW_pos_harvester", "The new harvester throws good men out of work; better the field were reaped by hand.",
     1, {"make_work": T}),
    ("MW_pos_machine", "Every machine that saves labor is an enemy to the laborer; progress that idles men is no progress at all.",
     1, {"make_work": T}),
    ("MW_neg_report", "The mill installed two electric looms this spring to expand its output.",
     1, {"make_work": F}),                                     # neutral description
    ("MW_neg_layoff", "The factory laid off forty hands on Friday owing to slack orders.",
     1, {"make_work": F}),                                     # reporting a layoff
    ("MW_neg_lament", "It is sad to see the old weavers idled by the new looms.",
     1, {"make_work": F}),                                     # RULING: pure sympathy, no anti-efficiency reasoning -> not the bias (the discriminating case)
    ("MW_neg_retrain", "As the mills mechanize, the state should retrain the displaced weavers and tide them over with relief.",
     1, {"make_work": F}),                                     # Caplan: helping the displaced (retraining/relief) is NOT the bias
    ("MW_pos_jobsgoal", "Whatever it builds, the public works bill is worth passing for one reason -- it makes work for idle hands.",
     1, {"make_work": T}),                                     # jobs-as-sole-goal, output irrelevant
    # --- pessimistic ------------------------------------------------------------
    ("PE_pos_ruin", "Trade will never recover; we are sliding into permanent ruin from which there is no return.",
     1, {"pessimistic": T}),
    ("PE_pos_decay", "The nation is doomed; every passing year drags us deeper into hopeless and final decay.",
     1, {"pessimistic": T}),
    ("PE_neg_bank", "The bank closed Tuesday morning; depositors gathered quietly at the door.",
     1, {"pessimistic": F}),                                   # accurate report of a real event
    ("PE_neg_forecast", "Economists expect a mild slowdown next year, with recovery likely by spring.",
     1, {"pessimistic": F}),                                   # sober forecast
    # --- relevance=0 controls (no economic content; all biases absent) ----------
    ("R0_bakesale", "The Ladies' Aid Society will hold a bake sale at the church on Saturday afternoon.",
     0, {}),
    ("R0_wedding", "Miss Clara Bow was wed to Mr. Thompson in a quiet ceremony attended only by family.",
     0, {}),
]


def build_queue(path):
    rows = [{"article_id": g[0], "text": g[1]} for g in GOLD]
    pd.DataFrame(rows).to_parquet(path, index=False)


def expected_frame():
    rows = []
    for _id, _txt, rel, exp in GOLD:
        row = {"article_id": _id, "exp_relevance": rel}
        for b in lj.BIASES:
            row[f"exp_{b}"] = bool(exp.get(b, False))
        rows.append(row)
    return pd.DataFrame(rows)


def prf(tp, fp, fn):
    p = tp / (tp + fp) if (tp + fp) else float("nan")
    r = tp / (tp + fn) if (tp + fn) else float("nan")
    f = 2 * p * r / (p + r) if (p and r and (p + r)) else float("nan")
    return p, r, f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default=os.path.join(os.path.dirname(__file__), "..", "data_panels", "gold_out"))
    ap.add_argument("--keys", default=None)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--adjudicator", default=lj.ADJUDICATOR_MODEL)
    a = ap.parse_args()

    outdir = os.path.abspath(a.outdir)
    if os.path.isdir(outdir):
        shutil.rmtree(outdir)                                  # always a clean run
    os.makedirs(outdir, exist_ok=True)
    queue = os.path.join(outdir, "gold_queue.parquet")
    build_queue(queue)

    # minimal args namespace the cmd_* functions expect
    class A: pass
    args = A()
    args.keys = a.keys; args.queue = queue; args.outdir = outdir
    args.id_col = "article_id"; args.text_col = "text"
    args.providers = None; args.workers = a.workers; args.adjudicator = a.adjudicator

    print(f"=== GOLD EVAL: {len(GOLD)} passages -> {outdir} ===")
    lj.cmd_run(args)   # full 3-level escalation: circuit -> appeals (full context) -> supreme court

    final = pd.read_parquet(os.path.join(outdir, "final.parquet"))
    exp = expected_frame()
    d = exp.merge(final, on="article_id", how="left")

    # relevance accuracy
    d["pred_relevance"] = d["relevance"].fillna(0).astype(int)
    rel_acc = (d["pred_relevance"] == d["exp_relevance"]).mean()

    print("\n--- per-bias endorse precision / recall / F1 ---")
    misses = []
    macro = []
    for b in lj.BIASES:
        pred_pos = d[f"{b}_stance"].eq("endorse")
        exp_pos = d[f"exp_{b}"]
        tp = int((pred_pos & exp_pos).sum())
        fp = int((pred_pos & ~exp_pos).sum())
        fn = int((~pred_pos & exp_pos).sum())
        tn = int((~pred_pos & ~exp_pos).sum())
        p, r, f = prf(tp, fp, fn)
        macro.append(f)
        print(f"  {b:13s} P={p:.2f} R={r:.2f} F1={f:.2f}  (tp={tp} fp={fp} fn={fn} tn={tn})")
        for _, row in d[pred_pos != exp_pos].iterrows():
            kind = "FP" if row[f"{b}_stance"] == "endorse" else "FN"
            misses.append((b, kind, row["article_id"], row.get(f"{b}_stance"),
                           row.get("confidence", "?")))

    print(f"\nrelevance accuracy: {rel_acc:.2f}  ({int((d['pred_relevance']==d['exp_relevance']).sum())}/{len(d)})")
    mac = [m for m in macro if m == m]
    print(f"macro endorse-F1 (biases with support): {sum(mac)/len(mac):.2f}" if mac else "macro F1: n/a")
    print(f"contested/adjudicated: {int(final['contested'].sum())}/{len(final)}")

    if misses:
        print("\n--- misses (inspect; adversarial cases are the point) ---")
        for b, kind, _id, stance, how in misses:
            print(f"  [{kind}] {b:13s} {_id:24s} pred_stance={stance!r:10s} via {how}")
    else:
        print("\nno misses: jury reproduced every gold label.")

    # also dump the full predicted table for eyeballing
    cols = ["article_id", "relevance", "contested", "confidence"] + [f"{b}_stance" for b in lj.BIASES]
    print("\n--- full predictions ---")
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(d[["article_id", "exp_relevance"] + [f"exp_{b}" for b in lj.BIASES]]
              .merge(final[cols], on="article_id", how="left").to_string(index=False))


if __name__ == "__main__":
    main()
