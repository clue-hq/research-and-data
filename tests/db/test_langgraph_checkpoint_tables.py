"""LangGraph's checkpoint tables are created by an Alembic migration (as the owner), and the runtime
only runs ``setup()`` when a database is behind (first production deploy, 2026-10-03: ``setup()`` as
the worker role failed with "permission denied for schema public")."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from typing import Any

import psycopg
import pytest
from langgraph.checkpoint.postgres.base import BasePostgresSaver

from clue_api.agent_execution_wiring import ensure_checkpoint_tables

_MIGRATION = next(
    (Path(__file__).resolve().parents[2] / "alembic" / "versions").glob(
        "*_langgraph_checkpoint_tables.py"
    )
)
_spec = importlib.util.spec_from_file_location("langgraph_checkpoint_tables", _MIGRATION)
assert _spec is not None and _spec.loader is not None
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)


def test_the_migration_freezes_exactly_langgraphs_migrations() -> None:
    # A LangGraph upgrade that adds a checkpoint migration fails here: write a new Alembic
    # migration for the new statements (never edit this one), then update the frozen copy's test.
    assert list(migration.LANGGRAPH_CHECKPOINT_MIGRATIONS) == list(BasePostgresSaver.MIGRATIONS)


class _Cursor:
    def __init__(self, value: int | None) -> None:
        self._value = value

    async def fetchone(self) -> dict[str, int] | None:
        # LangGraph's connections use dict rows; an empty table has no row.
        return None if self._value is None else {"v": self._value}


class _Conn:
    def __init__(self, recorded: int | None | type[Exception]) -> None:
        self._recorded = recorded

    async def execute(self, query: str) -> _Cursor:
        if isinstance(self._recorded, type):
            raise self._recorded('relation "checkpoint_migrations" does not exist')
        return _Cursor(self._recorded)


class _Saver:
    MIGRATIONS = BasePostgresSaver.MIGRATIONS

    def __init__(self, recorded: Any) -> None:
        self.conn = _Conn(recorded)
        self.setup_calls = 0

    async def setup(self) -> None:
        self.setup_calls += 1


def test_current_tables_are_left_alone() -> None:
    saver = _Saver(len(BasePostgresSaver.MIGRATIONS) - 1)
    asyncio.run(ensure_checkpoint_tables(saver))  # type: ignore[arg-type]
    assert saver.setup_calls == 0


@pytest.mark.parametrize("recorded", [None, 4, psycopg.errors.UndefinedTable])
def test_a_database_behind_or_without_the_tables_runs_setup(recorded: Any) -> None:
    saver = _Saver(recorded)
    asyncio.run(ensure_checkpoint_tables(saver))  # type: ignore[arg-type]
    assert saver.setup_calls == 1
