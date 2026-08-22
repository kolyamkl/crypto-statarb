"""M4 backtest engine for one pair — vectorised arithmetic, explicit state loop.

Execution model (no look-ahead, SPEC.md M4):
    The desired position is decided at the close of bar t and filled at the OPEN
    of bar t+1. Crypto perps trade 24/7, so open_{t+1} equals close_t to within
    microstructure noise — which is exactly what the slippage charge prices in.
    Hence the position HELD during bar t is desired.shift(1), and it earns bar
    t's close-to-close return.

Sizing:
    Unit gross capital per pair while active, split 1:beta across the legs
    (w_y = s/(1+beta), w_x = -s*beta/(1+beta)) so the pair is return-neutral
    under the hedge ratio. Beta is FROZEN at trade entry: re-hedging every bar
    would add turnover cost for a hedge drift that is negligible at delta=1e-5,
    and a fixed ratio per trade is what live execution would do.

Accounting:
    Arithmetic PnL on constant unit capital (no compounding), so the
    decomposition is exactly additive: net = gross - fee - slippage + funding,
    and the reconciliation test can assert it to float precision.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import BacktestConfig


def held_weights(desired: pd.Series, beta: pd.Series) -> pd.DataFrame:
    """Per-bar executed leg weights (w_y, w_x) held DURING each bar.

    desired/beta are indexed by decision bar; both are shifted one bar so the
    fill happens on the next bar, with beta frozen at the entry fill.
    """
    executed = desired.shift(1, fill_value=0).to_numpy()
    entry_beta = beta.shift(1).to_numpy()  # the hedge ratio known at decision time
    w_y = np.zeros(len(executed))
    w_x = np.zeros(len(executed))
    cur_y = cur_x = 0.0
    prev = 0
    for i, s in enumerate(executed):
        if s != prev:
            if s == 0:
                cur_y = cur_x = 0.0
            else:
                b = entry_beta[i]
                if not b > 0:
                    # 1:beta sizing needs a positive hedge ratio; a negative one
                    # would mean a long-long "pair" — refuse loudly, never trade it.
                    raise ValueError(f"non-positive beta {b} at entry index {i}")
                cur_y = s / (1.0 + b)
                cur_x = -s * b / (1.0 + b)
            prev = s
        w_y[i] = cur_y
        w_x[i] = cur_x
    return pd.DataFrame({"w_y": w_y, "w_x": w_x}, index=desired.index)


def backtest_pair(
    close_y: pd.Series,
    close_x: pd.Series,
    desired: pd.Series,
    beta: pd.Series,
    funding_y: pd.Series,
    funding_x: pd.Series,
    cfg: BacktestConfig,
) -> pd.DataFrame:
    """Per-bar PnL decomposition on unit pair capital.

    funding_y/funding_x: signed funding RATE aggregated per bar (0 when no event
    in that bar). Positive rate means longs pay shorts, so pnl = -w * rate.

    Columns: w_y, w_x, turnover, gross, fee, slip, funding, net.
    """
    frame = held_weights(desired, beta)
    r_y = close_y.pct_change().fillna(0.0)
    r_x = close_x.pct_change().fillna(0.0)

    frame["turnover"] = (
        frame["w_y"].diff().abs().fillna(frame["w_y"].abs())
        + frame["w_x"].diff().abs().fillna(frame["w_x"].abs())
    )
    frame["gross"] = frame["w_y"] * r_y + frame["w_x"] * r_x
    frame["fee"] = frame["turnover"] * cfg.taker_fee_bps / 1e4
    frame["slip"] = frame["turnover"] * cfg.slippage_bps / 1e4
    # Funding is charged on the position held in the bar containing the event;
    # rates are per-event (not annualized), so notional * rate is the cashflow.
    frame["funding"] = -(
        frame["w_y"] * funding_y.reindex(frame.index, fill_value=0.0)
        + frame["w_x"] * funding_x.reindex(frame.index, fill_value=0.0)
    )
    frame["net"] = frame["gross"] - frame["fee"] - frame["slip"] + frame["funding"]
    return frame


def portfolio_curve(pair_results: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Equal-capital portfolio: each pair runs on 1/n of the book's capital.

    Bars where a pair has no result yet (different warm-ups) contribute 0 for
    that pair — idle capital, not missing data.
    """
    n = len(pair_results)
    cols = ["gross", "fee", "slip", "funding", "net"]
    combined = sum(
        df[cols].reindex(_union_index(pair_results), fill_value=0.0) for df in pair_results.values()
    )
    return combined / n


def _union_index(pair_results: dict[str, pd.DataFrame]) -> pd.Index:
    idx: pd.Index | None = None
    for df in pair_results.values():
        idx = df.index if idx is None else idx.union(df.index)
    return idx.sort_values()
