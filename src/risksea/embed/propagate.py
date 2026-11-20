"""Embedding propagation baseline (M2.4, paper Sec IV-A / Algorithm 1).

Train node2vec on a core set of addresses, then give every other address an embedding
by aggregating the embeddings of up to `num_neighbors` (5) randomly sampled one-hop
neighbors that are in the core set. One hop only, as in the paper. Addresses with no
core neighbor get no embedding (the paper reports ~78% coverage).
"""
from __future__ import annotations

import numpy as np

from risksea.graph.build import Graph


def sample_core(graph: Graph, labeled_nodes, core_size: int, seed: int = 0) -> np.ndarray:
    """Core set recipe (paper Sec IV-A): all addresses that transacted with a labeled
    address (plus the labeled addresses), randomly sampled down to `core_size`."""
    labeled = np.asarray(labeled_nodes, dtype=np.int64)
    nbrs = [graph.neighbors(int(a)) for a in labeled]
    cand = np.unique(np.concatenate([labeled] + nbrs)) if nbrs else labeled
    cand = cand[graph.degree()[cand] > 0]
    if len(cand) <= core_size:
        return cand
    rng = np.random.default_rng(seed)
    return np.sort(rng.choice(cand, core_size, replace=False))


def propagate(core_emb: np.ndarray, core_mask: np.ndarray, graph: Graph,
              num_neighbors: int = 5, aggregation: str = "mean", seed: int = 0):
    """Return (matrix, mask) with propagated embeddings for non-core nodes.

    Core nodes keep their trained embeddings. For every other node X: take its core
    neighbors, sample up to `num_neighbors` uniformly without replacement, aggregate.
    """
    n, dim = core_emb.shape
    out = core_emb.copy()
    mask = core_mask.copy()

    deg = graph.degree()
    a = np.repeat(np.arange(n), deg)
    b = graph.indices
    sel = (~core_mask[a]) & core_mask[b]
    a, b = a[sel], b[sel]
    if len(a) == 0:
        return out, mask

    rng = np.random.default_rng(seed)
    key = rng.random(len(a))
    order = np.lexsort((key, a))            # by node, then random key => uniform sample w/o replacement
    a, b = a[order], b[order]
    first = np.r_[0, np.flatnonzero(np.diff(a)) + 1]
    group = np.repeat(np.arange(len(first)), np.diff(np.r_[first, len(a)]))
    rank = np.arange(len(a)) - first[group]
    keep = rank < num_neighbors
    a, b = a[keep], b[keep]
    first = np.r_[0, np.flatnonzero(np.diff(a)) + 1]
    sizes = np.diff(np.r_[first, len(a)])
    vecs = core_emb[b].astype(np.float64)
    sums = np.add.reduceat(vecs, first, axis=0)
    if aggregation == "mean":
        agg = sums / sizes[:, None]
    elif aggregation == "sum":
        agg = sums
    else:
        raise ValueError(f"unknown aggregation {aggregation!r}")
    nodes = a[first]
    out[nodes] = agg.astype(out.dtype)
    mask[nodes] = True
    return out, mask


def coverage(mask: np.ndarray, graph: Graph, active_nodes=None) -> dict:
    """Coverage stats: share of all nodes (with >=1 edge) and of an 'active' subset."""
    has_edge = graph.degree() > 0
    res = {"overall": float(mask[has_edge].mean()) if has_edge.any() else 0.0}
    if active_nodes is not None:
        act = np.asarray(active_nodes)
        res["active"] = float(mask[act].mean()) if len(act) else 0.0
    return res
