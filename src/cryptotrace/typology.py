"""Rule-based laundering-pattern tags on a traced subgraph (explainable, no training data needed).

  zero_out    forwards >= 90% of what it received within 24 h (a pass-through "bridge" account; book Ch.7 pattern d)
  fan_out     splits funds to >= 5 different recipients within 24 h (layering / smurfing)
  fan_in      receives from >= 5 different senders (aggregation / collector)
  peel        keeps a small part and passes the rest on, repeatedly (peeling chain)
  fast_hop    first outflow within 1 h of the funds arriving
"""
from __future__ import annotations

from collections import defaultdict

DAY = 24 * 3600


def tag_nodes(fwd_edges, arrival: dict, source: str) -> dict:
    out, inn = defaultdict(list), defaultdict(list)
    for e in fwd_edges:
        out[e.src].append(e)
        inn[e.dst].append(e)
    tags: dict = defaultdict(list)
    for n in set(out) | set(inn):
        arr = arrival.get(n)
        recv = sum(e.eth for e in inn.get(n, []))
        sent_24 = [e for e in out.get(n, []) if arr is not None and e.ts - arr <= DAY]
        sent_total = sum(e.eth for e in sent_24)
        if n != source and recv > 0 and sent_total >= 0.9 * recv and sent_24:
            tags[n].append("zero_out")
        if len({e.dst for e in sent_24}) >= 5:
            tags[n].append("fan_out")
        if len({e.src for e in inn.get(n, [])}) >= 5:
            tags[n].append("fan_in")
        if arr is not None and out.get(n) and min(e.ts for e in out[n]) - arr <= 3600 and n != source:
            tags[n].append("fast_hop")
        if n != source and recv > 0 and out.get(n):
            big = max(out[n], key=lambda e: e.eth)
            rest = sent_total - big.eth if sent_24 else 0
            if 0 < rest <= 0.15 * recv and big.eth >= 0.7 * recv:
                tags[n].append("peel")
    return dict(tags)
