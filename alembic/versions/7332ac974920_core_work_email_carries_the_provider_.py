"""core.work_email carries the provider verdict

Revision ID: 7332ac974920
Revises: a3602967bb73
Create Date: 2026-09-08

ARV2 D4-b decision 6. ``core.work_email`` stops being a bare address string and becomes
``{"address", "status", "checked_at"?}`` — the address with the provider's deliverability verdict,
which is the shape ``AiArkEmailExport`` insists on ("an address flattened away from its
status/domainType pair is a claim nobody can grade"). Without the verdict every real contact reads
as *look this up* on the screens, because the reader cannot tell a probed mailbox from a guess.

This is a data fix, not a schema change: no table gains or loses a column. ``register_field``
refuses to redefine a registered key, so a database that already carries the old ``str`` /
``{"type": "string"}`` row would fail the next ``load_core_pack`` — this revision rewrites the
stored row to the definition the pack now declares. On a fresh database the UPDATE touches zero
rows (packs load at runtime, never in a migration); that is fine.

``workspace_field_definition`` is not touched: its ``field_key LIKE 'client.%'`` CHECK means it can
never carry a ``core.*`` key.

Claim rows are NOT rewritten here. A stored bare string stays readable (the reader serves it as
*look up*), and converting one needs the provider verdict, which lives in the answer key rather
than in the database — ``scripts/load_arv2_answer_key.py --repair-emails`` supersedes those rows
with the verdict-carrying value.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7332ac974920"
down_revision: str | None = "a3602967bb73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Kept verbatim rather than imported: a migration must keep saying what it said the day it ran,
#: even after ``clue_research.claimstore.packs.WORK_EMAIL_VALUE_SCHEMA`` moves on.
_OBJECT_SCHEMA = (
    '{"type": "object", "required": ["address", "status"], "properties": '
    '{"address": {"type": "string"}, '
    '"status": {"type": "string", "enum": ["verified_smtp", "catch_all_valid", "invalid", '
    '"unknown", "unverified"]}, '
    '"checked_at": {"type": "string"}}}'
)
_STRING_SCHEMA = '{"type": "string"}'
#: The registry compares the *whole* stored definition against the pack's, so the description the
#: pack now carries has to land here too — otherwise the next ``load_core_pack`` still refuses.
_OBJECT_DESCRIPTION = (
    "Selected contact''s observed work email: the address with the provider''s deliverability "
    "verdict and the moment it was checked. It is delivery data until independent "
    "corroboration, reachability, use permission, and optional identity promotion pass."
)
_STRING_DESCRIPTION = (
    "Selected contact''s observed work email. It is delivery data until independent "
    "corroboration, reachability, use permission, and optional identity promotion pass."
)


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE field_definition
        SET value_type = 'object',
            value_schema = '{_OBJECT_SCHEMA}'::jsonb,
            description = '{_OBJECT_DESCRIPTION}'
        WHERE field_key = 'core.work_email' AND value_type = 'str'
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        UPDATE field_definition
        SET value_type = 'str',
            value_schema = '{_STRING_SCHEMA}'::jsonb,
            description = '{_STRING_DESCRIPTION}'
        WHERE field_key = 'core.work_email' AND value_type = 'object'
        """
    )
