import networkx as nx
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score

from risksea.embed.propagate import coverage, propagate, sample_core
from risksea.embed.static_n2v import StaticNode2Vec
from risksea.embed.walks import generate_walks, walks_to_sentences
from risksea.graph.build import Graph, build_graph, edge_table


def graph_from_pairs(pairs, n):
    e = pd.DataFrame(pairs, columns=["src", "dst"])
    e["count"] = 1.0
    return build_graph(e, n, top_k=None)


def test_walks_are_deterministic_and_valid():
    g = graph_from_pairs([(0, 1), (1, 2), (2, 3), (3, 0), (1, 3)], 4)
    w1 = generate_walks(g, [0, 1, 2, 3], 5, 8, seed=1)
    w2 = generate_walks(g, [0, 1, 2, 3], 5, 8, seed=1)
    assert np.array_equal(w1, w2)
    assert w1.shape == (20, 8)
    assert (w1 >= 0).all()
    # each step must follow an existing edge
    for row in w1:
        for a, b in zip(row[:-1], row[1:]):
            assert b in g.neighbors(a)


def test_walk_stops_at_isolated_node():
    g = graph_from_pairs([(0, 1)], 3)           # node 2 is isolated
    w = generate_walks(g, [2], 2, 5, seed=0)
    assert (w[:, 0] == 2).all() and (w[:, 1:] == -1).all()
    assert walks_to_sentences(w) == []


def test_transition_probabilities_match_p_q_formula():
    # edges: 0-1, 1-2, 1-3, 0-2.  State (prev=0, cur=1): neighbors of 1 are 0, 2, 3
    #   x=0 -> return (1/p) ; x=2 -> adjacent to 0 (1) ; x=3 -> not adjacent to 0 (1/q)
    g = graph_from_pairs([(0, 1), (1, 2), (1, 3), (0, 2)], 4)
    for p, q in [(1.0, 1.0), (0.25, 4.0), (4.0, 0.25)]:
        w = generate_walks(g, [0], 120_000, 3, p=p, q=q, weighted=False, seed=5)
        sel = w[w[:, 1] == 1]                    # walks that went 0 -> 1
        counts = np.array([(sel[:, 2] == x).sum() for x in (0, 2, 3)], float)
        emp = counts / counts.sum()
        exp = np.array([1 / p, 1.0, 1 / q])
        exp /= exp.sum()
        assert np.allclose(emp, exp, atol=0.015), (p, q, emp, exp)


def test_weighted_first_step_follows_edge_weights():
    e = pd.DataFrame({"src": [0, 0], "dst": [1, 2], "count": [9.0, 1.0]})
    g = build_graph(e, 3, top_k=None)
    w = generate_walks(g, [0], 50_000, 2, weighted=True, seed=2)
    frac = (w[:, 1] == 1).mean()
    assert abs(frac - 0.9) < 0.01


def test_node2vec_recovers_planted_communities():
    sizes = [100, 100]
    G = nx.stochastic_block_model(sizes, [[0.15, 0.01], [0.01, 0.15]], seed=3)
    pairs = list(G.edges())
    g = graph_from_pairs(pairs, 200)
    y = np.array([0] * 100 + [1] * 100)
    emb = StaticNode2Vec(dim=32, num_walks=10, walk_length=20, window=5, epochs=3,
                         workers=1, seed=1).fit(g)
    X, mask = emb.embed(200)
    assert mask.all()
    acc = cross_val_score(LogisticRegression(max_iter=1000), X, y, cv=5).mean()
    assert acc > 0.9, acc


def test_propagation_averages_sampled_core_neighbors():
    # core nodes 0..7 have one-hot embeddings; node 8 touches core {0,1}; node 9 touches core 0..7
    # node 10 touches only non-core node 8 (needs 2 hops -> must stay uncovered)
    n = 11
    pairs = [(8, 0), (8, 1)] + [(9, i) for i in range(8)] + [(10, 8)]
    g = graph_from_pairs(pairs, n)
    emb = np.zeros((n, 8), np.float32)
    emb[np.arange(8), np.arange(8)] = 1.0
    mask = np.zeros(n, bool); mask[:8] = True
    out, m = propagate(emb, mask, g, num_neighbors=5, seed=0)
    assert np.allclose(out[:8], emb[:8])                       # core untouched
    assert np.allclose(out[8], [0.5, 0.5, 0, 0, 0, 0, 0, 0])   # mean of its 2 core neighbors
    assert m[8] and m[9] and not m[10]                         # one hop only
    # node 9 had 8 core neighbors; exactly 5 sampled, each contributing 1/5
    assert np.isclose(out[9].sum(), 1.0)
    assert (out[9] > 0).sum() == 5 and np.allclose(out[9][out[9] > 0], 0.2)
    cov = coverage(m, g)
    assert abs(cov["overall"] - 10 / 11) < 1e-9


def test_sample_core_includes_labeled_and_respects_size():
    g = graph_from_pairs([(0, 1), (0, 2), (3, 4), (5, 6)], 7)
    core = sample_core(g, [0], core_size=10)
    assert set(core) == {0, 1, 2}
    core2 = sample_core(g, [0, 3, 5], core_size=4, seed=1)
    assert len(core2) == 4
