SHELL := /bin/bash
BACKEND := backend
WEB := web
PY := $(BACKEND)/.venv/bin
PYTHON ?= python3.13

.PHONY: help install infra infra-stop migrate seed corpus api worker web dev run lint typecheck test build check up down clean

help:
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

install: ## Create the Python venv and install web dependencies
	test -d $(BACKEND)/.venv || $(PYTHON) -m venv $(BACKEND)/.venv
	$(PY)/pip install -q --upgrade pip
	$(PY)/pip install -q -e "$(BACKEND)[dev,fastembed]"
	cd $(WEB) && pnpm install --frozen-lockfile

infra: ## Start PostgreSQL (pgvector) and Redis (loopback only, password-protected) on 5503/6403
	./scripts/local-infra.sh start

infra-stop: ## Stop the local PostgreSQL and Redis
	./scripts/local-infra.sh stop

migrate: ## Apply database migrations
	cd $(BACKEND) && .venv/bin/docforge migrate

corpus: ## Regenerate the bundled sample corpus
	cd $(BACKEND) && .venv/bin/docforge generate-corpus

seed: ## Reset the database and load a realistic demo history
	cd $(BACKEND) && .venv/bin/docforge seed --yes

run: ## Run the pipeline once in-process (no worker needed)
	cd $(BACKEND) && .venv/bin/docforge run

api: ## Start the API on :8103
	cd $(BACKEND) && .venv/bin/uvicorn docforge.api.app:create_app --factory --reload --port 8103

worker: ## Start the arq worker
	cd $(BACKEND) && .venv/bin/arq docforge.worker.main.WorkerSettings

web: ## Start the web app on :3103
	cd $(WEB) && pnpm dev

dev: ## Start API, worker and web together (Ctrl-C stops all)
	@trap 'kill 0' INT TERM EXIT; \
	$(MAKE) --no-print-directory api & \
	$(MAKE) --no-print-directory worker & \
	$(MAKE) --no-print-directory web & \
	wait

lint: ## Ruff and ESLint
	cd $(BACKEND) && .venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests
	cd $(WEB) && pnpm lint

typecheck: ## mypy --strict and tsc --noEmit
	cd $(BACKEND) && .venv/bin/mypy && .venv/bin/mypy tests
	cd $(WEB) && pnpm typecheck

test: ## pytest (needs PostgreSQL) and vitest
	cd $(BACKEND) && .venv/bin/pytest
	cd $(WEB) && pnpm test

build: ## Production build of the web app
	cd $(WEB) && pnpm build

check: lint typecheck test build ## Everything CI runs

up: ## Run the full stack with Docker Compose
	docker compose up --build -d
	docker compose --profile seed run --rm seed

down: ## Stop the Docker Compose stack
	docker compose down

clean: ## Remove local runtime data (blobs, exports, models)
	rm -rf data
