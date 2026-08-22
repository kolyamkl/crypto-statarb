"""Unit tests for the M2 pair-selection layer — synthetic data only, no DB.

Focus: (1) the statistics recover known ground truth on simulated series, and
(2) the Kalman filter is strictly causal — the look-ahead test the working
agreement demands for anything with a fit.
"""

import numpy as np
import pandas as pd
import pytest

from src.config import KalmanConfig, PairsConfig
from src.pairs.cointegration import half_life, ols_hedge, screen_pair
from src.pairs.kalman import kalman_hedge

CFG = PairsConfig(
    price_field="close",
    use_log_prices=True,
    min_overlap_bars=1000,
    adf_alpha=0.05,
    half_life_min_bars=2,
    half_life_max_bars=720,
    kalman=KalmanConfig(delta=1e-5, burn_in_bars=200),
)

N = 4000


def _index(n: int = N) -> pd.DatetimeIndex:
    return pd.date_range("2021-01-01", periods=n, freq="1h", tz="UTC")


def _random_walk(rng: np.random.Generator, n: int = N, start: float = 4.0) -> np.ndarray:
    """A log-price-like random walk (non-stationary by construction)."""
    return start + np.cumsum(rng.normal(0, 0.01, n))


def _ou(rng: np.random.Generator, phi: float, sigma: float, n: int = N) -> np.ndarray:
    """Stationary AR(1) noise with known persistence phi."""
    out = np.zeros(n)
    for t in range(1, n):
        out[t] = phi * out[t - 1] + rng.normal(0, sigma)
    return out


def _cointegrated_pair(
    rng: np.random.Generator, beta: float = 1.5, phi: float = 0.95
) -> tuple[pd.DataFrame, float]:
    """Two 'price' series sharing a random-walk trend; true spread is AR(1) with phi."""
    x_log = _random_walk(rng)
    y_log = 0.5 + beta * x_log + _ou(rng, phi, 0.01)
    panel = pd.DataFrame({"AAA": np.exp(y_log), "BBB": np.exp(x_log)}, index=_index())
    true_half_life = -np.log(2) / np.log(phi)
    return panel, true_half_life


# --- cointegration screen -----------------------------------------------------


def test_screen_detects_cointegrated_pair_and_recovers_beta():
    panel, true_hl = _cointegrated_pair(np.random.default_rng(0))
    r = screen_pair(panel, "AAA", "BBB", CFG)
    assert r is not None and r.passed
    assert r.eg_p_max < 0.01
    assert r.beta == pytest.approx(1.5, abs=0.1)
    assert r.half_life_bars == pytest.approx(true_hl, rel=0.5)


def test_screen_rejects_independent_random_walks():
    rng = np.random.default_rng(1)
    panel = pd.DataFrame(
        {"AAA": np.exp(_random_walk(rng)), "BBB": np.exp(_random_walk(rng))}, index=_index()
    )
    r = screen_pair(panel, "AAA", "BBB", CFG)
    assert r is not None and not r.passed
    # Independent walks are the EG null; expect a clearly non-significant p-value.
    assert r.eg_p_max > 0.05


def test_screen_skips_pair_with_short_overlap():
    panel, _ = _cointegrated_pair(np.random.default_rng(2))
    panel.iloc[: N - 500, 0] = np.nan  # only 500 joint bars < min_overlap_bars
    assert screen_pair(panel, "AAA", "BBB", CFG) is None


def test_half_life_recovers_known_ar1_persistence():
    spread = pd.Series(_ou(np.random.default_rng(3), 0.97, 0.01, 20_000), index=_index(20_000))
    assert half_life(spread) == pytest.approx(-np.log(2) / np.log(0.97), rel=0.25)


def test_half_life_is_none_for_explosive_series():
    # phi > 1 (explosive) must map to None. Note a plain random walk is NOT a
    # good probe here: finite-sample AR bias makes its phi estimate land just
    # below 1, giving a huge finite half-life — which the screen's
    # [min, max] half-life bounds are there to reject.
    rng = np.random.default_rng(4)
    s = np.zeros(1000)
    for t in range(1, 1000):
        s[t] = 1.01 * s[t - 1] + rng.normal(0, 0.1)
    assert half_life(pd.Series(s)) is None


def test_ols_hedge_recovers_exact_linear_relation():
    x = pd.Series(np.linspace(1, 10, 100))
    alpha, beta, spread = ols_hedge(2.0 + 3.0 * x, x)
    assert alpha == pytest.approx(2.0) and beta == pytest.approx(3.0)
    assert spread.abs().max() == pytest.approx(0.0, abs=1e-9)


# --- Kalman filter ------------------------------------------------------------


def _kalman_inputs(rng: np.random.Generator) -> tuple[pd.Series, pd.Series]:
    panel, _ = _cointegrated_pair(rng)
    return np.log(panel["AAA"]), np.log(panel["BBB"])


def test_kalman_is_causal_no_lookahead():
    """THE look-ahead test: perturbing the future must not change the past.

    If any future observation influenced the filtered estimate at time t, the
    hedge ratio would embed information unavailable in live trading.
    """
    y, x = _kalman_inputs(np.random.default_rng(5))
    k = 3000
    base = kalman_hedge(y, x, CFG.kalman)

    y_mut, x_mut = y.copy(), x.copy()
    y_mut.iloc[k:] += 10.0  # violently different future
    x_mut.iloc[k:] -= 5.0
    mutated = kalman_hedge(y_mut, x_mut, CFG.kalman)

    pd.testing.assert_frame_equal(base.iloc[: k - CFG.kalman.burn_in_bars],
                                  mutated.iloc[: k - CFG.kalman.burn_in_bars])


def test_kalman_converges_to_constant_beta():
    y, x = _kalman_inputs(np.random.default_rng(6))
    out = kalman_hedge(y, x, CFG.kalman)
    assert out["beta"].iloc[-500:].mean() == pytest.approx(1.5, abs=0.1)


def test_kalman_tracks_a_beta_regime_change():
    rng = np.random.default_rng(7)
    x_log = _random_walk(rng)
    beta_path = np.where(np.arange(N) < N // 2, 1.0, 2.0)  # jump at midpoint
    y_log = 0.5 + beta_path * x_log + _ou(rng, 0.9, 0.005)
    y = pd.Series(y_log, index=_index())
    x = pd.Series(x_log, index=_index())

    out = kalman_hedge(y, x, CFG.kalman)
    assert out["beta"].iloc[N // 2 - CFG.kalman.burn_in_bars - 1] == pytest.approx(1.0, abs=0.15)
    assert out["beta"].iloc[-1] == pytest.approx(2.0, abs=0.2)


def test_kalman_output_starts_after_burn_in():
    y, x = _kalman_inputs(np.random.default_rng(8))
    out = kalman_hedge(y, x, CFG.kalman)
    assert len(out) == len(y) - CFG.kalman.burn_in_bars
    assert (out.index == y.index[CFG.kalman.burn_in_bars :]).all()


def test_kalman_rejects_too_short_series():
    y, x = _kalman_inputs(np.random.default_rng(9))
    with pytest.raises(ValueError):
        kalman_hedge(y.iloc[:100], x.iloc[:100], CFG.kalman)  # shorter than burn-in
