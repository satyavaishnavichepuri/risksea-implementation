"""Behavioral features for the labeled addresses, from the extracted BigQuery feature tables.

    python scripts/real_features.py --tier S
Reads data/labels/labels_<tier>.parquet (address,label,node,...) and data/raw/<tier>/features_{eth,erc20}_parts,
keeps only labeled addresses, widens to one row per node, writes data/processed/<tier>/features_labeled.parquet.
"""
import argparse
from pathlib import Path

import duckdb
import pandas as pd

from risksea.features.behavioral import widen

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="S")
    a = ap.parse_args()
    labels = pd.read_parquet(ROOT / "data" / "labels" / f"labels_{a.tier}.parquet")
    con = duckdb.connect()
    con.register("lab", labels[["address", "node"]])
    frames = []
    for kind in ("eth", "erc20"):
        g = (ROOT / "data" / "raw" / a.tier / f"features_{kind}_parts" / "part-*.parquet").as_posix()
        long = con.execute(f"""
            SELECT lab.node AS addr, f.dir, f.kind, f.n, f.total, f.mean, f.std, f.min, f.max, f.median,
                   f.n_counterparties, f.first_ts, f.last_ts, f.active_days, f.n_tokens, f.gap_mean, f.gap_std
            FROM read_parquet('{g}') f JOIN lab ON f.addr = lab.address""").df()
        print(kind, "rows for labeled addresses:", len(long), "distinct labeled addresses:", long.addr.nunique())
        frames.append(long)
    long = pd.concat(frames, ignore_index=True)
    feats = widen(long, pd.Index(sorted(labels.node.unique()), name="node"))
    out = ROOT / "data" / "processed" / a.tier / "features_labeled.parquet"
    feats.to_parquet(out)
    act = (feats["eth_active"] > 0).sum()
    print(f"features: {feats.shape[0]:,} nodes x {feats.shape[1]} columns; ETH-active {act:,}; "
          f"ERC-20-active {(feats['erc20_active'] > 0).sum():,}; wrote {out}")


if __name__ == "__main__":
    main()
