# QuantAI developer entry points — `make help` lists everything.
SHELL := /bin/bash
PY := runtime/.venv/bin
export PATH := /opt/homebrew/bin:$(PATH)

.PHONY: help venv db-init db-start db-stop db-status test migrations-check check \
        build-frontend test-docker up down ci

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

venv: ## (Re)build runtime/.venv from requirements.txt (needs brew python@3.12)
	/opt/homebrew/opt/python@3.12/bin/python3.12 -m venv runtime/.venv
	$(PY)/pip install --upgrade pip
	$(PY)/pip install -r runtime/requirements.txt

db-init: ## Create + start the local dev Postgres (data in .devdb/)
	tool/devdb.sh init

db-start: ## Start the local dev Postgres
	tool/devdb.sh start

db-stop: ## Stop the local dev Postgres
	tool/devdb.sh stop

db-status: ## Show local dev Postgres status
	tool/devdb.sh status

test: ## Backend test suite (needs the dev Postgres running)
	cd runtime && ./.venv/bin/pytest -q

migrations-check: ## Fail if models drifted from the committed migrations
	cd runtime && DJANGO_SETTINGS_MODULE=config.test_settings \
		./.venv/bin/python manage.py makemigrations --check --dry-run

check: ## Django system checks
	cd runtime && DJANGO_SETTINGS_MODULE=config.test_settings \
		./.venv/bin/python manage.py check

build-frontend: ## Type-check + production build of the frontend
	cd console && npm run build

test-docker: ## Full containerized test run (CI parity; needs Docker)
	docker compose -f docker-compose.test.yml run --rm --build test

up: ## Full local stack via Docker (db, redis, api, worker, beat)
	docker compose up --build

down: ## Tear down the Docker stack
	docker compose down

ci: migrations-check check test build-frontend ## Everything CI runs that can run locally
