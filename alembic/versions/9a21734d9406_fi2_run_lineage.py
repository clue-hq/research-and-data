"""fi2 run lineage

Revision ID: 9a21734d9406
Revises: c6d84aa84b79
Create Date: 2026-08-07 20:37:09.064632+00:00

FI-2 pillar P2 (``docs/specs/FI-2-workspace-account-layer.md`` §3): the claim→project join spine.
Every claim already carries ``run_id NOT NULL``; ``run_lineage`` supplies the missing back-join
from a run to the project that produced it, so the project lens reads
``claim.run_id IN (SELECT run_id FROM run_lineage WHERE workspace_id = … AND project_id = …)``.
Registration happens once per run at mint time (idempotent upsert), never per claim.

``project_id`` is nullable: a workspace-level run (stage 0, seeds, client-KB) belongs to no
project. ``kind`` is text + a named CHECK rather than a DB enum (no new enum types), mirroring
``clue_research.claimstore.run_lineage.RUN_LINEAGE_KINDS``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9a21734d9406"
down_revision: str | None = "c6d84aa84b79"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE run_lineage (
            run_id          uuid        NOT NULL,
            workspace_id    text        NOT NULL,
            project_id      text        NULL,
            project_run_id  uuid        NULL,
            kind            text        NOT NULL,
            created_at      timestamptz NOT NULL,

            CONSTRAINT run_lineage_pkey PRIMARY KEY (run_id),
            CONSTRAINT run_lineage_project_run_fk FOREIGN KEY (project_run_id)
                REFERENCES project_run (id),
            CONSTRAINT run_lineage_kind_check CHECK (kind IN
                ('discovery','import','scoring','tiering','entity_research','committee',
                 'contact_research','narrative','stage0','enrichment','manual'))
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE run_lineage IS 'FI-2 P2: run -> project attribution for claims "
        "(claim.run_id back-join). One row per run, registered at run creation. "
        "NULL project_id = a workspace-level run (stage 0, seeds, client-KB).'"
    )
    # The project-lens predicate reads (workspace_id, project_id) — the only hot query.
    op.execute("CREATE INDEX run_lineage_by_project ON run_lineage (workspace_id, project_id)")


def downgrade() -> None:
    op.execute("DROP TABLE run_lineage")
