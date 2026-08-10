"""chat submission context and profile

Revision ID: 39513bbba38a
Revises: 18541ff11335
Create Date: 2026-08-09 22:29:03.758729+00:00

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
revision: str = "39513bbba38a"
down_revision: str | None = "18541ff11335"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE agent_turn_submission ADD COLUMN agent_profile_id text")
    op.execute(
        "ALTER TABLE agent_turn_submission ADD CONSTRAINT "
        "agent_turn_submission_profile_nonempty CHECK ("
        "agent_profile_id IS NULL OR length(btrim(agent_profile_id)) > 0)"
    )
    op.execute(
        "COMMENT ON COLUMN agent_turn_submission.agent_profile_id IS "
        "'The server-advertised agent profile selected for this submission. The fleet worker "
        "verifies it against the promoted immutable profile before execution.'"
    )

    op.execute(
        """
        CREATE TABLE agent_turn_submission_context_ref (
            turn_id        uuid NOT NULL,
            workspace_id   text NOT NULL,
            ordinal        integer NOT NULL,
            object_type    text NOT NULL,
            object_id      text NOT NULL,
            object_version integer,
            created_at     timestamptz NOT NULL DEFAULT now(),

            PRIMARY KEY (turn_id, ordinal),
            CONSTRAINT agent_turn_submission_context_ref_submission_fk
                FOREIGN KEY (turn_id, workspace_id)
                REFERENCES agent_turn_submission (turn_id, workspace_id),
            CONSTRAINT agent_turn_submission_context_ref_type
                CHECK (object_type IN ('account', 'contact')),
            CONSTRAINT agent_turn_submission_context_ref_ordinal
                CHECK (ordinal >= 0),
            CONSTRAINT agent_turn_submission_context_ref_object_nonempty
                CHECK (length(btrim(object_id)) > 0),
            CONSTRAINT agent_turn_submission_context_ref_version
                CHECK (object_version IS NULL OR object_version > 0)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE agent_turn_submission_context_ref IS "
        "'Ordered, immutable account/contact references supplied with one human chat submission. "
        "The HTTP boundary validates workspace ownership and contact/account relationships; the "
        "fleet worker rehydrates these rows into AgentTurnRequest.focus_refs.'"
    )
    op.execute(
        "CREATE INDEX agent_turn_submission_context_ref_object "
        "ON agent_turn_submission_context_ref (workspace_id, object_type, object_id)"
    )
    op.execute(
        "CREATE TRIGGER agent_turn_submission_context_ref_append_only "
        "BEFORE UPDATE OR DELETE ON agent_turn_submission_context_ref "
        "FOR EACH ROW EXECUTE FUNCTION execution_reject_append_only_mutation()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS agent_turn_submission_context_ref_append_only "
        "ON agent_turn_submission_context_ref"
    )
    op.execute("DROP INDEX IF EXISTS agent_turn_submission_context_ref_object")
    op.execute("DROP TABLE IF EXISTS agent_turn_submission_context_ref")
    op.execute(
        "ALTER TABLE agent_turn_submission "
        "DROP CONSTRAINT IF EXISTS agent_turn_submission_profile_nonempty"
    )
    op.execute("ALTER TABLE agent_turn_submission DROP COLUMN IF EXISTS agent_profile_id")
