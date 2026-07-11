"""Sanity-check plots for eyeballing ingested data: `uv run python -m src.ingest.sanity_plot`.

Writes PNGs to data/plots/ (gitignored). This is a looking-at-the-data step, not
analysis — M2 does the real work.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # headless: we save files, never open windows

import matplotlib.pyplot as plt
import pandas as pd
import psycopg

from src.config import REPO_ROOT, Config, load_config

PLOTS_DIR = REPO_ROOT / "data" / "plots"


def _df(conn: psycopg.Connection, query: str, params: tuple, columns: list[str]) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(query, params)
        df = pd.DataFrame(cur.fetchall(), columns=columns)
    for col in columns[1:]:
        df[col] = df[col].astype(float)  # Decimal -> float is fine for plotting
    return df.set_index(columns[0])


def plot_closes(conn: psycopg.Connection, cfg: Config, symbols: list[str]) -> None:
    fig, ax = plt.subplots(figsize=(12, 6))
    for symbol in symbols:
        df = _df(
            conn,
            """SELECT open_time, close FROM ohlcv
               WHERE exchange=%s AND market='perp' AND symbol=%s AND interval=%s
               ORDER BY open_time""",
            (cfg.data.exchange, symbol, cfg.data.interval),
            ["open_time", "close"],
        )
        if df.empty:
            continue
        # Normalize to 1.0 at each symbol's own first bar so different price scales share one axis
        ax.plot(df.index, df["close"] / df["close"].iloc[0], label=symbol, linewidth=0.8)
    ax.set_yscale("log")
    ax.set_title(f"Normalized close ({cfg.data.interval} bars, log scale)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "closes.png", dpi=120)
    plt.close(fig)


def plot_funding(conn: psycopg.Connection, cfg: Config, symbol: str) -> None:
    df = _df(
        conn,
        """SELECT funding_time, funding_rate FROM funding
           WHERE exchange=%s AND symbol=%s ORDER BY funding_time""",
        (cfg.data.exchange, symbol),
        ["funding_time", "funding_rate"],
    )
    if df.empty:
        return
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(df.index, df["funding_rate"] * 1e4, linewidth=0.5, alpha=0.5, label="per-8h rate (bps)")
    # 90-event window = 30 days of 8-hourly funding; smooths enough to see regimes
    ax.plot(df.index, (df["funding_rate"] * 1e4).rolling(90).mean(), linewidth=1.2,
            label="30-day rolling mean")
    ax.axhline(0, color="grey", linewidth=0.6)
    ax.set_title(f"{symbol} funding rate (basis points per 8h)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / f"funding_{symbol}.png", dpi=120)
    plt.close(fig)


def plot_premium(conn: psycopg.Connection, cfg: Config, symbol: str) -> None:
    df = _df(
        conn,
        """SELECT open_time, close FROM premium_index
           WHERE exchange=%s AND symbol=%s AND interval=%s ORDER BY open_time""",
        (cfg.data.exchange, symbol, cfg.data.interval),
        ["open_time", "close"],
    )
    if df.empty:
        return
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(df.index, df["close"] * 1e4, linewidth=0.5, alpha=0.7)
    ax.axhline(0, color="grey", linewidth=0.6)
    ax.set_title(f"{symbol} perp premium vs index (bps, {cfg.data.interval} close)")
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / f"premium_{symbol}.png", dpi=120)
    plt.close(fig)


def main() -> None:
    cfg = load_config()
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(cfg.db.dsn) as conn:
        plot_closes(conn, cfg, ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"])
        plot_funding(conn, cfg, "BTCUSDT")
        plot_premium(conn, cfg, "BTCUSDT")
    print(f"plots written to {PLOTS_DIR}")


if __name__ == "__main__":
    main()
