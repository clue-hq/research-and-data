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


def downgrade() -> None:
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
