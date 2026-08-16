"""D8 retention — the three indexes the two new sweeps read through.

Revision ID: 6f81d8fd729a
Revises: eb9c5b963f40
Create Date: 2026-08-10 10:56:06.786257+00:00

Design-integration Part II, slice D8 (ruling R-D8-4). No table, column, constraint or trigger
changes here — this migration adds **indexes only**, so it is trivially reversible and cannot
alter the meaning of a single row. Two sweeps land in D8 and each needs its scan to be served:

1. ``clue_execution.stream_tokens.sweep_stream_tokens`` deletes spent tokens — rows both consume
   statements already refuse (``used_at IS NULL AND expires_at > now()``). Its predicate is a
   two-branch OR (``expires_at`` in the past OR ``used_at`` stamped), so it needs one index per
   branch for the planner to BitmapOr them instead of scanning the whole table:
   ``stream_token_expires_at`` and the partial ``stream_token_used_at``. The partial index is
   deliberately partial — an unused token has ``used_at IS NULL`` and is exactly the row the sweep
   must NOT touch, so keeping it out of the index makes the index both smaller and honest about
   what it is for.
2. ``lumen_api.event_pruner`` scans ``design_agent_run`` for runs that have been TERMINAL for
   longer than the retention floor. ``design_agent_run_status_updated`` is a plain composite on
   ``(status, updated_at)`` — status equality first, then the age range, which is exactly the
   scan's shape. The pre-existing ``design_agent_run_workspace (workspace_id, updated_at DESC)``
   cannot serve it: it leads with the workspace, and the retention scan is deliberately
   cross-tenant.

   Composite rather than a partial index ``WHERE status IN ('succeeded','failed')``: an enum
   comparison in an index predicate has to be written against the enum type (``status::text`` is
   rejected — "functions in index predicate must be marked IMMUTABLE"), which would pin the index
   to the type's current OID and make it collateral damage of the next ``design_run_status``
   rebuild. A composite on the column survives that rebuild (PostgreSQL reindexes on
   ``ALTER COLUMN … TYPE``) and needs no restatement of the terminal vocabulary in DDL.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6f81d8fd729a"
down_revision: str | None = "eb9c5b963f40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- the stream_token sweep's two branches ------------------------------------------------
    op.execute("CREATE INDEX stream_token_expires_at ON stream_token (expires_at)")
    op.execute(
        "CREATE INDEX stream_token_used_at ON stream_token (used_at) WHERE used_at IS NOT NULL"
    )
    op.execute(
        "COMMENT ON INDEX stream_token_expires_at IS 'D8 retention: serves the expired half of "
        "sweep_stream_tokens (expires_at < now() - grace). A row past its expiry is already "
        "unreadable — both consume statements require expires_at > now().'"
    )
    op.execute(
        "COMMENT ON INDEX stream_token_used_at IS 'D8 retention: serves the used half of "
        "sweep_stream_tokens. Partial on used_at IS NOT NULL because an UNUSED token is precisely "
        "the row the sweep must never delete.'"
    )

    # --- the design event pruner's eligibility scan --------------------------------------------
    op.execute(
        "CREATE INDEX design_agent_run_status_updated ON design_agent_run (status, updated_at)"
    )
    op.execute(
        "COMMENT ON INDEX design_agent_run_status_updated IS 'D8 retention: serves "
        "clue_design.runs.list_prunable_terminal_runs (status IN terminal AND updated_at older "
        "than the retention floor). Cross-tenant because retention is a substrate property, so "
        "the workspace-leading design_agent_run_workspace index cannot serve it.'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS design_agent_run_status_updated")
    op.execute("DROP INDEX IF EXISTS stream_token_used_at")
    op.execute("DROP INDEX IF EXISTS stream_token_expires_at")
