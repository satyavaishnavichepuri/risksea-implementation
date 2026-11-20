"""Haircut taint tracking (baseline from the book): each transfer carries the sender's tainted share to recipients
in proportion to value; stop when the remaining taint is below theta. Forward only, no ranking, no backward pass.
"""
from __future__ import annotations

from collections import defaultdict

from cryptotrace.engines.common import VIZ_MIN_SHARE, Tracer


class Haircut(Tracer):
    name = "haircut"
    label = "Haircut taint (forward, value-proportional)"

    def _search(self, source, t0, t1):
        p, theta = self.p, self.p.epsilon
        pend = defaultdict(float)
        pend[source] = 1.0
        for rnd in range(1, p.max_rounds + 1):
            self.rounds = rnd
            expand = [n for n, v in pend.items() if v > theta and n not in self.terminal]
            if not expand:
                break
            expand = sorted(expand, key=lambda n: -pend[n])[: p.max_frontier]
            weights = {n: round(pend[n], 4) for n in expand[:12]}
            fr = self._fetch(expand, t1)
            by_node = defaultdict(list)
            xs = set(expand)
            for e in fr.edges:
                if e.src in xs:
                    by_node[e.src].append(e)
            drawn, absorbed = [], []
            for n in expand:
                arr = self.arrival.get(n, t0)
                fwd, _ = self._split(n, by_node.get(n, []), arr)
                self.out_total.setdefault(n, sum(e.eth for e in fwd))
                inferred = self._inferred_terminal(n, fwd, arr)
                if inferred:
                    self._set_terminal(n, inferred, rnd)
                    pend[n] = 0.0
                    absorbed.append(n)
                    continue
                sn, pend[n] = pend[n], 0.0
                f_tot = sum(e.eth for e in fwd)
                for e in fwd:
                    sh = sn * e.eth / f_tot
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
            self._emit("expand", rnd, nodes=expand, edges=drawn[:80], frontier=len(expand), terminals=len(absorbed),
                       residual=round(sum(pend.values()), 5), weights=weights, **self._pstats())
