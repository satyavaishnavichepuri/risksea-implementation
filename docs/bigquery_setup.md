# BigQuery dry run: setup

A dry run reads no data and costs nothing. It only reports how many bytes the query would scan.
You authenticate with your own Google account; nothing in this repo handles credentials.

## Option A - BigQuery web console (no installs)
1. Open https://console.cloud.google.com/bigquery and sign in. Any project works (the free sandbox is fine for dry runs).
2. Open a file from `sql/` (for example `sql/S_edges_eth.sql`), paste it into a new query tab.
3. The editor shows "This query will process X GB when run" at the top right. Note it down.
4. Repeat for the `S_`, `M_` and `L_` files (5 queries per tier) and send me the numbers.

## Option B - script (needs the gcloud CLI once)
1. Install the Google Cloud CLI: https://cloud.google.com/sdk/docs/install
2. `gcloud auth application-default login` (opens your browser; you log in, nothing is shared with me)
3. `python scripts/bq_dry_run.py --project YOUR_PROJECT_ID`
   Output: bytes per query, per tier, and an estimated list-price cost; written to `results/bq_dry_run.json`.

## Reading the result
- On-demand price is per TiB scanned (check current pricing; the first 1 TiB per month is free).
- Tier S is blocks 0-5M, M is 0-10M, L is 0-16M.
- The real run happens only after you approve a specific tier and its estimated cost.
