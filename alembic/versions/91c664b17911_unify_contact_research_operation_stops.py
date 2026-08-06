"""Unify contact-research operation cancellation, objection, and erasure controls.

Revision ID: 91c664b17911
Revises: 4d9b02f218dc
Create Date: 2026-08-05 15:16:32.576315+00:00

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
revision: str = "91c664b17911"
down_revision: str | None = "4d9b02f218dc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # C4 originally content-addressed the selection only inside an opaque fingerprint. Persist
    # exact selection lineage on new contact operations so cancellation can stop them directly.
    # NOT VALID preserves historical C4 rows while enforcing the check for every new row.
    op.execute(
        "ALTER TABLE external_research_operation "
        "ADD COLUMN contact_selection_id uuid, "
        "ADD COLUMN contact_selection_sha256 text, "
        "ADD COLUMN contact_intent_sha256 text"
    )
    op.execute(
        "ALTER TABLE external_research_operation ADD CONSTRAINT "
        "external_research_contact_selection_fk FOREIGN KEY "
        "(contact_selection_id, workspace_id) REFERENCES "
        "contact_research_selection (id, workspace_id)"
    )
    op.execute(
        "ALTER TABLE external_research_operation ADD CONSTRAINT "
        "external_research_contact_authority_shape CHECK ((subject_kind='account' "
        "AND contact_selection_id IS NULL AND contact_selection_sha256 IS NULL "
        "AND contact_intent_sha256 IS NULL) OR (subject_kind='contact' AND (("
        "contact_selection_id IS NULL AND contact_selection_sha256 IS NULL "
        "AND contact_intent_sha256 IS NULL) OR (contact_selection_id IS NOT NULL "
        "AND contact_selection_sha256 ~ '^[0-9a-f]{64}$' "
        "AND contact_intent_sha256 ~ '^[0-9a-f]{64}$')))) NOT VALID"
    )
    op.execute(
        """
        CREATE FUNCTION external_research_contact_authority_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND OLD.contact_selection_id IS NOT NULL
               AND (
                NEW.contact_selection_id IS DISTINCT FROM OLD.contact_selection_id
                OR NEW.contact_selection_sha256 IS DISTINCT FROM OLD.contact_selection_sha256
                OR NEW.contact_intent_sha256 IS DISTINCT FROM OLD.contact_intent_sha256
            ) THEN
                RAISE EXCEPTION 'external research contact authority is immutable';
            END IF;
            IF NEW.subject_kind = 'contact' AND NEW.contact_selection_id IS NOT NULL
               AND NOT EXISTS (
                SELECT 1 FROM contact_research_selection selection
                WHERE selection.id=NEW.contact_selection_id
                  AND selection.workspace_id=NEW.workspace_id
                  AND selection.project_id=NEW.project_id
                  AND selection.project_run_id=NEW.project_run_id
                  AND selection.account_id=NEW.account_id
                  AND selection.selection_sha256=NEW.contact_selection_sha256
                  AND EXISTS (
                      SELECT 1
                      FROM jsonb_array_elements(selection.body_json->'targets') AS target(value)
                      WHERE (target.value->>'contact_entity_id')::uuid=NEW.contact_id
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM contact_research_selection_cancellation cancellation
                      WHERE cancellation.selection_id=selection.id
                  )
            ) THEN
                RAISE EXCEPTION 'contact external research lacks active exact-selection authority';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER external_research_contact_authority "
        "BEFORE INSERT OR UPDATE OF contact_selection_id, contact_selection_sha256, "
        "contact_intent_sha256, subject_kind, contact_id, account_id, project_run_id, "
        "workspace_id, project_id ON external_research_operation FOR EACH ROW "
        "EXECUTE FUNCTION external_research_contact_authority_guard()"
    )

    # Stops live beside immutable provider receipts. A ready/charged result becomes unusable
    # immediately, while dispatched work can still reconcile its actual provider spend.
    op.execute(
        """
        CREATE TABLE external_research_operation_stop (
            id uuid NOT NULL,
            operation_id uuid NOT NULL,
            workspace_id text NOT NULL,
            reason_code text NOT NULL,
            authority_ref text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT external_research_operation_stop_pkey PRIMARY KEY (id),
            CONSTRAINT external_research_operation_stop_once UNIQUE (operation_id),
            CONSTRAINT external_research_operation_stop_operation_fk FOREIGN KEY
                (operation_id, workspace_id)
                REFERENCES external_research_operation (id, workspace_id),
            CONSTRAINT external_research_operation_stop_nonempty CHECK (
                length(btrim(reason_code)) > 0 AND length(btrim(authority_ref)) > 0
            )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE contact_channel_operation_stop (
            id uuid NOT NULL,
            operation_id uuid NOT NULL,
            workspace_id text NOT NULL,
            reason_code text NOT NULL,
            authority_ref text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT contact_channel_operation_stop_pkey PRIMARY KEY (id),
            CONSTRAINT contact_channel_operation_stop_once UNIQUE (operation_id),
            CONSTRAINT contact_channel_operation_stop_operation_fk FOREIGN KEY
                (operation_id, workspace_id)
                REFERENCES contact_channel_operation (id, workspace_id),
            CONSTRAINT contact_channel_operation_stop_nonempty CHECK (
                length(btrim(reason_code)) > 0 AND length(btrim(authority_ref)) > 0
            )
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION contact_research_operation_stop_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'contact research operation stops are append-only';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in (
        "external_research_operation_stop",
        "contact_channel_operation_stop",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE INSERT OR UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION contact_research_operation_stop_guard()"
        )


def downgrade() -> None:
    for table in (
        "contact_channel_operation_stop",
        "external_research_operation_stop",
    ):
        op.execute(f"DROP TRIGGER {table}_immutable ON {table}")
        op.execute(f"DROP TABLE {table}")
    op.execute("DROP FUNCTION contact_research_operation_stop_guard()")
    op.execute("DROP TRIGGER external_research_contact_authority ON external_research_operation")
    op.execute("DROP FUNCTION external_research_contact_authority_guard()")
    op.execute(
        "ALTER TABLE external_research_operation DROP CONSTRAINT "
        "external_research_contact_authority_shape, DROP CONSTRAINT "
        "external_research_contact_selection_fk, DROP COLUMN contact_intent_sha256, "
        "DROP COLUMN contact_selection_sha256, DROP COLUMN contact_selection_id"
    )
