"""M1 ingestion orchestrator: `uv run python -m src.ingest.run`.

Pulls OHLCV + funding + premium-index (basis) history for the config-driven
universe into Postgres, then rescans gaps and regenerates data_provenance.md.

Idempotent and resumable: every table has a composite PK with
ON CONFLICT DO NOTHING, and each series resumes from its own MAX(time) cursor,
so re-running only fetches what is missing.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import psycopg

from src.config import Config, load_config
from src.db import apply_schema, connect
from src.ingest.binance import (
    FUNDING_MAX_LIMIT,
    INTERVAL_MS,
    KLINES_MAX_LIMIT,
    BinanceUsdm,
    ms_to_utc,
    parse_funding,
    parse_kline,
    parse_premium_kline,
)

log = logging.getLogger(__name__)


def _config_start_ms(cfg: Config) -> int:
    return int(
        datetime.fromisoformat(cfg.data.start_date).replace(tzinfo=timezone.utc).timestamp() * 1000
    )


def _end_ms(cfg: Config) -> int:
    if cfg.data.end_date:
        return int(
            datetime.fromisoformat(cfg.data.end_date).replace(tzinfo=timezone.utc).timestamp()
            * 1000
        )
    return int(time.time() * 1000)


def _resume_cursor_ms(
    conn: psycopg.Connection, query: str, params: tuple, fallback_ms: int, step_ms: int
) -> int:
    """Resume after the newest stored row, or from config start on first run."""
    row = conn.execute(query, params).fetchone()
    if row and row[0] is not None:
        return int(row[0].timestamp() * 1000) + step_ms
    return fallback_ms


def ingest_symbols(client: BinanceUsdm, conn: psycopg.Connection, cfg: Config) -> None:
    """Record the survivorship metadata (onboard dates) for the configured universe."""
    info = {s["symbol"]: s for s in client.exchange_info()}
    with conn.cursor() as cur:
        for symbol in cfg.data.universe:
            meta = info.get(symbol)
            if meta is None:
                # A universe symbol missing from exchangeInfo likely means delisted —
                # surfaced loudly because silently skipping it would be survivorship bias.
                log.warning("symbol %s not in exchangeInfo — check for delisting", symbol)
                continue
            cur.execute(
                """
                INSERT INTO symbols (exchange, symbol, base_asset, quote_asset, status, onboard_date)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (exchange, symbol) DO UPDATE
                    SET status = EXCLUDED.status, onboard_date = EXCLUDED.onboard_date
                """,
                (
                    cfg.data.exchange,
                    symbol,
                    meta["baseAsset"],
                    meta["quoteAsset"],
                    meta["status"],
                    ms_to_utc(int(meta["onboardDate"])),
                ),
            )
    conn.commit()


def ingest_ohlcv(client: BinanceUsdm, conn: psycopg.Connection, cfg: Config, symbol: str) -> int:
    interval = cfg.data.interval
    step_ms = INTERVAL_MS[interval]
    end_ms = _end_ms(cfg)
    cursor = _resume_cursor_ms(
        conn,
        """SELECT MAX(open_time) FROM ohlcv
           WHERE exchange=%s AND market='perp' AND symbol=%s AND interval=%s""",
        (cfg.data.exchange, symbol, interval),
        _config_start_ms(cfg),
        step_ms,
    )
    inserted = 0
    while cursor < end_ms:
        raw = client.klines(symbol, interval, cursor, end_ms)
        # Drop the still-forming bar: its close is not final yet, and letting a
        # mutable bar into the dataset is a subtle source of look-ahead bias.
        complete = [r for r in raw if int(r[6]) < end_ms]
        if not complete:
            break
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO ohlcv (exchange, market, symbol, interval, open_time,
                                   open, high, low, close, volume, quote_volume, n_trades)
                VALUES (%s, 'perp', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                [(cfg.data.exchange, symbol, interval, *parse_kline(r)) for r in complete],
            )
        conn.commit()
        inserted += len(complete)
        cursor = int(complete[-1][0]) + step_ms
        if len(raw) < KLINES_MAX_LIMIT:
            break
    return inserted


def ingest_premium_index(
    client: BinanceUsdm, conn: psycopg.Connection, cfg: Config, symbol: str
) -> int:
    interval = cfg.data.interval
    step_ms = INTERVAL_MS[interval]
    end_ms = _end_ms(cfg)
    cursor = _resume_cursor_ms(
        conn,
        """SELECT MAX(open_time) FROM premium_index
           WHERE exchange=%s AND symbol=%s AND interval=%s""",
        (cfg.data.exchange, symbol, interval),
        _config_start_ms(cfg),
        step_ms,
    )
    inserted = 0
    while cursor < end_ms:
        raw = client.premium_index_klines(symbol, interval, cursor, end_ms)
        complete = [r for r in raw if int(r[6]) < end_ms]
        if not complete:
            break
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO premium_index (exchange, symbol, interval, open_time,
                                           open, high, low, close)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                [(cfg.data.exchange, symbol, interval, *parse_premium_kline(r)) for r in complete],
            )
        conn.commit()
        inserted += len(complete)
        cursor = int(complete[-1][0]) + step_ms
        if len(raw) < KLINES_MAX_LIMIT:
            break
    return inserted


def ingest_funding(client: BinanceUsdm, conn: psycopg.Connection, cfg: Config, symbol: str) -> int:
    end_ms = _end_ms(cfg)
    cursor = _resume_cursor_ms(
        conn,
        "SELECT MAX(funding_time) FROM funding WHERE exchange=%s AND symbol=%s",
        (cfg.data.exchange, symbol),
        _config_start_ms(cfg),
        1,  # funding has no fixed grid; resume 1ms past the newest stored event
    )
    inserted = 0
    while cursor < end_ms:
        raw = client.funding_rate(symbol, cursor, end_ms)
        if not raw:
            break
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO funding (exchange, symbol, funding_time, funding_rate, mark_price)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                [(cfg.data.exchange, symbol, *parse_funding(r)) for r in raw],
            )
        conn.commit()
        inserted += len(raw)
        cursor = int(raw[-1]["fundingTime"]) + 1
        if len(raw) < FUNDING_MAX_LIMIT:
            break
    return inserted


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config()
    client = BinanceUsdm(cfg.ingest)

    with connect(cfg.db) as conn:
        apply_schema(conn)
        ingest_symbols(client, conn, cfg)
        log.info("symbols table refreshed for %d universe entries", len(cfg.data.universe))

        for symbol in cfg.data.universe:
            n_bars = ingest_ohlcv(client, conn, cfg, symbol)
            n_prem = ingest_premium_index(client, conn, cfg, symbol)
            n_fund = ingest_funding(client, conn, cfg, symbol)
            log.info(
                "%s: +%d ohlcv bars, +%d premium bars, +%d funding events",
                symbol,
                n_bars,
                n_prem,
                n_fund,
            )

        from src.ingest.gaps import scan_and_store
        from src.ingest.provenance import write_provenance

        n_gaps = scan_and_store(conn, cfg)
        log.info("gap scan complete: %d interior gaps recorded", n_gaps)
        path = write_provenance(conn, cfg)
        log.info("provenance written to %s", path)


if __name__ == "__main__":
    main()
