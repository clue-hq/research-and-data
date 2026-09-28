"""hostname lock and handle backfill

Revision ID: 770bf20802e1
Revises: c16e1ae684b3
Create Date: 2026-09-28 16:55:48.794729+00:00

Custom-domain × F5 reconciliation (founder ruling 2026-09-28). Two hosting designs met in the
2026-09-28 merge: ours (``workspace_hostname``, the registry every public request resolves
through) and F5's (``design_workspace_handle``, one DNS label per workspace, frozen at the first
publish). Ours wins; F5's lock rule is adopted. This revision does three things:

1. **``workspace_hostname.locked_at``** — the first publish freezes a workspace's system label
   (F5 R-F5-5, adopted). A NULLABLE TIMESTAMP rather than a boolean, for F5's reason: "locked,
   and since when" answers a support question "locked" cannot, and NULL is the honest "never
   published". Only system rows are ever locked (``clue_spine.lock_system_hostname``); the lock is a
   DAL invariant, not a CHECK, so an operator can still unlock deliberately.
2. **Handles become system labels.** Every ``design_workspace_handle`` row becomes the workspace's
   system row ``<handle>.<suffix>``, carrying its ``locked_at`` over. A workspace that already has
   a system row keeps it (S1 allocated it from the workspace name); its handle is dropped unread —
   both were derived from the same name and the S1 row is the one publish URLs were minted from.
   A handle whose hostname is already held by ANOTHER workspace is skipped (``ON CONFLICT``); that
   workspace is then left without a system row, which ``make pages-backfill-hostnames`` allocates.
3. **``design_workspace_handle`` is dropped.**

The suffix reaches SQL as the session setting ``clue.pages_system_suffix``, which
``alembic/env.py`` sets from ``Settings().pages_system_suffix`` right after connecting. When it is
unset (offline ``--sql`` mode) the backfill inserts nothing rather than guess a suffix.

Reversible: the downgrade recreates the F5 table verbatim (from ``5456c0770de8``), writes every
on-suffix system label back as that workspace's handle (with its lock), and drops the column.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "770bf20802e1"
down_revision: str | None = "c16e1ae684b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SUFFIX = "current_setting('clue.pages_system_suffix', true)"


def upgrade() -> None:
    op.execute("ALTER TABLE workspace_hostname ADD COLUMN locked_at timestamptz")
    op.execute(
        f"""
        INSERT INTO workspace_hostname (hostname, workspace_id, kind, status, activated_at,
                                        locked_at)
        SELECT h.handle || '.' || {_SUFFIX}, h.workspace_id, 'system', 'active', now(),
               h.locked_at
        FROM design_workspace_handle h
        WHERE {_SUFFIX} IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM workspace_hostname w
                          WHERE w.workspace_id = h.workspace_id AND w.kind = 'system')
        ON CONFLICT (hostname) DO NOTHING
        """
    )
    op.execute("DROP TABLE design_workspace_handle")


def downgrade() -> None:
    # Verbatim from 5456c0770de8.
    op.execute(
        """
        CREATE TABLE design_workspace_handle (
            workspace_id text NOT NULL,
            handle       text NOT NULL,
            locked_at    timestamptz,
            created_at   timestamptz NOT NULL DEFAULT now(),
            updated_at   timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT design_workspace_handle_pkey PRIMARY KEY (workspace_id),
            CONSTRAINT design_workspace_handle_workspace_fk
                FOREIGN KEY (workspace_id) REFERENCES workspace (workspace_id),
            -- One workspace per handle: this is also the reverse lookup the public host
            -- router runs on every request.
            CONSTRAINT design_workspace_handle_unique UNIQUE (handle),
            -- A DNS label, or nothing: 1 or 3..63 chars, lowercase alnum with inner dashes.
            CONSTRAINT design_workspace_handle_shape
                CHECK (handle ~ '^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?$')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_workspace_handle IS 'The DNS label a workspace''s published "
        "sites hang off (F5, ruling R-F5-5): {handle}.pages.cluehq.ai. Derived from the "
        "workspace name, editable while nothing is published, and frozen by locked_at at the "
        "first publish — a live URL''s host segment must not move under links already sent. "
        "The UNIQUE handle is also the public host router''s reverse lookup.'"
    )
    # Every on-suffix system label goes back as its workspace's handle, lock included. Only rows
    # under the configured suffix: the label alone is unique only within one suffix. The shape
    # guard keeps a hand-written label the F5 CHECK would refuse from failing the downgrade.
    op.execute(
        f"""
        INSERT INTO design_workspace_handle (workspace_id, handle, locked_at)
        SELECT workspace_id, split_part(hostname, '.', 1), locked_at
        FROM workspace_hostname
        WHERE kind = 'system'
          AND hostname = split_part(hostname, '.', 1) || '.' || {_SUFFIX}
          AND split_part(hostname, '.', 1) ~ '^[a-z0-9](?:[a-z0-9-]{{1,61}}[a-z0-9])?$'
        """
    )
    op.execute("ALTER TABLE workspace_hostname DROP COLUMN locked_at")
