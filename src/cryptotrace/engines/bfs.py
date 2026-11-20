"""Blind breadth-first search (baseline from the book): follow every outflow of every discovered node, to a depth limit.
It ignores timing and amounts, so the output explodes; the book caps it at depth 2 for that reason. Shares are split
uniformly (there is no value weighting) and exist only so the comparison table can be filled.
"""
from __future__ import annotations

from collections import defaultdict

from cryptotrace.engines.common import Tracer


class BFS(Tracer):
    name = "bfs"
    label = "BFS (blind, depth-limited)"

    def _search(self, source, t0, t1):
        p = self.p
        level = [source]
        seen = {source}
        for rnd in range(1, p.bfs_depth + 1):
            self.rounds = rnd
            level = [n for n in level if n not in self.terminal]
            if not level:
                break
            fr = self._fetch(level, t1)
            by_node = defaultdict(list)
            xs = set(level)
            for e in fr.edges:
                if e.src in xs and e.dst != e.src:
                    by_node[e.src].append(e)
            nxt, drawn, absorbed = [], [], []
            for n in level:
                outs = by_node.get(n, [])
                self.out_total.setdefault(n, sum(e.eth for e in outs))
                for e in outs:
                    sh = self.share[n] / len(outs)
                    self.share[e.dst] += sh
                    if e.dst not in self.arrival or e.ts < self.arrival[e.dst]:
                        self.arrival[e.dst] = e.ts
                    self.depth[e.dst] = min(self.depth.get(e.dst, 10 ** 6), self.depth[n] + 1)
                    self._keep(e, "fwd", sh)
                    lt = self._label_terminal(e.dst)
                    drawn.append(dict(e.to_json(), role="fwd", share=round(sh, 6)))
                    if lt and e.dst not in self.terminal:
                        self._set_terminal(e.dst, lt, rnd)
                        absorbed.append(e.dst)
                    if e.dst not in seen:
                        seen.add(e.dst)
                        nxt.append(e.dst)
            self._emit("expand", rnd, nodes=level, edges=drawn[:80], frontier=len(level), terminals=len(absorbed),
                       residual=0, weights={}, **self._pstats())
            level = nxt
