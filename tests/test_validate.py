"""Unit tests for the M5 validation layer — synthetic data only, no DB.

Focus: the walk-forward's structural look-ahead guards (tuning windows always
end strictly before the slice they trade; folds never overlap) and the grid
machinery's slicing semantics.
"""

import numpy as np
import pandas as pd
import pytest

from src.config import BacktestConfig, GridConfig
from src.validate.grid import ParamSet, param_grid, run_params, spread_cache
from src.validate.walkforward import make_folds

BT = BacktestConfig(taker_fee_bps=5.0, slippage_bps=2.0)
GRID = GridConfig(
    kalman_delta=[1e-5, 1e-7],
    entry_z=[2.0],
    exit_z=[0.0],
    stop_z=[3.0],
    zscore_window_bars=[100],
)


def _index(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2021-01-01", periods=n, freq="1h", tz="UTC")


def _panel(seed: int, n: int = 3000) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    x_log = 4.0 + np.cumsum(rng.normal(0, 0.01, n))
    ou = np.zeros(n)
    for t in range(1, n):
        ou[t] = 0.95 * ou[t - 1] + rng.normal(0, 0.01)
    y_log = 0.5 + 1.5 * x_log + ou
    return pd.DataFrame({"AAA": np.exp(y_log), "BBB": np.exp(x_log)}, index=_index(n))


# --- fold structure (the structural look-ahead guard) -------------------------


def test_folds_tune_strictly_before_trade():
    idx = _index(1000)
    folds = make_folds(idx, train_bars=400, test_bars=100)
    for f in folds:
        assert f.train_start < f.test_start <= f.test_end


def test_fold_test_slices_tile_without_overlap():
    idx = _index(1000)
    folds = make_folds(idx, train_bars=400, test_bars=100)
    # consecutive folds: each test slice starts exactly where the previous ended
    for prev, nxt in zip(folds, folds[1:]):
        assert nxt.test_start == prev.test_end
    assert folds[0].test_start == idx[400]
    assert folds[-1].test_end == idx[-1] + (idx[1] - idx[0])  # last (short) fold reaches the end


def test_fold_count_covers_all_bars_after_first_train():
    idx = _index(1000)
    folds = make_folds(idx, train_bars=400, test_bars=250)
    # 600 bars to trade -> folds of 250, 250, 100
    assert len(folds) == 3


# --- grid machinery -----------------------------------------------------------


def test_param_grid_is_full_cartesian_product():
    grid = GridConfig(kalman_delta=[1e-5, 1e-7, 1e-8], entry_z=[1.5, 2.0, 2.5],
                      exit_z=[0.0, 0.5], stop_z=[3.0, 4.0], zscore_window_bars=[720, 1440])
    assert len(param_grid(grid)) == 72


def test_run_params_slice_counts_only_requested_bars():
    panel = _panel(0)
    book = [("AAA", "BBB")]
    cache = spread_cache(panel, book, [1e-5], burn_in_bars=200)
    params = ParamSet(1e-5, 100, 2.0, 0.0, 3.0)
    full = run_params(panel, book, params, cache, {}, BT)["AAA ~ BBB"]
    start, end = panel.index[1500], panel.index[2500]
    sliced = run_params(panel, book, params, cache, {}, BT, start=start, end=end)["AAA ~ BBB"]
    assert sliced.index.min() >= start and sliced.index.max() < end
    # without fresh_entries_only the sliced rows are identical to the full run's
    pd.testing.assert_frame_equal(sliced, full.loc[start : end - pd.Timedelta(hours=1)])


def test_fresh_entries_only_starts_flat_and_ends_flat():
    panel = _panel(1)
    book = [("AAA", "BBB")]
    cache = spread_cache(panel, book, [1e-5], burn_in_bars=200)
    params = ParamSet(1e-5, 100, 1.0, 0.0, 4.0)  # low entry -> plenty of trades
    start, end = panel.index[1500], panel.index[2500]
    out = run_params(panel, book, params, cache, {}, BT,
                     start=start, end=end, fresh_entries_only=True)["AAA ~ BBB"]
    assert out["w_y"].iloc[0] == 0.0  # no position inherited from before the slice
    assert out["w_y"].iloc[-1] == 0.0  # forced flat: exit cost charged inside the slice
    assert (out["w_y"] != 0).any()  # ...but it did actually trade


def test_spread_cache_train_values_independent_of_later_bars():
    """The reuse-one-computation trick is only valid if causality holds."""
    panel = _panel(2)
    short = panel.iloc[:2000]
    c_full = spread_cache(panel, [("AAA", "BBB")], [1e-5], 200)[("AAA", "BBB", 1e-5)]
    c_short = spread_cache(short, [("AAA", "BBB")], [1e-5], 200)[("AAA", "BBB", 1e-5)]
    pd.testing.assert_frame_equal(c_full.loc[c_short.index], c_short)


def test_run_params_rejects_missing_cache_entry():
    panel = _panel(3)
    cache = spread_cache(panel, [("AAA", "BBB")], [1e-5], 200)
    with pytest.raises(KeyError):
        run_params(panel, [("AAA", "BBB")], ParamSet(9e-9, 100, 2.0, 0.0, 3.0), cache, {}, BT)
