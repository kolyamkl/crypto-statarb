"""M10 equity ingestion: `STATARB_CONFIG=config_equities.yaml uv run python -m src.ingest.equities`.

Pulls daily ADJUSTED OHLCV (splits + dividends, yfinance `auto_adjust=True`) for
the pre-declared universe + aux symbols into the same `ohlcv` table, discriminated
by exchange='yfinance', market='equity'.

Two deliberate differences from the crypto ingester (DECISIONS.md 2026-09-06):

- **Upserts are ON CONFLICT DO UPDATE**, not DO NOTHING: adjusted prices are
  retroactively rescaled by every later dividend, so a re-ingestion legitimately
  rewrites history. The retrieval date in data_provenance_equities.md is
  therefore part of reproducibility.
- **Gap detection is calendar-aware**: equities skip weekends and holidays, so
  "missing" is defined against the union of trading dates observed across the
  whole universe (an NYSE-calendar proxy — every symbol here is NYSE/NASDAQ),
  not against a fixed bar grid.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import psycopg

from src.config import REPO_ROOT, Config, load_config
from src.db import apply_schema, connect

log = logging.getLogger(__name__)

PROVENANCE_PATH = REPO_ROOT / "data_provenance_equities.md"


def all_symbols(cfg: Config) -> list[str]:
    return list(cfg.data.universe) + list(cfg.data.aux)


def clean_daily_frame(df: pd.DataFrame, start: date, end: date, today: date) -> pd.DataFrame:
    """Pure filter for one symbol's yfinance frame: window-clip, drop NaN rows,
    and drop today's still-forming bar (a mutable bar is look-ahead bias waiting
    to happen — same rule as the crypto ingester's incomplete-kline drop)."""
    out = df.dropna(subset=["Open", "High", "Low", "Close"])
    dates = pd.Index([d.date() for d in out.index])
    keep = (dates >= start) & (dates <= end) & (dates < today)
    return out[list(keep)]


def union_calendar(frames: dict[str, pd.DataFrame]) -> list[date]:
    """Sorted union of trading dates across all symbols — the market-calendar
    proxy that defines what a 'missing' equity bar means."""
    dates: set[date] = set()
    for df in frames.values():
        dates.update(d.date() for d in df.index)
    return sorted(dates)


def calendar_gaps(
    symbol_dates: list[date], calendar: list[date]
) -> list[tuple[date, date, int]]:
    """Contiguous runs of calendar dates missing from a symbol's series, interior
    to its own [first, last] span. Pure function, unit-tested."""
    if not symbol_dates:
        return []
    have = set(symbol_dates)
    first, last = min(symbol_dates), max(symbol_dates)
    position = {d: i for i, d in enumerate(calendar)}
    missing = [d for d in calendar if first <= d <= last and d not in have]
    gaps: list[tuple[date, date, int]] = []
    run: list[date] = []
    for d in missing:
        # A run breaks when the next missing date is not the very next calendar slot.
        if run and position[d] - position[run[-1]] > 1:
            gaps.append((run[0], run[-1], len(run)))
            run = []
        run.append(d)
    if run:
        gaps.append((run[0], run[-1], len(run)))
    return gaps


def _utc_midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def fetch_frames(cfg: Config) -> dict[str, pd.DataFrame]:
    """One batched yfinance download for the whole universe + aux."""
    import yfinance as yf  # imported here so the crypto pipeline never needs it

    start = date.fromisoformat(cfg.data.start_date)
    end = date.fromisoformat(cfg.data.end_date)
    today = datetime.now(timezone.utc).date()
    raw = yf.download(
        tickers=all_symbols(cfg),
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),  # yfinance end is exclusive
        interval="1d",
        auto_adjust=True,  # split+dividend adjusted OHLC, consistently rescaled
        group_by="ticker",
        progress=False,
        threads=True,
    )
    frames: dict[str, pd.DataFrame] = {}
    for symbol in all_symbols(cfg):
        df = raw[symbol] if isinstance(raw.columns, pd.MultiIndex) else raw
        frames[symbol] = clean_daily_frame(df, start, end, today)
    return frames


def store_symbols(conn: psycopg.Connection, cfg: Config, frames: dict[str, pd.DataFrame]) -> None:
    """Survivorship metadata. yfinance has no onboard date; the first stored bar
    plays that role and the provenance doc states the (worse-than-crypto)
    survivorship caveat: today's large-caps only."""
    with conn.cursor() as cur:
        for symbol, df in frames.items():
            if df.empty:
                log.warning("symbol %s returned no data — check for delisting/rename", symbol)
                continue
            cur.execute(
                """
                INSERT INTO symbols (exchange, symbol, base_asset, quote_asset, status, onboard_date)
                VALUES (%s, %s, %s, 'USD', 'TRADING', %s)
                ON CONFLICT (exchange, symbol) DO UPDATE
                    SET status = EXCLUDED.status, onboard_date = EXCLUDED.onboard_date
                """,
                (cfg.data.exchange, symbol, symbol, _utc_midnight(df.index[0].date())),
            )
    conn.commit()


def store_ohlcv(conn: psycopg.Connection, cfg: Config, symbol: str, df: pd.DataFrame) -> int:
    rows = [
        (
            cfg.data.exchange,
            cfg.data.market,
            symbol,
            cfg.data.interval,
            _utc_midnight(t.date()),
            float(r["Open"]),
            float(r["High"]),
            float(r["Low"]),
            float(r["Close"]),
            float(r["Volume"]) if pd.notna(r["Volume"]) else 0.0,
        )
        for t, r in df.iterrows()
    ]
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO ohlcv (exchange, market, symbol, interval, open_time,
                               open, high, low, close, volume)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (exchange, market, symbol, interval, open_time) DO UPDATE SET
                open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
                close = EXCLUDED.close, volume = EXCLUDED.volume
            """,
            rows,
        )
    conn.commit()
    return len(rows)


def store_gaps(conn: psycopg.Connection, cfg: Config, frames: dict[str, pd.DataFrame]) -> int:
    calendar = union_calendar(frames)
    total = 0
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM data_gaps WHERE exchange = %s AND interval = %s",
            (cfg.data.exchange, cfg.data.interval),
        )
        for symbol, df in frames.items():
            for gap_start, gap_end, n_missing in calendar_gaps(
                [d.date() for d in df.index], calendar
            ):
                cur.execute(
                    """
                    INSERT INTO data_gaps
                        (exchange, market, symbol, interval, gap_start, gap_end, n_missing)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        cfg.data.exchange, cfg.data.market, symbol, cfg.data.interval,
                        _utc_midnight(gap_start), _utc_midnight(gap_end), n_missing,
                    ),
                )
                total += 1
    conn.commit()
    return total


def write_provenance(cfg: Config, frames: dict[str, pd.DataFrame], n_gaps: int) -> Path:
    import yfinance

    calendar = union_calendar(frames)
    retrieved = datetime.now(timezone.utc)
    lines = [
        "# Data Provenance — equities (M10)",
        "",
        "> Auto-generated by `src/ingest/equities.py` on every ingestion run — do not edit by hand.",
        "",
        f"- **Source:** yfinance {yfinance.__version__} (Yahoo Finance), daily bars,",
        "  `auto_adjust=True` — OHLC adjusted for splits AND dividends, consistently rescaled.",
        f"- **Retrieved:** {retrieved:%Y-%m-%d %H:%M} UTC. Adjusted history is retroactively",
        "  rescaled by every later dividend, so this retrieval date is part of reproducibility;",
        "  re-ingestion legitimately rewrites past bars (upsert = DO UPDATE).",
        f"- **Configured range:** {cfg.data.start_date} → {cfg.data.end_date} "
        "(matched to the crypto study's window).",
        "- **Calendar:** 'missing' is defined against the union of trading dates observed",
        f"  across all {len(frames)} symbols ({len(calendar)} dates) — an NYSE-calendar proxy.",
        "- **Survivorship — worse than crypto:** the universe is drawn from TODAY's large-caps",
        "  on a source that only lists surviving tickers. Documented in M10_PLAN.md §4; a",
        "  delisted-inclusive dataset (CRSP) would fix it and is out of scope at zero budget.",
        "- **Dividends on shorts** are proxied by adjusted prices + the borrow-fee cost model,",
        "  never modelled as explicit cash flows.",
        "",
        "## Coverage by symbol",
        "",
        "| Symbol | Role | First bar | Last bar | Bars stored | Calendar days in span | Missing |",
        "|--------|------|-----------|----------|-------------|-----------------------|---------|",
    ]
    for symbol, df in frames.items():
        role = "aux" if symbol in cfg.data.aux else "universe"
        if df.empty:
            lines.append(f"| {symbol} | {role} | — | — | 0 | — | — |")
            continue
        first, last = df.index[0].date(), df.index[-1].date()
        in_span = sum(1 for d in calendar if first <= d <= last)
        lines.append(
            f"| {symbol} | {role} | {first} | {last} | {len(df)} | {in_span} | {in_span - len(df)} |"
        )
    lines += ["", f"## Known gaps: {n_gaps} recorded in `data_gaps` (never forward-filled)", ""]
    PROVENANCE_PATH.write_text("\n".join(lines))
    return PROVENANCE_PATH


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config()
    if cfg.data.market != "equity":
        raise SystemExit(
            "equities ingester needs the equity config: STATARB_CONFIG=config_equities.yaml"
        )

    frames = fetch_frames(cfg)
    with connect(cfg.db) as conn:
        apply_schema(conn)
        store_symbols(conn, cfg, frames)
        for symbol, df in frames.items():
            n = store_ohlcv(conn, cfg, symbol, df)
            log.info("%s: upserted %d daily bars", symbol, n)
        n_gaps = store_gaps(conn, cfg, frames)
        log.info("gap scan complete: %d calendar gaps recorded", n_gaps)
    path = write_provenance(cfg, frames, n_gaps)
    log.info("provenance written to %s", path)


if __name__ == "__main__":
    main()
