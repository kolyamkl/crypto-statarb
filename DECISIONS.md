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

## 2026-08-22 — M2 pair selection methodology

- **Train/test split at 2024-12-31** (config `validation.train_end`): 4y train,
  ~1.5y untouched test. Pair SELECTION is treated as tuning, so M2 sees training
  data only — picking pairs on the full sample would leak test-period info into
  the strategy (selection look-ahead). *Auto-selected default, pending Kolya's
  review; config-driven.*
- **Log prices for the hedge regression**: β in log space is a scale-free return
  ratio, comparable across pairs regardless of price level.
- **Engle–Granger via `statsmodels.coint`, both directions, screened on the
  WORSE p-value**: EG is not symmetric in which leg is regressed on which; a
  genuinely cointegrated pair passes both ways. `coint` uses MacKinnon critical
  values that account for the estimated hedge ratio — a plain ADF on OLS
  residuals would be too lenient. Johansen deferred (optional per spec); EG is
  the interview-explainable core.
- **Half-life gate [24, 720] hourly bars (1–30d)** from an AR(1) fit on the
  spread: <1d reverts too fast to capture after costs on hourly bars; >30d ties
  up capital and weakens the stat-arb premise. This is a tradeability prior,
  not a statistical test.
- **Multiple testing acknowledged, not corrected**: 91 tests at α=0.05 → ~4.5
  false positives expected. Rather than a Bonferroni-style correction (which
  would kill everything), the screen is treated as a candidate filter backed by
  an economic-plausibility check (reports/m2_pair_notes.md); the real arbiter
  is out-of-sample M5.
- **Kalman filter hand-rolled** (~20 lines) with Chan's single-knob
  parameterization (`delta=1e-5`), state seeded by OLS on a 720-bar burn-in;
  filtered (one-sided) estimates only — smoothing would leak the future.
  Causality is enforced by a unit test that mutates future observations and
  asserts earlier output is bit-identical. Burn-in bars are never tradeable.
- **Static OLS β in the ranked table, Kalman β as diagnostic**: the screen ranks
  on full-train statistics; the time-varying β becomes the trading hedge in M3+.
  The 30d rolling-OLS comparison plot shows why: rolling OLS whipsaws (even
  flips negative on AVAX/NEAR); the Kalman path is stable.

## 2026-08-22 — M2 result: 1 of 91 pairs passes

- **Finding:** hourly return correlation is high everywhere (0.44–0.85) but only
  AVAX/NEAR passes EG at 5% with a tradeable half-life (~28d). 4 pairs under
  α=0.05 is what chance alone predicts (~4.5) — only AVAX/NEAR (p=0.002) beats
  the multiple-testing bar comfortably, and it is also the pair with the
  cleanest economic story (same-generation alt-L1 substitutes).
- **Kept as evidence** in `pair_screen` (all 91 rows) and reports/. The thin
  pass rate goes in the final report's "what didn't work" section: long-window
  cointegration screening on crypto majors yields almost no tradeable pairs.
- **Open decision for M3** (Kolya to pick at review): trade AVAX/NEAR alone, or
  add the economically-sensible near-misses ADA/DOT + ADA/LTC under a
  documented, post-hoc relaxation of the half-life bound to ~70d. Re-screening
  on a shorter window was considered and rejected as data snooping; M5's
  walk-forward re-screens per window anyway.

## 2026-08-22 — M2 review outcome: 3-pair book approved

- Kolya approved the 3-pair book (AVAX/NEAR + ADA/DOT + ADA/LTC), i.e. option 1:
  the half-life bound is relaxed to ~70d for the two near-misses, disclosed as a
  post-hoc widening here and in config.yaml. Rationale: book diversification and
  the near-misses' economic plausibility outweigh the purity of a 1-pair book.

## 2026-08-22 — M3 signal construction

- **Traded spread = Kalman INNOVATION** (today's y minus yesterday's-state
  prediction from today's x), not the raw OLS spread. Using the state filtered
  AT t would absorb today's observation and shrink the very dislocation we want
  to trade; the lagged state is both causal and honest.
- **Consequence discovered on real data:** the innovation reverts in HOURS
  (avg hold 16–31h), not the 28–66 DAYS of the M2 raw-spread half-lives —
  the filter's adaptive state absorbs the slow drift, so the strategy trades
  fast dislocations around a moving equilibrium. This largely defuses the
  slow-half-life concern for the two near-miss pairs, but it also means M2's
  half-life gate and the traded dynamics are different objects — worth a
  paragraph in the final report.
- **Rolling z window 1440 bars (60d)**: middle ground for the book's 28–66d
  raw half-lives; full-window min_periods so warm-up bars are NaN rather than
  computed from short noisy samples. Tunable in training (M5).
- **Entry/exit/stop = 2.0 / 0.0 / 3.0** — spec defaults, config-driven,
  explicitly tunable-not-sacred (M5 owns tuning).
- **Re-arm guard**: after any flat transition, no new entry until |z| returns
  inside the entry band. Without it, a 3-sigma stop-out would re-enter the next
  bar (|z| >= 2 still true), instantly re-buying the dislocation we refused to
  hold. Same guard means a z that gaps STRAIGHT past the stop from flat is
  never entered.
- **Signal-at-close semantics**: position at bar t is the DESIRED position
  decided at t's close; M4 executes on the next bar. The signal layer produces
  no PnL — PnL only exists net of costs (SPEC guardrail).
- **Fat tails on display**: z spikes to ±8 (Gaussian would never), and 34–40%
  of entries end in stop-outs. Expected for crypto; M4 will price what those
  stop-outs cost, and entry/stop levels are honest M5 tuning candidates.
