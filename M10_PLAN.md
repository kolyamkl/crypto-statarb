# M10 (PROPOSED) — Cross-asset replication: equity pairs vs crypto perps

> Status: **planned, pending Kolya's review** — not started. This document pre-registers the
> design so that no choice below can be quietly adjusted after seeing results.
> Prerequisite before any code: `git tag v1.0` on the final M8 commit, so the crypto study's
> numbers (CV, README) stay pinned to an immutable state. v1 reports are never overwritten.

## 1. Purpose

Run the **same pre-registered pipeline** on US equities and publish a side-by-side comparison
with the crypto perp study. This is a replication study of the *process*, not a hunt for a
better backtest — it directly addresses M7's core criticism (one pair, one episode, no breadth)
by testing whether the pipeline's behavior generalizes to a second asset class.

## 2. Pre-registered hypotheses (written before any data is pulled)

- **H1 — prevalence:** a larger share of equity pairs passes the Engle–Granger screen than
  crypto's 1/91. Same-sector stocks share cash-flow drivers, so real long-run equilibria
  should be more common.
- **H2 — stability:** equity cointegration is less episodic — higher rolling-EG pass rates
  than crypto's 5–11% of 1y windows.
- **H3 — profitability does NOT scale with prevalence:** net out-of-sample performance is
  *not* proportionally better, because equity pairs trading is a 40-year-old crowded trade
  (Gatev, Goetzmann & Rouwenhorst document industry-wide return decay after the 2000s).
  More cointegration ≠ more edge; finding H1+H2 true and H3 true would itself be the
  headline result.

Reporting rule: all three hypotheses are reported however they come out. A "boring" result
(everything as hypothesized) and a surprising one are equally publishable.

## 3. The one-way ratchet (validation protocol)

- Same split discipline as v1: train ≤ 2024-12-31; test 2025-01-01 → mid-2026 untouched
  until the final evaluation. The crypto test window is **burned** as evidence — nothing
  learned from it may tune the equity study (it informs only the *comparison framing*).
- Every parameter adaptation for equities (Section 5) is fixed in `config.yaml` **before**
  the first screen runs; deviations require a dated DECISIONS.md entry explaining why.
- One evaluation pass on the equity test window. No re-tuning after seeing it.
- Walk-forward re-run with the same fold structure (rescaled to daily bars) to test the
  automated pipeline on equities too — the crypto finding ("edge lives in curation") gets
  its own replication test.

## 4. Data (the only genuinely new engineering)

- **Bars:** daily adjusted closes. Free intraday equity data does not exist at usable
  quality; this is a known limitation, flagged prominently in the comparison (Section 7).
- **Source:** Stooq or yfinance daily OHLCV (decide at implementation; record choice and
  retrieval date in `data_provenance.md`). Adjusted prices handle splits/dividends for
  signal purposes; dividend cash flows on shorts are proxied inside the cost model.
- **Survivorship bias — worse than crypto:** free sources only list surviving tickers, and
  the universe below is drawn from today's large-caps. Documented, not fixable at zero
  budget (a delisted-inclusive dataset like CRSP would fix it; out of scope).
- **Window:** matched to crypto — 2021-01-01 → 2026-07-11, same `train_end: 2024-12-31`,
  so the comparison holds the macro period constant.
- **Universe (~24 tickers, pre-declared, economic clusters — chosen for plausible
  cointegration *mechanisms*, NOT known-good pairs, same rule as M1):**
  - Banks: JPM, BAC, C, WFC, GS, MS
  - Integrated oil: XOM, CVX, COP
  - Semiconductors: NVDA, AMD, INTC, TXN, AVGO
  - Payments: V, MA, AXP
  - Big-box retail: WMT, TGT, COST
  - Beverages: KO, PEP
  - Telecom: VZ, T
  - ~24 symbols → C(24,2) = 276 candidate pairs (multiple-testing note: ~13.8 expected
    false positives at 5%; report against this base rate exactly as M2 did).
- **Storage:** same Postgres schema with an `asset_class`/market discriminator (or a
  parallel table set); ingestion module `src/ingest/equities.py`, same idempotent-upsert +
  gap-recording + drop-forming-bar rules. No funding/premium tables for equities.

## 5. Pre-declared method adaptations (crypto → equities)

Everything not listed here stays byte-identical.

| knob | crypto (1h bars) | equities (daily bars) | rationale |
|---|---|---|---|
| bars per year | 8760 | 252 | trading calendar; Sharpe annualization √252 |
| z-score windows (grid) | 720h / 1440h (30d / 60d) | 21d / 42d trading days | same ~1–2 month calendar horizon |
| half-life bounds | 24–720h (1–30 d) | 5–60 trading days | daily bars can't resolve <1 week reversion; upper bound loosened because equity reversion is slower and holding costs lower (no funding) |
| Kalman burn-in | 720 bars | 63 bars (~3 months) | same calendar length |
| walk-forward folds | 17520h train / 2160h test | 504d train / 63d test | same 2y / 1 quarter structure |
| execution | decide at close t, fill bar t+1 | decide at close t, fill at **next day's open** | overnight gap risk is real in equities and must not be assumed away |
| trades floor | ≥15/pair-year | ≥10/pair-year | fewer bars ⇒ fewer signals; declared here, not fitted |

**Cost model (equity variant, pre-declared):**
- Commission ≈ 0 (retail zero-commission era) but **half-spread ≈ 1–2 bps** per side for
  liquid large-caps → model 2 bps/side slippage-inclusive.
- **Borrow fee** on the short leg: 30 bps/yr (general-collateral proxy for large caps),
  accrued daily — replaces funding, always a cost (unlike funding, which sometimes pays).
- **No funding income/expense**; dividends handled via adjusted prices + the borrow proxy.
- Same cost-stress multipliers (0.5×/1×/2×/3×) in M10's robustness pass.

## 6. Pipeline reuse map

| stage | change required |
|---|---|
| M2 screen, M3 signals, Kalman | none (config-driven) |
| M4 engine | funding component → borrow-fee component; next-open fill |
| M5 grid + walk-forward | none (config-driven rescaling) |
| M6 metrics | `BARS_PER_YEAR` from config (already parameterized) |
| M7 robustness | regime slices use SPY instead of BTC as the sector factor |
| tests | new: equity ingestion; borrow-fee accrual; everything else reused |

## 7. Comparison deliverables (`reports/m10_crossasset.md`)

Side-by-side, crypto column frozen from v1 reports:
1. **Prevalence:** % of pairs passing EG (worse direction) + half-life filter; observed vs
   luck-expected false positives. (H1)
2. **Stability:** rolling 1y EG pass rates per book pair; median worse-p. (H2)
3. **Half-life distributions** in calendar days.
4. **OOS performance:** net, Sharpe, max DD, hit rate for frozen split AND walk-forward.
5. **Cost stress** side-by-side (which market's edge is more friction-fragile).
6. Equity curves + rolling-EG comparison plots.

**Confound flagged in the report header:** the two studies differ in bar size (1h vs daily)
and cost structure, not just asset class. Prevalence/stability comparisons (H1, H2) are
robust to this; performance comparisons (H3) are indicative, not controlled.

## 8. Honest-reporting commitments

- Both books published, both walk-forwards published, cash folds included.
- If equities also produce a one-pair-carries-everything result, leave-one-pair-out says so.
- Failure analysis updated (`m7_failure_analysis.md` gains a cross-asset section or an
  `m10` counterpart) — whichever way the results land.
- DECISIONS.md entry at: plan acceptance, data-source choice, and results write-up.

## 9. Definition of Done

`make all-equities` (or a config-switched `make all`) reproduces the entire equity study
from raw data; `reports/m10_crossasset.md` presents the three-hypothesis comparison with
the crypto column pinned to v1.0; README gains a short cross-asset section and the CV's
"equities replication" claim becomes literally true.

## 10. Timeline & sequencing

~1–2 weeks part-time. **Starts only after internship applications are out** — the crypto
study is already CV-complete, and M9 (paper-trading) remains independently valuable and
can run in parallel (it's mostly waiting time).
