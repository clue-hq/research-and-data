"""JSON/timestamp codec helpers shared by the design DAL modules (D2.2).

The DAL speaks the merged design API's JSON shapes verbatim (the ``*_from_row`` contracts the
endpoints already serve), so the port is a storage swap, not an API change:

* jsonb parameters travel as ``json.dumps`` strings cast with ``CAST(:x AS jsonb)`` — explicit
  and driver-independent.
* jsonb results are decoded tolerantly (the asyncpg codec usually hands back Python objects;
  a str/bytes payload is parsed) — the claimstore precedent.
* timestamps come back as tz-aware datetimes and are rendered to ISO-8601 strings, matching
  the SQLite layer's ``utc_now()`` text format the API has always served.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

JsonObject = dict[str, Any]


def dump_json(value: object) -> str:
    return json.dumps(value)


def dump_json_opt(value: object | None) -> str | None:
    return None if value is None else json.dumps(value)


def load_json(raw: object) -> Any:
    if isinstance(raw, (bytes, bytearray)):
        return json.loads(raw.decode("utf-8"))
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


def load_json_opt(raw: object | None) -> Any:
    return None if raw is None else load_json(raw)


def iso(value: object) -> Any:
    """Render a datetime column to the ISO string shape the API has always served."""
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def as_datetime(value: object) -> datetime:
    """Coerce a caller-supplied instant into a real aware ``datetime`` (the ``iso`` inverse).

    Every ``timestamptz`` column whose value is the CALLER's (rather than the database's
    ``now()``) needs this: asyncpg binds parameters by inferred type, so a string does not
    survive a SQL-level ``CAST(:param AS timestamptz)`` — it is rejected at encode time, before
    Postgres ever sees the cast.

    A naive datetime is read as UTC rather than refused: every producer in this codebase stamps
    UTC, and silently storing a local-clock instant would be the worse answer.
    """
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
