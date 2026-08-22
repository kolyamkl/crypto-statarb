"""Unit tests for the M1 ingestion layer — pure functions only, no network/DB.

Focus: the places where silent data corruption hides (timestamp handling,
raw-row parsing, gap detection).
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.ingest.binance import (
    INTERVAL_MS,
    ms_to_utc,
    parse_funding,
    parse_kline,
    parse_premium_kline,
)
from src.ingest.gaps import find_gaps

H = INTERVAL_MS["1h"]
T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
T0_MS = int(T0.timestamp() * 1000)


def _bar(i: int) -> datetime:
    return T0 + timedelta(hours=i)


# --- timestamps ---------------------------------------------------------------


def test_ms_to_utc_is_tz_aware_utc():
    dt = ms_to_utc(T0_MS)
    assert dt == T0
    assert dt.tzinfo is not None and dt.utcoffset().total_seconds() == 0


def test_interval_ms_matches_timedelta():
    assert timedelta(milliseconds=INTERVAL_MS["1h"]) == timedelta(hours=1)
    assert timedelta(milliseconds=INTERVAL_MS["15m"]) == timedelta(minutes=15)


# --- raw-row parsing ----------------------------------------------------------

RAW_KLINE = [
    T0_MS, "42000.10", "42100.00", "41900.50", "42050.00", "123.456",
    T0_MS + H - 1, "5190000.12", 9876, "60.0", "2520000.0", "0",
]


def test_parse_kline_exact_decimals_and_utc():
    open_time, o, h, lo, c, vol, qvol, n = parse_kline(RAW_KLINE)
    assert open_time == T0
    # Decimal, not float: raw prices must round-trip losslessly into NUMERIC columns
    assert c == Decimal("42050.00") and isinstance(c, Decimal)
    assert (o, h, lo) == (Decimal("42000.10"), Decimal("42100.00"), Decimal("41900.50"))
    assert vol == Decimal("123.456") and qvol == Decimal("5190000.12") and n == 9876


def test_parse_premium_kline_takes_only_ohlc():
    parsed = parse_premium_kline([T0_MS, "0.0001", "0.0002", "-0.0001", "0.00015",
                                  "0", T0_MS + H - 1, "0", 0, "0", "0", "0"])
    assert parsed == (T0, Decimal("0.0001"), Decimal("0.0002"),
                      Decimal("-0.0001"), Decimal("0.00015"))


def test_parse_funding_with_and_without_mark_price():
    ft, rate, mark = parse_funding(
        {"symbol": "BTCUSDT", "fundingTime": T0_MS, "fundingRate": "-0.00012", "markPrice": "42000.1"}
    )
    assert (ft, rate, mark) == (T0, Decimal("-0.00012"), Decimal("42000.1"))
    # Older Binance records ship markPrice as "" — must map to NULL, not crash
    _, _, mark_empty = parse_funding(
        {"symbol": "BTCUSDT", "fundingTime": T0_MS, "fundingRate": "0.0001", "markPrice": ""}
    )
    assert mark_empty is None


# --- gap detection ------------------------------------------------------------


def test_no_gaps_in_contiguous_series():
    assert find_gaps([_bar(i) for i in range(10)], H) == []


def test_single_gap_bounds_and_count():
    # bars 0,1,2 then 6,7 -> bars 3,4,5 missing
    times = [_bar(i) for i in [0, 1, 2, 6, 7]]
    assert find_gaps(times, H) == [(_bar(3), _bar(5), 3)]


def test_multiple_gaps():
    times = [_bar(i) for i in [0, 2, 3, 10]]
    assert find_gaps(times, H) == [(_bar(1), _bar(1), 1), (_bar(4), _bar(9), 6)]


def test_empty_and_singleton_series_have_no_gaps():
    assert find_gaps([], H) == []
    assert find_gaps([_bar(0)], H) == []
