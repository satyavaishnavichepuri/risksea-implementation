"""FastAPI backend for the tracing MVP.

Run:  CRYPTOTRACE_BQ_PROJECT=<gcp project> uvicorn cryptotrace.api:app --app-dir src --port 8000
Live BigQuery use needs that env var and Application Default Credentials. Without them the benchmark cases, the
comparison and the zero-cost what-if mode (re-running a cached case with other algorithm parameters) all still work.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from cryptotrace.architecture import architecture
from cryptotrace.cases import CASES, ts
from cryptotrace.engines import ENGINES
from cryptotrace.evaluation import summarize
from cryptotrace.labels import LabelStore
from cryptotrace.models import TraceParams
from cryptotrace.providers.bigquery import BigQueryProvider, CacheMiss

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "cryptotrace"
CACHE = ROOT / "data" / "cryptotrace" / "cache.sqlite"
LABELS = LabelStore.from_files(ROOT / "data" / "labels")
GIB = 1024 ** 3
ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")

# what each case cost the first time it was fetched from BigQuery (later runs hit the cache and are free)
FIRST_RUN_GIB = {"cryptopia_2019": 9.51, "kucoin_2020": 3.87, "phishing_2018": 19.9}


def group_terminals(terms: list) -> list:
    """One row per receiving entity: many deposit addresses of one exchange are one finding, not many."""
    order = {"low": 0, "medium": 1, "high": 2}
    g: dict = {}
    for t in terms:
        a = g.setdefault((t["kind"], t["name"]), {"kind": t["kind"], "name": t["name"], "count": 0, "share": 0.0,
                                                  "eth_est": 0.0, "depth": t["depth"], "confidence": t["confidence"]})
        a["count"] += 1
        a["share"] += t["share"]
        a["eth_est"] += t["eth_est"]
        a["depth"] = min(a["depth"], t["depth"])
        if order[t["confidence"]] < order[a["confidence"]]:
            a["confidence"] = t["confidence"]
    return sorted(({**a, "share": round(a["share"], 6), "eth_est": round(a["eth_est"], 3)} for a in g.values()),
                  key=lambda x: -x["share"])

ENGINE_INFO = [
    {"id": "ttr", "label": "TTR-lite", "tagline": "ranked, time-respecting, value-weighted",
     "desc": "Personalised-PageRank-style push: follows outflows after the funds arrive, shares residual by amount, pulls a little relevance backward."},
    {"id": "haircut", "label": "Haircut taint", "tagline": "forward, value-proportional",
     "desc": "Classic taint tracking: each transfer carries the sender's tainted share forward in proportion to value. No ranking."},
    {"id": "bfs", "label": "Blind BFS", "tagline": "every neighbour, depth-limited",
     "desc": "Follows every outflow of every discovered address and ignores time and amounts. The book caps it at depth 2 because it explodes."},
]

app = FastAPI(title="CryptoTrace API", version="0.1")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# --------------------------------------------------------------------------------------------- models
class ParamsIn(BaseModel):
    alpha: float = Field(0.15, ge=0.01, le=0.5)
    beta: float = Field(0.8, ge=0.5, le=1.0)
    epsilon: float = Field(1e-3, ge=1e-4, le=1e-1)
    max_rounds: int = Field(8, ge=1, le=10)
    min_eth: float = Field(0.01, ge=0.001, le=10)
    hub_degree: int = Field(3000, ge=100, le=20000)
    time_respecting: bool = True
    bfs_depth: int = Field(2, ge=1, le=3)
    max_frontier: int = Field(300, ge=10, le=400)

    def to_params(self) -> TraceParams:
        return TraceParams(**self.model_dump())


class TraceIn(BaseModel):
    engine: str = "ttr"
    case_id: str | None = None                    # use a benchmark case's source and window
    source: str | None = None
    start: str | None = None                      # YYYY-MM-DD
    end: str | None = None
    params: ParamsIn = ParamsIn()
    live: bool = False                            # allow fresh BigQuery queries (billed, capped)


# --------------------------------------------------------------------------------------------- jobs
class Job:
    def __init__(self):
        self.id = uuid.uuid4().hex[:12]
        self.events: list = []
        self.result = None
        self.error = None
        self.done = False
        self.lock = threading.Lock()

    def push(self, obj):
        with self.lock:
            self.events.append(obj)


JOBS: dict[str, Job] = {}


def _provider(live: bool, params: TraceParams) -> BigQueryProvider:
    project = os.environ.get("CRYPTOTRACE_BQ_PROJECT", "")
    if live and not project:
        raise HTTPException(503, "Live mode needs the CRYPTOTRACE_BQ_PROJECT environment variable and BigQuery credentials.")
    return BigQueryProvider(project or "unused", CACHE, min_eth=params.min_eth, k=params.top_k,
                            budget_bytes=30 * GIB, cache_only=not live)


def _worker(job: Job, req: TraceIn, source: str, t0: int, t1: int):
    try:
        params = req.params.to_params()
        prov = _provider(req.live, params)
        tracer = ENGINES[req.engine](prov, LABELS, params, emit=lambda ev: job.push({"type": "event", **ev.to_json()}))
        res = tracer.run(source, t0, t1)
        res["case"] = req.case_id
        job.result = res
    except CacheMiss as e:
        job.error = {"code": "cache_miss", "message": str(e)}
    except Exception as e:  # surfaced to the UI, never swallowed
        job.error = {"code": "error", "message": f"{type(e).__name__}: {e}"}
    finally:
        job.done = True


# --------------------------------------------------------------------------------------------- routes
@app.get("/api/health")
def health():
    return {"ok": True, "labels": LABELS.counts(), "live_available": bool(os.environ.get("CRYPTOTRACE_BQ_PROJECT"))}


@app.get("/api/meta")
def meta():
    return {"engines": ENGINE_INFO, "defaults": ParamsIn().model_dump(), "labels": LABELS.counts(),
            "live_available": bool(os.environ.get("CRYPTOTRACE_BQ_PROJECT")),
            "limits": ["ETH only: external transfers, no internal contract transfers and no ERC-20 yet",
                       "Public BigQuery data has an update lag, so this is near-real-time, not real-time",
                       "Only each address's 200 largest transfers per direction are considered",
                       "Mixers and DEX contracts end the trace: that is a property of the chain, not a bug"]}


def _load(case_id: str, engine: str):
    f = RESULTS / f"{case_id}_{engine}.json"
    if not f.exists():
        raise HTTPException(404, f"No stored result for {case_id}/{engine}")
    return json.loads(f.read_text())


@app.get("/api/cases")
def cases():
    out = []
    for c in CASES.values():
        d = c.to_json()
        d["first_run_gib"] = FIRST_RUN_GIB.get(c.id)
        d["available"] = [e["id"] for e in ENGINE_INFO if (RESULTS / f"{c.id}_{e['id']}.json").exists()]
        if "ttr" in d["available"]:
            r = _load(c.id, "ttr")
            d["headline"] = {"terminals": group_terminals(r["terminals"])[:3], "source_out_eth": r["summary"]["source_out_eth"],
                             "nodes": r["stats"]["nodes_in_graph"], "rounds": r["stats"]["rounds"]}
        out.append(d)
    return out


@app.get("/api/cases/{case_id}/trace/{engine}")
def case_trace(case_id: str, engine: str):
    if case_id not in CASES:
        raise HTTPException(404, "unknown case")
    return _load(case_id, engine)


@app.get("/api/cases/{case_id}/compare")
def case_compare(case_id: str):
    if case_id not in CASES:
        raise HTTPException(404, "unknown case")
    case = CASES[case_id]
    rows = []
    for e in ENGINE_INFO:
        f = RESULTS / f"{case_id}_{e['id']}.json"
        if f.exists():
            rows.append(summarize(json.loads(f.read_text()), case))
    return {"case": case.to_json(), "rows": rows, "first_run_gib": FIRST_RUN_GIB.get(case_id)}


@app.post("/api/trace")
def start_trace(req: TraceIn):
    if req.engine not in ENGINES:
        raise HTTPException(400, "unknown engine")
    if req.case_id:
        if req.case_id not in CASES:
            raise HTTPException(404, "unknown case")
        c = CASES[req.case_id]
        source, t0, t1 = c.source, c.t0, c.t1
    else:
        if not (req.source and req.start and req.end and ADDR.match(req.source)):
            raise HTTPException(400, "give a case_id, or a valid 0x address with start and end dates (YYYY-MM-DD)")
        try:
            t0, t1 = ts(req.start), ts(req.end)
        except ValueError:
            raise HTTPException(400, "dates must be YYYY-MM-DD")
        if t1 <= t0 or (t1 - t0) > 120 * 86400:
            raise HTTPException(400, "the window must be positive and at most 120 days")
        source = req.source.lower()
    job = Job()
    JOBS[job.id] = job
    threading.Thread(target=_worker, args=(job, req, source, t0, t1), daemon=True).start()
    return {"job_id": job.id}


def _sse(job: Job):
    i = 0
    while True:
        with job.lock:
            chunk, done = job.events[i:], job.done
        for ev in chunk:
            yield f"data: {json.dumps(ev)}\n\n"
            i += 1
        if done and i >= len(job.events):
            break
        time.sleep(0.05)
    if job.error:
        yield f"data: {json.dumps({'type': 'error', **job.error})}\n\n"
    else:
        yield f"data: {json.dumps({'type': 'result', 'result': job.result})}\n\n"


@app.get("/api/jobs/{job_id}/stream")
def stream(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "unknown job")
    return StreamingResponse(_sse(job), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/architecture")
def arch():
    return architecture()


# --------------------------------------------------------------------------------------------- static UI (production build)
DIST = ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = DIST / path
        return FileResponse(f if f.is_file() else DIST / "index.html")
