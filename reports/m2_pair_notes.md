# M2 pair selection — analysis notes

Hand-written analysis of the auto-generated ranked table in `m2_pair_screen.md`.
Training window only (2021-01-01 → 2024-12-31, hourly Binance USDT-M perps).

## Headline finding: correlation is everywhere, cointegration almost nowhere

Every pair in the universe is positively correlated at the hourly return level
(0.44–0.85) — crypto trades as one big sector factor. Yet only **1 of 91 pairs**
(AVAX/NEAR) passes a 5% Engle–Granger screen *and* has a half-life inside the
tradeable [1d, 30d] band. This is the textbook correlation-vs-cointegration
distinction showing up in real data: shared short-run moves say nothing about a
stable long-run equilibrium between two prices.

Why so few pairs cointegrate over this window:

- The 4-year training window spans several structural regimes (2021 bull,
  2022 LUNA/FTX collapses, 2023–24 recovery) with heavy *dispersion* — e.g. SOL
  re-rated ~10x against ADA/DOT in 2023–24. Long-run equilibria between token
  prices genuinely broke.
- Idiosyncratic drivers dominate at the token level: unlock schedules (ARB, OP),
  meme flows (DOGE), payments-vs-platform narratives. These are permanent
  relative-value shocks, not mean-reverting noise.
- Half-lives cluster at 40–150+ days even where the EG statistic is decent:
  spreads drift back eventually, but far too slowly to trade on hourly bars
  against funding and fees.

## Does the one survivor make economic sense?

**AVAX ~ NEAR** (β=0.86, EG p=0.0021, half-life ≈ 28d): yes, this is the pair a
fundamental analyst would have proposed *before* seeing the statistics. Both are
2020-vintage high-throughput alt-L1 smart-contract platforms with the same
buyer base, competing for the same developer/TVL narrative, similar market-cap
tier, and no idiosyncratic driver the other lacks (contrast BTC's store-of-value
flows or DOGE's meme flows). They are close substitutes in an "L1 rotation"
basket, which is precisely the economic mechanism that generates cointegration.

Near-misses that passed the EG gate but revert too slowly (all half-life > 30d):

- **ADA ~ DOT** (p=0.049, ~51d): economically the most sensible near-miss — both
  2017-era "ETH alternative" platforms with overlapping holder bases.
- **ADA ~ LTC** (p=0.024, ~66d): plausible as two large-cap "OG retail" coins.
- **ETH ~ BCH** (p=0.028, ~48d): economically weak — ETH has strong idiosyncratic
  drivers; treating this one as a statistical accident is the safer read.

Multiple-testing context: at α=0.05 across 91 tests we *expect* ~4.5 false
positives, and we observed 4 pairs under 0.05. Only AVAX/NEAR (p=0.002) is
comfortably below what chance predicts; the economic-plausibility check above is
doing real work, not decoration.

A cautionary sight elsewhere in the table: several short-history ARB pairs fit
*negative* hedge ratios — nonsense hedges from spurious regression on trending
samples. The conservative both-directions screen rejected them all.

## Implications for M3+ (decision needed at review)

One pair is a thin book. Options, in order of my preference:

1. **Proceed with AVAX/NEAR + the two economically-sensible near-misses
   (ADA/DOT, ADA/LTC)** as a 3-pair book, documenting that the latter two relax
   the half-life bound to ~70d. Honest framing: the half-life bound is a
   tradeability prior, not a statistical test, so relaxing it is a documented
   judgment call — but it is still a post-hoc widening and must be labelled as
   such.
2. **Proceed with AVAX/NEAR alone.** Cleanest methodology, but a single pair
   makes every downstream number hostage to one spread.
3. **Re-screen on a shorter recent window** (e.g. last 2y of training). More
   pairs would pass, and walk-forward (M5) re-screens per window anyway — but
   doing it now because the 4y result was thin is exactly the data snooping the
   spec warns about, so I recommend against changing the M2 screen and instead
   letting M5's walk-forward re-screening speak.

The thin pass rate is itself a finding for the final report's "what didn't
work" section: naive long-window cointegration screening on crypto majors
yields almost no tradeable pairs.
