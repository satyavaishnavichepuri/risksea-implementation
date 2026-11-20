import numpy as np
import pandas as pd
import pytest

from risksea.features.behavioral import behavioral_features
from risksea.graph.build import build_graph, edge_table, graph_at
from risksea.synth import generate_world


def _tx(rows):
    df = pd.DataFrame(rows, columns=["src", "dst", "block", "value", "kind", "token"])
    df["ts"] = 1000 + df["block"] * 10
    return df


TOY = _tx([
    (0, 1, 1, 2.0, "eth", -1),
    (0, 1, 2, 4.0, "eth", -1),
    (0, 2, 3, 6.0, "eth", -1),
    (1, 0, 4, 10.0, "eth", -1),
    (2, 0, 5, 1.0, "erc20", 3),
    (2, 0, 6, 3.0, "erc20", 4),
])


# ---------------- graph ----------------

def test_edge_table_aggregates_pairs():
    e = edge_table(TOY).set_index(["src", "dst"])
    assert e.loc[(0, 1), "count"] == 2
    assert e.loc[(0, 1), "value"] == 6.0
    assert e.loc[(0, 1), "first_block"] == 1 and e.loc[(0, 1), "last_block"] == 2


def test_block_range_filters_edges():
    e = edge_table(TOY, upto_block=2)
    assert len(e) == 1 and e.iloc[0]["count"] == 2


def test_undirected_graph_is_symmetric_with_summed_weights():
    g = build_graph(edge_table(TOY), 3, top_k=None)
    assert list(g.neighbors(0)) == [1, 2]
    # 0<->1: 2 tx out + 1 tx in = 3 ; 0<->2: 1 out + 2 in = 3
    assert list(g.neighbor_weights(0)) == [3.0, 3.0]
    assert list(g.neighbors(1)) == [0] and list(g.neighbors(2)) == [0]


def test_directed_graph_keeps_direction():
    g = build_graph(edge_table(TOY), 3, top_k=None, directed=True)
    assert list(g.neighbors(0)) == [1, 2]
    assert list(g.neighbors(1)) == [0]


def test_top_k_caps_hub_degree_keeping_heaviest():
    rows = [(0, i, 1, 1.0, "eth", -1) for i in range(1, 11)]
    rows += [(0, 5, b, 1.0, "eth", -1) for b in range(2, 8)]   # node 5 becomes heaviest
    g = build_graph(edge_table(_tx(rows)), 11, top_k=3)
    assert g.degree()[0] == 3
    assert 5 in g.neighbors(0)
    assert np.all(np.diff(g.indptr) >= 0)


def test_graph_snapshots_grow_monotonically():
    w = generate_world(n_blocks=20_000, n_users=200, n_hubs=4, n_miners=4, n_merchants=8,
                       n_fraud_clusters=4, cluster_size=6, n_decoys=2, seed=3)
    n = len(w.nodes)
    g1 = graph_at(w.tx, n, 5_000, top_k=None)
    g2 = graph_at(w.tx, n, 15_000, top_k=None)
    assert g2.n_edges >= g1.n_edges
    assert (g2.degree() >= g1.degree()).all()


# ---------------- behavioral features ----------------

def test_behavioral_values_match_hand_computation():
    f = behavioral_features(TOY, 3)
    assert f.loc[0, "eth_out_n"] == 3
    assert f.loc[0, "eth_out_total"] == 12.0
    assert f.loc[0, "eth_out_mean"] == 4.0
    assert f.loc[0, "eth_out_min"] == 2.0 and f.loc[0, "eth_out_max"] == 6.0
    assert f.loc[0, "eth_out_median"] == 4.0
    assert f.loc[0, "eth_out_n_counterparties"] == 2
    assert f.loc[0, "eth_in_n"] == 1 and f.loc[0, "eth_in_total"] == 10.0
    # gaps for node 0 outgoing eth are 10s,10s -> mean 10, std 0, perfectly regular
    assert f.loc[0, "eth_out_gap_mean"] == 10.0 and f.loc[0, "eth_out_gap_std"] == 0.0
    assert f.loc[0, "eth_out_burstiness"] == -1.0
    assert f.loc[0, "eth_out_span"] == 20.0
    # erc20: node 2 sent two transfers of two distinct tokens
    assert f.loc[2, "erc20_out_n"] == 2 and f.loc[2, "erc20_out_n_tokens"] == 2
    assert f.loc[0, "erc20_in_n"] == 2
    # node with no erc20 activity -> zeros and inactive flag
    assert f.loc[1, "erc20_active"] == 0.0 and f.loc[1, "erc20_out_n"] == 0


def test_features_have_no_future_leakage():
    cut = 4
    full = behavioral_features(TOY, 3, upto_block=cut)
    trunc = behavioral_features(TOY[TOY.block <= cut], 3)
    pd.testing.assert_frame_equal(full, trunc)


def test_features_finite_and_one_row_per_node():
    w = generate_world(n_blocks=20_000, n_users=200, n_hubs=4, n_miners=4, n_merchants=8,
                       n_fraud_clusters=4, cluster_size=6, n_decoys=2, seed=3)
    f = behavioral_features(w.tx, len(w.nodes))
    assert len(f) == len(w.nodes)
    assert np.isfinite(f.to_numpy()).all()
    assert f.shape[1] > 60
