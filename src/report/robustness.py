"""M7 robustness stresses on the frozen M5 configuration.

Everything here is DIAGNOSTIC, run after all tuning is closed: cost multipliers,
parameter-neighborhood sensitivity on the untouched test window, market-regime
slicing, leave-one-pair-out, and rolling cointegration re-checks. None of it
feeds back into parameter choices — it exists to measure how fragile the M5/M6
numbers are, and is disclosed as post-hoc analysis.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from src.config import BacktestConfig, Config
from src.backtest.engine import portfolio_curve
from src.metrics.core import ann_sharpe
from src.pairs.cointegration import engle_granger_p
from src.validate.grid import ParamSet, param_grid, run_params


def cost_stress(
    panel: pd.DataFrame,
    book: list[tuple[str, str]],
    params: ParamSet,
    cache: dict,
    funding: dict[str, pd.Series],
    cfg: Config,
    cutoff: pd.Timestamp,
) -> pd.DataFrame:
    """Test-window net/Sharpe under scaled fee+slippage. Signals never see costs,
    so trades are identical across rows and the damage is pure cost arithmetic."""
    rows = []
    for m in cfg.robustness.cost_multipliers:
        bt = BacktestConfig(
            taker_fee_bps=cfg.backtest.taker_fee_bps * m,
            slippage_bps=cfg.backtest.slippage_bps * m,
        )
        results = run_params(panel, book, params, cache, funding, bt)
        port = portfolio_curve(results)
        test = port.loc[port.index >= cutoff]
        rows.append(
            {
                "cost_multiplier": m,
                "net": float(test["net"].sum()),
                "sharpe": ann_sharpe(test["net"], cfg.data.interval),
            }
        )
    return pd.DataFrame(rows)


def grid_train_vs_test(
    panel: pd.DataFrame,
    book: list[tuple[str, str]],
    cache: dict,
    funding: dict[str, pd.Series],
    cfg: Config,
    cutoff: pd.Timestamp,
) -> tuple[pd.DataFrame, float]:
    """Every grid config evaluated on BOTH windows. The Spearman rank correlation
    between train and test Sharpe measures how informative the tuning ranking
    was: near zero means the grid choice was closer to luck than skill."""
    rows = []
    for params in param_grid(cfg.validation.grid):
        results = run_params(panel, book, params, cache, funding, cfg.backtest)
        port = portfolio_curve(results)
        train = port.loc[port.index < cutoff]
        test = port.loc[port.index >= cutoff]
        rows.append(
            {
                **params.__dict__,
                "train_sharpe": ann_sharpe(train["net"], cfg.data.interval),
                "test_sharpe": ann_sharpe(test["net"], cfg.data.interval),
                "test_net": float(test["net"].sum()),
            }
        )
    table = pd.DataFrame(rows)
    rank_corr = float(spearmanr(table["train_sharpe"], table["test_sharpe"]).statistic)
    return table, rank_corr


def regime_slices(
    strategy_net: pd.Series, btc_close: pd.Series, window: int, interval: str
) -> pd.DataFrame:
    """Strategy PnL sliced by TRAILING BTC regime labels (causal by construction,
    though used purely descriptively): direction = sign of the trailing 30d BTC
    return; volatility = trailing 30d realized vol above/below its full-sample
    median. A market-neutral book should not care about direction — this checks."""
    btc = btc_close.reindex(strategy_net.index)
    trailing_ret = btc.pct_change(window)
    trailing_vol = btc.pct_change().rolling(window).std()
    labels = {
        "BTC trending up": trailing_ret > 0,
        "BTC trending down": trailing_ret <= 0,
        "high vol": trailing_vol > trailing_vol.median(),
        "low vol": trailing_vol <= trailing_vol.median(),
    }
    rows = []
    for name, mask in labels.items():
        sliced = strategy_net[mask.fillna(False)]
        rows.append(
            {
                "regime": name,
                "bars": len(sliced),
                "net": float(sliced.sum()),
                "sharpe": ann_sharpe(sliced, interval),
            }
        )
    return pd.DataFrame(rows)


def leave_one_pair_out(
    results: dict[str, pd.DataFrame], cutoff: pd.Timestamp, interval: str
) -> pd.DataFrame:
    """Test-window portfolio with each pair removed — how much of the result is
    one pair's doing. Remaining pairs are re-weighted to equal capital."""
    rows = []
    for dropped in results:
        rest = {k: v for k, v in results.items() if k != dropped}
        port = portfolio_curve(rest)
        test = port.loc[port.index >= cutoff]
        rows.append(
            {
                "without": dropped,
                "net": float(test["net"].sum()),
                "sharpe": ann_sharpe(test["net"], interval),
            }
        )
    return pd.DataFrame(rows)


def rolling_eg(
    panel: pd.DataFrame,
    book: list[tuple[str, str]],
    window: int,
    step: int,
) -> pd.DataFrame:
    """Worst-direction Engle-Granger p-value on rolling windows per book pair —
    did the cointegration that selected these pairs persist? Long format:
    (pair, window_end, eg_p_max)."""
    rows = []
    for leg_y, leg_x in book:
        joint = panel[[leg_y, leg_x]].dropna()
        y_log, x_log = np.log(joint[leg_y]), np.log(joint[leg_x])
        for start in range(0, len(joint) - window + 1, step):
            y_win = y_log.iloc[start : start + window]
            x_win = x_log.iloc[start : start + window]
            p = max(engle_granger_p(y_win, x_win), engle_granger_p(x_win, y_win))
            rows.append(
                {
                    "pair": f"{leg_y} ~ {leg_x}",
                    "window_end": joint.index[start + window - 1],
                    "eg_p_max": p,
                }
            )
    return pd.DataFrame(rows)
