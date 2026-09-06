"""Study-aware output locations.

The equity study (M10) must never overwrite the v1 crypto outputs — those are
pinned by the v1.0 tag. Every run module resolves its report/plot paths through
here: an empty `reports_subdir` reproduces the v1 layout byte-for-byte, and
`subdir: m10` isolates the equity study under reports/m10/ and data/plots/m10/.
"""

from __future__ import annotations

from pathlib import Path

from src.config import REPO_ROOT, Config


def report_path(cfg: Config, filename: str) -> Path:
    base = REPO_ROOT / "reports"
    return (base / cfg.reports_subdir if cfg.reports_subdir else base) / filename


def plot_dir(cfg: Config, stage: str) -> Path:
    base = REPO_ROOT / "data" / "plots"
    return (base / cfg.reports_subdir if cfg.reports_subdir else base) / stage


def oos_csv_path(cfg: Config) -> Path:
    base = REPO_ROOT / "data"
    return (base / cfg.reports_subdir if cfg.reports_subdir else base) / "m5_walkforward_oos.csv"
