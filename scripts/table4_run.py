"""Table IV runner: embeddings for the labeled addresses at each block checkpoint, by one method.

    python scripts/table4_run.py --tier S --method dynamic     --checkpoints 2000000 3500000 5000000
    python scripts/table4_run.py --tier S --method propagation --checkpoints 2000000 3500000 5000000

dynamic     DynN2VChain: static node2vec on the first snapshot, then incremental updates (walks only from
            nodes whose adjacency changed, over the full current graph, warm-started skip-gram), stepping
            every --step-blocks blocks. Embeds every node of the universe that has an edge.
propagation core set (grown from the labeled addresses, labeled addresses excluded, D20) is retrained from
            scratch at each checkpoint on the core's induced subgraph; other addresses get the mean of up to
            5 sampled core neighbors (one hop).
Each method runs in its own process so the two models never share memory. Output:
results/real_<tier>/table4_<method>.npz (present_/emb_/ok_ per checkpoint) and table4_<method>.json (timing, coverage).
Snapshots are unweighted (D22); walks are unweighted accordingly.
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from risksea.config import load_config
from risksea.embed.core import coverage_all, grow_core, propagate_targets
from risksea.embed.static_n2v import keys_as_int
from risksea.embed.stream_n2v import StreamingNode2Vec
from risksea.graph.build import induced_subgraph
from risksea.graph.snapshots import csr_at, delta_nodes, load_adj

ROOT = Path(__file__).resolve().parents[1]


def make_model(cfg, workers):
    c = cfg["node2vec"]
    return StreamingNode2Vec(dim=c["dim"], num_walks=c["num_walks"], walk_length=c["walk_length"], p=c["p"],
                             q=c["q"], window=c["window"], negative=c["negative"], epochs=c["epochs"],
                             workers=workers, weighted=False, seed=cfg["seed"], chunk_nodes=100_000)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="S")
    ap.add_argument("--method", required=True, choices=["dynamic", "propagation"])
    ap.add_argument("--checkpoints", type=int, nargs="+", required=True)
    ap.add_argument("--universe-size", type=int, default=3_000_000)
    ap.add_argument("--core-size", type=int, default=1_000_000)
    ap.add_argument("--step-blocks", type=int, default=500_000)
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()
    cfg = load_config()
    cps = sorted(a.checkpoints)
    t0 = time.time()
    lap = lambda m: print(f"[{time.time() - t0:7.0f}s] {m}", flush=True)

    proc = ROOT / "data" / "processed" / a.tier
    universe = np.load(proc / f"universe_ids_{a.universe_size}.npy")
    labels = pd.read_parquet(ROOT / "data" / "labels" / f"labels_{a.tier}.parquet")
    lab_pos = np.searchsorted(universe, labels.node.to_numpy())
    n = len(universe)
    adj = load_adj(ROOT / "data" / "snapshots" / a.tier / "adj.parquet")
    lap(f"universe {n:,} nodes, adjacency {len(adj['a']):,} entries, {len(lab_pos):,} labeled")

    out_arrays, meta = {}, {"method": a.method, "checkpoints": cps, "universe": n, "per_checkpoint": {}}

    def record(cp, g, emb, ok, extra):
        present = np.asarray(g.degree())[lab_pos] > 0
        out_arrays[f"present_{cp}"], out_arrays[f"emb_{cp}"], out_arrays[f"ok_{cp}"] = present, emb, ok
        meta["per_checkpoint"][str(cp)] = {"seconds_cumulative": round(time.time() - t0, 1),
                                           "labeled_present": int(present.sum()),
                                           "labeled_embedded": int(ok.sum()), **extra}
        lap(f"checkpoint {cp}: present {int(present.sum())}, embedded {int(ok.sum())} {extra}")

    if a.method == "dynamic":
        model = make_model(cfg, a.workers)
        g = csr_at(adj, n, cps[0])
        lap(f"initial snapshot {cps[0]:,}: {int((np.asarray(g.degree()) > 0).sum()):,} nodes with edges; training")
        model.fit(g)
        prev, steps = cps[0], 0

        def snap(cp, g, steps):
            kti = model.model.wv.key_to_index
            idx = np.array([kti.get(str(p), -1) for p in lab_pos], dtype=np.int64)
            ok = idx >= 0
            emb = np.zeros((len(lab_pos), model.dim), dtype=np.float32)
            emb[ok] = model.model.wv.vectors[idx[ok]]
            record(cp, g, emb, ok, {"steps": steps, "vocab": len(kti)})

        snap(cps[0], g, 0)
        for target in cps[1:]:
            for b in list(range(prev + a.step_blocks, target, a.step_blocks)) + [target]:
                g = csr_at(adj, n, b)
                stats = model.update(g, delta_nodes(adj, prev, b))
                prev, steps = b, steps + 1
                lap(f"  step to block {b:,}: {stats}")
            snap(target, g, steps)
    else:
        gF = csr_at(adj, n, cps[-1])
        core = grow_core(gF, lab_pos, a.core_size, seed=cfg["seed"], include_seeds=False)
        lap(f"core: {len(core):,} nodes (labeled addresses excluded)")
        for cp in cps:
            g = csr_at(adj, n, cp)
            cov = coverage_all(g, core)
            sub = induced_subgraph(g, core)
            model = make_model(cfg, a.workers)
            lap(f"checkpoint {cp:,}: training on the core's induced subgraph ({sub.n_edges:,} entries)")
            model.fit(sub, nodes=core, vocab_nodes=core)
            ids = keys_as_int(model.model)
            order = np.argsort(ids)
            emb, ok = propagate_targets(ids[order], model.model.wv.vectors[order].astype(np.float32), g, lab_pos,
                                        cfg["propagation"]["num_neighbors"], cfg["propagation"]["aggregation"],
                                        seed=cfg["seed"])
            record(cp, g, emb, ok, {"core_coverage_of_universe": round(cov["coverage"], 4),
                                    "core_nodes_embedded": int(len(ids))})
            del model

    res = ROOT / "results" / f"real_{a.tier}"
    res.mkdir(parents=True, exist_ok=True)
    np.savez(res / f"table4_{a.method}.npz", **out_arrays)
    (res / f"table4_{a.method}.json").write_text(json.dumps(meta, indent=2))
    lap("done")


if __name__ == "__main__":
    main()
