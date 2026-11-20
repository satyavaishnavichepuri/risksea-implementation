"""Dry-run every extraction query and report the bytes BigQuery WOULD scan. Nothing is billed.

    python scripts/bq_dry_run.py --project YOUR_GCP_PROJECT [--tiers S M L] [--price-per-tib 6.25]

Authentication is yours: this script only uses Application Default Credentials that you
set up yourself (gcloud auth application-default login, or GOOGLE_APPLICATION_CREDENTIALS).
It never reads or stores credentials. A dry run needs a project (for quota attribution) but
processes no data and costs nothing. The price default is the on-demand list price per TiB
at the time of writing; check current pricing, and note the first 1 TiB/month is free.
"""
import argparse
import json
import sys
from pathlib import Path

from google.api_core import exceptions as gexc
from google.auth import exceptions as aexc
from google.cloud import bigquery

from risksea.ingest.bq_queries import ALL_QUERIES, TIERS

GIB, TIB = 1024 ** 3, 1024 ** 4


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--tiers", nargs="+", default=["S", "M", "L"], choices=list(TIERS))
    ap.add_argument("--price-per-tib", type=float, default=6.25)
    ap.add_argument("--out", default="results/bq_dry_run.json")
    a = ap.parse_args()

    try:
        client = bigquery.Client(project=a.project)
    except aexc.DefaultCredentialsError:
        sys.exit("No Google credentials found. Authenticate yourself first (see docs/bigquery_setup.md); "
                 "this script never handles credentials.")

    report = {}
    for t in a.tiers:
        tier = TIERS[t]
        params = [bigquery.ScalarQueryParameter("max_block", "INT64", tier.max_block),
                  bigquery.ScalarQueryParameter("ts_cap", "STRING", tier.ts_cap)]
        rows, total = {}, 0
        for name, sql in ALL_QUERIES.items():
            cfg = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False, query_parameters=params)
            try:
                job = client.query(sql, job_config=cfg)
                b = job.total_bytes_processed
            except (gexc.GoogleAPICallError, aexc.GoogleAuthError) as e:
                sys.exit(f"[{t}/{name}] dry run failed: {e}")
            rows[name] = b
            total += b
            print(f"tier {t} {name:15s} {b / GIB:10.1f} GiB")
        cost = total / TIB * a.price_per_tib
        report[t] = {"bytes": rows, "total_gib": total / GIB, "est_usd_list_price": cost,
                     "max_block": tier.max_block, "ts_cap": tier.ts_cap}
        print(f"tier {t} TOTAL           {total / GIB:10.1f} GiB  ~${cost:,.2f} at list price "
              f"(before the 1 TiB/month free tier)\n")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(report, indent=2))
    print("wrote", a.out)


if __name__ == "__main__":
    main()
