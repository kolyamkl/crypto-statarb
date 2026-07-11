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
- **Binance USDT-M perps as primary data source, Hyperliquid as optional
  secondary.** Rationale: Binance perp history for majors goes back to 2019–2020
  and covers multiple regimes (2021 bull, 2022 crash, 2023 chop, 2024 bull);
  Hyperliquid mainnet history only starts ~2023 and its public API caps candle
  lookback. Funding on Binance is 8-hourly (1-hourly on Hyperliquid) — the
  backtest must use the per-exchange convention it trades on.
  *Auto-selected recommended default (Kolya AFK at decision time) — pending his
  review, together with: 1h bars and 2021-01-01 history start. All three are
  config-driven and cheap to change; ingestion is idempotent and resumable.*
- **Still-forming bar is dropped at ingestion**: the newest candle's close is
  mutable until the bar closes; letting it into the dataset would be a subtle
  look-ahead. We only store bars whose close time precedes the run's start.
- **`ON CONFLICT DO NOTHING` upserts**: raw historical data never changes, so
  idempotent re-runs are safe and duplicates are structurally impossible
  (composite PKs on every table).
- **`data_provenance.md` is auto-generated from the database** (not hand-written)
  so the provenance doc can never drift from what's actually stored.

## 2026-07-11 — Data quirks found during M1 verification

- **Binance funding cadence is NOT a fixed 8 hours.** SOLUSDT has ~101 funding
  events at ~2h spacing during November 2022 (the FTX collapse — SOL was the
  FTX/Alameda coin and Binance raised its funding frequency during the stress).
  Consequence for M4: the backtest must charge funding by joining the ACTUAL
  stored funding events, never by assuming an 8h grid — otherwise costs are
  mis-modelled precisely in the highest-stress regime. Evidence kept in the
  `funding` table (query interval distribution per symbol).
- **Zero interior gaps** in 646,101 hourly bars across 14 symbols — Binance perp
  kline history for this universe is continuous over 2021→2026. First-bar dates
  for ARBUSDT (2023-03) and OPUSDT (2022-06) reflect their listings and are
  recorded in `symbols.onboard_date`, not backfilled.
