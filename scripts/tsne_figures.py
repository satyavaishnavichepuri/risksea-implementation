"""t-SNE plots of the dynamic node2vec embeddings (paper Figs 11-13) + objective cluster-separation metrics.

    python scripts/tsne_figures.py --tier S [--checkpoint 5000000]

Fig 11: all labeled addresses by group; Fig 12: risky labels only; Fig 13: trusted labels only (each projected
separately, as in the paper). "Visible clusters" is subjective, so each view also gets (a) a silhouette score in the
original 128-d space (cosine) and (b) a 5-nearest-neighbour cross-validated accuracy against the majority-class
baseline, each next to a label-shuffled control (which should sit at ~0 / at the baseline).
"""
import argparse
import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.manifold import TSNE
from sklearn.metrics import balanced_accuracy_score, silhouette_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.neighbors import KNeighborsClassifier

ROOT = Path(__file__).resolve().parents[1]


def risky_category(tag: str) -> str:
    t = (tag or "").lower()
    if "phishing" in t and "token" not in t:
        return "Phishing"
    if t.startswith(("fake", "scam")) or "token deployer" in t:
        return "Fake token / ICO scam"
    if "hack" in t or "exploit" in t:
        return "Hack / exploit"
    return "Other risky"


def separation(X, y, seed=42):
    """silhouette (cosine) and 5-NN CV accuracy for labels y; plus shuffled-label controls."""
    rng = np.random.default_rng(seed)
    out = {}
    classes, counts = np.unique(y, return_counts=True)
    keep = np.isin(y, classes[counts >= 5])
    X, y = X[keep], y[keep]
    cv = StratifiedKFold(5, shuffle=True, random_state=seed)
    for tag, yy in (("real", y), ("shuffled_control", rng.permutation(y))):
        pred = cross_val_predict(KNeighborsClassifier(5, metric="cosine"), X, yy, cv=cv)
        out[tag] = {"silhouette_cosine": float(silhouette_score(X, yy, metric="cosine")),
                    "knn5_accuracy": float((pred == yy).mean()),
                    "knn5_balanced_accuracy": float(balanced_accuracy_score(yy, pred)),
                    "majority_baseline_accuracy": float(counts.max() / counts.sum())}
    out["n"], out["classes"] = int(len(y)), {str(c): int((y == c).sum()) for c in np.unique(y)}
    return out


def plot(Z, y, title, path, palette):
    fig, ax = plt.subplots(figsize=(6.4, 5.2))
    for c in sorted(set(y), key=lambda c: -int((y == c).sum())):
        m = y == c
        ax.scatter(Z[m, 0], Z[m, 1], s=7, alpha=0.65, label=f"{c} (n={int(m.sum())})", color=palette.get(c))
    ax.set(title=title, xticks=[], yticks=[])
    ax.legend(fontsize=8, markerscale=2, loc="best")
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="S")
    ap.add_argument("--checkpoint", type=int, default=5_000_000)
    a = ap.parse_args()
    res = ROOT / "results" / f"real_{a.tier}"
    figdir = ROOT / "results" / "figures"
    figdir.mkdir(parents=True, exist_ok=True)

    labels = pd.read_parquet(ROOT / "data" / "labels" / f"labels_{a.tier}.parquet")
    z = np.load(res / "table4_dynamic.npz")
    emb, ok = z[f"emb_{a.checkpoint}"], z[f"ok_{a.checkpoint}"]
    tags = pd.read_csv(ROOT / "data" / "labels" / "ethlabels_raw" / "phish-hack_all.csv", dtype=str)
    tag_of = dict(zip(tags.address.str.lower().str.strip(), tags.nameTag.fillna("")))

    def group(r):
        if r.sources == "block_miners":
            return "Miner"
        if r.sources == "ethlabels_exchange":
            return "Exchange"
        if r.sources == "ofac_sanctioned":
            return "OFAC sanctioned"
        return risky_category(tag_of.get(r.address, ""))
    labels = labels.assign(group=labels.apply(group, axis=1))
    keep = ok
    L, X = labels[keep].reset_index(drop=True), emb[keep]
    print("embedded labeled addresses:", len(L), "| groups:", L.group.value_counts().to_dict())

    palette = {"Miner": "#9aa0a6", "Exchange": "#1a73e8", "Phishing": "#d93025", "Fake token / ICO scam": "#f29900",
               "Hack / exploit": "#8e24aa", "Other risky": "#e37400", "OFAC sanctioned": "#000000"}
    views = {
        "all": ("Fig. 11 analog: all labeled addresses", L.group.isin(palette)),
        "risky": ("Fig. 12 analog: risky labels only", L.label == 1),
        "trusted": ("Fig. 13 analog: trusted labels only", L.label == 0),
    }
    metrics = {}
    for name, (title, mask) in views.items():
        Xs, ys = X[mask.to_numpy()], L.group[mask].to_numpy()
        Z = TSNE(n_components=2, perplexity=30, init="pca", metric="cosine", random_state=42).fit_transform(Xs)
        plot(Z, ys, f"{title} (t-SNE of node2vec, block {a.checkpoint / 1e6:g}M)", figdir / f"tsne_{name}.png", palette)
        metrics[name] = separation(Xs, ys)
        m = metrics[name]
        print(f"{name:8s} n={m['n']:5d}  5-NN acc real {m['real']['knn5_accuracy']:.3f} (balanced {m['real']['knn5_balanced_accuracy']:.3f}) "
              f"| majority {m['real']['majority_baseline_accuracy']:.3f} | shuffled {m['shuffled_control']['knn5_accuracy']:.3f} "
              f"| silhouette {m['real']['silhouette_cosine']:.3f} (shuffled {m['shuffled_control']['silhouette_cosine']:.3f})")
    # the paper's actual claim is about risk: bad vs good over all labeled addresses
    risk = np.where(L.label.to_numpy() == 1, "bad", "good")
    metrics["all_by_risk_class"] = separation(X, risk)
    m = metrics["all_by_risk_class"]
    print(f"bad-vs-good n={m['n']:5d}  5-NN acc real {m['real']['knn5_accuracy']:.3f} (balanced {m['real']['knn5_balanced_accuracy']:.3f}) "
          f"| majority {m['real']['majority_baseline_accuracy']:.3f} | shuffled {m['shuffled_control']['knn5_accuracy']:.3f} "
          f"| silhouette {m['real']['silhouette_cosine']:.3f} (shuffled {m['shuffled_control']['silhouette_cosine']:.3f})")
    (res / "tsne_metrics.json").write_text(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
