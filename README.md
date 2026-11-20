# Blockchain analytics: RiskSEA reproduction and CryptoTrace

This repository holds two connected pieces of work.

## 1. RiskSEA reproduction (`src/risksea/`, `scripts/`, `report/`)
An independent reproduction of *RiskSEA: A Scalable Graph Embedding for Detecting On-chain Fraudulent Activities on the Ethereum
Blockchain* (arXiv 2410.02160) on public data, with a comparative study of the paper against the reproduction.
- Final report (LaTeX, PDF): [`report/RiskSEA_Reproduction_Report.pdf`](report/RiskSEA_Reproduction_Report.pdf)
- Every deviation from the paper: [`docs/decisions.md`](docs/decisions.md)

## 2. CryptoTrace (`src/cryptotrace/`, `frontend/`)
A prototype that traces a victim-reported wallet to the exchange, mixer or DEX that received the funds, with an animated React
interface and a FastAPI backend. It starts from the reproduction's finding that risk *scoring* is not the same job as fund *tracing*.
- Overview, run commands, validated results, demo script and limits: [`docs/CRYPTOTRACE.md`](docs/CRYPTOTRACE.md)

## Quick start
```powershell
cd frontend; npm install; npm run build; cd ..
.\.venv\Scripts\python.exe -m uvicorn cryptotrace.api:app --app-dir src --port 8000
```
Then open http://127.0.0.1:8000. Tests: `.\.venv\Scripts\python.exe -m pytest -q`.

Raw data, graphs, embeddings and the BigQuery cache live under `data/` and are not tracked (large, regenerable, and some label
sources have unclear terms of use).
