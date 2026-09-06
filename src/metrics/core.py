"""Core performance statistics on per-bar arithmetic PnL (unit capital).

Built for M5's train/test comparison; M6 layers the full reporting on top.
All inputs are the per-bar `net`-style columns from the backtest engine —
arithmetic returns on constant capital, so equity is a cumsum and drawdown is
in absolute %-of-capital units.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import BARS_PER_YEAR  # single source of truth; re-exported for callers

__all__ = ["BARS_PER_YEAR"]


def bars_label(bars: float, interval: str) -> str:
    """Human-readable duration for a bar count — '123h (~5.1d)' or '12d'."""
    if interval == "1h":
        return f"{bars:.0f}h (~{bars / 24:.1f}d)"
    if interval == "1d":
        return f"{bars:.0f}d"
    return f"{bars:.0f} bars"


def ann_sharpe(pnl: pd.Series, interval: str) -> float:
    """Annualized Sharpe of per-bar PnL. Zero-vol (never traded) -> NaN, not 0:
    'no track record' and 'zero risk-adjusted return' are different claims."""
    std = float(pnl.std())
    if std == 0.0 or np.isnan(std):
        return float("nan")
    return float(pnl.mean() / std * np.sqrt(BARS_PER_YEAR[interval]))


def max_drawdown(pnl: pd.Series) -> float:
    """Deepest peak-to-trough fall of the cumulative PnL, in %-of-capital units
    (arithmetic equity, so this is NOT a relative drawdown)."""
    equity = pnl.cumsum()
    return float((equity - equity.cummax()).min())


def ann_sortino(pnl: pd.Series, interval: str) -> float:
    """Like Sharpe but penalizing only downside deviation — the number a fat-
    tailed strategy's Sharpe understates (or flatters, if the tails are on the
    loss side, which is exactly what stop-outs produce)."""
    # Target semideviation: squared shortfalls averaged over ALL bars (the
    # textbook convention) — averaging over losing bars only would shrink as
    # losses get rarer, inflating Sortino exactly when it should not be.
    dstd = float(np.sqrt((pnl.clip(upper=0) ** 2).mean()))
    if dstd == 0.0 or np.isnan(dstd):
        return float("nan")
    return float(pnl.mean() / dstd * np.sqrt(BARS_PER_YEAR[interval]))


def n_round_trips(w_y: pd.Series) -> int:
    """Entries counted as flat -> non-flat transitions of the held weight."""
    active = w_y != 0
    return int((active & ~active.shift(1, fill_value=False)).sum())


def trade_pnls(frame: pd.DataFrame) -> list[float]:
    """Net PnL per round trip. An episode runs from its first held bar through
    the first flat bar after it — that flat bar carries the exit fee/slip (the
    engine charges turnover when the weight CHANGES to zero), so excluding it
    would flatter every trade by one exit cost."""
    active = (frame["w_y"] != 0).to_numpy()
    net = frame["net"].to_numpy()
    pnls: list[float] = []
    i = 0
    n = len(active)
    while i < n:
        if active[i]:
            j = i
            while j < n and active[j]:
                j += 1
            end = min(j + 1, n)  # include the exit-cost bar when it exists
            pnls.append(float(net[i:end].sum()))
            i = end
        else:
            i += 1
    return pnls


def hit_rate(frame: pd.DataFrame) -> float:
    pnls = trade_pnls(frame)
    return float(np.mean([p > 0 for p in pnls])) if pnls else float("nan")


def avg_holding_bars(frame: pd.DataFrame) -> float:
    active = frame["w_y"] != 0
    runs = active.groupby((~active).cumsum()).sum()
    runs = runs[runs > 0]
    return float(runs.mean()) if len(runs) else float("nan")


def ann_turnover(frame: pd.DataFrame, interval: str) -> float:
    """Gross notional traded per year, in multiples of unit capital."""
    if "turnover" not in frame.columns:
        return float("nan")
    years = len(frame) / BARS_PER_YEAR[interval]
    return float(frame["turnover"].sum() / years) if years > 0 else float("nan")


def summarize(frame: pd.DataFrame, interval: str) -> dict[str, float]:
    """One row of headline stats for a backtest result frame (pair or portfolio).

    Portfolio frames have no weights; trade stats are reported when available.
    """
    costs = frame["fee"] + frame["slip"]
    if "borrow" in frame.columns:  # equity variant: borrow is a cost like fee/slip
        costs = costs + frame["borrow"]
    out = {
        "net": float(frame["net"].sum()),
        "gross": float(frame["gross"].sum()),
        "costs": float(costs.sum()),
        "funding": float(frame["funding"].sum()),
        "sharpe": ann_sharpe(frame["net"], interval),
        "max_dd": max_drawdown(frame["net"]),
        "bars": len(frame),
    }
    if "w_y" in frame.columns:
        out["trades"] = n_round_trips(frame["w_y"])
        out["pct_in_market"] = 100.0 * float((frame["w_y"] != 0).mean())
    return out


def full_summary(frame: pd.DataFrame, interval: str) -> dict[str, float]:
    """The M6 honest-metrics row: everything net of costs on unit capital."""
    out = summarize(frame, interval)
    out["sortino"] = ann_sortino(frame["net"], interval)
    if "w_y" in frame.columns:
        out["hit_rate"] = hit_rate(frame)
        out["avg_hold_bars"] = avg_holding_bars(frame)
        out["ann_turnover"] = ann_turnover(frame, interval)
    return out
