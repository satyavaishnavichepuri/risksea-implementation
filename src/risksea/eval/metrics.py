"""Metrics and curves used for every table/figure (M2.7)."""
from __future__ import annotations

import numpy as np
from sklearn.metrics import (auc, average_precision_score, precision_recall_curve,
                             precision_score, recall_score, f1_score, roc_auc_score)


def compute_metrics(y_true, proba, threshold: float = 0.5) -> dict:
    y_true = np.asarray(y_true)
    pred = (np.asarray(proba) >= threshold).astype(int)
    prec, rec, _ = precision_recall_curve(y_true, proba)
    return {
        "precision": float(precision_score(y_true, pred, zero_division=0)),
        "recall": float(recall_score(y_true, pred, zero_division=0)),
        "f1": float(f1_score(y_true, pred, zero_division=0)),
        "pr_auc": float(auc(rec, prec)),               # area under the PR curve
        "avg_precision": float(average_precision_score(y_true, proba)),
        "roc_auc": float(roc_auc_score(y_true, proba)) if len(np.unique(y_true)) > 1 else float("nan"),
    }


def summarize(runs: list[dict]) -> dict:
    """Mean, std and 95% CI half-width (normal approx) of each metric across seeds."""
    out = {}
    for k in runs[0]:
        v = np.array([r[k] for r in runs], dtype=float)
        sd = float(v.std(ddof=1)) if len(v) > 1 else 0.0
        out[k] = {"mean": float(v.mean()), "std": sd,
                  "ci95": float(1.96 * sd / np.sqrt(len(v))) if len(v) > 1 else 0.0}
    return out


def pr_curve(y_true, proba):
    prec, rec, _ = precision_recall_curve(y_true, proba)
    return rec, prec
