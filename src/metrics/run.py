"""M6 orchestrator: `uv run python -m src.metrics.run`.

One clean results table + figures, reproducibly (SPEC.md M6): re-derives the
frozen M5 static configuration (fast — the grid search is seconds), reads the
persisted walk-forward OOS series if present, and benchmarks everything against
buy-and-hold BTC and ETH on identical accounting. All strategy numbers are net
of costs; benchmark rows carry no cost model (a single entry fee would be
negligible at this horizon) — stated in the report.
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless: this module only writes files, never opens windows
import matplotlib.pyplot as plt
import pandas as pd

from src.config import load_config
from src.db import connect
from src.backtest.funding import funding_rate_per_bar
from src.metrics.core import BARS_PER_YEAR, avg_holding_bars, full_summary, trade_pnls
from src.pairs.data import load_close_panel, train_cutoff
from src.validate.run import FULL_HISTORY_END, OOS_CSV, static_split

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = REPO_ROOT / "reports" / "m6_metrics.md"
PLOT_DIR = REPO_ROOT / "data" / "plots" / "m6"

BENCHMARKS = ["BTCUSDT", "ETHUSDT"]


def benchmark_frame(closes: pd.Series) -> pd.DataFrame:
    """Buy-and-hold on unit capital, same arithmetic accounting as the engine."""
    ret = closes.pct_change().fillna(0.0)
    return pd.DataFrame({"net": ret, "gross": ret, "fee": 0.0, "slip": 0.0, "funding": 0.0})


def oos_frame(oos: pd.Series) -> pd.DataFrame:
    """The stitched walk-forward series is already net; costs are embedded in it,
    so gross/costs columns are not separable for this row."""
    return pd.DataFrame(
        {"net": oos, "gross": float("nan"), "fee": float("nan"), "slip": float("nan"),
         "funding": float("nan")}
    )


def portfolio_extras(frames: list[pd.DataFrame], interval: str) -> dict[str, float]:
    """Trade-level stats aggregated across the book's pairs (portfolio_curve
    drops the weight columns, so these are pooled from the per-pair frames)."""
    pnls = [p for f in frames for p in trade_pnls(f)]
    holds = [(avg_holding_bars(f), len(trade_pnls(f))) for f in frames]
    n_trades = sum(n for _, n in holds)
    years = len(frames[0]) / BARS_PER_YEAR[interval]
    any_active = pd.concat([(f["w_y"] != 0) for f in frames], axis=1).any(axis=1)
    return {
        "trades": n_trades,
        "hit_rate": float(pd.Series([p > 0 for p in pnls]).mean()) if pnls else float("nan"),
        "avg_hold_bars": (
            sum(h * n for h, n in holds if n) / n_trades if n_trades else float("nan")
        ),
        "ann_turnover": sum(float(f["turnover"].sum()) for f in frames) / len(frames) / years,
        "pct_in_market": 100.0 * float(any_active.mean()),
    }


def fmt(value: float, spec: str, scale: float = 1.0) -> str:
    if value is None or pd.isna(value):
        return "—"
    return format(value * scale, spec)


def stats_row(name: str, s: dict[str, float]) -> str:
    cells = [
        fmt(s.get("net"), "+.2f", 100) + "%",
        fmt(s.get("gross"), "+.2f", 100) + "%" if not pd.isna(s.get("gross", float("nan"))) else "—",
        fmt(s.get("costs"), ".2f", 100) + "%" if not pd.isna(s.get("costs", float("nan"))) else "—",
        fmt(s.get("sharpe"), "+.2f"),
        fmt(s.get("sortino"), "+.2f"),
        fmt(s.get("max_dd"), "+.2f", 100) + "%",
        fmt(s.get("hit_rate"), ".0%") if "hit_rate" in s else "—",
        fmt(s.get("avg_hold_bars"), ".0f") + "h" if "avg_hold_bars" in s else "—",
        fmt(s.get("ann_turnover"), ".1f") + "x" if "ann_turnover" in s else "—",
        fmt(s.get("pct_in_market"), ".0f") + "%" if "pct_in_market" in s else "—",
    ]
    return f"| {name} | " + " | ".join(cells) + " |"


def equity_drawdown_plot(series: dict[str, pd.Series], title: str, fname: str) -> Path:
    """Top: cumulative arithmetic PnL. Bottom: drawdown of the FIRST series."""
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(12, 7), sharex=True, height_ratios=[2, 1]
    )
    for label, net in series.items():
        ax1.plot(net.index, net.cumsum() * 100, label=label, lw=1.0)
    ax1.axhline(0, color="grey", lw=0.6)
    ax1.set_ylabel("% of unit capital")
    ax1.set_title(title)
    ax1.legend(loc="best", fontsize=8)

    first = next(iter(series.values()))
    equity = first.cumsum()
    drawdown = (equity - equity.cummax()) * 100
    ax2.fill_between(drawdown.index, drawdown, 0, alpha=0.5)
    ax2.set_ylabel("drawdown (%)")
    ax2.set_title(f"drawdown: {next(iter(series))}")
    fig.tight_layout()

    PLOT_DIR.mkdir(parents=True, exist_ok=True)
    path = PLOT_DIR / fname
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config()
    interval = cfg.data.interval

    with connect(cfg.db) as conn:
        panel = load_close_panel(conn, cfg, end=FULL_HISTORY_END)
        funding = {
            s: funding_rate_per_bar(conn, cfg, s, FULL_HISTORY_END) for s in cfg.data.universe
        }

    params, _, _, _, port, results = static_split(panel, funding, cfg)
    cutoff = pd.Timestamp(train_cutoff(cfg))
    train = port.loc[port.index < cutoff]
    test = port.loc[port.index >= cutoff]

    train_frames = [f.loc[f.index < cutoff] for f in results.values()]
    test_frames = [f.loc[f.index >= cutoff] for f in results.values()]
    rows: list[tuple[str, dict]] = [
        ("strategy — train (tuned here)",
         full_summary(train, interval) | portfolio_extras(train_frames, interval)),
        ("**strategy — test (untouched)**",
         full_summary(test, interval) | portfolio_extras(test_frames, interval)),
    ]
    oos = None
    if OOS_CSV.exists():
        oos = pd.read_csv(OOS_CSV, index_col=0, parse_dates=True)["net"]
        wf_summary = full_summary(oos_frame(oos), interval)
        # Costs are embedded in the stitched net series, not separable after the fact.
        wf_summary["gross"] = wf_summary["costs"] = wf_summary["funding"] = float("nan")
        rows.append(("**strategy — walk-forward OOS**", wf_summary))
    else:
        log.warning("no %s — run src.validate.run first for the walk-forward row", OOS_CSV)
    for sym in BENCHMARKS:
        for name, window in [("train", train.index), ("test", test.index)]:
            bench = full_summary(benchmark_frame(panel[sym].reindex(window)), interval)
            bench["pct_in_market"] = 100.0  # buy-and-hold is always fully deployed
            rows.append((f"{sym} buy-hold — {name}", bench))

    # Per-pair trade-level stats on the untouched test window.
    pair_rows = [
        (f"{name} — test", full_summary(frame.loc[frame.index >= cutoff], interval))
        for name, frame in results.items()
    ]

    header = (
        "| series | net | gross | costs | Sharpe | Sortino | max DD | hit rate "
        "| avg hold | turnover/yr | exposure |"
    )
    divider = "|" + "---|" * 11
    lines = [
        "# M6 metrics — everything net of costs, benchmarked",
        "",
        "> Auto-generated by `src/metrics/run.py` — do not edit by hand.",
        "",
        f"- Frozen M5 config `{params}`; split at {cfg.validation.train_end}; "
        "arithmetic PnL on unit capital throughout.",
        "- Benchmark rows carry no cost model (one entry fee is negligible at this "
        "horizon); exposure 100% vs the strategy's partial deployment — compare "
        "risk-adjusted (Sharpe/Sortino), not raw net.",
        "- The walk-forward row is net-only: costs are embedded per fold and not "
        "separable after stitching.",
        "- Constant-capital arithmetic accounting means a drawdown is a SUM of "
        "per-bar returns from the peak, so a benchmark's can exceed 100% — it is "
        "not a compounded loss.",
        "",
        header, divider,
        *[stats_row(name, s) for name, s in rows],
        "",
        "## Per-pair, test window",
        "",
        header, divider,
        *[stats_row(name, s) for name, s in pair_rows],
    ]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n")
    log.info("report written to %s", REPORT_PATH)

    log.info("plot: %s", equity_drawdown_plot(
        {"strategy (full history)": port["net"]},
        "frozen config over full history (train + test)", "strategy_full.png",
    ))
    test_series = {"strategy — test": test["net"]}
    for sym in BENCHMARKS:
        test_series[f"{sym} buy-hold"] = panel[sym].reindex(test.index).pct_change().fillna(0.0)
    log.info("plot: %s", equity_drawdown_plot(
        test_series, "untouched test window: strategy vs buy-and-hold", "test_vs_benchmarks.png",
    ))
    if oos is not None:
        log.info("plot: %s", equity_drawdown_plot(
            {"walk-forward OOS": oos}, "stitched walk-forward out-of-sample", "walkforward.png",
        ))


if __name__ == "__main__":
    main()
