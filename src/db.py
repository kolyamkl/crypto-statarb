"""Postgres connection helper. Raw SQL via psycopg — no ORM, by design (DECISIONS.md)."""

from __future__ import annotations

from pathlib import Path

import psycopg

from src.config import DbConfig

SCHEMA_PATH = Path(__file__).resolve().parent / "ingest" / "schema.sql"


def connect(cfg: DbConfig) -> psycopg.Connection:
    return psycopg.connect(cfg.dsn)


def apply_schema(conn: psycopg.Connection) -> None:
    """Idempotent: schema.sql uses CREATE TABLE IF NOT EXISTS throughout."""
    conn.execute(SCHEMA_PATH.read_text())
    conn.commit()
