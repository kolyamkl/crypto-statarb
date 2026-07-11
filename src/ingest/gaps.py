"""Gap detection for bar series.

SPEC.md M1: gaps are RECORDED, never silently forward-filled. The scanner walks
each symbol's stored bars and writes contiguous holes to the data_gaps table;
data_provenance.md is generated from that table.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import psycopg

from src.config import Config
from src.ingest.binance import INTERVAL_MS


def find_gaps(
    open_times: list[datetime], interval_ms: int
) -> list[tuple[datetime, datetime, int]]:
    """Return (first_missing_bar, last_missing_bar, n_missing) for every hole.

    Pure function over a sorted list of bar open times — unit-tested with
    synthetic series (tests/test_ingest.py). Only interior gaps are detectable;
    where the series starts/ends is a coverage question, not a gap.
    """
    step = timedelta(milliseconds=interval_ms)
    gaps: list[tuple[datetime, datetime, int]] = []
    for prev, cur in zip(open_times, open_times[1:]):
        delta = cur - prev
        if delta > step:
            n_missing = int(delta / step) - 1
            gaps.append((prev + step, cur - step, n_missing))
    return gaps


def scan_and_store(conn: psycopg.Connection, cfg: Config) -> int:
    """Rescan every universe symbol and rewrite data_gaps. Returns total gaps found."""
    interval = cfg.data.interval
    interval_ms = INTERVAL_MS[interval]
    exchange = cfg.data.exchange
    total = 0

    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM data_gaps WHERE exchange = %s AND interval = %s", (exchange, interval)
        )
        for symbol in cfg.data.universe:
            cur.execute(
                """
                SELECT open_time FROM ohlcv
                WHERE exchange = %s AND market = 'perp' AND symbol = %s AND interval = %s
                ORDER BY open_time
                """,
                (exchange, symbol, interval),
            )
            times = [row[0] for row in cur.fetchall()]
            for gap_start, gap_end, n_missing in find_gaps(times, interval_ms):
                cur.execute(
                    """
                    INSERT INTO data_gaps
                        (exchange, market, symbol, interval, gap_start, gap_end, n_missing)
                    VALUES (%s, 'perp', %s, %s, %s, %s, %s)
                    """,
                    (exchange, symbol, interval, gap_start, gap_end, n_missing),
                )
                total += 1
    conn.commit()
    return total
