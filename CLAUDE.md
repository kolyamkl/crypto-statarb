# crypto-statarb — Working Agreement for Claude Code

Full project spec: `SPEC.md` (single source of truth). This file is the standing agreement
from Section 7 of the spec, plus repo practicalities.

## Rules

- Build milestones **in strict order** (M1 → M9); stop at each Definition of Done and let
  Kolya review before proceeding.
- Prefer **transparent, readable code over cleverness** — every line must be explainable
  in an interview.
- When making a modelling choice (which test, which window, which cost assumption),
  **add a one-line comment explaining why**, and flag the assumption back to Kolya.
- Proactively hunt for **look-ahead bias** in anything with a rolling window or a fit;
  write a test for it.
- Never hard-code parameters that belong in `config.yaml`.
- Never commit data, secrets, or `.env`.
- Keep a running `DECISIONS.md` of methodology choices and trade-offs.
- When something doesn't work, **say so and keep the evidence** — negative results are
  part of the deliverable, not failures to hide.

## Stack & commands

- Python 3.11+ managed with `uv` (deps in `pyproject.toml`, locked in `uv.lock`).
- Postgres 16 via Docker Compose, host port **5433** (not 5432).

```bash
docker compose up -d db      # start Postgres
uv sync                      # install/refresh deps into .venv
uv run pytest                # run tests
uv run python -m src.ingest.run   # M1 ingestion (config-driven)
```

## Layout

See SPEC.md Section 3. `src/` is the source of truth; `notebooks/` is exploration only.
`data/` and `.env` are gitignored.
