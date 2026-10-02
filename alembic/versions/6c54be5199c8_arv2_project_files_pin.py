"""arv2 project files pin

Revision ID: 6c54be5199c8
Revises: c90aaea30a88
Create Date: 2026-09-12 11:36:42.125005+00:00

Conventions every migration must honour (docs/specs/M00-foundations-and-shared-contracts.md §M0.3;
see src/clue_research/db/README.md "Migration conventions checklist"):
- Append-only: claim history supersedes via ``superseded_by``; never UPDATE a value column in place.
- UTC ``timestamptz`` for time columns (e.g. ``observed_at`` / ``collected_at``).
- JSONB ``value_json`` payloads, with real indexed columns on the hot query keys (``entity_id`` …).
- Everything keys on a resolved ``entity_id`` — never a free-text name.
- Forward + reverse: ``downgrade()`` must cleanly reverse ``upgrade()`` (CI runs up → down → up).

Project context files (2026-09-12). A production Head-of-ABM turn opens on a compiled set of
per-project files — ``status.md``, ``decisions.md`` — seeded read-only under ``inputs/project/``.
Those files are recompiled as the project moves, so a turn that resolved "the current files"
independently on every attempt could seed one set, crash, and seed a different set on the retry:
the file the model was told to re-read would have moved underneath it.

This table applies to project files exactly the discipline ``agent_turn_knowledge_pin``
(``a3fc75e248e0``) applies to brand knowledge documents: one insert-once row per turn, written
before composition, carrying the exact file refs and one digest over the whole set. Every later
attempt of that turn reads this row instead of recompiling.

``files_sha256`` is a bare 64-hex sha256 — never a ``sha256:``-prefixed card digest — so two
attempts of one turn compare their pins without a normalization step.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6c54be5199c8"
down_revision: str | None = "c90aaea30a88"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE agent_turn_project_files (
            turn_id       uuid PRIMARY KEY,
            workspace_id  text NOT NULL,
            project_id    text NOT NULL,
            files         jsonb NOT NULL,
            files_sha256  text NOT NULL,
            pinned_at     timestamptz NOT NULL DEFAULT now(),

            -- The same turn anchor agent_turn_knowledge_pin uses: a pin can only name a turn that
            -- was really submitted, in the pin's own workspace.
            CONSTRAINT agent_turn_project_files_submission_fk
                FOREIGN KEY (turn_id, workspace_id)
                REFERENCES agent_turn_submission (turn_id, workspace_id),
            -- Composite, so a pin can never name a project in another workspace.
            CONSTRAINT agent_turn_project_files_project_fk
                FOREIGN KEY (project_id, workspace_id)
                REFERENCES project (project_id, workspace_id),
            CONSTRAINT agent_turn_project_files_identity_nonempty CHECK (
                length(btrim(workspace_id)) > 0
                AND length(btrim(project_id)) > 0
            ),
            CONSTRAINT agent_turn_project_files_array CHECK (
                jsonb_typeof(files) = 'array'
            ),
            CONSTRAINT agent_turn_project_files_sha256 CHECK (
                files_sha256 ~ '^[0-9a-f]{64}$'
            )
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE agent_turn_project_files IS 'The immutable set of compiled project "
        "files (inputs/project/**) one AGENT_TURN opens with, written before composition. Every "
        "retry of the turn seeds exactly these bytes; rows that change meanwhile affect only a "
        "later turn.'"
    )
    op.execute(
        "COMMENT ON COLUMN agent_turn_project_files.files_sha256 IS 'Bare 64-hex sha256 over the "
        "pinned files in path order — the value two attempts of one turn compare to prove they "
        "composed the same project context.'"
    )
    op.execute(
        "CREATE INDEX agent_turn_project_files_project "
        "ON agent_turn_project_files (workspace_id, project_id, pinned_at DESC)"
    )
    op.execute(
        "CREATE TRIGGER agent_turn_project_files_append_only "
        "BEFORE UPDATE OR DELETE ON agent_turn_project_files "
        "FOR EACH ROW EXECUTE FUNCTION execution_reject_append_only_mutation()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS agent_turn_project_files_append_only ON agent_turn_project_files"
    )
    op.execute("DROP INDEX IF EXISTS agent_turn_project_files_project")
    op.execute("DROP TABLE IF EXISTS agent_turn_project_files")
