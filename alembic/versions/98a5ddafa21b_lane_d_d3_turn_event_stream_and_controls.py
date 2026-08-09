"""lane D D3 turn event stream and controls

Revision ID: 98a5ddafa21b
Revises: fba208917f89
Create Date: 2026-08-08 00:00:00.000000+00:00

FI Lane D slice **D3** (`docs/specs/FI-lane-D-D3-implementation-brief.md`; charter §3-P4 and
§§3.1-3.6, ratified §6-D2 *complete token streaming*). Three things land here:

1. **``agent_turn_event_stream``** — the turn-scoped durable event outbox charter §3-P4 requires.
   It mirrors the proven ``run_event`` shape (a ``bigserial`` cursor, a workspace scope, a jsonb
   payload, at-least-once delivery deduplicated by the envelope id) but is keyed on a *turn*
   instead of a project run: ``run_event.run_id`` is ``NOT NULL``, so a conversation turn — which
   has no project run at all until it launches one — cannot be carried there.

   Two identifiers, because §3.2 asks for two different guarantees: ``event_id`` is the globally
   monotone ``Last-Event-ID`` cursor a reconnecting consumer replays from, and ``sequence`` is
   monotone *within one turn* so a consumer can order and gap-check a single turn's frames without
   knowing anything about the rest of the workspace. ``generation_attempt_id`` is what keeps a
   crash/retry from splicing two continuations into one part (§3.3(6)); ``delta_index`` is what
   makes a replayed token stream byte-identical in the same order (§3.3(4)).

   **Deliberately not append-only-by-trigger for DELETE.** Every other agent-plane table is
   immutable in both directions, and this one is immutable against ``UPDATE`` for the same reason
   (an emitted frame is a receipt of what a client was told). ``DELETE`` is left open for exactly
   one caller — the retention pruner — because this table is a *transport buffer*, not the durable
   record of the turn: the authority is the turn journal, the finalization commit, and the thread
   messages, all of which survive pruning untouched. §3.3(7)'s "the outbox is the buffer and the
   replay-retention policy is explicit" is what that buys.

2. **``agent_turn_control_request``** — the durable stop/retry requests of §3.5. A control is a
   human act, so it is a receipt: immutable, insert-once, carrying the Clue-owned internal identity
   of whoever asked. "Stopped" is *derived* from the presence of a stop row plus the turn's own
   terminal event, never stored as a mutable status — the same append-only doctrine ``agent_gate``
   follows in D4.

3. **``stream_token.turn_id``** — the B4 single-use SSE token store grows a second, mutually
   exclusive scope. A turn stream must be opened by a token minted *for that turn*; smuggling a
   turn id through the ``run_id`` column would have made every future reader of that table wrong
   about what it holds.

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
revision: str = "98a5ddafa21b"
down_revision: str | None = "fba208917f89"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: The closed §3.2 event vocabulary, as a SQL CHECK. ``stream.hello`` is generated at connect and
#: never stored; ``stream.reset`` is stored **only** for the one durable case §3.3(5) names — a
#: delta/message reconciliation mismatch, which instructs every attached and every future consumer
#: to re-fetch the canonical message rather than trust the projection.
_EVENT_TYPES = (
    "turn.accepted",
    "turn.started",
    "turn.awaiting_input",
    "turn.completed",
    "turn.failed",
    "turn.cancelled",
    "turn.retrying",
    "part.created",
    "part.updated",
    "part.completed",
    "part.failed",
    "part.reset",
    "text.start",
    "text.delta",
    "text.end",
    "stream.reset",
)

#: The §3.1 domain part vocabulary. ``text`` is carried by the ``text.*`` events rather than a part
#: snapshot, but it still owns a part id (deltas address it), so it is a member here too.
_PART_KINDS = (
    "text",
    "reasoning",
    "agent_activity",
    "tool",
    "task",
    "plan",
    "gate",
    "sources",
    "action",
)


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE agent_turn_event_stream (
            event_id              bigserial PRIMARY KEY,
            workspace_id          text        NOT NULL,
            project_id            text        NOT NULL,
            thread_id             text        NOT NULL,
            turn_id               uuid        NOT NULL,
            sequence              bigint      NOT NULL,
            generation_attempt_id uuid,
            event_type            text        NOT NULL,
            part_id               text,
            part_kind             text,
            message_id            uuid,
            run_id                uuid,
            delta_index           integer,
            payload               jsonb       NOT NULL DEFAULT '{{}}'::jsonb,
            occurred_at           timestamptz NOT NULL DEFAULT now(),

            -- Monotone within one turn (§3.2). UNIQUE rather than merely indexed: two concurrent
            -- emitters would be two live generations of one turn, which per-thread single-flight
            -- already forbids — so the honest outcome is a loud integrity error, not a silent
            -- duplicate frame.
            CONSTRAINT agent_turn_event_stream_turn_sequence UNIQUE (turn_id, sequence),
            CONSTRAINT agent_turn_event_stream_sequence_positive CHECK (sequence > 0),
            CONSTRAINT agent_turn_event_stream_type
                CHECK (event_type IN ({_quoted(_EVENT_TYPES)})),
            CONSTRAINT agent_turn_event_stream_part_kind
                CHECK (part_kind IS NULL OR part_kind IN ({_quoted(_PART_KINDS)})),
            -- A part event without a part is unrenderable; a delta without an index cannot be
            -- replayed in order; a delta outside an attempt cannot be isolated from a retry.
            CONSTRAINT agent_turn_event_stream_part_identity CHECK (
                event_type NOT LIKE 'part.%' OR (part_id IS NOT NULL AND part_kind IS NOT NULL)
            ),
            CONSTRAINT agent_turn_event_stream_text_identity CHECK (
                event_type NOT LIKE 'text.%'
                OR (part_id IS NOT NULL AND generation_attempt_id IS NOT NULL)
            ),
            CONSTRAINT agent_turn_event_stream_delta_index CHECK (
                (event_type = 'text.delta') = (delta_index IS NOT NULL)
            ),
            CONSTRAINT agent_turn_event_stream_delta_index_nonnegative
                CHECK (delta_index IS NULL OR delta_index >= 0),
            CONSTRAINT agent_turn_event_stream_payload_object
                CHECK (jsonb_typeof(payload) = 'object'),
            CONSTRAINT agent_turn_event_stream_scope_nonempty CHECK (
                length(btrim(workspace_id)) > 0
                AND length(btrim(project_id)) > 0
                AND length(btrim(thread_id)) > 0
            ),
            -- The thread anchor pins every frame to a thread *in its own workspace* (the composite
            -- FK pattern agent_thread / agent_turn / agent_turn_submission already use). There is
            -- deliberately no FK on turn_id: the first frames of a turn are emitted before the
            -- agent_turn row exists (that row needs an execution, which needs the model plane),
            -- and a transport buffer must never be the reason a turn cannot be announced.
            CONSTRAINT agent_turn_event_stream_thread_fk
                FOREIGN KEY (thread_id, workspace_id)
                REFERENCES agent_thread (id, workspace_id),
            CONSTRAINT agent_turn_event_stream_project_fk
                FOREIGN KEY (project_id, workspace_id)
                REFERENCES project (project_id, workspace_id)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE agent_turn_event_stream IS 'FI Lane D D3: the turn-scoped SSE outbox "
        "(charter §3-P4/§3.2). event_id is the Last-Event-ID cursor; sequence is monotone within "
        "one turn; generation_attempt_id isolates a retry from the attempt it replaced; "
        "delta_index orders replayed token deltas. A TRANSPORT BUFFER, not the durable record of "
        "the turn — the turn journal, the finalization commit and agent_thread_message are the "
        "authority, and DELETE here is reserved for the retention pruner.'"
    )
    # Replay: "this workspace's frames for this turn after this cursor, in cursor order".
    op.execute(
        "CREATE INDEX agent_turn_event_stream_turn_cursor "
        "ON agent_turn_event_stream (workspace_id, turn_id, event_id)"
    )
    # A thread-level attach (every turn of one conversation) and the retention sweep.
    op.execute(
        "CREATE INDEX agent_turn_event_stream_thread_cursor "
        "ON agent_turn_event_stream (workspace_id, thread_id, event_id)"
    )
    op.execute(
        "CREATE INDEX agent_turn_event_stream_occurred_at ON agent_turn_event_stream (occurred_at)"
    )
    # Immutable against UPDATE only — see the module docstring for why DELETE stays open.
    op.execute(
        "CREATE TRIGGER agent_turn_event_stream_no_update "
        "BEFORE UPDATE ON agent_turn_event_stream "
        "FOR EACH ROW EXECUTE FUNCTION execution_reject_append_only_mutation()"
    )

    op.execute(
        """
        CREATE TABLE agent_turn_control_request (
            control_id                 uuid PRIMARY KEY,
            workspace_id               text        NOT NULL,
            project_id                 text        NOT NULL,
            thread_id                  text        NOT NULL,
            turn_id                    uuid        NOT NULL,
            kind                       text        NOT NULL,
            target_attempt_id          uuid,
            retry_turn_id              uuid,
            requested_by_user_id       text        NOT NULL,
            requested_via_membership_id text       NOT NULL,
            requested_at               timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT agent_turn_control_request_kind CHECK (kind IN ('stop', 'retry')),
            -- A retry names the turn it created; a stop never does. Without this a 'retry' row
            -- could exist that points at nothing, which is a control nobody can audit.
            CONSTRAINT agent_turn_control_request_retry_target CHECK (
                (kind = 'retry') = (retry_turn_id IS NOT NULL)
            ),
            CONSTRAINT agent_turn_control_request_scope_nonempty CHECK (
                length(btrim(workspace_id)) > 0
                AND length(btrim(project_id)) > 0
                AND length(btrim(thread_id)) > 0
                AND length(btrim(requested_by_user_id)) > 0
                AND length(btrim(requested_via_membership_id)) > 0
            ),
            CONSTRAINT agent_turn_control_request_thread_fk
                FOREIGN KEY (thread_id, workspace_id)
                REFERENCES agent_thread (id, workspace_id),
            CONSTRAINT agent_turn_control_request_project_fk
                FOREIGN KEY (project_id, workspace_id)
                REFERENCES project (project_id, workspace_id),
            -- Clue-owned internal identity only (Lane B contract §§1.2-1.3): a control is an act of
            -- authority, so it names the authenticated human who performed it and the membership
            -- that authorized them, both as real foreign keys.
            CONSTRAINT agent_turn_control_request_user_fk
                FOREIGN KEY (requested_by_user_id) REFERENCES platform_user (user_id),
            CONSTRAINT agent_turn_control_request_membership_fk
                FOREIGN KEY (requested_via_membership_id, workspace_id)
                REFERENCES workspace_membership (membership_id, workspace_id)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE agent_turn_control_request IS 'FI Lane D D3: the durable stop/retry "
        "requests of charter §3.5. Immutable and insert-once (control_id is derived from the turn "
        "and the control kind, so a repeated stop is a replay, not a second cancellation). The "
        "worker observes a stop row and cancels only the active generation attempt; committed tool "
        "effects and detached research runs are untouched.'"
    )
    # The worker's stop poll: "is there a stop for this turn", scoped to its workspace.
    op.execute(
        "CREATE INDEX agent_turn_control_request_turn "
        "ON agent_turn_control_request (workspace_id, turn_id, kind)"
    )
    op.execute(
        "CREATE TRIGGER agent_turn_control_request_append_only "
        "BEFORE UPDATE OR DELETE ON agent_turn_control_request "
        "FOR EACH ROW EXECUTE FUNCTION execution_reject_append_only_mutation()"
    )

    # The single-use SSE token store grows a turn scope, mutually exclusive with the run scope.
    op.execute("ALTER TABLE stream_token ADD COLUMN turn_id uuid")
    op.execute(
        "ALTER TABLE stream_token ADD CONSTRAINT stream_token_single_scope "
        "CHECK (run_id IS NULL OR turn_id IS NULL)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE stream_token DROP CONSTRAINT IF EXISTS stream_token_single_scope")
    op.execute("ALTER TABLE stream_token DROP COLUMN IF EXISTS turn_id")

    op.execute(
        "DROP TRIGGER IF EXISTS agent_turn_control_request_append_only "
        "ON agent_turn_control_request"
    )
    op.execute("DROP INDEX IF EXISTS agent_turn_control_request_turn")
    op.execute("DROP TABLE IF EXISTS agent_turn_control_request")

    op.execute(
        "DROP TRIGGER IF EXISTS agent_turn_event_stream_no_update ON agent_turn_event_stream"
    )
    op.execute("DROP INDEX IF EXISTS agent_turn_event_stream_occurred_at")
    op.execute("DROP INDEX IF EXISTS agent_turn_event_stream_thread_cursor")
    op.execute("DROP INDEX IF EXISTS agent_turn_event_stream_turn_cursor")
    op.execute("DROP TABLE IF EXISTS agent_turn_event_stream")
