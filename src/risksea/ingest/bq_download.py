"""Parallel, resumable download of a finished BigQuery result table over plain REST.

Each worker thread reads a disjoint row range (tabledata.list) and writes one Parquet part file
atomically, so a part is either complete or absent and an interrupted run simply resumes.
Reading an existing result table scans no data and costs nothing. A `_SUCCESS` marker is written
only when every row has arrived. (gRPC/Storage API is deliberately not used: this machine's
Application Control policy blocks the gRPC DLL.)
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pyarrow.parquet as pq


def _fetch(client, table, start, n, out: Path, page_size):
    path = out / f"part-{start:012d}.parquet"
    if path.exists():
        return start, n, 0.0, True
    t0 = time.time()
    rows = client.list_rows(table, start_index=start, max_results=n, page_size=page_size)
    tbl = rows.to_arrow(create_bqstorage_client=False)
    tmp = path.with_suffix(".tmp")
    pq.write_table(tbl, tmp, compression="zstd")
    tmp.replace(path)
    return start, tbl.num_rows, time.time() - t0, False


def download_table(client, table, out: str | Path, threads: int = 16, chunk_rows: int = 250_000,
                   page_size: int = 50_000, max_rows: int | None = None, log=print) -> int:
    """Download `table` (a bigquery.Table) into `out`/part-*.parquet. Returns rows on disk.
    Raises RuntimeError if rows are missing (rerun resumes)."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    total = table.num_rows if max_rows is None else min(max_rows, table.num_rows)
    starts = list(range(0, total, chunk_rows))
    log(f"table rows {table.num_rows:,}; downloading {total:,} in {len(starts)} parts, {threads} threads")
    t0, done = time.time(), 0
    with ThreadPoolExecutor(max_workers=threads) as ex:
        futs = [ex.submit(_fetch, client, table, s, min(chunk_rows, total - s), out, page_size)
                for s in starts]
        for i, f in enumerate(as_completed(futs), 1):
            try:
                s, n, sec, skipped = f.result()
            except Exception as e:                        # keep going; rerun resumes
                log(f"part failed: {e!r}")
                continue
            done += 0 if skipped else n
            if i % 10 == 0 or i == len(starts):
                log(f"[{i}/{len(starts)}] {done / max(time.time() - t0, 1):,.0f} rows/s overall")
    got = sum(pq.ParquetFile(p).metadata.num_rows for p in out.glob("part-*.parquet"))
    if got != total:
        raise RuntimeError(f"incomplete: {got:,} of {total:,} rows on disk; rerun to fetch the rest")
    (out / "_SUCCESS").write_text(f"{got}\n")
    log(f"complete: {got:,} rows")
    return got
