# M4 backtest — analysis notes (honest negative result)

Hand-written analysis of the auto-generated numbers in `m4_backtest.md`.
Training window only (2021 → 2024), default M3 parameters, real frictions.

## Headline: the strategy as configured LOSES money — and not because of costs

Portfolio over 4 years, per unit of book capital:

| | gross | fees+slippage | funding | net |
|---|---|---|---|---|
| portfolio | **−1.5%** | −35.6% | +0.5% | **−36.5%** |

Two separate facts, and the first is the important one:

1. **Gross PnL is ~zero.** This is not "a good signal buried by fees" — the
   signal itself, entered at |z|≥2 on the Kalman innovation, has no edge before
   costs (per-pair gross: −14%, −15%, +25%). A cost problem could be engineered
   away; a no-edge problem cannot.
2. **Costs are large and exactly as predicted:** ~763 round trips × 2 units of
   gross turnover × 7bps (fee+slip) ≈ 35% of capital — the arithmetic reconciles
   with the backtest to the basis point, which is good news about the engine and
   bad news about the trade frequency.
3. **Funding is a non-issue on a hedged book** (+0.5% over 4y): long-leg and
   short-leg funding largely cancel. The FTX-regime funding-cadence machinery
   was still worth building — it is what lets us SAY this with evidence.

## Diagnosis: the adaptive hedge whitened away the signal

The M3 spread is the Kalman one-step prediction error. But a well-functioning
Kalman filter produces innovations that are close to WHITE NOISE by
construction — that is literally what the filter optimizes for. With
delta=1e-5 the state adapts fast enough that the slow 28–66d mean reversion the
M2 screen found gets absorbed into the moving [alpha, beta] state, and what is
left to "trade" is an unpredictable residual. Trading mean-reversion rules on
white noise produces exactly what we observe: zero gross, minus costs.

In other words: **M2 found slow mean reversion; M3's filter (as parameterized)
removed it before the trading rule could see it.** The M3 observation that
"average holds are hours, not days" was the early symptom of this.

## What this implies for M5 (training-window tuning — legitimate, documented)

The tension to resolve: the hedge must adapt (M2's static-beta assumption is
also wrong) but NOT so fast that it eats the signal. Candidate knobs, all
tunable on training data only:

- **delta ↓ (1e-7…1e-8):** slower filter → innovation keeps more of the raw
  spread's mean reversion → slower signals, fewer trades, less cost drag.
- **Trade the OLS/frozen-beta spread z instead of the innovation**, using the
  Kalman only to update the hedge slowly.
- **Cost-aware entry:** only enter when the dislocation (in spread terms)
  exceeds a multiple of the round-trip cost.
- **Wider entry / coarser bars (4h):** fewer, larger trades.

None of this is done here: M4's job was an engine whose accounting can be
trusted, and a first honest number. Both exist. The negative result stands as
evidence, per the working agreement — it is a finding about parameterization,
not yet a verdict on crypto stat-arb.
