"""Unit tests for the M3 signal layer — synthetic data only, no DB.

The one test that matters most (SPEC.md M3 DoD): prove that no future data
leaks into any rolling statistic — mutate the future, assert the past is
bit-identical, across the FULL pipeline (prices -> Kalman spread -> rolling z
-> position).
"""

import numpy as np
import pandas as pd
import pytest

from src.config import KalmanConfig
from src.pairs.kalman import kalman_hedge
from src.signals.rules import positions_from_z
from src.signals.spread import pair_spread, rolling_zscore, signal_frame

KCFG = KalmanConfig(delta=1e-5, burn_in_bars=200)
WINDOW = 100
N = 3000


def _index(n: int = N) -> pd.DatetimeIndex:
    return pd.date_range("2021-01-01", periods=n, freq="1h", tz="UTC")


def _prices(seed: int) -> tuple[pd.Series, pd.Series]:
    """A cointegrated 'price' pair, as in test_pairs."""
    rng = np.random.default_rng(seed)
    x_log = 4.0 + np.cumsum(rng.normal(0, 0.01, N))
    ou = np.zeros(N)
    for t in range(1, N):
        ou[t] = 0.95 * ou[t - 1] + rng.normal(0, 0.01)
    y_log = 0.5 + 1.5 * x_log + ou
    idx = _index()
    return pd.Series(np.exp(y_log), index=idx), pd.Series(np.exp(x_log), index=idx)


def _z(values: list[float]) -> pd.Series:
    return pd.Series(values, index=_index(len(values)), dtype=float)


# --- look-ahead (the DoD test) ------------------------------------------------


def test_full_pipeline_is_causal_no_lookahead():
    """Mutating every price after bar k must not change any output at bars <= k."""
    y, x = _prices(0)
    k = 2000

    base = signal_frame(y, x, KCFG, WINDOW)
    base["position"] = positions_from_z(base["z"], 2.0, 0.0, 3.0)

    y_mut, x_mut = y.copy(), x.copy()
    y_mut.iloc[k + 1 :] *= 7.0  # violently different future
    x_mut.iloc[k + 1 :] *= 0.2
    mutated = signal_frame(y_mut, x_mut, KCFG, WINDOW)
    mutated["position"] = positions_from_z(mutated["z"], 2.0, 0.0, 3.0)

    cutoff = y.index[k]
    pd.testing.assert_frame_equal(base.loc[:cutoff], mutated.loc[:cutoff])


def test_rolling_zscore_is_causal():
    rng = np.random.default_rng(1)
    s = pd.Series(rng.normal(0, 1, 1000), index=_index(1000))
    base = rolling_zscore(s, WINDOW)
    s_mut = s.copy()
    s_mut.iloc[600:] += 100.0
    pd.testing.assert_series_equal(base.iloc[:600], rolling_zscore(s_mut, WINDOW).iloc[:600])


def test_rolling_zscore_warmup_is_nan_not_short_window():
    s = pd.Series(np.arange(200, dtype=float), index=_index(200))
    z = rolling_zscore(s, WINDOW)
    assert z.iloc[: WINDOW - 1].isna().all()  # no stats from partial windows
    assert z.iloc[WINDOW - 1 :].notna().all()


def test_spread_uses_yesterdays_hedge_ratio():
    """spread_t must be built from the state filtered at t-1, not t."""
    y, x = _prices(2)
    y_log, x_log = np.log(y), np.log(x)
    frame = pair_spread(y_log, x_log, KCFG)
    states = kalman_hedge(y_log, x_log, KCFG)

    t = frame.index[500]
    t_prev = states.index[states.index.get_loc(t) - 1]
    expected = y_log[t] - (states.loc[t_prev, "alpha"] + states.loc[t_prev, "beta"] * x_log[t])
    assert frame.loc[t, "spread"] == pytest.approx(expected)
    assert frame.loc[t, "beta"] == pytest.approx(states.loc[t_prev, "beta"])


# --- trading rules state machine ---------------------------------------------


def test_short_entry_and_mean_exit():
    z = _z([0.0, 1.0, 2.1, 1.5, 0.5, -0.1])
    assert positions_from_z(z, 2.0, 0.0, 3.0).tolist() == [0, 0, -1, -1, -1, 0]


def test_long_entry_and_mean_exit():
    z = _z([0.0, -1.0, -2.1, -1.5, -0.5, 0.1])
    assert positions_from_z(z, 2.0, 0.0, 3.0).tolist() == [0, 0, 1, 1, 1, 0]


def test_stop_out_and_no_instant_reentry():
    # Stop at 3.2, then 2.5 would re-trigger entry without the re-arm guard.
    z = _z([0.0, 2.1, 3.2, 2.5, 2.2, 1.0, 2.2])
    assert positions_from_z(z, 2.0, 0.0, 3.0).tolist() == [0, -1, 0, 0, 0, 0, -1]


def test_jump_straight_past_stop_is_not_entered():
    # From flat, z gaps beyond the stop level: entering would buy a possibly
    # broken equilibrium. Must wait for a reset inside the band.
    z = _z([0.0, 3.5, 2.5, 1.0, 2.2])
    assert positions_from_z(z, 2.0, 0.0, 3.0).tolist() == [0, 0, 0, 0, -1]


def test_warmup_nan_stays_flat_and_disarmed():
    z = _z([np.nan, np.nan, 2.5, 1.0, 2.5])
    # First 2.5 arrives before any |z| < entry bar: not armed -> no entry.
    assert positions_from_z(z, 2.0, 0.0, 3.0).tolist() == [0, 0, 0, 0, -1]


def test_cancel_entries_without_positive_beta():
    from src.signals.rules import cancel_entries_without_positive_beta

    desired = _z([0, -1, -1, 0, 1, 1, 1, 0, -1, -1]).astype(int)
    beta = _z([1, -0.2, 1, 1, 1, -3, 1, 1, 0.5, 0.5])
    out = cancel_entries_without_positive_beta(desired, beta)
    # 1st episode: entry bar has beta=-0.2 -> whole episode cancelled
    assert out.iloc[1:3].tolist() == [0, 0]
    # 2nd episode: entry-bar beta is fine; a mid-trade dip must NOT cut it short
    assert out.iloc[4:7].tolist() == [1, 1, 1]
    # 3rd episode unaffected
    assert out.iloc[8:10].tolist() == [-1, -1]


def test_positions_are_only_valid_values():
    rng = np.random.default_rng(3)
    z = pd.Series(rng.normal(0, 2, 5000), index=_index(5000))
    assert set(positions_from_z(z, 2.0, 0.0, 3.0).unique()) <= {-1, 0, 1}
