"""design workspace handle

Revision ID: 5456c0770de8
Revises: 6893f29b6973
Create Date: 2026-09-03

F5 / founder ruling R-F5-5 (default): a workspace's published sites hang off ONE DNS label —
``{handle}.pages.cluehq.ai``. This table is where that label lives, and its whole design is the
two things that make a public URL trustworthy.

**One handle per workspace, and one workspace per handle.** ``workspace_id`` is the primary key
(a workspace cannot have two addresses) and ``handle`` is UNIQUE (two tenants cannot resolve to
the same host). The UNIQUE index is also the reverse lookup Task 15's host router runs on every
public request — ``handle -> workspace_id`` — so it is load-bearing for serving, not only for
integrity.

**The shape is a hostname segment, enforced in SQL.** ``design_workspace_handle_shape`` CHECKs
``^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?$``: lowercase alphanumerics with inner dashes, 1 or
3..63 characters, never leading or trailing a dash. The DAL shapes and validates too, but a
malformed label reaching the database would mint an unroutable host, so the constraint is the
backstop rather than the documentation — nothing that cannot be a subdomain can be stored.

**``locked_at`` is the point of the whole table.** The handle is derived from the workspace name
and stays editable while nothing is published; the FIRST PUBLISH sets ``locked_at`` and the DAL
refuses every later change. A published URL is something a marketer has already pasted into an
email — letting its host segment move afterwards would break links that are out in the world.
It is deliberately a NULLABLE TIMESTAMP rather than a boolean: "locked, and since when" answers
a support question that "locked" cannot, and NULL is the honest "never published" state.

No trigger, no immutability rule: unlike the publish tables this row is *meant* to be updated —
right up until it is locked. The lock is a DAL invariant over a nullable column, which keeps
un-locking possible as a deliberate, auditable operator action (a workspace that has taken every
site offline and wants its name back) instead of something only a migration could undo.

Hand-written and reversible: ``downgrade()`` drops the table (CI runs up -> down -> up).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5456c0770de8"
down_revision: str | None = "6893f29b6973"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.execute("DROP TABLE design_workspace_handle")
