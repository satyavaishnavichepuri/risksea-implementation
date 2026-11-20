-- tier L: blocks <= 16000000
SELECT miner AS address, COUNT(*) AS blocks_mined
FROM `bigquery-public-data.crypto_ethereum.blocks`
WHERE timestamp < TIMESTAMP('2022-12-05 00:00:00') AND number <= 16000000
GROUP BY miner
