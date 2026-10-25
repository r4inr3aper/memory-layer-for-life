.PHONY: install dev dev-lan worker schedules test test-unit test-integration test-contract test-golden coverage lint format typecheck migrate migrate-down migration eval import-eval-reports connection-check ui-install ui-dev ui-build ui-check docker-up docker-down docker-build check

install:
	uv sync --all-extras

dev:
	uvicorn app.main:app --reload --port 8000

# Reachable from a phone on the same network, for the mobile app. Only on a trusted network:
# the memory and console routes have no sign-in.
dev-lan:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Processes queued runs: retries that are due, and units captured without an API key.
worker:
	python -m scripts.process_pending

# Runs due scheduled tasks on its own. The API also does this while SCHEDULER_ENABLED is true.
schedules:
	python -m scripts.run_schedules --watch 60

test:
	pytest tests/ -v

test-unit:
	pytest tests/unit/ -v

test-integration:
	pytest tests/integration/ -v

test-contract:
	pytest tests/contract/ -v

test-golden:
	pytest tests/golden/ tests/integration/test_golden_pipeline.py -v

coverage:
	coverage run -m pytest tests/ -q
	coverage report

lint:
	ruff check .

format:
	ruff format .

typecheck:
	mypy

migrate:
	alembic upgrade head

migrate-down:
	alembic downgrade -1

migration:
	alembic revision --autogenerate -m "$(msg)"

# Live model evaluation. Calls the Anthropic API, so it costs money.
eval:
	python -m scripts.run_golden_eval

# Stores report files from earlier evaluations so the console can show them.
import-eval-reports:
	python -m scripts.import_eval_reports

# One tiny model call, logged like any other. Costs a fraction of a cent.
connection-check:
	python -m scripts.check_anthropic_connection

# Web console. Needs Node 20.19 or newer; see RUN_LOCALLY.md for a portable install.
ui-install:
	cd frontend && npm ci

ui-dev:
	cd frontend && npm run dev

ui-build:
	cd frontend && npm run build

ui-check:
	cd frontend && npm run check

docker-up:
	docker compose up -d db

docker-down:
	docker compose down

docker-build:
	docker compose build api

check: format lint typecheck test ui-check
