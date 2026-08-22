-- Processed-layer schema (Milestone M4). Derived series, regenerated whenever
-- code or config changes — hence ON CONFLICT ... DO UPDATE in the writer.

-- Per-bar PnL decomposition on unit pair capital. Weights are the position
-- HELD during the bar (decided the bar before, filled at this bar's open).
CREATE TABLE IF NOT EXISTS pair_backtest (
    exchange  TEXT NOT NULL,
    interval  TEXT NOT NULL,
    leg_y     TEXT NOT NULL,
    leg_x     TEXT NOT NULL,
    open_time TIMESTAMPTZ NOT NULL,
    w_y       DOUBLE PRECISION NOT NULL,
    w_x       DOUBLE PRECISION NOT NULL,
    gross     DOUBLE PRECISION NOT NULL,
    fee       DOUBLE PRECISION NOT NULL,
    slip      DOUBLE PRECISION NOT NULL,
    funding   DOUBLE PRECISION NOT NULL,  -- signed pnl: negative when we pay
    net       DOUBLE PRECISION NOT NULL,  -- gross - fee - slip + funding, exactly
    PRIMARY KEY (exchange, interval, leg_y, leg_x, open_time)
);
