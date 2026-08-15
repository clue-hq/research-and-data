"""enforce unified agent gate contract

Revision ID: f85ca69b93ba
Revises: fea2a60cffc0
Create Date: 2026-08-15 18:59:19.341227+00:00

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
revision: str = "f85ca69b93ba"
down_revision: str | None = "fea2a60cffc0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Install the union of the ICP-confirmation and product-selection contracts."""

    # S5's product branch was cut after the ICP lifecycle migration but replaced this constraint
    # with its own vocabulary.  At the merge point the last-applied branch therefore wins.  The
    # child revision makes the union explicit and retains the generic plan/budget kinds declared
    # by the original substrate.
    op.execute("ALTER TABLE agent_gate DROP CONSTRAINT agent_gate_kind")
    op.execute(
        "ALTER TABLE agent_gate ADD CONSTRAINT agent_gate_kind CHECK (kind IN ("
        "'directive_confirmation', 'icp_confirmation', 'product_selection', "
        "'plan_approval', 'budget_approval'))"
    )

    # Keep the cheap same-row rules in a CHECK.  Kind-specific requirements and membership in the
    # immutable product snapshot need the gate row and therefore live in the authority trigger.
    op.execute("ALTER TABLE agent_gate_answer DROP CONSTRAINT agent_gate_answer_selection_valid")
    op.execute(
        "ALTER TABLE agent_gate_answer "
        "ADD CONSTRAINT agent_gate_answer_selection_valid CHECK ("
        "selected_option_ref IS NULL OR (decision = 'approved' "
        "AND length(btrim(selected_option_ref)) > 0 "
        "AND decision_payload = '{}'::jsonb))"
    )

    # This replaces the ICP-only validator from 70e67fc26a3f.  One storage-boundary function now
    # proves the shared authority envelope and then dispatches the two auxiliary answer shapes:
    # bounded ICP revision text versus an exact product candidate.  The separate snapshot-erasure
    # trigger from df332fd7904c remains as defense in depth.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION agent_gate_answer_validate() RETURNS trigger AS $$
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
            IF presented.snapshot_erased_at IS NOT NULL THEN
                RAISE EXCEPTION 'an erased gate snapshot cannot be answered';
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
            IF NEW.selected_option_ref IS NOT NULL
               AND NEW.decision_payload <> '{}'::jsonb THEN
                RAISE EXCEPTION 'an answer cannot carry both a revision payload and a selection';
            END IF;

            IF presented.kind = 'icp_confirmation' THEN
                IF NEW.selected_option_ref IS NOT NULL THEN
                    RAISE EXCEPTION 'an ICP answer cannot carry a selected option';
                END IF;
                IF NEW.decision = 'revised' THEN
                    IF (SELECT count(*) FROM jsonb_object_keys(NEW.decision_payload)) <> 1
                       OR jsonb_typeof(NEW.decision_payload -> 'revision_request') <> 'string'
                       OR length(btrim(
                            NEW.decision_payload ->> 'revision_request'
                       )) NOT BETWEEN 1 AND 4000
                       OR NEW.decision_payload ->> 'revision_request'
                          <> btrim(NEW.decision_payload ->> 'revision_request') THEN
                        RAISE EXCEPTION
                            'an ICP revision requires one trimmed revision_request '
                            'of 1-4000 characters';
                    END IF;
                ELSIF NEW.decision_payload <> '{}'::jsonb THEN
                    RAISE EXCEPTION 'ICP approve/reject answers carry no decision payload';
                END IF;
            ELSIF presented.kind = 'product_selection' THEN
                IF NEW.decision_payload <> '{}'::jsonb THEN
                    RAISE EXCEPTION 'product-selection answers carry no decision payload';
                END IF;
                IF NEW.decision = 'approved' THEN
                    IF NEW.selected_option_ref IS NULL
                       OR length(btrim(NEW.selected_option_ref)) = 0 THEN
                        RAISE EXCEPTION 'product approval requires one selected option';
                    END IF;
                    IF jsonb_typeof(presented.subject_snapshot -> 'products')
                       IS DISTINCT FROM 'array' THEN
                        RAISE EXCEPTION 'product-selection gate has no valid candidate array';
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements(
                            presented.subject_snapshot -> 'products'
                        ) candidate
                        WHERE jsonb_typeof(candidate) = 'object'
                          AND candidate ->> 'product_id' = NEW.selected_option_ref
                    ) THEN
                        RAISE EXCEPTION
                            'selected option is not a candidate in the presented gate';
                    END IF;
                ELSIF NEW.selected_option_ref IS NOT NULL THEN
                    RAISE EXCEPTION 'product rejection/revision cannot carry a selected option';
                END IF;
            ELSIF NEW.decision_payload <> '{}'::jsonb
                  OR NEW.selected_option_ref IS NOT NULL THEN
                RAISE EXCEPTION 'this gate kind does not accept auxiliary answer input';
            END IF;

            -- A caller-supplied user id is not authority.  The cited answering turn must be a
            -- durable submission by this addressee in the exact project/thread of the gate.
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


def downgrade() -> None:
    """Restore the product-lineage parent shape at the explicit merge point."""

    # The parent graph's effective gate-kind constraint is S5's product vocabulary.  Refuse an
    # impossible reversal rather than pretending an already-presented ICP receipt can fit it.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM agent_gate WHERE kind = 'icp_confirmation') THEN
                RAISE EXCEPTION
                    'cannot downgrade unified agent gates while ICP confirmation gates exist';
            END IF;
        END;
        $$
        """
    )

    # Restore the exact ICP-era validator that remains installed at the merge parent.  It does not
    # interpret S5's selected option; the parent CHECK is restored immediately afterwards.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION agent_gate_answer_validate() RETURNS trigger AS $$
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
                        RAISE EXCEPTION
                            'an ICP revision requires one non-blank revision_request';
                    END IF;
                ELSIF NEW.decision_payload <> '{}'::jsonb THEN
                    RAISE EXCEPTION 'ICP approve/reject answers carry no decision payload';
                END IF;
            END IF;

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

    op.execute("ALTER TABLE agent_gate_answer DROP CONSTRAINT agent_gate_answer_selection_valid")
    op.execute(
        "ALTER TABLE agent_gate_answer "
        "ADD CONSTRAINT agent_gate_answer_selection_valid CHECK ("
        "selected_option_ref IS NULL OR (decision = 'approved' "
        "AND length(btrim(selected_option_ref)) > 0))"
    )
    op.execute("ALTER TABLE agent_gate DROP CONSTRAINT agent_gate_kind")
    op.execute(
        "ALTER TABLE agent_gate ADD CONSTRAINT agent_gate_kind CHECK (kind IN ("
        "'directive_confirmation', 'product_selection', 'plan_approval', 'budget_approval'))"
    )
