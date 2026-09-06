.PHONY: db-up db-down deps test ingest pairs signals backtest validate metrics report figures all figures-equities \
	ingest-equities pairs-equities signals-equities backtest-equities validate-equities \
	metrics-equities report-equities all-equities

# M10 equity study: same pipeline, config-switched (M10_PLAN.md).
EQ = STATARB_CONFIG=config_equities.yaml

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

pairs:
	uv run python -m src.pairs.run

signals:
	uv run python -m src.signals.run

backtest:
	uv run python -m src.backtest.run

validate:
	uv run python -m src.validate.run

metrics:
	uv run python -m src.metrics.run

report:
	uv run python -m src.report.run

# Promote the README figures from gitignored data/plots/ to the committed
# reports/figures/ so the writeup renders on GitHub without the data.
figures:
	mkdir -p reports/figures
	cp data/plots/m3/AVAXUSDT_NEARUSDT.png reports/figures/spread_AVAX_NEAR.png
	cp data/plots/m5/static_split.png reports/figures/static_split.png
	cp data/plots/m6/test_vs_benchmarks.png reports/figures/test_vs_benchmarks.png
	cp data/plots/m6/walkforward.png reports/figures/walkforward.png
	cp data/plots/m7/grid_train_vs_test.png reports/figures/grid_train_vs_test.png
	cp data/plots/m7/rolling_eg.png reports/figures/rolling_eg.png

# One command reproduces every table and figure in the README from raw data
# (SPEC.md reproducibility requirement). Ingest ~40min, validate ~2h.
all: ingest test pairs signals backtest validate metrics report figures

# ---- M10 equity study (outputs isolated under reports/m10/, data/plots/m10/) ----

ingest-equities: db-up deps
	$(EQ) uv run python -m src.ingest.equities

pairs-equities:
	$(EQ) uv run python -m src.pairs.run

signals-equities:
	$(EQ) uv run python -m src.signals.run

backtest-equities:
	$(EQ) uv run python -m src.backtest.run

validate-equities:
	$(EQ) uv run python -m src.validate.run

metrics-equities:
	$(EQ) uv run python -m src.metrics.run

report-equities:
	$(EQ) uv run python -m src.report.run

figures-equities:
	mkdir -p reports/figures
	cp data/plots/m10/m5/static_split.png reports/figures/m10_static_split.png
	cp data/plots/m10/m6/test_vs_benchmarks.png reports/figures/m10_test_vs_benchmarks.png
	cp data/plots/m10/m7/rolling_eg.png reports/figures/m10_rolling_eg.png

# One command reproduces the entire equity study (M10_PLAN.md DoD). Daily bars,
# so the whole chain runs in minutes, not hours.
all-equities: ingest-equities test pairs-equities signals-equities backtest-equities \
	validate-equities metrics-equities report-equities figures-equities
