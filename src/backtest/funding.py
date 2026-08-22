"""Map realized funding events onto bars for the backtest.

Uses the ACTUAL stored events, never an assumed 8h grid: Binance varies the
cadence under stress (SOLUSDT funded ~2-hourly during the Nov-2022 FTX collapse,
see DECISIONS.md), and assuming a grid would mis-price costs precisely in the
highest-stress regime.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import psycopg

from src.config import Config

# pandas floor() frequency for each bar interval we support.
FLOOR_FREQ = {"15m": "15min", "1h": "1h", "4h": "4h"}


def funding_rate_per_bar(
    conn: psycopg.Connection, cfg: Config, symbol: str, end: datetime
) -> pd.Series:
    """Sum of funding RATES per bar open_time (an event at an exact bar boundary
    belongs to the bar that STARTS there: the exchange charges whoever holds the
    position at the funding timestamp, and our fills happen at bar opens)."""
    rows = conn.execute(
        """
        SELECT funding_time, funding_rate FROM funding
        WHERE exchange = %s AND symbol = %s AND funding_time < %s
        ORDER BY funding_time
        """,
        (cfg.data.exchange, symbol, end),
    ).fetchall()
    if not rows:
        return pd.Series(dtype=float)
    events = pd.DataFrame(rows, columns=["funding_time", "rate"])
    events["rate"] = events["rate"].astype(float)
    bars = pd.DatetimeIndex(events["funding_time"]).floor(FLOOR_FREQ[cfg.data.interval])
    return events.groupby(bars)["rate"].sum()
