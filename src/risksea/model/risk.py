"""Risk scoring model (M2.7, paper Sec III-C): random forest over behavioral and/or node2vec features.

The classifier is created through `make_classifier` so it can be swapped later
(gradient boosting, calibration, ...) without touching the evaluation code.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split

from risksea.eval.metrics import compute_metrics, summarize
from risksea.features.behavioral import feature_groups


def make_classifier(cfg: dict, seed: int):
    m = cfg["model"]
    return RandomForestClassifier(n_estimators=m["n_estimators"], class_weight=m["class_weight"],
                                  n_jobs=-1, random_state=seed)


def signed_log1p(df: pd.DataFrame) -> pd.DataFrame:
    """Monotone, sign-preserving compression sign(x)*log1p(|x|). Random forests depend only on the
    ordering of a feature's values, so this loses no information; it removes float32 overflow from
    heavy-tailed amounts (raw ERC-20 units, in/out value ratios; decision D21)."""
    x = df.to_numpy(dtype=np.float64)
    return pd.DataFrame(np.sign(x) * np.log1p(np.abs(x)), index=df.index, columns=df.columns)


def assemble(behavioral: pd.DataFrame | None, emb: np.ndarray | None, emb_mask: np.ndarray | None,
             nodes: np.ndarray, compress: bool = True) -> pd.DataFrame:
    """Feature matrix for `nodes`. Nodes lacking an embedding get zeros (+ a has_n2v flag).
    Behavioral features are compressed with signed_log1p unless compress=False."""
    parts = []
    if behavioral is not None:
        beh = behavioral.loc[nodes].reset_index(drop=True)
        parts.append(signed_log1p(beh) if compress else beh)
    if emb is not None:
        e = pd.DataFrame(emb[nodes], columns=[f"n2v_{i}" for i in range(emb.shape[1])])
        e["has_n2v"] = emb_mask[nodes].astype(float)
        parts.append(e)
    X = pd.concat(parts, axis=1)
    X.index = nodes
    return X


def split(labels: pd.DataFrame, seed: int, test_size: float):
    """80/20 stratified-by-label split over distinct addresses (decision D6)."""
    tr, te = train_test_split(labels["node"].to_numpy(), test_size=test_size, random_state=seed,
                              stratify=labels["label"].to_numpy())
    return tr, te


def fit_eval(X: pd.DataFrame, labels: pd.DataFrame, cfg: dict, seed: int):
    """Train on one split, evaluate on the held-out addresses. Returns (metrics, model, test_proba, y_test)."""
    y = labels.set_index("node")["label"]
    tr, te = split(labels, seed, cfg["model"]["test_size"])
    clf = make_classifier(cfg, seed).fit(X.loc[tr].to_numpy(), y.loc[tr].to_numpy())
    proba = clf.predict_proba(X.loc[te].to_numpy())[:, 1]
    met = compute_metrics(y.loc[te].to_numpy(), proba, cfg["model"]["threshold"])
    return met, clf, proba, y.loc[te].to_numpy()


def multi_seed(X: pd.DataFrame, labels: pd.DataFrame, cfg: dict, n_seeds: int | None = None):
    n_seeds = n_seeds or cfg["model"]["n_seeds"]
    runs = [fit_eval(X, labels, cfg, cfg["seed"] + s)[0] for s in range(n_seeds)]
    return summarize(runs), runs


def grouped_importance(clf, columns) -> dict[str, float]:
    """Sum of RF importances by feature group: behavioral ETH / ERC-20 / node2vec."""
    imp = pd.Series(clf.feature_importances_, index=list(columns))
    groups = feature_groups(columns)
    groups["node2vec"] = [c for c in columns if c.startswith("n2v_") or c == "has_n2v"]
    return {g: float(imp[cols].sum()) for g, cols in groups.items() if cols}
