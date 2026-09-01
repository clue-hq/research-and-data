"""allow explicit committee job without tier claim

Revision ID: fc3e5477e872
Revises: a1c5b9842f0e
Create Date: 2026-08-18 21:54:02.848465+00:00

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
revision: str = "fc3e5477e872"
down_revision: str | None = "a1c5b9842f0e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE account_gap_operation ALTER COLUMN tier_claim_id DROP NOT NULL")
    op.execute(
        "ALTER TABLE committee_acquisition_operation ALTER COLUMN tier_claim_id DROP NOT NULL"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION account_gap_validate_tier_claim() RETURNS trigger AS $$
        BEGIN
            IF NEW.tier_claim_id IS NULL THEN
                IF NULLIF(NEW.request_json->>'entity_research_job_id', '') IS NULL THEN
                    RAISE EXCEPTION 'historical account-gap operation requires a tier claim';
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM entity_research_job
                     WHERE job_id = (NEW.request_json->>'entity_research_job_id')::uuid
                       AND subject_type = 'account'
                       AND subject_entity_id = NEW.account_id
                       AND workspace_id = NEW.workspace_id
                       AND project_id = NEW.project_id
                       AND project_run_id = NEW.project_run_id
                ) THEN
                    RAISE EXCEPTION 'tierless account-gap operation requires its exact account job';
                END IF;
                RETURN NEW;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM claim
                 WHERE id = NEW.tier_claim_id
                   AND workspace_id = NEW.workspace_id
                   AND entity_id = NEW.account_id
                   AND field_key = 'account.scoring.tier'
                   AND superseded_by IS NULL
            ) THEN
                RAISE EXCEPTION 'account-gap tier claim must be live and match its account';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION committee_acquisition_validate_tier_claim() RETURNS trigger AS $$
        BEGIN
            IF NEW.tier_claim_id IS NULL THEN
                IF NULLIF(NEW.request_json->>'entity_research_job_id', '') IS NULL THEN
                    RAISE EXCEPTION 'historical committee operation requires a tier claim';
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM entity_research_job
                     WHERE job_id = (NEW.request_json->>'entity_research_job_id')::uuid
                       AND subject_type = 'account'
                       AND subject_entity_id = NEW.account_id
                       AND workspace_id = NEW.workspace_id
                       AND project_id = NEW.project_id
                       AND project_run_id = NEW.project_run_id
                ) THEN
                    RAISE EXCEPTION 'tierless committee operation requires its exact account job';
                END IF;
                RETURN NEW;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM claim
                 WHERE id = NEW.tier_claim_id
                   AND workspace_id = NEW.workspace_id
                   AND entity_id = NEW.account_id
                   AND field_key = 'account.scoring.tier'
                   AND superseded_by IS NULL
            ) THEN
                RAISE EXCEPTION 'committee tier claim must be live and match its account';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION account_gap_validate_tier_claim() RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM claim
                 WHERE id = NEW.tier_claim_id
                   AND workspace_id = NEW.workspace_id
                   AND entity_id = NEW.account_id
                   AND field_key = 'account.scoring.tier'
                   AND superseded_by IS NULL
            ) THEN
                RAISE EXCEPTION 'account-gap tier claim must be live and match its account';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION committee_acquisition_validate_tier_claim() RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM claim
                 WHERE id = NEW.tier_claim_id
                   AND workspace_id = NEW.workspace_id
                   AND entity_id = NEW.account_id
                   AND field_key = 'account.scoring.tier'
                   AND superseded_by IS NULL
            ) THEN
                RAISE EXCEPTION 'committee tier claim must be live and match its account';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "ALTER TABLE committee_acquisition_operation ALTER COLUMN tier_claim_id SET NOT NULL"
    )
    op.execute("ALTER TABLE account_gap_operation ALTER COLUMN tier_claim_id SET NOT NULL")
