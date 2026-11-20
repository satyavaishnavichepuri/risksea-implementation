"""TTR-lite: ranked, time-respecting, value-weighted forward push (after TRacer / Transaction Tracing Rank, book Ch.8).

Each round expands every node whose residual exceeds epsilon (a synchronous version of the book's greedy pop, which
suits batched BigQuery fetches). Four ideas from the book are kept:
  tracing tendency   beta of the residual goes forward along outflows, (1-beta) backward along inflows
  weighted pollution edges share the residual in proportion to the amount transferred
  temporal reasoning funds can only follow outflows that happen after they arrived (earliest-arrival approximation)
  token redirection  not implemented in the MVP (ETH only), see docs
Two quantities travel together: `rank` (relevance, decays with distance, drives which nodes get expanded) and `share`
(estimated fraction of the source funds that reached a node, used for reporting).
"""
from __future__ import annotations

from collections import defaultdict

from cryptotrace.engines.common import VIZ_MIN_SHARE, Tracer


class TTR(Tracer):
    name = "ttr"
    label = "TTR-lite (ranked, time-respecting)"

    def _search(self, source, t0, t1):
        p = self.p
        r = defaultdict(float)
        pend = defaultdict(float)
        r[source], pend[source] = 1.0, 1.0
        upstream = set()
        for rnd in range(1, p.max_rounds + 1):
            self.rounds = rnd
            cand = [n for n, v in r.items() if v > p.epsilon]
            expand = []
            for n in cand:
                if n in self.terminal or n in upstream:
                    self.rank[n] += r[n]
                    r[n] = 0.0
                    continue
                expand.append(n)
            if not expand:
                break
            expand = sorted(expand, key=lambda n: -r[n])[: p.max_frontier]      # greedy: most relevant first
            weights = {n: round(r[n], 4) for n in expand[:12]}
            fr = self._fetch(expand, t1)
            by_node = defaultdict(list)
            xs = set(expand)
            for e in fr.edges:
                if e.src in xs:
                    by_node[e.src].append(e)
                if e.dst in xs:
                    by_node[e.dst].append(e)
            drawn, absorbed = [], []
            for n in expand:
                arr = self.arrival.get(n, t0)
                fwd, back = self._split(n, by_node.get(n, []), arr)
                self.out_total.setdefault(n, sum(e.eth for e in fwd))
                inferred = self._inferred_terminal(n, fwd, arr)
                if inferred:
                    self._set_terminal(n, inferred, rnd)
                    self.rank[n] += r[n]
                    r[n] = 0.0
                    absorbed.append(n)
                    continue
                rn, sn = r[n], pend[n]
                r[n], pend[n] = 0.0, 0.0
                self.rank[n] += p.alpha * rn
                f_tot = sum(e.eth for e in fwd)
                b_tot = sum(e.eth for e in back)
                if f_tot <= 0 and b_tot <= 0:
                    self.rank[n] += (1 - p.alpha) * rn
                    continue
                beta = 1.0 if b_tot <= 0 else (0.0 if f_tot <= 0 else p.beta)
                for e in fwd:
                    frac = e.eth / f_tot
                    r[e.dst] += (1 - p.alpha) * beta * rn * frac
                    sh = sn * frac
                    self.share[e.dst] += sh
                    pend[e.dst] += sh
                    if e.dst not in self.arrival or e.ts < self.arrival[e.dst]:
                        self.arrival[e.dst] = e.ts
                    self.depth[e.dst] = min(self.depth.get(e.dst, 10 ** 6), self.depth[n] + 1)
                    self._keep(e, "fwd", sh)
                    lt = self._label_terminal(e.dst)
                    if sh >= VIZ_MIN_SHARE or lt:
                        drawn.append(dict(e.to_json(), role="fwd", share=round(sh, 6)))
                    if lt and e.dst not in self.terminal:
                        self._set_terminal(e.dst, lt, rnd)
                        absorbed.append(e.dst)
                for e in back:
                    frac = e.eth / b_tot
                    r[e.src] += (1 - p.alpha) * (1 - beta) * rn * frac
                    if e.src not in self.depth:
                        upstream.add(e.src)
                    self._keep(e, "back", frac)
                    if frac >= 0.05:
                        drawn.append(dict(e.to_json(), role="back", share=round(frac, 6)))
            self._emit("expand", rnd, nodes=expand, edges=drawn[:80], frontier=len(expand), terminals=len(absorbed),
                       residual=round(sum(r.values()), 5), weights=weights, **self._pstats())
        if any(v > p.epsilon for v in r.values()):
            self.warnings.append(f"search stopped at the {p.max_rounds}-hop limit with unexplored flows remaining")
