"""Download a finished BigQuery result table in parallel (plain REST, no gRPC, no new query).

    python scripts/download_result.py --table PROJECT:DATASET.TABLE --out data/raw/S/edges_eth_parts \
        --project PROJECT [--threads 8] [--chunk-rows 1000000] [--max-rows N]

Each thread reads a disjoint row range (tabledata.list start_index/max_results) and writes one
Parquet part file. Already-written parts are skipped, so an interrupted run resumes. Reading an
existing query-result table scans no data and costs nothing. Uses only your ADC credentials.
"""
import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pyarrow.parquet as pq
from google.cloud import bigquery


def fetch(client, table, start, n, out: Path, page_size):
    path = out / f"part-{start:012d}.parquet"
    if path.exists():
        return start, n, 0.0, True
    t0 = time.time()
    rows = client.list_rows(table, start_index=start, max_results=n, page_size=page_size)
    tbl = rows.to_arrow(create_bqstorage_client=False)
    tmp = path.with_suffix(".tmp")
    pq.write_table(tbl, tmp, compression="zstd")
    tmp.replace(path)                         # atomic: a part file is either complete or absent
    return start, tbl.num_rows, time.time() - t0, False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", required=True)
    ap.add_argument("--project", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--chunk-rows", type=int, default=1_000_000)
    ap.add_argument("--page-size", type=int, default=50_000)
    ap.add_argument("--max-rows", type=int, default=None)
    a = ap.parse_args()

    client = bigquery.Client(project=a.project)
    table = client.get_table(a.table.replace(":", "."))
    total = table.num_rows if a.max_rows is None else min(a.max_rows, table.num_rows)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    starts = list(range(0, total, a.chunk_rows))
    print(f"table rows {table.num_rows:,}; downloading {total:,} in {len(starts)} parts, {a.threads} threads",
          flush=True)

    t0, done_rows = time.time(), 0
    with ThreadPoolExecutor(max_workers=a.threads) as ex:
        futs = [ex.submit(fetch, client, table, s, min(a.chunk_rows, total - s), out, a.page_size)
                for s in starts]
        for i, f in enumerate(as_completed(futs), 1):
            try:
                s, n, sec, skipped = f.result()
            except Exception as e:                       # report and keep going; rerun resumes
                print(f"part failed: {e!r}", flush=True)
                continue
            done_rows += 0 if skipped else n
            el = time.time() - t0
            print(f"[{i}/{len(starts)}] rows {s:,}+{n:,} {'(skipped)' if skipped else f'{sec:.0f}s'} | "
                  f"{done_rows / max(el, 1):,.0f} rows/s overall", flush=True)

    got = sum(pq.ParquetFile(p).metadata.num_rows for p in out.glob("part-*.parquet"))
    print(f"parts hold {got:,} rows (expected {total:,})")
    if got != total:
        sys.exit("INCOMPLETE: rerun the same command to fetch missing parts")
    print("complete")


if __name__ == "__main__":
    main()
