import numpy as np
import pandas as pd

from risksea.graph.build import build_graph, edge_table
from risksea.graph.build_duckdb import build_global_graph, load_graph
from risksea.synth import generate_world


def _addr(i):
    return "0x" + format(int(i), "040x")


def test_duckdb_graph_matches_in_memory_graph(tmp_path):
    w = generate_world(n_blocks=20_000, n_users=150, n_hubs=4, n_miners=4, n_merchants=8,
                       n_fraud_clusters=3, cluster_size=6, n_decoys=2, seed=5)
    eth = w.tx[w.tx.kind == "eth"]
    erc = w.tx[w.tx.kind == "erc20"]

    def edges(t):
        e = edge_table(t)
        return pd.DataFrame({"src": e.src.map(_addr), "dst": e.dst.map(_addr), "tx_count": e["count"]})

    (tmp_path / "eth").mkdir(); (tmp_path / "erc").mkdir()
    edges(eth).to_parquet(tmp_path / "eth" / "part-0.parquet")
    erc_e = edge_table(erc)
    pd.DataFrame({"src": erc_e.src.map(_addr), "dst": erc_e.dst.map(_addr), "token": 0,
                  "tx_count": erc_e["count"]}).to_parquet(tmp_path / "erc" / "part-0.parquet")

    K = 25
    stats = build_global_graph((tmp_path / "eth" / "*.parquet").as_posix(),
                               (tmp_path / "erc" / "*.parquet").as_posix(),
                               tmp_path / "g", top_k=K, memory_limit="1GB", threads=2, log=lambda m: None)
    g = load_graph(tmp_path / "g", mmap=False)
    nodes = pd.read_parquet(tmp_path / "g" / "nodes.parquet")
    id_to_addr = dict(zip(nodes.id, nodes.addr))
    addr_to_int = lambda a: int(a, 16)

    # reference: same combined weights, built in memory
    ref_edges = edge_table(w.tx)
    ref = build_graph(ref_edges, len(w.nodes), top_k=K)

    assert stats["nodes"] == len(nodes)
    assert (g.degree() <= K).all()
    for i, addr in id_to_addr.items():
        orig = addr_to_int(addr)
        got = sorted(addr_to_int(id_to_addr[j]) for j in g.neighbors(i))
        assert got == sorted(ref.neighbors(orig).tolist()), orig
        wg = sorted(g.neighbor_weights(i).tolist())
        wr = sorted(ref.neighbor_weights(orig).tolist())
        assert np.allclose(wg, wr)
    assert g.indices.dtype == np.int32
    assert all(np.all(np.diff(g.neighbors(i)) > 0) for i in range(g.n))   # sorted, no duplicates
