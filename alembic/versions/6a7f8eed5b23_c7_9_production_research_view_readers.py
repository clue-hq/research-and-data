"""c7 9 production research view readers

Revision ID: 6a7f8eed5b23
Revises: 677607ec1cd1
Create Date: 2026-07-30 13:24:17.068242+00:00

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
revision: str = "6a7f8eed5b23"
down_revision: str | None = "677607ec1cd1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A C7 subject version participates in statement/view identity.  The previous hard-coded
    # version=1 made an identity merge or canonical correction invisible to saved-view hashes.
    op.execute("ALTER TABLE account_entity ADD COLUMN canonical_version integer NOT NULL DEFAULT 1")
    op.execute(
        "ALTER TABLE account_entity ADD CONSTRAINT account_entity_canonical_version_positive "
        "CHECK (canonical_version >= 1)"
    )
    op.execute("ALTER TABLE contact_entity ADD COLUMN canonical_version integer NOT NULL DEFAULT 1")
    op.execute(
        "ALTER TABLE contact_entity ADD CONSTRAINT contact_entity_canonical_version_positive "
        "CHECK (canonical_version >= 1)"
    )
    op.execute(
        """
        CREATE FUNCTION bump_account_entity_canonical_version()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF ROW(
                NEW.canonical_name, NEW.primary_domain, NEW.aliases, NEW.hq_geo,
                NEW.registry_ids, NEW.status, NEW.merged_into
            ) IS DISTINCT FROM ROW(
                OLD.canonical_name, OLD.primary_domain, OLD.aliases, OLD.hq_geo,
                OLD.registry_ids, OLD.status, OLD.merged_into
            ) THEN
                NEW.canonical_version := OLD.canonical_version + 1;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER account_entity_bump_canonical_version
        BEFORE UPDATE ON account_entity
        FOR EACH ROW EXECUTE FUNCTION bump_account_entity_canonical_version()
        """
    )
    op.execute(
        """
        CREATE FUNCTION bump_contact_entity_canonical_version()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF ROW(
                NEW.account_entity_id, NEW.full_name, NEW.linkedin_url, NEW.verified_email,
                NEW.aliases, NEW.geo, NEW.jurisdiction, NEW.status, NEW.merged_into
            ) IS DISTINCT FROM ROW(
                OLD.account_entity_id, OLD.full_name, OLD.linkedin_url, OLD.verified_email,
                OLD.aliases, OLD.geo, OLD.jurisdiction, OLD.status, OLD.merged_into
            ) THEN
                NEW.canonical_version := OLD.canonical_version + 1;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER contact_entity_bump_canonical_version
        BEFORE UPDATE ON contact_entity
        FOR EACH ROW EXECUTE FUNCTION bump_contact_entity_canonical_version()
        """
    )

    # Field-to-section placement is registered projection metadata.  Readers never infer a
    # frontend section from a field prefix or from generated prose.
    op.execute(
        """
        CREATE TABLE research_view_field_route (
            route_id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            field_key            text NOT NULL
                                 REFERENCES field_definition(field_key) ON DELETE CASCADE,
            entity_type          entity_type NOT NULL,
            view_schema_version  text NOT NULL DEFAULT '1.0',
            section_kind         text NOT NULL,
            purpose              text NOT NULL DEFAULT 'display',
            context_scope        text NOT NULL DEFAULT 'subject_current',
            product_mode         text NOT NULL DEFAULT 'neutral_or_exact',
            ordinal              integer NOT NULL DEFAULT 0,
            route_version        integer NOT NULL DEFAULT 1,
            active               boolean NOT NULL DEFAULT true,
            created_at           timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT research_view_field_route_section CHECK (
                section_kind IN (
                    'summary', 'about', 'insights', 'professional_signals', 'evidence',
                    'quotes', 'background', 'career', 'education', 'publications', 'awards',
                    'personalization', 'value_narrative'
                )
            ),
            CONSTRAINT research_view_field_route_purpose CHECK (
                purpose IN ('display', 'personalization_candidate')
            ),
            CONSTRAINT research_view_field_route_context CHECK (
                context_scope IN ('subject_current', 'project_run_pinned')
            ),
            CONSTRAINT research_view_field_route_product CHECK (
                product_mode IN ('neutral_or_exact', 'exact_required', 'neutral_only')
            ),
            CONSTRAINT research_view_field_route_ordinal CHECK (ordinal >= 0),
            CONSTRAINT research_view_field_route_version CHECK (route_version >= 1),
            CONSTRAINT research_view_field_route_personalization CHECK (
                (purpose = 'personalization_candidate') = (section_kind = 'personalization')
                AND (
                    purpose <> 'personalization_candidate'
                    OR field_key LIKE 'contact.personalization.%'
                )
            )
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX research_view_field_route_active_display
        ON research_view_field_route(field_key, entity_type, view_schema_version)
        WHERE active AND purpose = 'display'
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX research_view_field_route_active_personalization
        ON research_view_field_route(field_key, entity_type, view_schema_version)
        WHERE active AND purpose = 'personalization_candidate'
        """
    )
    op.execute(
        """
        CREATE INDEX research_view_field_route_lookup
        ON research_view_field_route(entity_type, view_schema_version, active, ordinal, field_key)
        """
    )

    # Reference-only, exact-subject research/execution activity.  It deliberately stores no event
    # prose, claim body, evidence span, source URL, or provider payload.
    op.execute(
        """
        CREATE TABLE research_subject_activity (
            activity_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id         text NOT NULL,
            project_id           text NOT NULL,
            project_run_id       uuid NOT NULL REFERENCES project_run(id) ON DELETE CASCADE,
            account_run_id       uuid NOT NULL REFERENCES account_run(id) ON DELETE CASCADE,
            subject_entity_id    uuid NOT NULL,
            subject_entity_type  entity_type NOT NULL,
            product_id           text,
            owner_event_ref      text NOT NULL,
            event_kind           text NOT NULL,
            actor_category       text,
            occurred_at          timestamptz NOT NULL,
            created_at           timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT research_subject_activity_owner_unique
                UNIQUE (workspace_id, owner_event_ref, subject_entity_id),
            CONSTRAINT research_subject_activity_actor_category CHECK (
                actor_category IS NULL
                OR actor_category IN ('human', 'agent', 'system', 'worker')
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX research_subject_activity_scope
        ON research_subject_activity(
            workspace_id, project_id, project_run_id, account_run_id,
            subject_entity_type, subject_entity_id, product_id, occurred_at DESC, activity_id DESC
        )
        """
    )
    op.execute(
        """
        CREATE INDEX account_run_project_entity_lookup
        ON account_run(project_run_id, entity_id, id)
        """
    )

    # Display safety is an independent, versioned arm of the existing workspace policy.  Outreach
    # use decisions remain unchanged and cannot be mistaken for display permission.
    op.execute(
        "ALTER TABLE workspace_policy "
        "ADD COLUMN display_professional_public boolean NOT NULL DEFAULT true"
    )
    op.execute(
        "ALTER TABLE workspace_policy "
        "ADD COLUMN display_personal_public_non_sensitive boolean NOT NULL DEFAULT true"
    )
    op.execute(
        "ALTER TABLE workspace_policy ADD COLUMN display_sensitive boolean NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE workspace_policy "
        "ADD COLUMN display_requires_strong_contact_binding boolean NOT NULL DEFAULT true"
    )

    # Recheck/status attribution must stay in the same product scope as the old/new snapshots.
    op.execute("ALTER TABLE research_view_change_report ADD COLUMN product_id text")
    op.execute(
        """
        UPDATE research_view_change_report report
        SET product_id = snapshot.product_id
        FROM research_view_snapshot snapshot
        WHERE snapshot.snapshot_id = report.old_snapshot_id
          AND snapshot.workspace_id = report.workspace_id
        """
    )
    op.execute(
        """
        CREATE INDEX research_view_change_report_product_scope
        ON research_view_change_report(
            workspace_id, project_id, subject_entity_id, product_id, created_at DESC
        )
        """
    )

    # The legacy compatibility projection is still reachable during the C7 cutover.  Its natural
    # key must not let product B overwrite product A for the same account/ICP.
    op.execute("ALTER TABLE account_handoff ADD COLUMN product_id text NOT NULL DEFAULT ''")
    op.execute(
        """
        UPDATE account_handoff
        SET product_id = COALESCE(payload #>> '{handoff,product_id}', '')
        WHERE payload IS NOT NULL
        """
    )
    op.execute("DROP INDEX IF EXISTS account_handoff_scope")
    op.execute(
        """
        CREATE UNIQUE INDEX account_handoff_scope
        ON account_handoff(
            workspace_id, account_entity_id, icp_spec_version, icp_key, product_id
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS account_handoff_scope")
    # Downgrading removes product from the legacy cache key.  If C7.9 produced more than one
    # product-scoped projection for the same pre-C7 slot, retain the newest rebuildable cache row
    # and merge its exact subject-reachability references before restoring the old unique index.
    op.execute(
        """
        CREATE TEMP TABLE c79_handoff_downgrade_duplicates ON COMMIT DROP AS
        WITH ranked AS (
            SELECT
                id,
                first_value(id) OVER (
                    PARTITION BY workspace_id, account_entity_id, icp_spec_version, icp_key
                    ORDER BY assembled_at DESC, created_at DESC, id DESC
                ) AS retained_id,
                row_number() OVER (
                    PARTITION BY workspace_id, account_entity_id, icp_spec_version, icp_key
                    ORDER BY assembled_at DESC, created_at DESC, id DESC
                ) AS position
            FROM account_handoff
        )
        SELECT id AS duplicate_id, retained_id
        FROM ranked
        WHERE position > 1
        """
    )
    op.execute(
        """
        INSERT INTO account_handoff_subject (
            account_handoff_id,
            subject_entity_id,
            subject_entity_type,
            parent_account_entity_id,
            relation
        )
        SELECT
            duplicate.retained_id,
            subject.subject_entity_id,
            subject.subject_entity_type,
            subject.parent_account_entity_id,
            subject.relation
        FROM c79_handoff_downgrade_duplicates duplicate
        JOIN account_handoff_subject subject
          ON subject.account_handoff_id = duplicate.duplicate_id
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        DELETE FROM account_handoff_subject subject
        USING c79_handoff_downgrade_duplicates duplicate
        WHERE subject.account_handoff_id = duplicate.duplicate_id
        """
    )
    op.execute(
        """
        DELETE FROM account_handoff handoff
        USING c79_handoff_downgrade_duplicates duplicate
        WHERE handoff.id = duplicate.duplicate_id
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX account_handoff_scope
        ON account_handoff(workspace_id, account_entity_id, icp_spec_version, icp_key)
        """
    )
    op.execute("ALTER TABLE account_handoff DROP COLUMN product_id")

    op.execute("DROP INDEX IF EXISTS research_view_change_report_product_scope")
    op.execute("ALTER TABLE research_view_change_report DROP COLUMN product_id")

    op.execute("ALTER TABLE workspace_policy DROP COLUMN display_requires_strong_contact_binding")
    op.execute("ALTER TABLE workspace_policy DROP COLUMN display_sensitive")
    op.execute("ALTER TABLE workspace_policy DROP COLUMN display_personal_public_non_sensitive")
    op.execute("ALTER TABLE workspace_policy DROP COLUMN display_professional_public")

    op.execute("DROP TABLE research_subject_activity")
    op.execute("DROP INDEX IF EXISTS account_run_project_entity_lookup")
    op.execute("DROP TABLE research_view_field_route")

    op.execute("DROP TRIGGER contact_entity_bump_canonical_version ON contact_entity")
    op.execute("DROP FUNCTION bump_contact_entity_canonical_version()")
    op.execute("DROP TRIGGER account_entity_bump_canonical_version ON account_entity")
    op.execute("DROP FUNCTION bump_account_entity_canonical_version()")
    op.execute(
        "ALTER TABLE contact_entity DROP CONSTRAINT contact_entity_canonical_version_positive"
    )
    op.execute("ALTER TABLE contact_entity DROP COLUMN canonical_version")
    op.execute(
        "ALTER TABLE account_entity DROP CONSTRAINT account_entity_canonical_version_positive"
    )
    op.execute("ALTER TABLE account_entity DROP COLUMN canonical_version")
