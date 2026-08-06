"""m8c c2 exact contact external research subject

Revision ID: 9e3afe93b8e1
Revises: d0f7a2858e40
Create Date: 2026-08-05 04:20:18.203802+00:00

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
revision: str = "9e3afe93b8e1"
down_revision: str | None = "d0f7a2858e40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _snapshot_use_validator(*, exact_subject: bool) -> str:
    subject_guard = (
        """
                  AND snapshot.subject_kind=NEW.subject_kind
                  AND snapshot.contact_id IS NOT DISTINCT FROM NEW.contact_id
                  AND operation.subject_kind=NEW.subject_kind
                  AND operation.contact_id IS NOT DISTINCT FROM NEW.contact_id"""
        if exact_subject
        else ""
    )
    return f"""
        CREATE OR REPLACE FUNCTION external_research_validate_snapshot_use() RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM external_research_snapshot snapshot
                JOIN external_research_operation operation
                  ON operation.id=snapshot.operation_id
                 AND operation.workspace_id=snapshot.workspace_id
                WHERE snapshot.id=NEW.snapshot_id
                  AND snapshot.workspace_id=NEW.workspace_id
                  AND snapshot.account_id=NEW.account_id
                  AND snapshot.source_key=NEW.source_key
                  AND snapshot.fresh_until > NEW.adopted_at
                  AND operation.project_id=NEW.project_id
                  AND operation.reuse_fingerprint=NEW.reuse_fingerprint
                  AND operation.state='ready'{subject_guard}
            ) THEN
                RAISE EXCEPTION 'snapshot use must reference a matching fresh ready acquisition';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """


def _claim_lineage_validator(*, exact_subject: bool) -> str:
    subject_guard = (
        """
                  AND (
                      (snapshot.subject_kind='account' AND snapshot.account_id=NEW.entity_id)
                      OR
                      (snapshot.subject_kind='contact' AND snapshot.contact_id=NEW.entity_id)
                  )"""
        if exact_subject
        else "\n                  AND snapshot.account_id=NEW.entity_id"
    )
    return f"""
        CREATE OR REPLACE FUNCTION claim_validate_external_research_lineage() RETURNS trigger AS $$
        BEGIN
            IF NEW.source_key = 'exa_deep'
               AND NEW.source_operation_ref IS NOT NULL
               AND NOT EXISTS (
                SELECT 1
                FROM external_research_snapshot snapshot
                JOIN external_research_operation operation
                  ON operation.id=snapshot.operation_id
                 AND operation.workspace_id=snapshot.workspace_id
                JOIN external_research_result_artifact result
                  ON result.snapshot_id=snapshot.id
                 AND result.workspace_id=snapshot.workspace_id
                WHERE operation.id::text=NEW.source_operation_ref
                  AND snapshot.id::text=NEW.source_snapshot_ref
                  AND snapshot.provider_request_id=NEW.source_request_ref
                  {subject_guard.strip()}
                  AND snapshot.source_key=NEW.source_key
                  AND result.artifact_key=NEW.artifact_key
                  AND (NEW.workspace_id IS NULL OR snapshot.workspace_id=NEW.workspace_id)
            ) THEN
                RAISE EXCEPTION
                    'claim external research lineage does not match its snapshot/result evidence';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """


def upgrade() -> None:
    # A contact operation must be born against the current canonical contact under the exact
    # canonical account. A later merge does not rewrite immutable provider history; a successor
    # request is recompiled for the survivor.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM external_research_operation operation
                LEFT JOIN account_entity account ON account.id=operation.account_id
                    AND account.workspace_id=operation.workspace_id
                LEFT JOIN contact_entity contact ON contact.id=operation.contact_id
                    AND contact.workspace_id=operation.workspace_id
                WHERE account.id IS NULL
                   OR (operation.subject_kind='contact' AND (
                       contact.id IS NULL OR contact.account_entity_id<>operation.account_id
                   ))
            ) THEN
                RAISE EXCEPTION 'existing external research operation has invalid subject lineage';
            END IF;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION external_research_validate_canonical_subject() RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM account_entity account
                WHERE account.id=NEW.account_id
                  AND account.workspace_id=NEW.workspace_id
                  AND account.merged_into IS NULL
            ) THEN
                RAISE EXCEPTION 'external research requires a canonical account subject';
            END IF;
            IF NEW.subject_kind='contact' AND NOT EXISTS (
                SELECT 1 FROM contact_entity contact
                WHERE contact.id=NEW.contact_id
                  AND contact.workspace_id=NEW.workspace_id
                  AND contact.account_entity_id=NEW.account_id
                  AND contact.merged_into IS NULL
            ) THEN
                RAISE EXCEPTION
                    'external research requires a canonical contact under the exact account';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER external_research_canonical_subject BEFORE INSERT OR UPDATE OF "
        "workspace_id, subject_kind, account_id, contact_id ON external_research_operation "
        "FOR EACH ROW EXECUTE FUNCTION external_research_validate_canonical_subject()"
    )

    # Terminal snapshots are immutable, so temporarily remove only their mutation guard while the
    # migration copies the already-immutable operation subject onto historical rows.
    op.execute("DROP TRIGGER external_research_snapshot_immutable ON external_research_snapshot")
    op.execute(
        "ALTER TABLE external_research_snapshot ADD COLUMN subject_kind "
        "external_research_subject_kind"
    )
    op.execute("ALTER TABLE external_research_snapshot ADD COLUMN contact_id uuid")
    op.execute(
        "UPDATE external_research_snapshot snapshot SET "
        "subject_kind=operation.subject_kind, contact_id=operation.contact_id "
        "FROM external_research_operation operation "
        "WHERE operation.id=snapshot.operation_id "
        "AND operation.workspace_id=snapshot.workspace_id"
    )
    op.execute("ALTER TABLE external_research_snapshot ALTER COLUMN subject_kind SET NOT NULL")
    op.execute(
        "ALTER TABLE external_research_snapshot ADD CONSTRAINT "
        "external_research_snapshot_contact_fk FOREIGN KEY (contact_id, workspace_id) "
        "REFERENCES contact_entity (id, workspace_id)"
    )
    op.execute(
        "ALTER TABLE external_research_snapshot ADD CONSTRAINT "
        "external_research_snapshot_subject_shape CHECK ((subject_kind='account' "
        "AND contact_id IS NULL) OR (subject_kind='contact' AND contact_id IS NOT NULL))"
    )
    op.execute(
        """
        CREATE FUNCTION external_research_validate_snapshot_subject() RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM external_research_operation operation
                WHERE operation.id=NEW.operation_id
                  AND operation.workspace_id=NEW.workspace_id
                  AND operation.subject_kind=NEW.subject_kind
                  AND operation.account_id=NEW.account_id
                  AND operation.contact_id IS NOT DISTINCT FROM NEW.contact_id
                  AND operation.source_key=NEW.source_key
                  AND operation.request_fingerprint=NEW.request_fingerprint
            ) THEN
                RAISE EXCEPTION 'external research snapshot subject differs from its operation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER external_research_snapshot_subject_validate BEFORE INSERT "
        "ON external_research_snapshot FOR EACH ROW "
        "EXECUTE FUNCTION external_research_validate_snapshot_subject()"
    )
    op.execute(
        "CREATE TRIGGER external_research_snapshot_immutable BEFORE UPDATE OR DELETE "
        "ON external_research_snapshot FOR EACH ROW "
        "EXECUTE FUNCTION external_research_snapshot_immutable()"
    )

    op.execute(
        "DROP TRIGGER external_research_snapshot_use_immutable ON external_research_snapshot_use"
    )
    op.execute(
        "ALTER TABLE external_research_snapshot_use ADD COLUMN subject_kind "
        "external_research_subject_kind"
    )
    op.execute("ALTER TABLE external_research_snapshot_use ADD COLUMN contact_id uuid")
    op.execute(
        "UPDATE external_research_snapshot_use snapshot_use SET "
        "subject_kind=snapshot.subject_kind, contact_id=snapshot.contact_id "
        "FROM external_research_snapshot snapshot "
        "WHERE snapshot.id=snapshot_use.snapshot_id "
        "AND snapshot.workspace_id=snapshot_use.workspace_id"
    )
    op.execute("ALTER TABLE external_research_snapshot_use ALTER COLUMN subject_kind SET NOT NULL")
    op.execute(
        "ALTER TABLE external_research_snapshot_use ADD CONSTRAINT "
        "external_research_snapshot_use_contact_fk FOREIGN KEY (contact_id, workspace_id) "
        "REFERENCES contact_entity (id, workspace_id)"
    )
    op.execute(
        "ALTER TABLE external_research_snapshot_use ADD CONSTRAINT "
        "external_research_snapshot_use_subject_shape CHECK ((subject_kind='account' "
        "AND contact_id IS NULL) OR (subject_kind='contact' AND contact_id IS NOT NULL))"
    )
    op.execute(_snapshot_use_validator(exact_subject=True))
    op.execute(
        "CREATE TRIGGER external_research_snapshot_use_immutable BEFORE UPDATE OR DELETE "
        "ON external_research_snapshot_use FOR EACH ROW "
        "EXECUTE FUNCTION external_research_snapshot_use_immutable()"
    )

    op.execute("DROP INDEX external_research_ready_reuse")
    op.execute(
        "CREATE INDEX external_research_ready_account_subject "
        "ON external_research_operation "
        "(workspace_id, account_id, source_key, fresh_until DESC) "
        "WHERE state='ready' AND subject_kind='account'"
    )
    op.execute(
        "CREATE INDEX external_research_ready_contact_subject "
        "ON external_research_operation "
        "(workspace_id, contact_id, account_id, source_key, fresh_until DESC) "
        "WHERE state='ready' AND subject_kind='contact'"
    )
    op.execute(
        "CREATE INDEX external_research_snapshot_contact_subject "
        "ON external_research_snapshot "
        "(workspace_id, contact_id, account_id, source_key, fresh_until DESC) "
        "WHERE subject_kind='contact'"
    )
    op.execute(
        "CREATE INDEX external_research_snapshot_use_contact_lookup "
        "ON external_research_snapshot_use "
        "(workspace_id, project_run_id, contact_id, account_id, source_key, adopted_at DESC) "
        "WHERE subject_kind='contact'"
    )

    # The same lineage trigger now accepts a contact claim only when the immutable snapshot names
    # that exact contact; account behavior remains unchanged.
    op.execute(_claim_lineage_validator(exact_subject=True))


def downgrade() -> None:
    op.execute(_claim_lineage_validator(exact_subject=False))

    op.execute("DROP INDEX external_research_snapshot_use_contact_lookup")
    op.execute("DROP INDEX external_research_snapshot_contact_subject")
    op.execute("DROP INDEX external_research_ready_contact_subject")
    op.execute("DROP INDEX external_research_ready_account_subject")
    op.execute(
        "CREATE INDEX external_research_ready_reuse ON external_research_operation "
        "(workspace_id, account_id, source_key, fresh_until DESC) WHERE state='ready'"
    )

    op.execute(
        "DROP TRIGGER external_research_snapshot_use_immutable ON external_research_snapshot_use"
    )
    op.execute(_snapshot_use_validator(exact_subject=False))
    op.execute(
        "ALTER TABLE external_research_snapshot_use DROP CONSTRAINT "
        "external_research_snapshot_use_subject_shape"
    )
    op.execute(
        "ALTER TABLE external_research_snapshot_use DROP CONSTRAINT "
        "external_research_snapshot_use_contact_fk"
    )
    op.execute("ALTER TABLE external_research_snapshot_use DROP COLUMN contact_id")
    op.execute("ALTER TABLE external_research_snapshot_use DROP COLUMN subject_kind")
    op.execute(
        "CREATE TRIGGER external_research_snapshot_use_immutable BEFORE UPDATE OR DELETE "
        "ON external_research_snapshot_use FOR EACH ROW "
        "EXECUTE FUNCTION external_research_snapshot_use_immutable()"
    )

    op.execute("DROP TRIGGER external_research_snapshot_immutable ON external_research_snapshot")
    op.execute(
        "DROP TRIGGER external_research_snapshot_subject_validate ON external_research_snapshot"
    )
    op.execute("DROP FUNCTION external_research_validate_snapshot_subject()")
    op.execute(
        "ALTER TABLE external_research_snapshot DROP CONSTRAINT "
        "external_research_snapshot_subject_shape"
    )
    op.execute(
        "ALTER TABLE external_research_snapshot DROP CONSTRAINT "
        "external_research_snapshot_contact_fk"
    )
    op.execute("ALTER TABLE external_research_snapshot DROP COLUMN contact_id")
    op.execute("ALTER TABLE external_research_snapshot DROP COLUMN subject_kind")
    op.execute(
        "CREATE TRIGGER external_research_snapshot_immutable BEFORE UPDATE OR DELETE "
        "ON external_research_snapshot FOR EACH ROW "
        "EXECUTE FUNCTION external_research_snapshot_immutable()"
    )

    op.execute("DROP TRIGGER external_research_canonical_subject ON external_research_operation")
    op.execute("DROP FUNCTION external_research_validate_canonical_subject()")
