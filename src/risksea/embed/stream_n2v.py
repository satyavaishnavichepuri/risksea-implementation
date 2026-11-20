"""Memory-bounded node2vec training: walks are generated lazily in chunks while gensim consumes them.

The in-memory trainer (static_n2v.py) materialises every walk as a Python list, which is
impossible at millions of nodes. Here:
  * WalkCorpus     - a restartable iterable; each pass regenerates the same walks chunk by chunk
                     (deterministic per seed), so peak memory is one chunk of walks.
  * vocabulary     - built from expected visit counts instead of a full counting pass over the
                     corpus. A random walk's stationary visit frequency is proportional to weighted
                     degree, so count_i ~ total_tokens * wdeg_i / sum(wdeg). These counts drive
                     gensim's negative-sampling distribution (and frequent-word subsampling).
Embeddings are a (n_nodes x dim) float32 matrix plus a has-embedding mask, as elsewhere.
"""
from __future__ import annotations

import numpy as np
from gensim.models import Word2Vec

from risksea.embed.static_n2v import StaticNode2Vec, to_matrix
from risksea.embed.walks import generate_walks
from risksea.graph.build import Graph


class WalkCorpus:
    """Iterate walks (lists of node ids) for `start_nodes`, `chunk_nodes` start nodes at a time."""

    def __init__(self, graph: Graph, start_nodes, num_walks, walk_length, p=1.0, q=1.0,
                 weighted=True, seed=0, chunk_nodes=50_000):
        self.graph = graph
        self.start_nodes = np.asarray(start_nodes, dtype=np.int64)
        self.num_walks, self.walk_length = num_walks, walk_length
        self.p, self.q, self.weighted, self.seed = p, q, weighted, seed
        self.chunk_nodes = chunk_nodes

    @property
    def total_walks(self) -> int:
        return len(self.start_nodes) * self.num_walks

    def __iter__(self):
        for ci, lo in enumerate(range(0, len(self.start_nodes), self.chunk_nodes)):
            chunk = self.start_nodes[lo:lo + self.chunk_nodes]
            walks = generate_walks(self.graph, chunk, self.num_walks, self.walk_length,
                                   self.p, self.q, self.weighted, seed=self.seed * 1_000_003 + ci)
            lengths = (walks >= 0).sum(axis=1)
            for row, k in zip(walks, lengths):
                if k > 1:                                  # length-1 walks carry no context
                    yield list(map(str, row[:k].tolist()))     # string tokens (see walks_to_sentences)


def expected_counts(graph: Graph, nodes, total_tokens: int) -> dict:
    """Vocabulary frequencies ~ stationary visit counts (proportional to weighted degree)."""
    nodes = np.asarray(nodes, dtype=np.int64)
    ip = np.asarray(graph.indptr)
    has = ip[1:] > ip[:-1]
    wdeg = np.zeros(graph.n, dtype=np.float64)
    if has.any():
        # segments of non-empty nodes are contiguous, so reduceat at their starts sums each exactly
        wdeg[has] = np.add.reduceat(np.asarray(graph.weights, dtype=np.float64), ip[:-1][has])
    w = wdeg[nodes]
    w = w / max(w.sum(), 1e-12)
    cnt = 1 + (total_tokens * w).astype(np.int64)
    return {str(int(n)): int(c) for n, c in zip(nodes, cnt)}      # string keys (see walks_to_sentences)


class StreamingNode2Vec(StaticNode2Vec):
    def __init__(self, *args, chunk_nodes=50_000, sample=1e-3, **kw):
        super().__init__(*args, **kw)
        self.chunk_nodes, self.sample = chunk_nodes, sample

    def corpus(self, graph: Graph, nodes) -> WalkCorpus:
        return WalkCorpus(graph, nodes, self.num_walks, self.walk_length, self.p, self.q,
                          self.weighted, self.seed, self.chunk_nodes)

    def fit(self, graph: Graph, nodes=None, vocab_nodes=None):
        """Train on walks started from `nodes`. `vocab_nodes` (default: `nodes`) is the full set of nodes
        that may appear in walks; pass it when starting walks from only a subset (e.g. timing runs)."""
        if nodes is None:
            nodes = np.flatnonzero(graph.degree() > 0)
        nodes = np.asarray(nodes, dtype=np.int64)
        nodes = nodes[graph.degree()[nodes] > 0]
        vocab = nodes if vocab_nodes is None else np.asarray(vocab_nodes, dtype=np.int64)
        vocab = vocab[graph.degree()[vocab] > 0]
        corpus = self.corpus(graph, nodes)
        counts = expected_counts(graph, vocab, corpus.total_walks * self.walk_length)
        self.model = Word2Vec(vector_size=self.dim, window=self.window, min_count=1, sg=1, hs=0,
                              negative=self.negative, workers=self.workers, seed=self.seed,
                              sample=self.sample)
        self.model.build_vocab_from_freq(counts)
        self.model.train(corpus, total_examples=corpus.total_walks, epochs=self.epochs)
        return self

    # ------------------------------------------------------------------ incremental (DynN2VChain)
    def update(self, graph: Graph, delta_nodes) -> dict:
        """One incremental step: walks from `delta_nodes` over the FULL current graph, vocabulary grown
        with any new nodes, skip-gram continued from the previous weights (warm start).

        A node with edges that is not yet in the vocabulary must have gained its first edge since the
        last step, so it is necessarily a delta node and appears in its own walks; only those are added.
        Nodes absent from the delta walks keep their vectors."""
        self.n_updates = getattr(self, "n_updates", 0) + 1
        delta = np.asarray(delta_nodes, dtype=np.int64)
        delta = delta[graph.degree()[delta] > 0] if len(delta) else delta
        if len(delta) == 0:
            return {"n_start_nodes": 0, "n_new_nodes": 0}
        corpus = WalkCorpus(graph, delta, self.num_walks, self.walk_length, self.p, self.q,
                            self.weighted, self.seed + self.n_updates, self.chunk_nodes)
        known = self.model.wv.key_to_index
        new = np.array([v for v in delta.tolist() if str(v) not in known], dtype=np.int64)
        if len(new):
            counts = expected_counts(graph, new, corpus.total_walks * self.walk_length)
            self.model.build_vocab_from_freq(counts, update=True)
        self.model.train(corpus, total_examples=corpus.total_walks, epochs=self.epochs)
        return {"n_start_nodes": int(len(delta)), "n_new_nodes": int(len(new))}

