# crypto-statarb — Project Spec & Claude Code Brief

**Author:** Mykola "Kolya" Maklakov (GitHub: kolyamkl)
**Purpose:** Rebuild PeRatio's pair-trading work as an honest, interview-grade statistical-arbitrage research project.
**Audience for the final output:** a quant researcher/recruiter reading the README in ~5 minutes.
**Status:** greenfield repo, built with Claude Code.

---

## 0. How to use this document

This file is the single source of truth for the project. Drop it in the repo root as `SPEC.md` (and optionally copy the "Working agreement" section into `CLAUDE.md` so Claude Code reads it on every session). Build **one numbered milestone at a time, in order** — do not skip ahead. Each milestone has a Definition of Done; don't move on until it's met and committed.

There is a ready-to-paste **kickoff prompt for Claude Code at the very bottom** (Section 9). Start there.

---

## 1. What this project is (and is NOT)

**It IS:** a statistical pair-trading / stat-arb study on crypto pairs. Methodology first. Honest metrics with transaction costs, funding, and out-of-sample testing. A written report an interviewer can read and trust, including a "what didn't work" section.

**It is NOT** (kill these framings — they read as "crypto product," not research):
- ❌ "Custom LLM analyses news → generates signals"
- ❌ Telegram bot / clans / leaderboards / any product surface as the headline
- ❌ Any backtest result reported without transaction costs and without an out-of-sample test

The deployed PeRatio system and real Hyperliquid execution stay in the story — but as a **supporting credibility point** ("I also ran this live"), never the headline. The headline is the research.

**The single most important number in the whole project:** the gap between in-sample and out-of-sample performance. Report it prominently and honestly. A modest Sharpe that survives out-of-sample beats a huge Sharpe that doesn't.

---

## 2. Positioning for the two target lanes

- **Crypto-native quant (primary):** Wintermute, GSR, Cumberland, Flow Traders, Keyrock, Auros. This project is your genuine edge — crypto domain + real execution experience + honest research.
- **Traditional quant (side bets):** the methodology (cointegration, Kalman filtering, walk-forward validation, cost modelling) is exactly what they test; the fact that the underlying market is crypto is incidental.

Write the README so a reader from *either* lane sees rigor.

---

## 3. Tech stack & conventions

- **Language:** Python 3.11+. Type hints throughout.
- **Env & deps:** `uv` or `poetry` (pick one), pinned versions. `requirements.txt`/`pyproject.toml` committed.
- **Data store:** PostgreSQL (Docker Compose for local). Raw and processed tables separated.
- **Core libs:** `pandas`, `numpy`, `statsmodels` (ADF, Engle–Granger, OLS), `scipy`, `matplotlib`; `pykalman` or a hand-rolled Kalman filter for the dynamic hedge ratio. Avoid heavyweight backtest frameworks at first — a transparent, hand-written vectorised backtest is more defensible in interview than a black box.
- **Config:** all parameters (pairs, z-thresholds, costs, windows, train/test split dates) in one `config.yaml` — never hard-coded in logic.
- **Testing:** `pytest`. Unit tests on the parts where look-ahead bias hides (rolling stats, signal generation, PnL accounting).
- **Reproducibility:** fixed random seeds; a single `make all` / `python -m src.run` that reproduces every figure and metric from raw data.
- **Repo hygiene:** meaningful commits per milestone; no data or secrets committed (`.gitignore` the DB dumps and API keys; use `.env`).

Suggested layout:
```
crypto-statarb/
├── README.md            # the report — the thing interviewers read
├── SPEC.md              # this file
├── CLAUDE.md            # working agreement for Claude Code
├── config.yaml
├── docker-compose.yml   # postgres
├── pyproject.toml
├── data/                # gitignored; raw dumps
├── notebooks/           # exploration only, not the source of truth
├── src/
│   ├── ingest/          # M1 data layer
│   ├── pairs/           # M2 cointegration & hedge ratio
│   ├── signals/         # M3 z-score signals
│   ├── backtest/        # M4 backtest w/ frictions
│   ├── validate/        # M5 walk-forward
│   ├── metrics/         # M6 performance metrics
│   └── report/          # M7 figures + tables
└── tests/
```

---

## 4. The build — milestones in strict order

Each milestone = one focused work block. **Definition of Done (DoD)** must be met before moving on.

### M1 — Data layer
Pull clean historical OHLCV **plus funding rate and basis** for a candidate universe of crypto pairs from an exchange API (Hyperliquid and/or Binance). Store in Postgres. Document source, frequency (start hourly or 15m), and full date range. **No survivorship shortcuts** — record which symbols existed when, and note any gaps/outages rather than silently forward-filling.
- **DoD:** queryable `ohlcv` and `funding` tables; a `data_provenance.md` stating source, granularity, date range, and known gaps; a sanity notebook plotting a few series.

### M2 — Pair selection by cointegration (not correlation)
For each candidate pair: estimate hedge ratio β (OLS first, then a Kalman filter for a time-varying β), test the spread for stationarity with **ADF**, and screen pairs with **Engle–Granger** (and optionally **Johansen**). Correlation is a first-pass filter at most — selection is by cointegration.
- **DoD:** a ranked table of pairs with β, ADF p-value, half-life of mean reversion; a short note on why the top pairs make economic sense (not just statistical flukes).

### M3 — Signal construction
Rolling **z-score of the spread**. Entry when |z| > 2, exit as z → 0, stop-out when |z| > 3. Treat these as *tunable*, not sacred — but tune only on the training window (see M5). Guard against look-ahead: the z-score at time *t* uses only data up to *t*.
- **DoD:** signal series generated per pair; a unit test proving no future data leaks into any rolling statistic.

### M4 — Backtest with real frictions
Vectorised, transparent backtest applying: transaction costs, slippage, **perp funding costs**, and sane position sizing. No look-ahead anywhere — trades execute on the *next* bar after signal, at a realistic fill.
- **DoD:** per-pair and portfolio equity curves; PnL decomposed into gross vs. costs vs. funding; a test that PnL accounting reconciles.

### M5 — Out-of-sample / walk-forward validation
Split into a training window (tune thresholds/params here) and an untouched test window. Then a rolling **walk-forward** (re-fit, step, repeat). **The in-sample vs out-of-sample gap is the headline number — report it explicitly.**
- **DoD:** train vs. test metrics side by side; walk-forward equity curve; one paragraph honestly interpreting the degradation.

### M6 — Honest metrics
Sharpe, Sortino, max drawdown, hit rate, turnover, average holding period, exposure — all **net of costs**, benchmarked vs. buy-and-hold BTC/ETH. Show the equity curve and the drawdown curve.
- **DoD:** a `metrics` module that emits one clean results table + figures, reproducibly.

### M7 — Robustness & failure analysis
Stress across pairs, cost assumptions (double the fees — does the edge survive?), and market regimes (trend vs. chop, pre/post a big move). Write the **"what didn't work"** section: pairs that decohered, params that overfit, regimes that broke it.
- **DoD:** a robustness table + the honest failure write-up.

### M8 — The writeup (README)
Structure: **problem → data → method → results → limitations → next steps.** Lead with method and the out-of-sample result. Embed the equity curve, the results table, and the in-sample/out-of-sample comparison. This is what the interviewer reads — make it clean and skimmable.
- **DoD:** README a stranger can follow end-to-end and reproduce with one command.

### M9 (bonus) — Paper-trade live vs backtest
Run it forward on paper and compare realised vs. backtested PnL to demonstrate you understand overfitting and implementation shortfall. Ties in your real Hyperliquid execution credibility.

---

## 5. Guardrails (the things that get research projects rejected)

- **Look-ahead bias** is the cardinal sin. Every rolling statistic, every fit, every parameter choice must use only past data at each point in time. Assume it's there until a test proves it isn't.
- **Overfitting:** if you tried 50 pairs and 20 threshold combos and report the best, that's not a result — that's data snooping. Report the *process*, the parameter count, and the out-of-sample number.
- **Costs are not optional.** A "profitable" strategy that dies under realistic fees + funding + slippage is a negative result — and reporting it honestly is itself a strong signal.
- **No survivorship bias** in pair selection.
- **Reproducibility:** if you can't regenerate every number from raw data with one command, an interviewer can't trust any of them.

---

## 6. Definition of "v1 shipped" (your end-of-summer checkpoint)

M1–M8 complete, committed, and reproducible; a clean README report with an honest out-of-sample result and a "what didn't work" section; repo public at `github.com/kolyamkl/crypto-statarb`. M9 is a bonus if time allows.

---

## 7. Working agreement for Claude Code (copy into CLAUDE.md)

- Build milestones **in order**; stop at each DoD and let me review before proceeding.
- Prefer **transparent, readable code over cleverness** — I need to explain every line in an interview.
- When you make a modelling choice (which test, which window, which cost assumption), **add a one-line comment explaining why**, and flag the assumptions back to me.
- Proactively hunt for **look-ahead bias** in anything with a rolling window or a fit; write a test for it.
- Never hard-code parameters that belong in `config.yaml`.
- Never commit data, secrets, or `.env`.
- Keep a running `DECISIONS.md` of methodology choices and trade-offs — I'll turn it into the README's limitations section.
- When something doesn't work, **say so and keep the evidence** — negative results are part of the deliverable, not failures to hide.

---

## 8. Interview story this project buys you (keep the end in mind)

By the end you can say, crisply: *"I built a crypto stat-arb study — selected pairs by cointegration not correlation, estimated a time-varying hedge ratio with a Kalman filter, traded a z-score spread with realistic costs and funding, and validated walk-forward. In-sample Sharpe was X, out-of-sample Y — and here's the gap and why. Here's what didn't work and what I'd do next."* That sentence is the point of the whole project.

---

## 9. 🚀 KICKOFF PROMPT FOR CLAUDE CODE (paste this to start)

> I'm building a crypto statistical-arbitrage research project from scratch, in this empty repo. The full spec is in `SPEC.md` — read it first and treat it as the source of truth. It's a serious, interview-grade quant research project (methodology first, honest metrics with costs and out-of-sample testing), NOT a crypto product.
>
> Start with **Milestone M1 (Data layer) only** — do not build ahead. Specifically:
> 1. Set up the repo skeleton from Section 3 of the spec (Python 3.11+, `pyproject.toml`, `config.yaml`, Postgres via docker-compose, `.gitignore`, `.env.example`, `pytest`).
> 2. Write an ingestion module in `src/ingest/` that pulls historical OHLCV **plus funding rate and basis** for a small candidate universe of crypto pairs from the Hyperliquid API (and/or Binance), and stores it in Postgres. Make the symbol list and date range config-driven.
> 3. Document source, granularity, and date range in `data_provenance.md`, and record any gaps rather than silently forward-filling. No survivorship shortcuts.
> 4. Add a sanity-check script/notebook that plots a couple of series so I can eyeball the data.
>
> Before writing code, propose the schema for the `ohlcv` and `funding` tables and the exact API endpoints you'll hit, and wait for my OK. Keep code transparent and typed — I need to explain every line in an interview. Flag any assumptions back to me. Stop when M1's Definition of Done is met so I can review before we move to M2.

---

*Built from your Quant Internship Plan (Summer-2027 cycle) and the PeRatio → stat-arb build order. Verify each exchange API's current auth/rate limits when you start M1.*
