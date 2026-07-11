"""Skeleton sanity: config parses and declares the fields every module relies on."""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_config() -> dict:
    with open(REPO_ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


def test_config_parses_and_has_required_fields():
    cfg = load_config()
    assert cfg["data"]["interval"] in {"15m", "1h", "4h"}
    assert len(cfg["data"]["universe"]) >= 2, "need at least two symbols to form a pair"
    assert cfg["data"]["start_date"] < "2026-01-01"


def test_universe_has_no_duplicates():
    universe = load_config()["data"]["universe"]
    assert len(universe) == len(set(universe))
