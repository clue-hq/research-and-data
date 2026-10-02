"""allow account research without directional questions

Revision ID: 486ee7b24ae8
Revises: 509e5d0e623a
Create Date: 2026-08-18 21:33:08.540942+00:00

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
revision: str = "486ee7b24ae8"
down_revision: str | None = "509e5d0e623a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE entity_research_tool_request "
        "DROP CONSTRAINT entity_research_tool_request_nonempty"
    )
    op.execute(
        """
        ALTER TABLE entity_research_tool_request
        ADD CONSTRAINT entity_research_tool_request_nonempty CHECK (
            length(btrim(raw_tool_call_id)) > 0 AND length(btrim(tool_name)) > 0
            AND length(btrim(field_plan_ref)) > 0
            AND length(btrim(source_plan_ref)) > 0
            AND length(btrim(budget_reservation_key)) > 0
            AND length(btrim(idempotency_key)) > 0
            AND cardinality(source_keys) > 0
            AND (subject_type = 'account' OR cardinality(questions) > 0)
            AND jsonb_typeof(field_source_authority) = 'array'
            AND (
                (tool_name = 'discover_buying_committee' AND cardinality(field_keys) = 0
                 AND field_source_authority = '[]'::jsonb)
                OR
                (tool_name <> 'discover_buying_committee' AND cardinality(field_keys) > 0
                 AND jsonb_array_length(field_source_authority) > 0)
            )
        )
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE entity_research_tool_request "
        "DROP CONSTRAINT entity_research_tool_request_nonempty"
    )
    op.execute(
        """
        ALTER TABLE entity_research_tool_request
        ADD CONSTRAINT entity_research_tool_request_nonempty CHECK (
            length(btrim(raw_tool_call_id)) > 0 AND length(btrim(tool_name)) > 0
            AND length(btrim(field_plan_ref)) > 0
            AND length(btrim(source_plan_ref)) > 0
            AND length(btrim(budget_reservation_key)) > 0
            AND length(btrim(idempotency_key)) > 0
            AND cardinality(source_keys) > 0 AND cardinality(questions) > 0
            AND jsonb_typeof(field_source_authority) = 'array'
            AND (
                (tool_name = 'discover_buying_committee' AND cardinality(field_keys) = 0
                 AND field_source_authority = '[]'::jsonb)
                OR
                (tool_name <> 'discover_buying_committee' AND cardinality(field_keys) > 0
                 AND jsonb_array_length(field_source_authority) > 0)
            )
        )
        """
    )
