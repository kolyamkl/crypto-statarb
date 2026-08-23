"""Unit tests for the M6 metrics layer — hand-checked values on crafted frames."""

import numpy as np
import pandas as pd
import pytest

from src.metrics.core import (
    ann_sharpe,
    ann_sortino,
    ann_turnover,
    avg_holding_bars,
    full_summary,
    hit_rate,
    max_drawdown,
    trade_pnls,
)


def _frame(net, w_y, turnover=None) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(net), freq="1h", tz="UTC")
    df = pd.DataFrame(
        {"net": net, "gross": net, "fee": 0.0, "slip": 0.0, "funding": 0.0, "w_y": w_y},
        index=idx,
    )
    if turnover is not None:
        df["turnover"] = turnover
    return df


def test_sharpe_and_sortino_hand_checked():
    pnl = pd.Series([0.02, -0.01, 0.02, -0.01])
    expected_sharpe = pnl.mean() / pnl.std() * np.sqrt(365 * 24)
    assert ann_sharpe(pnl, "1h") == pytest.approx(expected_sharpe)
    downside_rms = np.sqrt((0.01**2 + 0.01**2) / 4)
    assert ann_sortino(pnl, "1h") == pytest.approx(pnl.mean() / downside_rms * np.sqrt(365 * 24))


def test_sortino_nan_when_no_losses():
    assert np.isnan(ann_sortino(pd.Series([0.01, 0.02]), "1h"))


def test_max_drawdown_hand_checked():
    # equity path: 0.10, 0.05, 0.00, 0.20 -> deepest fall from the 0.10 peak is -0.10
    assert max_drawdown(pd.Series([0.10, -0.05, -0.05, 0.20])) == pytest.approx(-0.10)


def test_trade_pnls_include_exit_cost_bar():
    # Episode 1: bars 1-2 held, bar 3 flat but carries the exit cost (-0.001).
    # Episode 2: bars 5-6 held, runs to the end (no exit bar exists).
    net = [0.0, 0.01, 0.02, -0.001, 0.0, -0.005, -0.005]
    w_y = [0.0, 0.5, 0.5, 0.0, 0.0, 0.5, 0.5]
    pnls = trade_pnls(_frame(net, w_y))
    assert pnls == [pytest.approx(0.029), pytest.approx(-0.010)]
    assert hit_rate(_frame(net, w_y)) == pytest.approx(0.5)


def test_avg_holding_and_turnover():
    net = [0.0] * 8
    w_y = [0, 0.5, 0.5, 0.5, 0, 0.5, 0, 0]  # runs of 3 and 1 -> mean 2
    turnover = [0, 1.0, 0, 0, 1.0, 1.0, 1.0, 0]
    f = _frame(net, w_y, turnover)
    assert avg_holding_bars(f) == pytest.approx(2.0)
    years = 8 / (365 * 24)
    assert ann_turnover(f, "1h") == pytest.approx(4.0 / years)


def test_full_summary_has_trade_stats_only_with_weights():
    with_w = full_summary(_frame([0.01, -0.01], [0.5, 0.5], [1.0, 0.0]), "1h")
    assert {"hit_rate", "avg_hold_bars", "ann_turnover", "sortino"} <= set(with_w)
    bench = _frame([0.01, -0.01], [0.5, 0.5]).drop(columns=["w_y"])
    without_w = full_summary(bench, "1h")
    assert "hit_rate" not in without_w and "sortino" in without_w
