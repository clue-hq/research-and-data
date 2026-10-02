"""focused account reconciliation checkpoints

Revision ID: f3eb43c7808f
Revises: 4c916b02ed9b
Create Date: 2026-09-28 03:21:48.855976+00:00

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
revision: str = "f3eb43c7808f"
down_revision: str | None = "4c916b02ed9b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""CREATE TABLE arv2_research_import_ready (
      workspace_id text NOT NULL,
      job_id uuid NOT NULL REFERENCES arv2_research_job(job_id) ON DELETE CASCADE,
      dossier_version integer NOT NULL,
      CONSTRAINT research_import_version_positive CHECK (dossier_version > 0),
      artifact_key text NOT NULL REFERENCES artifact(storage_key),
      imported_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (job_id, dossier_version)
    )""")
    op.execute("""CREATE TABLE arv2_narrative_reconciliation (
      generation_id uuid NOT NULL REFERENCES arv2_account_research_generation(generation_id)
        ON DELETE CASCADE,
      input_revision bigint NOT NULL,
      workspace_id text NOT NULL,
      state text NOT NULL DEFAULT 'prepared',
      packet_key text NOT NULL REFERENCES artifact(storage_key),
      response_key text REFERENCES artifact(storage_key),
      claim_versions jsonb NOT NULL,
      block_versions jsonb NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      completed_at timestamptz,
      CONSTRAINT reconciliation_state
        CHECK (state IN ('prepared','generated','completed','failed')),
      PRIMARY KEY(generation_id,input_revision)
    )""")


def downgrade() -> None:
    op.execute("DROP TABLE arv2_narrative_reconciliation")
    op.execute("DROP TABLE arv2_research_import_ready")
