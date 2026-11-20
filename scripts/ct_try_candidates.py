"""Trace a few labeled hack/phishing addresses (live, capped) and print what each reaches. Used to pick a demo case."""
import sys
import time

from cryptotrace.cases import ts
from cryptotrace.engines import TTR
from cryptotrace.labels import LabelStore
from cryptotrace.models import TraceParams
from cryptotrace.providers.bigquery import BigQueryProvider

project = sys.argv[1]
labels = LabelStore.from_files("data/labels")
CANDS = [  # (address, name, window start, window end)
    ("0xf6884686a999f5ae6c1af03db92bab9c6d7dc8de", "Coinrail Hacker", "2018-06-10", "2018-07-25"),
    ("0xdf9191889649c442836ef55de5036a7b694115b6", "Fake_Phishing1431", "2018-06-10", "2018-07-25"),
    ("0x5457bb4430d8b8d1a3708576100aef0e027c5b9b", "Fake_Phishing1951", "2018-06-29", "2018-08-13"),
    ("0xeca2592e788c76f2e3cd4eb6ffcdbe5cf8141c72", "Ian Balina Hacker 3", "2018-01-08", "2018-02-22"),
]
for addr, name, a, b in CANDS:
    prov = BigQueryProvider(project, "data/cryptotrace/cache.sqlite", budget_bytes=20 * 1024 ** 3)
    t = time.time()
    try:
        r = TTR(prov, labels, TraceParams()).run(addr, ts(a), ts(b))
    except Exception as e:
        print(f"{name}: failed {type(e).__name__}: {e}")
        continue
    print(f"\n== {name} {addr[:10]} {a}..{b}: rounds={r['stats']['rounds']} nodes={r['stats']['nodes_in_graph']} "
          f"out={r['summary']['source_out_eth']} ETH, billed {prov.stats['bytes_billed'] / 1024 ** 3:.1f} GiB, {time.time() - t:.0f}s")
    for x in r["terminals"][:6]:
        print(f"   {x['kind']:17s} {x['name'][:34]:34s} share {x['share']:.3f} ~{x['eth_est']:.0f} ETH depth {x['depth']} {x['confidence']}")
    if not r["terminals"]:
        print("   (no terminal reached)")
