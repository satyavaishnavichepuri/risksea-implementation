"""Run the approved BigQuery extraction for one tier; download results in parallel to local Parquet.

    python scripts/extract_bq.py --project PROJECT --tier S [--queries edges_erc20 ...] [--threads 16]

Safety:
  * Each query gets `maximum_bytes_billed` = its dry-run estimate (results/bq_dry_run.json) + 5%.
    BigQuery refuses to run (and bills nothing) if a query would scan more, so approved spend
    cannot be exceeded.
  * Queries whose output folder already has a `_SUCCESS` marker are skipped (no re-billing).
  * Results are read from the query's result table by parallel REST range reads (src/risksea/
    ingest/bq_download.py); reading results scans no data. Only your own ADC credentials are used.
  * After extraction, asserts the data really reaches the target block (checks the timestamp cap).
Output: data/raw/<tier>/<query>_parts/part-*.parquet
"""
import argparse
import json
import sys
from pathlib import Path

import pyarrow.parquet as pq
from google.api_core import exceptions as gexc
from google.auth import exceptions as aexc
from google.cloud import bigquery

from risksea.ingest.bq_download import download_table
from risksea.ingest.bq_queries import ALL_QUERIES, TIERS

ROOT = Path(__file__).resolve().parents[1]
HEADROOM = 1.05


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--tier", required=True, choices=list(TIERS))
    ap.add_argument("--queries", nargs="+", default=list(ALL_QUERIES))
    ap.add_argument("--threads", type=int, default=16)
    a = ap.parse_args()
    tier = TIERS[a.tier]
    est = json.loads((ROOT / "results" / "bq_dry_run.json").read_text())

    try:
        client = bigquery.Client(project=a.project)
    except aexc.DefaultCredentialsError:
        sys.exit("No Application Default Credentials. Run: gcloud auth application-default login")

    outroot = ROOT / "data" / "raw" / a.tier
    outroot.mkdir(parents=True, exist_ok=True)
    params = [bigquery.ScalarQueryParameter("max_block", "INT64", tier.max_block),
              bigquery.ScalarQueryParameter("ts_cap", "STRING", tier.ts_cap)]
    summary = {}
    for name in a.queries:
        out = outroot / f"{name}_parts"
        if (out / "_SUCCESS").exists():
            print(f"[{name}] already complete, skipping", flush=True)
            continue
        cap = int(int(est[f"{a.tier}_{name}"]) * HEADROOM)
        cfg = bigquery.QueryJobConfig(query_parameters=params, maximum_bytes_billed=cap)
        print(f"[{name}] running query (cap {cap / 1024**3:.1f} GiB) ...", flush=True)
        try:
            job = client.query(ALL_QUERIES[name], job_config=cfg)
            job.result()                                    # waits for the query only
            table = client.get_table(job.destination)
        except gexc.GoogleAPICallError as e:
            sys.exit(f"[{name}] failed: {e}")
        billed = job.total_bytes_billed or 0
        print(f"[{name}] query done, billed {billed / 1024**3:.2f} GiB, {table.num_rows:,} rows; downloading",
              flush=True)
        rows = download_table(client, table, out, threads=a.threads,
                              log=lambda m, n=name: print(f"[{n}] {m}", flush=True))
        summary[name] = {"rows": rows, "bytes_billed": billed, "job_id": job.job_id}

    # ---- post-run check: the timestamp cap must not have cut blocks off
    parts = outroot / "edges_eth_parts"
    if "edges_eth" in a.queries and (parts / "_SUCCESS").exists():
        top = int(pq.read_table(str(parts), columns=["last_block"]).column(0).to_pandas().max())
        summary["max_last_block_edges_eth"] = top
        if top < tier.max_block - 5_000:
            sys.exit(f"CHECK FAILED: highest block received is {top:,}, expected near {tier.max_block:,}. "
                     "ts_cap is probably too early -- data is truncated.")
        print(f"check ok: highest block in edges_eth = {top:,} (target {tier.max_block:,})")
    (outroot / "extraction_summary.json").write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
