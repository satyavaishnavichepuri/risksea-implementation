"""Table II on real data: behavioral vs propagated node2vec vs both (paper Sec IV-A, Table II).

    python scripts/table2_real.py --tier S --core-size 2500000 --emb core_emb_full.npz [--noseeds] [--no-miners]

Embeddings for the labeled addresses come from `propagate_targets` (core members keep their trained
vector; others average up to 5 sampled core neighbors). Everything printed is computed from files;
results are also written to results/real_<tier>/table2_<name>.json.
--no-miners drops block-miner addresses from the good class (they are structurally unusual and make
bad-vs-good easier than the paper's setting, so we report with and without them).
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from risksea.config import load_config
from risksea.embed.core import propagate_targets
from risksea.graph.build_duckdb import load_graph
from risksea.model.risk import assemble, fit_eval, grouped_importance, multi_seed

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="S")
    ap.add_argument("--core-size", type=int, default=2_500_000)
    ap.add_argument("--emb", default="core_emb_full.npz")
    ap.add_argument("--noseeds", action="store_true")
    ap.add_argument("--no-miners", action="store_true")
    ap.add_argument("--name", default=None)
    ap.add_argument("--no-flag", action="store_true", help="drop the has_n2v indicator (it can leak the label)")
    ap.add_argument("--covered-only", action="store_true", help="evaluate only addresses that have an embedding")
    a = ap.parse_args()
    cfg = load_config()
    proc = ROOT / "data" / "processed" / a.tier
    name = a.name or (("B_noseeds" if a.noseeds else "A_seeds") + ("_nominers" if a.no_miners else "")
                      + ("_noflag" if a.no_flag else "") + ("_coveredonly" if a.covered_only else ""))

    labels = pd.read_parquet(ROOT / "data" / "labels" / f"labels_{a.tier}.parquet")
    if a.no_miners:
        labels = labels[~((labels.label == 0) & (labels.sources == "block_miners"))]
    labels = labels.reset_index(drop=True)
    feats = pd.read_parquet(proc / "features_labeled.parquet")
    z = np.load(proc / a.emb)
    g = load_graph(ROOT / "data" / "graph" / a.tier)

    nodes = labels["node"].to_numpy()
    emb, ok = propagate_targets(z["ids"], z["vecs"], g, nodes, cfg["propagation"]["num_neighbors"],
                                cfg["propagation"]["aggregation"], seed=cfg["seed"])
    if a.covered_only:                      # keep only addresses that actually have an embedding
        keep = ok
        labels, nodes, emb, ok = labels[keep].reset_index(drop=True), nodes[keep], emb[keep], ok[keep]
    in_core = np.isin(nodes, z["ids"])
    print(f"[{name}] labeled {len(nodes):,}: bad {int(labels.label.sum()):,}, good {int((labels.label == 0).sum()):,}")
    print(f"[{name}] embedding available for {ok.mean():.1%} of labeled (in core: {in_core.mean():.1%}, "
          f"propagated: {(ok & ~in_core).mean():.1%}); "
          f"bad covered {ok[labels.label == 1].mean():.1%}, good covered {ok[labels.label == 0].mean():.1%}")

    # positional re-indexing so assemble() can take compact embeddings
    pos = np.arange(len(labels))
    lab_pos = pd.DataFrame({"node": pos, "label": labels["label"].to_numpy()})
    beh = feats.loc[nodes].reset_index(drop=True)
    sets = {"behavioral": (beh, None, None),
            "propagated_n2v": (None, emb, ok),
            "propagated_n2v+behavioral": (beh, emb, ok)}
    res = {"name": name, "n_bad": int(labels.label.sum()), "n_good": int((labels.label == 0).sum()),
           "embedding_available": float(ok.mean()), "metrics": {}}
    for k, (b, e, m) in sets.items():
        X = assemble(b, e, m, pos)
        if a.no_flag and "has_n2v" in X.columns:
            X = X.drop(columns="has_n2v")
        summ, _ = multi_seed(X, lab_pos, cfg)
        res["metrics"][k] = summ
        f = lambda key: f"{summ[key]['mean']:.3f}±{summ[key]['ci95']:.3f}"
        print(f"[{name}] {k:28s} P={f('precision')} R={f('recall')} F1={f('f1')} PR-AUC={f('pr_auc')} ROC-AUC={f('roc_auc')}")
    X = assemble(beh, emb, ok, pos)
    if a.no_flag:
        X = X.drop(columns="has_n2v")
    _, clf, _, _ = fit_eval(X, lab_pos, cfg, cfg["seed"])
    res["importance"] = grouped_importance(clf, X.columns)
    print(f"[{name}] grouped importance:", {k: round(v, 3) for k, v in res["importance"].items()})

    out = ROOT / "results" / f"real_{a.tier}"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"table2_{name}.json").write_text(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
