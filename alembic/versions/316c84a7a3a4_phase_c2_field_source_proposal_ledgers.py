"""phase c2 field source proposal ledgers

Revision ID: 316c84a7a3a4
Revises: b366c985ca12
Create Date: 2026-07-24 11:56:56.143297+00:00

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
revision: str = "316c84a7a3a4"
down_revision: str | None = "b366c985ca12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE proposal_status AS ENUM ('proposed', 'promoted', 'rejected', 'withdrawn')"
    )
    op.execute("CREATE TYPE proposal_authority AS ENUM ('policy', 'human')")

    op.execute(
        """
        CREATE TABLE field_definition_revision (
            id                   uuid NOT NULL,
            workspace_id         text NOT NULL,
            brand_id             text NOT NULL,
            product_id           text,
            project_id           text,
            icp_key              text,
            icp_spec_version     int,
            field_key            text NOT NULL,
            payload_hash         text NOT NULL,
            payload_json         jsonb NOT NULL,
            status               proposal_status NOT NULL DEFAULT 'proposed',
            proposed_by_actor    text NOT NULL,
            proposed_by_ref      text,
            proposed_at          timestamptz NOT NULL DEFAULT now(),
            required_authority   proposal_authority NOT NULL,
            decided_by           text,
            decision_authority   proposal_authority,
            decided_at           timestamptz,
            decision_reason      text,
            applied_field_key    text,
            applied_version      int,

            CONSTRAINT field_definition_revision_pkey PRIMARY KEY (id),
            CONSTRAINT field_definition_revision_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT field_definition_revision_brand_fk FOREIGN KEY (brand_id, workspace_id)
                REFERENCES brand (brand_id, workspace_id),
            CONSTRAINT field_definition_revision_product_fk FOREIGN KEY (product_id, workspace_id)
                REFERENCES product (product_id, workspace_id),
            CONSTRAINT field_definition_revision_project_fk FOREIGN KEY (project_id)
                REFERENCES project (project_id),
            CONSTRAINT field_definition_revision_icp_fk
                FOREIGN KEY (workspace_id, icp_key, icp_spec_version)
                REFERENCES icp_spec (workspace_id, icp_key, version),
            CONSTRAINT field_definition_revision_payload_object
                CHECK (jsonb_typeof(payload_json) = 'object'),
            CONSTRAINT field_definition_revision_hash_shape
                CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
            CONSTRAINT field_definition_revision_actor
                CHECK (proposed_by_actor IN ('agent', 'human', 'policy', 'system')),
            CONSTRAINT field_definition_revision_icp_pair CHECK (
                (icp_key IS NULL) = (icp_spec_version IS NULL)
            ),
            CONSTRAINT field_definition_revision_icp_version
                CHECK (icp_spec_version IS NULL OR icp_spec_version >= 1),
            CONSTRAINT field_definition_revision_applied_version
                CHECK (applied_version IS NULL OR applied_version >= 1),
            CONSTRAINT field_definition_revision_decision_stamp CHECK (
                (
                    status = 'proposed'
                    AND decided_at IS NULL
                    AND decided_by IS NULL
                    AND decision_authority IS NULL
                    AND decision_reason IS NULL
                )
                OR
                (
                    status <> 'proposed'
                    AND decided_at IS NOT NULL
                    AND decided_by IS NOT NULL
                    AND decision_authority IS NOT NULL
                    AND decision_reason IS NOT NULL
                )
            ),
            CONSTRAINT field_definition_revision_applied_iff_promoted CHECK (
                (
                    status = 'promoted'
                    AND applied_field_key IS NOT NULL
                    AND applied_version IS NOT NULL
                )
                OR
                (
                    status <> 'promoted'
                    AND applied_field_key IS NULL
                    AND applied_version IS NULL
                )
            ),
            CONSTRAINT field_definition_revision_dedupe UNIQUE NULLS NOT DISTINCT (
                workspace_id, brand_id, product_id, project_id, icp_key, icp_spec_version,
                payload_hash
            )
        )
        """
    )

    op.execute(
        """
        CREATE TABLE source_manifest_revision (
            id                   uuid NOT NULL,
            workspace_id         text NOT NULL,
            brand_id             text NOT NULL,
            product_id           text,
            project_id           text,
            icp_key              text,
            icp_spec_version     int,
            source_key           text NOT NULL,
            payload_hash         text NOT NULL,
            payload_json         jsonb NOT NULL,
            status               proposal_status NOT NULL DEFAULT 'proposed',
            proposed_by_actor    text NOT NULL,
            proposed_by_ref      text,
            proposed_at          timestamptz NOT NULL DEFAULT now(),
            required_authority   proposal_authority NOT NULL,
            decided_by           text,
            decision_authority   proposal_authority,
            decided_at           timestamptz,
            decision_reason      text,
            assigned_tier        int,
            applied_source_key   text,
            applied_version      int,
            yield_observations   int NOT NULL DEFAULT 0,
            yield_rate           numeric(8, 6),
            demoted_at           timestamptz,
            demoted_by           text,
            demotion_reason      text,
            demoted_version      int,

            CONSTRAINT source_manifest_revision_pkey PRIMARY KEY (id),
            CONSTRAINT source_manifest_revision_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT source_manifest_revision_brand_fk FOREIGN KEY (brand_id, workspace_id)
                REFERENCES brand (brand_id, workspace_id),
            CONSTRAINT source_manifest_revision_product_fk FOREIGN KEY (product_id, workspace_id)
                REFERENCES product (product_id, workspace_id),
            CONSTRAINT source_manifest_revision_project_fk FOREIGN KEY (project_id)
                REFERENCES project (project_id),
            CONSTRAINT source_manifest_revision_icp_fk
                FOREIGN KEY (workspace_id, icp_key, icp_spec_version)
                REFERENCES icp_spec (workspace_id, icp_key, version),
            CONSTRAINT source_manifest_revision_payload_object
                CHECK (jsonb_typeof(payload_json) = 'object'),
            CONSTRAINT source_manifest_revision_hash_shape
                CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
            CONSTRAINT source_manifest_revision_actor
                CHECK (proposed_by_actor IN ('agent', 'human', 'policy', 'system')),
            CONSTRAINT source_manifest_revision_icp_pair CHECK (
                (icp_key IS NULL) = (icp_spec_version IS NULL)
            ),
            CONSTRAINT source_manifest_revision_icp_version
                CHECK (icp_spec_version IS NULL OR icp_spec_version >= 1),
            CONSTRAINT source_manifest_revision_assigned_tier
                CHECK (assigned_tier IS NULL OR assigned_tier BETWEEN 1 AND 4),
            CONSTRAINT source_manifest_revision_applied_version
                CHECK (applied_version IS NULL OR applied_version >= 1),
            CONSTRAINT source_manifest_revision_yield_observations
                CHECK (yield_observations >= 0),
            CONSTRAINT source_manifest_revision_yield_rate
                CHECK (yield_rate IS NULL OR (yield_rate >= 0 AND yield_rate <= 1)),
            CONSTRAINT source_manifest_revision_decision_stamp CHECK (
                (
                    status = 'proposed'
                    AND decided_at IS NULL
                    AND decided_by IS NULL
                    AND decision_authority IS NULL
                    AND decision_reason IS NULL
                )
                OR
                (
                    status <> 'proposed'
                    AND decided_at IS NOT NULL
                    AND decided_by IS NOT NULL
                    AND decision_authority IS NOT NULL
                    AND decision_reason IS NOT NULL
                )
            ),
            CONSTRAINT source_manifest_revision_applied_iff_promoted CHECK (
                (
                    status = 'promoted'
                    AND assigned_tier IS NOT NULL
                    AND applied_source_key IS NOT NULL
                    AND applied_version IS NOT NULL
                )
                OR
                (
                    status <> 'promoted'
                    AND assigned_tier IS NULL
                    AND applied_source_key IS NULL
                    AND applied_version IS NULL
                )
            ),
            CONSTRAINT source_manifest_revision_demotion_coherence CHECK (
                (
                    demoted_at IS NULL
                    AND demoted_by IS NULL
                    AND demotion_reason IS NULL
                    AND demoted_version IS NULL
                )
                OR
                (
                    demoted_at IS NOT NULL
                    AND demoted_by IS NOT NULL
                    AND demotion_reason IS NOT NULL
                    AND demoted_version IS NOT NULL
                    AND status = 'promoted'
                )
            ),
            CONSTRAINT source_manifest_revision_dedupe UNIQUE NULLS NOT DISTINCT (
                workspace_id, brand_id, product_id, project_id, icp_key, icp_spec_version,
                payload_hash
            )
        )
        """
    )

    op.execute(
        "CREATE INDEX field_definition_revision_scope "
        "ON field_definition_revision (workspace_id, brand_id, status, proposed_at DESC)"
    )
    op.execute(
        "CREATE INDEX source_manifest_revision_scope "
        "ON source_manifest_revision (workspace_id, brand_id, status, proposed_at DESC)"
    )
    op.execute(
        "CREATE INDEX source_manifest_revision_yield_watch "
        "ON source_manifest_revision (source_key, status) "
        "WHERE status = 'promoted' AND decision_authority = 'policy' AND assigned_tier = 3"
    )

    op.execute(
        """
        CREATE FUNCTION field_definition_revision_reject_payload_update() RETURNS trigger AS $$
        BEGIN
            IF NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
               OR NEW.brand_id IS DISTINCT FROM OLD.brand_id
               OR NEW.product_id IS DISTINCT FROM OLD.product_id
               OR NEW.project_id IS DISTINCT FROM OLD.project_id
               OR NEW.icp_key IS DISTINCT FROM OLD.icp_key
               OR NEW.icp_spec_version IS DISTINCT FROM OLD.icp_spec_version
               OR NEW.field_key IS DISTINCT FROM OLD.field_key
               OR NEW.payload_hash IS DISTINCT FROM OLD.payload_hash
               OR NEW.payload_json IS DISTINCT FROM OLD.payload_json
               OR NEW.proposed_by_actor IS DISTINCT FROM OLD.proposed_by_actor
               OR NEW.proposed_by_ref IS DISTINCT FROM OLD.proposed_by_ref
               OR NEW.proposed_at IS DISTINCT FROM OLD.proposed_at
               OR NEW.required_authority IS DISTINCT FROM OLD.required_authority THEN
                RAISE EXCEPTION
                    'field proposal payload and scope are immutable; submit a new proposal';
            END IF;
            IF OLD.status <> 'proposed'
               AND (
                   NEW.status IS DISTINCT FROM OLD.status
                   OR NEW.decided_by IS DISTINCT FROM OLD.decided_by
                   OR NEW.decision_authority IS DISTINCT FROM OLD.decision_authority
                   OR NEW.decided_at IS DISTINCT FROM OLD.decided_at
                   OR NEW.decision_reason IS DISTINCT FROM OLD.decision_reason
                   OR NEW.applied_field_key IS DISTINCT FROM OLD.applied_field_key
                   OR NEW.applied_version IS DISTINCT FROM OLD.applied_version
               ) THEN
                RAISE EXCEPTION 'field proposal decision is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER field_definition_revision_payload_immutable "
        "BEFORE UPDATE ON field_definition_revision FOR EACH ROW "
        "EXECUTE FUNCTION field_definition_revision_reject_payload_update()"
    )

    op.execute(
        """
        CREATE FUNCTION source_manifest_revision_reject_payload_update() RETURNS trigger AS $$
        BEGIN
            IF NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
               OR NEW.brand_id IS DISTINCT FROM OLD.brand_id
               OR NEW.product_id IS DISTINCT FROM OLD.product_id
               OR NEW.project_id IS DISTINCT FROM OLD.project_id
               OR NEW.icp_key IS DISTINCT FROM OLD.icp_key
               OR NEW.icp_spec_version IS DISTINCT FROM OLD.icp_spec_version
               OR NEW.source_key IS DISTINCT FROM OLD.source_key
               OR NEW.payload_hash IS DISTINCT FROM OLD.payload_hash
               OR NEW.payload_json IS DISTINCT FROM OLD.payload_json
               OR NEW.proposed_by_actor IS DISTINCT FROM OLD.proposed_by_actor
               OR NEW.proposed_by_ref IS DISTINCT FROM OLD.proposed_by_ref
               OR NEW.proposed_at IS DISTINCT FROM OLD.proposed_at
               OR NEW.required_authority IS DISTINCT FROM OLD.required_authority THEN
                RAISE EXCEPTION
                    'source proposal payload and scope are immutable; submit a new proposal';
            END IF;
            IF OLD.status <> 'proposed'
               AND (
                   NEW.status IS DISTINCT FROM OLD.status
                   OR NEW.decided_by IS DISTINCT FROM OLD.decided_by
                   OR NEW.decision_authority IS DISTINCT FROM OLD.decision_authority
                   OR NEW.decided_at IS DISTINCT FROM OLD.decided_at
                   OR NEW.decision_reason IS DISTINCT FROM OLD.decision_reason
                   OR NEW.assigned_tier IS DISTINCT FROM OLD.assigned_tier
                   OR NEW.applied_source_key IS DISTINCT FROM OLD.applied_source_key
                   OR NEW.applied_version IS DISTINCT FROM OLD.applied_version
               ) THEN
                RAISE EXCEPTION 'source proposal decision is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER source_manifest_revision_payload_immutable "
        "BEFORE UPDATE ON source_manifest_revision FOR EACH ROW "
        "EXECUTE FUNCTION source_manifest_revision_reject_payload_update()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS source_manifest_revision_payload_immutable "
        "ON source_manifest_revision"
    )
    op.execute("DROP FUNCTION IF EXISTS source_manifest_revision_reject_payload_update()")
    op.execute(
        "DROP TRIGGER IF EXISTS field_definition_revision_payload_immutable "
        "ON field_definition_revision"
    )
    op.execute("DROP FUNCTION IF EXISTS field_definition_revision_reject_payload_update()")
    op.execute("DROP TABLE source_manifest_revision")
    op.execute("DROP TABLE field_definition_revision")
    op.execute("DROP TYPE proposal_authority")
    op.execute("DROP TYPE proposal_status")
