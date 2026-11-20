"""BigQuery extraction queries over `bigquery-public-data.crypto_ethereum` (milestone M3).

Everything is aggregated server-side so we never move billions of raw rows:
  edges_*     one row per (src, dst[, token]) pair: count, value, first/last block
  features_*  one row per (address, direction): the behavioral statistics of
              features/behavioral.py, in BigQuery dialect

Cost control:
  * The source tables are partitioned by block_timestamp, NOT block_number, so every query
    filters on BOTH: `block_timestamp < @ts_cap` prunes partitions (that is what saves money)
    and `block_number <= @max_block` makes the cut exact.
  * `@ts_cap` must be >= the real timestamp of `max_block`, otherwise blocks would be silently
    dropped. The caps below are deliberately a few days late; the extraction step asserts that
    the last block it received is within a small margin of `max_block`.
  * Only external transactions and ERC-20 Transfer events are used (no internal traces),
    matching the paper's "Ethereum transactions" and "ERC-20 token based transactions".
Known limits: ERC-20 amounts are raw token units (decimals differ per token, decision D17);
APPROX_QUANTILES gives an approximate median; one very hot address can make the LAG window
for gap statistics heavy at full scale (watch for "resources exceeded" on the real run).
"""
from __future__ import annotations

from dataclasses import dataclass

PROJECT_DATASET = "bigquery-public-data.crypto_ethereum"


@dataclass(frozen=True)
class Tier:
    name: str
    max_block: int
    ts_cap: str            # ISO timestamp, a few days after max_block's real time


TIERS = {
    "S": Tier("S", 5_000_000, "2018-02-10 00:00:00"),
    "M": Tier("M", 10_000_000, "2020-05-15 00:00:00"),
    "L": Tier("L", 16_000_000, "2022-12-05 00:00:00"),
}

_ETH = dict(table=f"{PROJECT_DATASET}.transactions", kind="eth",
            value="CAST(value AS FLOAT64) / 1e18", token="-1")
_ERC20 = dict(table=f"{PROJECT_DATASET}.token_transfers", kind="erc20",
              value="IFNULL(SAFE_CAST(value AS FLOAT64), 0.0)", token="FARM_FINGERPRINT(token_address)")


def edges_sql(kind: str) -> str:
    s = _ETH if kind == "eth" else _ERC20
    token_col = "" if kind == "eth" else ", FARM_FINGERPRINT(token_address) AS token"
    token_grp = "" if kind == "eth" else ", token"
    return f"""
SELECT from_address AS src, to_address AS dst{token_col},
       COUNT(*) AS tx_count,
       SUM({s['value']}) AS value,
       MIN(block_number) AS first_block,
       MAX(block_number) AS last_block
FROM `{s['table']}`
WHERE block_timestamp < TIMESTAMP(@ts_cap)
  AND block_number <= @max_block
  AND from_address IS NOT NULL AND to_address IS NOT NULL
GROUP BY src, dst{token_grp}
""".strip()


def features_sql(kind: str) -> str:
    s = _ETH if kind == "eth" else _ERC20
    ev = lambda a, b, d: f"""SELECT {a} AS addr, '{d}' AS dir, UNIX_SECONDS(block_timestamp) AS ts,
         {s['value']} AS value, {b} AS cp, {s['token']} AS token
  FROM `{s['table']}`
  WHERE block_timestamp < TIMESTAMP(@ts_cap) AND block_number <= @max_block
    AND from_address IS NOT NULL AND to_address IS NOT NULL"""
    return f"""
WITH ev AS (
  {ev('from_address', 'to_address', 'out')}
  UNION ALL
  {ev('to_address', 'from_address', 'in')}
),
gaps AS (
  SELECT addr, dir, ts - LAG(ts) OVER (PARTITION BY addr, dir ORDER BY ts) AS gap FROM ev
),
gap_stats AS (
  SELECT addr, dir, AVG(gap) AS gap_mean, IFNULL(STDDEV_POP(gap), 0) AS gap_std
  FROM gaps WHERE gap IS NOT NULL GROUP BY addr, dir
),
agg AS (
  SELECT addr, dir,
         COUNT(*) AS n, SUM(value) AS total, AVG(value) AS mean,
         IFNULL(STDDEV_POP(value), 0) AS std, MIN(value) AS min, MAX(value) AS max,
         APPROX_QUANTILES(value, 2)[OFFSET(1)] AS median,
         COUNT(DISTINCT cp) AS n_counterparties,
         MIN(ts) AS first_ts, MAX(ts) AS last_ts,
         COUNT(DISTINCT DIV(ts, 86400)) AS active_days,
         COUNT(DISTINCT token) AS n_tokens
  FROM ev GROUP BY addr, dir
)
SELECT a.*, IFNULL(g.gap_mean, 0) AS gap_mean, IFNULL(g.gap_std, 0) AS gap_std, '{s['kind']}' AS kind
FROM agg a LEFT JOIN gap_stats g USING (addr, dir)
""".strip()


def miners_sql() -> str:
    """Miner addresses (good labels, derived from data): distinct block producers up to max_block."""
    return f"""
SELECT miner AS address, COUNT(*) AS blocks_mined
FROM `{PROJECT_DATASET}.blocks`
WHERE timestamp < TIMESTAMP(@ts_cap) AND number <= @max_block
GROUP BY miner
""".strip()


ALL_QUERIES = {
    "edges_eth": edges_sql("eth"),
    "edges_erc20": edges_sql("erc20"),
    "features_eth": features_sql("eth"),
    "features_erc20": features_sql("erc20"),
    "miners": miners_sql(),
}
