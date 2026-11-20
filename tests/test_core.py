import numpy as np
import pandas as pd

from risksea.embed.core import coverage_all, grow_core, propagate_targets
from risksea.embed.propagate import coverage, propagate
from risksea.graph.build import build_graph


def graph_from_pairs(pairs, n):
    e = pd.DataFrame(pairs, columns=["src", "dst"])
    e["count"] = 1.0
    return build_graph(e, n, top_k=None)


# path 0-1-2-3-4-5-6, plus isolated 7 and a separate edge 8-9
PATH = graph_from_pairs([(i, i + 1) for i in range(6)] + [(8, 9)], 10)


def test_grow_core_keeps_seeds_and_expands_by_hops():
    core = grow_core(PATH, [3], core_size=3, seed=0)
    assert 3 in core and len(core) == 3 and set(core) == {2, 3, 4}          # hop 1 first
    core5 = grow_core(PATH, [3], core_size=5, seed=0)
    assert set(core5) == {1, 2, 3, 4, 5}                                      # then hop 2
    big = grow_core(PATH, [3], core_size=100, seed=0)
    assert set(big) == {0, 1, 2, 3, 4, 5, 6}                                  # stops at component edge
    assert (np.diff(big) > 0).all()                                           # sorted, unique


def test_grow_core_truncates_randomly_but_always_keeps_seeds():
    star = graph_from_pairs([(0, i) for i in range(1, 50)], 50)
    a = grow_core(star, [0], core_size=10, seed=1)
    b = grow_core(star, [0], core_size=10, seed=1)
    c = grow_core(star, [0], core_size=10, seed=2)
    assert len(a) == 10 and 0 in a and np.array_equal(a, b) and not np.array_equal(a, c)
    assert 7 not in grow_core(PATH, [7], 5)      # isolated seed has no edges -> dropped


def test_coverage_all_counts_core_plus_one_hop_only():
    cov = coverage_all(PATH, [3])
    # nodes with edges: 0-6, 8, 9 -> 9 nodes. covered: 3 (core), 2, 4 (neighbors) -> 3
    assert cov["nodes_with_edges"] == 9 and cov["core"] == 1 and cov["covered_one_hop"] == 3
    assert abs(cov["coverage"] - 3 / 9) < 1e-12


def test_coverage_all_matches_dense_propagation_coverage():
    core = np.array([1, 4, 8])
    emb = np.zeros((10, 2), np.float32)
    mask = np.zeros(10, bool); mask[core] = True
    _, m = propagate(emb, mask, PATH, seed=0)
    assert abs(coverage(m, PATH)["overall"] - coverage_all(PATH, core)["coverage"]) < 1e-12


def test_propagate_targets_semantics():
    n = 12
    # target 8 touches core {0,1}; target 9 touches core 0..7 (8 of them); 10 touches non-core 8 only
    pairs = [(8, 0), (8, 1)] + [(9, i) for i in range(8)] + [(10, 8)]
    g = graph_from_pairs(pairs, n)
    core_ids = np.arange(8)
    vecs = np.eye(8, dtype=np.float32)                        # one-hot -> easy to read the averages
    out, ok = propagate_targets(core_ids, vecs, g, targets=[3, 8, 9, 10, 11], num_neighbors=5, seed=0)
    assert np.allclose(out[0], vecs[3]) and ok[0]                              # core node keeps its vector
    assert np.allclose(out[1], [0.5, 0.5, 0, 0, 0, 0, 0, 0])                   # mean of its two core neighbors
    assert (out[2] > 0).sum() == 5 and np.allclose(out[2][out[2] > 0], 0.2)    # exactly 5 sampled
    assert not ok[3] and not ok[4]                                             # 2 hops away / isolated
    assert np.allclose(out[3:], 0)


def test_propagate_targets_deterministic_per_seed():
    g = graph_from_pairs([(8, i) for i in range(8)], 9)
    vecs = np.random.default_rng(0).normal(size=(8, 4)).astype(np.float32)
    a, _ = propagate_targets(np.arange(8), vecs, g, [8], seed=3)
    b, _ = propagate_targets(np.arange(8), vecs, g, [8], seed=3)
    assert np.array_equal(a, b)


def test_grow_core_can_exclude_seeds_and_still_reach_their_neighborhood():
    core = grow_core(PATH, [3], core_size=4, seed=0, include_seeds=False)
    assert 3 not in core                                    # seed is out of the core
    assert {2, 4} <= set(core)                              # but its neighbors are in
    assert set(core) == {1, 2, 4, 5}                        # hop 2 never re-adds the seed
    out, ok = propagate_targets(core, np.eye(len(core), dtype=np.float32), PATH, targets=[3], seed=0)
    assert ok[0] and abs(out[0].sum() - 1.0) < 1e-6         # the excluded seed is embedded by propagation
