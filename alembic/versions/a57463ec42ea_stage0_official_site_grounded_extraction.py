"""stage0 official site grounded extraction

Revision ID: a57463ec42ea
Revises: 93113e83bf2f
Create Date: 2026-08-14 03:26:35.430546+00:00

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
revision: str = "a57463ec42ea"
down_revision: str | None = "93113e83bf2f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "official_site_corpus_checkpoint_run_scope_anchor",
        "official_site_corpus_checkpoint",
        ["id", "crawl_run_id", "workspace_id"],
    )
    op.create_unique_constraint(
        "run_lineage_workspace_anchor", "run_lineage", ["run_id", "workspace_id"]
    )
    op.execute(
        """
        CREATE TABLE official_site_extraction_operation (
            id                         uuid PRIMARY KEY,
            workspace_id               text NOT NULL,
            crawl_run_id               uuid NOT NULL,
            checkpoint_id              uuid NOT NULL,
            recon_run_id               uuid NOT NULL,
            claim_run_id               uuid NOT NULL,
            client_entity_id           uuid NOT NULL,
            phase                      text NOT NULL,
            category                   text NOT NULL,
            field_key                  text NOT NULL,
            model_id                   text NOT NULL,
            answering_model_id         text,
            prompt_version             text NOT NULL,
            schema_version             text NOT NULL,
            corpus_version             text NOT NULL,
            input_sha256               text NOT NULL,
            snapshot_ids_json          jsonb NOT NULL,
            state                      text NOT NULL DEFAULT 'prepared',
            response_artifact_key      text,
            response_sha256            text,
            prompt_tokens              integer,
            completion_tokens          integer,
            cost_cents                 numeric,
            claim_ids_json             jsonb NOT NULL DEFAULT '[]'::jsonb,
            failure_code               text,
            created_at                 timestamptz NOT NULL DEFAULT now(),
            dispatched_at              timestamptz,
            response_retained_at        timestamptz,
            completed_at               timestamptz,

            CONSTRAINT official_site_extraction_operation_scope_anchor
                UNIQUE (id, workspace_id),
            CONSTRAINT official_site_extraction_operation_identity UNIQUE (
                workspace_id, checkpoint_id, claim_run_id, category, field_key,
                model_id, prompt_version, schema_version, corpus_version, input_sha256
            ),
            CONSTRAINT official_site_extraction_operation_run_fk
                FOREIGN KEY (crawl_run_id, workspace_id)
                REFERENCES official_site_crawl_run (id, workspace_id),
            CONSTRAINT official_site_extraction_operation_checkpoint_fk
                FOREIGN KEY (checkpoint_id, crawl_run_id, workspace_id)
                REFERENCES official_site_corpus_checkpoint (id, crawl_run_id, workspace_id),
            CONSTRAINT official_site_extraction_operation_recon_fk
                FOREIGN KEY (recon_run_id, workspace_id)
                REFERENCES recon_run (id, workspace_id),
            CONSTRAINT official_site_extraction_operation_claim_run_fk
                FOREIGN KEY (claim_run_id, workspace_id)
                REFERENCES run_lineage (run_id, workspace_id),
            CONSTRAINT official_site_extraction_operation_entity_fk
                FOREIGN KEY (client_entity_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT official_site_extraction_operation_response_artifact_fk
                FOREIGN KEY (response_artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT official_site_extraction_operation_phase
                CHECK (phase IN ('fast', 'background')),
            CONSTRAINT official_site_extraction_operation_category CHECK (
                category IN ('product_value', 'pricing_proof', 'customer_evidence',
                             'company_context')
            ),
            CONSTRAINT official_site_extraction_operation_state CHECK (
                state IN ('prepared', 'dispatched', 'response_retained', 'materialized',
                          'empty', 'failed', 'spend_unknown')
            ),
            CONSTRAINT official_site_extraction_operation_hashes CHECK (
                input_sha256 ~ '^[0-9a-f]{64}$'
                AND (response_sha256 IS NULL OR response_sha256 ~ '^[0-9a-f]{64}$')
            ),
            CONSTRAINT official_site_extraction_operation_json_shapes CHECK (
                jsonb_typeof(snapshot_ids_json) = 'array'
                AND jsonb_typeof(claim_ids_json) = 'array'
            ),
            CONSTRAINT official_site_extraction_operation_usage CHECK (
                (prompt_tokens IS NULL OR prompt_tokens >= 0)
                AND (completion_tokens IS NULL OR completion_tokens >= 0)
                AND (cost_cents IS NULL OR cost_cents >= 0)
            ),
            CONSTRAINT official_site_extraction_operation_dispatch CHECK (
                (state = 'prepared' AND dispatched_at IS NULL)
                OR (state = 'empty' AND response_artifact_key IS NULL
                    AND dispatched_at IS NULL)
                OR (state NOT IN ('prepared', 'empty') AND dispatched_at IS NOT NULL)
                OR (state = 'empty' AND response_artifact_key IS NOT NULL
                    AND dispatched_at IS NOT NULL)
            ),
            CONSTRAINT official_site_extraction_operation_response CHECK (
                state NOT IN ('response_retained', 'materialized', 'failed')
                OR (response_artifact_key IS NOT NULL AND response_sha256 IS NOT NULL
                    AND answering_model_id IS NOT NULL AND response_retained_at IS NOT NULL)
            ),
            CONSTRAINT official_site_extraction_operation_terminal CHECK (
                (state IN ('materialized', 'empty', 'failed', 'spend_unknown')
                    AND completed_at IS NOT NULL)
                OR (state NOT IN ('materialized', 'empty', 'failed', 'spend_unknown')
                    AND completed_at IS NULL)
            ),
            CONSTRAINT official_site_extraction_operation_failure CHECK (
                (state IN ('failed', 'spend_unknown') AND failure_code IS NOT NULL)
                OR (state NOT IN ('failed', 'spend_unknown') AND failure_code IS NULL)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX official_site_extraction_operation_checkpoint "
        "ON official_site_extraction_operation (workspace_id, checkpoint_id, state)"
    )
    op.execute(
        "CREATE INDEX official_site_extraction_operation_claim_run "
        "ON official_site_extraction_operation (workspace_id, claim_run_id, field_key)"
    )
    op.execute(
        "CREATE INDEX official_site_extraction_operation_response_artifact "
        "ON official_site_extraction_operation (response_artifact_key) "
        "WHERE response_artifact_key IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP TABLE official_site_extraction_operation")
    op.drop_constraint("run_lineage_workspace_anchor", "run_lineage", type_="unique")
    op.drop_constraint(
        "official_site_corpus_checkpoint_run_scope_anchor",
        "official_site_corpus_checkpoint",
        type_="unique",
    )
