"""tool_invocation A9 idempotency (B4 slice 2)

Revision ID: 49911e6aac37
Revises: 86b9c791ae12
Create Date: 2026-07-22 07:08:27.755561+00:00

The A9 toolbelt-idempotency record (PB-B4 D6): one row per ``idempotency_key`` capturing the
canonicalised request-body hash + the JSON response, so a keyed tool invocation deduplicates:

* same key + same body within its TTL → replay the stored ``response_json`` (no re-execution);
* same key + a *different* body within its TTL → ``IdempotencyConflict``;
* a reused key past its TTL → a fresh invocation (the loader treats the stale row as absent and the
  writer overwrites it via the ``ON CONFLICT`` upsert).

This is **additive** over the M7.4 durable idempotency ledger (``idempotency_ledger``, the domain
``account_step`` / ``campaign_phase`` scopes) — a *different*, generic A9 dedup at the toolbelt HTTP
edge; the two never share a table. TTL is enforced in the loader (``created_at`` within
``CLUE_TOOLBELT_IDEMPOTENCY_TTL_S``), not by a DB sweep, so the table needs no status lifecycle.

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
            idempotency_key text        NOT NULL,
            body_sha256     text        NOT NULL,
            tool_name       text        NOT NULL,
            response_json   jsonb       NOT NULL,
            created_at      timestamptz NOT NULL DEFAULT now(),

            -- One row per idempotency key (D6 "idempotency_key unique"): a retried keyed call
            -- deduplicates onto this row; the ON CONFLICT upsert overwrites a TTL-expired one.
            CONSTRAINT tool_invocation_pkey PRIMARY KEY (idempotency_key),
            -- The stored response is a ToolResult dump — always a JSON object, never a bare scalar.
            CONSTRAINT tool_invocation_response_is_object
                CHECK (jsonb_typeof(response_json) = 'object')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE tool_invocation IS 'A9 toolbelt-idempotency record (PB-B4 D6). One row "
        "per idempotency_key: body_sha256 (canonicalised request hash) + response_json (a "
        "ToolResult dump). Same key+body within CLUE_TOOLBELT_IDEMPOTENCY_TTL_S replays; same "
        "key+different body conflicts. Additive over idempotency_ledger (the M7.4 domain scopes).'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tool_invocation")
