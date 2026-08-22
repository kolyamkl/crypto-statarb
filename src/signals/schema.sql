-- Processed-layer schema (Milestone M3). Derived series, regenerated whenever
-- code or config changes — hence ON CONFLICT ... DO UPDATE in the writer.

-- One row per book pair per bar. `position` is the DESIRED spread position
-- decided at the close of open_time; M4 executes it on the NEXT bar.
CREATE TABLE IF NOT EXISTS pair_signal (
    exchange  TEXT NOT NULL,
    interval  TEXT NOT NULL,
    leg_y     TEXT NOT NULL,
    leg_x     TEXT NOT NULL,
    open_time TIMESTAMPTZ NOT NULL,
    beta      DOUBLE PRECISION NOT NULL,  -- lagged Kalman hedge ratio usable at t
    spread    DOUBLE PRECISION NOT NULL,  -- Kalman innovation (log space)
    z         DOUBLE PRECISION,           -- NULL during the rolling-window warm-up
    position  SMALLINT NOT NULL,          -- +1 long spread / -1 short / 0 flat
    PRIMARY KEY (exchange, interval, leg_y, leg_x, open_time)
);
