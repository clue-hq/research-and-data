"""thread purge cleanup event

Revision ID: 5e78522ddf48
Revises: 98775241f1e5
Create Date: 2026-09-13 16:35:33.126329+00:00

Retention is keyed to threads, not turns: the agent workspace is one persistent directory per chat
thread, so what gets purged (and receipted) is a thread. The receipt still names the thread's
NEWEST turn for its NOT NULL composite FK (rulings addendum R4) and gains a nullable ``thread_id``
so a reader never has to join back through the turn to learn which directory went away.

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
revision: str = "5e78522ddf48"
down_revision: str | None = "98775241f1e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_ACTIONS = "('terminal_retention_purge', 'materialization_failure_purge')"
_NEW_ACTIONS = "('terminal_retention_purge', 'materialization_failure_purge', 'thread_purge')"


def upgrade() -> None:
    # Nullable, no backfill: the pre-existing per-turn purges did not purge a thread, so there is
    # no thread id to invent for them. NULL means "this receipt predates thread retention".
    op.execute("ALTER TABLE agent_workspace_cleanup_event ADD COLUMN thread_id text")
    op.execute(
        "ALTER TABLE agent_workspace_cleanup_event DROP CONSTRAINT agent_workspace_cleanup_action"
    )
    op.execute(
        "ALTER TABLE agent_workspace_cleanup_event "
        f"ADD CONSTRAINT agent_workspace_cleanup_action CHECK (action IN {_NEW_ACTIONS})"
    )
    # "What has already been purged in this workspace, and which thread was it?" — the sweep's
    # dedupe reads by turn, but every operator question is thread-shaped.
    op.execute(
        "CREATE INDEX agent_workspace_cleanup_thread_idx "
        "ON agent_workspace_cleanup_event (workspace_id, thread_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS agent_workspace_cleanup_thread_idx")
    # The restored CHECK cannot admit ``thread_purge`` rows, so they must go before it returns.
    # The table carries a C6.8 append-only trigger that rejects every DELETE; this migration is
    # the one authorised exception, so it disables the trigger for exactly this statement and
    # re-enables it immediately (the table is append-only again before the transaction commits).
    op.execute(
        "ALTER TABLE agent_workspace_cleanup_event "
        "DISABLE TRIGGER agent_workspace_cleanup_event_no_delete"
    )
    op.execute("DELETE FROM agent_workspace_cleanup_event WHERE action = 'thread_purge'")
    op.execute(
        "ALTER TABLE agent_workspace_cleanup_event "
        "ENABLE TRIGGER agent_workspace_cleanup_event_no_delete"
    )
    op.execute(
        "ALTER TABLE agent_workspace_cleanup_event DROP CONSTRAINT agent_workspace_cleanup_action"
    )
    op.execute(
        "ALTER TABLE agent_workspace_cleanup_event "
        f"ADD CONSTRAINT agent_workspace_cleanup_action CHECK (action IN {_OLD_ACTIONS})"
    )
    op.execute("ALTER TABLE agent_workspace_cleanup_event DROP COLUMN thread_id")
