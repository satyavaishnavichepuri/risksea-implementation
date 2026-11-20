-- tier M: blocks <= 10000000
SELECT from_address AS src, to_address AS dst, FARM_FINGERPRINT(token_address) AS token,
       COUNT(*) AS tx_count,
       SUM(IFNULL(SAFE_CAST(value AS FLOAT64), 0.0)) AS value,
       MIN(block_number) AS first_block,
       MAX(block_number) AS last_block
FROM `bigquery-public-data.crypto_ethereum.token_transfers`
WHERE block_timestamp < TIMESTAMP('2020-05-15 00:00:00')
  AND block_number <= 10000000
  AND from_address IS NOT NULL AND to_address IS NOT NULL
GROUP BY src, dst, token
