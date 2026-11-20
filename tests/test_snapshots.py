import duckdb
import numpy as np
import pandas as pd

from risksea.graph.build import edge_table, graph_at
from risksea.graph.snapshots import build_universe_adj, csr_at, delta_nodes, load_adj
from risksea.synth import generate_world


def _addr(i):
    return "0x" + format(int(i), "040x")


def _write_inputs(tmp_path, w):
    def edges(t, token=False):
        e = edge_table(t)
        d = pd.DataFrame({"src": e.src.map(_addr), "dst": e.dst.map(_addr), "tx_count": e["count"],
                          "first_block": e["first_block"], "last_block": e["last_block"]})
        if token:
            d["token"] = 0
        return d
    (tmp_path / "eth").mkdir(); (tmp_path / "erc").mkdir()
    edges(w.tx[w.tx.kind == "eth"]).to_parquet(tmp_path / "eth" / "part-0.parquet")
    edges(w.tx[w.tx.kind == "erc20"], token=True).to_parquet(tmp_path / "erc" / "part-0.parquet")
    n = len(w.nodes)
    nodes = pd.DataFrame({"addr": [_addr(i) for i in range(n)], "id": np.arange(n, dtype=np.int32)})
    con = duckdb.connect()
    con.register("nodes", nodes)
    con.execute(f"COPY (SELECT addr, id, hash(addr) AS h FROM nodes) TO '{(tmp_path / 'nodes.parquet').as_posix()}' (FORMAT PARQUET)")
    return n


def test_snapshots_match_in_memory_graphs_and_deltas(tmp_path):
    w = generate_world(n_blocks=20_000, n_users=150, n_hubs=4, n_miners=4, n_merchants=8,
                       n_fraud_clusters=3, cluster_size=6, n_decoys=2, seed=5)
    n = _write_inputs(tmp_path, w)
    universe = np.arange(n)                                   # everyone: positions == ids
    adj_path = build_universe_adj((tmp_path / "eth" / "*.parquet").as_posix(),
                                  (tmp_path / "erc" / "*.parquet").as_posix(),
                                  (tmp_path / "nodes.parquet").as_posix(), universe, tmp_path / "snap",
                                  top_k=10_000, memory_limit="1GB", threads=2, log=lambda m: None)
    adj = load_adj(adj_path)
    for cut in (4_000, 12_000, 19_999):
        g = csr_at(adj, n, cut)
        ref = graph_at(w.tx, n, cut, top_k=None)
        for v in range(n):
            assert sorted(g.neighbors(v).tolist()) == sorted(ref.neighbors(v).tolist()), (cut, v)
        assert (g.weights == 1).all()
    # delta nodes = nodes whose adjacency grew in the window
    d = delta_nodes(adj, 4_000, 12_000)
    g1, g2 = csr_at(adj, n, 4_000), csr_at(adj, n, 12_000)
    grew = np.flatnonzero(g2.degree() > g1.degree())
    assert np.array_equal(np.sort(d), grew)


def test_universe_restricts_nodes_and_top_k_caps_degree_without_looking_ahead(tmp_path):
    w = generate_world(n_blocks=20_000, n_users=150, n_hubs=4, n_miners=4, n_merchants=8,
                       n_fraud_clusters=3, cluster_size=6, n_decoys=2, seed=5)
    n = _write_inputs(tmp_path, w)
    universe = np.sort(np.random.default_rng(0).choice(n, 120, replace=False))
    K = 7
    adj = load_adj(build_universe_adj((tmp_path / "eth" / "*.parquet").as_posix(),
                                      (tmp_path / "erc" / "*.parquet").as_posix(),
                                      (tmp_path / "nodes.parquet").as_posix(), universe, tmp_path / "snap",
                                      top_k=K, memory_limit="1GB", threads=2, log=lambda m: None))
    assert adj["a"].max() < 120 and adj["b"].max() < 120                  # positions inside the universe
    final = csr_at(adj, 120, 10**9)
    assert (final.degree() <= K).all()
    # snapshots only ever grow, and an edge never appears before its first block
    early, late = csr_at(adj, 120, 5_000), csr_at(adj, 120, 15_000)
    assert (late.degree() >= early.degree()).all()
    pos_to_id = universe
    src_dst_first = edge_table(w.tx).set_index(["src", "dst"])["first_block"]
    for v in range(120):
        for u in early.neighbors(v):
            pair = (pos_to_id[v], pos_to_id[u])
            fb = min(src_dst_first.get(pair, 10**9), src_dst_first.get(pair[::-1], 10**9))
            assert fb <= 5_000
