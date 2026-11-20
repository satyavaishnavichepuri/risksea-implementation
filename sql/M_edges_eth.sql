-- tier M: blocks <= 10000000
SELECT from_address AS src, to_address AS dst,
       COUNT(*) AS tx_count,
       SUM(CAST(value AS FLOAT64) / 1e18) AS value,
       MIN(block_number) AS first_block,
       MAX(block_number) AS last_block
FROM `bigquery-public-data.crypto_ethereum.transactions`
WHERE block_timestamp < TIMESTAMP('2020-05-15 00:00:00')
  AND block_number <= 10000000
  AND from_address IS NOT NULL AND to_address IS NOT NULL
GROUP BY src, dst
