"""stage0 icp confirmation gate lifecycle

Revision ID: 70e67fc26a3f
Revises: 2fb8e2479183
Create Date: 2026-08-11 19:57:20.570172+00:00

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
revision: str = "70e67fc26a3f"
down_revision: str | None = "2fb8e2479183"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Make the generic gate substrate honest for non-spend ICP confirmation."""

    # Existing Lane-D gates all expose the full decision vocabulary. Persist that vocabulary on
    # every row before making it mandatory, so answerability is data rather than a renderer guess.
    op.execute(
        "ALTER TABLE agent_gate ADD COLUMN permitted_decisions text[] "
        "NOT NULL DEFAULT ARRAY['approved','rejected','revised']::text[]"
    )
    op.execute("ALTER TABLE agent_gate ALTER COLUMN permitted_decisions DROP DEFAULT")
    op.execute(
        "ALTER TABLE agent_gate ADD CONSTRAINT agent_gate_permitted_decisions CHECK ("
        "cardinality(permitted_decisions) > 0 "
        "AND permitted_decisions <@ ARRAY['approved','rejected','revised']::text[])"
    )

    # An ICP confirmation carries no spend. Nullability is paired, so the generic row cannot hold
    # an amount without a currency or a currency without an amount.
    op.execute("ALTER TABLE agent_gate ALTER COLUMN max_spend_cents DROP NOT NULL")
    op.execute("ALTER TABLE agent_gate ALTER COLUMN currency DROP NOT NULL")
    op.execute(
        "ALTER TABLE agent_gate ADD CONSTRAINT agent_gate_amount_pair CHECK ("
        "(max_spend_cents IS NULL) = (currency IS NULL))"
    )

    op.execute("ALTER TABLE agent_gate DROP CONSTRAINT agent_gate_kind")
    op.execute(
        "ALTER TABLE agent_gate ADD CONSTRAINT agent_gate_kind CHECK (kind IN ("
        "'directive_confirmation','icp_confirmation','plan_approval','budget_approval'))"
    )
    op.execute(
        "ALTER TABLE agent_gate ADD CONSTRAINT agent_gate_icp_decisions CHECK ("
        "kind <> 'icp_confirmation' OR permitted_decisions = "
        "ARRAY['approved','rejected','revised']::text[])"
    )
    op.execute(
        "CREATE UNIQUE INDEX agent_gate_one_icp_subject "
        "ON agent_gate (workspace_id, project_id, subject_ref, expected_subject_sha256) "
        "WHERE kind = 'icp_confirmation'"
    )

    # The answer receipt records the digest echoed by the client and a bounded typed payload. Drop
    # the append-only trigger only for the migration backfill, then restore it before traffic can
    # observe the new shape.
    op.execute("DROP TRIGGER agent_gate_answer_append_only ON agent_gate_answer")
    op.execute("ALTER TABLE agent_gate_answer ADD COLUMN expected_subject_sha256 text")
    op.execute(
        "ALTER TABLE agent_gate_answer ADD COLUMN decision_payload jsonb "
        "NOT NULL DEFAULT '{}'::jsonb"
    )
    op.execute(
        "UPDATE agent_gate_answer a SET expected_subject_sha256 = g.expected_subject_sha256 "
        "FROM agent_gate g WHERE g.gate_id = a.gate_id AND g.workspace_id = a.workspace_id"
    )
    op.execute("ALTER TABLE agent_gate_answer ALTER COLUMN expected_subject_sha256 SET NOT NULL")
    op.execute("ALTER TABLE agent_gate_answer ALTER COLUMN decision_payload DROP DEFAULT")
    op.execute(
        "ALTER TABLE agent_gate_answer ADD CONSTRAINT agent_gate_answer_digest CHECK ("
        "expected_subject_sha256 ~ '^[0-9a-f]{64}$')"
    )
    op.execute(
        "ALTER TABLE agent_gate_answer ADD CONSTRAINT agent_gate_answer_payload_object CHECK ("
        "jsonb_typeof(decision_payload) = 'object')"
    )

    # Database-enforced authority: even a future caller that bypasses the route cannot answer with
    # a decision the gate did not offer, a stale digest, or the wrong human. ICP revision receipts
    # carry exactly one non-blank request; approve/reject carry no hidden payload.
    op.execute(
        """
        CREATE FUNCTION agent_gate_answer_validate() RETURNS trigger AS $$
        DECLARE
            presented agent_gate%ROWTYPE;
            answering_turn agent_turn_submission%ROWTYPE;
        BEGIN
            SELECT * INTO presented
            FROM agent_gate
            WHERE gate_id = NEW.gate_id AND workspace_id = NEW.workspace_id;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'agent gate does not exist in this workspace';
            END IF;
            IF NOT (NEW.decision = ANY(presented.permitted_decisions)) THEN
                RAISE EXCEPTION 'decision is not permitted by this gate';
            END IF;
            IF NEW.expected_subject_sha256 <> presented.expected_subject_sha256 THEN
                RAISE EXCEPTION 'answer digest does not match the presented gate';
            END IF;
            IF NEW.answered_by_user_id <> presented.addressee_user_id THEN
                RAISE EXCEPTION 'only the gate addressee may answer';
            END IF;
            IF presented.kind = 'icp_confirmation' THEN
                IF NEW.decision = 'revised' THEN
                    IF (SELECT count(*) FROM jsonb_object_keys(NEW.decision_payload)) <> 1
                       OR jsonb_typeof(NEW.decision_payload -> 'revision_request') <> 'string'
                       OR length(btrim(NEW.decision_payload ->> 'revision_request')) = 0 THEN
                        RAISE EXCEPTION 'an ICP revision requires one non-blank revision_request';
                    END IF;
                ELSIF NEW.decision_payload <> '{}'::jsonb THEN
                    RAISE EXCEPTION 'ICP approve/reject answers carry no decision payload';
                END IF;
            END IF;

            -- The answer is a turn receipt, not merely a caller-supplied user id. Prove at the
            -- storage boundary that the named turn is in this gate's exact project/thread and
            -- that its durable submitter is the addressee recorded above. The existing FK proves
            -- only workspace membership, which is insufficient for cross-thread authority.
            SELECT * INTO answering_turn
            FROM agent_turn_submission
            WHERE turn_id = NEW.turn_id AND workspace_id = NEW.workspace_id;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'answering turn does not exist in this workspace';
            END IF;
            IF answering_turn.project_id <> presented.project_id
               OR answering_turn.thread_id <> presented.thread_id THEN
                RAISE EXCEPTION 'answering turn does not belong to this gate thread';
            END IF;
            IF answering_turn.submitted_by_user_id <> NEW.answered_by_user_id THEN
                RAISE EXCEPTION 'answering turn was not submitted by the gate addressee';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER agent_gate_answer_authority "
        "BEFORE INSERT ON agent_gate_answer "
        "FOR EACH ROW EXECUTE FUNCTION agent_gate_answer_validate()"
    )
    op.execute(
        "CREATE TRIGGER agent_gate_answer_append_only "
        "BEFORE UPDATE OR DELETE ON agent_gate_answer "
        "FOR EACH ROW EXECUTE FUNCTION execution_reject_append_only_mutation()"
    )


def downgrade() -> None:
    """Restore the pre-ICP Lane-D gate shape."""

    op.execute("DROP TRIGGER IF EXISTS agent_gate_answer_authority ON agent_gate_answer")
    op.execute("DROP FUNCTION IF EXISTS agent_gate_answer_validate()")
    op.execute(
        "ALTER TABLE agent_gate_answer DROP CONSTRAINT IF EXISTS agent_gate_answer_payload_object"
    )
    op.execute("ALTER TABLE agent_gate_answer DROP CONSTRAINT IF EXISTS agent_gate_answer_digest")
    op.execute("ALTER TABLE agent_gate_answer DROP COLUMN decision_payload")
    op.execute("ALTER TABLE agent_gate_answer DROP COLUMN expected_subject_sha256")

    op.execute("ALTER TABLE agent_gate DROP CONSTRAINT IF EXISTS agent_gate_icp_decisions")
    op.execute("DROP INDEX IF EXISTS agent_gate_one_icp_subject")
    op.execute("ALTER TABLE agent_gate DROP CONSTRAINT agent_gate_kind")
    op.execute(
        "ALTER TABLE agent_gate ADD CONSTRAINT agent_gate_kind CHECK ("
        "kind IN ('directive_confirmation','plan_approval','budget_approval'))"
    )
    op.execute("ALTER TABLE agent_gate DROP CONSTRAINT agent_gate_amount_pair")
    op.execute("ALTER TABLE agent_gate ALTER COLUMN currency SET NOT NULL")
    op.execute("ALTER TABLE agent_gate ALTER COLUMN max_spend_cents SET NOT NULL")
    op.execute("ALTER TABLE agent_gate DROP CONSTRAINT agent_gate_permitted_decisions")
    op.execute("ALTER TABLE agent_gate DROP COLUMN permitted_decisions")
