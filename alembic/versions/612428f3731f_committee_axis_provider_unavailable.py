"""committee axis provider unavailable

Revision ID: 612428f3731f
Revises: 0296c177772f
Create Date: 2026-08-20 18:37:46.476149+00:00

The zero-cost terminal disposition of the committee axis when the provider's organization index
cannot serve the account at all.

Live run ``dc86340f`` (2026-08-20 21:36:47 IST, "Greater Chicago Specialty Physicians LLC"):
``discover_buying_committee`` composed correctly, reached Sumble committee input resolution, and
died with a raw ``SumbleCommitteePreparationError`` ("no exact matched organization") that escaped
as ``execution_failed`` and requeued the job. Sumble's index simply has no exact match for a small
Chicago physician group — a fact about the provider's data, the same species as the 402 that
already folds terminally and lets an account settle with an honest committee gap.

That refusal happens **before any provider operation row exists**: nothing was reserved, nothing
dispatched, nothing charged, so there is no operation to stamp and no settlement to fold. This
table is the honest alternative to inventing one. One row per real, journalled committee tool call
that the engine refused on a durable world fact; it records what was attempted, against which
sources, and why the provider could not be asked. ``read_account_research_execution_completeness``
reads it as a terminal committee attempt so ``assess_account_coverage`` /
``finalize_account_research`` can close with an honest empty committee, exactly as the 402 path
does through its fold.

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
revision: str = "612428f3731f"
down_revision: str | None = "0296c177772f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE entity_research_account_committee_unavailable (
            tool_request_id      uuid PRIMARY KEY REFERENCES entity_research_tool_request
                                     (tool_request_id) ON DELETE RESTRICT,
            research_run_id      uuid NOT NULL REFERENCES entity_research_run
                                     (research_run_id) ON DELETE RESTRICT,
            job_id               uuid NOT NULL REFERENCES entity_research_job
                                     (job_id) ON DELETE RESTRICT,
            workspace_id         text NOT NULL,
            account_entity_id    uuid NOT NULL,
            source_keys          text[] NOT NULL,
            reason_code          text NOT NULL,
            detail               text NOT NULL,
            created_at           timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT entity_research_committee_unavailable_sources
                CHECK (cardinality(source_keys) > 0),
            CONSTRAINT entity_research_committee_unavailable_reason CHECK (
                reason_code IN (
                    'committee_provider_organization_unmatched',
                    'committee_provider_identity_absent'
                )
            ),
            CONSTRAINT entity_research_committee_unavailable_detail
                CHECK (length(btrim(detail)) > 0 AND length(btrim(workspace_id)) > 0)
        )
        """
    )
    op.execute(
        "CREATE INDEX entity_research_committee_unavailable_job "
        "ON entity_research_account_committee_unavailable (job_id, created_at)"
    )
    # Same append-only discipline as every other account-research ledger: a recorded world-fact
    # attempt is history, and history is never rewritten.
    op.execute(
        "CREATE TRIGGER entity_research_account_committee_unavailable_append_only "
        "BEFORE UPDATE OR DELETE ON entity_research_account_committee_unavailable "
        "FOR EACH ROW EXECUTE FUNCTION reject_entity_research_account_history_mutation()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS entity_research_account_committee_unavailable_append_only "
        "ON entity_research_account_committee_unavailable"
    )
    op.execute("DROP TABLE IF EXISTS entity_research_account_committee_unavailable")
