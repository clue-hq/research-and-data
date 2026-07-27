"""C7.4 reference-only research-view receipts and evidence-access audit.

Revision ID: a69a1769d4bc
Revises: 0ac041814c56
Create Date: 2026-07-27 19:10:45.253750+00:00

The saved research view is deliberately a receipt, not a frozen dossier.  These tables contain
only scope pins, canonical subject references, ordering, bounded state enums, hashes, and claim /
owner references.  They contain no research value, evidence span, source locator, object key,
signed URL, rationale, or rendered body.  Snapshot resolution must re-read the referenced
authorities under current retention, erasure, and display policy.

The legacy ``account_handoff.payload`` remains a bounded compatibility surface until C7.6/C7.7
cut readers over.  C7.4 makes it nullable, adds an exact subject reachability index, and records a
one-way purge marker so DSAR can remove copied personal bodies without deleting row identity.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a69a1769d4bc"
down_revision: str | None = "0ac041814c56"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_RECEIPT_TABLES = (
    "research_view_snapshot",
    "research_view_snapshot_section",
    "research_view_snapshot_item",
    "research_view_snapshot_support",
    "research_view_snapshot_evidence_action",
    "research_view_snapshot_subject",
    "evidence_access_audit",
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE research_view_snapshot (
            snapshot_id               uuid PRIMARY KEY,
            operation_id              uuid NOT NULL,
            workspace_id              text NOT NULL REFERENCES workspace(workspace_id),
            project_id                text NOT NULL,
            project_run_id            uuid NOT NULL,
            view_id                   uuid NOT NULL,
            subject_entity_id         uuid NOT NULL,
            subject_entity_type       entity_type NOT NULL,
            subject_entity_version    integer NOT NULL,
            parent_account_entity_id  uuid,
            product_id                text,
            schema_version            text NOT NULL,
            source_state_sha256       char(64) NOT NULL,
            composition_sha256        char(64) NOT NULL,
            supersedes_snapshot_id    uuid,
            created_at                timestamptz NOT NULL,

            CONSTRAINT research_view_snapshot_operation_unique
                UNIQUE (workspace_id, operation_id),
            CONSTRAINT research_view_snapshot_workspace_anchor
                UNIQUE (snapshot_id, workspace_id),
            CONSTRAINT research_view_snapshot_supersedes_scope_fk
                FOREIGN KEY(supersedes_snapshot_id, workspace_id)
                REFERENCES research_view_snapshot(snapshot_id, workspace_id),
            CONSTRAINT research_view_snapshot_project_scope_fk
                FOREIGN KEY(project_id, workspace_id)
                REFERENCES project(project_id, workspace_id),
            CONSTRAINT research_view_snapshot_run_scope_fk
                FOREIGN KEY(project_run_id, workspace_id, project_id)
                REFERENCES project_run(id, workspace_id, project_id),
            CONSTRAINT research_view_snapshot_product_scope_fk
                FOREIGN KEY(product_id, workspace_id)
                REFERENCES product(product_id, workspace_id),
            CONSTRAINT research_view_snapshot_subject_version_positive
                CHECK (subject_entity_version >= 1),
            CONSTRAINT research_view_snapshot_schema_version
                CHECK (schema_version = '1.0'),
            CONSTRAINT research_view_snapshot_subject_parent
                CHECK (
                    (subject_entity_type = 'account' AND parent_account_entity_id IS NULL)
                    OR
                    (subject_entity_type = 'contact' AND parent_account_entity_id IS NOT NULL)
                ),
            CONSTRAINT research_view_snapshot_source_hash
                CHECK (source_state_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT research_view_snapshot_composition_hash
                CHECK (composition_sha256 ~ '^[0-9a-f]{64}$')
        )
        """
    )
    op.execute(
        "CREATE INDEX research_view_snapshot_scope "
        "ON research_view_snapshot(workspace_id, project_id, subject_entity_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX research_view_snapshot_run "
        "ON research_view_snapshot(workspace_id, project_run_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX research_view_snapshot_product "
        "ON research_view_snapshot(workspace_id, product_id) WHERE product_id IS NOT NULL"
    )

    op.execute(
        """
        CREATE TABLE research_view_snapshot_section (
            snapshot_id    uuid NOT NULL REFERENCES research_view_snapshot(snapshot_id),
            ordinal        integer NOT NULL,
            section_id     text NOT NULL,
            section_kind   text NOT NULL,
            block_kind     text,
            availability   text NOT NULL,
            reason_codes   text[] NOT NULL DEFAULT '{}',

            CONSTRAINT research_view_snapshot_section_pkey PRIMARY KEY(snapshot_id, ordinal),
            CONSTRAINT research_view_snapshot_section_ordinal CHECK (ordinal >= 0),
            CONSTRAINT research_view_snapshot_section_id_unique UNIQUE(snapshot_id, section_id),
            CONSTRAINT research_view_snapshot_section_kind CHECK (
                section_kind IN (
                    'identity', 'research_status', 'summary', 'about', 'fit', 'insights',
                    'committee', 'activity', 'professional_signals', 'evidence', 'quotes',
                    'background', 'career', 'education', 'publications', 'awards',
                    'personalization', 'value_narrative', 'feasibility', 'coverage_gaps'
                )
            ),
            CONSTRAINT research_view_snapshot_section_block CHECK (
                block_kind IS NULL OR block_kind IN (
                    'executive_summary', 'company_profile', 'fit_assessment', 'signal',
                    'committee_member', 'personalization', 'value_narrative', 'feasibility',
                    'coverage_gap'
                )
            ),
            CONSTRAINT research_view_snapshot_section_availability CHECK (
                availability IN ('available', 'unknown', 'unavailable', 'redacted', 'restricted')
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE research_view_snapshot_item (
            snapshot_id              uuid NOT NULL REFERENCES research_view_snapshot(snapshot_id),
            section_ordinal          integer NOT NULL,
            ordinal                  integer NOT NULL,
            item_id                  text NOT NULL,
            item_kind                text NOT NULL,
            statement_id             uuid,
            claim_id                 uuid,
            statement_kind           text,
            field_key                text,
            owner_ref                text,
            data_species             text,
            relation                 text,
            item_subject_entity_id   uuid NOT NULL,
            item_subject_entity_type entity_type NOT NULL,
            item_subject_version     integer NOT NULL,
            item_parent_account_id   uuid,
            item_product_id          text,
            availability             text,
            verification             verification_status,
            freshness                text,
            conflict_state           text,
            display_decision         text,
            outreach_decision        text,
            identity_binding         identity_binding,
            use_class                use_class,
            selection_reason_code    text,
            reason_codes             text[] NOT NULL DEFAULT '{}',

            CONSTRAINT research_view_snapshot_item_pkey
                PRIMARY KEY(snapshot_id, section_ordinal, ordinal),
            CONSTRAINT research_view_snapshot_item_section_fk
                FOREIGN KEY(snapshot_id, section_ordinal)
                REFERENCES research_view_snapshot_section(snapshot_id, ordinal),
            CONSTRAINT research_view_snapshot_item_ordinal CHECK (ordinal >= 0),
            CONSTRAINT research_view_snapshot_item_subject_version
                CHECK (item_subject_version >= 1),
            CONSTRAINT research_view_snapshot_item_kind
                CHECK (item_kind IN ('statement', 'reference', 'personalization')),
            CONSTRAINT research_view_snapshot_item_statement_kind
                CHECK (statement_kind IS NULL OR statement_kind IN ('direct', 'derived')),
            CONSTRAINT research_view_snapshot_item_species CHECK (
                data_species IS NULL OR data_species IN (
                    'identity', 'execution', 'score', 'claim_derivation', 'committee',
                    'coverage', 'activity'
                )
            ),
            CONSTRAINT research_view_snapshot_item_relation CHECK (
                relation IS NULL OR relation IN ('subject', 'parent_account', 'committee_member')
            ),
            CONSTRAINT research_view_snapshot_item_availability CHECK (
                availability IS NULL OR availability IN (
                    'available', 'unknown', 'unavailable', 'redacted', 'restricted'
                )
            ),
            CONSTRAINT research_view_snapshot_item_freshness CHECK (
                freshness IS NULL OR freshness IN ('fresh', 'stale', 'expired')
            ),
            CONSTRAINT research_view_snapshot_item_conflict CHECK (
                conflict_state IS NULL OR conflict_state IN ('none', 'review_required')
            ),
            CONSTRAINT research_view_snapshot_item_display CHECK (
                display_decision IS NULL OR display_decision IN (
                    'allowed', 'denied', 'not_applicable'
                )
            ),
            CONSTRAINT research_view_snapshot_item_outreach CHECK (
                outreach_decision IS NULL OR outreach_decision IN (
                    'allowed', 'denied', 'not_applicable'
                )
            ),
            CONSTRAINT research_view_snapshot_item_shape CHECK (
                (
                    item_kind IN ('statement', 'personalization')
                    AND statement_id IS NOT NULL
                    AND claim_id IS NOT NULL
                    AND statement_kind IS NOT NULL
                    AND field_key IS NOT NULL
                    AND owner_ref IS NULL
                    AND data_species IS NULL
                    AND relation IS NULL
                    AND availability IS NOT NULL
                    AND verification IS NOT NULL
                    AND freshness IS NOT NULL
                    AND conflict_state IS NOT NULL
                    AND display_decision IS NOT NULL
                    AND outreach_decision IS NOT NULL
                    AND (
                        (item_kind = 'personalization' AND selection_reason_code IS NOT NULL)
                        OR
                        (item_kind = 'statement' AND selection_reason_code IS NULL)
                    )
                )
                OR
                (
                    item_kind = 'reference'
                    AND statement_id IS NULL
                    AND claim_id IS NULL
                    AND statement_kind IS NULL
                    AND field_key IS NULL
                    AND owner_ref IS NOT NULL
                    AND data_species IS NOT NULL
                    AND relation IS NOT NULL
                    AND availability IS NULL
                    AND verification IS NULL
                    AND freshness IS NULL
                    AND conflict_state IS NULL
                    AND display_decision IS NULL
                    AND outreach_decision IS NULL
                    AND identity_binding IS NULL
                    AND use_class IS NULL
                    AND selection_reason_code IS NULL
                )
            ),
            CONSTRAINT research_view_snapshot_item_subject_parent CHECK (
                (item_subject_entity_type = 'account' AND item_parent_account_id IS NULL)
                OR
                (item_subject_entity_type = 'contact' AND item_parent_account_id IS NOT NULL)
            ),
            CONSTRAINT research_view_snapshot_item_id_unique UNIQUE(snapshot_id, item_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX research_view_snapshot_item_claim "
        "ON research_view_snapshot_item(claim_id) WHERE claim_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX research_view_snapshot_item_statement "
        "ON research_view_snapshot_item(statement_id) WHERE statement_id IS NOT NULL"
    )

    op.execute(
        """
        CREATE TABLE research_view_snapshot_support (
            snapshot_id       uuid NOT NULL,
            section_ordinal   integer NOT NULL,
            item_ordinal      integer NOT NULL,
            ordinal           integer NOT NULL,
            claim_id          uuid NOT NULL,
            reference_kind    text NOT NULL,
            support_role      text,
            required          boolean NOT NULL,

            CONSTRAINT research_view_snapshot_support_pkey
                PRIMARY KEY(snapshot_id, section_ordinal, item_ordinal, ordinal),
            CONSTRAINT research_view_snapshot_support_item_fk
                FOREIGN KEY(snapshot_id, section_ordinal, item_ordinal)
                REFERENCES research_view_snapshot_item(snapshot_id, section_ordinal, ordinal),
            CONSTRAINT research_view_snapshot_support_ordinal CHECK (ordinal >= 0),
            CONSTRAINT research_view_snapshot_support_shape CHECK (
                (
                    reference_kind = 'derived_support'
                    AND support_role IN (
                        'direct_evidence', 'corroboration', 'account_signal',
                        'employer_context', 'client_capability'
                    )
                )
                OR
                (reference_kind = 'owner_evidence' AND support_role IS NULL)
            ),
            CONSTRAINT research_view_snapshot_support_claim_unique
                UNIQUE(snapshot_id, section_ordinal, item_ordinal, claim_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX research_view_snapshot_support_claim "
        "ON research_view_snapshot_support(claim_id)"
    )

    op.execute(
        """
        CREATE TABLE research_view_snapshot_evidence_action (
            snapshot_id       uuid NOT NULL,
            section_ordinal   integer NOT NULL,
            item_ordinal      integer NOT NULL,
            ordinal           integer NOT NULL,
            action_id         uuid NOT NULL,
            statement_id      uuid NOT NULL,
            claim_id          uuid NOT NULL,
            action_kind       text NOT NULL,
            provider_label    text,
            media_type        text,

            CONSTRAINT research_view_snapshot_evidence_action_pkey
                PRIMARY KEY(snapshot_id, section_ordinal, item_ordinal, ordinal),
            CONSTRAINT research_view_snapshot_evidence_action_item_fk
                FOREIGN KEY(snapshot_id, section_ordinal, item_ordinal)
                REFERENCES research_view_snapshot_item(snapshot_id, section_ordinal, ordinal),
            CONSTRAINT research_view_snapshot_evidence_action_ordinal CHECK (ordinal >= 0),
            CONSTRAINT research_view_snapshot_evidence_action_id_unique
                UNIQUE(snapshot_id, action_id),
            CONSTRAINT research_view_snapshot_evidence_action_kind CHECK (
                action_kind IN (
                    'open_public_source', 'view_api_provenance', 'request_artifact_preview'
                )
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX research_view_snapshot_evidence_action_lookup "
        "ON research_view_snapshot_evidence_action(action_id, claim_id, statement_id)"
    )

    op.execute(
        """
        CREATE TABLE research_view_snapshot_subject (
            snapshot_id               uuid NOT NULL REFERENCES research_view_snapshot(snapshot_id),
            subject_entity_id         uuid NOT NULL,
            subject_entity_type       entity_type NOT NULL,
            parent_account_entity_id  uuid,
            relation                  text NOT NULL,

            CONSTRAINT research_view_snapshot_subject_pkey
                PRIMARY KEY(snapshot_id, subject_entity_id, relation),
            CONSTRAINT research_view_snapshot_subject_parent CHECK (
                (subject_entity_type = 'account' AND parent_account_entity_id IS NULL)
                OR
                (subject_entity_type = 'contact' AND parent_account_entity_id IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX research_view_snapshot_subject_reachable "
        "ON research_view_snapshot_subject(subject_entity_id, snapshot_id)"
    )

    op.execute(
        """
        CREATE TABLE evidence_access_audit (
            audit_id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id       text NOT NULL REFERENCES workspace(workspace_id),
            project_id         text NOT NULL REFERENCES project(project_id),
            actor_id           text NOT NULL,
            subject_entity_id  uuid NOT NULL,
            statement_id       uuid NOT NULL,
            claim_id           uuid NOT NULL,
            action_id          uuid NOT NULL,
            requested_action   text NOT NULL,
            outcome_action     text NOT NULL,
            allowed            boolean NOT NULL,
            reason_codes       text[] NOT NULL,
            created_at         timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT evidence_access_audit_reasons_nonempty
                CHECK (cardinality(reason_codes) BETWEEN 1 AND 8),
            CONSTRAINT evidence_access_audit_requested_action CHECK (
                requested_action IN (
                    'open_public_source', 'view_api_provenance', 'request_artifact_preview'
                )
            ),
            CONSTRAINT evidence_access_audit_outcome_action CHECK (
                outcome_action IN (
                    'open_public_source', 'view_api_provenance', 'request_artifact_preview',
                    'unavailable', 'redacted'
                )
            ),
            CONSTRAINT evidence_access_audit_coherent CHECK (
                (allowed AND outcome_action = requested_action)
                OR
                (NOT allowed AND outcome_action IN ('unavailable', 'redacted'))
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX evidence_access_audit_scope "
        "ON evidence_access_audit(workspace_id, project_id, actor_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX evidence_access_audit_claim "
        "ON evidence_access_audit(claim_id, created_at DESC)"
    )

    # Legacy compatibility: retain the row and its version/current-pointer identity while allowing
    # compliance to purge the copied JSON body.  New C7 receipts can be linked during the C7.6
    # consumer cutover; until then the subject index gives DSAR an exact reachability path.
    op.execute("ALTER TABLE account_handoff ALTER COLUMN payload DROP NOT NULL")
    op.execute(
        "ALTER TABLE account_handoff "
        "ADD COLUMN research_view_snapshot_id uuid "
        "REFERENCES research_view_snapshot(snapshot_id)"
    )
    op.execute("ALTER TABLE account_handoff ADD COLUMN legacy_payload_purged_at timestamptz")
    op.execute(
        """
        CREATE TABLE account_handoff_subject (
            account_handoff_id         uuid NOT NULL REFERENCES account_handoff(id),
            subject_entity_id          uuid NOT NULL,
            subject_entity_type        entity_type NOT NULL,
            parent_account_entity_id   uuid,
            relation                   text NOT NULL,

            CONSTRAINT account_handoff_subject_pkey
                PRIMARY KEY(account_handoff_id, subject_entity_id, relation),
            CONSTRAINT account_handoff_subject_parent CHECK (
                (subject_entity_type = 'account' AND parent_account_entity_id IS NULL)
                OR
                (subject_entity_type = 'contact' AND parent_account_entity_id IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX account_handoff_subject_reachable "
        "ON account_handoff_subject(subject_entity_id, account_handoff_id)"
    )
    # Backfill every pre-C7 legacy row before DSAR relies on the index. Account identity,
    # committee contacts, and every claim referenced by the handoff provenance index are reachable.
    op.execute(
        """
        INSERT INTO account_handoff_subject (
            account_handoff_id, subject_entity_id, subject_entity_type,
            parent_account_entity_id, relation
        )
        SELECT id, account_entity_id, 'account', NULL, 'view_subject'
        FROM account_handoff
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO account_handoff_subject (
            account_handoff_id, subject_entity_id, subject_entity_type,
            parent_account_entity_id, relation
        )
        SELECT h.id, c.id, 'contact', c.account_entity_id, 'committee_member'
        FROM account_handoff h
        CROSS JOIN LATERAL jsonb_array_elements(
            COALESCE(h.payload #> '{handoff,committee}', '[]'::jsonb)
        ) AS members(member)
        JOIN contact_entity c ON c.id::text = member->>'contact_entity_id'
        WHERE c.workspace_id = h.workspace_id
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO account_handoff_subject (
            account_handoff_id, subject_entity_id, subject_entity_type,
            parent_account_entity_id, relation
        )
        SELECT DISTINCT h.id, c.entity_id, c.entity_type,
               ce.account_entity_id, 'claim_reachable'
        FROM account_handoff h
        CROSS JOIN LATERAL jsonb_object_keys(
            COALESCE(h.payload #> '{handoff,provenance_index}', '{}'::jsonb)
        ) AS refs(claim_ref)
        JOIN claim c ON c.id::text = claim_ref
        LEFT JOIN contact_entity ce
          ON c.entity_type = 'contact' AND ce.id = c.entity_id
        LEFT JOIN account_entity ae
          ON c.entity_type = 'account' AND ae.id = c.entity_id
        WHERE (
                c.reuse_scope = 'public_footprint'
                OR c.workspace_id = h.workspace_id
              )
          AND (
                (c.entity_type = 'contact' AND ce.workspace_id = h.workspace_id)
                OR
                (c.entity_type = 'account' AND ae.workspace_id = h.workspace_id)
              )
        ON CONFLICT DO NOTHING
        """
    )

    # Receipts and audits are append-only. Runtime correction is a new superseding snapshot.
    op.execute(
        """
        CREATE FUNCTION reject_c7_receipt_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'C7 research-view receipts and evidence audits are append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in _RECEIPT_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_c7_receipt_mutation()"
        )


def downgrade() -> None:
    for table in reversed(_RECEIPT_TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS reject_c7_receipt_mutation()")

    op.execute("DROP INDEX IF EXISTS account_handoff_subject_reachable")
    op.execute("DROP TABLE IF EXISTS account_handoff_subject")
    # A purged legacy projection has no body that can be restored. account_handoff is a rebuildable
    # read projection (claims remain authoritative), so downgrade removes only those already-empty
    # cache rows before restoring the pre-C7 NOT NULL contract.
    op.execute("DELETE FROM account_handoff WHERE payload IS NULL")
    op.execute("ALTER TABLE account_handoff DROP COLUMN IF EXISTS legacy_payload_purged_at")
    op.execute("ALTER TABLE account_handoff DROP COLUMN IF EXISTS research_view_snapshot_id")
    op.execute("ALTER TABLE account_handoff ALTER COLUMN payload SET NOT NULL")

    op.execute("DROP INDEX IF EXISTS evidence_access_audit_claim")
    op.execute("DROP INDEX IF EXISTS evidence_access_audit_scope")
    op.execute("DROP TABLE IF EXISTS evidence_access_audit")
    op.execute("DROP INDEX IF EXISTS research_view_snapshot_subject_reachable")
    op.execute("DROP TABLE IF EXISTS research_view_snapshot_subject")
    op.execute("DROP INDEX IF EXISTS research_view_snapshot_evidence_action_lookup")
    op.execute("DROP TABLE IF EXISTS research_view_snapshot_evidence_action")
    op.execute("DROP INDEX IF EXISTS research_view_snapshot_support_claim")
    op.execute("DROP TABLE IF EXISTS research_view_snapshot_support")
    op.execute("DROP INDEX IF EXISTS research_view_snapshot_item_statement")
    op.execute("DROP INDEX IF EXISTS research_view_snapshot_item_claim")
    op.execute("DROP TABLE IF EXISTS research_view_snapshot_item")
    op.execute("DROP TABLE IF EXISTS research_view_snapshot_section")
    op.execute("DROP INDEX IF EXISTS research_view_snapshot_product")
    op.execute("DROP INDEX IF EXISTS research_view_snapshot_run")
    op.execute("DROP INDEX IF EXISTS research_view_snapshot_scope")
    op.execute("DROP TABLE IF EXISTS research_view_snapshot")
