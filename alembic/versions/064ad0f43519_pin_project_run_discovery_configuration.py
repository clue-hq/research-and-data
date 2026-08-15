"""pin project run discovery configuration

Revision ID: 064ad0f43519
Revises: f85ca69b93ba
Create Date: 2026-08-15 23:09:36.758238+00:00

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
revision: str = "064ad0f43519"
down_revision: str | None = "f85ca69b93ba"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Pin the provider-neutral discovery scope and permit its bounded revision receipt."""

    op.execute(
        """
        CREATE TABLE project_run_discovery_configuration (
            project_run_id          uuid PRIMARY KEY,
            workspace_id            text NOT NULL,
            project_id              text NOT NULL,
            icp_key                 text NOT NULL,
            icp_version             int NOT NULL,
            planning_policy_version text NOT NULL,
            configuration_json      jsonb NOT NULL,
            configuration_sha256    text NOT NULL,
            source_gate_id           uuid,
            created_at               timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT project_run_discovery_configuration_icp_version
                CHECK (icp_version >= 1),
            CONSTRAINT project_run_discovery_configuration_policy
                CHECK (length(btrim(planning_policy_version)) > 0),
            CONSTRAINT project_run_discovery_configuration_json
                CHECK (jsonb_typeof(configuration_json) = 'object'),
            CONSTRAINT project_run_discovery_configuration_hash
                CHECK (configuration_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT project_run_discovery_configuration_run_fk
                FOREIGN KEY (project_run_id) REFERENCES project_run (id),
            CONSTRAINT project_run_discovery_configuration_workspace_fk
                FOREIGN KEY (workspace_id) REFERENCES workspace (workspace_id),
            CONSTRAINT project_run_discovery_configuration_gate_fk
                FOREIGN KEY (source_gate_id) REFERENCES agent_gate (gate_id)
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION project_run_discovery_configuration_validate() RETURNS trigger AS $$
        DECLARE
            pinned_run project_run%ROWTYPE;
            source_gate agent_gate%ROWTYPE;
            source_answer agent_gate_answer%ROWTYPE;
        BEGIN
            SELECT * INTO pinned_run FROM project_run WHERE id = NEW.project_run_id;
            IF NOT FOUND
               OR pinned_run.workspace_id <> NEW.workspace_id
               OR pinned_run.project_id <> NEW.project_id
               OR pinned_run.icp_key <> NEW.icp_key
               OR pinned_run.icp_version <> NEW.icp_version THEN
                RAISE EXCEPTION 'discovery configuration does not match project-run lineage';
            END IF;
            IF NEW.configuration_json ->> 'schema_version'
                   IS DISTINCT FROM 'stage0-discovery-configuration@1'
               OR NEW.configuration_json ->> 'entity_type' IS DISTINCT FROM 'company'
               OR jsonb_typeof(NEW.configuration_json -> 'requested_account_count')
                  IS DISTINCT FROM 'number'
               OR (NEW.configuration_json ->> 'requested_account_count')::int NOT BETWEEN 1 AND 50
               OR jsonb_typeof(NEW.configuration_json -> 'search_intent')
                  IS DISTINCT FROM 'string'
               OR length(btrim(NEW.configuration_json ->> 'search_intent')) NOT BETWEEN 1 AND 4000
               OR jsonb_typeof(NEW.configuration_json -> 'must_have_criteria')
                  IS DISTINCT FROM 'array'
               OR jsonb_array_length(NEW.configuration_json -> 'must_have_criteria') = 0
               OR jsonb_array_length(NEW.configuration_json -> 'must_have_criteria') > 50
               OR EXISTS (
                   SELECT 1
                   FROM jsonb_array_elements(
                       NEW.configuration_json -> 'must_have_criteria'
                   ) criterion
                   WHERE jsonb_typeof(criterion) IS DISTINCT FROM 'string'
                      OR length(btrim(criterion #>> '{}')) NOT BETWEEN 1 AND 500
                      OR criterion #>> '{}' IS DISTINCT FROM btrim(criterion #>> '{}')
               )
               OR (
                   SELECT count(*) FROM jsonb_array_elements_text(
                       NEW.configuration_json -> 'must_have_criteria'
                   ) criterion
               ) <> (
                   SELECT count(DISTINCT criterion)
                   FROM jsonb_array_elements_text(
                       NEW.configuration_json -> 'must_have_criteria'
                   ) criterion
               )
               OR jsonb_typeof(NEW.configuration_json -> 'exclusion_criteria')
                  IS DISTINCT FROM 'array'
               OR jsonb_array_length(NEW.configuration_json -> 'exclusion_criteria') > 50
               OR EXISTS (
                   SELECT 1
                   FROM jsonb_array_elements(
                       NEW.configuration_json -> 'exclusion_criteria'
                   ) criterion
                   WHERE jsonb_typeof(criterion) IS DISTINCT FROM 'string'
                      OR length(btrim(criterion #>> '{}')) NOT BETWEEN 1 AND 500
                      OR criterion #>> '{}' IS DISTINCT FROM btrim(criterion #>> '{}')
               )
               OR (
                   SELECT count(*) FROM jsonb_array_elements_text(
                       NEW.configuration_json -> 'exclusion_criteria'
                   ) criterion
               ) <> (
                   SELECT count(DISTINCT criterion)
                   FROM jsonb_array_elements_text(
                       NEW.configuration_json -> 'exclusion_criteria'
                   ) criterion
               )
               OR NEW.configuration_json - ARRAY[
                   'schema_version', 'approved_icp_ref', 'entity_type',
                   'requested_account_count', 'search_intent',
                   'must_have_criteria', 'exclusion_criteria'
               ] <> '{}'::jsonb
               OR NEW.configuration_json ->> 'approved_icp_ref'
                  IS DISTINCT FROM 'icp-spec:' || NEW.workspace_id || ':' || NEW.icp_key
                     || ':' || 'v' || NEW.icp_version::text THEN
                RAISE EXCEPTION 'discovery configuration is not a valid provider-neutral scope';
            END IF;
            IF NEW.source_gate_id IS NOT NULL THEN
                SELECT * INTO source_gate
                FROM agent_gate
                WHERE gate_id = NEW.source_gate_id AND workspace_id = NEW.workspace_id;
                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'discovery configuration gate is absent or belongs to another workspace';
                END IF;
                SELECT * INTO source_answer
                FROM agent_gate_answer
                WHERE gate_id = NEW.source_gate_id AND workspace_id = NEW.workspace_id;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'discovery configuration gate has no durable answer';
                END IF;
                IF source_gate.kind <> 'directive_confirmation'
                   OR source_gate.project_id <> NEW.project_id
                   OR source_gate.subject_revision <> NEW.icp_version
                   OR source_gate.snapshot_erased_at IS NOT NULL
                   OR source_gate.subject_snapshot ->> 'subject_kind'
                      <> 'discovery_configuration'
                   OR source_gate.subject_snapshot ->> 'planning_policy_version'
                      <> NEW.planning_policy_version
                   OR source_gate.subject_snapshot -> 'configuration'
                      <> NEW.configuration_json
                   OR source_answer.expected_subject_sha256
                      <> source_gate.expected_subject_sha256
                   OR source_answer.answered_by_user_id <> source_gate.addressee_user_id
                   OR source_answer.decision <> 'approved' THEN
                    RAISE EXCEPTION
                        'discovery configuration gate is absent, foreign, stale or unapproved';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER project_run_discovery_configuration_authority
        BEFORE INSERT ON project_run_discovery_configuration
        FOR EACH ROW EXECUTE FUNCTION project_run_discovery_configuration_validate()
        """
    )
    op.execute(
        """
        CREATE FUNCTION project_run_discovery_configuration_reject_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'project_run_discovery_configuration is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER project_run_discovery_configuration_immutable
        BEFORE UPDATE OR DELETE ON project_run_discovery_configuration
        FOR EACH ROW EXECUTE FUNCTION project_run_discovery_configuration_reject_mutation()
        """
    )

    # A discovery-scope proposal reuses the directive gate substrate.  Its only auxiliary answer
    # is the same bounded revision_request used by ICP revision; ordinary research directives
    # remain unable to carry one.
    op.execute(_answer_validator(discovery_configuration_revision=True))


def downgrade() -> None:
    """Restore the exact unified-gate parent after removing discovery configuration rows."""

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM project_run_discovery_configuration) THEN
                RAISE EXCEPTION
                    'cannot downgrade while project-run discovery configurations exist';
            END IF;
            IF EXISTS (
                SELECT 1 FROM agent_gate
                WHERE kind = 'directive_confirmation'
                  AND subject_snapshot ->> 'subject_kind' = 'discovery_configuration'
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade while discovery-configuration gates exist';
            END IF;
        END;
        $$
        """
    )
    op.execute(_answer_validator(discovery_configuration_revision=False))
    op.execute(
        "DROP TRIGGER project_run_discovery_configuration_immutable "
        "ON project_run_discovery_configuration"
    )
    op.execute("DROP FUNCTION project_run_discovery_configuration_reject_mutation()")
    op.execute(
        "DROP TRIGGER project_run_discovery_configuration_authority "
        "ON project_run_discovery_configuration"
    )
    op.execute("DROP FUNCTION project_run_discovery_configuration_validate()")
    op.execute("DROP TABLE project_run_discovery_configuration")


def _answer_validator(*, discovery_configuration_revision: bool) -> str:
    discovery_branch = (
        """
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
        if discovery_configuration_revision
        else ""
    )
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
{discovery_branch}
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
