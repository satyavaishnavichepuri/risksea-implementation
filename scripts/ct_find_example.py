"""Exploration: which Etherscan-labeled phishing/hack addresses moved the most ETH out in 2018-01..2018-12?

    python scripts/ct_find_example.py PROJECT
Dry-runs first and refuses to run above 30 GiB. Prints the top outflow addresses to pick a real demo case from.
"""
import sys

import pandas as pd
from google.cloud import bigquery

project = sys.argv[1]
ph = pd.read_csv("data/labels/ethlabels_raw/phish-hack_all.csv", dtype=str)
addrs = sorted(set(ph.address.str.lower().str.strip()))
sql = """
SELECT from_address AS src, COUNT(*) AS n, SUM(CAST(value AS FLOAT64) / 1e18) AS eth_out,
       UNIX_SECONDS(MIN(block_timestamp)) AS first_ts, UNIX_SECONDS(MAX(block_timestamp)) AS last_ts
FROM `bigquery-public-data.crypto_ethereum.transactions`
WHERE block_timestamp >= TIMESTAMP('2018-01-01') AND block_timestamp < TIMESTAMP('2019-01-01')
  AND from_address IN UNNEST(@addrs) AND value > 0 AND to_address IS NOT NULL
GROUP BY src HAVING eth_out >= 100 ORDER BY eth_out DESC LIMIT 25
"""
c = bigquery.Client(project=project)
params = [bigquery.ArrayQueryParameter("addrs", "STRING", addrs)]
dry = c.query(sql, job_config=bigquery.QueryJobConfig(dry_run=True, query_parameters=params))
gib = dry.total_bytes_processed / 1024 ** 3
print(f"dry run: {gib:.1f} GiB (~${gib / 1024 * 6.25:.2f} at list price); {len(addrs)} labeled addresses")
if gib > 30:
    sys.exit("above the 30 GiB budget, not running")
job = c.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params, maximum_bytes_billed=int(32 * 1024 ** 3)))
rows = list(job.result())
print(f"billed {job.total_bytes_billed / 1024 ** 3:.1f} GiB")
tag = dict(zip(ph.address.str.lower().str.strip(), ph.nameTag.fillna("")))
for r in rows:
    print(f"{r['src']}  out {r['eth_out']:>10.1f} ETH  n={r['n']:>4}  ts {r['first_ts']}..{r['last_ts']}  {tag.get(r['src'], '')[:28]}")
