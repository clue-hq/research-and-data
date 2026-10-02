"""widen tool request and provider operation field axis to core fields

Revision ID: 9184f54adc26
Revises: 91fd9e4d772b
Create Date: 2026-08-18 19:15:00.470287+00:00

Slice B admitted the comprehensive profile's ten ``core.*`` firmographic rows into the account
launch selection (``account_axis_field_keys`` at the launcher) and widened the coverage-row CHECK
(``99923d6527c3``) — but two trigger functions on the governed request path still restate the old
raw-prefix rule ``field_key LIKE subject_type || '.%'``, so an account job that was *launched*
with ``core.industry`` could not *request* it: the first governed ``enrich_account`` naming a
``core.*`` field raised ``governed tool request contains a cross-axis field``, and (behind it)
``provider operation contains invalid field authority``.  Widen both predicates to the same
launch-field axis: an ``account`` subject also owns ``core.%``; a ``contact`` subject is
untouched and still refuses everything but ``contact.%``.  The Python mirrors of this rule
(``clue_api.entity_research_tools.field_key_on_subject_axis``) change in the same commit — the
trigger predicates and that helper must stay in lockstep.

Trigger functions validate future rows only (no stored-row re-validation is involved), so both
directions are pure ``CREATE OR REPLACE FUNCTION``; the attached triggers are untouched.  The
bodies below are the live definitions from ``5764311c620d`` with only the cross-axis predicate
parametrized.

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
revision: str = "9184f54adc26"
down_revision: str | None = "91fd9e4d772b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The R4-era raw prefix rule: every requested field must live under the subject's namespace.
_ORIGINAL_CROSS_AXIS = "field_key NOT LIKE NEW.subject_type || '.%'"

#: The launch-field axis (contract §3.1 / ``account_axis_field_keys``): an account subject also
#: owns the ``core.*`` firmographic rows.  Contact subjects keep the original rule.
_WIDENED_CROSS_AXIS = (
    "field_key NOT LIKE NEW.subject_type || '.%' "
    "AND NOT (NEW.subject_type::text = 'account' AND field_key LIKE 'core.%')"
)


def _replace_field_axis(cross_axis_predicate: str) -> None:
    """Rebuild both governed-path trigger functions around ``cross_axis_predicate``.

    ``cross_axis_predicate`` matches a field key that is OUTSIDE the subject's axis (the
    exception-raising direction).  Everything else in both bodies is byte-identical to the live
    ``5764311c620d`` definitions.
    """

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION entity_research_validate_tool_request() RETURNS trigger AS $$
        DECLARE authority_fields text[]; authority_sources text[];
        BEGIN
            IF EXISTS (
                SELECT 1 FROM unnest(NEW.field_keys) AS field_key
                WHERE {cross_axis_predicate}
            ) THEN RAISE EXCEPTION 'governed tool request contains a cross-axis field'; END IF;
            SELECT coalesce(array_agg(value->>'field_key' ORDER BY value->>'field_key'), '{{}}')
              INTO authority_fields FROM jsonb_array_elements(NEW.field_source_authority) value;
            SELECT coalesce(array_agg(DISTINCT source ORDER BY source), '{{}}')
              INTO authority_sources FROM jsonb_array_elements(NEW.field_source_authority) value,
              LATERAL jsonb_array_elements_text(value->'source_keys') source;
            IF NEW.tool_name <> 'discover_buying_committee' AND (
                (SELECT array_agg(value ORDER BY value) FROM unnest(NEW.field_keys) value)
                    IS DISTINCT FROM authority_fields OR
                (SELECT array_agg(value ORDER BY value) FROM unnest(NEW.source_keys) value)
                    IS DISTINCT FROM authority_sources
            ) THEN RAISE EXCEPTION 'field-source authority differs from requested fields/sources';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM entity_research_agent_turn turn_row
                JOIN entity_research_agent_event event_row
                  ON event_row.event_id=NEW.tool_event_id
                 AND event_row.agent_turn_id=turn_row.agent_turn_id
                 AND event_row.agent_execution_id=turn_row.agent_execution_id
                WHERE turn_row.agent_turn_id=NEW.agent_turn_id
                  AND turn_row.agent_execution_id=NEW.agent_execution_id
                  AND turn_row.job_id=NEW.job_id AND turn_row.research_run_id=NEW.research_run_id
                  AND turn_row.subject_type=NEW.subject_type
                  AND turn_row.target_entity_id=NEW.target_entity_id
                  AND turn_row.parent_account_id IS NOT DISTINCT FROM NEW.parent_account_id
                  AND turn_row.workspace_id=NEW.workspace_id
                  AND turn_row.project_id=NEW.project_id AND turn_row.product_id=NEW.product_id
                  AND turn_row.project_run_id=NEW.project_run_id
                  AND turn_row.context_json->'tool_names' ? NEW.tool_name
                  AND NOT EXISTS (
                      SELECT 1 FROM unnest(NEW.field_keys) requested_field
                      WHERE NOT (turn_row.context_json->'admitted_field_keys' ? requested_field)
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM unnest(NEW.source_keys) requested_source
                      WHERE NOT (turn_row.context_json->'admitted_source_keys' ? requested_source)
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM jsonb_array_elements(NEW.field_source_authority) requested_authority
                      WHERE NOT EXISTS (
                          SELECT 1
                          FROM jsonb_array_elements(
                              turn_row.context_json->'field_source_authority'
                          ) admitted_authority
                          WHERE admitted_authority->>'field_key' =
                                requested_authority->>'field_key'
                            AND NOT EXISTS (
                                SELECT 1
                                FROM jsonb_array_elements_text(
                                    requested_authority->'source_keys'
                                ) requested_source
                                WHERE NOT (
                                    admitted_authority->'source_keys' ? requested_source
                                )
                            )
                      )
                  )
                  AND (
                      NEW.parent_operation_ref IS NOT NULL OR NOT EXISTS (
                          SELECT 1 FROM unnest(NEW.questions) requested_question
                          WHERE NOT (
                              turn_row.context_json->'research_questions' ? requested_question
                          )
                      )
                  )
                  AND event_row.event_kind='tool_started'
                  AND event_row.tool_call_id=NEW.raw_tool_call_id
                  AND event_row.tool_name=NEW.tool_name
                  AND event_row.tool_version=NEW.tool_version
                  AND event_row.tool_input_sha256=NEW.tool_input_sha256
                  AND event_row.occurred_at <= NEW.created_at
            ) THEN RAISE EXCEPTION 'governed tool request differs from admitted journal'; END IF;
            IF NEW.parent_operation_ref IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM entity_research_result parent_result
                JOIN entity_research_tool_request parent_request
                  ON parent_request.tool_request_id=parent_result.tool_request_id
                WHERE NEW.parent_operation_ref=parent_result.provider_operation_ref
                  AND NEW.parent_observation_ref='research-result:' || parent_result.result_id::text
                  AND NEW.prior_result_sha256=parent_result.result_sha256
                  AND parent_request.research_run_id=NEW.research_run_id
                  AND parent_request.job_id=NEW.job_id
                  AND parent_request.subject_type=NEW.subject_type
                  AND parent_request.target_entity_id=NEW.target_entity_id
                  AND parent_request.workspace_id=NEW.workspace_id
                  AND parent_result.created_at <= NEW.created_at
            ) THEN RAISE EXCEPTION 'follow-up parent observation crosses exact job authority';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION protect_entity_research_provider_operation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP='INSERT' THEN
                IF cardinality(NEW.field_keys) IS DISTINCT FROM (
                    SELECT count(DISTINCT field_key) FROM unnest(NEW.field_keys) field_key
                ) OR EXISTS (
                    SELECT 1 FROM unnest(NEW.field_keys) field_key
                    WHERE {cross_axis_predicate}
                ) THEN
                    RAISE EXCEPTION 'provider operation contains invalid field authority';
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP='DELETE' OR
               ROW(NEW.operation_ref, NEW.provider_kind, NEW.workspace_id, NEW.project_id,
                   NEW.project_run_id, NEW.subject_type, NEW.target_entity_id,
                   NEW.parent_account_id, NEW.source_key, NEW.field_keys,
                   NEW.request_artifact_ref,
                   NEW.reserved_at)
               IS DISTINCT FROM
               ROW(OLD.operation_ref, OLD.provider_kind, OLD.workspace_id, OLD.project_id,
                   OLD.project_run_id, OLD.subject_type, OLD.target_entity_id,
                   OLD.parent_account_id, OLD.source_key, OLD.field_keys,
                   OLD.request_artifact_ref,
                   OLD.reserved_at) OR
               (OLD.dispatched_at IS NOT NULL AND
                NEW.dispatched_at IS DISTINCT FROM OLD.dispatched_at)
            THEN RAISE EXCEPTION 'provider operation authority is immutable';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )


def upgrade() -> None:
    _replace_field_axis(_WIDENED_CROSS_AXIS)


def downgrade() -> None:
    # Loud by design: after downgrade a new account tool request naming a ``core.*`` field is
    # refused again; already-stored rows are historical ledger facts and stay untouched.
    _replace_field_axis(_ORIGINAL_CROSS_AXIS)
