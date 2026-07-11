"""Minimal typed client for Binance USDT-M futures PUBLIC market-data endpoints.

Hand-rolled instead of ccxt so that auth-free pagination, throttling, and parsing
stay fully visible and interview-explainable (DECISIONS.md). Only four endpoints:

    GET /fapi/v1/exchangeInfo         -> symbols + onboard dates
    GET /fapi/v1/klines               -> perp OHLCV candles
    GET /fapi/v1/fundingRate          -> realized funding events (8-hourly)
    GET /fapi/v1/premiumIndexKlines   -> perp-vs-index premium candles (basis)
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import requests

from src.config import IngestConfig

log = logging.getLogger(__name__)

BASE_URL = "https://fapi.binance.com"
KLINES_MAX_LIMIT = 1500
FUNDING_MAX_LIMIT = 1000

INTERVAL_MS: dict[str, int] = {
    "15m": 15 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
}


def ms_to_utc(ms: int) -> datetime:
    """Binance timestamps are epoch milliseconds; we store tz-aware UTC everywhere."""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def parse_kline(raw: list[Any]) -> tuple:
    """One /fapi/v1/klines row -> (open_time, o, h, l, c, volume, quote_volume, n_trades).

    Raw layout: [openTime, open, high, low, close, volume, closeTime,
                 quoteVolume, nTrades, takerBase, takerQuote, ignore].
    Decimal (not float) so raw prices round-trip losslessly into NUMERIC columns.
    """
    return (
        ms_to_utc(int(raw[0])),
        Decimal(raw[1]),
        Decimal(raw[2]),
        Decimal(raw[3]),
        Decimal(raw[4]),
        Decimal(raw[5]),
        Decimal(raw[7]),
        int(raw[8]),
    )


def parse_premium_kline(raw: list[Any]) -> tuple:
    """premiumIndexKlines shares the kline layout, but volume/trade fields are zeros."""
    return (
        ms_to_utc(int(raw[0])),
        Decimal(raw[1]),
        Decimal(raw[2]),
        Decimal(raw[3]),
        Decimal(raw[4]),
    )


def parse_funding(raw: dict[str, Any]) -> tuple:
    """One /fapi/v1/fundingRate item -> (funding_time, funding_rate, mark_price|None)."""
    mark = raw.get("markPrice")
    return (
        ms_to_utc(int(raw["fundingTime"])),
        Decimal(raw["fundingRate"]),
        Decimal(mark) if mark not in (None, "") else None,
    )


class BinanceUsdm:
    def __init__(self, cfg: IngestConfig) -> None:
        self._cfg = cfg
        self._session = requests.Session()
        self._last_request_at = 0.0

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Throttled GET with exponential-backoff retries; respects 429 Retry-After."""
        for attempt in range(self._cfg.max_retries + 1):
            # Throttle: keep a minimum spacing between request starts so we stay
            # well under Binance's 2400 weight/min IP limit.
            wait = self._cfg.min_request_interval_s - (time.monotonic() - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
            self._last_request_at = time.monotonic()

            try:
                resp = self._session.get(
                    f"{BASE_URL}{path}", params=params, timeout=self._cfg.request_timeout_s
                )
            except requests.RequestException as exc:
                if attempt == self._cfg.max_retries:
                    raise
                backoff = self._cfg.retry_backoff_s * 2**attempt
                log.warning("network error on %s (%s); retrying in %.1fs", path, exc, backoff)
                time.sleep(backoff)
                continue

            if resp.status_code == 200:
                return resp.json()

            if resp.status_code in (429, 418):  # rate-limited / temporary IP ban
                backoff = float(resp.headers.get("Retry-After", self._cfg.retry_backoff_s * 2**attempt))
                log.warning("HTTP %s on %s; backing off %.1fs", resp.status_code, path, backoff)
                time.sleep(backoff)
                continue

            resp.raise_for_status()

        raise RuntimeError(f"exhausted retries for {path}")

    def exchange_info(self) -> list[dict[str, Any]]:
        return self._get("/fapi/v1/exchangeInfo")["symbols"]

    def klines(self, symbol: str, interval: str, start_ms: int, end_ms: int) -> list[list[Any]]:
        return self._get(
            "/fapi/v1/klines",
            {
                "symbol": symbol,
                "interval": interval,
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": KLINES_MAX_LIMIT,
            },
        )

    def premium_index_klines(
        self, symbol: str, interval: str, start_ms: int, end_ms: int
    ) -> list[list[Any]]:
        return self._get(
            "/fapi/v1/premiumIndexKlines",
            {
                "symbol": symbol,
                "interval": interval,
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": KLINES_MAX_LIMIT,
            },
        )

    def funding_rate(self, symbol: str, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
        return self._get(
            "/fapi/v1/fundingRate",
            {
                "symbol": symbol,
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": FUNDING_MAX_LIMIT,
            },
        )
