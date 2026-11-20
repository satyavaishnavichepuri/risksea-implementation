"""How many of our labeled addresses actually exist in the extracted graph?

    python scripts/label_overlap.py --tier S

Reads data/graph/<tier>/nodes.parquet (addr,id), the OFAC list and the miner addresses, and reports
overlap per source plus the usable label counts after the bad-wins merge. Writes
results/label_overlap_<tier>.json and results/label_audit_<tier>.md (the audit to review).
"""
import argparse
import json
from pathlib import Path

import duckdb
import pandas as pd

from risksea.ingest.labels import audit_markdown, merge_labels, restrict_to_graph, standardize

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="S")
    a = ap.parse_args()
    nodes_pq = ROOT / "data" / "graph" / a.tier / "nodes.parquet"

    ofac = pd.read_csv(ROOT / "data" / "labels" / "ofac_raw" / "sanctioned_addresses_ETH.txt",
                       header=None, names=["address"], dtype=str)
    miners = duckdb.connect().execute(
        f"SELECT address FROM read_parquet('{(ROOT / 'data' / 'raw' / a.tier / 'miners_parts' / 'part-*.parquet').as_posix()}')"
    ).df()
    frames = [standardize(ofac, "ofac_sanctioned", 1), standardize(miners, "block_miners", 0)]
    # eth-labels (Etherscan-derived; see docs/decisions.md D19 for the terms-of-use caveat)
    raw = ROOT / "data" / "labels" / "ethlabels_raw"
    for fname, source, label in (("phish-hack_all.csv", "ethlabels_phish_hack", 1),
                                 ("exchange_all.csv", "ethlabels_exchange", 0)):
        if (raw / fname).exists():
            df = pd.read_csv(raw / fname, dtype=str)
            frames.append(standardize(df, source, label, raw_label_col="nameTag"))
    merged, audit = merge_labels(frames)

    # address -> node id, only for labeled addresses (no need to load all 24M nodes into pandas)
    con = duckdb.connect()
    con.register("lab", merged[["address"]])
    a2n = dict(con.execute(
        f"SELECT n.addr, n.id FROM read_parquet('{nodes_pq.as_posix()}') n JOIN lab ON n.addr = lab.address").fetchall())
    kept, info = restrict_to_graph(merged, a2n)

    per_source = {}
    for src, g in pd.concat(frames).dropna(subset=["address"]).groupby("source"):
        in_graph = g.address.drop_duplicates().isin(a2n).sum()
        per_source[src] = {"labeled": int(g.address.nunique()), "in_graph": int(in_graph)}
    res = {"tier": a.tier, "per_source": per_source, "after_merge": info}
    (ROOT / "results" / f"label_overlap_{a.tier}.json").write_text(json.dumps(res, indent=2))
    (ROOT / "results" / f"label_audit_{a.tier}.md").write_text(audit_markdown(audit, info))
    kept.to_parquet(ROOT / "data" / "labels" / f"labels_{a.tier}.parquet")
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
