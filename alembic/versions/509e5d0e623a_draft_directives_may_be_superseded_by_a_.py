"""draft directives may be superseded by a fresh draft

Revision ID: 509e5d0e623a
Revises: 9184f54adc26
Create Date: 2026-08-18 20:20:00.000000+00:00

The A2 lifecycle admitted only ``draft -> confirmed`` and ``confirmed -> superseded``, which made
confirmation the sole exit from a draft.  Found live at the Slice B browser gate: a draft whose
effort tier could never price its confirmation gate deadlocked the whole directive lineage —
"cannot append behind an unconfirmed directive" refused every successor, and no reject path
exists.  The draft compiler now supersedes an unconfirmed latest draft when a fresh draft
arrives (``clue_research.directives.draft_research_directive``, with an append-only
``superseded`` event naming the successor), so the trigger's transition set gains exactly
``draft -> superseded``.  Confirmed history is untouched: content immutability, the confirmation
receipt rules, and ``confirmed -> superseded`` are byte-identical to ``8f44b739674c``.

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
revision: str = "509e5d0e623a"
down_revision: str | None = "9184f54adc26"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_WIDENED = """
CREATE OR REPLACE FUNCTION account_research_directive_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF EXISTS (SELECT 1 FROM project WHERE project_id = OLD.project_id) THEN
                    RAISE EXCEPTION
                        'account_research_directive is lifecycle-owned; delete the project';
                END IF;
                RETURN OLD;
            END IF;
            IF NEW.directive_id IS DISTINCT FROM OLD.directive_id
               OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
               OR NEW.project_id IS DISTINCT FROM OLD.project_id
               OR NEW.product_id IS DISTINCT FROM OLD.product_id
               OR NEW.icp_key IS DISTINCT FROM OLD.icp_key
               OR NEW.icp_version IS DISTINCT FROM OLD.icp_version
               OR NEW.version IS DISTINCT FROM OLD.version
               OR NEW.predecessor_id IS DISTINCT FROM OLD.predecessor_id
               OR NEW.content_json IS DISTINCT FROM OLD.content_json
               OR NEW.memory_refs IS DISTINCT FROM OLD.memory_refs
               OR NEW.created_by IS DISTINCT FROM OLD.created_by
               OR NEW.source_turn_ref IS DISTINCT FROM OLD.source_turn_ref
               OR NEW.draft_operation_id IS DISTINCT FROM OLD.draft_operation_id
               OR NEW.draft_request_sha256 IS DISTINCT FROM OLD.draft_request_sha256
               OR NEW.canonical_json_sha256 IS DISTINCT FROM OLD.canonical_json_sha256
               OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION
                    'research directive content is immutable; append a successor version';
            END IF;
            IF NOT (
                (OLD.status = 'draft' AND NEW.status = 'confirmed')
                OR (OLD.status = 'draft' AND NEW.status = 'superseded')
                OR (OLD.status = 'confirmed' AND NEW.status = 'superseded')
                OR (OLD.status = NEW.status)
            ) THEN
                RAISE EXCEPTION 'invalid research directive lifecycle transition';
            END IF;
            IF OLD.status = NEW.status AND (
                NEW.confirmation_operation_id IS DISTINCT FROM OLD.confirmation_operation_id
                OR NEW.confirmed_by IS DISTINCT FROM OLD.confirmed_by
                OR NEW.confirming_turn_ref IS DISTINCT FROM OLD.confirming_turn_ref
                OR NEW.confirmed_at IS DISTINCT FROM OLD.confirmed_at
            ) THEN
                RAISE EXCEPTION 'research directive confirmation receipt is immutable';
            END IF;
            IF OLD.status = 'draft' AND NEW.status = 'confirmed' AND (
                NEW.confirmation_operation_id IS NULL
                OR NEW.confirmed_by IS NULL
                OR NEW.confirming_turn_ref IS NULL
                OR NEW.confirmed_at IS NULL
            ) THEN
                RAISE EXCEPTION 'confirmed directive requires a complete confirmation receipt';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
"""

_ORIGINAL = """
CREATE OR REPLACE FUNCTION account_research_directive_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF EXISTS (SELECT 1 FROM project WHERE project_id = OLD.project_id) THEN
                    RAISE EXCEPTION
                        'account_research_directive is lifecycle-owned; delete the project';
                END IF;
                RETURN OLD;
            END IF;
            IF NEW.directive_id IS DISTINCT FROM OLD.directive_id
               OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
               OR NEW.project_id IS DISTINCT FROM OLD.project_id
               OR NEW.product_id IS DISTINCT FROM OLD.product_id
               OR NEW.icp_key IS DISTINCT FROM OLD.icp_key
               OR NEW.icp_version IS DISTINCT FROM OLD.icp_version
               OR NEW.version IS DISTINCT FROM OLD.version
               OR NEW.predecessor_id IS DISTINCT FROM OLD.predecessor_id
               OR NEW.content_json IS DISTINCT FROM OLD.content_json
               OR NEW.memory_refs IS DISTINCT FROM OLD.memory_refs
               OR NEW.created_by IS DISTINCT FROM OLD.created_by
               OR NEW.source_turn_ref IS DISTINCT FROM OLD.source_turn_ref
               OR NEW.draft_operation_id IS DISTINCT FROM OLD.draft_operation_id
               OR NEW.draft_request_sha256 IS DISTINCT FROM OLD.draft_request_sha256
               OR NEW.canonical_json_sha256 IS DISTINCT FROM OLD.canonical_json_sha256
               OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION
                    'research directive content is immutable; append a successor version';
            END IF;
            IF NOT (
                (OLD.status = 'draft' AND NEW.status = 'confirmed')
                OR (OLD.status = 'confirmed' AND NEW.status = 'superseded')
                OR (OLD.status = NEW.status)
            ) THEN
                RAISE EXCEPTION 'invalid research directive lifecycle transition';
            END IF;
            IF OLD.status = NEW.status AND (
                NEW.confirmation_operation_id IS DISTINCT FROM OLD.confirmation_operation_id
                OR NEW.confirmed_by IS DISTINCT FROM OLD.confirmed_by
                OR NEW.confirming_turn_ref IS DISTINCT FROM OLD.confirming_turn_ref
                OR NEW.confirmed_at IS DISTINCT FROM OLD.confirmed_at
            ) THEN
                RAISE EXCEPTION 'research directive confirmation receipt is immutable';
            END IF;
            IF OLD.status = 'draft' AND NEW.status = 'confirmed' AND (
                NEW.confirmation_operation_id IS NULL
                OR NEW.confirmed_by IS NULL
                OR NEW.confirming_turn_ref IS NULL
                OR NEW.confirmed_at IS NULL
            ) THEN
                RAISE EXCEPTION 'confirmed directive requires a complete confirmation receipt';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
"""


_RECEIPT_ALL_NULL = (
    "confirmation_operation_id IS NULL AND confirmed_by IS NULL "
    "AND confirming_turn_ref IS NULL AND confirmed_at IS NULL"
)
_RECEIPT_ALL_SET = (
    "confirmation_operation_id IS NOT NULL AND confirmed_by IS NOT NULL "
    "AND confirming_turn_ref IS NOT NULL AND confirmed_at IS NOT NULL"
)

#: A superseded row now has two legal shapes: a superseded *confirmed* directive keeps its full
#: receipt; a superseded *draft* never had one.
_WIDENED_SHAPE = (
    f"(status = 'draft' AND {_RECEIPT_ALL_NULL}) "
    f"OR (status = 'confirmed' AND {_RECEIPT_ALL_SET}) "
    f"OR (status = 'superseded' AND (({_RECEIPT_ALL_SET}) OR ({_RECEIPT_ALL_NULL})))"
)

_ORIGINAL_SHAPE = (
    f"(status = 'draft' AND {_RECEIPT_ALL_NULL}) "
    f"OR (status IN ('confirmed', 'superseded') AND {_RECEIPT_ALL_SET})"
)


def _replace_shape(predicate: str) -> None:
    op.execute(
        "ALTER TABLE account_research_directive "
        "DROP CONSTRAINT account_research_directive_confirmation_shape"
    )
    op.execute(
        "ALTER TABLE account_research_directive "
        f"ADD CONSTRAINT account_research_directive_confirmation_shape CHECK ({predicate})"
    )


def upgrade() -> None:
    op.execute(_WIDENED)
    _replace_shape(_WIDENED_SHAPE)


def downgrade() -> None:
    # Loud by design: a stored receipt-less superseded draft fails the narrowed CHECK
    # re-validation rather than surviving under a constraint that no longer describes it.
    _replace_shape(_ORIGINAL_SHAPE)
    op.execute(_ORIGINAL)
