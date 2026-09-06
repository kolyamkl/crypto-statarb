# M10 — cross-asset comparison: equity pairs vs crypto perps

Hand-written analysis of the pre-registered replication (M10_PLAN.md, commit
`1ba73ad`). The crypto column is **pinned to tag `v1.0`** and was never re-run;
the equity study's auto-generated tables live in `reports/m10/`. Every parameter
below was frozen in `config_equities.yaml` (commit `ce0cf74`) before any equity
data was pulled, and the equity test window (2025-01-01 → 2026-07-10) was
evaluated exactly once.

> **Confound, stated up front (M10_PLAN §7):** the two studies differ in bar size
> (1h vs daily) and cost structure (funding + 7 bps vs borrow + 2 bps), not just
> asset class. Prevalence and stability comparisons (H1, H2) are robust to this;
> performance comparisons (H3) are indicative, not controlled.

## Verdicts on the three pre-registered hypotheses

| # | hypothesis (written before any data) | verdict |
|---|---|---|
| H1 | more equity pairs pass the EG screen than crypto's 1/91 | **supported, with an asterisk** — 13/276 (4.7%) vs 1/91 (1.1%), but 13 passes is almost exactly the ~13.8 false positives luck predicts |
| H2 | equity cointegration is less episodic than crypto's | **refuted** — rolling 1y pass rates 0–4% vs crypto's 5–11%; equity full-sample cointegration was *more* of an averaging artifact, not less |
| H3 | profitability does NOT scale with prevalence | **supported, the interesting way** — the equity book's headline OOS beats crypto's, but the diagnostics attribute it to a favorable tape, not to the screen: the tuning ranking was *anti*-informative, the economically-motivated pair lost money, and SPY buy-and-hold beat the book risk-adjusted |

## Side-by-side (crypto column frozen from v1.0)

| | crypto perps (v1.0) | US equities (M10) |
|---|---|---|
| universe → pairs | 14 symbols → 91 | 24 tickers → 276 |
| screen passes (worse-dir EG p < .05 + half-life gate) | **1** (1.1%) | **13** (4.7%) |
| luck-expected passes at α=.05 | ~4.5 | ~13.8 |
| best pair | AVAX~NEAR, p=0.0021 | MA~V, p=0.0045 |
| book half-lives (calendar) | ~28 / 51 / 66 d | ~22 / 22 / 23 d |
| book selection | human curation (relaxed HL bound post-hoc) | mechanical top-3 rule, pre-declared |
| train net / Sharpe / maxDD | +30.8% / +0.59 / −18.7% | +12.4% / +0.37 / −23.8% |
| **test net / Sharpe / maxDD** | **+4.0% / +0.27 / −16.9%** | **+13.7% / +1.02 / −6.0%** |
| test hit rate / turnover | 60% / ~39×/yr | 68% / ~28×/yr |
| test-window costs | ~4–5%/yr of capital | **0.96% total** over 1.5y |
| walk-forward (automated) | **−30.2%**, Sharpe −0.69 | **+3.3%**, Sharpe +0.12 |
| WF folds traded / cash | 12 / 3 | 14 / 0 |
| edge at 2× / 3× costs | −0.2% / −4.3% (dies) | +12.8% / +12.0% (survives) |
| grid Spearman (train→test Sharpe) | +0.10 | **−0.30** |
| grid configs positive OOS | minority | **97%** |
| leave-one-pair-out worst case | without ADA/LTC: **−0.24%** | without MA~AVGO: +7.3% (still positive) |
| regime split (factor up / down) | +11.5% / −7.2% (BTC) | +14.6% / +3.0% (SPY) |
| rolling 1y EG pass rates | 5–11% of windows | **0–4%** of windows |
| market benchmark, test window | BTC −22.9% (Sharpe −0.33) | SPY +29.6% (**Sharpe +1.11**) |

## 1. Prevalence (H1): more passes, but not more than luck

13 of 276 equity pairs passed both pre-registered gates vs crypto's 1 of 91 — a
4× higher pass *rate*, directionally as hypothesized (shared cash-flow drivers).
The asterisk: 276 tests at α = 0.05 predict ~13.8 false positives, and we
observed 13. Crypto's screen passed *fewer* pairs than luck predicts (1 vs
~4.5); equities passed *exactly* as many as luck predicts. Neither market shows
evidence of pairwise cointegration in excess of the multiple-testing base rate.
What H1 actually bought is candidate volume, not statistical conviction — and
the top of the equity list is at least economically legible (Mastercard~Visa,
Wells Fargo~AmEx) in a way AVAX~NEAR never was.

The mechanical top-3 book rule (pre-declared in DECISIONS.md before the screen
ran) selected MA~V, MA~AVGO, MA~NVDA — **Mastercard in all three pairs**. A
curator would have vetoed that concentration on sight. It was left as selected,
because the whole point of the rule was to remove the human step the crypto
study (M7) identified as its probable source of edge.

## 2. Stability (H2): refuted — equity cointegration was MORE episodic

The rolling 1-year Engle–Granger re-check is the hypothesis's own test, and it
came out backwards: the equity book pairs pass in **0% (MA~AVGO), 2% (MA~NVDA),
and 4% (MA~V)** of 1y windows, against crypto's 5–11%. The full-sample screen
detected a property of the 4-year average that essentially never holds in any
particular year — in *both* markets, but worse in equities. Median rolling
p-values sit at 0.40–0.68. Whatever made the equity test window profitable, it
was not a stable long-run equilibrium between these names.

## 3. Performance (H3): the headline flatters, the diagnostics confess

Read alone, the frozen split looks like vindication: test net **+13.7%, Sharpe
+1.02, maxDD −6.0%** — better than train (+0.37), better than crypto's OOS
(+0.27). Four diagnostics say the flattery is the tape, not the screen:

1. **The tuning ranking was anti-informative.** Spearman rank correlation
   between train and test Sharpe across all 72 configs: **−0.30** (crypto:
   +0.10). The train-best config was mediocre OOS (grid test-Sharpe range −0.11
   to +2.22). And **97% of configs were positive OOS** — when nearly every cell
   of the grid pays, the grid isn't finding edge; the window is handing it out.
2. **The economically-motivated pair lost money.** MA~V — the duopoly, the
   pair a human would have picked first — netted **−3.7%** (Sharpe −0.57) in the
   test window. The profits came from MA~AVGO (+26.3%) and MA~NVDA (+18.4%),
   the two cross-cluster pairs flagged as plausible luck candidates in
   `config_equities.yaml` *when the book was fixed*. Leave-one-pair-out:
   dropping MA~V *raises* test net to +22.4%. The one clean inversion of the
   crypto result (where the whole edge was one pair) — here the edge is
   distributed, but across the pairs with the weakest economic story.
3. **The book kept a directional tilt.** +14.6% in trailing-SPY-up regimes vs
   +3.0% in SPY-down. Milder than crypto's split (+11.5%/−7.2%) and positive on
   both sides — but the test window was 245 up-bars vs 114 down-bars. Dollar
   neutrality is still not factor neutrality.
4. **The passive benchmark won.** SPY buy-and-hold over the same test window:
   +29.6%, Sharpe **+1.11**, against the strategy's +1.02. In crypto the
   strategy's +4% against BTC's −23% was the whole story; in equities the
   market-neutral book made real money and *still* failed to beat owning the
   index. Gatev, Goetzmann & Rouwenhorst's decay thesis survives contact with
   this data: prevalence did not convert into edge over the passive alternative.

**The walk-forward is the fairest cross-asset read**, because it is the same
no-human-in-the-loop pipeline in both markets: crypto **−30.2%** (Sharpe −0.69),
equities **+3.3%** over 3.5 years (Sharpe +0.12, maxDD −7.4%, all 14 folds
traded, fold books as unstable as crypto's ever were). The automated pipeline
stops losing money in equities — mostly because frictions stop punishing its
churn — but it earns approximately nothing. The v1 conclusion generalizes:
**the pipeline manufactures candidates, not edge, in both asset classes.**

## 4. Costs: the one structural difference that is real

The crypto edge died at 2× costs (+4.0% → −0.2%). The equity book at 2× and 3×
costs: +12.8% and +12.0% — barely dented, because zero-commission spreads plus
30 bps/yr borrow are an order of magnitude below perp taker-fees plus funding
(test-window costs: 0.96% of capital total, vs ~4–5%/yr in crypto). This is the
robust, unglamorous cross-asset finding: **equity stat-arb's binding constraint
is signal, not friction; crypto's was friction, not signal.** Neither market
offered both at once.

## 5. What M10 changes about the v1 conclusions

- v1 attributed the crypto OOS profit to the human curation step. The equity
  study removed that step, and the mechanical book still printed a positive
  OOS — but via its least-motivated pairs, in a window where 97% of the grid
  was positive and the index did better. That is not evidence curation was the
  edge; it is evidence that *single-window OOS results, curated or not, are
  weak instruments*. The walk-forward remains the only instrument that
  generalized across both markets, and it reads ~zero in equities and worse in
  crypto.
- H2's refutation weakens the textbook rationale for equity pairs trading as
  practiced here: same-sector large-caps did not exhibit more stable pairwise
  cointegration than crypto perps. Basket/factor approaches (v1's "next steps")
  look better motivated than bilateral pairs in both markets.
- The CV claim is now literally true in both directions: the pipeline is
  asset-agnostic, and so — apparently — is its central negative result.

## Reproduce

```bash
make all-equities   # ingest (yfinance, ~1 min) → tests → screen → … → reports/m10/
```

Equity provenance: `data_provenance_equities.md` (retrieval-dated; adjusted
prices rewrite history, so re-pulls shift numbers slightly). Auto-generated
equity tables: `reports/m10/m2_pair_screen.md` … `m7_robustness.md`.
