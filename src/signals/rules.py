"""M3 trading rules: z-score -> desired spread position, as a tiny state machine.

Position semantics (in units of the spread = long leg_y, short beta*leg_x):
    +1  long the spread   (entered when z <= -entry_z: spread is cheap)
    -1  short the spread  (entered when z >= +entry_z: spread is rich)
     0  flat

Rules (SPEC.md M3, thresholds tunable in config, never here):
    enter when |z| >= entry_z, exit when z reverts through exit_z toward the
    mean, stop out when |z| >= stop_z (the equilibrium may have broken).

Re-arm guard: after ANY flat transition (exit or stop), a new entry is allowed
only once |z| has first come back inside the entry band. Without this, a
stopped-out position at |z| > 3 would instantly re-enter on the next bar
(|z| >= 2 still true) — re-buying the exact dislocation we just refused to hold.

The position at index t is the DESIRED position decided at the close of bar t;
execution on the next bar (and all PnL) is M4's job.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def cancel_entries_without_positive_beta(desired: pd.Series, beta: pd.Series) -> pd.Series:
    """Cancel whole trade episodes whose ENTRY-bar hedge ratio is not positive.

    The 1:beta sizing only makes sense for beta > 0 — a non-positive estimate
    means the filter thinks the 'pair' is long-long (or degenerate), and a live
    desk would simply not put the trade on. Discovered the hard way in M5's
    walk-forward: freshly screened pairs can have Kalman betas that dip negative
    even when the training-window OLS beta was positive. Cancelling the whole
    episode (not just masking bars) keeps the state machine's semantics intact.
    """
    out = desired.to_numpy().copy()
    beta_values = beta.to_numpy()
    cancelled = False
    prev = 0
    for i, s in enumerate(out):
        if s != 0 and prev == 0:  # entry decided at this bar, using this bar's beta
            cancelled = not beta_values[i] > 0
        elif s == 0:
            cancelled = False
        prev = s
        if cancelled:
            out[i] = 0
    return pd.Series(out, index=desired.index, name=desired.name)


def positions_from_z(z: pd.Series, entry_z: float, exit_z: float, stop_z: float) -> pd.Series:
    """Explicit bar-by-bar loop, on purpose: a vectorised state machine is
    clever but unreviewable, and 35k iterations of this are instant."""
    values = z.to_numpy()
    out = np.zeros(len(values), dtype=np.int8)
    pos = 0
    armed = False  # becomes True only when |z| is inside the entry band

    for i, zt in enumerate(values):
        if np.isnan(zt):  # warm-up: not tradeable, stay flat and disarmed
            out[i] = pos
            continue

        if pos == 0:
            if abs(zt) < entry_z:
                armed = True
            elif armed:
                if abs(zt) >= stop_z:
                    # z jumped straight past the stop level: entering here means
                    # buying a possibly-broken equilibrium — skip and re-arm later.
                    armed = False
                else:
                    pos = -1 if zt > 0 else 1
                    armed = False
        elif pos == -1:  # short the spread, profits as z falls to the mean
            if zt >= stop_z or zt <= exit_z:
                pos = 0
        else:  # pos == +1, long the spread, profits as z rises to the mean
            if zt <= -stop_z or zt >= -exit_z:
                pos = 0

        out[i] = pos

    return pd.Series(out, index=z.index, name="position")
