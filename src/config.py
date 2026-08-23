"""Typed access to config.yaml and .env.

Every module reads parameters through here — nothing downstream may hard-code a
value that belongs in config.yaml (SPEC.md working agreement).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class DataConfig:
    exchange: str
    interval: str
    start_date: str  # ISO date; symbols listed later simply start at listing
    end_date: str | None  # None = up to the most recent complete bar
    universe: list[str]


@dataclass(frozen=True)
class IngestConfig:
    request_timeout_s: float
    max_retries: int
    retry_backoff_s: float
    min_request_interval_s: float


@dataclass(frozen=True)
class GridConfig:
    kalman_delta: list[float]
    entry_z: list[float]
    exit_z: list[float]
    stop_z: list[float]
    zscore_window_bars: list[int]


@dataclass(frozen=True)
class WalkforwardConfig:
    train_bars: int
    test_bars: int
    max_pairs: int


@dataclass(frozen=True)
class ValidationConfig:
    train_end: str  # ISO date; last day visible to any selection/tuning step (M2-M4)
    grid: GridConfig
    min_trades_per_year: float
    walkforward: WalkforwardConfig


@dataclass(frozen=True)
class KalmanConfig:
    delta: float  # state-to-observation noise ratio; larger = faster-moving beta
    burn_in_bars: int  # OLS warm-up used to initialize the filter state


@dataclass(frozen=True)
class PairsConfig:
    price_field: str
    use_log_prices: bool
    min_overlap_bars: int
    adf_alpha: float
    half_life_min_bars: float
    half_life_max_bars: float
    kalman: KalmanConfig


@dataclass(frozen=True)
class SignalsConfig:
    book: list[tuple[str, str]]  # (leg_y, leg_x) in the M2 regression direction
    zscore_window_bars: int
    entry_z: float
    exit_z: float
    stop_z: float


@dataclass(frozen=True)
class BacktestConfig:
    taker_fee_bps: float
    slippage_bps: float


@dataclass(frozen=True)
class RobustnessConfig:
    cost_multipliers: list[float]
    regime_window_bars: int
    rolling_eg_window_bars: int
    rolling_eg_step_bars: int


@dataclass(frozen=True)
class DbConfig:
    host: str
    port: int
    user: str
    password: str
    dbname: str

    @property
    def dsn(self) -> str:
        return (
            f"host={self.host} port={self.port} user={self.user} "
            f"password={self.password} dbname={self.dbname}"
        )


@dataclass(frozen=True)
class Config:
    data: DataConfig
    validation: ValidationConfig
    pairs: PairsConfig
    signals: SignalsConfig
    backtest: BacktestConfig
    robustness: RobustnessConfig
    ingest: IngestConfig
    db: DbConfig


def load_config(path: Path | None = None) -> Config:
    load_dotenv(REPO_ROOT / ".env")
    with open(path or REPO_ROOT / "config.yaml") as f:
        raw = yaml.safe_load(f)

    return Config(
        data=DataConfig(
            exchange=raw["data"]["exchange"],
            interval=raw["data"]["interval"],
            start_date=raw["data"]["start_date"],
            end_date=raw["data"]["end_date"],
            universe=list(raw["data"]["universe"]),
        ),
        validation=ValidationConfig(
            train_end=raw["validation"]["train_end"],
            grid=GridConfig(
                kalman_delta=[float(v) for v in raw["validation"]["grid"]["kalman_delta"]],
                entry_z=[float(v) for v in raw["validation"]["grid"]["entry_z"]],
                exit_z=[float(v) for v in raw["validation"]["grid"]["exit_z"]],
                stop_z=[float(v) for v in raw["validation"]["grid"]["stop_z"]],
                zscore_window_bars=[
                    int(v) for v in raw["validation"]["grid"]["zscore_window_bars"]
                ],
            ),
            min_trades_per_year=float(raw["validation"]["min_trades_per_year"]),
            walkforward=WalkforwardConfig(
                train_bars=int(raw["validation"]["walkforward"]["train_bars"]),
                test_bars=int(raw["validation"]["walkforward"]["test_bars"]),
                max_pairs=int(raw["validation"]["walkforward"]["max_pairs"]),
            ),
        ),
        pairs=PairsConfig(
            price_field=raw["pairs"]["price_field"],
            use_log_prices=bool(raw["pairs"]["use_log_prices"]),
            min_overlap_bars=int(raw["pairs"]["min_overlap_bars"]),
            adf_alpha=float(raw["pairs"]["adf_alpha"]),
            half_life_min_bars=float(raw["pairs"]["half_life_min_bars"]),
            half_life_max_bars=float(raw["pairs"]["half_life_max_bars"]),
            kalman=KalmanConfig(
                delta=float(raw["pairs"]["kalman"]["delta"]),
                burn_in_bars=int(raw["pairs"]["kalman"]["burn_in_bars"]),
            ),
        ),
        signals=SignalsConfig(
            book=[(str(y), str(x)) for y, x in raw["signals"]["book"]],
            zscore_window_bars=int(raw["signals"]["zscore_window_bars"]),
            entry_z=float(raw["signals"]["entry_z"]),
            exit_z=float(raw["signals"]["exit_z"]),
            stop_z=float(raw["signals"]["stop_z"]),
        ),
        backtest=BacktestConfig(
            taker_fee_bps=float(raw["backtest"]["taker_fee_bps"]),
            slippage_bps=float(raw["backtest"]["slippage_bps"]),
        ),
        robustness=RobustnessConfig(
            cost_multipliers=[float(v) for v in raw["robustness"]["cost_multipliers"]],
            regime_window_bars=int(raw["robustness"]["regime_window_bars"]),
            rolling_eg_window_bars=int(raw["robustness"]["rolling_eg_window_bars"]),
            rolling_eg_step_bars=int(raw["robustness"]["rolling_eg_step_bars"]),
        ),
        ingest=IngestConfig(
            request_timeout_s=float(raw["ingest"]["request_timeout_s"]),
            max_retries=int(raw["ingest"]["max_retries"]),
            retry_backoff_s=float(raw["ingest"]["retry_backoff_s"]),
            min_request_interval_s=float(raw["ingest"]["min_request_interval_s"]),
        ),
        db=DbConfig(
            host=os.environ.get("POSTGRES_HOST", "localhost"),
            port=int(os.environ.get("POSTGRES_PORT", "5433")),
            user=os.environ.get("POSTGRES_USER", "statarb"),
            password=os.environ.get("POSTGRES_PASSWORD", "statarb"),
            dbname=os.environ.get("POSTGRES_DB", "statarb"),
        ),
    )
