# DECISIONS.md — methodology & engineering choices

Running log of every non-obvious choice, with the reasoning. Feeds the README's
limitations section at M8. Newest entries at the bottom.

## 2026-07-11 — Repo bootstrap (M1)

- **`uv` over `poetry`**: single fast binary, standards-based `pyproject.toml`,
  lockfile committed. No functional difference for this project; picked for speed.
- **Raw SQL via `psycopg` (no ORM)**: the data layer should be transparent and
  interview-explainable; an ORM hides the exact queries and adds nothing for a
  research pipeline with ~4 tables.
- **Postgres host port 5433**: avoids colliding with other local Postgres
  instances (5432 in use by another project).
- **Hand-rolled ingestion (no ccxt)**: we hit only a handful of endpoints; a raw
  REST client keeps auth, rate limiting, and pagination fully visible, which is
  the point of the exercise. Trade-off: exchange-specific code.
- **PROPOSED (pending review): Binance USDT-M perps as primary data source,
  Hyperliquid as optional secondary.** Rationale: Binance perp history for majors
  goes back to 2019–2020 and covers multiple regimes (2021 bull, 2022 crash, 2023
  chop, 2024 bull); Hyperliquid mainnet history only starts ~2023 and its public
  API caps candle lookback. Funding on Binance is 8-hourly (1-hourly on
  Hyperliquid) — the backtest must use the per-exchange convention it trades on.
