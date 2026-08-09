"""lane D D4 agent gate substrate

Revision ID: 3caa27516b81
Revises: fba208917f89
Create Date: 2026-08-08 16:41:02.913224+00:00

FI Lane D slice **D4** (`docs/specs/FI-lane-D-D4-implementation-brief.md`; charter §3-P5(a),
ratified **§6-D3**). The durable, **generic** gate substrate the Option-B kickoff flow hangs on,
built as the register ratified it: an **immutable gate row** written when the gate is presented,
plus an **insert-once answer record**. There is no ``status`` column anywhere — "open" is the
absence of an answer row and "answered" is its presence, which is the same append-only doctrine
the 13 C6 receipt tables and D2's ``agent_turn_submission`` follow. A mutable status column would
be a second, forgeable statement about what the human decided.

Two tables:

1. **``agent_gate``** — what was presented, to whom, over which subject, for how much. Every field
   is a fact at presentation time and none of them may drift afterwards:

   * the *anchors* (``workspace_id`` / ``project_id`` / ``thread_id`` / ``turn_id``) are composite
     foreign keys in the house pattern, so a gate structurally belongs to one thread of one project
     of one workspace, and its presenting turn provably belongs to that same thread;
   * ``kind`` is a closed CHECK vocabulary — ``directive_confirmation`` is the one D4 builds, and
     ``plan_approval`` / ``budget_approval`` are declared now because §3-P5(a) names them and a
     generic substrate that has to be migrated for its second kind was never generic;
   * ``subject_ref`` + ``subject_revision`` + ``expected_subject_sha256`` are what the human was
     actually shown. The digest is the anti-staleness device: an answer that names a different
     digest than the gate is refused rather than applied to a subject that has since been redrafted;
   * ``max_spend_cents`` + ``currency`` carry the **server-derived maximum spend** (ratified §6-D5 —
     no estimate tool in V1). It is computed at gate creation with the launcher's own Σ per-account
     ``effort_policy.budget_cap_cents`` and re-verified at launch through
     ``expected_estimated_cost_cents``. One number, one source, stored where the human can see it;
   * ``addressee_user_id`` is the Clue-owned internal ``platform_user.user_id`` (never a provider
     id — Lane B ruling 3) of the one person entitled to answer.

2. **``agent_gate_answer``** — that the addressee answered, once. ``gate_id`` is the primary key,
   so the "answer exactly once" rule is a database constraint rather than a code path: a second
   answer (a double-click, a replayed request with different bytes, a racing second session) hits
   the primary key and is refused. It records the *answering* turn and its ``turn-action:`` receipt,
   so the durable chain gate → confirming turn → ``research_directive.confirming_turn_ref`` →
   ``entity_research_run.approval_refs`` is a join, not a reconstruction.

   Its ``turn_id`` references ``agent_turn_submission``, not ``agent_turn``: the answering turn is
   recorded by the HTTP route *before* the fleet worker executes it (D2's two-phase turn identity),
   so at the moment the answer is written the ``agent_turn`` row does not exist yet — while the
   submission row does, and carries NOT NULL internal submitter identity. That FK is therefore the
   stronger statement: an answer can only cite a turn a real human demonstrably submitted.

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
revision: str = "3caa27516b81"
down_revision: str | None = "fba208917f89"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # D2 gave ``agent_turn_submission`` a bare ``turn_id`` primary key. The answer record below
    # wants to reference it *inside one workspace*, which needs the same ``(id, workspace_id)``
    # anchor every other agent-plane table publishes. Additive and free (the PK already implies
    # uniqueness of the pair).
    op.execute(
        "ALTER TABLE agent_turn_submission "
        "ADD CONSTRAINT agent_turn_submission_workspace_anchor UNIQUE (turn_id, workspace_id)"
    )

    op.execute(
        """
        CREATE TABLE agent_gate (
            gate_id                 uuid PRIMARY KEY,
            workspace_id            text NOT NULL,
            project_id              text NOT NULL,
            thread_id               text NOT NULL,
            turn_id                 uuid NOT NULL,
            kind                    text NOT NULL,
            subject_ref             text NOT NULL,
            subject_revision        integer,
            expected_subject_sha256 text NOT NULL,
            subject_snapshot        jsonb NOT NULL,
            max_spend_cents         numeric(20, 4) NOT NULL,
            currency                text NOT NULL,
            addressee_user_id       text NOT NULL,
            created_at              timestamptz NOT NULL DEFAULT now(),

            -- The presenting turn, proved to live in this gate's own thread and workspace: the
            -- three-column anchor agent_turn already publishes for exactly this purpose.
            CONSTRAINT agent_gate_turn_fk
                FOREIGN KEY (turn_id, workspace_id, thread_id)
                REFERENCES agent_turn (id, workspace_id, thread_id),
            CONSTRAINT agent_gate_project_fk
                FOREIGN KEY (project_id, workspace_id)
                REFERENCES project (project_id, workspace_id),
            -- Clue-owned internal identity only (FI-lane-B-authenticated-principal-contract.md
            -- ruling 3). A gate addressed to a provider identifier would be unanswerable by the
            -- platform's own authorization.
            CONSTRAINT agent_gate_addressee_fk
                FOREIGN KEY (addressee_user_id) REFERENCES platform_user (user_id),
            -- The answer record's workspace-scoped anchor.
            CONSTRAINT agent_gate_workspace_anchor UNIQUE (gate_id, workspace_id),
            -- Closed vocabulary: §3-P5(a)'s three kinds. Adding a fourth is a reviewed migration,
            -- which is the point — a gate kind decides which server path is allowed to answer it.
            CONSTRAINT agent_gate_kind CHECK (
                kind IN ('directive_confirmation', 'plan_approval', 'budget_approval')
            ),
            CONSTRAINT agent_gate_digest CHECK (
                expected_subject_sha256 ~ '^[0-9a-f]{64}$'
            ),
            -- Money is never negative and never a float; the currency is an ISO-4217 alpha code so
            -- an amount can never be rendered without knowing what it is denominated in.
            CONSTRAINT agent_gate_max_spend_nonnegative CHECK (max_spend_cents >= 0),
            CONSTRAINT agent_gate_currency CHECK (currency ~ '^[A-Z]{3}$'),
            CONSTRAINT agent_gate_identity_nonempty CHECK (
                length(btrim(workspace_id)) > 0
                AND length(btrim(project_id)) > 0
                AND length(btrim(thread_id)) > 0
                AND length(btrim(subject_ref)) > 0
                AND length(btrim(addressee_user_id)) > 0
            ),
            CONSTRAINT agent_gate_subject_revision_positive CHECK (
                subject_revision IS NULL OR subject_revision >= 1
            ),
            CONSTRAINT agent_gate_subject_snapshot_object CHECK (
                jsonb_typeof(subject_snapshot) = 'object'
            )
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE agent_gate IS 'FI Lane D D4 (charter §3-P5(a), ratified §6-D3): the "
        "immutable record that a gate was presented to one addressee over one exact subject "
        "revision for one server-derived maximum spend. Open vs answered is DERIVED from "
        "agent_gate_answer, never stored — there is deliberately no status column.'"
    )
    # The thread's gate strip, newest last: what a transcript cold-load and the D3 `gate` part
    # projection both read.
    op.execute(
        "CREATE INDEX agent_gate_thread_created "
        "ON agent_gate (workspace_id, thread_id, created_at, gate_id)"
    )
    # "Which gate did this turn present?" — the join the run/turn narration walks.
    op.execute("CREATE INDEX agent_gate_turn ON agent_gate (workspace_id, turn_id)")

    op.execute(
        """
        CREATE TABLE agent_gate_answer (
            gate_id             uuid PRIMARY KEY,
            workspace_id        text NOT NULL,
            turn_id             uuid NOT NULL,
            action_ref          text NOT NULL,
            decision            text NOT NULL,
            answered_by_user_id text NOT NULL,
            answered_at         timestamptz NOT NULL DEFAULT now(),

            -- Insert-once by construction: gate_id IS the primary key, so a gate is answerable
            -- exactly once and the second answer is a database error rather than a policy the
            -- application has to remember.
            CONSTRAINT agent_gate_answer_gate_fk
                FOREIGN KEY (gate_id, workspace_id)
                REFERENCES agent_gate (gate_id, workspace_id),
            -- The answering turn as the *route* recorded it (D2's two-phase turn identity): the
            -- submission exists before the worker builds the agent_turn row, and it carries NOT
            -- NULL internal submitter identity, so this FK proves a real human submitted the act.
            CONSTRAINT agent_gate_answer_turn_fk
                FOREIGN KEY (turn_id, workspace_id)
                REFERENCES agent_turn_submission (turn_id, workspace_id),
            CONSTRAINT agent_gate_answer_user_fk
                FOREIGN KEY (answered_by_user_id) REFERENCES platform_user (user_id),
            CONSTRAINT agent_gate_answer_decision CHECK (
                decision IN ('approved', 'rejected', 'revised')
            ),
            -- One act, one name: the receipt is always the canonical turn-action reference D1
            -- mints, so an answer can never cite an action the server cannot re-derive.
            CONSTRAINT agent_gate_answer_action_ref CHECK (
                action_ref = 'turn-action:' || turn_id::text
            ),
            CONSTRAINT agent_gate_answer_identity_nonempty CHECK (
                length(btrim(workspace_id)) > 0
                AND length(btrim(answered_by_user_id)) > 0
            )
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE agent_gate_answer IS 'FI Lane D D4: the insert-once record that a gate "
        "was answered — by which turn, under which turn-action receipt, with which decision, by "
        "whom. Its existence is what makes a gate answered; gate_id is the primary key so the "
        "once-only rule is a constraint, not a convention.'"
    )
    # "Which gate did this turn answer?" — the gate-answer resolver's exact lookup.
    op.execute(
        "CREATE INDEX agent_gate_answer_turn ON agent_gate_answer (workspace_id, turn_id)"
    )

    # Immutable by trigger, like the 13 agent-plane receipt tables (migration 7e9269ed8a81) and
    # D2's submission table. A presented gate and a recorded decision are receipts; nothing in the
    # platform may edit either after the fact.
    op.execute(
        "CREATE TRIGGER agent_gate_append_only "
        "BEFORE UPDATE OR DELETE ON agent_gate "
        "FOR EACH ROW EXECUTE FUNCTION execution_reject_append_only_mutation()"
    )
    op.execute(
        "CREATE TRIGGER agent_gate_answer_append_only "
        "BEFORE UPDATE OR DELETE ON agent_gate_answer "
        "FOR EACH ROW EXECUTE FUNCTION execution_reject_append_only_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS agent_gate_answer_append_only ON agent_gate_answer")
    op.execute("DROP TRIGGER IF EXISTS agent_gate_append_only ON agent_gate")
    op.execute("DROP INDEX IF EXISTS agent_gate_answer_turn")
    op.execute("DROP TABLE IF EXISTS agent_gate_answer")
    op.execute("DROP INDEX IF EXISTS agent_gate_turn")
    op.execute("DROP INDEX IF EXISTS agent_gate_thread_created")
    op.execute("DROP TABLE IF EXISTS agent_gate")
    op.execute(
        "ALTER TABLE agent_turn_submission "
        "DROP CONSTRAINT IF EXISTS agent_turn_submission_workspace_anchor"
    )
