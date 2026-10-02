"""The R3 registry migration's swap says what it did, instead of matching zero rows in silence.

`7c4f1a2b9d63` moves the `contact.facet.career_history` `field_definition` row onto the shape the
R3 writer writes (the `core.work_email` row is D4-b's `7332ac974920`). The swap is exact on every
column it reads, so a row that drifted matches nothing — and until this test's subject existed,
the operator learned about that only as a `FieldRedefinitionError` at fleet worker start, which is
the exact failure the migration exists to prevent.

The bind is a stub rather than a database because the four outcomes are decided by three counts,
and driving them through Postgres would need four differently-seeded databases to say the same
thing.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "7c4f1a2b9d63_arv2_r3_career_history_shape.py"
)


def _migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_r3_field_shape_migration", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Result:
    def __init__(self, *, rowcount: int = 0, scalar: int = 0) -> None:
        self.rowcount = rowcount
        self._scalar = scalar

    def scalar_one(self) -> int:
        return self._scalar


class _Bind:
    """A bind that answers the swap's three statements with the counts this case is about."""

    def __init__(self, *, updated: int, already: int, present: int) -> None:
        self._updated, self._already, self._present = updated, already, present
        self.statements: list[str] = []

    def execute(self, statement: Any, parameters: Any = None) -> _Result:
        text = str(statement)
        self.statements.append(text.split()[0])
        if text.startswith("UPDATE"):
            return _Result(rowcount=self._updated)
        if "value_schema" in text:
            return _Result(scalar=self._already)
        return _Result(scalar=self._present)


def _swap_with(bind: _Bind, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _migration()
    monkeypatch.setattr(module.op, "get_bind", lambda: bind)
    module._swap(
        field_key="contact.facet.career_history",
        old_schema={"type": "array", "items": {"type": "object"}},
        new_schema={"type": "array", "items": {"type": "object", "properties": {}}},
        old_type="list[object]",
        new_type="list[object]",
        old_description="before",
        new_description="after",
    )


def test_a_row_the_swap_moves_is_the_happy_path_and_asks_nothing_further(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bind = _Bind(updated=1, already=0, present=0)

    _swap_with(bind, monkeypatch)

    assert bind.statements == ["UPDATE"], "an updated row needs no second question"


@pytest.mark.parametrize(
    ("already", "present", "why"),
    [(1, 1, "already the after shape — a re-run or a fresh pack load"), (0, 0, "no row at all")],
    ids=["already-migrated", "packs-never-loaded"],
)
def test_a_swap_that_updates_nothing_is_silent_when_there_is_nothing_to_align(
    already: int, present: int, why: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _swap_with(_Bind(updated=0, already=already, present=present), monkeypatch)


def test_a_row_that_is_neither_shape_raises_and_names_the_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The drifted row. Silence here is a worker that will not start, hours later."""
    with pytest.raises(RuntimeError) as raised:
        _swap_with(_Bind(updated=0, already=0, present=1), monkeypatch)

    assert "contact.facet.career_history" in str(raised.value)
    assert "FieldRedefinitionError" in str(raised.value)
