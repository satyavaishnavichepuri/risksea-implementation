import re

from risksea.ingest.bq_queries import ALL_QUERIES, TIERS, edges_sql, features_sql


def test_every_query_prunes_partitions_and_cuts_by_block():
    for name, sql in ALL_QUERIES.items():
        assert "@ts_cap" in sql and "@max_block" in sql, name
        # no query may reference the source tables without the timestamp filter
        assert re.search(r"(block_)?timestamp < TIMESTAMP\(@ts_cap\)", sql), name


def test_queries_use_documented_tables_and_no_credentials_or_literals():
    assert "crypto_ethereum.transactions" in edges_sql("eth")
    assert "crypto_ethereum.token_transfers" in edges_sql("erc20")
    assert "crypto_ethereum.blocks" in ALL_QUERIES["miners"]
    for sql in ALL_QUERIES.values():
        assert "0x" not in sql                      # no hard-coded addresses


def test_feature_columns_match_local_duckdb_features():
    cols = ["n", "total", "mean", "std", "min", "max", "median", "n_counterparties",
            "first_ts", "last_ts", "active_days", "n_tokens", "gap_mean", "gap_std"]
    for kind in ("eth", "erc20"):
        sql = features_sql(kind)
        for c in cols:
            assert re.search(rf"\bAS {c}\b", sql), (kind, c)
        assert f"'{kind}' AS kind" in sql


def test_tier_caps_are_after_block_dates_and_ordered():
    s, m, l = TIERS["S"], TIERS["M"], TIERS["L"]
    assert s.max_block < m.max_block < l.max_block
    assert s.ts_cap < m.ts_cap < l.ts_cap
