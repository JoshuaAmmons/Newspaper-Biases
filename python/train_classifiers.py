"""
Train the STAGED bias classifiers (see docs/PROJECT_PLAN.md §6.3):

  Stage 1  relevance gate         : binary, is the passage about any of the 4 domains?
  Stage 2  stance heads (4 biases): multi-label, P(endorse {anti_market, anti_foreign,
                                     make_work, pessimistic}) on RELEVANT passages.

Both stages fine-tune RoBERTa with the proven recipe carried over from the companion
project: warmup, weight decay, gradient accumulation (so a 12 GB GPU can train roberta-large
at effective batch 8-16), fp16, early stopping on the best dev metric. We emit dev-set
predictions so R (rmd/06) can fit isotonic calibrators and pick per-bias thresholds.

Usage:
    python python/train_classifiers.py --stage both --base roberta-base
    # roberta-large on a 12 GB card:
    python python/train_classifiers.py --stage both --base roberta-large \
        --batch-size 2 --grad-accum 4

Inputs (built by rmd/05_build_training_set.Rmd), split by title+year to avoid leakage:
    data_panels/train.parquet, dev.parquet, test.parquet
  columns: article_id, text, relevance (0/1),
           y_anti_market, y_anti_foreign, y_make_work, y_pessimistic   (1 == endorse)
Outputs:
    models/roberta_relevance/      models/roberta_stance/
    models/dev_pred_relevance.parquet   models/dev_pred_stance.parquet
    models/test_metrics.json
"""
import os, json, argparse
import numpy as np, pandas as pd
import torch
from datasets import Dataset
from transformers import (AutoTokenizer, AutoModelForSequenceClassification,
                          TrainingArguments, Trainer, DataCollatorWithPadding,
                          EarlyStoppingCallback)
from sklearn.metrics import f1_score, precision_recall_fscore_support, average_precision_score

# Portable root: env var override, else the parent of this script's directory.
ROOT = os.environ.get("CAPLAN_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANELS = os.path.join(ROOT, "data_panels")
MODELS = os.path.join(ROOT, "models")
BIASES = ["anti_market", "anti_foreign", "make_work", "pessimistic"]
MAXLEN = 512
os.makedirs(MODELS, exist_ok=True)

def load_split(name):
    return pd.read_parquet(os.path.join(PANELS, f"{name}.parquet"))

def tokenize_fn(tok):
    return lambda b: tok(b["text"], truncation=True, max_length=MAXLEN)

def make_training_args(out_dir, metric, epochs, bs, lr, grad_accum):
    """Shared proven recipe for both stages."""
    return TrainingArguments(
        output_dir=out_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=bs,
        per_device_eval_batch_size=bs * 2,
        gradient_accumulation_steps=grad_accum,   # effective batch = bs * grad_accum
        learning_rate=lr,
        weight_decay=0.01,
        warmup_ratio=0.1,
        fp16=torch.cuda.is_available(),
        eval_strategy="epoch", save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model=metric, greater_is_better=True,
        save_total_limit=2, logging_steps=25,
        report_to="none", seed=42)

# ---- Stage 1: relevance (binary) -------------------------------------------
def train_relevance(base, epochs, bs, lr, grad_accum):
    tok = AutoTokenizer.from_pretrained(base)
    def to_ds(df):
        d = Dataset.from_pandas(df[["text"]].assign(labels=df["relevance"].astype(int)),
                                preserve_index=False)
        return d.map(tokenize_fn(tok), batched=True)
    tr, dv, te = (to_ds(load_split(s)) for s in ["train", "dev", "test"])
    model = AutoModelForSequenceClassification.from_pretrained(base, num_labels=2)

    def metrics(p):
        pred = p.predictions.argmax(-1)
        pr, rc, f1, _ = precision_recall_fscore_support(p.label_ids, pred,
                                                        average="binary", zero_division=0)
        return {"precision": pr, "recall": rc, "f1": f1}

    trainer = Trainer(
        model=model, args=make_training_args(os.path.join(MODELS, "_tmp_relevance"),
                                             "f1", epochs, bs, lr, grad_accum),
        train_dataset=tr, eval_dataset=dv, tokenizer=tok,
        data_collator=DataCollatorWithPadding(tok), compute_metrics=metrics,
        callbacks=[EarlyStoppingCallback(early_stopping_patience=2)])
    trainer.train()
    trainer.save_model(os.path.join(MODELS, "roberta_relevance"))
    tok.save_pretrained(os.path.join(MODELS, "roberta_relevance"))

    dev_df = load_split("dev")
    probs = torch.softmax(torch.tensor(trainer.predict(dv).predictions), -1)[:, 1].numpy()
    pd.DataFrame({"article_id": dev_df["article_id"], "relevance": dev_df["relevance"],
                  "p_relevance": probs}).to_parquet(
        os.path.join(MODELS, "dev_pred_relevance.parquet"), index=False)
    return {"test": metrics(trainer.predict(te))}

# ---- Stage 2: stance heads (multi-label over 4 biases) ----------------------
def train_stance(base, epochs, bs, lr, grad_accum):
    tok = AutoTokenizer.from_pretrained(base)
    def to_ds(df):
        df = df[df["relevance"] == 1].copy()           # conditional on relevance
        y = df[[f"y_{b}" for b in BIASES]].astype(float).values
        d = Dataset.from_pandas(df[["text"]].assign(labels=list(y)), preserve_index=False)
        return d.map(tokenize_fn(tok), batched=True), df
    (tr, _), (dv, dv_df), (te, te_df) = (to_ds(load_split(s)) for s in ["train", "dev", "test"])
    model = AutoModelForSequenceClassification.from_pretrained(
        base, num_labels=len(BIASES), problem_type="multi_label_classification")

    def metrics(p):
        probs = 1 / (1 + np.exp(-p.predictions))
        out = {}
        for i, b in enumerate(BIASES):
            yt = p.label_ids[:, i]
            out[f"{b}_ap"] = average_precision_score(yt, probs[:, i]) if yt.sum() else float("nan")
            out[f"{b}_f1@.5"] = f1_score(yt, (probs[:, i] > .5).astype(int), zero_division=0)
        out["macro_ap"] = float(np.nanmean([out[f"{b}_ap"] for b in BIASES]))
        return out

    trainer = Trainer(
        model=model, args=make_training_args(os.path.join(MODELS, "_tmp_stance"),
                                             "macro_ap", epochs, bs, lr, grad_accum),
        train_dataset=tr, eval_dataset=dv, tokenizer=tok,
        data_collator=DataCollatorWithPadding(tok), compute_metrics=metrics,
        callbacks=[EarlyStoppingCallback(early_stopping_patience=2)])
    trainer.train()
    trainer.save_model(os.path.join(MODELS, "roberta_stance"))
    tok.save_pretrained(os.path.join(MODELS, "roberta_stance"))

    dev_probs = 1 / (1 + np.exp(-trainer.predict(dv).predictions))
    cols = {"article_id": dv_df["article_id"].values}
    for i, b in enumerate(BIASES):
        cols[f"p_{b}"] = dev_probs[:, i]; cols[f"y_{b}"] = dv_df[f"y_{b}"].values
    pd.DataFrame(cols).to_parquet(os.path.join(MODELS, "dev_pred_stance.parquet"), index=False)
    return {"test": metrics(trainer.predict(te))}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["relevance", "stance", "both"], default="both")
    ap.add_argument("--base", default="roberta-base",
                    help="roberta-base (fast) or roberta-large (stronger, needs more VRAM)")
    ap.add_argument("--epochs", type=int, default=10)   # early stopping ends it sooner
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--grad-accum", type=int, default=1,
                    help="gradient accumulation steps; raise (e.g. 4) for roberta-large on small VRAM")
    ap.add_argument("--lr", type=float, default=2e-5)
    a = ap.parse_args()

    results = {}
    if a.stage in ("relevance", "both"):
        results["relevance"] = train_relevance(a.base, a.epochs, a.batch_size, a.lr, a.grad_accum)
    if a.stage in ("stance", "both"):
        results["stance"] = train_stance(a.base, a.epochs, a.batch_size, a.lr, a.grad_accum)
    with open(os.path.join(MODELS, "test_metrics.json"), "w") as f:
        json.dump(results, f, indent=2)
    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    main()
