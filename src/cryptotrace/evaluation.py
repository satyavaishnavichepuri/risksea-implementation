"""Metrics for comparing tracing strategies on a case, mirroring the book's Chapter 8 table.

  recall        share of the book's expected destinations that the tracer reached (by name match)
  nodes         size of the output graph an investigator has to audit (smaller is better at equal recall)
  depth         deepest hop reached
  runtime/cost  wall-clock seconds and BigQuery GiB billed
"""
from __future__ import annotations


def match_expected(result: dict, case) -> dict:
    names = [t["name"] or "" for t in result["terminals"]]
    found = {k: any(k.lower() in n.lower() for n in names) for k in case.expect_names}
    groups = {}
    for k, ok in found.items():
        groups[k] = ok
    hit = sum(1 for v in groups.values() if v)
    return {"found": groups, "hit": hit, "total": len(groups), "recall": round(hit / len(groups), 3) if groups else None}


def summarize(result: dict, case) -> dict:
    s, st = result["summary"], result["stats"]
    m = match_expected(result, case)
    return {
        "engine": result["engine"], "engine_label": result["engine_label"],
        "terminals": s["n_terminals"], "exchange_terminals": s["n_exchange_terminals"],
        "nearest_exchange": s["nearest_exchange"], "top_exchange_by_share": s["top_exchange_by_share"],
        "expected_hit": m["hit"], "expected_total": m["total"], "recall": m["recall"], "found": m["found"],
        "nodes": st["nodes_in_graph"], "edges_drawn": st["edges_drawn"], "edges_considered": st["edges_considered"],
        "depth": st["max_depth"], "rounds": st["rounds"], "seconds": st["seconds"],
        "gib_billed": round(st["bytes_billed"] / 1024 ** 3, 3), "queries": st["queries"],
    }
