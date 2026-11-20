import pandas as pd

from risksea.ingest.labels import (audit_markdown, merge_labels, normalize_address,
                                   restrict_to_graph, standardize)

A = "0x" + "a" * 40
B = "0x" + "b" * 40
C = "0x" + "c" * 40


def test_normalize_address():
    assert normalize_address("  0x" + "A" * 40 + " ") == A
    assert normalize_address("0x123") is None
    assert normalize_address("0x" + "g" * 40) is None
    assert normalize_address(None) is None


def test_bad_wins_and_conflict_counted():
    bad = standardize(pd.DataFrame({"address": [A.upper().replace("0X", "0x"), B]}), "phish", 1)
    good = standardize(pd.DataFrame({"address": [A, C]}), "exchanges", 0)
    merged, audit = merge_labels([bad, good])
    m = merged.set_index("address")
    assert m.loc[A, "label"] == 1 and bool(m.loc[A, "conflict"])      # A is in both -> bad wins
    assert m.loc[B, "label"] == 1 and m.loc[C, "label"] == 0
    assert m.loc[A, "sources"] == "exchanges,phish" and m.loc[A, "n_sources"] == 2
    assert audit["conflicts_resolved_to_bad"] == 1
    assert audit["final_bad"] == 2 and audit["final_good"] == 1


def test_invalid_and_duplicate_rows_are_counted_not_hidden():
    df = pd.DataFrame({"address": [A, A, "not-an-address", None]})
    merged, audit = merge_labels([standardize(df, "s", 1)])
    assert audit["raw_rows"] == 4 and audit["invalid_addresses"] == 2
    assert audit["duplicate_rows_dropped"] == 1
    assert len(merged) == 1


def test_restrict_to_graph_attaches_nodes_and_reports_drops():
    merged, _ = merge_labels([standardize(pd.DataFrame({"address": [A, B]}), "s", 1),
                              standardize(pd.DataFrame({"address": [C]}), "t", 0)])
    kept, info = restrict_to_graph(merged, {A: 0, C: 5})
    assert set(kept.address) == {A, C} and set(kept.node) == {0, 5}
    assert info == {"before": 3, "in_graph": 2, "dropped_not_in_graph": 1,
                    "final_bad": 1, "final_good": 1}


def test_audit_markdown_mentions_every_source():
    merged, audit = merge_labels([standardize(pd.DataFrame({"address": [A]}), "phish", 1),
                                  standardize(pd.DataFrame({"address": [C]}), "miners", 0)])
    md = audit_markdown(audit)
    assert "| phish | bad |" in md and "| miners | good |" in md
    assert "final: 1 bad / 1 good" in md
