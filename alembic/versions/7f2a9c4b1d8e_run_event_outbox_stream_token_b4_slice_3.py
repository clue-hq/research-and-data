"""run_event outbox + stream_token (B4 slice 3)

Revision ID: 7f2a9c4b1d8e
Revises: 49911e6aac37
Create Date: 2026-07-22 13:10:00.000000+00:00

PB-B4 slice 3 (D8) adds the read-side transport substrate for the treaty SSE surface (REQ-11/A5),
generalizing the M12.3 ``handoff_event`` outbox pattern into two brand-new side tables:

* ``run_event`` — the **durable per-workspace run-event outbox**. The drive path (the
  ``ComposingRunDriver.advance`` boundary, wired at the ``clue_api`` composition root) writes one
  row per run lifecycle event (``run.phase.started`` / ``run.phase.completed`` /
  ``run.step.progress`` / ``run.done``). ``seq`` is a plain ``bigserial`` — **globally** monotone,
  so a workspace's rows form a strictly-increasing subsequence (**per-workspace ordering**, the
  documented guarantee: the SSE envelope's ``id`` is this ``seq``; replay filters ``seq > cursor``
  within one ``(workspace_id[, run_id])``). Payload is JSONB; ``created_at`` bounds the replay
  horizon (``CLUE_SSE_REPLAY_HORIZON_S``, a read-time window — no DB sweep here). Emission is
  at-least-once / seq-idempotent (a consumer dedups by ``seq``), never write-through into the claim
  store (conventions §6 — a one-directional research→transport seam, like ``handoff_event``).

* ``stream_token`` — the **single-use SSE stream token** table. A consumer mints a token
  (workspace- and optionally run-scoped, TTL ``CLUE_SSE_STREAM_TOKEN_TTL_S``) and presents it to
  open the ``GET …/events`` stream exactly once; ``used_at`` is stamped atomically on consumption
  (``… WHERE used_at IS NULL AND expires_at > now() RETURNING`` — a second use finds no live row
  and is refused). EventSource reconnect re-mints (the token authorises *opening* a stream;
  ``Last-Event-ID`` carries the replay cursor across connects independently of the token).

Both are additive side tables — no enum type, no trigger, no ALTER of any frozen contract. TTL /
horizon are enforced in the loader (``created_at`` / ``expires_at`` arithmetic), not by a sweep.

Conventions every migration honours (docs/specs/M00-foundations-and-shared-contracts.md §M0.3):
- Forward + reverse: ``downgrade()`` cleanly reverses ``upgrade()`` (CI runs up → down → up).
- UTC ``timestamptz`` for time columns; JSONB payload; a real indexed key on the hot replay path.
- Historical migration files stay byte-identical; this migration only adds two new tables.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7f2a9c4b1d8e"
down_revision: str | None = "49911e6aac37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE run_event (
            seq          bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            workspace_id text        NOT NULL,
            run_id       uuid        NOT NULL,
            topic        text        NOT NULL,
            payload      jsonb       NOT NULL DEFAULT '{}'::jsonb,
            created_at   timestamptz NOT NULL DEFAULT now(),

            -- A stored run-event always carries a JSON-object payload (never a bare scalar), so a
            -- consumer's ``data`` is always a decodable object.
            CONSTRAINT run_event_payload_object CHECK (jsonb_typeof(payload) = 'object')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE run_event IS 'B4 slice-3 (D8) durable per-workspace SSE run-event "
        "outbox. "
        "seq is a globally-monotone bigserial (a workspace''s rows form a strictly-increasing "
        "subsequence = per-workspace ordering); the SSE envelope id is this seq; replay filters "
        "seq > cursor within one (workspace_id[, run_id]). At-least-once / seq-idempotent; "
        "one-directional (drive-path -> transport), never a claim-store write-back.'"
    )
    # Replay hot path: a workspace stream reads its own rows in seq order (the SSE Last-Event-ID
    # cursor filters seq > :cursor). The composite index makes both the workspace stream and the
    # per-run stream (run_id filter) index-served.
    op.execute("CREATE INDEX run_event_workspace_seq ON run_event (workspace_id, seq)")
    op.execute("CREATE INDEX run_event_workspace_run_seq ON run_event (workspace_id, run_id, seq)")

    op.execute(
        """
        CREATE TABLE stream_token (
            token         uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id  text        NOT NULL,
            run_id        uuid,
            created_at    timestamptz NOT NULL DEFAULT now(),
            expires_at    timestamptz NOT NULL,
            used_at       timestamptz,

            -- A token expires strictly after it is minted.
            CONSTRAINT stream_token_expiry_after_creation CHECK (expires_at > created_at)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE stream_token IS 'B4 slice-3 (D8) single-use SSE stream token. Workspace- "
        "and optionally run-scoped, TTL CLUE_SSE_STREAM_TOKEN_TTL_S; used_at is stamped atomically "
        "on consumption (WHERE used_at IS NULL AND expires_at > now() RETURNING), so a second use "
        "finds no live row and is refused. EventSource reconnect re-mints.'"
    )
    # Consumption filters on (token) with a live-row predicate; tenant reads scope on workspace_id.
    op.execute("CREATE INDEX stream_token_workspace ON stream_token (workspace_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS stream_token_workspace")
    op.execute("DROP TABLE IF EXISTS stream_token")
    op.execute("DROP INDEX IF EXISTS run_event_workspace_run_seq")
    op.execute("DROP INDEX IF EXISTS run_event_workspace_seq")
    op.execute("DROP TABLE IF EXISTS run_event")
