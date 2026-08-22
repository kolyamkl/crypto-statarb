"""M5 walk-forward: re-screen pairs AND re-tune parameters on a rolling window,
then trade the next untouched slice. Repeat, step, stitch.

This validates the whole PIPELINE, not one lucky pair list: each fold's book is
whatever the M2 screen (unchanged rules, pre-registered half-life bounds) finds
in that fold's training window — a fold with no passing pairs holds cash, which
is recorded, not hidden. Structural look-ahead guard: everything a fold tunes
on ends strictly before the slice it trades, asserted in code and unit-tested.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas as pd

from src.config import Config
from src.backtest.engine import portfolio_curve
from src.metrics.core import ann_sharpe
from src.pairs.cointegration import screen_universe
from src.validate.grid import ParamSet, grid_search, run_params, spread_cache

log = logging.getLogger(__name__)


@dataclass
class Fold:
    train_start: pd.Timestamp
    test_start: pd.Timestamp  # tuning uses bars strictly BEFORE this
    test_end: pd.Timestamp
    book: list[tuple[str, str]] = field(default_factory=list)
    params: ParamSet | None = None
    train_sharpe: float = float("nan")
    test_net: float = float("nan")
    test_sharpe: float = float("nan")


def make_folds(index: pd.DatetimeIndex, train_bars: int, test_bars: int) -> list[Fold]:
    """Rolling folds over the bar index; the last fold may have a short test."""
    folds = []
    start = 0
    while start + train_bars < len(index):
        test_start = start + train_bars
        test_end = min(test_start + test_bars, len(index))
        folds.append(
            Fold(
                train_start=index[start],
                test_start=index[test_start],
                test_end=index[test_end - 1] + (index[1] - index[0]),
            )
        )
        start += test_bars
    return folds


def run_walkforward(
    panel: pd.DataFrame, funding: dict[str, pd.Series], cfg: Config
) -> tuple[pd.Series, list[Fold]]:
    """Returns the stitched out-of-sample portfolio net PnL series and fold log."""
    wf = cfg.validation.walkforward
    folds = make_folds(panel.index, wf.train_bars, wf.test_bars)
    oos_parts: list[pd.Series] = []

    for i, fold in enumerate(folds):
        assert fold.train_start < fold.test_start <= fold.test_end  # structural guard
        train_panel = panel.loc[(panel.index >= fold.train_start) & (panel.index < fold.test_start)]

        # 1) Re-screen the whole universe on this fold's training window only.
        passed = [r for r in screen_universe(train_panel, cfg.pairs) if r.passed]
        fold.book = [(r.leg_y, r.leg_x) for r in passed[: wf.max_pairs]]
        if not fold.book:
            log.info("fold %d (%s): no pairs pass — holding cash", i, fold.test_start.date())
            continue

        # 2) Re-tune the pre-declared grid on the same training window.
        span = panel.loc[(panel.index >= fold.train_start) & (panel.index < fold.test_end)]
        cache = spread_cache(
            span, fold.book, cfg.validation.grid.kalman_delta, cfg.pairs.kalman.burn_in_bars
        )
        table = grid_search(
            span, fold.book, cfg.validation.grid, cache, funding, cfg.backtest,
            cfg.data.interval, cfg.validation.min_trades_per_year, end=fold.test_start,
        )
        eligible = table[table["eligible"]]
        if eligible.empty:
            log.info("fold %d (%s): no eligible config — holding cash", i, fold.test_start.date())
            continue
        best = eligible.iloc[0]
        fold.params = ParamSet(
            delta=float(best["delta"]),
            zscore_window_bars=int(best["zscore_window_bars"]),
            entry_z=float(best["entry_z"]),
            exit_z=float(best["exit_z"]),
            stop_z=float(best["stop_z"]),
        )
        fold.train_sharpe = float(best["sharpe"])

        # 3) Trade the untouched slice: fresh entries only, exits forced inside.
        results = run_params(
            span, fold.book, fold.params, cache, funding, cfg.backtest,
            start=fold.test_start, end=fold.test_end, fresh_entries_only=True,
        )
        port = portfolio_curve(results)
        fold.test_net = float(port["net"].sum())
        fold.test_sharpe = ann_sharpe(port["net"], cfg.data.interval)
        oos_parts.append(port["net"])
        log.info(
            "fold %d (%s -> %s): book=%s params=%s train_sharpe=%.2f test_net=%+.2f%%",
            i, fold.test_start.date(), fold.test_end.date(),
            [f"{y}/{x}" for y, x in fold.book], fold.params, fold.train_sharpe,
            fold.test_net * 100,
        )

    if not oos_parts:
        return pd.Series(dtype=float), folds
    stitched = pd.concat(oos_parts).sort_index()
    assert not stitched.index.duplicated().any()  # folds must never overlap
    return stitched, folds
