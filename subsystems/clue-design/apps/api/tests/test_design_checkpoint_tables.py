"""The design job's sync LangGraph saver runs ``setup()`` only when the database is behind.

Production opens it as ``clue_worker``, which has no CREATE on schema public; the tables come from
the platform's Alembic migration (first production deploy, 2026-10-03).
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest
from langgraph.checkpoint.postgres.base import BasePostgresSaver
from lumen_api.fleet_handler import _ensure_checkpoint_tables


class _Cursor:
    def __init__(self, value: int | None) -> None:
        self._value = value

    def fetchone(self) -> dict[str, int] | None:
        # LangGraph's connections use dict rows; an empty table has no row.
        return None if self._value is None else {"v": self._value}


class _Conn:
    def __init__(self, recorded: Any) -> None:
        self._recorded = recorded

    def execute(self, query: str) -> _Cursor:
        if isinstance(self._recorded, type):
            raise self._recorded('relation "checkpoint_migrations" does not exist')
        return _Cursor(self._recorded)


class _Saver:
    MIGRATIONS = BasePostgresSaver.MIGRATIONS

    def __init__(self, recorded: Any) -> None:
        self.conn = _Conn(recorded)
        self.setup_calls = 0

    def setup(self) -> None:
        self.setup_calls += 1


def test_current_tables_are_left_alone() -> None:
    saver = _Saver(len(BasePostgresSaver.MIGRATIONS) - 1)
    _ensure_checkpoint_tables(saver)
    assert saver.setup_calls == 0


@pytest.mark.parametrize("recorded", [None, 4, psycopg.errors.UndefinedTable])
def test_a_database_behind_or_without_the_tables_runs_setup(recorded: Any) -> None:
    saver = _Saver(recorded)
    _ensure_checkpoint_tables(saver)
    assert saver.setup_calls == 1
