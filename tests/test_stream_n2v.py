import networkx as nx
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score

from risksea.embed.stream_n2v import StreamingNode2Vec, WalkCorpus, expected_counts
from risksea.graph.build import build_graph


def graph_from_pairs(pairs, n):
    e = pd.DataFrame(pairs, columns=["src", "dst"])
    e["count"] = 1.0
    return build_graph(e, n, top_k=None)


def test_corpus_is_restartable_and_deterministic():
    g = graph_from_pairs([(0, 1), (1, 2), (2, 3), (3, 0), (1, 3), (4, 5)], 7)   # node 6 isolated
    c = WalkCorpus(g, np.arange(7), num_walks=3, walk_length=5, seed=2, chunk_nodes=2)
    a, b = list(c), list(c)
    assert a == b and len(a) > 0                      # a second pass yields identical walks
    assert all(len(w) > 1 for w in a)                 # single-node walks dropped
    assert c.total_walks == 21
    # chunk size must not change which walk set is produced per node count
    assert len(list(WalkCorpus(g, np.arange(7), 3, 5, seed=2, chunk_nodes=7))) == len(a)


def test_expected_counts_follow_weighted_degree():
    g = graph_from_pairs([(0, 1), (0, 2), (0, 3), (1, 2)], 5)                   # node 4 isolated
    cnt = {int(k): v for k, v in expected_counts(g, [0, 1, 2, 3], total_tokens=1000).items()}   # keys are string tokens
    # weighted degrees: 0->3, 1->2, 2->2, 3->1  => proportional counts
    assert cnt[0] > cnt[1] == cnt[2] > cnt[3]
    assert abs(sum(cnt.values()) - 1000) <= 4 + 4                                # +1 floor per node
    assert abs(cnt[0] / cnt[3] - 3) < 0.1


def test_streaming_node2vec_recovers_planted_communities():
    G = nx.stochastic_block_model([100, 100], [[0.15, 0.01], [0.01, 0.15]], seed=3)
    g = graph_from_pairs(list(G.edges()), 200)
    y = np.array([0] * 100 + [1] * 100)
    m = StreamingNode2Vec(dim=32, num_walks=10, walk_length=20, window=5, epochs=3, workers=1,
                          seed=1, chunk_nodes=40).fit(g)
    X, mask = m.embed(200)
    assert mask.all()
    assert cross_val_score(LogisticRegression(max_iter=1000), X, y, cv=5).mean() > 0.9


def test_streaming_fit_skips_isolated_nodes_and_respects_node_subset():
    g = graph_from_pairs([(0, 1), (1, 2), (2, 0), (3, 4)], 6)                   # node 5 isolated
    m = StreamingNode2Vec(dim=8, num_walks=4, walk_length=6, window=3, epochs=1, workers=1,
                          seed=0).fit(g, nodes=[0, 1, 2, 5])
    _, mask = m.embed(6)
    assert mask[0] and mask[1] and mask[2] and not mask[5]


def test_streaming_update_adds_new_nodes_and_freezes_untouched_ones():
    # three triangles {0,1,2} {3,4,5} {8,9,10}. Snapshot 2 adds node 6 (attached to 0) and a new edge 0-3.
    base = [(0, 1), (1, 2), (2, 0), (3, 4), (4, 5), (5, 3), (8, 9), (9, 10), (10, 8)]
    g1 = graph_from_pairs(base, 11)
    g2 = graph_from_pairs(base + [(0, 6), (0, 3)], 11)
    # sample=0: frequent-word downsampling would discard nearly every token of such a tiny corpus
    m = StreamingNode2Vec(dim=8, num_walks=6, walk_length=4, window=2, epochs=2, workers=1, seed=0,
                          sample=0).fit(g1)
    before, mask0 = m.embed(11)
    assert not mask0[6] and mask0[[0, 1, 2, 3, 4, 5, 8, 9, 10]].all()
    stats = m.update(g2, delta_nodes=[0, 6])
    after, mask1 = m.embed(11)
    assert stats["n_new_nodes"] == 1 and mask1[6]                    # node 6 now embedded
    # the exact walks the update trained on (same corpus parameters as StreamingNode2Vec.update)
    corpus = WalkCorpus(g2, np.array([0, 6]), m.num_walks, m.walk_length, m.p, m.q, m.weighted,
                        m.seed + 1, m.chunk_nodes)
    walked = {int(v) for sent in corpus for v in sent}
    assert 0 in walked and walked.isdisjoint({8, 9, 10})            # third component is out of reach
    old = [0, 1, 2, 3, 4, 5, 8, 9, 10]
    untouched = [v for v in old if v not in walked]
    assert untouched == [8, 9, 10]
    assert np.array_equal(before[untouched], after[untouched])       # frozen
    moved = [v for v in old if v in walked]
    assert not np.allclose(before[moved], after[moved])              # updated
    assert m.update(g2, delta_nodes=[]) == {"n_start_nodes": 0, "n_new_nodes": 0}
