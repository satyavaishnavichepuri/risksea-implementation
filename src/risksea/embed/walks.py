"""Biased second-order node2vec random walks (M2.3), numba-accelerated.

From state (prev=t, cur=v) the next node x in N(v) is drawn with probability
proportional to  w(v,x) * alpha,  where alpha = 1/p if x == t (return),
1 if x is a neighbor of t (BFS-like), and 1/q otherwise (DFS-like).

Randomness is supplied as a pre-drawn uniform matrix so results are deterministic
for a given seed regardless of thread scheduling. Walk length L is the number of
nodes in the walk (paper: "number of nodes to visit"). Walks that hit a node with
no neighbors are padded with -1.
"""
from __future__ import annotations

import numpy as np
from numba import njit, prange

from risksea.graph.build import Graph


@njit(cache=True)
def _has_edge(indptr, indices, a, b):
    lo = indptr[a]
    hi = indptr[a + 1] - 1
    while lo <= hi:
        mid = (lo + hi) >> 1
        v = indices[mid]
        if v == b:
            return True
        if v < b:
            lo = mid + 1
        else:
            hi = mid - 1
    return False


@njit(parallel=True, cache=True)
def _walks_kernel(indptr, indices, weights, starts, U, p, q, weighted, L):
    n_walks = starts.shape[0]
    out = np.full((n_walks, L), -1, dtype=np.int64)
    for i in prange(n_walks):
        cur = starts[i]
        out[i, 0] = cur
        prev = -1
        for s in range(1, L):
            lo = indptr[cur]
            hi = indptr[cur + 1]
            if hi == lo:
                break
            total = 0.0
            for j in range(lo, hi):
                w = weights[j] if weighted else 1.0
                if prev >= 0:
                    x = indices[j]
                    if x == prev:
                        w = w / p
                    elif not _has_edge(indptr, indices, prev, x):
                        w = w / q
                total += w
            r = U[i, s - 1] * total
            acc = 0.0
            chosen = hi - 1
            for j in range(lo, hi):
                w = weights[j] if weighted else 1.0
                if prev >= 0:
                    x = indices[j]
                    if x == prev:
                        w = w / p
                    elif not _has_edge(indptr, indices, prev, x):
                        w = w / q
                acc += w
                if r < acc:
                    chosen = j
                    break
            nxt = indices[chosen]
            out[i, s] = nxt
            prev = cur
            cur = nxt
    return out


def generate_walks(graph: Graph, start_nodes, num_walks: int, walk_length: int,
                   p: float = 1.0, q: float = 1.0, weighted: bool = True,
                   seed: int = 0, chunk: int = 200_000) -> np.ndarray:
    """Return an int64 array (len(start_nodes)*num_walks, walk_length), -1 padded.

    Walk order: all start nodes for round 0, then round 1, ... (as in reference node2vec).
    """
    starts = np.tile(np.asarray(start_nodes, dtype=np.int64), num_walks)
    rng = np.random.default_rng(seed)
    parts = []
    for lo in range(0, len(starts), chunk):
        s = starts[lo:lo + chunk]
        U = rng.random((len(s), max(walk_length - 1, 1)))
        parts.append(_walks_kernel(graph.indptr, graph.indices, graph.weights, s, U,
                                   float(p), float(q), bool(weighted), int(walk_length)))
    if not parts:
        return np.empty((0, walk_length), dtype=np.int64)
    return np.concatenate(parts, axis=0)


def walks_to_sentences(walks: np.ndarray):
    """Strip -1 padding and return gensim sentences as lists of STRING tokens.
    Walks of length 1 carry no context and are dropped.

    Tokens are strings on purpose: gensim treats an int `n` as present in `model.wv` whenever
    0 <= n < vocab size (it reads it as a row index), so incremental vocabulary updates silently skip
    new nodes whose id is smaller than the vocabulary size. String keys have no such ambiguity."""
    out = []
    for row in walks:
        k = int((row >= 0).sum())
        if k > 1:
            out.append(list(map(str, row[:k].tolist())))
    return out
