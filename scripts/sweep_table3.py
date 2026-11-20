"""Table III sweep: node2vec hyperparameters vs risk-score quality (paper Sec IV-F, Table III, Figs 5-9).

    python scripts/sweep_table3.py --tier S [--only w3_l8_p1_q1 ...]

Every configuration is trained from scratch on the same 2.5M-node core's induced subgraph (labeled addresses
are core members, as in Table II variant A), then the labeled addresses' embeddings are scored with the
frozen random-forest protocol on node2vec features ONLY (no behavioral features, no has-embedding flag).
Splits are identical across configurations (same seeds), so configurations are compared on paired splits.
The base configuration is repeated with extra training seeds (names ending _s1, _s2, ...) to measure how much
of any difference is training noise rather than signal. Results are written one file per configuration to
results/real_<tier>/sweep/, so an interrupted sweep resumes where it stopped.
Grid (paper Table III): walks {3,6,9} @ length 8; length {4,8,16} @ 3 walks; joint (6,8) (10,10) (9,16);
p {0.25,0.5,1,2,4} and q {0.25,0.5,1,2,4} @ (3 walks, length 8).
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from risksea.config import load_config
from risksea.embed.static_n2v import keys_as_int
from risksea.embed.stream_n2v import StreamingNode2Vec
from risksea.eval.metrics import pr_curve
from risksea.graph.build import induced_subgraph
from risksea.graph.build_duckdb import load_graph
from risksea.model.risk import assemble, fit_eval, multi_seed

ROOT = Path(__file__).resolve().parents[1]
BASE = dict(num_walks=3, walk_length=8, p=1.0, q=1.0)


def name_of(c):
    return f"w{c['num_walks']}_l{c['walk_length']}_p{c['p']:g}_q{c['q']:g}"


def grid():
    cfgs = [dict(BASE)]
    cfgs += [dict(BASE, num_walks=6), dict(BASE, num_walks=9)]                      # varying number of walks
    cfgs += [dict(BASE, walk_length=4), dict(BASE, walk_length=16)]                 # varying length
    cfgs += [dict(num_walks=10, walk_length=10, p=1.0, q=1.0),                      # joint
             dict(num_walks=9, walk_length=16, p=1.0, q=1.0)]
    cfgs += [dict(BASE, p=v) for v in (0.25, 0.5, 2.0, 4.0)]                        # return parameter
    cfgs += [dict(BASE, q=v) for v in (0.25, 0.5, 2.0, 4.0)]                        # in-out parameter
    return cfgs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="S")
    ap.add_argument("--core-size", type=int, default=2_500_000)
    ap.add_argument("--noise-seeds", type=int, default=3, help="extra training seeds for the base configuration")
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()
    cfg = load_config()
    proc = ROOT / "data" / "processed" / a.tier
    out = ROOT / "results" / f"real_{a.tier}" / "sweep"
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    lap = lambda m: print(f"[{time.time() - t0:7.0f}s] {m}", flush=True)

    labels = pd.read_parquet(ROOT / "data" / "labels" / f"labels_{a.tier}.parquet")
    core = np.load(proc / f"core_ids_{a.core_size}.npy")
    g = load_graph(ROOT / "data" / "graph" / a.tier)
    sub = induced_subgraph(g, core)
    lab_nodes = labels.node.to_numpy()
    pos = np.arange(len(labels))
    is_miner = ((labels.label == 0) & (labels.sources == "block_miners")).to_numpy()
    lap(f"core {len(core):,} nodes, subgraph {sub.n_edges:,} entries, {len(labels):,} labeled "
        f"({int(labels.label.sum())} bad)")

    allc = grid()
    jobs = [(name_of(allc[0]), allc[0], 0)]                                   # base configuration first
    jobs += [(f"{name_of(BASE)}_s{k}", dict(BASE), k) for k in range(1, a.noise_seeds + 1)]   # noise estimate early
    jobs += [(name_of(c), c, 0) for c in allc[1:]]
    if a.only:
        jobs = [j for j in jobs if j[0] in a.only]
    for nm, c, train_seed in jobs:
        path = out / f"{nm}.json"
        if path.exists():
            lap(f"{nm}: already done, skipping")
            continue
        lap(f"{nm}: training ({c['num_walks']} walks x length {c['walk_length']}, p={c['p']}, q={c['q']}, seed +{train_seed})")
        t1 = time.time()
        m = StreamingNode2Vec(dim=cfg["node2vec"]["dim"], num_walks=c["num_walks"], walk_length=c["walk_length"],
                              p=c["p"], q=c["q"], window=cfg["node2vec"]["window"],
                              negative=cfg["node2vec"]["negative"], epochs=cfg["node2vec"]["epochs"],
                              workers=a.workers, weighted=True, seed=cfg["seed"] + train_seed, chunk_nodes=100_000)
        m.fit(sub, nodes=core, vocab_nodes=core)
        train_s = time.time() - t1
        ids = keys_as_int(m.model)
        order = np.argsort(ids)
        ids, vecs = ids[order], m.model.wv.vectors[order].astype(np.float32)
        p_ = np.searchsorted(ids, lab_nodes)
        p_[p_ >= len(ids)] = 0
        ok = ids[p_] == lab_nodes
        emb = np.where(ok[:, None], vecs[p_], 0.0).astype(np.float32)
        del m

        res = {"name": nm, "config": c, "train_seed_offset": train_seed, "train_seconds": round(train_s, 1),
               "labeled_embedded": int(ok.sum()), "labeled_total": int(len(ok))}
        for tag, keep in (("all", np.ones(len(labels), bool)), ("no_miners", ~is_miner)):
            keep = keep & ok
            X = assemble(None, emb[keep], ok[keep], np.arange(int(keep.sum()))).drop(columns="has_n2v")
            lab = pd.DataFrame({"node": np.arange(int(keep.sum())), "label": labels.label.to_numpy()[keep]})
            summ, _ = multi_seed(X, lab, cfg)
            res[tag] = {"n_bad": int((lab.label == 1).sum()), "n_good": int((lab.label == 0).sum()), **summ}
            if tag == "all":                                  # PR curve of the first split (Figs 5-9)
                _, _, proba, y_test = fit_eval(X, lab, cfg, cfg["seed"])
                rec, prec = pr_curve(y_test, proba)
                step = max(1, len(rec) // 200)
                res["pr_curve"] = {"recall": rec[::step].round(4).tolist(), "precision": prec[::step].round(4).tolist()}
        path.write_text(json.dumps(res, indent=2))
        s = res["all"]["pr_auc"]
        lap(f"{nm}: trained {train_s:.0f}s, PR-AUC {s['mean']:.3f}±{s['ci95']:.3f}, "
            f"F1 {res['all']['f1']['mean']:.3f}, no-miners PR-AUC {res['no_miners']['pr_auc']['mean']:.3f}")
    lap("sweep complete")


if __name__ == "__main__":
    main()
