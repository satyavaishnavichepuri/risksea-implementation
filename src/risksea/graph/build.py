"""Transaction graph construction (M2.1).

The graph is stored as a CSR adjacency (indptr/indices/weights) so random walks
can run in numba and neighbor lists can be partitioned by source node.

Design notes (see docs/decisions.md):
  * D9  - edge weight = interaction count (ETH + ERC-20 combined).
  * D13 - walks run over the undirected view (neighbors = in + out), because a
          pure out-edge walk gets stuck at sink nodes (e.g. fraud collectors).
          Set directed=True to keep paper-literal directed edges.
  * Hub nodes are capped to their top-K neighbors by interaction count (K=200,
    paper Sec IV-E) to avoid data skew.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Graph:
    n: int
    indptr: np.ndarray    # int64, len n+1
    indices: np.ndarray   # int64, neighbor ids, sorted ascending within each node
    weights: np.ndarray   # float64, interaction counts

    def neighbors(self, i: int) -> np.ndarray:
        return self.indices[self.indptr[i]:self.indptr[i + 1]]

    def neighbor_weights(self, i: int) -> np.ndarray:
        return self.weights[self.indptr[i]:self.indptr[i + 1]]

    def degree(self) -> np.ndarray:
        return np.diff(self.indptr)

    @property
    def n_edges(self) -> int:
        return int(len(self.indices))


def edge_table(tx: pd.DataFrame, from_block: int | None = None,
               upto_block: int | None = None) -> pd.DataFrame:
    """Aggregate raw transfers to directed pair edges within a block range [from, upto]."""
    t = tx
    if from_block is not None:
        t = t[t.block >= from_block]
    if upto_block is not None:
        t = t[t.block <= upto_block]
    g = t.groupby(["src", "dst"], sort=False).agg(
        count=("block", "size"), value=("value", "sum"),
        first_block=("block", "min"), last_block=("block", "max")).reset_index()
    return g


def build_graph(edges: pd.DataFrame, n_nodes: int, top_k: int | None = 200,
                directed: bool = False) -> Graph:
    """CSR graph from an edge table; keeps the top_k neighbors per node by weight."""
    src = edges["src"].to_numpy(np.int64)
    dst = edges["dst"].to_numpy(np.int64)
    w = edges["count"].to_numpy(np.float64)
    if not directed:
        a = np.concatenate([src, dst]); b = np.concatenate([dst, src]); ww = np.concatenate([w, w])
        df = pd.DataFrame({"a": a, "b": b, "w": ww}).groupby(["a", "b"], sort=False).w.sum().reset_index()
    else:
        df = pd.DataFrame({"a": src, "b": dst, "w": w}).groupby(["a", "b"], sort=False).w.sum().reset_index()

    if top_k is not None:
        # rank neighbors per source by weight desc (ties broken by neighbor id for determinism)
        df = df.sort_values(["a", "w", "b"], ascending=[True, False, True], kind="mergesort")
        df["rank"] = df.groupby("a", sort=False).cumcount()
        df = df[df["rank"] < top_k]
    df = df.sort_values(["a", "b"], kind="mergesort")
    a = df["a"].to_numpy(np.int64)
    counts = np.bincount(a, minlength=n_nodes)
    indptr = np.zeros(n_nodes + 1, dtype=np.int64)
    np.cumsum(counts, out=indptr[1:])
    return Graph(n=n_nodes, indptr=indptr, indices=df["b"].to_numpy(np.int64),
                 weights=df["w"].to_numpy(np.float64))


def induced_subgraph(graph: Graph, nodes) -> Graph:
    """Subgraph keeping only edges whose both endpoints are in `nodes` (node ids unchanged)."""
    keep = np.zeros(graph.n, dtype=bool)
    keep[np.asarray(nodes, dtype=np.int64)] = True
    a = np.repeat(np.arange(graph.n, dtype=np.int32), np.asarray(graph.degree()))
    sel = keep[a] & keep[np.asarray(graph.indices)]
    counts = np.bincount(a[sel], minlength=graph.n)
    indptr = np.zeros(graph.n + 1, dtype=np.int64)
    np.cumsum(counts, out=indptr[1:])
    return Graph(n=graph.n, indptr=indptr, indices=np.asarray(graph.indices)[sel], weights=np.asarray(graph.weights)[sel])


def graph_at(tx: pd.DataFrame, n_nodes: int, upto_block: int, top_k: int | None = 200,
             directed: bool = False) -> Graph:
    """Graph snapshot containing all transactions up to and including upto_block."""
    return build_graph(edge_table(tx, upto_block=upto_block), n_nodes, top_k, directed)
