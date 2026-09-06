"""M10 unit tests: the equity engine variant (next-open fills, borrow fee), the
config switch, and the calendar-aware ingestion helpers — synthetic data, no DB,
no network. The crypto path must stay bit-identical: proven here by running the
same inputs through both old-shaped and new-shaped configs.
"""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.backtest.engine import backtest_pair
from src.config import BacktestConfig, load_config
from src.ingest.equities import calendar_gaps, clean_daily_frame, union_calendar

CRYPTO_CFG = BacktestConfig(taker_fee_bps=10.0, slippage_bps=5.0)
# 252 bps/yr over 252 bars/yr = exactly 1bp per held bar — easy paper arithmetic.
EQUITY_CFG = BacktestConfig(
    taker_fee_bps=0.0,
    slippage_bps=5.0,
    borrow_fee_bps_per_year=252.0,
    borrow_rate_per_bar=252.0 / 1e4 / 252,
    fill_at_next_open=True,
)

NO_FUNDING = pd.Series(dtype=float)


def _index(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2024-01-01", periods=n, freq="1D", tz="UTC")


def _series(values, idx) -> pd.Series:
    return pd.Series(list(values), index=idx, dtype=float)


# --- next-open fill mechanics -------------------------------------------------


def test_next_open_fill_hand_computed():
    """Overnight gap goes to the position carried into it; the fresh fill earns
    only open -> close. Every number below is worked out on paper."""
    idx = _index(5)
    open_y = _series([100, 104, 110, 108, 107], idx)  # gaps vs prior closes
    close_y = _series([102, 106, 109, 107, 107], idx)
    open_x = _series([50, 50, 50, 50, 50], idx)  # flat x isolates the y leg
    close_x = _series([50, 50, 50, 50, 50], idx)
    desired = pd.Series([0, 1, 1, 0, 0], index=idx)  # decided at bar 1's close
    beta = _series([1] * 5, idx)

    out = backtest_pair(close_y, close_x, desired, beta, NO_FUNDING, NO_FUNDING,
                        EQUITY_CFG, open_y=open_y, open_x=open_x)

    # Filled at bar 2's open: intraday segment only, w_y = 0.5.
    assert out["w_y"].iloc[2] == pytest.approx(0.5)
    assert out["gross"].iloc[2] == pytest.approx(0.5 * (109 / 110 - 1))
    # Bar 3 still held (exit decided at ITS close): overnight 109->108 + intraday 108->107.
    assert out["w_y"].iloc[3] == pytest.approx(0.5)
    assert out["gross"].iloc[3] == pytest.approx(0.5 * (108 / 109 - 1) + 0.5 * (107 / 108 - 1))
    # Bar 4: the exit fills at the open, so only the overnight segment (107->107 = 0) is ours.
    assert out["w_y"].iloc[4] == 0.0
    assert out["gross"].iloc[4] == pytest.approx(0.5 * (107 / 107 - 1))
    # Bar 1 (the signal bar) is never ours.
    assert out["gross"].iloc[1] == 0.0


def test_next_open_collapses_to_close_to_close_when_no_gap():
    """With open_t == close_{t-1} (a 24/7 market) the two-segment formula must
    reproduce the crypto engine's numbers exactly."""
    rng = np.random.default_rng(7)
    n = 400
    idx = _index(n)
    close_y = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=idx)
    close_x = pd.Series(50 * np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=idx)
    open_y = close_y.shift(1).fillna(close_y.iloc[0])  # no overnight gap
    open_x = close_x.shift(1).fillna(close_x.iloc[0])
    desired = pd.Series(([0] * 5 + [1] * 10 + [0] * 3 + [-1] * 7) * 16, index=idx)
    beta = _series([1.2] * n, idx)

    gapless_cfg = BacktestConfig(taker_fee_bps=0.0, slippage_bps=5.0, fill_at_next_open=True)
    crypto_like = BacktestConfig(taker_fee_bps=0.0, slippage_bps=5.0)
    a = backtest_pair(close_y, close_x, desired, beta, NO_FUNDING, NO_FUNDING,
                      gapless_cfg, open_y=open_y, open_x=open_x)
    b = backtest_pair(close_y, close_x, desired, beta, NO_FUNDING, NO_FUNDING, crypto_like)
    pd.testing.assert_series_equal(a["gross"], b["gross"])
    pd.testing.assert_series_equal(a["net"], b["net"])


def test_next_open_fill_is_causal_no_lookahead():
    """Mutate everything after bar k (closes AND opens) — results at <= k must be
    bit-identical. The rolling-window discipline, applied to the new fill path."""
    rng = np.random.default_rng(3)
    n = 300
    idx = _index(n)
    close_y = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=idx)
    close_x = pd.Series(50 * np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=idx)
    open_y = close_y.shift(1).fillna(100.0) * (1 + rng.normal(0, 0.003, n))  # real gaps
    open_x = close_x.shift(1).fillna(50.0) * (1 + rng.normal(0, 0.003, n))
    desired = pd.Series(([0] * 4 + [1] * 8 + [0] * 2 + [-1] * 6) * 15, index=idx)
    beta = _series([1.0] * n, idx)

    out = backtest_pair(close_y, close_x, desired, beta, NO_FUNDING, NO_FUNDING,
                        EQUITY_CFG, open_y=open_y, open_x=open_x)
    k = 200
    close_y_mut, open_y_mut = close_y.copy(), open_y.copy()
    close_y_mut.iloc[k + 1:] *= 5.0
    open_y_mut.iloc[k + 1:] *= 5.0
    mutated = backtest_pair(close_y_mut, close_x, desired, beta, NO_FUNDING, NO_FUNDING,
                            EQUITY_CFG, open_y=open_y_mut, open_x=open_x)
    pd.testing.assert_frame_equal(out.iloc[: k + 1], mutated.iloc[: k + 1])


def test_fill_at_next_open_requires_opens():
    idx = _index(3)
    s = _series([1, 1, 1], idx)
    with pytest.raises(ValueError, match="open"):
        backtest_pair(s, s, pd.Series([0, 0, 0], index=idx), s, NO_FUNDING, NO_FUNDING,
                      EQUITY_CFG)


# --- borrow accrual -----------------------------------------------------------


def test_borrow_accrues_on_short_leg_only():
    """252 bps/yr at 252 bars/yr = 1bp per held bar on the SHORT leg's notional.
    Long spread with beta=1: short leg is x with |w_x| = 0.5 -> 0.5bp per bar."""
    idx = _index(6)
    flat = _series([100] * 6, idx)
    flat_x = _series([50] * 6, idx)
    desired = pd.Series([0, 1, 1, 1, 0, 0], index=idx)
    beta = _series([1] * 6, idx)
    out = backtest_pair(flat, flat_x, desired, beta, NO_FUNDING, NO_FUNDING,
                        EQUITY_CFG, open_y=flat, open_x=flat_x)
    held = [2, 3, 4]  # bars where w != 0 (desired shifted one bar)
    for i in range(6):
        expected = 0.5 * 1e-4 if i in held else 0.0
        assert out["borrow"].iloc[i] == pytest.approx(expected), f"bar {i}"
    # decomposition stays exactly additive with the borrow term
    residual = (out["net"] - (out["gross"] - out["fee"] - out["slip"]
                              + out["funding"] - out["borrow"])).abs()
    assert residual.max() < 1e-15


def test_crypto_engine_unchanged_borrow_zero():
    """The v1 crypto path must be bit-identical: borrow column exists but is 0
    and net matches the old formula exactly."""
    rng = np.random.default_rng(11)
    n = 500
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    close_y = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=idx)
    close_x = pd.Series(50 * np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=idx)
    desired = pd.Series(([0] * 5 + [1] * 12 + [0] * 3) * 25, index=idx)
    beta = pd.Series(1.1, index=idx)
    out = backtest_pair(close_y, close_x, desired, beta, NO_FUNDING, NO_FUNDING, CRYPTO_CFG)
    assert (out["borrow"] == 0).all()
    pd.testing.assert_series_equal(
        out["net"], out["gross"] - out["fee"] - out["slip"] + out["funding"],
        check_names=False,
    )


# --- config switch ------------------------------------------------------------


def test_equity_config_loads_and_is_frozen_as_declared(monkeypatch):
    monkeypatch.setenv("STATARB_CONFIG", "config_equities.yaml")
    cfg = load_config()
    assert cfg.data.market == "equity" and cfg.data.exchange == "yfinance"
    assert len(cfg.data.universe) == 24 and cfg.data.aux == ["SPY"]
    assert cfg.validation.train_end == "2024-12-31"  # same split as crypto
    # same 72-config search space, z windows rescaled to trading days
    g = cfg.validation.grid
    assert (len(g.kalman_delta) * len(g.entry_z) * len(g.exit_z)
            * len(g.stop_z) * len(g.zscore_window_bars)) == 72
    assert g.zscore_window_bars == [21, 42]
    assert cfg.backtest.fill_at_next_open and cfg.backtest.borrow_fee_bps_per_year == 30.0
    assert cfg.backtest.borrow_rate_per_bar == pytest.approx(30.0 / 1e4 / 252)
    assert cfg.robustness.factor_symbol == "SPY" and cfg.benchmark_symbols == ["SPY"]
    assert cfg.reports_subdir == "m10"
    assert cfg.signals.book == []  # filled only by the pre-declared post-screen rule


def test_crypto_config_defaults_unchanged(monkeypatch):
    monkeypatch.delenv("STATARB_CONFIG", raising=False)
    cfg = load_config()
    assert cfg.data.market == "perp"
    assert cfg.backtest.borrow_fee_bps_per_year == 0.0
    assert not cfg.backtest.fill_at_next_open
    assert cfg.robustness.factor_symbol == "BTCUSDT"
    assert cfg.benchmark_symbols == ["BTCUSDT", "ETHUSDT"]
    assert cfg.reports_subdir == ""


# --- calendar-aware ingestion helpers ----------------------------------------


def test_calendar_gaps_split_on_present_days():
    calendar = [date(2024, 1, d) for d in (2, 3, 4, 5, 8, 9, 10, 11, 12)]
    # symbol missing Jan 4 and Jan 9-10; present either side
    have = [date(2024, 1, d) for d in (2, 3, 5, 8, 11, 12)]
    gaps = calendar_gaps(have, calendar)
    assert gaps == [
        (date(2024, 1, 4), date(2024, 1, 4), 1),
        (date(2024, 1, 9), date(2024, 1, 10), 2),
    ]


def test_calendar_gaps_ignore_edges_and_weekends():
    # A weekend (Jan 6-7) is not in the calendar, so it is never a gap; dates
    # before the symbol's first bar are coverage, not gaps.
    calendar = [date(2024, 1, d) for d in (2, 3, 4, 5, 8, 9)]
    have = [date(2024, 1, d) for d in (4, 5, 8, 9)]  # starts later than calendar
    assert calendar_gaps(have, calendar) == []


def test_clean_daily_frame_drops_forming_bar_and_clips_window():
    idx = pd.to_datetime(["2020-12-31", "2024-01-02", "2024-01-03", "2024-01-04"])
    df = pd.DataFrame(
        {"Open": [1, 1, np.nan, 1], "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 0.0},
        index=idx,
    )
    out = clean_daily_frame(
        df, start=date(2021, 1, 1), end=date(2026, 7, 11), today=date(2024, 1, 4)
    )
    # 2020 row clipped, NaN row dropped, and "today" (the forming bar) excluded
    assert [d.date() for d in out.index] == [date(2024, 1, 2)]


def test_union_calendar():
    a = pd.DataFrame(index=pd.to_datetime(["2024-01-02", "2024-01-03"]))
    b = pd.DataFrame(index=pd.to_datetime(["2024-01-03", "2024-01-04"]))
    assert union_calendar({"a": a, "b": b}) == [
        date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)
    ]
