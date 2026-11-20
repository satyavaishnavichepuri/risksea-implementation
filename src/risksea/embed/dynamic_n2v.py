"""DynN2VChain: incremental dynamic node2vec (M2.5, paper Sec IV-C/D/E, Algorithm 3).

Following dynnode2vec:
  1. Train static node2vec on the first snapshot G1.
  2. For each later snapshot, take the *delta nodes* (addresses that transacted since the
     last run), generate *evolving walks* only from those nodes -- but over the FULL current
     graph, so a new edge A-C is visible to A's walk decisions -- then
  3. update the skip-gram vocabulary with the new walks and continue training from the
     previous weights (warm start). Nodes absent from the delta walks keep their vectors.
The walk generator is pluggable (`walk_fn`) so the partitioned/distributed generator
(embed/distributed_walks.py) can replace the in-memory one.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from risksea.embed.static_n2v import StaticNode2Vec
from risksea.embed.walks import generate_walks, walks_to_sentences
from risksea.graph.build import Graph, graph_at


def find_delta_nodes(tx: pd.DataFrame, lo_block: int, hi_block: int) -> np.ndarray:
    """Addresses with at least one transfer in blocks (lo_block, hi_block]."""
    t = tx[(tx.block > lo_block) & (tx.block <= hi_block)]
    return np.unique(np.concatenate([t.src.to_numpy(), t.dst.to_numpy()]))


class DynamicNode2Vec(StaticNode2Vec):
    def __init__(self, *args, walk_fn=generate_walks, **kw):
        super().__init__(*args, **kw)
        self.walk_fn = walk_fn
        self.n_updates = 0

    def fit_initial(self, graph: Graph):
        return self.fit(graph)

    def update(self, graph: Graph, delta_nodes) -> dict:
        """One incremental step: evolving walks from delta nodes -> warm-start skip-gram."""
        self.n_updates += 1
        delta_nodes = np.asarray(delta_nodes, dtype=np.int64)
        delta_nodes = delta_nodes[graph.degree()[delta_nodes] > 0] if len(delta_nodes) else delta_nodes
        if len(delta_nodes) == 0:
            return {"n_walks": 0, "n_nodes_in_walks": 0}
        walks = self.walk_fn(graph, delta_nodes, self.num_walks, self.walk_length,
                             self.p, self.q, self.weighted, seed=self.seed + self.n_updates)
        sentences = walks_to_sentences(walks)
        if not sentences:
            return {"n_walks": 0, "n_nodes_in_walks": 0}
        self.model.build_vocab(sentences, update=True)
        self.model.train(sentences, total_examples=len(sentences), epochs=self.epochs)
        return {"n_walks": len(sentences), "n_nodes_in_walks": int(np.unique(walks[walks >= 0]).size)}


def train_dynamic(tx: pd.DataFrame, n_nodes: int, checkpoints, step_blocks: int, cfg: dict,
                  top_k: int | None = 200, walk_fn=generate_walks, workers: int | None = None):
    """Run the incremental pipeline across checkpoint blocks.

    checkpoints: sorted block numbers, e.g. [5M, 8M, 10M, 16M]. The first is trained
    statically; between checkpoints we step every `step_blocks` blocks (decision D8).
    Returns {checkpoint: {"emb": matrix, "mask": mask, "seconds": cumulative, "steps": int}}.
    """
    cps = sorted(int(c) for c in checkpoints)
    c = cfg["node2vec"]
    model = DynamicNode2Vec(
        dim=c["dim"], num_walks=c["num_walks"], walk_length=c["walk_length"], p=c["p"], q=c["q"],
        window=c["window"], negative=c["negative"], epochs=c["epochs"],
        workers=c["workers"] if workers is None else workers, seed=cfg["seed"], walk_fn=walk_fn)
    t0 = time.time()
    model.fit_initial(graph_at(tx, n_nodes, cps[0], top_k))
    out = {cps[0]: _snap(model, n_nodes, t0, 0)}
    prev, steps = cps[0], 0
    for target in cps[1:]:
        bounds = list(range(prev + step_blocks, target, step_blocks)) + [target]
        for b in bounds:
            g = graph_at(tx, n_nodes, b, top_k)
            model.update(g, find_delta_nodes(tx, prev, b))
            prev, steps = b, steps + 1
        out[target] = _snap(model, n_nodes, t0, steps)
    return out


def _snap(model, n_nodes, t0, steps):
    emb, mask = model.embed(n_nodes)
    return {"emb": emb, "mask": mask, "seconds": time.time() - t0, "steps": steps}
