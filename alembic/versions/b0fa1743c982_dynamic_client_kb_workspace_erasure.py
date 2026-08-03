"""dynamic client kb workspace erasure

Revision ID: b0fa1743c982
Revises: 282b9c7278c2
Create Date: 2026-08-03 07:40:31.278856+00:00

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
revision: str = "b0fa1743c982"
down_revision: str | None = "282b9c7278c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # One row is both the append-only audit and the no-resurrection barrier. Writers take a
    # FOR KEY SHARE lock on workspace and check this marker; erasure takes FOR UPDATE before
    # removing content, so a racing write lands wholly before the sweep or is refused after it.
    op.execute(
        """
        CREATE TABLE workspace_dynamic_client_kb_erasure (
            workspace_id          text PRIMARY KEY,
            erased_by             text NOT NULL,
            reason_code           text NOT NULL,
            definition_count      int NOT NULL,
            proposal_count        int NOT NULL,
            materialization_count int NOT NULL,
            readiness_policy_count int NOT NULL,
            claim_count           int NOT NULL,
            artifact_count        int NOT NULL,
            erased_at             timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT workspace_dynamic_client_kb_erasure_workspace_fk
                FOREIGN KEY (workspace_id) REFERENCES workspace (workspace_id),
            CONSTRAINT workspace_dynamic_client_kb_erasure_actor
                CHECK (length(btrim(erased_by)) BETWEEN 1 AND 256),
            CONSTRAINT workspace_dynamic_client_kb_erasure_reason
                CHECK (reason_code = 'workspace_dynamic_client_kb_erasure'),
            CONSTRAINT workspace_dynamic_client_kb_erasure_counts CHECK (
                definition_count >= 0
                AND proposal_count >= 0
                AND materialization_count >= 0
                AND readiness_policy_count >= 0
                AND claim_count >= 0
                AND artifact_count >= 0
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE workspace_dynamic_client_kb_claim_erasure (
            workspace_id       text NOT NULL,
            erased_claim_id    uuid NOT NULL,
            tombstone_claim_id uuid NOT NULL,
            reason_code        text NOT NULL,
            erased_at          timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT workspace_dynamic_client_kb_claim_erasure_pkey
                PRIMARY KEY (workspace_id, erased_claim_id),
            CONSTRAINT workspace_dynamic_client_kb_claim_erasure_parent_fk
                FOREIGN KEY (workspace_id)
                REFERENCES workspace_dynamic_client_kb_erasure (workspace_id)
                DEFERRABLE INITIALLY DEFERRED,
            CONSTRAINT workspace_dynamic_client_kb_claim_erasure_old_fk
                FOREIGN KEY (erased_claim_id, workspace_id)
                REFERENCES claim (id, workspace_id),
            CONSTRAINT workspace_dynamic_client_kb_claim_erasure_tombstone_fk
                FOREIGN KEY (tombstone_claim_id, workspace_id)
                REFERENCES claim (id, workspace_id),
            CONSTRAINT workspace_dynamic_client_kb_claim_erasure_reason
                CHECK (reason_code = 'workspace_dynamic_client_kb_erasure')
        )
        """
    )


def downgrade() -> None:
    op.drop_table("workspace_dynamic_client_kb_claim_erasure")
    op.drop_table("workspace_dynamic_client_kb_erasure")
