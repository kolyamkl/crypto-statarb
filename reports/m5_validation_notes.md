# M5 validation — interpretation (the honest paragraphs)

Hand-written analysis of the auto-generated numbers in `m5_validation.md`.

## The two headline numbers

1. **Static split (curated 3-pair book, grid tuned on train, frozen):**
   train Sharpe **+0.59** → test Sharpe **+0.27**, net +30.8% (4y) → +4.0%
   (1.5y). The edge survives out-of-sample but roughly halves — and the equity
   curve shows the surviving half is concentrated in one strong quarter
   (Q1 2025) followed by ~18 months of plateau and a decaying tail.
2. **Walk-forward (fully automated: re-screen 91 pairs + re-tune the grid every
   quarter):** stitched out-of-sample **−30.2%** over ~3.5 years. 15 folds:
   11 traded (5 positive, 7 negative), 3 held cash because the screen found
   nothing (all of 2025). Average per-fold train Sharpe ≈ +1.0; realized
   out-of-sample: consistently worse, often negative — per-fold overfitting
   measured directly, fold after fold.

## Interpreting the degradation

The gap between the two experiments is the real finding. The static book and
the walk-forward run the SAME signals, SAME engine, SAME costs — the only
difference is who chose the pairs. The static book went through the M2 review's
economic-plausibility filter (same-vintage L1 substitutes, large-cap OG coins);
the automated quarterly re-screen takes whatever a 2y window's statistics
offer, and 2y crypto windows offer mostly artifacts: books changed almost every
fold (cointegration is not stable at that horizon — consistent with M2 finding
only 1/91 pairs on the 4y window), and the two worst folds (−15.1%, −12.1%)
held books the economic filter would likely have vetoed — the −15.1% fold was
short-DOGE-spread through the November-2024 meme rally. **Whatever edge exists
here lives in pair curation, not in parameter tuning** — the grid mattered far
less than the book (most folds chose the same corner of the grid: slow filter,
wide entry).

Honest bottom line for the final report: a modest, curated-book edge survives
out-of-sample (Sharpe ~0.27, net +2.7%/year, max drawdown −16.9%) but is thin,
concentrated in one quarter, and not investable as-is; the fully systematic
version of the same pipeline loses money. The multiple-testing caveat from M2
also compounds across walk-forward folds (91 tests × 12 traded folds), which
is exactly the mechanism the cash-quarters and bad-books symptoms point at.

## Also learned (engineering)

The first walk-forward attempt crashed — deliberately: the engine refuses
entries with a non-positive hedge ratio, and a freshly screened fold pair hit
one (Kalman beta −0.19). The fix cancels such trade episodes at the signal
level, the way a live desk would refuse a degenerate hedge, with a unit test
that a mid-trade beta dip does NOT cut a healthy trade short. A looser engine
would have silently monetized a long-long "pair".
