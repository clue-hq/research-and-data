"""arv2 onboarding substrate

Revision ID: 0aa95f87eb49
Revises: 44039cb83844
Create Date: 2026-09-07 14:32:08.550289+00:00

Track O substrate (docs/specs/ARV2-ONBOARDING-PLAN.md §3, §6; ARV2-PRODUCT-CATALOG-CONTRACT.md §6):
onboarding runs/steps, brand knowledge documents, the versioned project product set, and the
product_set_selection human gate. Nothing here references a Client-KB version, a readiness
decision, or a Stage-0 run pin (standing rule, catalog contract §10).

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
revision: str = "0aa95f87eb49"
down_revision: str | None = "44039cb83844"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _create_onboarding_tables()
    _create_project_product()
    _install_product_set_gate_kind()


def downgrade() -> None:
    _remove_product_set_gate_kind()
    _drop_project_product()
    _drop_onboarding_tables()


# --- §3 onboarding run / step / document ------------------------------------------------------


def _create_onboarding_tables() -> None:
    op.execute(
        """
        CREATE TABLE onboarding_run (
            run_id               uuid NOT NULL,
            workspace_id         text NOT NULL,
            brand_id             text NOT NULL,
            client_entity_id     uuid,
            company_domain       text NOT NULL,
            requested_by_user_id text NOT NULL,
            requested_at         timestamptz NOT NULL DEFAULT now(),
            status               text NOT NULL DEFAULT 'queued',
            lane_version         text NOT NULL DEFAULT 'onboarding-v2',
            cost_usd             numeric(12, 6) NOT NULL DEFAULT 0,
            finished_at          timestamptz,

            CONSTRAINT onboarding_run_pkey PRIMARY KEY (run_id),
            -- Composite-FK anchor: lets a step pin (run, workspace) as one unit, so a step can
            -- never carry a workspace its own run does not belong to.
            CONSTRAINT onboarding_run_workspace_anchor UNIQUE (run_id, workspace_id),
            CONSTRAINT onboarding_run_status CHECK (status IN
                ('queued', 'running', 'completed', 'completed_with_gaps', 'failed')),
            CONSTRAINT onboarding_run_finished_when_terminal CHECK
                ((status IN ('queued', 'running')) = (finished_at IS NULL)),
            CONSTRAINT onboarding_run_domain_nonblank CHECK (length(btrim(company_domain)) > 0),
            CONSTRAINT onboarding_run_cost_nonnegative CHECK (cost_usd >= 0),
            CONSTRAINT onboarding_run_brand_fk FOREIGN KEY (brand_id, workspace_id)
                REFERENCES brand (brand_id, workspace_id),
            CONSTRAINT onboarding_run_user_fk FOREIGN KEY (requested_by_user_id)
                REFERENCES platform_user (user_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX onboarding_run_workspace_requested "
        "ON onboarding_run (workspace_id, requested_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE onboarding_step (
            step_id            uuid NOT NULL,
            run_id             uuid NOT NULL,
            workspace_id       text NOT NULL,
            kind               text NOT NULL,
            subject_ref        text,
            phase              text NOT NULL,
            status             text NOT NULL DEFAULT 'queued',
            provider_run_id    text,
            raw_artifact_key   text,
            output_document_id uuid,
            cost_usd           numeric(12, 6) NOT NULL DEFAULT 0,
            searches           integer NOT NULL DEFAULT 0,
            started_at         timestamptz,
            finished_at        timestamptz,
            failure_code       text,
            failure_message    text,

            CONSTRAINT onboarding_step_pkey PRIMARY KEY (step_id),
            -- Tenancy is structural, not writer-trusted: a step pins (run, workspace) as one unit.
            CONSTRAINT onboarding_step_run_fk FOREIGN KEY (run_id, workspace_id)
                REFERENCES onboarding_run (run_id, workspace_id),
            -- Composite-FK anchor: lets a document pin (step, workspace) as one unit.
            CONSTRAINT onboarding_step_workspace_anchor UNIQUE (step_id, workspace_id),
            CONSTRAINT onboarding_step_kind CHECK (kind IN
                ('overview', 'lineup', 'catalog_sync', 'reviews', 'synthesis', 'product_research')),
            CONSTRAINT onboarding_step_phase CHECK (phase IN ('fast', 'background')),
            CONSTRAINT onboarding_step_status CHECK (status IN
                ('queued', 'running', 'completed', 'empty', 'failed')),
            CONSTRAINT onboarding_step_failure_pair CHECK
                ((status = 'failed') = (failure_code IS NOT NULL)),
            CONSTRAINT onboarding_step_finished_when_terminal CHECK
                ((status IN ('queued', 'running')) = (finished_at IS NULL)),
            CONSTRAINT onboarding_step_cost_nonnegative CHECK (cost_usd >= 0 AND searches >= 0)
        )
        """
    )
    # subject_ref is NULL for the single-subject kinds; COALESCE makes the identity unique anyway.
    op.execute(
        "CREATE UNIQUE INDEX onboarding_step_identity "
        "ON onboarding_step (run_id, kind, COALESCE(subject_ref, ''))"
    )
    op.execute("CREATE INDEX onboarding_step_run ON onboarding_step (run_id, phase, status)")
    op.execute(
        """
        CREATE TABLE brand_knowledge_document (
            document_id            uuid NOT NULL,
            workspace_id           text NOT NULL,
            brand_id               text NOT NULL,
            folder                 text NOT NULL,
            path                   text NOT NULL,
            kind                   text NOT NULL,
            version                integer NOT NULL,
            status                 text NOT NULL DEFAULT 'running',
            artifact_key           text,
            artifact_sha256        text,
            produced_by_step_id    uuid,
            produced_by_turn_id    uuid,
            supersedes_document_id uuid,
            created_at             timestamptz NOT NULL DEFAULT now(),
            updated_at             timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT brand_knowledge_document_pkey PRIMARY KEY (document_id),
            CONSTRAINT brand_knowledge_document_brand_fk FOREIGN KEY (brand_id, workspace_id)
                REFERENCES brand (brand_id, workspace_id),
            -- A NULL produced_by_step_id leaves this FK unenforced: the "produced by a turn
            -- instead" case. When a step IS named, it must live in the document's workspace.
            CONSTRAINT brand_knowledge_document_step_fk
                FOREIGN KEY (produced_by_step_id, workspace_id)
                REFERENCES onboarding_step (step_id, workspace_id),
            CONSTRAINT brand_knowledge_document_turn_fk FOREIGN KEY (produced_by_turn_id)
                REFERENCES agent_turn (id),
            CONSTRAINT brand_knowledge_document_supersedes_fk FOREIGN KEY (supersedes_document_id)
                REFERENCES brand_knowledge_document (document_id),
            CONSTRAINT brand_knowledge_document_folder CHECK (folder IN
                ('company', 'product', 'audience', 'proof', 'design')),
            CONSTRAINT brand_knowledge_document_kind CHECK (kind IN
                ('company-overview', 'product-catalog', 'product-research', 'customer-reviews',
                 'icp-definition', 'audience-persona', 'design-brief')),
            CONSTRAINT brand_knowledge_document_status CHECK (status IN
                ('running', 'ready', 'empty', 'failed', 'proposed', 'confirmed', 'superseded')),
            CONSTRAINT brand_knowledge_document_version_positive CHECK (version >= 1),
            CONSTRAINT brand_knowledge_document_path_in_folder CHECK (path LIKE folder || '/%'),
            CONSTRAINT brand_knowledge_document_one_producer CHECK
                (NOT (produced_by_step_id IS NOT NULL AND produced_by_turn_id IS NOT NULL)),
            -- A served status means bytes exist: key + a real sha256.
            CONSTRAINT brand_knowledge_document_body_when_served CHECK
                (status NOT IN ('ready', 'proposed', 'confirmed', 'superseded')
                 OR (artifact_key IS NOT NULL AND artifact_sha256 ~ '^[0-9a-f]{64}$')),
            CONSTRAINT brand_knowledge_document_path_version
                UNIQUE (workspace_id, brand_id, path, version)
        )
        """
    )
    op.execute(
        "CREATE INDEX brand_knowledge_document_tree "
        "ON brand_knowledge_document (workspace_id, brand_id, folder, path, version DESC)"
    )
    op.execute(
        "ALTER TABLE onboarding_step ADD CONSTRAINT onboarding_step_output_document_fk "
        "FOREIGN KEY (output_document_id) REFERENCES brand_knowledge_document (document_id)"
    )


def _drop_onboarding_tables() -> None:
    op.execute("ALTER TABLE onboarding_step DROP CONSTRAINT onboarding_step_output_document_fk")
    op.execute("DROP INDEX brand_knowledge_document_tree")
    op.execute("DROP TABLE brand_knowledge_document")
    op.execute("DROP INDEX onboarding_step_run")
    op.execute("DROP INDEX onboarding_step_identity")
    op.execute("DROP TABLE onboarding_step")
    op.execute("DROP INDEX onboarding_run_workspace_requested")
    op.execute("DROP TABLE onboarding_run")


# --- §6.2 the versioned project product set (rulings P1/P2) ------------------------------------


def _create_project_product() -> None:
    # The composite FKs bind to the spine's existing anchors — product_context_anchor (product)
    # and project_run_context_anchor (project) — so no new unique index is needed here.
    op.execute(
        """
        CREATE TABLE project_product (
            workspace_id          text NOT NULL,
            project_id            text NOT NULL,
            brand_id              text NOT NULL,
            product_id            text NOT NULL,
            selection_version     integer NOT NULL,
            gate_id               uuid NOT NULL,
            confirmed_by_user_id  text NOT NULL,
            confirmed_at          timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT project_product_pkey PRIMARY KEY (project_id, selection_version, product_id),
            CONSTRAINT project_product_version_positive CHECK (selection_version >= 1),
            -- Same workspace AND same brand, structurally (the pin project.product_id had).
            CONSTRAINT project_product_product_fk FOREIGN KEY (product_id, brand_id, workspace_id)
                REFERENCES product (product_id, brand_id, workspace_id),
            CONSTRAINT project_product_project_fk FOREIGN KEY (project_id, brand_id, workspace_id)
                REFERENCES project (project_id, brand_id, workspace_id),
            CONSTRAINT project_product_user_fk FOREIGN KEY (confirmed_by_user_id)
                REFERENCES platform_user (user_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX project_product_current "
        "ON project_product (project_id, selection_version DESC)"
    )
    # gate_id is the answered product_set_selection gate. It is deliberately NOT a foreign key:
    # clue_spine sits below clue_api.agent_gate, and the answer row (agent_gate_answer, PK gate_id)
    # is the durable proof the route checks before calling confirm_project_product_set.
    op.execute(
        "CREATE TRIGGER project_product_append_only "
        "BEFORE UPDATE OR DELETE ON project_product FOR EACH ROW "
        "EXECUTE FUNCTION execution_reject_append_only_mutation()"
    )


def _drop_project_product() -> None:
    op.execute("DROP TRIGGER project_product_append_only ON project_product")
    op.execute("DROP INDEX project_product_current")
    op.execute("DROP TABLE project_product")


# --- §6.3 the product_set_selection human gate ------------------------------------------------

_GATE_KINDS_BEFORE = (
    "'directive_confirmation', 'icp_confirmation', 'product_selection', "
    "'plan_approval', 'budget_approval'"
)
_GATE_KINDS_AFTER = (
    "'directive_confirmation', 'icp_confirmation', 'product_selection', "
    "'product_set_selection', 'plan_approval', 'budget_approval'"
)


def _install_product_set_gate_kind() -> None:
    op.execute("ALTER TABLE agent_gate DROP CONSTRAINT agent_gate_kind")
    op.execute(
        "ALTER TABLE agent_gate ADD CONSTRAINT agent_gate_kind "
        f"CHECK (kind IN ({_GATE_KINDS_AFTER}))"
    )
    op.execute(_answer_validator(product_set=True))


def _remove_product_set_gate_kind() -> None:
    op.execute(_answer_validator(product_set=False))
    op.execute("ALTER TABLE agent_gate DROP CONSTRAINT agent_gate_kind")
    op.execute(
        "ALTER TABLE agent_gate ADD CONSTRAINT agent_gate_kind "
        f"CHECK (kind IN ({_GATE_KINDS_BEFORE}))"
    )


def _answer_validator(*, product_set: bool) -> str:
    """The whole ``agent_gate_answer_validate()`` body, exactly as 064ad0f43519 installs it, with
    the product-set branch inserted before the generic refusal when ``product_set`` is true.
    ``tests/db/test_arv2_onboarding_substrate_migration.py`` proves the ``False`` form is
    text-identical to the previous migration's, so ``downgrade()`` reinstalls the real thing."""
    product_set_branch = (
        """
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
        if product_set
        else ""
    )
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
{product_set_branch}{discovery_branch}
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
