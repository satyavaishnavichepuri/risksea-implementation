"""BigQuery edge provider over the public `crypto_ethereum.transactions` table, with an on-disk cache.

Tracing asks for the neighbourhood of a few addresses at a time, so each hop is one BigQuery query that returns a
few thousand rows (the largest transfers per address) instead of downloading the chain. Cost control:
  * the table is partitioned by block_timestamp, so every query is bounded by a time window (partition pruning);
  * every job carries `maximum_bytes_billed`;
  * results are cached in SQLite, so an address is fetched at most once per (window, filters) and re-runs are free.
Only external ETH transfers are used here (no internal traces, no ERC-20); that limit is reported in the UI.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from google.cloud import bigquery

from cryptotrace.models import Edge, FetchResult

TABLE = "bigquery-public-data.crypto_ethereum.transactions"

HOP_SQL = f"""
WITH e AS (
  SELECT `hash` AS tx, from_address AS src, to_address AS dst,
         CAST(value AS FLOAT64) / 1e18 AS eth, UNIX_SECONDS(block_timestamp) AS ts, block_number AS blk
  FROM `{TABLE}`
  WHERE block_timestamp >= TIMESTAMP_SECONDS(@t0) AND block_timestamp < TIMESTAMP_SECONDS(@t1)
    AND to_address IS NOT NULL AND value > 0
    AND (from_address IN UNNEST(@nodes) OR to_address IN UNNEST(@nodes))
), ends AS (
  SELECT src AS node, 'out' AS dir, tx, src, dst, eth, ts, blk FROM e WHERE src IN UNNEST(@nodes)
  UNION ALL
  SELECT dst AS node, 'in' AS dir, tx, src, dst, eth, ts, blk FROM e WHERE dst IN UNNEST(@nodes)
)
SELECT node, dir, tx, src, dst, eth, ts, blk,
       COUNT(*) OVER (PARTITION BY node, dir) AS deg
FROM ends
WHERE eth >= @min_eth
QUALIFY ROW_NUMBER() OVER (PARTITION BY node, dir ORDER BY eth DESC) <= @k
"""

HOP_SQL_NO_HASH = HOP_SQL.replace("`hash` AS tx", "CAST(NULL AS STRING) AS tx")


class CacheMiss(RuntimeError):
    """Raised in cache-only mode when a trace needs an address that was never fetched."""


class BigQueryProvider:
    def __init__(self, project: str, cache_path: str | Path, min_eth: float = 0.01, k: int = 200,
                 max_bytes_per_query: int = 40 * 1024 ** 3, include_hash: bool = True, chunk: int = 400,
                 budget_bytes: int = 60 * 1024 ** 3, cache_only: bool = False):
        self.project = project
        self._client = None                   # created lazily so cache-only use needs no credentials
        self.cache_only = cache_only
        self.min_eth, self.k, self.chunk = min_eth, k, chunk
        self.max_bytes = max_bytes_per_query
        self.budget = budget_bytes            # hard ceiling on total bytes billed by THIS provider instance
        self.sql = HOP_SQL if include_hash else HOP_SQL_NO_HASH
        self.stats = {"queries": 0, "bytes_billed": 0, "cache_hits": 0}
        self._lock = threading.Lock()
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(cache_path), check_same_thread=False)
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS fetched(key TEXT, node TEXT, t0 INTEGER, deg_out INTEGER, deg_in INTEGER,
                                             PRIMARY KEY(key, node));
          CREATE TABLE IF NOT EXISTS edges(key TEXT, tx TEXT, src TEXT, dst TEXT, eth REAL, ts INTEGER, blk INTEGER,
                                           UNIQUE(key, tx, src, dst, ts, eth));
          CREATE INDEX IF NOT EXISTS edges_src ON edges(key, src);
          CREATE INDEX IF NOT EXISTS edges_dst ON edges(key, dst);
        """)

    @property
    def client(self):
        if self._client is None:
            self._client = bigquery.Client(project=self.project)
        return self._client

    # ------------------------------------------------------------------ cost estimate
    def dry_run_bytes(self, t0: int, t1: int) -> int:
        cfg = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False, query_parameters=self._params(t0, t1, ["0x" + "0" * 40]))   # non-empty: an empty list is optimised away
        return int(self.client.query(self.sql, job_config=cfg).total_bytes_processed)

    def _params(self, t0, t1, nodes):
        return [bigquery.ScalarQueryParameter("t0", "INT64", int(t0)),
                bigquery.ScalarQueryParameter("t1", "INT64", int(t1)),
                bigquery.ArrayQueryParameter("nodes", "STRING", list(nodes)),
                bigquery.ScalarQueryParameter("min_eth", "FLOAT64", self.min_eth),
                bigquery.ScalarQueryParameter("k", "INT64", self.k)]

    # ------------------------------------------------------------------ fetch
    def fetch(self, nodes: dict, t1: int) -> FetchResult:
        """nodes: {address: earliest unix ts needed}. Returns edges touching them (cached after the first fetch)."""
        key = f"{self.min_eth}|{self.k}|{t1}"
        with self._lock:
            have = {r[0]: r[1] for r in self.db.execute(
                "SELECT node, t0 FROM fetched WHERE key=?", (key,)).fetchall()}
            need = {n: t for n, t in nodes.items() if n not in have or have[n] > t}
            self.stats["cache_hits"] += len(nodes) - len(need)
            items = list(need.items())
            if items and self.cache_only:
                raise CacheMiss(f"{len(items)} address(es) are not cached for this window; "
                                "enable live BigQuery to fetch them")
            for i in range(0, len(items), self.chunk):
                part = items[i:i + self.chunk]
                if self.stats["bytes_billed"] + 2 * 1024 ** 3 > self.budget:
                    raise RuntimeError(f"BigQuery budget of {self.budget / 1024 ** 3:.0f} GiB reached; stopping the trace")
                t0 = min(t for _, t in part)
                cfg = bigquery.QueryJobConfig(query_parameters=self._params(t0, t1, [n for n, _ in part]),
                                              maximum_bytes_billed=self.max_bytes)
                job = self.client.query(self.sql, job_config=cfg)
                rows = list(job.result())
                self.stats["queries"] += 1
                self.stats["bytes_billed"] += int(job.total_bytes_billed or 0)
                deg = {}
                for r in rows:
                    deg[(r["node"], r["dir"])] = int(r["deg"])
                    self.db.execute("INSERT OR IGNORE INTO edges VALUES (?,?,?,?,?,?,?)",
                                    (key, r["tx"], r["src"], r["dst"], float(r["eth"]), int(r["ts"]), int(r["blk"])))
                for n, tt in part:
                    self.db.execute("INSERT OR REPLACE INTO fetched VALUES (?,?,?,?,?)",
                                    (key, n, tt, deg.get((n, "out"), 0), deg.get((n, "in"), 0)))
                self.db.commit()
            return self._read(key, nodes)

    def _read(self, key: str, nodes: dict) -> FetchResult:
        seen, out, degree = set(), [], {}
        for n, t0 in nodes.items():
            fr = self.db.execute("SELECT deg_out, deg_in FROM fetched WHERE key=? AND node=?", (key, n)).fetchone()
            if fr:
                degree[(n, "out")], degree[(n, "in")] = fr
            for row in self.db.execute(
                    "SELECT tx, src, dst, eth, ts, blk FROM edges WHERE key=? AND (src=? OR dst=?) AND ts>=?",
                    (key, n, n, t0)):
                k = (row[0], row[1], row[2], row[4], row[3])
                if k not in seen:
                    seen.add(k)
                    out.append(Edge(src=row[1], dst=row[2], eth=row[3], ts=row[4], blk=row[5], tx=row[0]))
        return FetchResult(edges=out, degree=degree, queries=self.stats["queries"],
                           bytes_billed=self.stats["bytes_billed"], cache_hits=self.stats["cache_hits"])
