"""widen account coverage field axis to core fields

Revision ID: 99923d6527c3
Revises: a1c5b9842f0e
Create Date: 2026-08-18 15:52:14.741762+00:00

The M8D R5 coverage row records the fields one account job settled.  Its field-axis CHECK
(``entity_research_account_coverage_field_axis``, migration ``85595185f793``) accepted only
``account.%`` keys, because the launcher used to project the confirmed directive with the same
raw prefix.  The comprehensive account profile (contract §3.1) is 21 fields, ten of which are
``core.*`` firmographic facts — organization-level truth that account research owns — so a job
that settles ``core.industry`` must be able to write it into ``completed_field_keys`` /
``unresolved_field_keys``.  Widen the one immutable predicate function behind that CHECK to the
launch axis; the contact coverage guard (``7bb3178d7580``) is untouched, and a ``contact.%``
field is still refused on an account coverage row.

Conventions every migration must honour (docs/specs/M00-foundations-and-shared-contracts.md §M0.3;
see src/clue_research/db/README.md "Migration conventions checklist"):
- Append-only: claim history supersedes via ``superseded_by``; never UPDATE a value column in place.
- UTC ``timestamptz`` for time columns (e.g. ``observed_at`` / ``collected_at``).
- JSONB ``value_json`` payloads, with real indexed columns on the hot query keys (``entity_id`` …).
- Everything keys on a resolved ``entity_id`` — never a free-text name.
- Forward + reverse: ``downgrade()`` must cleanly reverse ``upgrade()`` (CI runs up → down → up).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "99923d6527c3"
down_revision: str | None = "a1c5b9842f0e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WIDENED_PREDICATE = "field_key LIKE 'account.%' OR field_key LIKE 'core.%'"
_ORIGINAL_PREDICATE = "field_key LIKE 'account.%'"


def _replace_field_axis(predicate: str) -> None:
    """Rebuild the coverage field-axis guard around ``predicate``.

    The CHECK calls an IMMUTABLE SQL function, so the constraint is dropped first and re-added
    under its original token name afterwards: that re-validates every existing row against the
    new predicate instead of leaving stored rows unchecked.
    """

    op.execute(
        "ALTER TABLE entity_research_account_coverage "
        "DROP CONSTRAINT entity_research_account_coverage_field_axis"
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION entity_research_all_account_fields(keys text[])
        RETURNS boolean LANGUAGE sql IMMUTABLE STRICT AS $$
            SELECT COALESCE(bool_and({predicate}), TRUE)
            FROM unnest(keys) field_key
        $$
        """
    )
    op.execute(
        "ALTER TABLE entity_research_account_coverage "
        "ADD CONSTRAINT entity_research_account_coverage_field_axis CHECK ("
        "entity_research_all_account_fields("
        "completed_field_keys || unresolved_field_keys))"
    )


def upgrade() -> None:
    _replace_field_axis(_WIDENED_PREDICATE)


def downgrade() -> None:
    # Loud by design: a stored ``core.*`` coverage key fails the narrowed CHECK re-validation
    # rather than being silently retained under a constraint that no longer describes it.
    _replace_field_axis(_ORIGINAL_PREDICATE)
