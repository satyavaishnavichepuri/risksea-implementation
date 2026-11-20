"""Behavioral features (M2.2): per-address statistics of amount, timing and frequency.

Computed separately for ETH and ERC-20 transfers, split into incoming and outgoing,
as the paper describes (Sec III-B1). The paper's feature list ("Table 1") is missing,
so this is our own list (decision D1). Computed in DuckDB so the same SQL scales to
the real transfer tables. Only transfers with block <= upto_block are used (no leakage).
"""
from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd

KINDS = ("eth", "erc20")
DIRS = ("in", "out")

_SQL = """
WITH ev AS (
  SELECT src AS addr, 'out' AS dir, kind, ts, value, dst AS cp, token FROM tx WHERE block <= {upto}
  UNION ALL
  SELECT dst AS addr, 'in'  AS dir, kind, ts, value, src AS cp, token FROM tx WHERE block <= {upto}
),
gaps AS (
  SELECT addr, dir, kind,
         ts - lag(ts) OVER (PARTITION BY addr, dir, kind ORDER BY ts) AS gap
  FROM ev
),
gap_stats AS (
  SELECT addr, dir, kind, avg(gap) AS gap_mean, coalesce(stddev_pop(gap), 0) AS gap_std
  FROM gaps WHERE gap IS NOT NULL GROUP BY addr, dir, kind
),
agg AS (
  SELECT addr, dir, kind,
         count(*) AS n,
         sum(value) AS total,
         avg(value) AS mean,
         coalesce(stddev_pop(value), 0) AS std,
         min(value) AS min,
         max(value) AS max,
         quantile_cont(value, 0.5) AS median,
         count(DISTINCT cp) AS n_counterparties,
         min(ts) AS first_ts,
         max(ts) AS last_ts,
         count(DISTINCT CAST(ts / 86400 AS BIGINT)) AS active_days,
         count(DISTINCT token) AS n_tokens
  FROM ev GROUP BY addr, dir, kind
)
SELECT a.*, coalesce(g.gap_mean, 0) AS gap_mean, coalesce(g.gap_std, 0) AS gap_std
FROM agg a LEFT JOIN gap_stats g USING (addr, dir, kind)
"""

_STATS = ["n", "total", "mean", "std", "min", "max", "median", "n_counterparties",
          "active_days", "gap_mean", "gap_std", "span", "tx_per_active_day", "burstiness"]


def widen(long: pd.DataFrame, index) -> pd.DataFrame:
    """Long per-(address, dir, kind) statistics -> one wide feature row per address in `index`.

    `long` needs columns addr, dir, kind and the stats produced by the SQL (local DuckDB or the
    BigQuery extraction, which share the same column names). Addresses without activity get zeros.
    """
    long = long.copy()
    long["span"] = long["last_ts"] - long["first_ts"]
    long["tx_per_active_day"] = long["n"] / long["active_days"].clip(lower=1)
    denom = long["gap_std"] + long["gap_mean"]
    # Goh-Barabasi burstiness in [-1, 1]; 0 when undefined
    long["burstiness"] = np.where(denom > 0, (long["gap_std"] - long["gap_mean"]) / denom.where(denom > 0, 1), 0.0)

    wide = {}
    for kind in KINDS:
        for d in DIRS:
            sub = long[(long.kind == kind) & (long.dir == d)].set_index("addr")
            for s in _STATS:
                wide[f"{kind}_{d}_{s}"] = sub[s]
            if kind == "erc20":
                wide[f"{kind}_{d}_n_tokens"] = sub["n_tokens"]
    feats = pd.DataFrame(wide).reindex(index)
    feats = feats.fillna(0.0)

    for kind in KINDS:
        n_in, n_out = feats[f"{kind}_in_n"], feats[f"{kind}_out_n"]
        feats[f"{kind}_active"] = ((n_in + n_out) > 0).astype(float)
        feats[f"{kind}_count_ratio_in_out"] = n_in / (n_out + 1.0)
        feats[f"{kind}_value_ratio_in_out"] = feats[f"{kind}_in_total"] / (feats[f"{kind}_out_total"] + 1e-9)
        feats[f"{kind}_n_counterparties_total"] = feats[f"{kind}_in_n_counterparties"] + feats[f"{kind}_out_n_counterparties"]
    feats.index.name = "node"
    return feats


def behavioral_features(tx: pd.DataFrame, n_nodes: int, upto_block: int | None = None) -> pd.DataFrame:
    """Return a (n_nodes x F) frame indexed by node id. Addresses with no activity get zeros."""
    if upto_block is None:
        upto_block = int(tx["block"].max())
    con = duckdb.connect()
    con.register("tx", tx)
    long = con.execute(_SQL.format(upto=int(upto_block))).df()
    con.close()
    return widen(long, range(n_nodes))


def feature_groups(columns) -> dict[str, list[str]]:
    """Group columns as ETH vs ERC-20 behavioral (used by the importance report)."""
    return {
        "behavioral_eth": [c for c in columns if c.startswith("eth_")],
        "behavioral_erc20": [c for c in columns if c.startswith("erc20_")],
    }
