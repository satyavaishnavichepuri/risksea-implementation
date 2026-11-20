"""Horizontally scalable random walks (M2.6, paper Sec IV-E, Algorithm 2).

Split-apply-combine over a *partitioned neighbor store*:
  store   - the graph is written as NodeNeighborLists partitioned by source node
            (node % n_partitions), neighbors already capped to top-K by interaction count.
  split   - the delta/start nodes are divided into independent tasks.
  apply   - each task runs its walks, loading only the small partition files it needs
            (lazily, cached per process) -- the whole graph never sits in one process.
  combine - walks are merged back by their global walk index (and could be written to a
            distributed file system partitioned by source).

The randomness uses the same per-walk uniform stream as `walks.generate_walks`
(row r of the uniform matrix = draws [r*(L-1), (r+1)*(L-1)) of PCG64(seed)), so the
distributed output is *bit-identical* to the in-memory generator. That is the test
that proves the distribution did not change the algorithm.

The kernel here is plain Python (the reference/portable form: the same function body
can be mapped over a Spark RDD/DataFrame). Locally tasks run in a process pool.
"""
from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from risksea.graph.build import Graph


# ---------------------------------------------------------------- store
def write_neighbor_store(graph: Graph, directory: str | Path, n_partitions: int = 8) -> Path:
    """Write the graph as per-partition neighbor lists (partitioned by node % n_partitions)."""
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    nodes_all = np.arange(graph.n)
    for part in range(n_partitions):
        nodes = nodes_all[nodes_all % n_partitions == part]
        nodes = nodes[graph.degree()[nodes] > 0]
        indptr = np.zeros(len(nodes) + 1, dtype=np.int64)
        indptr[1:] = np.cumsum(graph.degree()[nodes])
        idx = [graph.neighbors(int(v)) for v in nodes]
        wts = [graph.neighbor_weights(int(v)) for v in nodes]
        np.savez(d / f"part_{part:05d}.npz", nodes=nodes, indptr=indptr,
                 indices=np.concatenate(idx) if idx else np.empty(0, np.int64),
                 weights=np.concatenate(wts) if wts else np.empty(0, np.float64))
    (d / "META").write_text(str(n_partitions))
    return d


class NeighborStore:
    """Lazy reader: loads one partition file the first time one of its nodes is requested."""

    def __init__(self, directory: str | Path):
        self.dir = Path(directory)
        self.n_partitions = int((self.dir / "META").read_text())
        self._cache: dict[int, tuple] = {}
        self.files_loaded = 0

    def _part(self, p: int):
        if p not in self._cache:
            z = np.load(self.dir / f"part_{p:05d}.npz")
            self._cache[p] = (z["nodes"], z["indptr"], z["indices"], z["weights"])
            self.files_loaded += 1
        return self._cache[p]

    def neighbors(self, v: int):
        nodes, indptr, indices, weights = self._part(v % self.n_partitions)
        k = np.searchsorted(nodes, v)
        if k >= len(nodes) or nodes[k] != v:
            return indices[:0], weights[:0]
        return indices[indptr[k]:indptr[k + 1]], weights[indptr[k]:indptr[k + 1]]


# ---------------------------------------------------------------- kernel
def _uniforms_for_walk(seed: int, row: int, n_draws: int) -> np.ndarray:
    bg = np.random.PCG64(np.random.SeedSequence(seed))
    bg.advance(row * n_draws)
    return np.random.Generator(bg).random(n_draws)


def _one_walk(store: NeighborStore, start: int, U, p, q, weighted, L):
    out = np.full(L, -1, dtype=np.int64)
    cur = start
    out[0] = cur
    prev = -1
    for s in range(1, L):
        nb, wt = store.neighbors(cur)
        if len(nb) == 0:
            break
        pn = store.neighbors(prev)[0] if prev >= 0 else None
        ws = []
        for j in range(len(nb)):
            w = wt[j] if weighted else 1.0
            if prev >= 0:
                x = nb[j]
                if x == prev:
                    w = w / p
                else:
                    k = np.searchsorted(pn, x)
                    if not (k < len(pn) and pn[k] == x):
                        w = w / q
            ws.append(w)
        total = 0.0
        for w in ws:
            total += w
        r = U[s - 1] * total
        acc = 0.0
        chosen = len(nb) - 1
        for j, w in enumerate(ws):
            acc += w
            if r < acc:
                chosen = j
                break
        nxt = int(nb[chosen])
        out[s] = nxt
        prev, cur = cur, nxt
    return out


def _task(args):
    directory, start_nodes, node_offset, n_total_nodes, num_walks, L, p, q, weighted, seed = args
    store = NeighborStore(directory)
    rows, walks = [], []
    for rnd in range(num_walks):
        for i, v in enumerate(start_nodes):
            row = rnd * n_total_nodes + node_offset + i       # global walk index
            U = _uniforms_for_walk(seed, row, max(L - 1, 1))
            rows.append(row)
            walks.append(_one_walk(store, int(v), U, p, q, weighted, L))
    return np.array(rows), np.array(walks), store.files_loaded


def distributed_walks(store_dir: str | Path, start_nodes, num_walks: int, walk_length: int,
                      p: float = 1.0, q: float = 1.0, weighted: bool = True, seed: int = 0,
                      n_tasks: int = 4, max_workers: int | None = 2):
    """Split start nodes into tasks, run walks against the partitioned store, combine.

    Returns (walks [len(start_nodes)*num_walks, L] in the same order as
    `walks.generate_walks`, total partition files loaded across tasks).
    """
    start_nodes = np.asarray(start_nodes, dtype=np.int64)
    n = len(start_nodes)
    splits = np.array_split(np.arange(n), max(1, min(n_tasks, n)))
    jobs = [(str(store_dir), start_nodes[s], int(s[0]), n, num_walks, walk_length, p, q,
             weighted, seed) for s in splits if len(s)]
    if max_workers and max_workers > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=max_workers) as ex:
            results = list(ex.map(_task, jobs))
    else:
        results = [_task(j) for j in jobs]
    out = np.full((n * num_walks, walk_length), -1, dtype=np.int64)
    loaded = 0
    for rows, walks, files in results:                   # combine by global walk index
        out[rows] = walks
        loaded += files
    return out, loaded


def make_walk_fn(store_dir: str | Path, n_tasks: int = 4, max_workers: int | None = 2):
    """Adapter with the same signature as generate_walks, for DynamicNode2Vec(walk_fn=...).
    The caller must have written the *current* graph snapshot to store_dir."""
    def fn(graph, nodes, num_walks, walk_length, p, q, weighted, seed=0):
        return distributed_walks(store_dir, nodes, num_walks, walk_length, p, q, weighted,
                                 seed, n_tasks, max_workers)[0]
    return fn
