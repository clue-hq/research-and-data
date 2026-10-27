"""annual revenue holds a provider range

Revision ID: 802fa1e6c449
Revises: 67008abcd347
Create Date: 2026-10-27 05:16:10.007053+00:00

``core.annual_revenue`` required one ``amount``. AI Ark answers revenue as a range
(``1000000-5000000``), so the range had nowhere to go: the only AI Ark revenue claim was
``core.revenue_band``, written only when the range sat inside one of our bands, and the accounts
table showed nothing for every other company (founder 2026-10-27: show the band AI Ark gives). The
field now also takes ``amount_min``/``amount_max``; ``amount`` stops being required because the
schema validator has no ``anyOf`` to say "one or the other", and each writer writes one.

This is a pack-row change, so it ships with its exact before/after swap (the ``7c4f1a2b9d63``
posture): ``register_field`` refuses an in-place redefinition, so without this the pack load at
worker start raises ``FieldRedefinitionError`` on every database carrying the old row. A row that
is neither shape raises here, naming the field. Existing claims are not touched.

Conventions every migration must honour (docs/specs/M00-foundations-and-shared-contracts.md §M0.3;
see src/clue_research/db/README.md "Migration conventions checklist"):
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
revision: str = "802fa1e6c449"
down_revision: str | None = "67008abcd347"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FIELD = "core.annual_revenue"

_ESTIMATE_KIND = {
    "type": "string",
    "enum": ["reported", "provider_estimate", "third_party_estimate"],
}

_BEFORE: dict[str, Any] = {
    "type": "object",
    "required": ["amount", "currency", "as_of", "estimate_kind"],
    "properties": {
        "amount": {"type": "number"},
        "currency": {"type": "string"},
        "as_of": {"type": "string"},
        "estimate_kind": _ESTIMATE_KIND,
    },
}
_AFTER: dict[str, Any] = {
    "type": "object",
    "required": ["currency", "as_of", "estimate_kind"],
    "properties": {
        "amount": {"type": "number"},
        "amount_min": {"type": "number"},
        "amount_max": {"type": "number"},
        "currency": {"type": "string"},
        "as_of": {"type": "string"},
        "estimate_kind": _ESTIMATE_KIND,
    },
}
_DESCRIPTION_BEFORE = (
    "Annual revenue with currency, as-of date, and explicit reported/estimate semantics."
)
_DESCRIPTION_AFTER = (
    "Annual revenue — one amount or a provider's low-high range — with currency, as-of "
    "date, and explicit reported/estimate semantics."
)

_UPDATE = sa.text(
    "UPDATE field_definition SET value_schema = CAST(:new_schema AS jsonb), "
    "description = :new_description "
    "WHERE field_key = :field_key AND value_schema = CAST(:old_schema AS jsonb) "
    "AND description = :old_description"
)
_ALREADY = sa.text(
    "SELECT count(*) FROM field_definition WHERE field_key = :field_key "
    "AND value_schema = CAST(:new_schema AS jsonb) AND description = :new_description"
)
_PRESENT = sa.text("SELECT count(*) FROM field_definition WHERE field_key = :field_key")


def _swap(*, forward: bool) -> None:
    old_schema, new_schema = (_BEFORE, _AFTER) if forward else (_AFTER, _BEFORE)
    old_description, new_description = (
        (_DESCRIPTION_BEFORE, _DESCRIPTION_AFTER)
        if forward
        else (_DESCRIPTION_AFTER, _DESCRIPTION_BEFORE)
    )
    bind = op.get_bind()
    parameters = {
        "field_key": _FIELD,
        "old_schema": json.dumps(old_schema),
        "new_schema": json.dumps(new_schema),
        "old_description": old_description,
        "new_description": new_description,
    }
    if bind.execute(_UPDATE, parameters).rowcount:
        return
    if bind.execute(_ALREADY, parameters).scalar_one():
        return
    if not bind.execute(_PRESENT, {"field_key": _FIELD}).scalar_one():
        return
    raise RuntimeError(
        f"field_definition row for {_FIELD!r} is neither the shape this migration moves from "
        "nor the shape it moves to, so it was left alone. Align it before starting a worker: "
        "register_field compares the whole row and would raise FieldRedefinitionError."
    )


def upgrade() -> None:
    _swap(forward=True)


def downgrade() -> None:
    _swap(forward=False)
