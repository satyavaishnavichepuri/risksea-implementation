"""Time-ordered graph snapshots for the dynamic-node2vec experiments (Table IV).

The extracted edge tables record, per (src, dst) pair, the FIRST block at which it appeared, so a
snapshot at block b is "every pair with first_block <= b". Exact interaction counts per checkpoint are
not available, so snapshots are UNWEIGHTED (decision D22). To keep walks cheap, each node keeps its
top-K neighbors by TOTAL interaction count (as in the global graph); the snapshot then filters that
fixed neighbor set by first block, so the neighbor *choice* uses final counts but edge *existence*
never looks ahead.

Everything is restricted to a "universe" of nodes (a subset that fits in memory at dim 128); node ids
are re-labelled to positions 0..|U|-1 in the sorted universe.
"""
from __future__ import annotations

import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

from risksea.graph.build import Graph


def build_universe_adj(eth_glob: str, erc20_glob: str, nodes_pq: str, universe_ids, out_dir: str | Path,
                       top_k: int = 200, memory_limit: str = "5GB", threads: int = 4, log=print) -> Path:
    """Write out_dir/adj.parquet with columns (a, b, w, fb), both orientations, sorted by (a, b), where
    a, b are universe positions, w the total interaction count, fb the first block of the pair."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "_duckdb_tmp"
    tmp.mkdir(exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET memory_limit='{memory_limit}'; SET threads={threads}; "
                f"SET temp_directory='{tmp.as_posix()}'; SET preserve_insertion_order=false;")
    t0 = time.time()
    step = lambda m: log(f"[{time.time() - t0:6.0f}s] {m}")
    P = lambda name: (out / name).as_posix()

    uni = pd.DataFrame({"id": np.asarray(universe_ids, dtype=np.int32),
                        "pos": np.arange(len(universe_ids), dtype=np.int32)})
    con.register("uni", uni)
    uh = P("_uni_hash.parquet")
    con.execute(f"COPY (SELECT n.h, u.pos FROM read_parquet('{nodes_pq}') n JOIN uni u ON n.id = u.id) "
                f"TO '{uh}' (FORMAT PARQUET)")
    step(f"universe: {len(uni):,} nodes")

    pairs = P("_pairs_u.parquet")
    con.execute(f"""
      COPY (
        SELECT sa.pos AS a, sb.pos AS b, p.w, p.fb
        FROM (SELECT hs, hd, SUM(c) AS w, MIN(fb) AS fb FROM (
                SELECT hash(src) AS hs, hash(dst) AS hd, tx_count AS c, first_block AS fb
                FROM read_parquet('{eth_glob}')
                UNION ALL SELECT hash(src), hash(dst), tx_count, first_block FROM read_parquet('{erc20_glob}'))
              WHERE hs IN (SELECT h FROM read_parquet('{uh}')) AND hd IN (SELECT h FROM read_parquet('{uh}'))
              GROUP BY hs, hd) p
        JOIN read_parquet('{uh}') sa ON p.hs = sa.h
        JOIN read_parquet('{uh}') sb ON p.hd = sb.h
        WHERE sa.pos <> sb.pos
      ) TO '{pairs}' (FORMAT PARQUET)""")
    step(f"{con.execute(f'SELECT count(*) FROM read_parquet({chr(39)}{pairs}{chr(39)})').fetchone()[0]:,} directed pairs inside the universe")

    und = P("_und_u.parquet")
    con.execute(f"""COPY (SELECT least(a, b) AS lo, greatest(a, b) AS hi, SUM(w) AS w, MIN(fb) AS fb
                          FROM read_parquet('{pairs}') GROUP BY lo, hi) TO '{und}' (FORMAT PARQUET)""")

    adj = f"(SELECT lo AS a, hi AS b, w, fb FROM read_parquet('{und}') " \
          f"UNION ALL SELECT hi, lo, w, fb FROM read_parquet('{und}'))"
    con.execute(f"""
      COPY (
        WITH adj AS {adj}, big AS (SELECT a FROM adj GROUP BY a HAVING count(*) > {top_k})
        SELECT a, b, CAST(w AS FLOAT) AS w, CAST(fb AS BIGINT) AS fb FROM (
          SELECT a, b, w, fb FROM adj WHERE NOT EXISTS (SELECT 1 FROM big WHERE big.a = adj.a)
          UNION ALL
          SELECT a, b, w, fb FROM (
            SELECT a, b, w, fb, row_number() OVER (PARTITION BY a ORDER BY w DESC, b) AS rn
            FROM adj WHERE EXISTS (SELECT 1 FROM big WHERE big.a = adj.a))
          WHERE rn <= {top_k})
        ORDER BY a, b
      ) TO '{P('adj.parquet')}' (FORMAT PARQUET)""")
    con.close()
    for f in ("_uni_hash.parquet", "_pairs_u.parquet", "_und_u.parquet"):
        (out / f).unlink(missing_ok=True)
    step("adjacency written")
    return out / "adj.parquet"


def load_adj(path: str | Path) -> dict:
    """Adjacency columns as numpy arrays: a, b (int32), fb (int64)."""
    d = ds.dataset(str(path))
    return {"a": d.to_table(columns=["a"]).column(0).to_numpy().astype(np.int32),
            "b": d.to_table(columns=["b"]).column(0).to_numpy().astype(np.int32),
            "fb": d.to_table(columns=["fb"]).column(0).to_numpy().astype(np.int64)}


def csr_at(adj: dict, n: int, cut: int) -> Graph:
    """Unweighted snapshot: every adjacency entry whose pair first appeared at or before block `cut`."""
    m = adj["fb"] <= cut
    counts = np.bincount(adj["a"][m], minlength=n)
    indptr = np.zeros(n + 1, dtype=np.int64)
    np.cumsum(counts, out=indptr[1:])
    return Graph(n=n, indptr=indptr, indices=adj["b"][m].astype(np.int32),
                 weights=np.ones(int(m.sum()), dtype=np.float32))


def delta_nodes(adj: dict, lo: int, hi: int) -> np.ndarray:
    """Nodes that gained at least one adjacency entry with first block in (lo, hi]."""
    m = (adj["fb"] > lo) & (adj["fb"] <= hi)
    return np.unique(adj["a"][m]).astype(np.int64)
