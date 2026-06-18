# Clue-HQ Research & Data subsystem — developer entrypoints.
# `make check` is the single gate M0.1 requires (format + lint + type-check + dependency
# contracts + structure tests). CI runs the same target; M0.6 extends it (DB/migration smoke,
# span smoke, eval harness).

.DEFAULT_GOAL := help
.PHONY: help install format lint typecheck contracts test check \
	db-up db-down migrate migrate-down db-smoke

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Create the venv and install deps + the package (editable)
	uv sync

format: ## Auto-format and apply safe lint fixes
	uv run ruff format .
	uv run ruff check --fix .

lint: ## Lint (no changes)
	uv run ruff format --check .
	uv run ruff check .

typecheck: ## Static type check (mypy + pydantic plugin)
	uv run mypy

contracts: ## Enforce the modular dependency rules (import-linter)
	uv run lint-imports

test: ## Run the test suite
	uv run pytest

check: lint typecheck contracts test ## Run the full local gate (what CI runs)

# --- database (M0.3) --------------------------------------------------------
# Postgres + pgvector lifecycle and the reviewed-migration workflow. The DB DSN is read from
# CLUE_DATABASE_URL (the shared seam), defaulting to the local docker-compose database
# (postgresql+asyncpg://clue:clue@localhost:5432/clue). See src/clue_research/db/README.md.

db-up: ## Start local Postgres+pgvector (waits for healthcheck)
	docker compose up -d --wait db

db-down: ## Stop local Postgres+pgvector and remove its volume
	docker compose down -v

migrate: ## Apply all migrations up to head
	uv run alembic upgrade head

migrate-down: ## Roll back one migration
	uv run alembic downgrade -1

db-smoke: ## Migration smoke: up to head -> down to base -> up to head (reversibility check)
	uv run alembic upgrade head
	uv run alembic downgrade base
	uv run alembic upgrade head
