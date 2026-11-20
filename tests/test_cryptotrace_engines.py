import pytest

from cryptotrace.engines import BFS, TTR, Haircut
from cryptotrace.labels import LabelStore
from cryptotrace.models import Edge, Label, TraceParams
from cryptotrace.providers.base import MemoryProvider

S, A, B, C, D1, HOT, MIX, U, X, Z, Q = ["0x" + c * 40 for c in "123456789abcdef"][:11]
T0 = 1000
HOUR = 3600


def world(extra=()):
    es = [
        Edge(U, S, 100.0, 900, 1, "tx_fund"),       # upstream funding of the source (backward edge)
        Edge(S, A, 60.0, 1100, 2, "tx_sa"),
        Edge(S, B, 40.0, 1100, 2, "tx_sb"),
        Edge(X, A, 5.0, 1050, 1, "tx_xa"),          # another funder paying A inside the window, before S's funds arrive
        Edge(A, Z, 5.0, 1050, 1, "tx_az_old"),      # outflow BEFORE S's funds reach A (1100): time-respecting must skip
        Edge(A, D1, 60.0, 1200, 3, "tx_ad"),
        Edge(D1, HOT, 60.0, 1300, 4, "tx_dh"),      # sweep to a labeled exchange hot wallet within 48 h
        Edge(B, C, 40.0, 1200, 3, "tx_bc"),
        Edge(C, MIX, 40.0, 1300, 4, "tx_cm"),       # ends in a mixer
        Edge(B, Q, 0.5, 5000, 9, "tx_bq"),          # tiny later outflow
    ] + list(extra)
    return MemoryProvider(es)


def labels():
    ls = LabelStore()
    ls.add(HOT, Label("exchange", "ExampleEx", "test"))
    ls.add(MIX, Label("mixer", "Example Mixer", "test"))
    return ls


PARAMS = TraceParams(max_rounds=6, min_eth=0.0, hub_degree=1000, bfs_depth=2)


def run(engine, params=PARAMS, extra=()):
    return engine(world(extra), labels(), params).run(S, T0, 10 ** 7)


def by_node(res):
    return {t["node"]: t for t in res["terminals"]}


def test_ttr_finds_the_exchange_deposit_and_the_mixer_with_correct_shares():
    res = run(TTR)
    t = by_node(res)
    assert t[D1]["kind"] == "exchange_deposit" and t[D1]["name"] == "ExampleEx"
    assert t[D1]["confidence"] == "medium" and "sweep rule" in t[D1]["reason"]
    assert t[MIX]["kind"] == "mixer"
    assert t[D1]["share"] == pytest.approx(0.6, abs=0.01)
    assert t[MIX]["share"] == pytest.approx(0.4, abs=0.01)
    assert res["summary"]["nearest_exchange"] == "ExampleEx"


def test_evidence_path_is_a_time_ordered_chain_with_hashes():
    res = run(TTR)
    path = by_node(res)[D1]["path"]
    assert [e["tx"] for e in path] == ["tx_sa", "tx_ad"]
    assert all(path[i]["ts"] <= path[i + 1]["ts"] for i in range(len(path) - 1))
    assert path[0]["src"] == S and path[-1]["dst"] == D1


def test_time_respecting_ignores_outflows_before_funds_arrive():
    res = run(TTR)
    assert "tx_az_old" not in {e["tx"] for e in res["edges"]}
    loose = run(TTR, TraceParams(max_rounds=6, min_eth=0.0, hub_degree=1000, time_respecting=False))
    assert "tx_az_old" in {e["tx"] for e in loose["edges"]}      # the switch really changes behaviour


def test_upstream_funder_is_reported_but_never_as_a_destination():
    res = run(TTR)
    roles = {n["id"]: n["role"] for n in res["nodes"]}
    assert roles[X] == "upstream"
    assert X not in by_node(res)


def test_haircut_matches_ttr_on_this_simple_world():
    t = by_node(run(Haircut))
    assert t[D1]["share"] == pytest.approx(0.6, abs=0.01) and t[MIX]["share"] == pytest.approx(0.4, abs=0.01)


def test_blind_bfs_with_the_books_depth_limit_misses_the_exchange_but_deeper_search_finds_it():
    shallow = run(BFS)                                   # depth 2: only reaches D1's parent level
    assert shallow["summary"]["n_exchange_terminals"] == 0
    deep = run(BFS, TraceParams(max_rounds=6, min_eth=0.0, hub_degree=1000, bfs_depth=4))
    assert any(t["kind"] == "exchange" for t in deep["terminals"])


def test_unlabeled_high_activity_node_is_treated_as_a_service_hub():
    extra = [Edge("0x" + "e" * 40, A, 1.0, 1100 + i, 5, f"h{i}") for i in range(20)]
    res = run(TTR, TraceParams(max_rounds=6, min_eth=0.0, hub_degree=10), extra=extra)
    assert any(t["kind"] == "service_hub" for t in res["terminals"]) or any(
        n["terminal"] and n["terminal"]["kind"] == "service_hub" for n in res["nodes"])


def test_typology_tags_pass_through_accounts():
    res = run(TTR)
    tags = {n["id"]: set(n["tags"]) for n in res["nodes"]}
    assert "zero_out" in tags[C] and "fast_hop" in tags[C]
    assert "zero_out" in tags[A]


def test_event_stream_is_ordered_and_complete():
    res = run(TTR)
    kinds = [e["kind"] for e in res["events"]]
    assert kinds[0] == "start" and kinds[-1] == "done" and "expand" in kinds and "absorb" in kinds
    rounds = [e["round"] for e in res["events"]]
    assert rounds == sorted(rounds)


def test_dust_threshold_and_degree_are_respected_by_the_provider():
    p = MemoryProvider([Edge(S, A, 0.001, 1100, 1, "d"), Edge(S, B, 5.0, 1100, 1, "b")], min_eth=0.01)
    fr = p.fetch({S: 0}, 10 ** 7)
    assert [e.tx for e in fr.edges] == ["b"]
