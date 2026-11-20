"""Select the core set, train node2vec on its induced subgraph, save compact core embeddings.

    python scripts/train_core.py --tier S --core-size 2500000 [--timing-starts 100000] [--tag full]

Stages are cached on disk (core_ids.npy), so reruns skip the expensive selection.
--timing-starts N starts walks from only N core nodes (vocabulary still covers the whole core) and
reports throughput, so the full run's cost can be estimated before it is launched.
Output: data/processed/<tier>/core_emb_<tag>.npz  (ids sorted ascending, vecs aligned, float32)
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from risksea.config import load_config
from risksea.embed.core import coverage_all, grow_core
from risksea.embed.static_n2v import keys_as_int
from risksea.embed.stream_n2v import StreamingNode2Vec
from risksea.graph.build import induced_subgraph
from risksea.graph.build_duckdb import load_graph

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="S")
    ap.add_argument("--core-size", type=int, default=2_500_000)
    ap.add_argument("--timing-starts", type=int, default=None)
    ap.add_argument("--tag", default="full")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--exclude-seeds", action="store_true",
                    help="keep labeled addresses OUT of the core (they get propagated embeddings, D20)")
    a = ap.parse_args()
    cfg = load_config()
    proc = ROOT / "data" / "processed" / a.tier
    t0 = time.time()
    lap = lambda m: print(f"[{time.time() - t0:7.0f}s] {m}", flush=True)

    g = load_graph(ROOT / "data" / "graph" / a.tier)
    lap(f"graph loaded: {g.n:,} nodes")
    suffix = "_noseeds" if a.exclude_seeds else ""
    core_path = proc / f"core_ids_{a.core_size}{suffix}.npy"
    if core_path.exists():
        core = np.load(core_path)
    else:
        seeds = pd.read_parquet(ROOT / "data" / "labels" / f"labels_{a.tier}.parquet")["node"].to_numpy()
        core = grow_core(g, seeds, a.core_size, seed=cfg["seed"], include_seeds=not a.exclude_seeds)
        np.save(core_path, core)
    lap(f"core: {len(core):,} nodes")
    cov = coverage_all(g, core)
    lap(f"one-hop coverage of the whole graph: {cov}")
    (proc / f"coverage_{a.core_size}{suffix}.json").write_text(json.dumps(cov, indent=2))

    sub = induced_subgraph(g, core)
    lap(f"induced subgraph: {sub.n_edges:,} adjacency entries; core nodes with edges in subgraph: "
        f"{int((np.asarray(sub.degree())[core] > 0).sum()):,}")

    n2v = StreamingNode2Vec.from_config(cfg)
    n2v.workers = a.workers
    n2v.chunk_nodes = 100_000
    starts = core if a.timing_starts is None else core[:: max(1, len(core) // a.timing_starts)][: a.timing_starts]
    lap(f"training: {len(starts):,} start nodes x {n2v.num_walks} walks x length {n2v.walk_length}, dim {n2v.dim}")
    t1 = time.time()
    n2v.fit(sub, nodes=starts, vocab_nodes=core)
    train_s = time.time() - t1
    tokens = len(starts) * n2v.num_walks * n2v.walk_length
    lap(f"trained in {train_s:.0f}s  ({tokens / train_s:,.0f} tokens/s)")
    if a.timing_starts is not None:
        full_tokens = len(core) * n2v.num_walks * n2v.walk_length
        print(json.dumps({"timing_starts": len(starts), "seconds": round(train_s, 1),
                          "tokens_per_s": round(tokens / train_s),
                          "estimated_full_seconds": round(full_tokens / (tokens / train_s)),
                          "estimated_full_hours": round(full_tokens / (tokens / train_s) / 3600, 2)}, indent=2))
    keys = keys_as_int(n2v.model)
    order = np.argsort(keys)
    np.savez(proc / f"core_emb_{a.tag}.npz", ids=keys[order], vecs=n2v.model.wv.vectors[order].astype(np.float32))
    lap(f"saved {len(keys):,} embeddings -> core_emb_{a.tag}.npz")


if __name__ == "__main__":
    main()
