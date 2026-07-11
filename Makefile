.PHONY: db-up db-down deps test ingest all

db-up:
	docker compose up -d db

db-down:
	docker compose down

deps:
	uv sync

test:
	uv run pytest -q

ingest: db-up deps
	uv run python -m src.ingest.run

# Will grow milestone by milestone until it reproduces every figure and metric
# in the README from raw data (SPEC.md §3 reproducibility requirement).
all: ingest test
