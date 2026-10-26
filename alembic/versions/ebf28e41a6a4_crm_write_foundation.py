"""crm write foundation: proposals, the write log, grants, record links, the permission gate.

Spec: docs/superpowers/specs/crm-integration/ (Phase 2 — write foundation; rulings R-6.x). The
agent proposes CRM changes as a ``crm_write_proposal`` holding ordered ``crm_write`` rows (the
write log: what, why, before/after, and what the CRM said). A change runs only when it is covered:
by a standing ``crm_write_grant`` or by a person's answer to a ``crm_write_permission`` gate. A
``crm_record_link`` remembers which CRM record a Clue entity is, and whether Clue created it. When
a proposal's writes finish, the chat that proposed them resumes with a ``crm_writes_finished``
derived turn.

``crm_write.failure_kind`` includes ``not_applied``: a CRM can report success while the value did
not land, which the executor finds by reading the record back (Task 1 spike ruling).

Revision ID: ebf28e41a6a4
Revises: c87ba03cfc4e
Create Date: 2026-10-21 22:22:23.958902+00:00

Downgrade deletes the rows of the new gate kind and derivation first (with their answers and
child rows; those tables are append-only, so their delete guards are lifted for the delete only),
then restores the previous CHECKs and answer validator and drops the four tables.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ebf28e41a6a4"
down_revision: str | None = "c87ba03cfc4e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DERIVATIONS_BEFORE = (
    "'design_leg_redelivery', 'design_leg_first_turn', 'discovery_finished', 'crm_connected'"
)
_DERIVATIONS_AFTER = _DERIVATIONS_BEFORE + ", 'crm_writes_finished'"

_GATE_KINDS_BEFORE = (
    "'directive_confirmation', 'icp_confirmation', 'product_selection', "
    "'product_set_selection', 'plan_approval', 'budget_approval'"
)
_GATE_KINDS_AFTER = _GATE_KINDS_BEFORE + ", 'crm_write_permission'"

_UUID_PATTERN = "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


def upgrade() -> None:
    _create_tables()
    op.execute(_gate_kind_check(_GATE_KINDS_AFTER))
    op.execute(_answer_validator(crm_write=True))
    op.execute(_derivation_check(_DERIVATIONS_AFTER))


def downgrade() -> None:
    _delete_crm_writes_finished_turns()
    _delete_crm_write_permission_gates()
    op.execute(_derivation_check(_DERIVATIONS_BEFORE))
    op.execute(_answer_validator(crm_write=False))
    op.execute(_gate_kind_check(_GATE_KINDS_BEFORE))
    op.execute("DROP TABLE crm_record_link")
    op.execute("DROP TABLE crm_write_grant")
    op.execute("DROP TABLE crm_write")
    op.execute("DROP TABLE crm_write_proposal")


# --- the four tables ------------------------------------------------------------------------


def _create_tables() -> None:
    op.execute(
        """
        CREATE TABLE crm_write_proposal (
            proposal_id uuid NOT NULL,
            workspace_id text NOT NULL,
            connection_id uuid NOT NULL,
            project_id text NOT NULL,
            thread_id text NOT NULL,
            turn_id uuid NOT NULL,
            gate_id uuid NULL,
            status text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            answered_by_user_id text NULL,
            answered_at timestamptz NULL,
            finished_at timestamptz NULL,
            CONSTRAINT crm_write_proposal_pkey PRIMARY KEY (proposal_id),
            CONSTRAINT crm_write_proposal_workspace_fk
                FOREIGN KEY (workspace_id) REFERENCES workspace (workspace_id),
            CONSTRAINT crm_write_proposal_connection_fk
                FOREIGN KEY (connection_id)
                REFERENCES workspace_integration_connection (connection_id),
            CONSTRAINT crm_write_proposal_status CHECK (status IN (
                'prepared', 'awaiting_permission', 'queued', 'sending', 'paused', 'finished',
                'declined', 'replaced'
            ))
        )
        """
    )
    op.execute("CREATE INDEX crm_write_proposal_thread ON crm_write_proposal (thread_id)")
    op.execute(
        "CREATE INDEX crm_write_proposal_gate ON crm_write_proposal (gate_id) "
        "WHERE gate_id IS NOT NULL"
    )
    op.execute(
        """
        CREATE TABLE crm_write (
            write_id uuid NOT NULL,
            proposal_id uuid NOT NULL,
            workspace_id text NOT NULL,
            connection_id uuid NOT NULL,
            ordinal integer NOT NULL,
            slug text NOT NULL,
            arguments jsonb NOT NULL,
            kind text NOT NULL,
            object text NOT NULL,
            record_ref text NULL,
            record_label text NOT NULL,
            field text NULL,
            before_value jsonb NULL,
            after_value jsonb NULL,
            overwrites_person boolean NOT NULL,
            reason text NOT NULL,
            source_ref text NULL,
            reverses_write_id uuid NULL,
            scope_key text NOT NULL,
            covered_by text NULL,
            selected boolean NOT NULL,
            status text NOT NULL,
            failure_kind text NULL,
            crm_message text NULL,
            retryable boolean NULL,
            crm_id text NULL,
            idempotency_key text NOT NULL,
            attempts integer NOT NULL DEFAULT 0,
            sent_at timestamptz NULL,
            finished_at timestamptz NULL,
            CONSTRAINT crm_write_pkey PRIMARY KEY (write_id),
            CONSTRAINT crm_write_proposal_fk
                FOREIGN KEY (proposal_id) REFERENCES crm_write_proposal (proposal_id),
            CONSTRAINT crm_write_workspace_fk
                FOREIGN KEY (workspace_id) REFERENCES workspace (workspace_id),
            CONSTRAINT crm_write_connection_fk
                FOREIGN KEY (connection_id)
                REFERENCES workspace_integration_connection (connection_id),
            CONSTRAINT crm_write_reverses_fk
                FOREIGN KEY (reverses_write_id) REFERENCES crm_write (write_id),
            CONSTRAINT crm_write_status CHECK (status IN (
                'proposed', 'queued', 'sending', 'succeeded', 'failed', 'skipped'
            )),
            CONSTRAINT crm_write_failure_kind CHECK (failure_kind IS NULL OR failure_kind IN (
                'validation_rule', 'required_field', 'duplicate_rule', 'permission', 'not_found',
                'rate_limited', 'connection_expired', 'conflict', 'not_applied', 'other'
            )),
            CONSTRAINT crm_write_covered_by
                CHECK (covered_by IS NULL OR covered_by ~ '^(grant|gate):.+$'),
            CONSTRAINT crm_write_attempts_nonnegative CHECK (attempts >= 0),
            CONSTRAINT crm_write_idempotency_key_unique UNIQUE (idempotency_key),
            CONSTRAINT crm_write_proposal_ordinal UNIQUE (proposal_id, ordinal)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE crm_write_grant (
            grant_id uuid NOT NULL,
            workspace_id text NOT NULL,
            connection_id uuid NOT NULL,
            scope_kind text NOT NULL,
            kind text NULL,
            object text NULL,
            field text NULL,
            granted_by_user_id text NOT NULL,
            granted_at timestamptz NOT NULL DEFAULT now(),
            revoked_by_user_id text NULL,
            revoked_at timestamptz NULL,
            CONSTRAINT crm_write_grant_pkey PRIMARY KEY (grant_id),
            CONSTRAINT crm_write_grant_workspace_fk
                FOREIGN KEY (workspace_id) REFERENCES workspace (workspace_id),
            CONSTRAINT crm_write_grant_connection_fk
                FOREIGN KEY (connection_id)
                REFERENCES workspace_integration_connection (connection_id),
            CONSTRAINT crm_write_grant_scope_kind
                CHECK (scope_kind IN ('field', 'kind', 'fully_automatic')),
            CONSTRAINT crm_write_grant_revocation_pair
                CHECK ((revoked_at IS NULL) = (revoked_by_user_id IS NULL))
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX crm_write_grant_one_live "
        "ON crm_write_grant (connection_id, scope_kind, kind, object, field) NULLS NOT DISTINCT "
        "WHERE revoked_at IS NULL"
    )
    op.execute(
        """
        CREATE TABLE crm_record_link (
            workspace_id text NOT NULL,
            connection_id uuid NOT NULL,
            crm_object text NOT NULL,
            crm_id text NOT NULL,
            clue_entity_id uuid NULL,
            created_by_clue boolean NOT NULL,
            created_by_write_id uuid NULL,
            linked_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT crm_record_link_pkey PRIMARY KEY (connection_id, crm_object, crm_id),
            CONSTRAINT crm_record_link_workspace_fk
                FOREIGN KEY (workspace_id) REFERENCES workspace (workspace_id),
            CONSTRAINT crm_record_link_connection_fk
                FOREIGN KEY (connection_id)
                REFERENCES workspace_integration_connection (connection_id),
            CONSTRAINT crm_record_link_write_fk
                FOREIGN KEY (created_by_write_id) REFERENCES crm_write (write_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX crm_record_link_entity ON crm_record_link (clue_entity_id) "
        "WHERE clue_entity_id IS NOT NULL"
    )


# --- CHECKs and the downgrade's deletes ----------------------------------------------------


def _derivation_check(values: str) -> str:
    return f"""
        ALTER TABLE agent_turn_submission
            DROP CONSTRAINT agent_turn_submission_derivation_kind,
            ADD CONSTRAINT agent_turn_submission_derivation_kind
                CHECK (derivation IS NULL OR derivation IN ({values}))
        """


def _gate_kind_check(values: str) -> str:
    return f"""
        ALTER TABLE agent_gate
            DROP CONSTRAINT agent_gate_kind,
            ADD CONSTRAINT agent_gate_kind CHECK (kind IN ({values}))
        """


def _delete_guarded(table: str, guard: str, where: str) -> None:
    """Delete rows from an append-only table, lifting its delete guard for this statement only."""
    op.execute(f"ALTER TABLE {table} DISABLE TRIGGER {guard}")
    op.execute(f"DELETE FROM {table} WHERE {where}")
    op.execute(f"ALTER TABLE {table} ENABLE TRIGGER {guard}")


def _delete_crm_writes_finished_turns() -> None:
    turns = "SELECT turn_id FROM agent_turn_submission WHERE derivation = 'crm_writes_finished'"
    for table, guard in (
        ("agent_turn_submission_context_ref", "agent_turn_submission_context_ref_append_only"),
        ("agent_turn_scope_pin", "agent_turn_scope_pin_append_only"),
        ("agent_turn_knowledge_pin", "agent_turn_knowledge_pin_append_only"),
        ("agent_turn_project_files", "agent_turn_project_files_append_only"),
        ("agent_gate_answer", "agent_gate_answer_append_only"),
    ):
        _delete_guarded(table, guard, f"turn_id IN ({turns})")
    op.execute(f"DELETE FROM agent_turn_submission_attachment WHERE turn_id IN ({turns})")
    _delete_guarded(
        "agent_turn_submission",
        "agent_turn_submission_append_only",
        "derivation = 'crm_writes_finished'",
    )


def _delete_crm_write_permission_gates() -> None:
    gates = "SELECT gate_id FROM agent_gate WHERE kind = 'crm_write_permission'"
    _delete_guarded("agent_gate_answer", "agent_gate_answer_append_only", f"gate_id IN ({gates})")
    _delete_guarded("agent_gate_subject", "agent_gate_subject_append_only", f"gate_id IN ({gates})")
    _delete_guarded("agent_gate", "agent_gate_append_only", "kind = 'crm_write_permission'")


# --- the answer validator -------------------------------------------------------------------

#: A CRM write permission answer names its choices in ``decision_payload``: an approval carries
#: exactly ``selected_write_ids`` (write ids, as uuid strings) and ``always_allow`` (scope keys a
#: person chose to allow from now on), both arrays and nothing else; a rejection carries nothing.
_CRM_WRITE_PERMISSION_BRANCH = f"""
            ELSIF presented.kind = 'crm_write_permission' THEN
                IF NEW.selected_option_ref IS NOT NULL THEN
                    RAISE EXCEPTION
                        'a CRM write permission answer carries its choices in decision_payload, '
                        'not selected_option_ref';
                END IF;
                IF NEW.decision = 'approved' THEN
                    IF (SELECT count(*) FROM jsonb_object_keys(NEW.decision_payload)) <> 2
                       OR jsonb_typeof(NEW.decision_payload -> 'selected_write_ids')
                          IS DISTINCT FROM 'array'
                       OR jsonb_typeof(NEW.decision_payload -> 'always_allow')
                          IS DISTINCT FROM 'array' THEN
                        RAISE EXCEPTION
                            'CRM write permission approval requires the selected_write_ids and '
                            'always_allow arrays and nothing else';
                    END IF;
                    IF EXISTS (
                        SELECT 1 FROM jsonb_array_elements(
                            NEW.decision_payload -> 'selected_write_ids') chosen
                        WHERE jsonb_typeof(chosen) IS DISTINCT FROM 'string'
                           OR NOT (chosen #>> '{{}}') ~ '{_UUID_PATTERN}'
                    ) THEN
                        RAISE EXCEPTION
                            'CRM write permission selected_write_ids must be write ids';
                    END IF;
                    IF EXISTS (
                        SELECT 1 FROM jsonb_array_elements(
                            NEW.decision_payload -> 'always_allow') scope
                        WHERE jsonb_typeof(scope) IS DISTINCT FROM 'string'
                           OR length(btrim(scope #>> '{{}}')) = 0
                    ) THEN
                        RAISE EXCEPTION
                            'CRM write permission always_allow must be non-empty scope keys';
                    END IF;
                ELSIF NEW.decision_payload <> '{{}}'::jsonb THEN
                    RAISE EXCEPTION 'CRM write permission rejection carries no decision payload';
                END IF;
    """


def _answer_validator(*, crm_write: bool) -> str:
    """The whole ``agent_gate_answer_validate()`` body, exactly as 0aa95f87eb49 installs it (with
    its product-set branch), plus the ``crm_write_permission`` branch when ``crm_write`` is true.
    ``tests/db/test_crm_write_foundation_migration.py`` proves the ``False`` form is text-identical
    to the previous migration's, so ``downgrade()`` reinstalls the real thing."""
    crm_branch = _CRM_WRITE_PERMISSION_BRANCH if crm_write else ""
    product_set_branch = """
            ELSIF presented.kind = 'product_set_selection' THEN
                IF NEW.selected_option_ref IS NOT NULL THEN
                    RAISE EXCEPTION
                        'a product-set answer carries its choices in decision_payload, '
                        'not selected_option_ref';
                END IF;
                IF NEW.decision = 'approved' THEN
                    IF (SELECT count(*) FROM jsonb_object_keys(NEW.decision_payload)) <> 1
                       OR jsonb_typeof(NEW.decision_payload -> 'selected_option_refs')
                          IS DISTINCT FROM 'array'
                       OR jsonb_array_length(
                            NEW.decision_payload -> 'selected_option_refs') < 1 THEN
                        RAISE EXCEPTION
                            'product-set approval requires selected_option_refs with at least '
                            'one entry and nothing else';
                    END IF;
                    IF jsonb_typeof(presented.subject_snapshot -> 'products')
                       IS DISTINCT FROM 'array' THEN
                        RAISE EXCEPTION 'product-set gate has no valid candidate array';
                    END IF;
                    IF (SELECT count(*) FROM jsonb_array_elements_text(
                            NEW.decision_payload -> 'selected_option_refs'))
                       <> (SELECT count(DISTINCT value) FROM jsonb_array_elements_text(
                            NEW.decision_payload -> 'selected_option_refs')) THEN
                        RAISE EXCEPTION 'product-set approval cannot repeat a product';
                    END IF;
                    IF EXISTS (
                        SELECT 1 FROM jsonb_array_elements_text(
                            NEW.decision_payload -> 'selected_option_refs') chosen
                        WHERE NOT EXISTS (
                            SELECT 1 FROM jsonb_array_elements(
                                presented.subject_snapshot -> 'products') candidate
                            WHERE jsonb_typeof(candidate) = 'object'
                              AND candidate ->> 'product_id' = chosen.value
                        )
                    ) THEN
                        RAISE EXCEPTION
                            'a selected product is not a candidate in the presented gate';
                    END IF;
                ELSIF NEW.decision_payload <> '{}'::jsonb THEN
                    RAISE EXCEPTION 'product-set rejection/revision carries no decision payload';
                END IF;
    """
    discovery_branch = """
            ELSIF presented.kind = 'directive_confirmation'
                  AND presented.subject_snapshot ->> 'subject_kind'
                      = 'discovery_configuration' THEN
                IF NEW.selected_option_ref IS NOT NULL THEN
                    RAISE EXCEPTION 'a discovery configuration cannot carry a selected option';
                END IF;
                IF NEW.decision = 'revised' THEN
                    IF (SELECT count(*) FROM jsonb_object_keys(NEW.decision_payload)) <> 1
                       OR jsonb_typeof(NEW.decision_payload -> 'revision_request') <> 'string'
                       OR length(btrim(NEW.decision_payload ->> 'revision_request'))
                          NOT BETWEEN 1 AND 4000
                       OR NEW.decision_payload ->> 'revision_request'
                          <> btrim(NEW.decision_payload ->> 'revision_request') THEN
                        RAISE EXCEPTION
                            'a discovery revision requires one trimmed revision_request '
                            'of 1-4000 characters';
                    END IF;
                ELSIF NEW.decision_payload <> '{}'::jsonb THEN
                    RAISE EXCEPTION
                        'discovery approve/reject answers carry no decision payload';
                END IF;
    """
    return f"""
        CREATE OR REPLACE FUNCTION agent_gate_answer_validate() RETURNS trigger AS $$
        DECLARE
            presented agent_gate%ROWTYPE;
            answering_turn agent_turn_submission%ROWTYPE;
        BEGIN
            SELECT * INTO presented FROM agent_gate
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
               AND NEW.decision_payload <> '{{}}'::jsonb THEN
                RAISE EXCEPTION 'an answer cannot carry both a revision payload and a selection';
            END IF;

            IF presented.kind = 'icp_confirmation' THEN
                IF NEW.selected_option_ref IS NOT NULL THEN
                    RAISE EXCEPTION 'an ICP answer cannot carry a selected option';
                END IF;
                IF NEW.decision = 'revised' THEN
                    IF (SELECT count(*) FROM jsonb_object_keys(NEW.decision_payload)) <> 1
                       OR jsonb_typeof(NEW.decision_payload -> 'revision_request') <> 'string'
                       OR length(btrim(NEW.decision_payload ->> 'revision_request'))
                          NOT BETWEEN 1 AND 4000
                       OR NEW.decision_payload ->> 'revision_request'
                          <> btrim(NEW.decision_payload ->> 'revision_request') THEN
                        RAISE EXCEPTION
                            'an ICP revision requires one trimmed revision_request '
                            'of 1-4000 characters';
                    END IF;
                ELSIF NEW.decision_payload <> '{{}}'::jsonb THEN
                    RAISE EXCEPTION 'ICP approve/reject answers carry no decision payload';
                END IF;
            ELSIF presented.kind = 'product_selection' THEN
                IF NEW.decision_payload <> '{{}}'::jsonb THEN
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
                        SELECT 1 FROM jsonb_array_elements(
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
{product_set_branch}{crm_branch}{discovery_branch}
            ELSIF NEW.decision_payload <> '{{}}'::jsonb
                  OR NEW.selected_option_ref IS NOT NULL THEN
                RAISE EXCEPTION 'this gate kind does not accept auxiliary answer input';
            END IF;

            SELECT * INTO answering_turn FROM agent_turn_submission
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
