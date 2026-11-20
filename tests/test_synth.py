import numpy as np

from risksea.config import load_config, seed_everything
from risksea.synth import generate_world

SMALL = dict(n_blocks=20_000, n_users=300, n_hubs=5, n_miners=5, n_merchants=10,
             n_fraud_clusters=6, cluster_size=8, n_decoys=3, seed=7)


def test_config_loads_and_overrides():
    cfg = load_config(overrides={"node2vec": {"p": 2.0}})
    assert cfg["node2vec"]["p"] == 2.0
    assert cfg["node2vec"]["q"] == 1.0          # untouched sibling key
    assert cfg["graph"]["top_k_neighbors"] == 200


def test_seed_everything_returns_reproducible_rng():
    a = seed_everything(1).random(3)
    b = seed_everything(1).random(3)
    assert np.allclose(a, b)


def test_world_is_deterministic_by_seed():
    w1 = generate_world(**SMALL)
    w2 = generate_world(**SMALL)
    assert w1.tx.equals(w2.tx) and w1.labels.equals(w2.labels)
    w3 = generate_world(**{**SMALL, "seed": 8})
    assert not w1.tx.equals(w3.tx)


def test_world_basic_invariants():
    w = generate_world(**SMALL)
    tx = w.tx
    assert (tx.src != tx.dst).all()
    assert tx.block.between(0, SMALL["n_blocks"] - 1).all()
    assert tx.block.is_monotonic_increasing
    assert set(tx.kind) == {"eth", "erc20"}
    assert (tx.token[tx.kind == "eth"] == -1).all()
    n_nodes = len(w.nodes)
    assert tx.src.max() < n_nodes and tx.dst.max() < n_nodes


def test_planted_structure_is_present():
    w = generate_world(**SMALL)
    roles = w.nodes.set_index("node").role
    tx = w.tx
    # fraud mules are connected to each other inside their cluster
    cl = w.nodes.set_index("node").cluster
    mule_tx = tx[(tx.src.map(roles) == "mule") & (tx.dst.map(roles) == "mule")]
    assert len(mule_tx) > 0
    assert (mule_tx.src.map(cl) == mule_tx.dst.map(cl)).all()
    # hubs have much higher degree than ordinary users
    deg = np.bincount(np.concatenate([tx.src, tx.dst]), minlength=len(w.nodes))
    hub_deg = deg[w.nodes.node[w.nodes.role == "hub"]].mean()
    user_deg = deg[w.nodes.node[w.nodes.role == "user"]].mean()
    assert hub_deg > 5 * user_deg


def test_labels_cover_expected_roles():
    w = generate_world(**SMALL)
    bad = set(w.labels[w.labels.label == 1].role)
    good = set(w.labels[w.labels.label == 0].role)
    assert bad <= {"mother", "mule"} and "mother" in bad
    assert good == {"hub", "miner", "merchant"}
    assert w.labels.node.is_unique
