"""tool_invocation A9 idempotency (B4 slice 2)

Revision ID: 49911e6aac37
Revises: 86b9c791ae12
Create Date: 2026-07-22 07:08:27.755561+00:00

The A9 toolbelt-idempotency record (PB-B4 D6): one row per ``(workspace_id, idempotency_key)``
capturing the canonicalised request-body hash, the invoking ``tool_name``, a ``status``
(``pending`` while an invocation holds the reservation, ``completed`` once it lands its response),
and the JSON response, so a keyed tool invocation deduplicates **per tenant**:

* same (ws, key) + same tool + same body within its TTL, ``completed`` → replay the stored
  ``response_json`` (no re-execution);
* same (ws, key) + a *different* body OR a *different* tool within its TTL → ``IdempotencyConflict``
  (the pause/resume same-body trap dies via the ``tool_name`` check);
* same (ws, key) still ``pending`` → ``IdempotencyConflict`` (a same-key invocation is in flight);
* the **same** key in a *different* ``workspace_id`` → a clean miss (a fresh execution, no
  cross-tenant replay/leak) — which is why the scope is ``(workspace_id, idempotency_key)``;
* a reused key past its TTL → a fresh invocation (the reservation upsert overwrites a stale row).

The ``status`` discriminator is the B4 slice-2 up-front **reservation** (S4): a keyed call
``INSERT``s a ``pending`` row before it executes (``ON CONFLICT DO NOTHING`` unless the existing row
is TTL-expired), so a concurrent same-key double-submit loses the reservation and refuses rather
than double-executing; a failed invoke ``DELETE``s its ``pending`` reservation (a
``PreconditionFailed`` must never be cached).

This is **additive** over the M7.4 durable idempotency ledger (``idempotency_ledger``, the domain
``account_step`` / ``campaign_phase`` scopes) — a *different*, generic A9 dedup at the toolbelt HTTP
edge; the two never share a table. TTL is enforced in the loader (``created_at`` within
``CLUE_TOOLBELT_IDEMPOTENCY_TTL_S``), not by a DB sweep.

Branch-local amendment note (B4 slice-2 review hardening): this migration is amended **in place**
(it was never deployed — it is the branch head). A dev DB stamped on the *old* single-column-PK
shape must ``make db-fresh`` (drop + re-upgrade) to pick up the ``workspace_id`` / ``status``
columns and the composite PK.

Conventions every migration must honour (docs/specs/M00-foundations-and-shared-contracts.md §M0.3):
- Forward + reverse: ``downgrade()`` must cleanly reverse ``upgrade()`` (CI runs up → down → up).
- UTC ``timestamptz`` for time columns; JSONB payload with a real indexed PK on the hot key.
- Historical migration files stay byte-identical; this migration only adds the new table.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "49911e6aac37"
down_revision: str | None = "86b9c791ae12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE tool_invocation (
            workspace_id    text        NOT NULL,
            idempotency_key text        NOT NULL,
            body_sha256     text        NOT NULL,
            tool_name       text        NOT NULL,
            status          text        NOT NULL DEFAULT 'completed',
            response_json   jsonb,
            created_at      timestamptz NOT NULL DEFAULT now(),

            -- One row per (workspace_id, idempotency_key): dedup is per-tenant, so the SAME key in
            -- a different workspace is a clean miss (no cross-tenant replay/leak). A retried keyed
            -- call deduplicates onto this row; the reservation upsert overwrites a TTL-expired one.
            CONSTRAINT tool_invocation_pkey PRIMARY KEY (workspace_id, idempotency_key),
            -- The A9 reservation lifecycle: 'pending' (an invocation holds the slot, response NULL)
            -- or 'completed' (the response landed).
            CONSTRAINT tool_invocation_status_valid
                CHECK (status IN ('pending', 'completed')),
            -- A completed row always carries a JSON-object response (a ToolResult dump, never
            -- a bare scalar); a pending reservation carries none yet.
            CONSTRAINT tool_invocation_response_shape CHECK (
                (status = 'completed' AND jsonb_typeof(response_json) = 'object')
                OR (status = 'pending' AND response_json IS NULL)
            )
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE tool_invocation IS 'A9 toolbelt-idempotency record (PB-B4 D6). One row "
        "per (workspace_id, idempotency_key): body_sha256 (canonicalised request hash) + tool_name "
        "+ status (pending|completed) + response_json (a ToolResult dump). Same (ws,key,tool,body) "
        "within CLUE_TOOLBELT_IDEMPOTENCY_TTL_S replays; a different body/tool or an in-flight "
        "pending row conflicts; the same key in another workspace is a clean miss. Additive over "
        "idempotency_ledger (the M7.4 domain scopes).'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tool_invocation")
