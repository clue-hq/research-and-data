"""M8C C6 immutable selected-contact research authorization.

Revision ID: 4d9b02f218dc
Revises: fd8d61eb482f
Create Date: 2026-08-05 11:03:48.200642+00:00

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
revision: str = "4d9b02f218dc"
down_revision: str | None = "fd8d61eb482f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE contact_research_selection (
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
            body_json jsonb NOT NULL,
            predecessor_id uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT contact_research_selection_pkey PRIMARY KEY (id),
            CONSTRAINT contact_research_selection_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            CONSTRAINT contact_research_selection_project_run_fk
                FOREIGN KEY (project_run_id, workspace_id, project_id)
                REFERENCES project_run (id, workspace_id, project_id),
            CONSTRAINT contact_research_selection_account_run_fk
                FOREIGN KEY (account_run_id) REFERENCES account_run (id),
            CONSTRAINT contact_research_selection_account_fk
                FOREIGN KEY (account_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT contact_research_selection_predecessor_fk
                FOREIGN KEY (predecessor_id) REFERENCES contact_research_selection (id),
            CONSTRAINT contact_research_selection_workspace_anchor UNIQUE (id, workspace_id),
            CONSTRAINT contact_research_selection_digest_unique
                UNIQUE (workspace_id, project_run_id, account_id, selection_sha256),
            CONSTRAINT contact_research_selection_hashes CHECK (
                directive_sha256 ~ '^[0-9a-f]{64}$'
                AND selection_sha256 ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT contact_research_selection_version CHECK (directive_version >= 1),
            CONSTRAINT contact_research_selection_body_object CHECK (
                jsonb_typeof(body_json)='object'
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX contact_research_selection_scope ON contact_research_selection "
        "(workspace_id, project_run_id, account_id, created_at DESC, id DESC)"
    )
    op.execute(
        """
        CREATE TABLE contact_research_selection_cancellation (
            id uuid NOT NULL,
            selection_id uuid NOT NULL,
            workspace_id text NOT NULL,
            cancelled_by text NOT NULL,
            reason_code text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT contact_research_selection_cancellation_pkey PRIMARY KEY (id),
            CONSTRAINT contact_research_selection_cancellation_selection_fk
                FOREIGN KEY (selection_id, workspace_id)
                REFERENCES contact_research_selection (id, workspace_id),
            CONSTRAINT contact_research_selection_cancellation_once UNIQUE (selection_id),
            CONSTRAINT contact_research_selection_cancellation_actor CHECK (
                length(btrim(cancelled_by)) > 0
            ),
            CONSTRAINT contact_research_selection_cancellation_reason CHECK (
                length(btrim(reason_code)) > 0
            )
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION contact_research_selection_guard() RETURNS trigger AS $$
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
        "CREATE TRIGGER contact_research_selection_immutable "
        "BEFORE INSERT OR UPDATE OR DELETE ON contact_research_selection FOR EACH ROW "
        "EXECUTE FUNCTION contact_research_selection_guard()"
    )
    op.execute(
        """
        CREATE FUNCTION contact_research_selection_cancellation_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'contact research selection cancellations are append-only';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER contact_research_selection_cancellation_immutable "
        "BEFORE INSERT OR UPDATE OR DELETE ON contact_research_selection_cancellation "
        "FOR EACH ROW EXECUTE FUNCTION contact_research_selection_cancellation_guard()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER contact_research_selection_cancellation_immutable "
        "ON contact_research_selection_cancellation"
    )
    op.execute("DROP FUNCTION contact_research_selection_cancellation_guard()")
    op.execute("DROP TABLE contact_research_selection_cancellation")
    op.execute("DROP TRIGGER contact_research_selection_immutable ON contact_research_selection")
    op.execute("DROP FUNCTION contact_research_selection_guard()")
    op.execute("DROP TABLE contact_research_selection")
