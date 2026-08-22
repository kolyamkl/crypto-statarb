-- Processed-layer schema (Milestone M2). Separate from the raw layer by design:
-- raw tables are exact Decimal facts from the exchange; this table is DERIVED
-- statistics (float is fine) that legitimately change when code or params change,
-- hence ON CONFLICT ... DO UPDATE upserts in the writer.

-- One row per screened pair per training cutoff. leg_y/leg_x record the chosen
-- regression direction: log(leg_y) = alpha + beta * log(leg_x) + spread.
CREATE TABLE IF NOT EXISTS pair_screen (
    exchange       TEXT NOT NULL,
    interval       TEXT NOT NULL,
    train_end      DATE NOT NULL,           -- selection used data <= this day only
    leg_y          TEXT NOT NULL,
    leg_x          TEXT NOT NULL,
    n_bars         INTEGER NOT NULL,        -- joint (inner-join) bars in the window
    alpha          DOUBLE PRECISION NOT NULL,
    beta           DOUBLE PRECISION NOT NULL,
    eg_p           DOUBLE PRECISION NOT NULL,  -- Engle-Granger p, chosen direction
    eg_p_reverse   DOUBLE PRECISION NOT NULL,  -- opposite direction
    eg_p_max       DOUBLE PRECISION NOT NULL,  -- conservative screen statistic
    half_life_bars DOUBLE PRECISION,         -- NULL: spread shows no mean reversion
    ret_corr       DOUBLE PRECISION NOT NULL,  -- descriptive only, never a filter
    passed         BOOLEAN NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (exchange, interval, train_end, leg_y, leg_x)
);
