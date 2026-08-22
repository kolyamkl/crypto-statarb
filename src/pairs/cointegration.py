"""M2 pair screening: Engle-Granger cointegration on log close prices.

Selection is by COINTEGRATION, not correlation (SPEC.md M2): two prices can be
highly correlated yet drift apart forever; cointegration is the property that a
fixed linear combination of them is stationary, i.e. the spread mean-reverts.

Look-ahead guard: everything in this module runs on the TRAINING window only
(config validation.train_end). Choosing pairs on data that overlaps the test
period would leak test-period information into the strategy (selection bias),
so the caller must pass a panel already truncated at train_end.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tsa.stattools import coint

from src.config import PairsConfig


@dataclass(frozen=True)
class PairScreenResult:
    leg_y: str  # dependent leg: log(leg_y) = alpha + beta * log(leg_x) + spread
    leg_x: str
    n_bars: int
    alpha: float
    beta: float
    eg_p: float  # Engle-Granger p-value, y-regressed-on-x direction
    eg_p_reverse: float  # x-regressed-on-y direction
    eg_p_max: float  # conservative screen statistic: worst of the two directions
    half_life_bars: float | None  # None when the spread shows no mean reversion
    ret_corr: float  # log-return correlation (descriptive only, never a filter)
    passed: bool


def ols_hedge(y: pd.Series, x: pd.Series) -> tuple[float, float, pd.Series]:
    """Static hedge ratio by OLS: y_t = alpha + beta * x_t + spread_t."""
    fit = sm.OLS(y, sm.add_constant(x)).fit()
    alpha, beta = float(fit.params.iloc[0]), float(fit.params.iloc[1])
    return alpha, beta, y - (alpha + beta * x)


def engle_granger_p(y: pd.Series, x: pd.Series) -> float:
    """Engle-Granger cointegration p-value for y regressed on x.

    statsmodels.coint uses MacKinnon critical values that account for the hedge
    ratio being ESTIMATED — running a plain ADF on the OLS residuals would use
    critical values that are too lenient and over-accept pairs.
    """
    return float(coint(y, x, trend="c")[1])


def half_life(spread: pd.Series) -> float | None:
    """Half-life of mean reversion in bars, from an AR(1) fit on the spread.

    Fit d(spread)_t = a + b * spread_{t-1}; the AR(1) coefficient is phi = 1 + b
    and the half-life is -ln(2)/ln(phi). Returns None when phi is outside (0, 1),
    i.e. the spread does not mean-revert at all.
    """
    lagged = spread.shift(1).iloc[1:]
    delta = spread.diff().iloc[1:]
    b = float(sm.OLS(delta, sm.add_constant(lagged)).fit().params.iloc[1])
    phi = 1.0 + b
    if not 0.0 < phi < 1.0:
        return None
    return float(-np.log(2) / np.log(phi))


def screen_pair(panel: pd.DataFrame, a: str, b: str, cfg: PairsConfig) -> PairScreenResult | None:
    """Screen one unordered pair {a, b}. Returns None if joint history is too short."""
    joint = panel[[a, b]].dropna()
    if len(joint) < cfg.min_overlap_bars:
        return None
    pa = np.log(joint[a]) if cfg.use_log_prices else joint[a]
    pb = np.log(joint[b]) if cfg.use_log_prices else joint[b]

    # EG is not symmetric in which leg is regressed on which. A genuinely
    # cointegrated pair passes in both directions, so we screen on the WORSE
    # p-value (conservative) and take hedge parameters from the better direction.
    p_ab = engle_granger_p(pa, pb)
    p_ba = engle_granger_p(pb, pa)
    y, x = (pa, pb) if p_ab <= p_ba else (pb, pa)

    alpha, beta, spread = ols_hedge(y, x)
    hl = half_life(spread)
    ret_corr = float(pa.diff().corr(pb.diff()))

    p_max = max(p_ab, p_ba)
    passed = (
        p_max < cfg.adf_alpha
        and hl is not None
        and cfg.half_life_min_bars <= hl <= cfg.half_life_max_bars
    )
    return PairScreenResult(
        leg_y=str(y.name),
        leg_x=str(x.name),
        n_bars=len(joint),
        alpha=alpha,
        beta=beta,
        eg_p=p_ab if p_ab <= p_ba else p_ba,
        eg_p_reverse=p_ba if p_ab <= p_ba else p_ab,
        eg_p_max=p_max,
        half_life_bars=hl,
        ret_corr=ret_corr,
        passed=passed,
    )


def screen_universe(panel: pd.DataFrame, cfg: PairsConfig) -> list[PairScreenResult]:
    """Screen every unordered pair in the panel, ranked best-first by eg_p_max."""
    results = []
    for a, b in combinations(sorted(panel.columns), 2):
        res = screen_pair(panel, a, b, cfg)
        if res is not None:
            results.append(res)
    return sorted(results, key=lambda r: (not r.passed, r.eg_p_max))
