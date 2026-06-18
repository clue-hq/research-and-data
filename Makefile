# Clue-HQ Research & Data subsystem — developer entrypoints.
# `make check` is the single gate M0.1 requires (format + lint + type-check + dependency
# contracts + structure tests). CI runs the same target; M0.6 extends it (DB/migration smoke,
# span smoke, eval harness).

.DEFAULT_GOAL := help
.PHONY: help install format lint typecheck contracts test check

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
