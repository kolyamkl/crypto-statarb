"""M5 grid search over the pre-declared parameter grid — TRAINING data only.

Anti-snooping discipline: the grid in config.yaml is the entire search space
(72 configs); selection is by portfolio net Sharpe with a minimum-trades floor,
and the full ranked table is written to the report so the reader can see how
sensitive the choice was — one good cell in a sea of bad ones is luck, not edge.

Efficiency note: the Kalman spread depends only on (pair, delta), so it is
computed once per (pair, delta) over the evaluation span and reused across all
trading-rule combinations. Causality (unit-tested) guarantees that values on
the training slice are identical whether or not later bars were appended.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product

import numpy as np
import pandas as pd

from src.config import BacktestConfig, GridConfig, KalmanConfig
from src.backtest.engine import backtest_pair, portfolio_curve
from src.metrics.core import BARS_PER_YEAR, ann_sharpe, n_round_trips
from src.signals.rules import cancel_entries_without_positive_beta, positions_from_z
from src.signals.spread import pair_spread, rolling_zscore


@dataclass(frozen=True)
class ParamSet:
    delta: float
    zscore_window_bars: int
    entry_z: float
    exit_z: float
    stop_z: float


def param_grid(grid: GridConfig) -> list[ParamSet]:
    return [
        ParamSet(*combo)
        for combo in product(
            grid.kalman_delta, grid.zscore_window_bars, grid.entry_z, grid.exit_z, grid.stop_z
        )
    ]


def spread_cache(
    panel: pd.DataFrame,
    book: list[tuple[str, str]],
    deltas: list[float],
    burn_in_bars: int,
) -> dict[tuple[str, str, float], pd.DataFrame]:
    """(leg_y, leg_x, delta) -> [beta, spread] frame over the panel's full span."""
    cache: dict[tuple[str, str, float], pd.DataFrame] = {}
    for leg_y, leg_x in book:
        joint = panel[[leg_y, leg_x]].dropna()
        y_log, x_log = np.log(joint[leg_y]), np.log(joint[leg_x])
        for delta in deltas:
            kcfg = KalmanConfig(delta=delta, burn_in_bars=burn_in_bars)
            cache[(leg_y, leg_x, delta)] = pair_spread(y_log, x_log, kcfg)
    return cache


def run_params(
    panel: pd.DataFrame,
    book: list[tuple[str, str]],
    params: ParamSet,
    cache: dict[tuple[str, str, float], pd.DataFrame],
    funding: dict[str, pd.Series],
    bt_cfg: BacktestConfig,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    fresh_entries_only: bool = False,
) -> dict[str, pd.DataFrame]:
    """Backtest every book pair under one ParamSet, sliced to [start, end).

    Signals are computed on the full cached span (causal, so bar values do not
    depend on what follows); the slice selects which bars' PnL we count.
    fresh_entries_only zeroes desired positions before `start` so a slice earns
    only trades initiated inside it (used for walk-forward test slices), and
    forces a flat decision two bars before `end` so the exit fill and its cost
    land INSIDE the slice instead of leaking past the fold boundary.
    """
    results: dict[str, pd.DataFrame] = {}
    for leg_y, leg_x in book:
        frame = cache[(leg_y, leg_x, params.delta)]
        z = rolling_zscore(frame["spread"], params.zscore_window_bars)
        desired = positions_from_z(z, params.entry_z, params.exit_z, params.stop_z)
        # Walk-forward-screened pairs can carry degenerate hedge estimates;
        # entries with beta <= 0 are cancelled, never traded (see rules.py).
        desired = cancel_entries_without_positive_beta(desired, frame["beta"])
        if fresh_entries_only and start is not None:
            desired = desired.where(desired.index >= start, 0)
        if fresh_entries_only and end is not None:
            in_slice = desired.index[(desired.index >= (start or desired.index[0]))
                                     & (desired.index < end)]
            if len(in_slice) >= 2:
                desired.loc[in_slice[-2] :] = 0
        result = backtest_pair(
            close_y=panel[leg_y].reindex(frame.index),
            close_x=panel[leg_x].reindex(frame.index),
            desired=desired,
            beta=frame["beta"],
            funding_y=funding.get(leg_y, pd.Series(dtype=float)),
            funding_x=funding.get(leg_x, pd.Series(dtype=float)),
            cfg=bt_cfg,
        )
        if start is not None:
            result = result.loc[result.index >= start]
        if end is not None:
            result = result.loc[result.index < end]
        results[f"{leg_y} ~ {leg_x}"] = result
    return results


def grid_search(
    panel: pd.DataFrame,
    book: list[tuple[str, str]],
    grid: GridConfig,
    cache: dict[tuple[str, str, float], pd.DataFrame],
    funding: dict[str, pd.Series],
    bt_cfg: BacktestConfig,
    interval: str,
    min_trades_per_year: float,
    end: pd.Timestamp,
) -> pd.DataFrame:
    """Evaluate the whole grid on data strictly before `end` (the tuning window).

    Returns one row per ParamSet ranked by portfolio net Sharpe; configs below
    the trades floor keep their stats but are excluded from eligibility.
    """
    rows = []
    for params in param_grid(grid):
        results = run_params(panel, book, params, cache, funding, bt_cfg, end=end)
        port = portfolio_curve(results)
        years = len(port) / BARS_PER_YEAR[interval]
        trades = sum(n_round_trips(r["w_y"]) for r in results.values())
        rows.append(
            {
                **params.__dict__,
                "net": port["net"].sum(),
                "sharpe": ann_sharpe(port["net"], interval),
                "trades": trades,
                "eligible": trades >= min_trades_per_year * years * len(book),
            }
        )
    table = pd.DataFrame(rows).sort_values("sharpe", ascending=False).reset_index(drop=True)
    return table
