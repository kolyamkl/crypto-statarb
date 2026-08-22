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
