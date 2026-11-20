"""Write each query with its parameters filled in, for pasting into the BigQuery web console.
The console shows "This query will process X" without running it (no cost, no setup beyond a Google login).
"""
from pathlib import Path

from risksea.ingest.bq_queries import ALL_QUERIES, TIERS

out = Path(__file__).resolve().parents[1] / "sql"
out.mkdir(exist_ok=True)
for t, tier in TIERS.items():
    for name, sql in ALL_QUERIES.items():
        body = sql.replace("@max_block", str(tier.max_block)).replace("@ts_cap", f"'{tier.ts_cap}'")
        (out / f"{t}_{name}.sql").write_text(f"-- tier {t}: blocks <= {tier.max_block}\n{body}\n")
print("wrote", len(list(out.glob('*.sql'))), "files to", out)
