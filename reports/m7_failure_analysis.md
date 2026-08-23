# M7 — what didn't work (the honest section)

Hand-written. This is the part of the project I'd defend hardest in an
interview, because every claim below is backed by a table in the repo.

## 1. The Kalman filter whitened away its own signal (M4)

With the textbook delta=1e-5, the filter adapted fast enough to absorb the slow
mean reversion the M2 screen had found; what remained to trade was
near-white noise, and the first backtest lost −36.5% net (gross ≈ 0 — a
no-edge problem, not a cost problem). The M5 grid "fixed" it by slowing the
filter 100x — which is another way of saying the strategy only works in the
narrow band between "hedge too static" and "hedge so adaptive it eats the
signal", and we found that band by searching on training data.

## 2. The fully-automated pipeline lost 30% out-of-sample (M5)

Re-screening pairs and re-tuning quarterly — the same signals, engine, and
costs as the curated book — produced −30.2% over 3.5 years. Books were
unstable fold to fold, three 2025 quarters found no pairs at all, and the worst
fold was short a DOGE spread through the November-2024 meme rally. The edge,
such as it is, came from the human economic-plausibility filter at M2 review,
which is precisely the part that doesn't scale and can't be validated
statistically.

## 3. The surviving +4% is one pair and one quarter (M6/M7)

Leave-one-pair-out: remove ADA/LTC and the test window nets −0.24% — the
entire out-of-sample profit was one pair's doing (remove the losing ADA/DOT
instead and it doubles to +8.15%). The equity curve concentrates most of the
gain in Q1-2025 — which the rolling-EG plot independently identifies as
ADA/LTC's only strongly-cointegrated episode. An edge this concentrated is an
anecdote, not a distribution.

## 4. Double the fees and it's gone (M7 cost stress)

0.5x costs: +6.1% / Sharpe +0.42. 1x: +4.0% / +0.27. **2x: −0.2% / −0.01.**
The spec's own stress question — "double the fees, does the edge survive?" —
has answer **no**. At taker+slippage of ~14bps a round trip and ~39x annual
turnover, the strategy pays ~4-5%/year to the market; the gross edge is barely
bigger. (Implication: maker execution or lower turnover isn't an optimization,
it's existential.)

## 5. The parameter tuning was mostly luck (M7 sensitivity)

Spearman rank correlation between train and test Sharpe across all 72 grid
configs: **+0.10**. Only 35% of configs were positive out-of-sample, and the
best test config (+0.85) had a NEGATIVE train Sharpe. The honest reading: the
grid search picked a defensible config, but its train ranking carried almost
no information about test performance — the +0.27 landed within luck's reach.

## 6. "Market-neutral" wasn't, in PnL terms (M7 regimes)

The book is hedged position-by-position, yet realized PnL splits +11.5%
(Sharpe +2.14) in trailing-BTC-up regimes vs −7.2% (Sharpe −0.85) in
BTC-down regimes. Mean-reversion between alts appears to hold when the sector
grinds up and to break when it sells off together — exactly when a neutral
book is supposed to earn its keep. Dollar-neutrality is not factor-neutrality.

## 7. The cointegration itself was episodic (M7 rolling EG)

The three book pairs pass a rolling 1y Engle-Granger at 5%, in only 5–11% of
windows across 2022–2026. The M2 full-window screen detected an AVERAGE
property that exists in few actual sub-periods. Pairwise cointegration on
crypto majors is a sometimes-thing, which caps what any static pair-trading
system can extract from it.

## Structural limitations (known, unfixed)

- **Survivorship:** Binance exchangeInfo only lists surviving symbols; coins
  delisted before mid-2026 could never enter the universe (documented in M1).
- **Multiple testing:** 91 pairs at 5%, compounded across walk-forward folds.
- **Execution model:** 1h bars, next-bar fills, flat bps slippage; no intrabar
  stop-outs (a 3-sigma spike inside a bar is invisible), no liquidation or
  margin modelling.
- **No shorting frictions beyond funding** (borrow availability assumed).

## What I would try next (not claims — hypotheses)

Maker-first execution and entry thresholds priced off round-trip cost (the
edge dies at 2x costs, so the cost side is the highest-leverage dial); basket /
cross-sectional stat-arb instead of bilateral pairs (episodic pairwise
cointegration suggests a common-factor structure that pairs capture badly);
and a regime gate driven by the sector factor, given finding #6. Each is a
training-window experiment first, by the same rules as everything above.
