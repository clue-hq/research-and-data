"""lane D D0 durable thread shell

Revision ID: fb558870202b
Revises: 870fe4f2af87
Create Date: 2026-08-08 11:38:21.297735+00:00

FI Lane D slice D0 (``docs/specs/FI-lane-D-production-chat-and-launch.md`` §3-P1): REQ-21's durable
shell. Four things land here, all additive:

1. **``agent_thread``** — the thread entity REQ-21 specified and nothing implemented. It is
   deliberately **not** under the C6 append-only trigger: a thread is mutable *shell* state (title,
   pinned, archived), not a receipt. Every receipt about what happened in the thread stays in the 13
   append-only agent-plane tables, which are untouched.
2. **``agent_turn`` ownership columns** — ``submitted_by_user_id`` /
   ``submitted_via_membership_id``,
   the Clue-owned internal identities `FI-lane-B-authenticated-principal-contract.md` §7 requires
   a human turn to persist *before* enqueue. Both are nullable: every turn written today (the
   stage-0 trial, the entity-research fleet, specialist delegations) has no human submitter,
   and inventing one would be exactly the fabricated identity Lane B forbids. No provider (Clerk)
   value ever enters either column — they hold ``platform_user.user_id`` /
   ``workspace_membership.membership_id`` only. There is **no** foreign key to those two tables:
   they are Lane B B1's and do not exist on this branch; adding the FKs is a later join slice.
3. **The grandfathered thread FK** — ``agent_turn (thread_id, workspace_id)`` references
   ``agent_thread (id, workspace_id)`` ``NOT VALID``, so historical rows are never scanned while
   every new write is checked. ``agent_thread_message`` deliberately gets **no** FK of its own: its
   thread integrity already rides its composite FK to ``agent_turn (id, workspace_id, thread_id)``,
   so a message provably shares its turn's ``(workspace_id, thread_id)`` and that pair is what this
   constraint now proves resolves to a thread. A second FK would be redundant, not safer.
4. **Two read indexes** — the ``get_onboarding_input_for_artifact`` lookup
   (``subsystems/research/clue_research/stage0/governed.py``) had none, and the project-scoped turn
   pagination this slice adds needs a ``(workspace_id, project_id, requested_at, id)`` key
   (``agent_turn`` had only the thread-scoped equivalent).

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
revision: str = "fb558870202b"
down_revision: str | None = "870fe4f2af87"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- the thread entity (REQ-21) -----------------------------------------------------------
    # Mutable shell state, so no append-only trigger. ``status``/``pinned``/``title`` are exactly
    # the three things the frontend's authored thread contract mutates
    # (apps/frontend/docs/api-contracts/projects.md), and each mutation is a governed tool call.
    op.execute(
        """
        CREATE TABLE agent_thread (
            id                        text PRIMARY KEY,
            workspace_id              text NOT NULL,
            project_id                text NOT NULL,
            created_by_user_id        text,
            created_via_membership_id text,
            status                    text NOT NULL DEFAULT 'active',
            pinned                    boolean NOT NULL DEFAULT false,
            title                     text,
            created_at                timestamptz NOT NULL DEFAULT now(),
            updated_at                timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT agent_thread_workspace_fk
                FOREIGN KEY (workspace_id) REFERENCES workspace (workspace_id),
            CONSTRAINT agent_thread_project_fk
                FOREIGN KEY (project_id, workspace_id)
                REFERENCES project (project_id, workspace_id),
            -- The anchor the agent_turn FK below references, and the reason every thread read can
            -- be workspace-scoped structurally rather than by remembering a WHERE clause.
            CONSTRAINT agent_thread_workspace_anchor UNIQUE (id, workspace_id),
            CONSTRAINT agent_thread_status CHECK (status IN ('active', 'archived')),
            CONSTRAINT agent_thread_identity_nonempty CHECK (
                length(btrim(id)) > 0
                AND length(btrim(workspace_id)) > 0
                AND length(btrim(project_id)) > 0
            ),
            -- A blank title is not a title; absent is the honest representation of "unnamed".
            CONSTRAINT agent_thread_title_nonempty CHECK (
                title IS NULL OR length(btrim(title)) > 0
            ),
            CONSTRAINT agent_thread_owner_nonempty CHECK (
                (created_by_user_id IS NULL OR length(btrim(created_by_user_id)) > 0)
                AND (
                    created_via_membership_id IS NULL
                    OR length(btrim(created_via_membership_id)) > 0
                )
            ),
            -- A membership without the user it belongs to is nonsense; the reverse is legitimate
            -- until Lane B B4 carries membership through the ToolContext seam.
            CONSTRAINT agent_thread_membership_requires_user CHECK (
                created_via_membership_id IS NULL OR created_by_user_id IS NOT NULL
            )
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE agent_thread IS 'REQ-21 thread shell: threads belong to projects. "
        "Mutable (title/pinned/status), unlike the 13 append-only agent-plane receipt tables. "
        "created_by_user_id / created_via_membership_id hold Clue-owned internal ids "
        "(platform_user.user_id / workspace_membership.membership_id) only — never a provider "
        "(Clerk) identifier, per FI-lane-B-authenticated-principal-contract.md ruling 3.'"
    )
    # The listing key for "this project's threads, oldest first, keyset-paginated".
    op.execute(
        "CREATE INDEX agent_thread_project_listing "
        "ON agent_thread (workspace_id, project_id, created_at, id)"
    )

    # --- agent_turn: durable submitter identity (Lane B contract §7) ----------------------------
    # ADD COLUMN is DDL; the append-only trigger guards row UPDATE/DELETE and does not see it.
    op.execute(
        """
        ALTER TABLE agent_turn
            ADD COLUMN submitted_by_user_id text,
            ADD COLUMN submitted_via_membership_id text,
            ADD CONSTRAINT agent_turn_submitter_nonempty CHECK (
                (submitted_by_user_id IS NULL OR length(btrim(submitted_by_user_id)) > 0)
                AND (
                    submitted_via_membership_id IS NULL
                    OR length(btrim(submitted_via_membership_id)) > 0
                )
            ),
            ADD CONSTRAINT agent_turn_submitter_membership_requires_user CHECK (
                submitted_via_membership_id IS NULL OR submitted_by_user_id IS NOT NULL
            )
        """
    )

    # --- the grandfathered thread FK ------------------------------------------------------------
    # NOT VALID: existing rows are never scanned (legacy trial/fleet threads predate the table),
    # while every new turn must name a thread that exists in its own workspace. The turn journal
    # provisions the thread row for platform-originated turns, so this is enforceable today.
    op.execute(
        """
        ALTER TABLE agent_turn
            ADD CONSTRAINT agent_turn_thread_fk
                FOREIGN KEY (thread_id, workspace_id)
                REFERENCES agent_thread (id, workspace_id)
                NOT VALID
        """
    )

    # --- read indexes ---------------------------------------------------------------------------
    # Project-scoped keyset pagination over turns (clue_projections.agent_turns_for_project). The
    # thread-scoped twin (agent_turn_thread_requested) already exists; this is its project sibling.
    op.execute(
        "CREATE INDEX agent_turn_project_requested "
        "ON agent_turn (workspace_id, project_id, requested_at, id)"
    )
    # ``get_onboarding_input_for_artifact``'s exact predicate — equality on
    # (workspace_id, project_id, artifact_key, actor) then ORDER BY created_at DESC, id DESC. The
    # optional ``kind`` filter is deliberately not in the key: it is a cheap recheck on the one row
    # the ordering already selects.
    op.execute(
        "CREATE INDEX onboarding_input_artifact_capture "
        "ON onboarding_input (workspace_id, project_id, artifact_key, actor, created_at DESC, "
        "id DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS onboarding_input_artifact_capture")
    op.execute("DROP INDEX IF EXISTS agent_turn_project_requested")
    op.execute("ALTER TABLE agent_turn DROP CONSTRAINT IF EXISTS agent_turn_thread_fk")
    op.execute(
        """
        ALTER TABLE agent_turn
            DROP CONSTRAINT IF EXISTS agent_turn_submitter_membership_requires_user,
            DROP CONSTRAINT IF EXISTS agent_turn_submitter_nonempty,
            DROP COLUMN IF EXISTS submitted_via_membership_id,
            DROP COLUMN IF EXISTS submitted_by_user_id
        """
    )
    op.execute("DROP INDEX IF EXISTS agent_thread_project_listing")
    op.execute("DROP TABLE IF EXISTS agent_thread")
