"""Run all three engines on the benchmark cases against BigQuery (cached) and store the results as JSON.

    python scripts/ct_run_cases.py PROJECT [case_id ...]
Writes results/cryptotrace/<case>_<engine>.json. All engines share one cache, so each address is fetched once.
Every BigQuery job carries a bytes cap. Printed cost is the real billed total.
"""
import json
import sys
import time
from pathlib import Path

from cryptotrace.cases import CASES
from cryptotrace.engines import ENGINES
from cryptotrace.evaluation import summarize
from cryptotrace.labels import LabelStore
from cryptotrace.models import TraceParams
from cryptotrace.providers.bigquery import BigQueryProvider

ROOT = Path(__file__).resolve().parents[1]
project = sys.argv[1]
want = sys.argv[2:] or list(CASES)
labels = LabelStore.from_files(ROOT / "data" / "labels")
print("labels:", labels.counts())
out = ROOT / "results" / "cryptotrace"
out.mkdir(parents=True, exist_ok=True)
for cid in want:
    case = CASES[cid]
    prov = BigQueryProvider(project, ROOT / "data" / "cryptotrace" / "cache.sqlite")
    for ename in ("ttr", "haircut", "bfs"):
        t = time.time()
        res = ENGINES[ename](prov, labels, TraceParams()).run(case.source, case.t0, case.t1)
        res["case"] = cid
        (out / f"{cid}_{ename}.json").write_text(json.dumps(res))
        row = summarize(res, case)
        print(f"[{cid}] {ename:8s} terminals={row['terminals']:3d} exchanges={row['exchange_terminals']:2d} "
              f"nearest={row['nearest_exchange']} found={row['found']} nodes={row['nodes']} depth={row['depth']} "
              f"{time.time() - t:5.1f}s  billed so far {prov.stats['bytes_billed'] / 1024 ** 3:.2f} GiB", flush=True)
