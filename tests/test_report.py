"""Unit tests for the M7 robustness layer — synthetic data only, no DB."""

import numpy as np
import pandas as pd
import pytest

from src.backtest.engine import backtest_pair
from src.config import BacktestConfig
from src.report.robustness import leave_one_pair_out, regime_slices, rolling_eg


def _index(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")


def test_cost_stress_is_linear_in_the_multiplier():
    """Signals never see costs, so trades are identical and the multiplier acts
    linearly on the fee+slip components only."""
    rng = np.random.default_rng(0)
    idx = _index(500)
    close_y = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 500))), index=idx)
    close_x = pd.Series(50 * np.exp(np.cumsum(rng.normal(0, 0.01, 500))), index=idx)
    desired = pd.Series(([0] * 50 + [1] * 30 + [0] * 20) * 5, index=idx)
    beta = pd.Series(1.0, index=idx)
    none = pd.Series(dtype=float)

    base = backtest_pair(close_y, close_x, desired, beta, none, none,
                         BacktestConfig(taker_fee_bps=5.0, slippage_bps=2.0))
    doubled = backtest_pair(close_y, close_x, desired, beta, none, none,
                            BacktestConfig(taker_fee_bps=10.0, slippage_bps=4.0))
    assert doubled["gross"].sum() == pytest.approx(base["gross"].sum())
    assert doubled["net"].sum() == pytest.approx(
        base["gross"].sum() - 2 * (base["fee"] + base["slip"]).sum() + base["funding"].sum()
    )


def test_regime_slices_partition_direction_and_vol():
    rng = np.random.default_rng(1)
    idx = _index(2000)
    net = pd.Series(rng.normal(0, 1e-3, 2000), index=idx)
    btc = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 2000))), index=idx)
    out = regime_slices(net, btc, window=100, interval="1h").set_index("regime")
    labeled = 2000 - 100  # first `window` bars have no trailing label
    assert out.loc["BTC trending up", "bars"] + out.loc["BTC trending down", "bars"] == labeled
    assert out.loc["BTC trending up", "net"] + out.loc["BTC trending down", "net"] == (
        pytest.approx(float(net.iloc[100:].sum()))
    )
    # vol slices partition ALL bars with a defined trailing vol (window bars in)
    assert out.loc["high vol", "bars"] + out.loc["low vol", "bars"] == 2000 - 100


def test_leave_one_pair_out_drops_exactly_one():
    idx = _index(10)
    frame = pd.DataFrame(
        {"net": 0.01, "gross": 0.01, "fee": 0.0, "slip": 0.0, "funding": 0.0, "borrow": 0.0},
        index=idx,
    )
    results = {"a": frame, "b": frame * 3}
    out = leave_one_pair_out(results, idx[0], "1h").set_index("without")
    assert out.loc["a", "net"] == pytest.approx(0.03 * 10)  # only b remains, full weight
    assert out.loc["b", "net"] == pytest.approx(0.01 * 10)


def test_rolling_eg_window_count_and_detection():
    rng = np.random.default_rng(2)
    n, window, step = 1300, 1000, 100
    x_log = 4.0 + np.cumsum(rng.normal(0, 0.01, n))
    ou = np.zeros(n)
    for t in range(1, n):
        ou[t] = 0.9 * ou[t - 1] + rng.normal(0, 0.01)
    panel = pd.DataFrame(
        {"AAA": np.exp(0.5 + 1.5 * x_log + ou), "BBB": np.exp(x_log)}, index=_index(n)
    )
    out = rolling_eg(panel, [("AAA", "BBB")], window, step)
    assert len(out) == (n - window) // step + 1
    assert (out["eg_p_max"] < 0.05).all()  # genuinely cointegrated in every window
