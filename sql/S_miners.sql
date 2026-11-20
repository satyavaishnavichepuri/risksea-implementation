-- tier S: blocks <= 5000000
SELECT miner AS address, COUNT(*) AS blocks_mined
FROM `bigquery-public-data.crypto_ethereum.blocks`
WHERE timestamp < TIMESTAMP('2018-02-10 00:00:00') AND number <= 5000000
GROUP BY miner
