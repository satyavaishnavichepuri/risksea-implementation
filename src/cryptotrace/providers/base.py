"""Edge providers: where transfers come from. The engines only ever call `fetch`.

fetch(nodes, t1) takes {node: earliest_ts_needed} and returns every transfer touching those nodes at or after
that time (both directions), capped per node to the largest transfers, plus the nodes' true degrees.
"""
from __future__ import annotations

from collections import defaultdict

from cryptotrace.models import Edge, FetchResult


class MemoryProvider:
    """In-memory provider over a fixed edge list (tests, synthetic data, replay demos)."""

    def __init__(self, edges: list[Edge], top_k: int = 200, min_eth: float = 0.0):
        self.edges = list(edges)
        self.top_k = top_k
        self.min_eth = min_eth
        self.out = defaultdict(list)
        self.inn = defaultdict(list)
        for e in self.edges:
            self.out[e.src].append(e)
            self.inn[e.dst].append(e)
        self.stats = {"queries": 0, "bytes_billed": 0, "cache_hits": 0}

    def fetch(self, nodes: dict, t1: int) -> FetchResult:
        seen, out_edges, degree = set(), [], {}
        for node, t0 in nodes.items():
            for direction, book in (("out", self.out), ("in", self.inn)):
                es = [e for e in book.get(node, []) if e.ts >= t0 and e.ts < t1 and e.eth >= self.min_eth]
                degree[(node, direction)] = len(es)
                es.sort(key=lambda e: -e.eth)
                for e in es[: self.top_k]:
                    key = (e.tx, e.src, e.dst, e.ts, e.eth)
                    if key not in seen:
                        seen.add(key)
                        out_edges.append(e)
        self.stats["queries"] += 1
        return FetchResult(edges=out_edges, degree=degree, queries=1)
