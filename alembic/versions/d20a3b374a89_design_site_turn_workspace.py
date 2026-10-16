"""design site turn workspace

Revision ID: d20a3b374a89
Revises: c8c3d99be272
Create Date: 2026-10-16 12:36:30.507090+00:00

Site-turn durability (docs/superpowers/plans/2026-10-16-site-turn-durability.md §2.1, Task 3):
ONE working copy per running site turn, overwritten in place, never a pile of copies. It holds the
text of the turn's editable files (pages, shell, plan.md, fetched/, and the offloads the
conversation may refer to later) and the turn's in-memory state (sections written and images added
this turn, round and time counters), stamped with the LangGraph checkpoint id it matches. A turn
taken over after a worker dies lays these files over a folder rebuilt from the stored site and
resumes the conversation from that checkpoint, so nothing finished is redone.

The row is deleted when its run reaches a terminal status (``clue_design.site_turn_workspace``,
called from every terminal write in ``clue_design.runs``), together with the run's checkpoints.
``attempt_generation`` is the lease generation of the attempt that wrote the row; a write from an
attempt that no longer holds the run is refused by the DAL.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "d20a3b374a89"
down_revision: str | None = "c8c3d99be272"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE design_site_turn_workspace (
            run_id             text        NOT NULL,
            workspace_id       text        NOT NULL,
            checkpoint_id      text        NOT NULL,
            files              jsonb       NOT NULL,
            turn_state         jsonb       NOT NULL,
            files_sha256       text        NOT NULL,
            attempt_generation bigint,
            updated_at         timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT design_site_turn_workspace_pkey PRIMARY KEY (run_id),
            CONSTRAINT design_site_turn_workspace_run_fk FOREIGN KEY (run_id, workspace_id)
                REFERENCES design_agent_run (run_id, workspace_id) ON DELETE CASCADE,
            CONSTRAINT design_site_turn_workspace_checkpoint_nonempty
                CHECK (length(checkpoint_id) > 0),
            CONSTRAINT design_site_turn_workspace_files_object
                CHECK (jsonb_typeof(files) = 'object'),
            CONSTRAINT design_site_turn_workspace_turn_state_object
                CHECK (jsonb_typeof(turn_state) = 'object'),
            CONSTRAINT design_site_turn_workspace_files_sha_shape
                CHECK (files_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT design_site_turn_workspace_generation_positive
                CHECK (attempt_generation IS NULL OR attempt_generation >= 1)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE design_site_turn_workspace")
