"""Unit tests for the M4 backtest engine — synthetic data only, no DB.

The DoD test is reconciliation: the PnL decomposition must add up exactly
(net = gross - fee - slip + funding), and a fully hand-computed scenario checks
every component against numbers worked out on paper.
"""

import numpy as np
import pandas as pd
import pytest

from src.backtest.engine import backtest_pair, held_weights, portfolio_curve
from src.config import BacktestConfig

CFG = BacktestConfig(taker_fee_bps=10.0, slippage_bps=5.0)


def _index(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")


def _series(values, idx=None) -> pd.Series:
    values = list(values)
    return pd.Series(values, index=idx if idx is not None else _index(len(values)), dtype=float)


# --- hand-computed scenario (every number worked out on paper) ----------------


def test_hand_computed_round_trip():
    idx = _index(6)
    close_y = _series([100, 100, 102, 101, 101, 101], idx)
    close_x = _series([50, 50, 50, 50, 50, 50], idx)  # flat x isolates the y leg
    desired = pd.Series([0, 1, 1, 0, 0, 0], index=idx)
    beta = _series([1, 1, 1, 1, 1, 1], idx)
    funding_y = pd.Series([0.01], index=[idx[3]])  # longs pay 1% during bar 3
    funding_x = pd.Series([0.004], index=[idx[2]])  # shorts RECEIVE during bar 2

    out = backtest_pair(close_y, close_x, desired, beta, funding_y, funding_x, CFG)

    # Decided at close of bar 1 -> held during bars 2..3, w = (+0.5, -0.5).
    assert out["w_y"].tolist() == [0, 0, 0.5, 0.5, 0, 0]
    assert out["w_x"].tolist() == [0, 0, -0.5, -0.5, 0, 0]
    # gross: bar2 = 0.5 * 2%, bar3 = 0.5 * (101/102 - 1)
    assert out["gross"].iloc[2] == pytest.approx(0.01)
    assert out["gross"].iloc[3] == pytest.approx(0.5 * (101 / 102 - 1))
    # one unit of gross turnover on entry (bar 2) and on exit (bar 4)
    assert out["turnover"].tolist() == [0, 0, 1.0, 0, 1.0, 0]
    assert out["fee"].iloc[2] == pytest.approx(10 / 1e4)
    assert out["slip"].iloc[4] == pytest.approx(5 / 1e4)
    # funding: short x receives, long y pays
    assert out["funding"].iloc[2] == pytest.approx(-(-0.5) * 0.004)
    assert out["funding"].iloc[3] == pytest.approx(-0.5 * 0.01)
    assert out["funding"].iloc[4] == 0.0  # flat after exit: no funding exposure
    # exact additive decomposition, bar by bar
    pd.testing.assert_series_equal(
        out["net"], out["gross"] - out["fee"] - out["slip"] + out["funding"], check_names=False
    )


# --- reconciliation on random data (the DoD test) -----------------------------


def _random_case(seed: int, n: int = 2000):
    rng = np.random.default_rng(seed)
    idx = _index(n)
    close_y = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=idx)
    close_x = pd.Series(50 * np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=idx)
    # random position runs of 10-50 bars, flat gaps between
    desired = np.zeros(n, dtype=int)
    i = 0
    while i < n - 60:
        i += int(rng.integers(5, 30))
        run = int(rng.integers(10, 50))
        desired[i : i + run] = rng.choice([-1, 1])
        i += run
    beta = pd.Series(1.0 + 0.5 * np.abs(np.sin(np.arange(n) / 300)), index=idx)
    funding_y = pd.Series(rng.normal(0, 1e-4, n // 8), index=idx[:: 8][: n // 8])
    funding_x = pd.Series(rng.normal(0, 1e-4, n // 8), index=idx[:: 8][: n // 8])
    return close_y, close_x, pd.Series(desired, index=idx), beta, funding_y, funding_x


def test_decomposition_reconciles_exactly_on_random_data():
    out = backtest_pair(*_random_case(0), CFG)
    residual = (out["net"] - (out["gross"] - out["fee"] - out["slip"] + out["funding"])).abs()
    assert residual.max() < 1e-15
    # and costs appear exactly when the position changes
    assert ((out["fee"] > 0) == (out["turnover"] > 0)).all()


def test_backtest_is_causal_no_lookahead():
    args = _random_case(1)
    out = backtest_pair(*args, CFG)
    close_y, close_x, desired, beta, fy, fx = args
    k = 1500
    close_y_mut = close_y.copy()
    close_y_mut.iloc[k + 1 :] *= 3.0
    mutated = backtest_pair(close_y_mut, close_x, desired, beta, fy, fx, CFG)
    pd.testing.assert_frame_equal(out.iloc[: k + 1], mutated.iloc[: k + 1])


# --- execution mechanics ------------------------------------------------------


def test_signal_bar_move_is_never_captured():
    """A position decided at bar t's close must NOT earn bar t's own return —
    the classic backtest look-ahead. It earns from bar t+1, after the fill."""
    idx = _index(4)
    close_y = _series([100, 110, 121, 121], idx)  # +10% on the signal bar, +10% after
    close_x = _series([50, 50, 50, 50], idx)
    desired = pd.Series([0, 1, 1, 0], index=idx)  # decided at bar 1's close
    beta = _series([1, 1, 1, 1], idx)
    out = backtest_pair(close_y, close_x, desired, beta, pd.Series(dtype=float),
                        pd.Series(dtype=float), CFG)
    assert out["w_y"].iloc[1] == 0.0  # not yet held during the signal bar
    assert out["gross"].iloc[1] == 0.0  # the signal bar's +10% is not ours
    assert out["gross"].iloc[2] == pytest.approx(0.5 * 0.10)  # the next bar's move is


def test_beta_frozen_at_entry_no_rehedge_turnover():
    idx = _index(8)
    close_y = _series([100] * 8, idx)
    close_x = _series([50] * 8, idx)
    desired = pd.Series([0, 1, 1, 1, 1, 0, 0, 0], index=idx)
    beta = _series([1, 1, 3, 3, 3, 3, 3, 3], idx)  # beta drifts mid-trade
    out = backtest_pair(close_y, close_x, desired, beta, pd.Series(dtype=float),
                        pd.Series(dtype=float), CFG)
    # entry used beta known at decision (bar 1): w = (0.5, -0.5), constant while held
    assert out["w_y"].iloc[2:6].tolist() == [0.5] * 4
    assert (out["turnover"].iloc[3:6] == 0).all()  # no re-hedge churn inside the trade


def test_negative_beta_entry_refused():
    idx = _index(4)
    desired = pd.Series([0, 1, 1, 0], index=idx)
    beta = _series([-0.5, -0.5, -0.5, -0.5], idx)
    with pytest.raises(ValueError, match="beta"):
        held_weights(desired, beta)


def test_portfolio_is_equal_capital_mean():
    idx = _index(5)
    a = pd.DataFrame({c: [0.01] * 5 for c in ["gross", "fee", "slip", "funding", "net"]}, index=idx)
    b = pd.DataFrame({c: [0.03] * 5 for c in ["gross", "fee", "slip", "funding", "net"]},
                     index=idx[2:].append(_index(7)[5:7]))  # partly disjoint index
    port = portfolio_curve({"a": a, "b": b})
    assert port.loc[idx[0], "net"] == pytest.approx(0.005)  # only pair a active
    assert port.loc[idx[2], "net"] == pytest.approx(0.02)  # both active
