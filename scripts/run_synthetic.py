"""End-to-end run on the synthetic world (milestone M2 gate).

Produces results/synthetic/*.json|csv: Table-II-style (behavioral / propagated n2v / both),
Table-IV-style (propagation vs DynN2VChain at checkpoints) and coverage stats.
Every number in the output comes from code; nothing is typed by hand.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from risksea.config import load_config, seed_everything
from risksea.embed.dynamic_n2v import train_dynamic
from risksea.embed.propagate import coverage, propagate, sample_core
from risksea.embed.static_n2v import StaticNode2Vec
from risksea.features.behavioral import behavioral_features
from risksea.graph.build import graph_at, induced_subgraph
from risksea.model.risk import assemble, fit_eval, grouped_importance, multi_seed
from risksea.synth import generate_world

OUT = Path(__file__).resolve().parents[1] / "results" / "synthetic"


def main(fast: bool = False):
    cfg = load_config()
    seed_everything(cfg["seed"])
    OUT.mkdir(parents=True, exist_ok=True)
    sc = dict(cfg["synthetic"])
    if fast:
        sc.update(n_blocks=40_000, n_users=800, n_fraud_clusters=12)
    world = generate_world(**sc, seed=cfg["seed"])
    n, tx, labels = len(world.nodes), world.tx, world.labels
    final = world.n_blocks - 1
    cps = [int(final * 0.5), int(final * 0.8), final]
    print(f"nodes={n} tx={len(tx)} labeled={len(labels)} (bad={int(labels.label.sum())})")

    feats = behavioral_features(tx, n, upto_block=final)
    full = graph_at(tx, n, final, cfg["graph"]["top_k_neighbors"])
    nodes = labels["node"].to_numpy()

    # ---- propagation baseline: n2v on core subgraph, then one-hop propagation
    core = sample_core(full, nodes, core_size=int(0.6 * n), seed=cfg["seed"])
    sub = induced_subgraph(full, core)
    prop_model = StaticNode2Vec.from_config(cfg).fit(sub, nodes=core)
    core_emb, core_mask = prop_model.embed(n)
    prop_emb, prop_mask = propagate(core_emb, core_mask, full,
                                    cfg["propagation"]["num_neighbors"], cfg["propagation"]["aggregation"],
                                    seed=cfg["seed"])
    cov = coverage(prop_mask, full)
    print("propagation coverage:", cov)

    # ---- Table II style: behavioral / propagated n2v / both
    rows = {}
    for name, (b, e, m) in {
        "behavioral": (feats, None, None),
        "propagated_n2v": (None, prop_emb, prop_mask),
        "propagated_n2v+behavioral": (feats, prop_emb, prop_mask),
    }.items():
        X = assemble(b, e, m, nodes)
        summ, _ = multi_seed(X, labels, cfg)
        rows[name] = summ
        print(f"{name:28s} F1={summ['f1']['mean']:.3f} P={summ['precision']['mean']:.3f} "
              f"R={summ['recall']['mean']:.3f} PR-AUC={summ['pr_auc']['mean']:.3f}")
    X = assemble(feats, prop_emb, prop_mask, nodes)
    _, clf, _, _ = fit_eval(X, labels, cfg, cfg["seed"])
    imp = grouped_importance(clf, X.columns)
    print("grouped importance:", {k: round(v, 3) for k, v in imp.items()})

    # ---- Table IV style: propagation vs dynamic at checkpoints (n2v features only)
    dyn = train_dynamic(tx, n, cps, step_blocks=max(final // 10, 1), cfg=cfg,
                        top_k=cfg["graph"]["top_k_neighbors"])
    tab4 = {}
    for cp in cps:
        g = graph_at(tx, n, cp, cfg["graph"]["top_k_neighbors"])
        csub = induced_subgraph(g, sample_core(g, nodes, int(0.6 * n), seed=cfg["seed"]))
        cc = sample_core(g, nodes, int(0.6 * n), seed=cfg["seed"])
        pm = StaticNode2Vec.from_config(cfg).fit(csub, nodes=cc)
        ce, cm = pm.embed(n)
        pe, pmask = propagate(ce, cm, g, seed=cfg["seed"])
        s_prop, _ = multi_seed(assemble(None, pe, pmask, nodes), labels, cfg)
        d = dyn[cp]
        s_dyn, _ = multi_seed(assemble(None, d["emb"], d["mask"], nodes), labels, cfg)
        tab4[cp] = {"propagation": s_prop, "dynamic": s_dyn, "dyn_seconds": d["seconds"],
                    "dyn_steps": d["steps"]}
        print(f"checkpoint {cp:>7}: PR-AUC propagation={s_prop['pr_auc']['mean']:.3f} "
              f"dynamic={s_dyn['pr_auc']['mean']:.3f}")

    (OUT / "table2.json").write_text(json.dumps(rows, indent=2))
    (OUT / "table4.json").write_text(json.dumps({str(k): v for k, v in tab4.items()}, indent=2))
    (OUT / "meta.json").write_text(json.dumps({"coverage": cov, "importance": imp,
                                               "nodes": n, "transfers": int(len(tx))}, indent=2))
    print("wrote", OUT)


if __name__ == "__main__":
    main(fast="--fast" in sys.argv)
