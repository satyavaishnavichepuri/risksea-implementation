"""Dry-run the tracing hop query for the two benchmark windows: bytes per hop and a cost estimate. Bills nothing."""
import calendar
import sys
from datetime import datetime, timezone

from cryptotrace.providers.bigquery import BigQueryProvider

PROJECT = sys.argv[1]
price = 6.25
cases = {"cryptopia_2019": ("2019-05-14", "2019-06-28"), "kucoin_2020": ("2020-09-25", "2020-11-10")}
ts = lambda d: calendar.timegm(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timetuple())
for hashed in (True, False):
    p = BigQueryProvider(PROJECT, "data/cryptotrace/_dry.sqlite", include_hash=hashed)
    for name, (a, b) in cases.items():
        by = p.dry_run_bytes(ts(a), ts(b))
        print(f"{name:16s} window {a}..{b}  include_hash={hashed!s:5s}  {by / 1024**3:6.2f} GiB per hop  "
              f"~${by / 1024**4 * price:.3f} per hop at list price")
