"""M3 spread and z-score construction — every value at time t uses data <= t.

The tradeable spread is the Kalman PREDICTION error (innovation): today's log
price of leg_y minus what yesterday's filtered [alpha, beta] predicts from
today's leg_x. Using the state filtered AT t would be subtly wrong — that state
has already absorbed today's observation, shrinking the very dislocation we
want to trade. "Today's spread, measured with yesterday's hedge ratio" is both
causal and honest.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import KalmanConfig
from src.pairs.kalman import kalman_hedge


def pair_spread(y_log: pd.Series, x_log: pd.Series, kcfg: KalmanConfig) -> pd.DataFrame:
    """Causal innovation spread. Columns: beta (the LAGGED hedge ratio actually
    usable at t), spread. Starts one bar after the Kalman burn-in."""
    states = kalman_hedge(y_log, x_log, kcfg)
    lagged = states.shift(1)  # state known at the close of bar t-1
    spread = y_log - (lagged["alpha"] + lagged["beta"] * x_log)
    return pd.DataFrame({"beta": lagged["beta"], "spread": spread}).dropna()


def rolling_zscore(spread: pd.Series, window: int) -> pd.Series:
    """z_t = (spread_t - mean_{t-window+1..t}) / std_{t-window+1..t}.

    pandas rolling windows END at t — no future bars enter the statistics.
    min_periods defaults to the full window, so the first window-1 values are
    NaN (warm-up) rather than being computed from a shorter, noisier sample.
    """
    mean = spread.rolling(window).mean()
    std = spread.rolling(window).std()
    return (spread - mean) / std


def signal_frame(
    y_close: pd.Series, x_close: pd.Series, kcfg: KalmanConfig, zscore_window: int
) -> pd.DataFrame:
    """Full causal pipeline for one pair: log prices -> Kalman spread -> rolling z.

    Columns: beta, spread, z. The z warm-up rows are kept (z = NaN) so the
    caller can see exactly which bars are not yet tradeable.
    """
    joint = pd.concat({"y": y_close, "x": x_close}, axis=1).dropna()
    frame = pair_spread(np.log(joint["y"]), np.log(joint["x"]), kcfg)
    frame["z"] = rolling_zscore(frame["spread"], zscore_window)
    return frame
