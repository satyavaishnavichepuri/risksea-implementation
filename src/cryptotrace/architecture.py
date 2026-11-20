"""The system architecture as data, so the UI draws exactly what exists (and what does not yet).

status: live     implemented and exercised by the benchmark cases
        partial  implemented in part (see `note`)
        planned  designed, not built; listed so the roadmap is honest
`ps` lists the problem-statement requirements a module serves; `book` the chapter that inspired it.
"""
from __future__ import annotations

MODULES = [
    # ------------------------------------------------------------------ intake
    {"id": "intake", "group": "intake", "label": "Complaint intake", "status": "partial",
     "desc": "Takes a victim-reported wallet and a time window and opens a case.",
     "details": ["API accepts an address, window and engine today", "CSV / JSON batch adapter for NCRP-style exports: planned",
                 "SAHYOG / NCRP integration: specification unknown, treated as a requirement to clarify"],
     "ps": ["ingest reported wallet addresses", "integration with SAHYOG and NCRP"], "book": "Ch.8 (problem definition)"},
    # ------------------------------------------------------------------ data
    {"id": "adapter", "group": "data", "label": "Chain adapter", "status": "partial",
     "desc": "Turns a blockchain into a stream of timed, valued transfers (edges).",
     "details": ["Ethereum external ETH transfers via BigQuery: live", "Internal transfers (needed to pass through DEX contracts): planned",
                 "ERC-20 / USDT, Bitcoin, Tron, BNB Chain adapters: planned, same Edge interface"],
     "ps": ["support multiple blockchain ecosystems", "scalable blockchain indexing"], "book": "Ch.1, Ch.8"},
    {"id": "cache", "group": "data", "label": "Edge cache", "status": "live",
     "desc": "SQLite cache of every address neighbourhood fetched; re-runs and what-if parameter changes cost nothing.",
     "details": ["Per-hop BigQuery queries return only the largest transfers per address (top 200)",
                 "Hard per-query and per-trace byte caps"], "ps": ["real-time tracing capability"], "book": "Ch.8 (cost independent of graph size)"},
    {"id": "labels", "group": "data", "label": "Label store", "status": "live",
     "desc": "Who is an exchange, mixer, DEX, sanctioned or known-bad address, with provenance for every label.",
     "details": ["372 exchange, 5,594 known-bad, 123 OFAC, 4 mixer pools, 1 DEX (curated)",
                 "Exchange deposit addresses are mostly unlabeled anywhere: inferred by the sweep rule"],
     "ps": ["clustering of exchange wallets", "identify exchanges or VASPs"], "book": "Ch.1 (entity identification)"},
    # ------------------------------------------------------------------ engines
    {"id": "tracing", "group": "engine", "label": "Tracing engine", "status": "live",
     "desc": "Follows the money forward from the reported wallet: ranked, time-respecting, value-weighted search.",
     "details": ["TTR-lite: tracing tendency, weighted pollution, temporal reasoning", "Baselines: blind BFS, Haircut taint",
                 "Token swaps / DeFi redirection: planned"], "ps": ["automatically perform blockchain tracing", "detect fund movement patterns"],
     "book": "Ch.8 (TRacer)"},
    {"id": "attribution", "group": "engine", "label": "Attribution engine", "status": "live",
     "desc": "Decides where tracing stops and who the receiving entity is.",
     "details": ["Labeled exchange, mixer, DEX, sanctioned: stop immediately", "Deposit-sweep rule: forwards >=80% of outflow to a labeled exchange within 48 h",
                 "Unlabeled high-activity hub: stop and flag for manual review"],
     "ps": ["identify the nearest exchange or VASP receiving direct deposits"], "book": "Ch.1 (deposit-address reuse), Ch.5"},
    {"id": "typology", "group": "engine", "label": "Typology engine", "status": "live",
     "desc": "Explainable laundering-pattern tags on the traced subgraph.",
     "details": ["zero-out middle account, fan-out, fan-in, peeling chain, fast hop"], "ps": ["detection of intermediary laundering wallets", "automated pattern recognition for fraud typologies"],
     "book": "Ch.7 (patterns)"},
    {"id": "risk", "group": "engine", "label": "Risk model", "status": "planned",
     "desc": "ML wallet risk score. Our RiskSEA reproduction is the baseline; RiskProp-style unsupervised rating is the next step.",
     "details": ["RiskSEA reproduction exists offline (Ethereum 2018 data), not wired in", "Heterophily-aware models (Ch.5) are the improvement path"],
     "ps": ["risk categorization of wallets", "AI/ML-assisted risk detection"], "book": "Ch.5, Ch.7"},
    {"id": "internal", "group": "engine", "label": "DEX pass-through", "status": "planned",
     "desc": "Follow funds through a DEX contract by matching deposits with withdrawals (internal transfers).",
     "details": ["Why the Cryptopia trace stops at EtherDelta today", "Needs the BigQuery traces table"],
     "ps": ["identification of cross-chain / DeFi fund movement"], "book": "Ch.8 (Swap pattern)"},
    {"id": "cross", "group": "engine", "label": "Cross-chain", "status": "planned",
     "desc": "Follow funds across bridges and between chains.", "details": ["Not covered by the book chapters read; needs bridge event matching"],
     "ps": ["identification of cross-chain fund movement"], "book": "n/a"},
    # ------------------------------------------------------------------ output
    {"id": "casefile", "group": "output", "label": "Case file", "status": "live",
     "desc": "One JSON per trace: nodes, edges, terminals, evidence paths with transaction hashes, tags, warnings, event log.",
     "details": ["Every claim is backed by a path of real transactions", "Stops and limits are stated in the file"],
     "ps": ["generate actionable intelligence for investigators", "standardized investigation reports"], "book": "Ch.8"},
    {"id": "report", "group": "output", "label": "Investigator report", "status": "partial",
     "desc": "Printable summary with evidence table.", "details": ["Print view in the UI: live", "PDF / standard-format export: planned"],
     "ps": ["generation of standardized investigation reports"], "book": "Ch.8"},
    {"id": "dashboard", "group": "output", "label": "Dashboard & API", "status": "live",
     "desc": "FastAPI backend with live event streaming; React app with animated tracing, comparison and roadmap.",
     "details": ["Server-sent events stream each search round to the UI"], "ps": ["analytics dashboards for law enforcement", "API integrations", "fund-flow visualization"], "book": ""},
    {"id": "alerts", "group": "output", "label": "Alerts / watchlist", "status": "planned",
     "desc": "Watch reported wallets and trigger a trace when they move.", "details": ["Needs a live feed (node, RPC or API key)", "Replay demo is possible with the cached cases"],
     "ps": ["automated alert generation", "real-time tracing capability"], "book": "Ch.6 (streaming)"},
    # ------------------------------------------------------------------ evaluation
    {"id": "bench", "group": "eval", "label": "Benchmark", "status": "live",
     "desc": "Documented cases with published answers; compares search strategies on recall, nodes to audit, depth, runtime, cost.",
     "details": ["Cryptopia 2019 and KuCoin 2020 from the book's Chapter 8"], "ps": ["reduce response time in cyber fraud investigations"], "book": "Ch.8 (evaluation)"},
]

FLOWS = [
    ("intake", "adapter", "wallet + window"), ("adapter", "cache", "transfers"), ("cache", "tracing", "edges"),
    ("labels", "attribution", "who is who"), ("tracing", "attribution", "reached nodes"), ("attribution", "typology", "subgraph"),
    ("typology", "casefile", "tags"), ("attribution", "casefile", "terminals + paths"), ("casefile", "report", ""),
    ("casefile", "dashboard", "events + results"), ("casefile", "bench", "metrics"), ("risk", "casefile", ""), ("internal", "tracing", ""),
    ("cross", "adapter", ""), ("dashboard", "alerts", ""),
]

# the animation: which modules light up for each kind of engine event
STAGES = ["intake", "adapter", "cache", "tracing", "attribution", "typology", "casefile", "report"]


def architecture() -> dict:
    return {"modules": MODULES, "flows": [{"from": a, "to": b, "label": c} for a, b, c in FLOWS], "stages": STAGES}
