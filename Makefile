# Clue-HQ Research & Data subsystem — developer entrypoints.
# `make check` is the single gate M0.1 requires (format + lint + type-check + dependency
# contracts + structure tests). CI runs the same target; M0.6 extends it (DB/migration smoke,
# span smoke, eval harness).

.DEFAULT_GOAL := help
.PHONY: help install format lint typecheck contracts test check \
	db-up db-down db-fresh migrate migrate-down db-smoke eval eval-verification eval-design-exit \
	redis-up redis-down manual manual-check manual-link cost-report langfuse-check \
	pages-backfill-hostnames
	sandbox-image

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Create the venv and install deps + the package (editable)
	uv sync --all-packages

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

# --- the Head of ABM's operating manual -------------------------------------
# The generated chapters are never hand-edited: the builder is their only writer. `manual-check`
# is the drift gate; the field snapshot behind manual-fields is refreshed separately, by hand,
# with `python -m clue_agents.manual.fields_snapshot` against a migrated database.

manual: ## Regenerate the generated manual chapters (tools, fields, errors, limits)
	uv run python -m clue_api.manual_build --write

manual-check: ## Fail when a generated manual chapter is stale against the code
	uv run python -m clue_api.manual_build --check

manual-link: ## Rewrite a hand-written chapter's `manual:<chapter>` tokens to their real paths
	uv run python -m clue_api.manual_build --link

# --- database (M0.3) --------------------------------------------------------
# Postgres + pgvector lifecycle and the reviewed-migration workflow. The DB DSN is read from
# CLUE_DATABASE_URL (the shared seam), defaulting to the local docker-compose database
# (postgresql+asyncpg://clue:clue@localhost:5432/clue). See libs/clue-db/clue_db/README.md.

db-up: ## Start local Postgres+pgvector (waits for healthcheck)
	docker compose up -d --wait db

db-down: ## Stop local Postgres+pgvector and remove its volume
	docker compose down -v

# Dependency-free schema reset (no psql needed): drops + recreates the `public` schema through
# clue_db, honouring the same CLUE_DATABASE_URL seam everything else uses.
define DB_FRESH_PY
import asyncio

from sqlalchemy import text

from clue_db import database_url, db_lifespan


async def main() -> None:
    async with db_lifespan() as engine, engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    print(f"public schema dropped and recreated on {database_url()!r}")


asyncio.run(main())
endef
export DB_FRESH_PY

db-fresh: ## Drop + recreate the public schema (clean slate for a fresh test run; reads CLUE_DATABASE_URL)
	uv run python -c "$$DB_FRESH_PY"

migrate: ## Apply all migrations up to head
	uv run alembic upgrade head

migrate-down: ## Roll back one migration
	uv run alembic downgrade -1

db-smoke: ## Migration smoke: up to head -> down to base -> up to head (reversibility check)
	uv run alembic upgrade head
	uv run alembic downgrade base
	uv run alembic upgrade head

# --- redis (M2.4) -----------------------------------------------------------
# Ephemeral state for in-flight locks + rate-limit coordination (conventions §6). The DSN seam is
# CLUE_REDIS_URL, defaulting to redis://localhost:6379/0. The lock tests skip gracefully without it.

redis-up: ## Start local Redis (waits for healthcheck)
	docker compose up -d --wait redis

redis-down: ## Stop local Redis
	docker compose stop redis

# --- evals (M0.6) -----------------------------------------------------------
eval: ## Run the eval harness against the stub gold set (regression-on-swap demo; no live calls)
	uv run python -m clue_research.evals

eval-verification: ## M9.6 verification-battery DEMO (rubrics + per-mechanism + regression-on-swap; always exits 0)
	uv run python -m clue_research.verification.eval_cli

eval-design-exit: ## P3.6 design-leg exit-judgment golden-set DEMO (fail-safe envelope + regression-on-weakened-judge; always exits 0)
	uv run python -m clue_design.evals

# --- cost (lane 3 slice 1) ---------------------------------------------------
cost-report: ## Print a workspace's cost report from the two ledgers. Usage: make cost-report ARGS="--workspace acme [--project P] [--json]"
	uv run python -m clue_projections.cost_cli $(ARGS)

# --- pages hostnames (custom-domain publishing S1) ---------------------------
pages-backfill-hostnames: ## Allocate missing system hostnames. Usage: make pages-backfill-hostnames ARGS="--database-url postgresql+asyncpg://... [--suffix pages.localhost] [--dry-run]"
	uv run python scripts/backfill_workspace_hostnames.py $(ARGS)

# --- Langfuse (lane 3 slice 3) ----------------------------------------------
langfuse-check: ## Is Langfuse enabled and does the host accept the keys? Reads .env; sends no trace
	uv run python -m clue_api.langfuse_check

# --- agent code sandbox (spec 2026-09-19) ------------------------------------
sandbox-image: ## Build the Head-of-ABM code sandbox image named by CLUE_SANDBOX_IMAGE (default clue-agent-sandbox:latest)
	docker build -t $${CLUE_SANDBOX_IMAGE:-clue-agent-sandbox:latest} docker/agent-sandbox
