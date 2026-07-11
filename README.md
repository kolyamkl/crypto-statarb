# crypto-statarb

A statistical-arbitrage research study on crypto pairs: cointegration-based pair
selection, time-varying hedge ratios via Kalman filtering, z-score spread trading,
backtesting with realistic costs (fees, slippage, perp funding), and walk-forward
out-of-sample validation.

> **Status: work in progress — Milestone M1 (data layer).**
> This README will become the full research report (problem → data → method →
> results → limitations → next steps) at Milestone M8.

## Reproduce

```bash
cp .env.example .env
docker compose up -d db
uv sync
uv run python -m src.ingest.run   # pull raw OHLCV + funding into Postgres
```

Data sources, granularity, and known gaps are documented in `data_provenance.md`.
Methodology decisions and trade-offs are logged in `DECISIONS.md`.
