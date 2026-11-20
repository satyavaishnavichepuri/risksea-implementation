-- tier M: blocks <= 10000000
SELECT miner AS address, COUNT(*) AS blocks_mined
FROM `bigquery-public-data.crypto_ethereum.blocks`
WHERE timestamp < TIMESTAMP('2020-05-15 00:00:00') AND number <= 10000000
GROUP BY miner
