"""Hand-rolled Kalman filter for a time-varying hedge ratio.

Hand-rolled rather than pykalman: the filter is ~20 lines, owning them is the
point of the exercise, and pykalman is unmaintained (DECISIONS.md).

Model (per Chan, "Algorithmic Trading", ch. 3):
    state:       [alpha_t, beta_t] follows a random walk
    observation: y_t = alpha_t + beta_t * x_t + e_t,   e_t ~ N(0, R)

Look-ahead guard: this is a FILTER, never a smoother — the estimate at time t
uses observations up to and including t only. Using smoothed (two-sided)
estimates would leak the future into the hedge ratio; a unit test asserts
causality by mutating future observations and checking earlier output is
unchanged.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm

from src.config import KalmanConfig


def kalman_hedge(y: pd.Series, x: pd.Series, cfg: KalmanConfig) -> pd.DataFrame:
    """Filtered [alpha_t, beta_t] for y_t = alpha_t + beta_t * x_t + e_t.

    The first `burn_in_bars` observations are used for an OLS warm-up that
    initializes the state, its covariance, and the observation noise R; those
    bars get no filtered estimate and must never be traded downstream.

    Returns a DataFrame indexed like y[burn_in:] with columns alpha, beta.
    """
    if len(y) != len(x):
        raise ValueError("y and x must be aligned and equal length")
    burn = cfg.burn_in_bars
    if len(y) <= burn:
        raise ValueError(f"need more than burn_in_bars={burn} observations, got {len(y)}")

    # Warm-up: OLS on the burn-in window seeds the state, its covariance, and R.
    warm = sm.OLS(y.iloc[:burn], sm.add_constant(x.iloc[:burn])).fit()
    state = np.array([warm.params.iloc[0], warm.params.iloc[1]])  # [alpha, beta]
    cov = np.asarray(warm.cov_params())  # OLS parameter covariance as initial P
    obs_var = float(warm.resid.var(ddof=2))  # R: observation noise from OLS residuals

    # Chan's single-knob parameterization: state noise as a fixed ratio delta.
    state_noise = cfg.delta / (1.0 - cfg.delta) * np.eye(2)

    xs = x.to_numpy()
    ys = y.to_numpy()
    n = len(ys)
    out = np.empty((n - burn, 2))

    for t in range(burn, n):
        cov = cov + state_noise  # predict: random-walk state, uncertainty grows
        h = np.array([1.0, xs[t]])  # observation vector for y_t = [1, x_t] @ state
        innovation = ys[t] - h @ state
        innovation_var = h @ cov @ h + obs_var
        gain = cov @ h / innovation_var
        state = state + gain * innovation  # update: blend prediction with observation t
        cov = cov - np.outer(gain, h) @ cov
        out[t - burn] = state

    return pd.DataFrame(out, index=y.index[burn:], columns=["alpha", "beta"])
