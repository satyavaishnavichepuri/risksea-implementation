import json
import time

import pytest
from fastapi.testclient import TestClient

from cryptotrace import api

client = TestClient(api.app)


def test_health_and_meta():
    h = client.get("/api/health").json()
    assert h["ok"] and h["labels"]["exchange"] > 300
    m = client.get("/api/meta").json()
    assert {e["id"] for e in m["engines"]} == {"ttr", "haircut", "bfs"} and m["limits"]


def test_cases_list_has_headlines_for_both_benchmarks():
    cs = {c["id"]: c for c in client.get("/api/cases").json()}
    assert set(cs) == {"cryptopia_2019", "kucoin_2020", "phishing_2018"}
    assert cs["kucoin_2020"]["headline"]["terminals"][0]["kind"] == "mixer"
    assert cs["cryptopia_2019"]["headline"]["terminals"][0]["kind"] == "dex"
    top = cs["phishing_2018"]["headline"]["terminals"][0]            # 29 deposit addresses are ONE finding
    assert top["kind"] == "exchange_deposit" and top["count"] > 20 and top["share"] > 0.8


def test_phishing_case_separates_the_strategies_like_the_books_benchmark():
    rows = {r["engine"]: r for r in client.get("/api/cases/phishing_2018/compare").json()["rows"]}
    assert rows["ttr"]["exchange_terminals"] > 20 and rows["haircut"]["exchange_terminals"] > 20
    assert rows["bfs"]["terminals"] == 0                   # blind depth-2 BFS never reaches the deposit addresses
    assert rows["ttr"]["expected_total"] == 0              # no published answer for this case: stated, not faked


def test_stored_trace_and_comparison():
    t = client.get("/api/cases/kucoin_2020/trace/ttr").json()
    assert t["engine"] == "ttr" and t["events"] and t["terminals"][0]["path"]
    c = client.get("/api/cases/kucoin_2020/compare").json()
    assert {r["engine"] for r in c["rows"]} == {"ttr", "haircut", "bfs"}
    assert client.get("/api/cases/nope/compare").status_code == 404


def test_trace_validation_rejects_bad_input():
    assert client.post("/api/trace", json={"engine": "nope", "case_id": "kucoin_2020"}).status_code == 400
    assert client.post("/api/trace", json={"engine": "ttr", "source": "0x123"}).status_code == 400
    bad = {"engine": "ttr", "source": "0x" + "a" * 40, "start": "2019-01-01", "end": "2020-01-01"}
    assert client.post("/api/trace", json=bad).status_code == 400          # window > 120 days


def _run(body):
    job = client.post("/api/trace", json=body).json()["job_id"]
    with client.stream("GET", f"/api/jobs/{job}/stream") as r:
        msgs = [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: ")]
    return msgs


def test_cached_case_reruns_at_zero_cost_with_other_parameters_and_streams_events():
    msgs = _run({"engine": "ttr", "case_id": "kucoin_2020", "params": {"beta": 0.9, "epsilon": 0.005}})
    kinds = [m["type"] for m in msgs]
    assert kinds[-1] == "result" and "event" in kinds
    res = msgs[-1]["result"]
    assert res["params"]["beta"] == 0.9 and res["terminals"][0]["kind"] == "mixer"
    assert res["stats"]["queries"] == 0                                    # served entirely from the cache


def test_uncached_address_in_cache_only_mode_reports_a_clear_error():
    body = {"engine": "ttr", "source": "0x" + "ab" * 20, "start": "2020-09-25", "end": "2020-10-05"}
    msgs = _run(body)
    assert msgs[-1]["type"] == "error" and msgs[-1]["code"] == "cache_miss"
