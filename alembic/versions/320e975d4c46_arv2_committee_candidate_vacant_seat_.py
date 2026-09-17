"""arv2 r2-close: account.committee_candidate no longer requires a name (vacant seats validate)

Revision ID: 320e975d4c46
Revises: a3602967bb73
Create Date: 2026-09-08 06:40:00+00:00

The R2-close changed the ARV2 pack's ``account.committee_candidate`` value schema in place: only
``persona`` identifies a row now, because a **vacant seat** ("nobody holds this role") is a
finding about the account and carries no name — requiring one made every recorded vacancy land
``schema_valid=false``. ``register_field`` refuses an in-place redefinition, so on any database
that already carries the R2 shape (every one the R2 acceptance ran on) the pack load at fleet
worker start raised ``FieldRedefinitionError`` and the worker never came up. The fresh-DB suites
could not see it. This data migration aligns the durable row the way ``91fd9e4d772b`` aligned the
Exa Deep tier plans: an exact before/after swap, so a row whose stored schema is neither shape (a
deliberate local override) is left untouched.

Existing ``account.committee_candidate`` claims are not touched — their annotations were computed
against the old shape and stay as the audit of that run; the next run validates against the new
one.

Conventions every migration must honour (docs/specs/M00-foundations-and-shared-contracts.md §M0.3):
- Append-only: claim history supersedes via ``superseded_by``; never UPDATE a value column in place.
- UTC ``timestamptz`` for time columns (e.g. ``observed_at`` / ``collected_at``).
- JSONB ``value_json`` payloads, with real indexed columns on the hot query keys (``entity_id`` …).
- Everything keys on a resolved ``entity_id`` — never a free-text name.
- Forward + reverse: ``downgrade()`` must cleanly reverse ``upgrade()`` (CI runs up → down → up).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "320e975d4c46"
down_revision: str | None = "a3602967bb73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FIELD_KEY = "account.committee_candidate"

_PROPERTIES: dict[str, Any] = {
    "name": {"type": "string"},
    "title": {"type": "string"},
    "persona": {
        "type": "string",
        "enum": ["economic_buyer", "champion", "user", "technical_evaluator", "blocker"],
    },
    "linkedin_url": {"type": "string"},
    "confirmed_by": {"type": "string"},
    "vacant_seat": {"type": "boolean"},
}

_BEFORE: dict[str, Any] = {
    "type": "object",
    "required": ["name", "persona"],
    "properties": _PROPERTIES,
}
_AFTER: dict[str, Any] = {
    "type": "object",
    "required": ["persona"],
    "properties": _PROPERTIES,
}

_UPDATE = sa.text(
    "UPDATE field_definition SET value_schema = CAST(:new AS jsonb) "
    "WHERE field_key = :field_key AND value_schema = CAST(:old AS jsonb)"
)


def _reschema(*, forward: bool) -> None:
    old, new = (_BEFORE, _AFTER) if forward else (_AFTER, _BEFORE)
    op.get_bind().execute(
        _UPDATE,
        {"field_key": _FIELD_KEY, "old": json.dumps(old), "new": json.dumps(new)},
    )


def upgrade() -> None:
    _reschema(forward=True)


def downgrade() -> None:
    _reschema(forward=False)
