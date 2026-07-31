"""c7_5 governed research view recheck

Revision ID: 9df19defc755
Revises: a69a1769d4bc
Create Date: 2026-07-27 19:46:11.180469+00:00

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
revision: str = "9df19defc755"
down_revision: str | None = "a69a1769d4bc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE research_view_change_report (
            report_id                      uuid PRIMARY KEY,
            operation_id                   uuid NOT NULL,
            workspace_id                   text NOT NULL REFERENCES workspace(workspace_id),
            project_id                     text NOT NULL,
            project_run_id                 uuid NOT NULL,
            subject_entity_id              uuid NOT NULL,
            subject_entity_type            entity_type NOT NULL,
            parent_account_entity_id       uuid,
            old_snapshot_id                uuid NOT NULL,
            new_snapshot_id                uuid NOT NULL,
            old_source_state_sha256         char(64) NOT NULL,
            new_source_state_sha256         char(64) NOT NULL,
            old_composition_sha256          char(64) NOT NULL,
            new_composition_sha256          char(64) NOT NULL,
            selected_section_kinds          text[] NOT NULL DEFAULT '{}',
            request_research                boolean NOT NULL,
            reason_codes                    text[] NOT NULL DEFAULT '{}',
            created_at                      timestamptz NOT NULL,

            CONSTRAINT research_view_change_report_operation_unique
                UNIQUE (workspace_id, operation_id),
            CONSTRAINT research_view_change_report_workspace_anchor
                UNIQUE (report_id, workspace_id),
            CONSTRAINT research_view_change_report_project_scope_fk
                FOREIGN KEY(project_id, workspace_id)
                REFERENCES project(project_id, workspace_id),
            CONSTRAINT research_view_change_report_run_scope_fk
                FOREIGN KEY(project_run_id, workspace_id, project_id)
                REFERENCES project_run(id, workspace_id, project_id),
            CONSTRAINT research_view_change_report_old_snapshot_fk
                FOREIGN KEY(old_snapshot_id, workspace_id)
                REFERENCES research_view_snapshot(snapshot_id, workspace_id),
            CONSTRAINT research_view_change_report_new_snapshot_fk
                FOREIGN KEY(new_snapshot_id, workspace_id)
                REFERENCES research_view_snapshot(snapshot_id, workspace_id),
            CONSTRAINT research_view_change_report_subject_parent CHECK (
                (subject_entity_type = 'account' AND parent_account_entity_id IS NULL)
                OR
                (subject_entity_type = 'contact' AND parent_account_entity_id IS NOT NULL)
            ),
            CONSTRAINT research_view_change_report_hashes CHECK (
                old_source_state_sha256 ~ '^[0-9a-f]{64}$'
                AND new_source_state_sha256 ~ '^[0-9a-f]{64}$'
                AND old_composition_sha256 ~ '^[0-9a-f]{64}$'
                AND new_composition_sha256 ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT research_view_change_report_sections CHECK (
                selected_section_kinds <@ ARRAY[
                    'identity', 'research_status', 'summary', 'about', 'fit', 'insights',
                    'committee', 'activity', 'professional_signals', 'evidence', 'quotes',
                    'background', 'career', 'education', 'publications', 'awards',
                    'personalization', 'value_narrative', 'feasibility', 'coverage_gaps'
                ]::text[]
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX research_view_change_report_scope "
        "ON research_view_change_report("
        "workspace_id, project_id, subject_entity_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX research_view_change_report_snapshot "
        "ON research_view_change_report(workspace_id, old_snapshot_id, created_at DESC)"
    )

    op.execute(
        """
        CREATE TABLE research_view_change_item (
            report_id       uuid NOT NULL REFERENCES research_view_change_report(report_id),
            item_id         text NOT NULL,
            statement_id    uuid,
            section_id      text NOT NULL,
            change_kind     text NOT NULL,

            CONSTRAINT research_view_change_item_pkey PRIMARY KEY(report_id, item_id),
            CONSTRAINT research_view_change_item_kind CHECK (
                change_kind IN ('unchanged', 'added', 'removed', 'stale', 'restricted')
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX research_view_change_item_statement "
        "ON research_view_change_item(statement_id) WHERE statement_id IS NOT NULL"
    )

    op.execute(
        """
        CREATE TABLE research_view_change_operation (
            report_id               uuid NOT NULL REFERENCES research_view_change_report(report_id),
            ordinal                 integer NOT NULL,
            requested_operation_id  uuid NOT NULL,

            CONSTRAINT research_view_change_operation_pkey PRIMARY KEY(report_id, ordinal),
            CONSTRAINT research_view_change_operation_ordinal CHECK (ordinal >= 0),
            CONSTRAINT research_view_change_operation_unique
                UNIQUE(report_id, requested_operation_id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE research_view_section_staleness (
            staleness_id      uuid PRIMARY KEY,
            operation_id      uuid NOT NULL,
            workspace_id      text NOT NULL REFERENCES workspace(workspace_id),
            snapshot_id       uuid NOT NULL,
            section_ordinal   integer NOT NULL,
            section_id        text NOT NULL,
            claim_id          uuid NOT NULL,
            reason_code       text NOT NULL,
            created_at        timestamptz NOT NULL,

            CONSTRAINT research_view_section_staleness_operation_unique
                UNIQUE (
                    workspace_id, operation_id, snapshot_id, section_ordinal, claim_id, reason_code
                ),
            CONSTRAINT research_view_section_staleness_snapshot_fk
                FOREIGN KEY(snapshot_id, workspace_id)
                REFERENCES research_view_snapshot(snapshot_id, workspace_id),
            CONSTRAINT research_view_section_staleness_section_fk
                FOREIGN KEY(snapshot_id, section_ordinal)
                REFERENCES research_view_snapshot_section(snapshot_id, ordinal),
            CONSTRAINT research_view_section_staleness_reason CHECK (
                reason_code ~ '^[a-z][a-z0-9_]{0,79}$'
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX research_view_section_staleness_claim "
        "ON research_view_section_staleness(workspace_id, claim_id, created_at DESC)"
    )

    op.execute(
        """
        CREATE TABLE research_view_event (
            event_id            uuid PRIMARY KEY,
            event_key           text NOT NULL,
            topic               text NOT NULL,
            workspace_id        text NOT NULL REFERENCES workspace(workspace_id),
            project_id          text NOT NULL,
            project_run_id      uuid NOT NULL,
            subject_entity_id   uuid NOT NULL,
            snapshot_id         uuid NOT NULL,
            report_id           uuid,
            section_ids         text[] NOT NULL DEFAULT '{}',
            item_ids            text[] NOT NULL DEFAULT '{}',
            reason_codes        text[] NOT NULL DEFAULT '{}',
            fetch_ref           text NOT NULL,
            created_at          timestamptz NOT NULL,

            CONSTRAINT research_view_event_key_unique UNIQUE(workspace_id, event_key),
            CONSTRAINT research_view_event_project_scope_fk
                FOREIGN KEY(project_id, workspace_id)
                REFERENCES project(project_id, workspace_id),
            CONSTRAINT research_view_event_run_scope_fk
                FOREIGN KEY(project_run_id, workspace_id, project_id)
                REFERENCES project_run(id, workspace_id, project_id),
            CONSTRAINT research_view_event_snapshot_fk
                FOREIGN KEY(snapshot_id, workspace_id)
                REFERENCES research_view_snapshot(snapshot_id, workspace_id),
            CONSTRAINT research_view_event_report_fk
                FOREIGN KEY(report_id, workspace_id)
                REFERENCES research_view_change_report(report_id, workspace_id),
            CONSTRAINT research_view_event_topic CHECK (
                topic IN (
                    'research_view.updated',
                    'research_view.section_stale',
                    'research_view.recheck_completed'
                )
            ),
            CONSTRAINT research_view_event_fetch_ref CHECK (
                fetch_ref !~ '[:][/][/]' AND fetch_ref !~ '^/'
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX research_view_event_scope "
        "ON research_view_event(workspace_id, project_run_id, created_at, event_id)"
    )

    for table in (
        "research_view_change_report",
        "research_view_change_item",
        "research_view_change_operation",
        "research_view_section_staleness",
        "research_view_event",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_c7_receipt_mutation()"
        )


def downgrade() -> None:
    for table in (
        "research_view_event",
        "research_view_section_staleness",
        "research_view_change_operation",
        "research_view_change_item",
        "research_view_change_report",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")

    op.execute("DROP INDEX IF EXISTS research_view_event_scope")
    op.execute("DROP TABLE IF EXISTS research_view_event")
    op.execute("DROP INDEX IF EXISTS research_view_section_staleness_claim")
    op.execute("DROP TABLE IF EXISTS research_view_section_staleness")
    op.execute("DROP TABLE IF EXISTS research_view_change_operation")
    op.execute("DROP INDEX IF EXISTS research_view_change_item_statement")
    op.execute("DROP TABLE IF EXISTS research_view_change_item")
    op.execute("DROP INDEX IF EXISTS research_view_change_report_snapshot")
    op.execute("DROP INDEX IF EXISTS research_view_change_report_scope")
    op.execute("DROP TABLE IF EXISTS research_view_change_report")
