"""Shared machinery for the tracing engines: expansion, terminals, evidence paths, result building, event stream.

Vocabulary
  source     the reported suspect wallet (start of the trace)
  terminal   a node where tracing stops because funds reached a service: a labeled exchange, a mixer, a sanctioned
             address, an *inferred* exchange deposit address (see sweep rule) or a high-degree unknown hub
  share      estimated fraction of the source's funds that reached a node (value-proportional, time-respecting)
  rank       the engine's own relevance score (for TTR: personalised-PageRank-style rank)
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from cryptotrace.models import Edge, TraceEvent, TraceParams

SWEEP_WINDOW_S = 48 * 3600        # a deposit address forwards received funds within this long
SWEEP_SHARE = 0.80                # ... and at least this share of its outflow goes to labeled exchange wallet(s)
SWEEP_MAX_RECIPIENTS = 3
VIZ_MIN_SHARE = 0.01              # edges carrying less than this share of the funds are aggregated, not drawn


class Tracer:
    name = "base"
    label = "Base"

    def __init__(self, provider, labels, params: TraceParams | None = None, emit=None):
        self.provider, self.labels = provider, labels
        self.p = params or TraceParams()
        self._emit_cb = emit
        self.events: list = []
        self.warnings: list = []
        self.edges: dict = {}                  # key -> {"edge": Edge, "role": "fwd"|"back", "share": float}
        self.arrival: dict = {}                # node -> earliest arrival ts
        self.depth: dict = {}                  # node -> hops from source (forward)
        self.share: dict = defaultdict(float)  # node -> estimated fraction of source funds that reached it
        self.rank: dict = defaultdict(float)
        self.terminal: dict = {}               # node -> {"kind","name","reason","round"}
        self.degree: dict = {}                 # (node, dir) -> degree in window
        self.out_total: dict = {}              # node -> total outflow value (after arrival, capped list)
        self.fwd_edges_seen: list = []         # every forward edge considered (for path search)
        self.seen_edge_count = 0
        self.t_start = 0.0
        self.rounds = 0
        self.source = None

    # ------------------------------------------------------------------ events
    def _emit(self, kind, round_, nodes=None, edges=None, **info):
        ev = TraceEvent(round=round_, kind=kind, nodes=nodes or [], edges=edges or [], info=info)
        self.events.append(ev.to_json())
        if self._emit_cb:
            self._emit_cb(ev)

    def _pstats(self) -> dict:
        s = getattr(self.provider, "stats", {})
        return {"bytes_billed": s.get("bytes_billed", 0), "queries": s.get("queries", 0),
                "cache_hits": s.get("cache_hits", 0)}

    # ------------------------------------------------------------------ fetching and filtering
    def _fetch(self, nodes, t1: int):
        """Always fetch from the start of the incident window: the engine, not the provider, decides what is
        time-consistent (outflows after arrival, inflows before it), so the time-respecting switch is real and
        upstream funders can be seen. Cost is unchanged because BigQuery bills by window partition, not by node."""
        fr = self.provider.fetch({n: self.t_window0 for n in nodes}, t1)
        self.degree.update(fr.degree)
        self.seen_edge_count += len(fr.edges)
        return fr

    def _split(self, node, edges, arr):
        """Forward (outflow after arrival) and backward (inflow before arrival) edges of `node`."""
        fwd, back = [], []
        for e in edges:
            if e.src == node and e.dst != node:
                if (not self.p.time_respecting) or e.ts >= arr:
                    fwd.append(e)
            elif e.dst == node and e.src != node:
                # strictly before arrival: the edge the funds arrived on must not be walked backwards (ping-pong)
                if (not self.p.time_respecting) or e.ts < arr:
                    back.append(e)
        return fwd, back

    # ------------------------------------------------------------------ terminals
    def _label_terminal(self, node):
        """Labeled services stop the trace without needing to fetch their (huge) neighbourhood."""
        l = self.labels.get(node)
        if l and l.kind in ("exchange", "mixer", "sanctioned", "dex"):
            return {"kind": l.kind, "name": l.name, "reason": f"labeled {l.kind} ({l.source})"}
        return None

    def _inferred_terminal(self, node, fwd, arr):
        """Deposit-address sweep rule and unknown-hub guard. `fwd` = outflow edges of an expanded unlabeled node."""
        deg = self.degree.get((node, "out"), 0) + self.degree.get((node, "in"), 0)
        if deg > self.p.hub_degree:
            return {"kind": "service_hub", "name": "Unlabeled high-activity service", "reason":
                    f"{deg:,} transfers in the window; treated as a service, trace stops (manual review)"}
        if node == self.source or not fwd:
            return None
        recent = [e for e in fwd if e.ts - arr <= SWEEP_WINDOW_S]
        tot = sum(e.eth for e in recent)
        if tot <= 0 or len({e.dst for e in recent}) > SWEEP_MAX_RECIPIENTS:
            return None
        to_ex = defaultdict(float)
        for e in recent:
            l = self.labels.get(e.dst)
            if l and l.kind == "exchange":
                to_ex[l.name] += e.eth
        if not to_ex:
            return None
        name, amt = max(to_ex.items(), key=lambda kv: kv[1])
        if sum(to_ex.values()) / tot >= SWEEP_SHARE:
            return {"kind": "exchange_deposit", "name": name, "reason":
                    f"sweep rule: forwards {100 * sum(to_ex.values()) / tot:.0f}% of its outflow to {name} within 48 h"}
        return None

    def _set_terminal(self, node, info, round_):
        info = dict(info, round=round_)
        self.terminal[node] = info
        self._emit("absorb", round_, nodes=[node], kind_of=info["kind"], name=info["name"], reason=info["reason"])

    # ------------------------------------------------------------------ edge bookkeeping
    def _keep(self, e: Edge, role: str, share: float):
        k = (e.tx, e.src, e.dst, e.ts, e.eth)
        cur = self.edges.get(k)
        if cur is None:
            self.edges[k] = {"edge": e, "role": role, "share": share}
        elif role == "fwd":
            cur["role"], cur["share"] = "fwd", max(cur["share"], share)
        return k

    # ------------------------------------------------------------------ main entry
    def run(self, source: str, t0: int, t1: int):
        self.source, self.t_start, self.t_window0 = source.lower(), time.time(), t0
        self.arrival[self.source], self.depth[self.source] = t0, 0
        self.share[self.source] = 1.0
        self._emit("start", 0, nodes=[self.source], source=self.source, engine=self.name, t0=t0, t1=t1,
                   label=(self.labels.get(self.source).to_json() if self.labels.get(self.source) else None))
        self._search(self.source, t0, t1)
        res = self._result(t0, t1)
        self._emit("done", self.rounds, nodes=[], summary=res["summary"])
        return res

    def _search(self, source, t0, t1):  # pragma: no cover - implemented by engines
        raise NotImplementedError

    # ------------------------------------------------------------------ evidence paths
    def _best_paths(self, targets):
        """Max-share time-respecting path from the source to each target (DP over edges in time order)."""
        fwd = [(v["edge"]) for v in self.edges.values() if v["role"] == "fwd"]
        fwd.sort(key=lambda e: e.ts)
        best = {self.source: (1.0, None, self.arrival[self.source])}
        for e in fwd:
            b = best.get(e.src)
            if b is None or e.ts < b[2]:
                continue
            tot = self.out_total.get(e.src) or e.eth
            sc = b[0] * min(1.0, e.eth / tot)
            cur = best.get(e.dst)
            if cur is None or sc > cur[0]:
                best[e.dst] = (sc, e, e.ts)
        paths = {}
        for t in targets:
            if t not in best:
                continue
            path, node, guard = [], t, 0
            while node != self.source and guard < 64:
                step = best[node][1]
                if step is None:
                    break
                path.append(step)
                node, guard = step.src, guard + 1
            paths[t] = list(reversed(path))
        return paths

    # ------------------------------------------------------------------ result
    def _reachable(self):
        adj = defaultdict(list)
        for v in self.edges.values():
            if v["role"] == "fwd":
                adj[v["edge"].src].append(v["edge"].dst)
        seen, dq = {self.source}, deque([self.source])
        while dq:
            u = dq.popleft()
            for w in adj[u]:
                if w not in seen:
                    seen.add(w)
                    dq.append(w)
        return seen

    def _result(self, t0, t1):
        from cryptotrace.typology import tag_nodes

        reach = self._reachable()
        src_out = self.out_total.get(self.source, 0.0)
        # terminals reached downstream of the source
        dest = [n for n in self.terminal if n in reach and n != self.source]
        paths = self._best_paths(dest)
        terminals = []
        for n in dest:
            info = self.terminal[n]
            terminals.append({
                "node": n, "kind": info["kind"], "name": info["name"], "reason": info["reason"],
                "share": round(self.share.get(n, 0.0), 6), "eth_est": round(self.share.get(n, 0.0) * src_out, 3),
                "depth": self.depth.get(n), "first_ts": self.arrival.get(n),
                "confidence": {"exchange": "high", "mixer": "high", "sanctioned": "high", "dex": "medium",
                               "exchange_deposit": "medium", "service_hub": "low"}.get(info["kind"], "low"),
                "path": [x.to_json() for x in paths.get(n, [])],
            })
        terminals.sort(key=lambda t: (-t["share"], t["depth"] or 99))
        kept = {k: v for k, v in self.edges.items() if v["role"] == "back" and v["share"] >= 0.05
                or v["role"] == "fwd" and (v["share"] >= VIZ_MIN_SHARE or v["edge"].dst in self.terminal)}
        node_ids = {self.source} | {v["edge"].src for v in kept.values()} | {v["edge"].dst for v in kept.values()}
        edge_list = [dict(v["edge"].to_json(), role=v["role"], share=round(v["share"], 6)) for v in kept.values()]
        tags = tag_nodes([v["edge"] for v in self.edges.values() if v["role"] == "fwd"], self.arrival, self.source)
        nodes = []
        for n in node_ids:
            lab = self.labels.get(n)
            role = ("source" if n == self.source else "terminal" if n in self.terminal else
                    "intermediate" if n in reach else "upstream")
            nodes.append({"id": n, "role": role, "label": lab.to_json() if lab else None,
                          "terminal": self.terminal.get(n), "depth": self.depth.get(n),
                          "rank": round(self.rank.get(n, 0.0), 6), "share": round(self.share.get(n, 0.0), 6),
                          "first_ts": self.arrival.get(n), "tags": tags.get(n, []),
                          "deg_in": self.degree.get((n, "in")), "deg_out": self.degree.get((n, "out"))})
        secs = time.time() - self.t_start
        stats = {"rounds": self.rounds, "nodes_in_graph": len(node_ids), "edges_considered": self.seen_edge_count,
                 "edges_drawn": len(edge_list), "queries": getattr(self.provider, "stats", {}).get("queries", 0),
                 "bytes_billed": getattr(self.provider, "stats", {}).get("bytes_billed", 0),
                 "cache_hits": getattr(self.provider, "stats", {}).get("cache_hits", 0), "seconds": round(secs, 2),
                 "max_depth": max([self.depth.get(n, 0) or 0 for n in reach] or [0])}
        ex = [t for t in terminals if t["kind"] in ("exchange", "exchange_deposit")]
        summary = {"engine": self.name, "n_terminals": len(terminals), "n_exchange_terminals": len(ex),
                   "nearest_exchange": (min(ex, key=lambda t: (t["depth"] or 99, -t["share"]))["name"] if ex else None),
                   "top_exchange_by_share": (ex[0]["name"] if ex else None), "source_out_eth": round(src_out, 3)}
        return {"engine": self.name, "engine_label": self.label, "source": self.source, "t0": t0, "t1": t1,
                "params": self.p.to_json(), "nodes": nodes, "edges": edge_list, "terminals": terminals,
                "stats": stats, "summary": summary, "warnings": self.warnings, "events": self.events}
