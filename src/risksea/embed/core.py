"""Core-set selection and compact propagation for graphs too large for a dense embedding matrix.

At 24M nodes a dense (n x 128) float32 matrix is 12 GB, so here embeddings live only for
the core set (core_ids sorted, core_vecs aligned) and propagated embeddings are computed only
for the target nodes we actually need (labeled addresses). Coverage over ALL nodes is computed
from the adjacency alone (no vectors), as a boolean pass.
Paper recipe (Sec IV-A): core = addresses that transacted with the labeled set, plus more
addresses up to the core size. We grow outward from the labeled seeds hop by hop, so the core
induces a connected subgraph that node2vec can learn from (a purely random sample of ~10% of
nodes would leave most of them isolated in the induced subgraph).
"""
from __future__ import annotations

import numpy as np

from risksea.graph.build import Graph


def _neighbors_mask(graph: Graph, nodes: np.ndarray, n: int, batch: int = 50_000) -> np.ndarray:
    """Boolean mask of all neighbors of `nodes` (batched to bound memory)."""
    out = np.zeros(n, dtype=bool)
    ip = np.asarray(graph.indptr)
    for lo in range(0, len(nodes), batch):
        b = nodes[lo:lo + batch]
        starts, ends = ip[b], ip[b + 1]
        lens = ends - starts
        total = int(lens.sum())
        if total == 0:
            continue
        offs = np.repeat(starts - (np.cumsum(lens) - lens), lens)
        idx = np.arange(total, dtype=np.int64) + offs
        out[np.asarray(graph.indices)[idx]] = True
    return out


def grow_core(graph: Graph, seeds, core_size: int, seed: int = 0, include_seeds: bool = True) -> np.ndarray:
    """Seeds' neighbors, then outward hop by hop, randomly truncated at `core_size`.
    include_seeds=True keeps the seeds (with edges) in the core, so they get trained embeddings.
    include_seeds=False keeps them OUT of the core (decision D20), so labeled addresses can only get
    embeddings by propagation from their core neighbors -- the reading of the paper in which
    "propagated embeddings" are what the classifier sees. Returns sorted node ids."""
    rng = np.random.default_rng(seed)
    n = graph.n
    seeds = np.unique(np.asarray(seeds, dtype=np.int64))
    seeds = seeds[graph.degree()[seeds] > 0]
    member = np.zeros(n, dtype=bool)
    forbid = np.zeros(n, dtype=bool)
    if include_seeds:
        member[seeds] = True
    else:
        forbid[seeds] = True
    frontier = seeds
    while member.sum() < core_size and len(frontier):
        cand = _neighbors_mask(graph, frontier, n) & ~member & ~forbid
        cand_ids = np.flatnonzero(cand)
        room = core_size - int(member.sum())
        if len(cand_ids) > room:
            cand_ids = rng.choice(cand_ids, room, replace=False)
        member[cand_ids] = True
        frontier = np.sort(cand_ids)
    return np.flatnonzero(member)


def coverage_all(graph: Graph, core_ids) -> dict:
    """Share of nodes (with >= 1 edge) that are in the core or have >= 1 core neighbor."""
    n = graph.n
    ip = np.asarray(graph.indptr)
    core_mask = np.zeros(n, dtype=bool)
    core_mask[np.asarray(core_ids, dtype=np.int64)] = True
    has_edge = ip[1:] > ip[:-1]
    has_core_nb = np.zeros(n, dtype=bool)
    if has_edge.any():
        vals = core_mask[np.asarray(graph.indices)]
        sums = np.add.reduceat(vals, ip[:-1][has_edge], dtype=np.int32)   # segments of non-empty nodes
        has_core_nb[np.flatnonzero(has_edge)] = sums > 0
    covered = core_mask | has_core_nb
    return {"nodes_with_edges": int(has_edge.sum()),
            "core": int(core_mask.sum()),
            "covered_one_hop": int(covered[has_edge].sum()),
            "coverage": float(covered[has_edge].mean())}


def propagate_targets(core_ids, core_vecs: np.ndarray, graph: Graph, targets,
                      num_neighbors: int = 5, aggregation: str = "mean", seed: int = 0):
    """Embeddings for `targets`: core nodes keep their own vector; others average up to
    `num_neighbors` randomly sampled core neighbors (one hop, paper Sec IV-A).
    Returns (matrix [len(targets) x dim], covered mask)."""
    core_ids = np.asarray(core_ids, dtype=np.int64)
    rng = np.random.default_rng(seed)
    targets = np.asarray(targets, dtype=np.int64)
    out = np.zeros((len(targets), core_vecs.shape[1]), dtype=np.float32)
    ok = np.zeros(len(targets), dtype=bool)
    for k, t in enumerate(targets):
        pos = np.searchsorted(core_ids, t)
        if pos < len(core_ids) and core_ids[pos] == t:
            out[k], ok[k] = core_vecs[pos], True
            continue
        nb = np.asarray(graph.neighbors(int(t)), dtype=np.int64)
        if len(nb) == 0:
            continue
        p = np.searchsorted(core_ids, nb)
        p[p >= len(core_ids)] = 0
        in_core = core_ids[p] == nb
        cp = p[in_core]
        if len(cp) == 0:
            continue
        if len(cp) > num_neighbors:
            cp = rng.choice(cp, num_neighbors, replace=False)
        v = core_vecs[cp].astype(np.float64)
        out[k] = (v.mean(axis=0) if aggregation == "mean" else v.sum(axis=0)).astype(np.float32)
        ok[k] = True
    return out, ok
