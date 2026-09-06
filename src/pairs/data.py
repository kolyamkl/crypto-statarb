"""Load aligned price panels from Postgres for the analysis layer.

The raw layer stores NUMERIC (exact Decimal); analysis works in float64 — the
loss is far below tick size and every stats routine needs floats anyway.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import psycopg

from src.config import Config


def train_cutoff(cfg: Config) -> datetime:
    """First instant NOT visible to selection/tuning (train_end is inclusive)."""
    day = datetime.fromisoformat(cfg.validation.train_end).replace(tzinfo=timezone.utc)
    return day + timedelta(days=1)


def load_close_panel(
    conn: psycopg.Connection,
    cfg: Config,
    end: datetime | None = None,
    symbols: list[str] | None = None,
    field: str = "close",
) -> pd.DataFrame:
    """Wide price panel: index=open_time (UTC), one column per symbol.

    `end` is exclusive and defaults to the training cutoff — callers must ask
    explicitly to see anything beyond the training window. `symbols` defaults to
    the universe; benchmark/factor callers pass universe + aux explicitly so the
    pair screen can never accidentally see an aux symbol. `field` selects the
    price column ('open' for the equity next-open fill model).
    """
    if field not in ("close", "open"):  # column name is interpolated — whitelist it
        raise ValueError(f"unsupported price field {field!r}")
    end = end or train_cutoff(cfg)
    rows = conn.execute(
        f"""
        SELECT open_time, symbol, {field} FROM ohlcv
        WHERE exchange = %s AND market = %s AND interval = %s
          AND symbol = ANY(%s) AND open_time < %s
        ORDER BY open_time
        """,
        (cfg.data.exchange, cfg.data.market, cfg.data.interval, symbols or cfg.data.universe, end),
    ).fetchall()
    df = pd.DataFrame(rows, columns=["open_time", "symbol", field])
    panel = df.pivot(index="open_time", columns="symbol", values=field).astype(float)
    # No forward-filling here, ever: a NaN is a recorded absence (see gap policy);
    # pair-level code decides how to align, typically an inner join via dropna().
    return panel
