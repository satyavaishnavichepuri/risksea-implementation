"""Memory-safe global graph build with DuckDB (spills to disk), for real-scale data.

Input : raw edge parts (ETH and ERC-20) with string addresses, as extracted from BigQuery.
Output: out_dir/nodes.parquet   (addr, id)   ids = rank of the address in sorted order (deterministic)
        out_dir/indptr.npy, indices.npy (int32), weights.npy (float32)   -- undirected CSR, each node
        keeping its top-K neighbors by interaction count (decisions D9, D13, paper Sec IV-E)
        out_dir/stats.json

Edge weight of a pair = ETH tx count + ERC-20 transfer count (all tokens). Pair weights are
summed over both directions. Neighbor lists are sorted ascending (required by the walk kernel's
binary-search adjacency test).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import duckdb
import numpy as np
import pyarrow.dataset as ds

from risksea.graph.build import Graph


def build_global_graph(eth_glob: str, erc20_glob: str, out_dir: str | Path, top_k: int = 200,
                       memory_limit: str = "5GB", threads: int = 4, log=print) -> dict:
    """Staged build: every stage reads/writes Parquet so DuckDB's working set stays small.

    Joins use 64-bit address hashes instead of 42-char strings (far less memory); collisions are
    *checked* (distinct hashes must equal distinct addresses) rather than assumed away.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "_duckdb_tmp"
    tmp.mkdir(exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET memory_limit='{memory_limit}'; SET threads={threads}; "
                f"SET temp_directory='{tmp.as_posix()}'; SET preserve_insertion_order=false;")
    t0 = time.time()

    def step(msg):
        log(f"[{time.time() - t0:6.0f}s] {msg}")

    P = lambda name: (out / name).as_posix()
    scratch = []

    # ---- 1. distinct addresses per source column (small, independent passes)
    step("distinct addresses per source column")
    parts = []
    for tag, glob, col in (("eth_src", eth_glob, "src"), ("eth_dst", eth_glob, "dst"),
                           ("erc_src", erc20_glob, "src"), ("erc_dst", erc20_glob, "dst")):
        f = P(f"_addr_{tag}.parquet")
        con.execute(f"COPY (SELECT DISTINCT {col} AS addr FROM read_parquet('{glob}')) TO '{f}' (FORMAT PARQUET)")
        parts.append(f)
        scratch.append(f)
        step(f"  {tag} done")

    # ---- 2. global sorted unique list; id = position in the sorted file (deterministic)
    step("sorted unique address list")
    sorted_pq = P("_addrs_sorted.parquet")
    union = " UNION ".join(f"SELECT addr FROM read_parquet('{f}')" for f in parts)
    con.execute(f"COPY (SELECT addr FROM ({union}) ORDER BY addr) TO '{sorted_pq}' (FORMAT PARQUET)")
    scratch.append(sorted_pq)
    nodes_pq = P("nodes.parquet")
    con.execute(f"""COPY (SELECT addr, CAST(file_row_number AS INTEGER) AS id, hash(addr) AS h
                         FROM read_parquet('{sorted_pq}', file_row_number=true)) TO '{nodes_pq}' (FORMAT PARQUET)""")
    n_nodes, n_hash = con.execute(f"SELECT count(*), count(DISTINCT h) FROM read_parquet('{nodes_pq}')").fetchone()
    if n_hash != n_nodes:
        raise RuntimeError(f"64-bit hash collision among addresses ({n_nodes - n_hash} duplicates); "
                           "switch the join key to a wider hash")
    step(f"{n_nodes:,} nodes (hash keys collision-free)")

    # ---- 3. directed pair weights (ETH + ERC-20), grouped on hash pairs, mapped to ids
    step("directed pair weights")
    pairs_pq = P("_pairs.parquet")
    con.execute(f"""
      COPY (
        SELECT s.id AS a, d.id AS b, p.w
        FROM (SELECT hash(src) AS hs, hash(dst) AS hd, SUM(c) AS w FROM (
                SELECT src, dst, tx_count AS c FROM read_parquet('{eth_glob}')
                UNION ALL SELECT src, dst, tx_count FROM read_parquet('{erc20_glob}'))
              GROUP BY hs, hd) p
        JOIN read_parquet('{nodes_pq}') s ON p.hs = s.h
        JOIN read_parquet('{nodes_pq}') d ON p.hd = d.h
        WHERE s.id <> d.id
      ) TO '{pairs_pq}' (FORMAT PARQUET)""")
    scratch.append(pairs_pq)
    n_pairs = con.execute(f"SELECT count(*) FROM read_parquet('{pairs_pq}')").fetchone()[0]
    step(f"{n_pairs:,} directed pairs")

    # ---- 4. undirected unique pairs (sum both directions)
    step("undirected pairs")
    und_pq = P("_und.parquet")
    con.execute(f"""COPY (SELECT least(a, b) AS lo, greatest(a, b) AS hi, SUM(w) AS w
                          FROM read_parquet('{pairs_pq}') GROUP BY lo, hi) TO '{und_pq}' (FORMAT PARQUET)""")
    scratch.append(und_pq)

    # ---- 5. both orientations, top-K per node. Only nodes with degree > K need ranking.
    step(f"adjacency with top-{top_k} per node")
    adj_pq = P("_adj.parquet")
    adj = (f"(SELECT lo AS a, hi AS b, w FROM read_parquet('{und_pq}') "
           f"UNION ALL SELECT hi, lo, w FROM read_parquet('{und_pq}'))")
    con.execute(f"""
      COPY (
        WITH adj AS {adj},
             big AS (SELECT a FROM adj GROUP BY a HAVING count(*) > {top_k})
        SELECT a, b, CAST(w AS FLOAT) AS w FROM (
          SELECT a, b, w FROM adj WHERE NOT EXISTS (SELECT 1 FROM big WHERE big.a = adj.a)
          UNION ALL
          SELECT a, b, w FROM (
            SELECT a, b, w, row_number() OVER (PARTITION BY a ORDER BY w DESC, b) AS rn
            FROM adj WHERE EXISTS (SELECT 1 FROM big WHERE big.a = adj.a))
          WHERE rn <= {top_k})
        ORDER BY a, b
      ) TO '{adj_pq}' (FORMAT PARQUET)""")
    scratch.append(adj_pq)
    con.close()

    # ---- 6. CSR arrays
    step("CSR arrays")
    dset = ds.dataset(adj_pq)
    n_edges = dset.count_rows()
    a = dset.to_table(columns=["a"]).column(0).to_numpy()
    counts = np.bincount(a, minlength=n_nodes)
    del a
    indptr = np.zeros(n_nodes + 1, dtype=np.int64)
    np.cumsum(counts, out=indptr[1:])
    np.save(out / "indptr.npy", indptr)
    np.save(out / "indices.npy", dset.to_table(columns=["b"]).column(0).to_numpy().astype(np.int32))
    np.save(out / "weights.npy", dset.to_table(columns=["w"]).column(0).to_numpy().astype(np.float32))
    stats = {"nodes": int(n_nodes), "directed_pairs": int(n_pairs), "adjacency_entries": int(n_edges),
             "top_k": top_k, "max_degree_after_cap": int(counts.max()),
             "nodes_with_edges": int((counts > 0).sum()), "seconds": round(time.time() - t0, 1)}
    (out / "stats.json").write_text(json.dumps(stats, indent=2))
    for f in scratch:
        Path(f).unlink(missing_ok=True)
    step(f"done: {stats}")
    return stats


def load_graph(out_dir: str | Path, mmap: bool = True) -> Graph:
    out = Path(out_dir)
    mode = "r" if mmap else None
    indptr = np.load(out / "indptr.npy", mmap_mode=mode)
    return Graph(n=len(indptr) - 1, indptr=indptr,
                 indices=np.load(out / "indices.npy", mmap_mode=mode),
                 weights=np.load(out / "weights.npy", mmap_mode=mode))
