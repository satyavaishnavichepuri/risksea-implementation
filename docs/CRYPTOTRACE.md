# CryptoTrace — crypto fraud attribution prototype

Given a victim-reported wallet, follow the funds forward, find the first service that received them (exchange, exchange
deposit address, mixer, DEX, unlabeled hub) and hand over a path of real transactions as evidence. Built on ideas from
*Blockchain Transaction Data Analytics* (Wu, Lin, Zheng), mainly Chapter 8 (TRacer), Chapter 7 (risk patterns) and Chapter 1
(deposit-address attribution).

## Validated results (public Ethereum data, cached in `results/cryptotrace/`)

| Case (book Ch. 8) | What the tracer found | Matches the book? |
|---|---|---|
| Cryptopia hack, May 2019 | 99.98% of the 30.8K ETH entered one address in 500–1000 ETH batches in 6 search rounds. That address is the EtherDelta DEX contract (label curated, **unverified on-chain**). | EtherDelta: yes. Yobit and OKEx: **not reached**. They are downstream of the contract through *internal* transfers, which this MVP does not read. 1 of 3 expected destinations. |
| KuCoin hack, Sept 2020 | 99.8% (≈11.5K ETH) went to the Tornado Cash 100 ETH pool in 2 hops, with a 2-transfer evidence path. Tracing stops and says why. | Mixer destination: yes. The book reports ≈13.8K ETH; our window and 0.01 ETH dust filter give 11.5K. |

| Phishing-labeled wallet, mid-2018 (**no published answer**; picked by us) | 90.9% (≈2,227 ETH) reached **29 distinct deposit addresses** that each sweep into the labeled exchange wallet *ShapeShift 3* (inferred, medium confidence), plus 5.2% in 2 unlabeled service hubs; 5 rounds, 75 accounts. | No ground truth. Selected because its trace reaches exchange deposits (selection bias, disclosed in the app). Treat as an investigative lead. |

On the two book cases all three strategies (TTR-lite, Haircut, blind BFS) reach the same destination; they differ in effort
(KuCoin: 3 accounts for TTR/Haircut, 12 for BFS). On the phishing case they **separate**, as the book's benchmark predicts: TTR-lite
and Haircut each reach 31 destinations, blind depth-2 BFS reaches 0. The book's 20-case benchmark files are not available to us.

Cost: a dry run of one hop query is about 1.2 GiB. First full fetch: 9.5 GiB (Cryptopia), 3.9 GiB (KuCoin) and 19.9 GiB (phishing case), roughly $0.06, $0.02 and
$0.12 at an assumed $6.25/TiB list price (check current pricing; the first 1 TiB per month is free). Re-runs and parameter changes
are served from the SQLite cache and are free.

## Run it

Requires the project's `.venv` (Python 3.12) and Node 18+. All commands from the repository root.

**Demo mode (one process; the UI is served by FastAPI)**
```powershell
cd frontend; npm install; npm run build; cd ..
.\.venv\Scripts\python.exe -m uvicorn cryptotrace.api:app --app-dir src --port 8000
```
Open http://127.0.0.1:8000

**Development mode (hot reload)**
```powershell
.\.venv\Scripts\python.exe -m uvicorn cryptotrace.api:app --app-dir src --port 8000
cd frontend; npm run dev
```
Open http://localhost:5173 (the dev server proxies `/api` to port 8000).

**Live tracing of any wallet (billed, capped)** needs BigQuery credentials (`gcloud auth application-default login`) and a project:
```powershell
$env:CRYPTOTRACE_BQ_PROJECT = "your-gcp-project-id"
.\.venv\Scripts\python.exe -m uvicorn cryptotrace.api:app --app-dir src --port 8000
```
Each live trace has a 30 GiB budget and every query a 40 GiB cap. Windows are limited to 120 days.

**Regenerate the cached benchmark results**
```powershell
.\.venv\Scripts\python.exe scripts\ct_run_cases.py your-gcp-project-id
```

**Tests:** `.\.venv\Scripts\python.exe -m pytest -q` (78 tests; none cover the React app, which was checked by hand in a browser).

## Architecture

`intake → chain adapter → edge cache → tracing engine → attribution → typology → case file → report / dashboard`, with a label
store feeding attribution and a benchmark harness on the side. The UI's *System* page draws this from `GET /api/architecture`,
including which modules are live, partial or planned.

| Module | File | Status |
|---|---|---|
| Edge model, params, events | `src/cryptotrace/models.py` | live |
| Providers (BigQuery + SQLite cache, in-memory) | `src/cryptotrace/providers/` | live (ETH external transfers only) |
| Label store with provenance | `src/cryptotrace/labels.py` | live |
| Engines: TTR-lite, Haircut, BFS | `src/cryptotrace/engines/` | live |
| Attribution (labels, deposit-sweep rule, hub guard) | `engines/common.py` | live |
| Typology tags | `src/cryptotrace/typology.py` | live |
| API (REST + server-sent events) | `src/cryptotrace/api.py` | live |
| React app | `frontend/` | live |
| DEX pass-through, ERC-20, other chains, risk model, alerts | — | planned |

### How the tracer works
Each search round expands every account with enough unexplained "residual" (highest first, capped at 300). It fetches the account's
transfers (largest 200 per direction), keeps outflows **after** the funds arrived, splits the residual by amount (β forward, 1−β
backward), and stops at labeled exchanges, mixers, sanctioned addresses and DEX contracts. Unlabeled accounts that forward ≥80% of
their outflow to a labeled exchange wallet within 48 h are classed as *exchange deposit addresses* (medium confidence); unlabeled
accounts with more than 3,000 transfers are treated as service hubs and flagged for manual review. Evidence paths are the
max-share, time-ordered chain of real transactions from the source to each destination.

## Demo script (about 5 minutes)

1. **Overview**: the problem in one sentence; the headline numbers (29 deposit addresses into one exchange, 99.8% into Tornado Cash) and the cost.
2. **System**: press *Play a trace through the system*; narrate each module lighting up. Point out dashed planned modules.
3. **Trace Lab, phishing case (opens by default)**: watch the graph grow; at the end the top finding auto-highlights. Expand it to show the 29 addresses to ask the exchange to freeze and one evidence path. Say it is inferred and has no ground truth. Switch to Blind BFS: it finds nothing. Shortcuts: Space, arrows, F, R.
3b. **Trace Lab, KuCoin**: watch the graph grow round by round. Open *Inside the engine*. Click the mixer, read the evidence path, open a hash on Etherscan.
4. **Trace Lab, Cryptopia**: the trace ends at EtherDelta. Say plainly why: the exit is an internal transfer, the first roadmap item.
5. Change **β or ε** and press *Run trace* (free, cached) to show the algorithm reacting.
6. **Compare**: strategies agree on the book cases and separate on the phishing case; show the book's table for the wider picture.
7. **Gaps**: the plain-language research gaps. **Report**: print the investigator report.

## Honest limits

- Ethereum **external ETH transfers only**: no internal transfers, so no tracing through DEX or mixer contracts; no ERC-20 or stablecoins yet.
- Public BigQuery data has an **update lag**: near-real-time at best. A watchlist/alert feature needs a live feed.
- Only each address's **200 largest transfers** per direction are considered; dust below 0.01 ETH is ignored.
- Labels are public and incomplete (372 exchanges). Exchange deposit addresses are **inferred**, not confirmed. The EtherDelta label is curated and unverified.
- The Tornado Cash pool addresses are curated and were verified on-chain (each receives one fixed denomination).
- Temporal reasoning uses an earliest-arrival approximation, not per-timestamp residuals as in the book.
- Validated on **two book cases** (one only partly reproduced) plus one real example with no published answer. This is a smoke test, not a replication of the book's benchmark.
- The phishing example was selected from public labels because its trace reaches exchange deposits, so it demonstrates the rule; it does not measure accuracy.
- SAHYOG / NCRP integration is **not built**: no specification was available, so it is listed as a requirement to clarify.
