"""D7 Round B — drop ``design_run_event``: the design leg streams on the platform outbox

Revision ID: eb9c5b963f40
Revises: a02cbcb6e641
Create Date: Part II slice D7 Round B

``design_run_event`` was born labelled temporary (D1f: *"dies at D7"*, in the table's own COMMENT).
Round A widened ``run_event`` with a subject taxonomy; Round B moves the design leg onto it —
``design.run.event`` / ``design.run.completed`` / ``design.run.failed`` under
``subject_kind='design_run'`` — and this migration removes the substrate it replaced. With the
table go its per-run ``seq`` (the platform outbox's global identity column assigns event ids now),
its ``FOR UPDATE`` allocator, and the private polled SSE route that read it.

**Why the downgrade only recreates the shape, and does not refuse on rows.** Two of this branch's
migrations (D5's reshape, Round A's widening) refuse to downgrade while incompatible data exists,
because in both cases a downgrade would have *destroyed* information with no other home. That is
not the situation here: the data this table used to hold now lives in ``run_event``, which the
downgrade leaves untouched. Recreating the empty structure restores the pre-D7 schema exactly —
constraints, index and COMMENT included — so the older code that expects it can run; it simply
starts with no history, which is the honest state for a log whose writer was removed. Refusing on
rows would be worse than useless: this table's rows can only be pre-D7 leftovers, and refusing to
downgrade *because the old code left data behind* would make the downgrade path unusable precisely
when it is wanted.

Hand-written and reversible: ``downgrade()`` mirrors ``upgrade()`` (CI runs up → down → up).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "eb9c5b963f40"
down_revision: str | None = "a02cbcb6e641"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The index is owned by the table and would go with it; dropped explicitly so the statement
    # pair mirrors the downgrade's create pair one-for-one.
    op.execute("DROP INDEX IF EXISTS design_run_event_run")
    op.execute("DROP TABLE IF EXISTS design_run_event")


def downgrade() -> None:
    # Byte-for-byte the D1f (``e79f192828b1``) definition — same column list, same constraint
    # names, same index, same COMMENT — so a downgraded database is indistinguishable from a
    # pre-D7 one apart from holding no rows.
    op.execute(
        """
        CREATE TABLE design_run_event (
            id           bigint GENERATED ALWAYS AS IDENTITY,
            workspace_id text NOT NULL,
            run_id       text NOT NULL,
            seq          integer NOT NULL,
            event_type   text NOT NULL,
            data_json    jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at   timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT design_run_event_pkey PRIMARY KEY (id),
            CONSTRAINT design_run_event_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT design_run_event_run_fk
                FOREIGN KEY (run_id, workspace_id)
                REFERENCES design_agent_run (run_id, workspace_id) ON DELETE CASCADE,
            CONSTRAINT design_run_event_seq_unique UNIQUE (run_id, seq),
            CONSTRAINT design_run_event_data_object CHECK (jsonb_typeof(data_json) = 'object')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_run_event IS 'Ported design SSE event log (PD D1f) — "
        "TEMPORARY: dies at D7 when leg activity moves to design.* topics on the platform "
        "run_event stream (C5.1 subject-widening precedent). seq is the SSE event id, "
        "allocated under FOR UPDATE on the parent run row (D2 DAL).'"
    )
    op.execute("CREATE INDEX design_run_event_run ON design_run_event (run_id, seq)")
