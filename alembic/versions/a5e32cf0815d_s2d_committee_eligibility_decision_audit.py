"""s2d committee eligibility decision audit

Revision ID: a5e32cf0815d
Revises: f8a81c7e1563
Create Date: 2026-08-03 16:35:19.529084+00:00

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
revision: str = "a5e32cf0815d"
down_revision: str | None = "f8a81c7e1563"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE committee_eligibility_outcome AS ENUM ('eligible', 'reusable', 'ineligible')"
    )
    op.execute(
        """
        CREATE TABLE committee_eligibility_decision (
            id                          uuid NOT NULL,
            workspace_id                text NOT NULL,
            project_id                  text NOT NULL,
            project_run_id              uuid NOT NULL,
            account_id                  uuid NOT NULL,
            request_fingerprint         text NOT NULL,
            authorization_fingerprint   text NOT NULL,
            decision_fingerprint        text NOT NULL,
            policy_version              text NOT NULL,
            outcome                     committee_eligibility_outcome NOT NULL,
            conditions_json             jsonb NOT NULL,
            reason_codes_json           jsonb NOT NULL,
            evidence_refs_json          jsonb NOT NULL,
            reusable_operation_id       uuid,
            created_at                  timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT committee_eligibility_decision_pkey PRIMARY KEY (id),
            CONSTRAINT committee_eligibility_decision_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT committee_eligibility_decision_run_fk
                FOREIGN KEY (project_run_id, workspace_id, project_id)
                REFERENCES project_run (id, workspace_id, project_id),
            CONSTRAINT committee_eligibility_decision_account_fk
                FOREIGN KEY (account_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT committee_eligibility_decision_reuse_fk
                FOREIGN KEY (reusable_operation_id, workspace_id)
                REFERENCES committee_acquisition_operation (id, workspace_id),
            CONSTRAINT committee_eligibility_decision_fingerprint_unique
                UNIQUE (workspace_id, project_run_id, account_id, decision_fingerprint),
            CONSTRAINT committee_eligibility_decision_hashes CHECK (
                request_fingerprint ~ '^[0-9a-f]{64}$'
                AND authorization_fingerprint ~ '^[0-9a-f]{64}$'
                AND decision_fingerprint ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT committee_eligibility_decision_json_shapes CHECK (
                jsonb_typeof(conditions_json) = 'array'
                AND jsonb_array_length(conditions_json) = 7
                AND jsonb_typeof(reason_codes_json) = 'array'
                AND jsonb_typeof(evidence_refs_json) = 'array'
            ),
            CONSTRAINT committee_eligibility_decision_reuse_shape CHECK (
                (outcome = 'reusable') = (reusable_operation_id IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX committee_eligibility_decision_account_time "
        "ON committee_eligibility_decision (workspace_id, account_id, created_at DESC)"
    )
    op.execute(
        """
        CREATE FUNCTION committee_eligibility_reject_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'committee eligibility decisions are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER committee_eligibility_decision_immutable BEFORE UPDATE OR DELETE "
        "ON committee_eligibility_decision FOR EACH ROW "
        "EXECUTE FUNCTION committee_eligibility_reject_mutation()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER committee_eligibility_decision_immutable ON committee_eligibility_decision"
    )
    op.execute("DROP FUNCTION committee_eligibility_reject_mutation()")
    op.execute("DROP INDEX committee_eligibility_decision_account_time")
    op.execute("DROP TABLE committee_eligibility_decision")
    op.execute("DROP TYPE committee_eligibility_outcome")
