"""Database-backed contact-selection approval and linear successor authority.

Revision ID: d338ba5a8f7e
Revises: 91c664b17911
Create Date: 2026-08-05 15:34:55.975302+00:00

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
revision: str = "d338ba5a8f7e"
down_revision: str | None = "91c664b17911"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE contact_research_selection_approval (
            id uuid NOT NULL,
            workspace_id text NOT NULL,
            project_id text NOT NULL,
            project_run_id uuid NOT NULL,
            account_run_id uuid NOT NULL,
            account_id uuid NOT NULL,
            directive_id uuid NOT NULL,
            directive_version integer NOT NULL,
            directive_sha256 text NOT NULL,
            selection_sha256 text NOT NULL,
            predecessor_id uuid,
            authority_kind text NOT NULL,
            approval_operation_id uuid NOT NULL,
            approved_by text NOT NULL,
            action_ref text NOT NULL,
            approved_at timestamptz NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT contact_research_selection_approval_pkey PRIMARY KEY (id),
            CONSTRAINT contact_research_selection_approval_workspace_anchor
                UNIQUE (id, workspace_id),
            CONSTRAINT contact_research_selection_approval_operation_account_unique
                UNIQUE (workspace_id, approval_operation_id, account_id),
            CONSTRAINT contact_research_selection_approval_project_run_fk
                FOREIGN KEY (project_run_id, workspace_id, project_id)
                REFERENCES project_run (id, workspace_id, project_id),
            CONSTRAINT contact_research_selection_approval_account_run_fk
                FOREIGN KEY (account_run_id) REFERENCES account_run (id),
            CONSTRAINT contact_research_selection_approval_account_fk
                FOREIGN KEY (account_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT contact_research_selection_approval_directive_fk
                FOREIGN KEY (directive_id, directive_version, directive_sha256)
                REFERENCES account_research_directive
                    (directive_id, version, canonical_json_sha256),
            CONSTRAINT contact_research_selection_approval_predecessor_fk
                FOREIGN KEY (predecessor_id) REFERENCES contact_research_selection (id),
            CONSTRAINT contact_research_selection_approval_hashes CHECK (
                directive_sha256 ~ '^[0-9a-f]{64}$'
                AND selection_sha256 ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT contact_research_selection_approval_nonempty CHECK (
                length(btrim(approved_by)) > 0 AND length(btrim(action_ref)) > 0
            ),
            CONSTRAINT contact_research_selection_approval_kind CHECK (
                (authority_kind='directive_confirmation' AND predecessor_id IS NULL)
                OR (authority_kind='human_successor' AND predecessor_id IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        "ALTER TABLE contact_research_selection ADD COLUMN approval_id uuid, "
        "ADD CONSTRAINT contact_research_selection_approval_fk FOREIGN KEY "
        "(approval_id, workspace_id) REFERENCES "
        "contact_research_selection_approval (id, workspace_id)"
    )
    op.execute(
        "ALTER TABLE contact_channel_operation ADD CONSTRAINT "
        "contact_channel_operation_selection_fk FOREIGN KEY (selection_id, workspace_id) "
        "REFERENCES contact_research_selection (id, workspace_id) NOT VALID"
    )
    op.execute(
        "ALTER TABLE contact_channel_reuse ADD CONSTRAINT "
        "contact_channel_reuse_selection_fk FOREIGN KEY (selection_id, workspace_id) "
        "REFERENCES contact_research_selection (id, workspace_id) NOT VALID"
    )
    op.execute(
        """
        CREATE FUNCTION contact_research_selection_approval_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'contact research selection approvals are append-only';
            END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended(
                NEW.workspace_id || ':' || NEW.project_run_id::text || ':' || NEW.account_id::text,
                0
            ));
            IF NOT EXISTS (
                SELECT 1 FROM account_run ar
                WHERE ar.id=NEW.account_run_id
                  AND ar.project_run_id=NEW.project_run_id
                  AND ar.entity_id=NEW.account_id
                  AND ar.research_directive_id=NEW.directive_id
                  AND ar.research_directive_version=NEW.directive_version
                  AND ar.research_directive_sha256=NEW.directive_sha256
            ) THEN
                RAISE EXCEPTION 'selection approval crosses account-run directive authority';
            END IF;
            IF NEW.authority_kind='directive_confirmation' THEN
                IF EXISTS (
                    SELECT 1 FROM contact_research_selection selection
                    WHERE selection.workspace_id=NEW.workspace_id
                      AND selection.project_run_id=NEW.project_run_id
                      AND selection.account_id=NEW.account_id
                ) THEN
                    RAISE EXCEPTION 'initial selection approval cannot replace an existing head';
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM account_research_directive directive
                    WHERE directive.directive_id=NEW.directive_id
                      AND directive.workspace_id=NEW.workspace_id
                      AND directive.project_id=NEW.project_id
                      AND directive.version=NEW.directive_version
                      AND directive.canonical_json_sha256=NEW.directive_sha256
                      AND directive.status IN ('confirmed', 'superseded')
                      AND directive.confirmation_operation_id=NEW.approval_operation_id
                      AND directive.confirmed_by=NEW.approved_by
                      AND directive.confirming_turn_ref=NEW.action_ref
                      AND directive.confirmed_at=NEW.approved_at
                ) THEN
                    RAISE EXCEPTION
                        'initial selection lacks exact directive confirmation authority';
                END IF;
            ELSE
                IF NOT EXISTS (
                    SELECT 1 FROM contact_research_selection predecessor
                    WHERE predecessor.id=NEW.predecessor_id
                      AND predecessor.workspace_id=NEW.workspace_id
                      AND predecessor.project_id=NEW.project_id
                      AND predecessor.project_run_id=NEW.project_run_id
                      AND predecessor.account_run_id=NEW.account_run_id
                      AND predecessor.account_id=NEW.account_id
                      AND NOT EXISTS (
                          SELECT 1 FROM contact_research_selection successor
                          WHERE successor.predecessor_id=predecessor.id
                      )
                ) THEN
                    RAISE EXCEPTION 'successor approval does not name the current selection head';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER contact_research_selection_approval_immutable "
        "BEFORE INSERT OR UPDATE OR DELETE ON contact_research_selection_approval "
        "FOR EACH ROW EXECUTE FUNCTION contact_research_selection_approval_guard()"
    )
    op.execute(
        "CREATE UNIQUE INDEX contact_research_selection_one_successor "
        "ON contact_research_selection (predecessor_id) WHERE predecessor_id IS NOT NULL"
    )
    op.execute(
        """
        CREATE FUNCTION contact_channel_selection_authority_guard() RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM contact_research_selection selection
                WHERE selection.id=NEW.selection_id
                  AND selection.workspace_id=NEW.workspace_id
                  AND selection.project_id=NEW.project_id
                  AND selection.project_run_id=NEW.project_run_id
                  AND selection.account_id=NEW.account_id
                  AND selection.selection_sha256=NEW.selection_sha256
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
                RAISE EXCEPTION 'contact channel operation lacks exact active selection authority';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER contact_channel_selection_authority "
        "BEFORE INSERT OR UPDATE OF selection_id, selection_sha256, workspace_id, project_id, "
        "project_run_id, account_id, contact_id ON contact_channel_operation FOR EACH ROW "
        "EXECUTE FUNCTION contact_channel_selection_authority_guard()"
    )
    op.execute(
        """
        CREATE FUNCTION contact_channel_reuse_selection_authority_guard() RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM contact_research_selection selection
                JOIN contact_channel_operation operation
                  ON operation.id=NEW.source_operation_id
                 AND operation.workspace_id=NEW.workspace_id
                WHERE selection.id=NEW.selection_id
                  AND selection.workspace_id=NEW.workspace_id
                  AND selection.project_id=NEW.project_id
                  AND selection.project_run_id=NEW.project_run_id
                  AND selection.account_id=operation.account_id
                  AND selection.selection_sha256=NEW.selection_sha256
                  AND EXISTS (
                      SELECT 1
                      FROM jsonb_array_elements(selection.body_json->'targets') AS target(value)
                      WHERE (target.value->>'contact_entity_id')::uuid=operation.contact_id
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM contact_research_selection_cancellation cancellation
                      WHERE cancellation.selection_id=selection.id
                  )
            ) THEN
                RAISE EXCEPTION 'contact channel reuse lacks exact active selection authority';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER contact_channel_reuse_selection_authority "
        "BEFORE INSERT ON contact_channel_reuse FOR EACH ROW "
        "EXECUTE FUNCTION contact_channel_reuse_selection_authority_guard()"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION contact_research_selection_guard() RETURNS trigger AS $$
        DECLARE
            target jsonb;
            referenced_claim text;
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'contact research selections are immutable';
            END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended(
                NEW.workspace_id || ':' || NEW.project_run_id::text || ':' || NEW.account_id::text,
                0
            ));
            IF NEW.approval_id IS NULL OR NOT EXISTS (
                SELECT 1 FROM contact_research_selection_approval approval
                WHERE approval.id=NEW.approval_id
                  AND approval.workspace_id=NEW.workspace_id
                  AND approval.project_id=NEW.project_id
                  AND approval.project_run_id=NEW.project_run_id
                  AND approval.account_run_id=NEW.account_run_id
                  AND approval.account_id=NEW.account_id
                  AND approval.directive_id=NEW.directive_id
                  AND approval.directive_version=NEW.directive_version
                  AND approval.directive_sha256=NEW.directive_sha256
                  AND approval.selection_sha256=NEW.selection_sha256
                  AND approval.predecessor_id IS NOT DISTINCT FROM NEW.predecessor_id
                  AND approval.approved_by=NEW.body_json->>'approved_by'
                  AND approval.approved_at=(NEW.body_json->>'approved_at')::timestamptz
            ) THEN
                RAISE EXCEPTION 'contact research selection lacks exact database approval';
            END IF;
            IF NEW.body_json->>'workspace_id' <> NEW.workspace_id
               OR NEW.body_json->>'project_id' <> NEW.project_id
               OR (NEW.body_json->>'project_run_id')::uuid <> NEW.project_run_id
               OR (NEW.body_json->>'account_entity_id')::uuid <> NEW.account_id
               OR (NEW.body_json#>>'{research_directive,directive_id}')::uuid
                    <> NEW.directive_id
               OR (NEW.body_json#>>'{research_directive,version}')::integer
                    <> NEW.directive_version
               OR NEW.body_json#>>'{research_directive,canonical_json_sha256}'
                    <> NEW.directive_sha256 THEN
                RAISE EXCEPTION 'contact research selection columns differ from body authority';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM account_run account_run
                WHERE account_run.id=NEW.account_run_id
                  AND account_run.project_run_id=NEW.project_run_id
                  AND account_run.entity_id=NEW.account_id
                  AND account_run.research_directive_id=NEW.directive_id
                  AND account_run.research_directive_version=NEW.directive_version
                  AND account_run.research_directive_sha256=NEW.directive_sha256
            ) THEN
                RAISE EXCEPTION 'contact research selection crosses its account run';
            END IF;
            IF NEW.predecessor_id IS NULL AND EXISTS (
                SELECT 1 FROM contact_research_selection selection
                WHERE selection.workspace_id=NEW.workspace_id
                  AND selection.project_run_id=NEW.project_run_id
                  AND selection.account_id=NEW.account_id
            ) THEN
                RAISE EXCEPTION 'contact research selection requires the current predecessor';
            END IF;
            IF NEW.predecessor_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM contact_research_selection predecessor
                WHERE predecessor.id=NEW.predecessor_id
                  AND predecessor.workspace_id=NEW.workspace_id
                  AND predecessor.project_id=NEW.project_id
                  AND predecessor.project_run_id=NEW.project_run_id
                  AND predecessor.account_run_id=NEW.account_run_id
                  AND predecessor.account_id=NEW.account_id
                  AND NOT EXISTS (
                      SELECT 1 FROM contact_research_selection successor
                      WHERE successor.predecessor_id=predecessor.id
                  )
            ) THEN
                RAISE EXCEPTION 'contact research selection predecessor is not the current head';
            END IF;
            FOR target IN SELECT value FROM jsonb_array_elements(NEW.body_json->'targets') LOOP
                IF NOT EXISTS (
                    SELECT 1 FROM contact_entity contact
                    WHERE contact.id=(target->>'contact_entity_id')::uuid
                      AND contact.workspace_id=NEW.workspace_id
                      AND contact.account_entity_id=NEW.account_id
                      AND contact.merged_into IS NULL
                ) THEN
                    RAISE EXCEPTION 'contact research target is absent, merged, or cross-account';
                END IF;
                FOR referenced_claim IN
                    SELECT value #>> '{}'
                    FROM jsonb_array_elements(target->'committee_claim_ids')
                LOOP
                    IF NOT EXISTS (
                        SELECT 1 FROM claim c
                        WHERE c.id=referenced_claim::uuid
                          AND c.entity_id=(target->>'contact_entity_id')::uuid
                          AND c.run_id=NEW.account_run_id
                          AND c.research_mode='committee_discovery'
                    ) THEN
                        RAISE EXCEPTION 'contact selection committee claim crosses contact/run';
                    END IF;
                END LOOP;
                FOR referenced_claim IN
                    SELECT value #>> '{}'
                    FROM jsonb_array_elements(target->'strong_identity_claim_ids')
                LOOP
                    IF NOT EXISTS (
                        SELECT 1 FROM claim c
                        WHERE c.id=referenced_claim::uuid
                          AND c.entity_id=(target->>'contact_entity_id')::uuid
                          AND c.run_id=NEW.account_run_id
                          AND c.research_mode='committee_discovery'
                    ) THEN
                        RAISE EXCEPTION 'contact selection identity claim crosses contact/run';
                    END IF;
                END LOOP;
            END LOOP;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS contact_channel_reuse_selection_authority ON contact_channel_reuse"
    )
    op.execute("DROP FUNCTION IF EXISTS contact_channel_reuse_selection_authority_guard()")
    op.execute(
        "DROP TRIGGER IF EXISTS contact_channel_selection_authority ON contact_channel_operation"
    )
    op.execute("DROP FUNCTION IF EXISTS contact_channel_selection_authority_guard()")
    op.execute(
        "ALTER TABLE contact_channel_reuse DROP CONSTRAINT IF EXISTS "
        "contact_channel_reuse_selection_fk"
    )
    op.execute(
        "ALTER TABLE contact_channel_operation DROP CONSTRAINT IF EXISTS "
        "contact_channel_operation_selection_fk"
    )
    op.execute("DROP INDEX contact_research_selection_one_successor")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION contact_research_selection_guard() RETURNS trigger AS $$
        DECLARE
            target jsonb;
            referenced_claim text;
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'contact research selections are immutable';
            END IF;
            IF NEW.body_json->>'workspace_id' <> NEW.workspace_id
               OR NEW.body_json->>'project_id' <> NEW.project_id
               OR (NEW.body_json->>'project_run_id')::uuid <> NEW.project_run_id
               OR (NEW.body_json->>'account_entity_id')::uuid <> NEW.account_id
               OR (NEW.body_json#>>'{research_directive,directive_id}')::uuid
                    <> NEW.directive_id
               OR (NEW.body_json#>>'{research_directive,version}')::integer
                    <> NEW.directive_version
               OR NEW.body_json#>>'{research_directive,canonical_json_sha256}'
                    <> NEW.directive_sha256 THEN
                RAISE EXCEPTION 'contact research selection columns differ from body authority';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM account_run account_run
                WHERE account_run.id=NEW.account_run_id
                  AND account_run.project_run_id=NEW.project_run_id
                  AND account_run.entity_id=NEW.account_id
            ) THEN
                RAISE EXCEPTION 'contact research selection crosses its account run';
            END IF;
            IF NEW.predecessor_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM contact_research_selection predecessor
                WHERE predecessor.id=NEW.predecessor_id
                  AND predecessor.workspace_id=NEW.workspace_id
                  AND predecessor.project_run_id=NEW.project_run_id
                  AND predecessor.account_id=NEW.account_id
            ) THEN
                RAISE EXCEPTION 'contact research selection predecessor crosses scope';
            END IF;
            FOR target IN SELECT value FROM jsonb_array_elements(NEW.body_json->'targets') LOOP
                IF NOT EXISTS (
                    SELECT 1 FROM contact_entity contact
                    WHERE contact.id=(target->>'contact_entity_id')::uuid
                      AND contact.workspace_id=NEW.workspace_id
                      AND contact.account_entity_id=NEW.account_id
                      AND contact.merged_into IS NULL
                ) THEN
                    RAISE EXCEPTION 'contact research target is absent, merged, or cross-account';
                END IF;
                FOR referenced_claim IN
                    SELECT value #>> '{}'
                    FROM jsonb_array_elements(target->'committee_claim_ids')
                LOOP
                    IF NOT EXISTS (
                        SELECT 1 FROM claim c
                        WHERE c.id=referenced_claim::uuid
                          AND c.entity_id=(target->>'contact_entity_id')::uuid
                          AND c.run_id=NEW.account_run_id
                          AND c.research_mode='committee_discovery'
                    ) THEN
                        RAISE EXCEPTION 'contact selection committee claim crosses contact/run';
                    END IF;
                END LOOP;
                FOR referenced_claim IN
                    SELECT value #>> '{}'
                    FROM jsonb_array_elements(target->'strong_identity_claim_ids')
                LOOP
                    IF NOT EXISTS (
                        SELECT 1 FROM claim c
                        WHERE c.id=referenced_claim::uuid
                          AND c.entity_id=(target->>'contact_entity_id')::uuid
                          AND c.run_id=NEW.account_run_id
                          AND c.research_mode='committee_discovery'
                    ) THEN
                        RAISE EXCEPTION 'contact selection identity claim crosses contact/run';
                    END IF;
                END LOOP;
            END LOOP;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "DROP TRIGGER contact_research_selection_approval_immutable "
        "ON contact_research_selection_approval"
    )
    op.execute("DROP FUNCTION contact_research_selection_approval_guard()")
    op.execute(
        "ALTER TABLE contact_research_selection DROP CONSTRAINT "
        "contact_research_selection_approval_fk, DROP COLUMN approval_id"
    )
    op.execute("DROP TABLE contact_research_selection_approval")
