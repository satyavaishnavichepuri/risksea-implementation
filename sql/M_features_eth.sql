-- tier M: blocks <= 10000000
WITH ev AS (
  SELECT from_address AS addr, 'out' AS dir, UNIX_SECONDS(block_timestamp) AS ts,
         CAST(value AS FLOAT64) / 1e18 AS value, to_address AS cp, -1 AS token
  FROM `bigquery-public-data.crypto_ethereum.transactions`
  WHERE block_timestamp < TIMESTAMP('2020-05-15 00:00:00') AND block_number <= 10000000
    AND from_address IS NOT NULL AND to_address IS NOT NULL
  UNION ALL
  SELECT to_address AS addr, 'in' AS dir, UNIX_SECONDS(block_timestamp) AS ts,
         CAST(value AS FLOAT64) / 1e18 AS value, from_address AS cp, -1 AS token
  FROM `bigquery-public-data.crypto_ethereum.transactions`
  WHERE block_timestamp < TIMESTAMP('2020-05-15 00:00:00') AND block_number <= 10000000
    AND from_address IS NOT NULL AND to_address IS NOT NULL
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
SELECT a.*, IFNULL(g.gap_mean, 0) AS gap_mean, IFNULL(g.gap_std, 0) AS gap_std, 'eth' AS kind
FROM agg a LEFT JOIN gap_stats g USING (addr, dir)
