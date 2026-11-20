import numpy as np
import pandas as pd

from risksea.config import load_config
from risksea.embed.distributed_walks import NeighborStore, distributed_walks, write_neighbor_store
from risksea.embed.dynamic_n2v import DynamicNode2Vec, find_delta_nodes, train_dynamic
from risksea.embed.walks import generate_walks
from risksea.graph.build import build_graph, edge_table, graph_at
from risksea.synth import generate_world


def g_from_pairs(pairs, n, top_k=None):
    e = pd.DataFrame(pairs, columns=["src", "dst"])
    e["count"] = 1.0
    return build_graph(e, n, top_k=top_k)


SMALL = dict(n_blocks=20_000, n_users=250, n_hubs=4, n_miners=4, n_merchants=8,
             n_fraud_clusters=5, cluster_size=7, n_decoys=3, seed=11)


# ------------------------------------------------ delta nodes / evolving walks
def test_find_delta_nodes_uses_half_open_block_range():
    tx = pd.DataFrame({"src": [0, 1, 2], "dst": [1, 2, 3], "block": [5, 10, 15]})
    assert list(find_delta_nodes(tx, 5, 10)) == [1, 2]
    assert list(find_delta_nodes(tx, 0, 15)) == [0, 1, 2, 3]
    assert len(find_delta_nodes(tx, 15, 20)) == 0


def test_new_edge_is_visible_to_delta_walks():
    # old graph: A(0)-B(1).  new graph adds A-C(2).  Walks from A over the FULL new graph
    # must reach C about half the time; over the old graph never.
    old = g_from_pairs([(0, 1)], 3)
    new = g_from_pairs([(0, 1), (0, 2)], 3)
    w_old = generate_walks(old, [0], 4000, 2, seed=1)
    w_new = generate_walks(new, [0], 4000, 2, seed=1)
    assert (w_old[:, 1] == 2).sum() == 0
    assert abs((w_new[:, 1] == 2).mean() - 0.5) < 0.03


# ------------------------------------------------ warm-start update semantics
def _fitted(world, upto):
    n = len(world.nodes)
    m = DynamicNode2Vec(dim=16, num_walks=3, walk_length=8, window=4, epochs=2, workers=1, seed=3)
    m.fit_initial(graph_at(world.tx, n, upto, top_k=50))
    return m, n


def test_update_changes_walked_nodes_and_freezes_the_rest():
    w = generate_world(**SMALL)
    m, n = _fitted(w, 8_000)
    before, mask0 = m.embed(n)
    g = graph_at(w.tx, n, 14_000, top_k=50)
    delta = find_delta_nodes(w.tx, 8_000, 14_000)
    # restrict delta to a few nodes so many nodes are NOT in the delta walks
    delta = delta[:5]
    walks = generate_walks(g, delta, m.num_walks, m.walk_length, m.p, m.q, m.weighted,
                           seed=m.seed + 1)
    walked = np.unique(walks[walks >= 0])
    stats = m.update(g, delta)
    assert stats["n_nodes_in_walks"] == len(walked)
    after, mask1 = m.embed(n)
    untouched = np.flatnonzero(mask0 & ~np.isin(np.arange(n), walked))
    assert len(untouched) > 0
    assert np.array_equal(before[untouched], after[untouched])         # frozen
    moved = np.flatnonzero(mask0 & np.isin(np.arange(n), walked))
    assert not np.allclose(before[moved], after[moved])                # updated
    assert mask1.sum() >= mask0.sum()                                  # vocabulary only grows


def test_update_embeds_brand_new_nodes():
    w = generate_world(**SMALL)
    m, n = _fitted(w, 1_000)          # early snapshot: many nodes have not appeared yet
    _, mask0 = m.embed(n)
    g = graph_at(w.tx, n, 19_000, top_k=50)
    m.update(g, find_delta_nodes(w.tx, 1_000, 19_000))
    _, mask1 = m.embed(n)
    assert mask1.sum() > mask0.sum()


def test_train_dynamic_returns_snapshot_per_checkpoint():
    w = generate_world(**SMALL)
    cfg = load_config(overrides={"node2vec": {"dim": 8, "num_walks": 2, "walk_length": 6,
                                              "window": 3, "workers": 1}})
    out = train_dynamic(w.tx, len(w.nodes), [5_000, 10_000, 20_000], 5_000, cfg, top_k=50)
    assert sorted(out) == [5_000, 10_000, 20_000]
    assert out[5_000]["steps"] == 0 and out[10_000]["steps"] == 1 and out[20_000]["steps"] == 3
    cov = [out[c]["mask"].sum() for c in sorted(out)]
    assert cov == sorted(cov)                                          # coverage never shrinks
    assert out[20_000]["seconds"] >= out[10_000]["seconds"]


# ------------------------------------------------ distributed walk generator
def test_distributed_walks_are_bit_identical_to_in_memory(tmp_path):
    w = generate_world(**SMALL)
    n = len(w.nodes)
    g = graph_at(w.tx, n, 20_000, top_k=30)
    store = write_neighbor_store(g, tmp_path / "store", n_partitions=6)
    starts = np.flatnonzero(g.degree() > 0)[:60]
    for p, q, weighted in [(1.0, 1.0, True), (0.5, 2.0, True), (2.0, 0.5, False)]:
        ref = generate_walks(g, starts, 2, 7, p, q, weighted, seed=9)
        got, loaded = distributed_walks(store, starts, 2, 7, p, q, weighted, seed=9,
                                        n_tasks=3, max_workers=1)
        assert np.array_equal(ref, got), (p, q, weighted)


def test_distributed_walks_work_across_processes_and_load_lazily(tmp_path):
    w = generate_world(**SMALL)
    n = len(w.nodes)
    g = graph_at(w.tx, n, 20_000, top_k=30)
    store = write_neighbor_store(g, tmp_path / "store", n_partitions=16)
    starts = np.flatnonzero(g.degree() > 0)[:40]
    ref = generate_walks(g, starts, 2, 6, 1.0, 1.0, True, seed=4)
    got, loaded = distributed_walks(store, starts, 2, 6, 1.0, 1.0, True, seed=4,
                                    n_tasks=4, max_workers=2)
    assert np.array_equal(ref, got)
    assert loaded > 0


def test_neighbor_store_lookup_matches_graph(tmp_path):
    g = g_from_pairs([(0, 1), (0, 2), (3, 4)], 6)
    store = NeighborStore(write_neighbor_store(g, tmp_path / "s", n_partitions=3))
    for v in range(6):
        nb, wt = store.neighbors(v)
        assert list(nb) == list(g.neighbors(v)) and list(wt) == list(g.neighbor_weights(v))


def test_update_adds_new_nodes_even_when_their_id_is_below_the_vocabulary_size():
    """Regression: gensim treats an int token n as 'in vocab' when 0 <= n < len(vocab) (row-index
    semantics), which silently skipped new nodes with small ids. Tokens are now strings."""
    base = [(0, 1), (1, 2), (2, 0), (3, 4), (4, 5), (5, 3), (8, 9), (9, 10), (10, 8)]
    g1 = g_from_pairs(base, 11)
    g2 = g_from_pairs(base + [(0, 6)], 11)             # node 6 < vocabulary size (9) but NOT in the vocabulary
    m = DynamicNode2Vec(dim=8, num_walks=6, walk_length=4, window=2, epochs=2, workers=1, seed=0)
    m.fit_initial(g1)
    assert not m.embed(11)[1][6]
    m.update(g2, [0, 6])
    assert m.embed(11)[1][6]                            # node 6 must now have an embedding
