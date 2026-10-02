"""Refresh the committed snapshot of the field registry.

Run by hand against a migrated database when the registry changes:

    set -a; source .env; set +a
    .venv/bin/python -m clue_agents.manual.fields_snapshot

It runs one SELECT and writes ``catalog/manual/fields.json``, sorted by field key. The snapshot is
committed so the chapter builds and the drift test run with no database at all: CI must be able to
say "the manual is stale" without a registry to read.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from clue_agents.manual.build import DEFAULT_CATALOG_ROOT
from clue_db import connection, db_lifespan

__all__ = ["COLUMNS", "snapshot_path", "write_snapshot"]

#: What a chapter prints about a field. Nothing here is personal data or client content: the
#: registry is the platform's own vocabulary, identical on every deployment.
COLUMNS: tuple[str, ...] = (
    "field_key",
    "value_type",
    "description",
    "freshness_ttl",
    "reuse_scope",
    "gate",
    "field_class",
    "active",
    "pack",
    "signal_class",
)

_SELECT = f"SELECT {', '.join(COLUMNS)} FROM field_definition ORDER BY field_key"  # noqa: S608


def snapshot_path(catalog_root: Path = DEFAULT_CATALOG_ROOT) -> Path:
    return catalog_root / "manual" / "fields.json"


async def read_rows() -> list[dict[str, Any]]:
    """The registry, read once. SELECT only: this script never writes to the database."""

    async with db_lifespan(), connection() as conn:
        result = await conn.exec_driver_sql(_SELECT)
        return [
            {name: _jsonable(value) for name, value in zip(COLUMNS, row, strict=True)}
            for row in result.fetchall()
        ]


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


async def write_snapshot(catalog_root: Path = DEFAULT_CATALOG_ROOT) -> int:
    rows = await read_rows()
    path = snapshot_path(catalog_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return len(rows)


def main() -> int:
    written = asyncio.run(write_snapshot())
    print(f"wrote {written} field rows to {snapshot_path()}")
    return 0


if __name__ == "__main__":  # pragma: no cover - console entry point
    raise SystemExit(main())
