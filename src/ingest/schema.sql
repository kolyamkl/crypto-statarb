-- Raw-data schema (Milestone M1). All timestamps are UTC (TIMESTAMPTZ).
-- Prices/rates are NUMERIC (exact decimal), not floats: raw data must round-trip losslessly.
-- Composite primary keys make every ingestion upsert idempotent.

-- Survivorship record: when each symbol became tradeable on the exchange.
-- NOTE (limitation, see data_provenance.md): Binance exchangeInfo only lists
-- CURRENTLY-existing symbols, so coins delisted before ingestion day are invisible.
-- We mitigate by fixing the universe in config.yaml up front and recording onboard dates.
CREATE TABLE IF NOT EXISTS symbols (
    exchange     TEXT NOT NULL,
    symbol       TEXT NOT NULL,
    base_asset   TEXT NOT NULL,
    quote_asset  TEXT NOT NULL,
    status       TEXT NOT NULL,
    onboard_date TIMESTAMPTZ,
    PRIMARY KEY (exchange, symbol)
);

CREATE TABLE IF NOT EXISTS ohlcv (
    exchange     TEXT NOT NULL,
    market       TEXT NOT NULL,          -- 'perp' | 'spot'
    symbol       TEXT NOT NULL,
    interval     TEXT NOT NULL,          -- '15m' | '1h' | ...
    open_time    TIMESTAMPTZ NOT NULL,   -- bar open (UTC)
    open         NUMERIC NOT NULL,
    high         NUMERIC NOT NULL,
    low          NUMERIC NOT NULL,
    close        NUMERIC NOT NULL,
    volume       NUMERIC NOT NULL,       -- base-asset volume
    quote_volume NUMERIC,
    n_trades     BIGINT,
    PRIMARY KEY (exchange, market, symbol, interval, open_time)
);

CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_time ON ohlcv (symbol, open_time);

-- Funding lives in its own table: it ticks on a different clock than candles
-- (8-hourly on Binance USDT-M, hourly on Hyperliquid).
CREATE TABLE IF NOT EXISTS funding (
    exchange     TEXT NOT NULL,
    symbol       TEXT NOT NULL,
    funding_time TIMESTAMPTZ NOT NULL,
    funding_rate NUMERIC NOT NULL,       -- realized per-interval rate (not annualized)
    mark_price   NUMERIC,                -- may be absent in older Binance records
    PRIMARY KEY (exchange, symbol, funding_time)
);

-- Basis series: perp premium vs the underlying index, as candles of
-- (mark - index) / index. Source: Binance premiumIndexKlines.
CREATE TABLE IF NOT EXISTS premium_index (
    exchange   TEXT NOT NULL,
    symbol     TEXT NOT NULL,
    interval   TEXT NOT NULL,
    open_time  TIMESTAMPTZ NOT NULL,
    open       NUMERIC NOT NULL,
    high       NUMERIC NOT NULL,
    low        NUMERIC NOT NULL,
    close      NUMERIC NOT NULL,
    PRIMARY KEY (exchange, symbol, interval, open_time)
);

-- Detected holes in the bar series. Gaps are RECORDED, never forward-filled
-- (SPEC.md M1). Regenerated on every ingestion run by the gap scanner.
CREATE TABLE IF NOT EXISTS data_gaps (
    exchange   TEXT NOT NULL,
    market     TEXT NOT NULL,
    symbol     TEXT NOT NULL,
    interval   TEXT NOT NULL,
    gap_start  TIMESTAMPTZ NOT NULL,     -- first missing bar
    gap_end    TIMESTAMPTZ NOT NULL,     -- last missing bar
    n_missing  INTEGER NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (exchange, market, symbol, interval, gap_start)
);
