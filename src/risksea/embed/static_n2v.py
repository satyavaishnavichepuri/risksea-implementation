"""Static node2vec: biased walks + skip-gram (gensim Word2Vec, sg=1)  (M2.3/M2.4).

Also defines the small embedder interface used across the project so alternative
embedders (e.g. a GNN) can be dropped in later:
    fit(graph, nodes) -> self ;  embed(n_nodes) -> (matrix [n_nodes, dim], has_embedding mask)
"""
from __future__ import annotations

import numpy as np
from gensim.models import Word2Vec

from risksea.embed.walks import generate_walks, walks_to_sentences
from risksea.graph.build import Graph


def keys_as_int(model: Word2Vec) -> np.ndarray:
    """Vocabulary keys (string tokens) as int64 node ids, aligned with model.wv.vectors."""
    ks = model.wv.index_to_key
    return np.fromiter((int(k) for k in ks), dtype=np.int64, count=len(ks))


def to_matrix(model: Word2Vec, n_nodes: int):
    """Dense (n_nodes x dim) matrix + boolean mask of nodes that have an embedding."""
    dim = model.vector_size
    mat = np.zeros((n_nodes, dim), dtype=np.float32)
    mask = np.zeros(n_nodes, dtype=bool)
    keys = keys_as_int(model)
    mat[keys] = model.wv.vectors
    mask[keys] = True
    return mat, mask


class StaticNode2Vec:
    def __init__(self, dim=128, num_walks=10, walk_length=10, p=1.0, q=1.0, window=10,
                 negative=5, epochs=1, workers=4, weighted=True, seed=42):
        self.dim, self.num_walks, self.walk_length = dim, num_walks, walk_length
        self.p, self.q, self.window, self.negative = p, q, window, negative
        self.epochs, self.workers, self.weighted, self.seed = epochs, workers, weighted, seed
        self.model: Word2Vec | None = None

    @classmethod
    def from_config(cls, cfg: dict, seed: int | None = None):
        c = cfg["node2vec"]
        return cls(dim=c["dim"], num_walks=c["num_walks"], walk_length=c["walk_length"],
                   p=c["p"], q=c["q"], window=c["window"], negative=c["negative"],
                   epochs=c["epochs"], workers=c["workers"],
                   seed=cfg["seed"] if seed is None else seed)

    def fit(self, graph: Graph, nodes=None):
        """Train on walks started from `nodes` (default: every node with at least one neighbor)."""
        if nodes is None:
            nodes = np.flatnonzero(graph.degree() > 0)
        walks = generate_walks(graph, nodes, self.num_walks, self.walk_length,
                               self.p, self.q, self.weighted, seed=self.seed)
        sentences = walks_to_sentences(walks)
        self.model = Word2Vec(
            sentences=sentences, vector_size=self.dim, window=self.window, min_count=1,
            sg=1, hs=0, negative=self.negative, workers=self.workers, epochs=self.epochs,
            seed=self.seed)
        return self

    def embed(self, n_nodes: int):
        return to_matrix(self.model, n_nodes)
