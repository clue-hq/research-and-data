"""arv2 r3 live walk: career history dates nest under ``date``

Revision ID: 7c4f1a2b9d63
Revises: 60e51eba0123
Create Date: 2026-09-09 12:00:00+00:00

One registry row now declares the shape its writer writes and its reader reads. It was found by
reading a real person job's output through the live read surface (walk finding W3,
`.context/arv2-r3-acceptance/acceptance.md`), and it is a pack-row schema change, so it ships with
its exact before/after swap here: `register_field` refuses an in-place redefinition, so without
this migration the pack load at worker start would raise `FieldRedefinitionError` on every
database that already carries the old row, and the fresh-DB suites could not see it.

`contact.facet.career_history` declared `start`/`end` flat on each entry. Neither the answer keys
nor the read surface use that spelling — `current_position_start` takes the entry with no
`date.end` and reads its `date.start` — so the dates now nest under `date`, and the AI Ark mapper
writes them there.

The walk's other shape finding, W1 (`core.work_email` as the address with its verdict), is carried
by D4-b's own migration `7332ac974920`, which landed first on the integration branch with the
registry's closed status vocabulary (`claimstore.packs.WORK_EMAIL_STATUSES`); this revision does
not touch that row. The ARV2 export mapper writes the shape that migration declares.

**A swap that matches nothing is loud.** Each swap checks what it did: an updated row is the
happy path, a row already in the after shape is a re-run or a fresh pack load, no row at all is a
database that has never loaded the packs — and a row that is *neither* shape raises here, naming
the field, because that database's pack load is going to fail at worker start with
`FieldRedefinitionError` and the migration is the earlier, better place to hear it. Nothing is
rewritten in that case, which is the `320e975d4c46` posture; only the silence is removed.

**Existing claims are not touched** (the `320e975d4c46` precedent). A value written under the old
declaration keeps the shape it was written in and the annotations it was graded with; the next run
validates against the new one. Readers that must serve both — the person job's identity-lock
employment lines — read both spellings deliberately, and say so at the site.

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
revision: str = "7c4f1a2b9d63"
down_revision: str | None = "60e51eba0123"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CAREER_HISTORY = "contact.facet.career_history"

_CAREER_HISTORY_DESCRIPTION = (
    "Professional history beyond the current title — prior roles (Doc C §2)."
)

_CAREER_HISTORY_BEFORE: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["org"],
        "properties": {
            "org": {"type": "string"},
            "role": {"type": "string"},
            "start": {"type": "string"},
            "end": {"type": "string"},
        },
    },
}
_CAREER_HISTORY_AFTER: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["org"],
        "properties": {
            "org": {"type": "string"},
            "role": {"type": "string"},
            "date": {
                "type": "object",
                "properties": {"start": {"type": "string"}, "end": {"type": "string"}},
            },
        },
    },
}

#: The swap is exact on every column it reads, so a row a deployment has deliberately overridden
#: (a schema that is neither shape) is never silently rewritten.
_UPDATE = sa.text(
    "UPDATE field_definition SET value_schema = CAST(:new_schema AS jsonb), "
    "value_type = :new_type, description = :new_description "
    "WHERE field_key = :field_key AND value_schema = CAST(:old_schema AS jsonb) "
    "AND value_type = :old_type AND description = :old_description"
)

#: Is the row already the shape this swap moves *to*? A second run of the same migration and a
#: database seeded fresh from the packs both land here, and both are fine.
_ALREADY = sa.text(
    "SELECT count(*) FROM field_definition WHERE field_key = :field_key "
    "AND value_schema = CAST(:new_schema AS jsonb) AND value_type = :new_type "
    "AND description = :new_description"
)

#: Does this deployment carry a row for the field at all? A database that has never loaded the
#: packs carries none — the rows are written by ``register_field`` at worker start, not here — and
#: there is nothing to align.
_PRESENT = sa.text("SELECT count(*) FROM field_definition WHERE field_key = :field_key")


def _swap(
    *,
    field_key: str,
    old_schema: dict[str, Any],
    new_schema: dict[str, Any],
    old_type: str,
    new_type: str,
    old_description: str,
    new_description: str,
) -> None:
    """Move one field_definition row from the before shape to the after shape, or say why not.

    A swap that matches nothing is only ever *silent* about one thing worth hearing: a row that is
    neither shape. ``register_field`` compares the whole row, so that database's pack load fails at
    worker start with ``FieldRedefinitionError`` — the exact failure this migration exists to
    prevent — and the operator learns about it from a worker that will not come up rather than from
    the migration that could have told them. So it is raised here, naming the field.

    The ``320e975d4c46`` precedent (an override "is left untouched rather than silently rewritten")
    is kept: nothing is rewritten either way. The raise adds no write, only the signal.
    """
    bind = op.get_bind()
    parameters = {
        "field_key": field_key,
        "old_schema": json.dumps(old_schema),
        "new_schema": json.dumps(new_schema),
        "old_type": old_type,
        "new_type": new_type,
        "old_description": old_description,
        "new_description": new_description,
    }
    if bind.execute(_UPDATE, parameters).rowcount:
        return
    if bind.execute(_ALREADY, parameters).scalar_one():
        return
    if not bind.execute(_PRESENT, {"field_key": field_key}).scalar_one():
        return
    raise RuntimeError(
        f"field_definition row for {field_key!r} is neither the shape this migration moves from "
        "nor the shape it moves to, so it was left alone. Align it (or drop it and let the pack "
        "load rewrite it) before starting a worker: register_field compares the whole row and "
        "would raise FieldRedefinitionError at worker start."
    )


def _reschema(*, forward: bool) -> None:
    history_old, history_new = (
        (_CAREER_HISTORY_BEFORE, _CAREER_HISTORY_AFTER)
        if forward
        else (_CAREER_HISTORY_AFTER, _CAREER_HISTORY_BEFORE)
    )
    _swap(
        field_key=_CAREER_HISTORY,
        old_schema=history_old,
        new_schema=history_new,
        # Neither the value type nor the description moves: a career history is a
        # ``list[object]`` of prior roles under both shapes. Only where the dates sit changed.
        old_type="list[object]",
        new_type="list[object]",
        old_description=_CAREER_HISTORY_DESCRIPTION,
        new_description=_CAREER_HISTORY_DESCRIPTION,
    )


def upgrade() -> None:
    _reschema(forward=True)


def downgrade() -> None:
    _reschema(forward=False)
