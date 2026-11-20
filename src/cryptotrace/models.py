"""Shared data structures for the tracing MVP.

An Edge is one on-chain ETH transfer (directed, timed, valued). Everything the engines do is expressed in
terms of Edges, so a different chain only needs a different provider that yields Edges.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    eth: float          # value in ETH
    ts: int             # unix seconds
    blk: int
    tx: Optional[str] = None

    def to_json(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Label:
    kind: str           # exchange | mixer | sanctioned | bad | service
    name: str
    source: str

    def to_json(self) -> dict:
        return asdict(self)


@dataclass
class FetchResult:
    edges: list
    degree: dict                      # (node, 'in'|'out') -> total degree in window before the per-node cap
    queries: int = 0
    bytes_billed: int = 0
    cache_hits: int = 0


@dataclass
class TraceParams:
    alpha: float = 0.15               # teleport / stay probability (kept as node rank)
    beta: float = 0.8                 # forward vs backward attention (tracing tendency)
    epsilon: float = 1e-3             # residual threshold: below this a node is not expanded
    max_rounds: int = 8               # max expansion rounds (hops) for the synchronous search
    min_eth: float = 0.01             # ignore dust below this
    hub_degree: int = 3000            # unlabeled nodes with more edges than this are treated as service hubs
    time_respecting: bool = True      # only follow outflows that happen after the funds arrived
    top_k: int = 200                  # per-node neighbour cap (largest transfers first)
    bfs_depth: int = 2                # depth limit of the blind BFS baseline (the book caps it at 2)
    max_frontier: int = 300           # at most this many nodes expand per round (highest residual first)

    def to_json(self) -> dict:
        return asdict(self)


@dataclass
class TraceEvent:
    """One animation frame: what the engine just did. Streamed to the UI as it happens."""
    round: int
    kind: str                         # start | expand | absorb | stop | done
    nodes: list = field(default_factory=list)   # node ids touched
    edges: list = field(default_factory=list)   # Edge json added this step
    info: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return {"round": self.round, "kind": self.kind, "nodes": self.nodes, "edges": self.edges, "info": self.info}
