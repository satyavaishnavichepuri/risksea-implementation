"""Choose the experiment universe and build its time-stamped adjacency (for Table IV).

    python scripts/build_snapshots.py --tier S --universe-size 3000000
Writes data/processed/<tier>/universe_ids.npy and data/snapshots/<tier>/adj.parquet, and prints how many
labeled addresses exist (have an edge) at a range of block checkpoints.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from risksea.config import load_config
from risksea.embed.core import grow_core
from risksea.graph.build_duckdb import load_graph
from risksea.graph.snapshots import build_universe_adj, csr_at, load_adj

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="S")
    ap.add_argument("--universe-size", type=int, default=3_000_000)
    a = ap.parse_args()
    cfg = load_config()
    proc = ROOT / "data" / "processed" / a.tier
    labels = pd.read_parquet(ROOT / "data" / "labels" / f"labels_{a.tier}.parquet")

    uni_path = proc / f"universe_ids_{a.universe_size}.npy"
    if uni_path.exists():
        universe = np.load(uni_path)
    else:
        g = load_graph(ROOT / "data" / "graph" / a.tier)
        universe = grow_core(g, labels.node.to_numpy(), a.universe_size, seed=cfg["seed"], include_seeds=True)
        np.save(uni_path, universe)
    print(f"universe: {len(universe):,} nodes", flush=True)

    raw = ROOT / "data" / "raw" / a.tier
    adj_path = build_universe_adj((raw / "edges_eth_parts" / "part-*.parquet").as_posix(),
                                  (raw / "edges_erc20_parts" / "part-*.parquet").as_posix(),
                                  (ROOT / "data" / "graph" / a.tier / "nodes.parquet").as_posix(), universe,
                                  ROOT / "data" / "snapshots" / a.tier, top_k=cfg["graph"]["top_k_neighbors"],
                                  memory_limit="5GB", threads=4, log=lambda m: print(m, flush=True))
    adj = load_adj(adj_path)
    n = len(universe)
    lab_pos = np.searchsorted(universe, labels.node.to_numpy())
    assert (universe[lab_pos] == labels.node.to_numpy()).all()
    rows = []
    for cut in range(500_000, 5_000_001, 500_000):
        g = csr_at(adj, n, cut)
        present = np.asarray(g.degree())[lab_pos] > 0
        rows.append({"block": cut, "nodes_with_edges": int((np.asarray(g.degree()) > 0).sum()),
                     "adjacency_entries": g.n_edges,
                     "labeled_present": int(present.sum()),
                     "bad_present": int((present & (labels.label.to_numpy() == 1)).sum()),
                     "good_present": int((present & (labels.label.to_numpy() == 0)).sum())})
    df = pd.DataFrame(rows)
    print(df.to_string(index=False), flush=True)
    df.to_csv(proc / "snapshot_presence.csv", index=False)


if __name__ == "__main__":
    main()
