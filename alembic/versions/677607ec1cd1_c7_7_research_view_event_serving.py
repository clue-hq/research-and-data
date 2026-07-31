"""c7_7 research view event serving

Revision ID: 677607ec1cd1
Revises: 9df19defc755
Create Date: 2026-07-28 14:44:10.976191+00:00

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
revision: str = "677607ec1cd1"
down_revision: str | None = "9df19defc755"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Central aggregation: every accepted C7 event becomes an SSE run-event in the same database
    # transaction.  The trigger owns the payload shape so a caller cannot accidentally add claim
    # values, evidence spans, source locators, or rendered prose.
    op.execute(
        """
        CREATE FUNCTION publish_research_view_event_to_run_outbox()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            event_payload jsonb;
            legacy_topic text;
        BEGIN
            event_payload := jsonb_build_object(
                'source_event_id', NEW.event_id,
                'canonical_topic', NEW.topic,
                'project_id', NEW.project_id,
                'project_run_id', NEW.project_run_id,
                'subject_entity_id', NEW.subject_entity_id,
                'snapshot_id', NEW.snapshot_id,
                'report_id', NEW.report_id,
                'section_ids', to_jsonb(NEW.section_ids),
                'item_ids', to_jsonb(NEW.item_ids),
                'reason_codes', to_jsonb(NEW.reason_codes),
                'fetch_ref', NEW.fetch_ref
            );

            INSERT INTO run_event (workspace_id, run_id, topic, payload, created_at)
            VALUES (
                NEW.workspace_id, NEW.project_run_id, NEW.topic, event_payload, NEW.created_at
            );

            legacy_topic := CASE NEW.topic
                WHEN 'research_view.updated' THEN 'dossier.updated'
                WHEN 'research_view.section_stale' THEN 'dossier.section.stale'
                ELSE NULL
            END;
            IF legacy_topic IS NOT NULL THEN
                INSERT INTO run_event (workspace_id, run_id, topic, payload, created_at)
                VALUES (
                    NEW.workspace_id,
                    NEW.project_run_id,
                    legacy_topic,
                    event_payload || jsonb_build_object('deprecated_alias', true),
                    NEW.created_at
                );
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER research_view_event_publish_to_run_outbox
        AFTER INSERT ON research_view_event
        FOR EACH ROW EXECUTE FUNCTION publish_research_view_event_to_run_outbox()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS research_view_event_publish_to_run_outbox ON research_view_event"
    )
    op.execute("DROP FUNCTION IF EXISTS publish_research_view_event_to_run_outbox()")
