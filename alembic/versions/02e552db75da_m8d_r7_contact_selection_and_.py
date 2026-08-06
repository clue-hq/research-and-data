"""m8d r7 contact selection and independent launch

Revision ID: 02e552db75da
Revises: 4ff507129dd5
Create Date: 2026-08-06 06:19:41.726405+00:00

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
revision: str = "02e552db75da"
down_revision: str | None = "4ff507129dd5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Explicit human selection may be the first contact-selection action; committee
    # materialization/directive confirmation is no longer a prerequisite for naming a governed
    # identity-resolved non-committee contact.
    op.execute(
        "ALTER TABLE contact_research_selection_approval DROP CONSTRAINT "
        "contact_research_selection_approval_kind, ADD CONSTRAINT "
        "contact_research_selection_approval_kind CHECK ((authority_kind IN "
        "('directive_confirmation', 'human_initial') AND predecessor_id IS NULL) OR "
        "(authority_kind='human_successor' AND predecessor_id IS NOT NULL))"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION contact_research_selection_approval_guard() RETURNS trigger AS $$
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
            ELSIF NEW.authority_kind='human_initial' THEN
                IF EXISTS (
                    SELECT 1 FROM contact_research_selection selection
                    WHERE selection.workspace_id=NEW.workspace_id
                      AND selection.project_run_id=NEW.project_run_id
                      AND selection.account_id=NEW.account_id
                ) THEN
                    RAISE EXCEPTION 'human initial selection cannot replace an existing head';
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
                IF EXISTS (
                    SELECT 1 FROM entity_research_run run
                    JOIN entity_research_job job USING (research_run_id)
                    WHERE run.workspace_id=NEW.workspace_id
                      AND run.contact_selection_id=NEW.predecessor_id
                      AND job.state <> 'terminal'
                ) THEN
                    RAISE EXCEPTION
                        'active contact research must terminate before selection succession';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION contact_research_selection_guard() RETURNS trigger AS $$
        DECLARE
            target jsonb;
            referenced_claim text;
            target_basis text;
            association_claims jsonb;
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
               OR (NEW.body_json#>>'{research_directive,directive_id}')::uuid <> NEW.directive_id
               OR (NEW.body_json#>>'{research_directive,version}')::integer <> NEW.directive_version
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
                target_basis := COALESCE(target->>'selection_basis', 'committee_member');
                association_claims := CASE
                    WHEN jsonb_array_length(COALESCE(
                        target->'association_evidence_claim_ids', '[]'::jsonb
                    )) > 0
                    THEN target->'association_evidence_claim_ids'
                    ELSE target->'strong_identity_claim_ids'
                END;
                IF target_basis NOT IN ('committee_member', 'user_selected_associated_contact') THEN
                    RAISE EXCEPTION 'contact research target has an invalid selection basis';
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM contact_entity contact
                    WHERE contact.id=(target->>'contact_entity_id')::uuid
                      AND contact.workspace_id=NEW.workspace_id
                      AND contact.account_entity_id=NEW.account_id
                      AND contact.merged_into IS NULL
                      AND (contact.linkedin_url IS NOT NULL OR contact.verified_email IS NOT NULL)
                ) THEN
                    RAISE EXCEPTION
                        'contact research target is absent, merged, weak, or cross-account';
                END IF;
                IF jsonb_array_length(target->'strong_identity_claim_ids') < 1 OR
                   jsonb_array_length(association_claims) < 1 THEN
                    RAISE EXCEPTION 'contact target lacks identity or association evidence';
                END IF;
                IF target_basis='committee_member' AND
                   jsonb_array_length(target->'committee_claim_ids') < 1 THEN
                    RAISE EXCEPTION 'committee target lacks committee claim evidence';
                END IF;
                IF target_basis='user_selected_associated_contact' AND
                   jsonb_array_length(target->'committee_claim_ids') <> 0 THEN
                    RAISE EXCEPTION 'non-committee target carries committee claim evidence';
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
                          AND c.superseded_by IS NULL
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
                          AND c.superseded_by IS NULL
                          AND (c.field_key='core.discovery_provenance' OR
                               c.identity_binding='strong')
                    ) THEN
                        RAISE EXCEPTION
                            'contact selection identity claim is not current and strong';
                    END IF;
                END LOOP;
                FOR referenced_claim IN
                    SELECT value #>> '{}' FROM jsonb_array_elements(association_claims)
                LOOP
                    IF NOT EXISTS (
                        SELECT 1 FROM claim c
                        WHERE c.id=referenced_claim::uuid
                          AND c.entity_id=(target->>'contact_entity_id')::uuid
                          AND c.superseded_by IS NULL
                          AND c.field_key IN (
                              'core.discovery_provenance',
                              'contact.organization_relationship'
                          )
                    ) THEN
                        RAISE EXCEPTION 'contact selection association evidence is not current';
                    END IF;
                END LOOP;
            END LOOP;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )

    op.execute(
        "ALTER TABLE entity_research_run ADD COLUMN contact_selection_id uuid, "
        "ADD CONSTRAINT entity_research_run_contact_selection_shape CHECK (("
        "run_kind='account_research' AND contact_selection_id IS NULL) OR ("
        "run_kind='contact_research' AND contact_selection_id IS NOT NULL AND "
        "contact_selection_id=selection_id)) NOT VALID, "
        "ADD CONSTRAINT entity_research_run_contact_selection_fk FOREIGN KEY "
        "(contact_selection_id, workspace_id) REFERENCES "
        "contact_research_selection (id, workspace_id) DEFERRABLE INITIALLY DEFERRED NOT VALID"
    )
    op.execute(
        """
        CREATE TABLE entity_research_contact_launch (
            research_run_id          uuid PRIMARY KEY REFERENCES entity_research_run
                                         (research_run_id) ON DELETE RESTRICT,
            workspace_id             text NOT NULL,
            project_id               text NOT NULL,
            product_id               text NOT NULL,
            project_run_id           uuid NOT NULL,
            account_run_id           uuid NOT NULL REFERENCES account_run (id) ON DELETE RESTRICT,
            account_entity_id        uuid NOT NULL,
            contact_selection_id     uuid NOT NULL,
            contact_selection_sha256 text NOT NULL,
            selection_approval_id    uuid NOT NULL REFERENCES contact_research_selection_approval
                                         (id) ON DELETE RESTRICT,
            source_operation_id      uuid NOT NULL,
            source_action_ref        text NOT NULL,
            launched_by              text NOT NULL,
            confirmed_at             timestamptz NOT NULL,
            request_json             jsonb NOT NULL,
            request_sha256           text NOT NULL,
            created_at               timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT entity_research_contact_launch_selection_fk FOREIGN KEY
                (contact_selection_id, workspace_id)
                REFERENCES contact_research_selection (id, workspace_id) ON DELETE RESTRICT,
            CONSTRAINT entity_research_contact_launch_account_fk FOREIGN KEY
                (account_entity_id, workspace_id)
                REFERENCES account_entity (id, workspace_id) ON DELETE RESTRICT,
            CONSTRAINT entity_research_contact_launch_action_unique
                UNIQUE (workspace_id, source_operation_id),
            CONSTRAINT entity_research_contact_launch_hashes CHECK (
                contact_selection_sha256 ~ '^[0-9a-f]{64}$' AND
                request_sha256 ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT entity_research_contact_launch_nonempty CHECK (
                length(btrim(source_action_ref)) > 0 AND length(btrim(launched_by)) > 0
            ),
            CONSTRAINT entity_research_contact_launch_request_object
                CHECK (jsonb_typeof(request_json)='object')
        )
        """
    )
    op.execute(
        "CREATE INDEX entity_research_contact_launch_scope ON "
        "entity_research_contact_launch "
        "(workspace_id, project_id, product_id, project_run_id, account_entity_id)"
    )
    op.execute(
        """
        CREATE TABLE entity_research_contact_job_authority (
            job_id                  uuid PRIMARY KEY REFERENCES entity_research_job
                                        (job_id) ON DELETE RESTRICT,
            research_run_id         uuid NOT NULL REFERENCES entity_research_contact_launch
                                        (research_run_id) ON DELETE RESTRICT,
            workspace_id            text NOT NULL,
            contact_selection_id    uuid NOT NULL,
            contact_id              uuid NOT NULL,
            account_id              uuid NOT NULL,
            selection_basis         text NOT NULL,
            contact_intent_json      jsonb NOT NULL,
            contact_intent_sha256    text NOT NULL,
            target_json              jsonb NOT NULL,
            budget_cap_cents         numeric(18, 6) NOT NULL,
            created_at               timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT entity_research_contact_job_selection_fk FOREIGN KEY
                (contact_selection_id, workspace_id)
                REFERENCES contact_research_selection (id, workspace_id) ON DELETE RESTRICT,
            CONSTRAINT entity_research_contact_job_contact_fk FOREIGN KEY
                (contact_id, workspace_id)
                REFERENCES contact_entity (id, workspace_id) ON DELETE RESTRICT,
            CONSTRAINT entity_research_contact_job_basis CHECK (
                selection_basis IN ('committee_member', 'user_selected_associated_contact')
            ),
            CONSTRAINT entity_research_contact_job_intent_object
                CHECK (jsonb_typeof(contact_intent_json)='object'),
            CONSTRAINT entity_research_contact_job_target_object
                CHECK (jsonb_typeof(target_json)='object'),
            CONSTRAINT entity_research_contact_job_intent_sha
                CHECK (contact_intent_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT entity_research_contact_job_budget_positive
                CHECK (budget_cap_cents > 0),
            CONSTRAINT entity_research_contact_job_exact_json CHECK ((
                contact_intent_json->>'contact_entity_id'=contact_id::text AND
                contact_intent_json->>'account_entity_id'=account_id::text AND
                contact_intent_json->>'selection_id'=contact_selection_id::text AND
                target_json->>'contact_entity_id'=contact_id::text AND
                COALESCE(target_json->>'selection_basis', 'committee_member')=selection_basis
            ) IS TRUE)
        )
        """
    )
    op.execute(
        "CREATE INDEX entity_research_contact_job_run ON "
        "entity_research_contact_job_authority (research_run_id, contact_id)"
    )
    op.execute(
        """
        CREATE FUNCTION validate_entity_research_contact_launch_row()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            run_row entity_research_run%ROWTYPE;
            selection_row contact_research_selection%ROWTYPE;
            job_row entity_research_job%ROWTYPE;
        BEGIN
            IF TG_TABLE_NAME='entity_research_contact_launch' THEN
                SELECT * INTO run_row FROM entity_research_run
                WHERE research_run_id=NEW.research_run_id;
                SELECT * INTO selection_row FROM contact_research_selection
                WHERE id=NEW.contact_selection_id AND workspace_id=NEW.workspace_id;
                IF NOT FOUND OR run_row.run_kind <> 'contact_research' OR
                   run_row.subject_type <> 'contact' OR
                   run_row.contact_selection_id <> NEW.contact_selection_id OR
                   run_row.workspace_id <> NEW.workspace_id OR
                   run_row.project_id <> NEW.project_id OR
                   run_row.product_id <> NEW.product_id OR
                   run_row.project_run_id <> NEW.project_run_id OR
                   selection_row.project_id <> NEW.project_id OR
                   selection_row.project_run_id <> NEW.project_run_id OR
                   selection_row.account_run_id <> NEW.account_run_id OR
                   selection_row.account_id <> NEW.account_entity_id OR
                   selection_row.selection_sha256 <> NEW.contact_selection_sha256 OR
                   selection_row.approval_id <> NEW.selection_approval_id THEN
                    RAISE EXCEPTION 'contact launch crosses run/selection authority';
                END IF;
            ELSE
                SELECT * INTO job_row FROM entity_research_job WHERE job_id=NEW.job_id;
                IF NOT FOUND OR job_row.research_run_id <> NEW.research_run_id OR
                   job_row.subject_type <> 'contact' OR
                   job_row.subject_entity_id <> NEW.contact_id OR
                   job_row.parent_account_id <> NEW.account_id OR
                   job_row.workspace_id <> NEW.workspace_id OR
                   job_row.budget_cap_cents <> NEW.budget_cap_cents THEN
                    RAISE EXCEPTION 'contact job authority crosses its exact fleet job';
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM contact_research_selection selection,
                         LATERAL jsonb_array_elements(selection.body_json->'targets') target
                    WHERE selection.id=NEW.contact_selection_id
                      AND selection.workspace_id=NEW.workspace_id
                      AND target.value=NEW.target_json
                ) THEN
                    RAISE EXCEPTION 'contact job target differs from durable selection';
                END IF;
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER entity_research_contact_launch_scope BEFORE INSERT OR UPDATE ON "
        "entity_research_contact_launch FOR EACH ROW EXECUTE FUNCTION "
        "validate_entity_research_contact_launch_row()"
    )
    op.execute(
        "CREATE TRIGGER entity_research_contact_job_scope BEFORE INSERT OR UPDATE ON "
        "entity_research_contact_job_authority FOR EACH ROW EXECUTE FUNCTION "
        "validate_entity_research_contact_launch_row()"
    )
    op.execute(
        """
        CREATE FUNCTION validate_entity_research_contact_run_complete()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.run_kind <> 'contact_research' THEN
                RETURN NEW;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM contact_research_selection selection
                WHERE selection.id=NEW.contact_selection_id
                  AND selection.workspace_id=NEW.workspace_id
                  AND selection.project_id=NEW.project_id
                  AND selection.project_run_id=NEW.project_run_id
                  AND selection.account_id=(
                      NEW.lifecycle_json#>>'{selection,account_entity_id}'
                  )::uuid
                  AND NOT EXISTS (
                      SELECT 1 FROM contact_research_selection_cancellation cancellation
                      WHERE cancellation.selection_id=selection.id
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM contact_research_selection successor
                      WHERE successor.predecessor_id=selection.id
                  )
            ) THEN
                RAISE EXCEPTION 'contact research run lacks an active current selection';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM entity_research_contact_launch launch
                WHERE launch.research_run_id=NEW.research_run_id
                  AND launch.contact_selection_id=NEW.contact_selection_id
                  AND launch.workspace_id=NEW.workspace_id
                  AND launch.project_id=NEW.project_id
                  AND launch.product_id=NEW.product_id
                  AND launch.project_run_id=NEW.project_run_id
            ) THEN
                RAISE EXCEPTION 'contact research run lacks a separate confirmed launch';
            END IF;
            IF EXISTS (
                SELECT 1 FROM entity_research_job job
                LEFT JOIN entity_research_contact_job_authority authority
                  ON authority.job_id=job.job_id
                WHERE job.research_run_id=NEW.research_run_id
                  AND (
                      job.subject_type <> 'contact' OR authority.job_id IS NULL OR
                      authority.research_run_id <> NEW.research_run_id OR
                      authority.contact_selection_id <> NEW.contact_selection_id OR
                      NOT EXISTS (
                          SELECT 1 FROM jsonb_array_elements(
                              NEW.lifecycle_json#>'{selection,subjects}'
                          ) subject
                          WHERE (subject.value->>'subject_entity_id')::uuid=job.subject_entity_id
                            AND subject.value->'contact_authority' IS NOT NULL
                      )
                  )
            ) OR (
                SELECT count(*) FROM entity_research_job
                WHERE research_run_id=NEW.research_run_id
            ) <> jsonb_array_length(NEW.lifecycle_json#>'{selection,subjects}') THEN
                RAISE EXCEPTION 'contact research jobs do not exactly cover the valid selection';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER entity_research_contact_run_complete "
        "AFTER INSERT ON entity_research_run DEFERRABLE INITIALLY DEFERRED "
        "FOR EACH ROW EXECUTE FUNCTION validate_entity_research_contact_run_complete()"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION contact_research_selection_cancellation_guard()
        RETURNS trigger AS $$
        DECLARE
            selection_scope record;
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'contact research selection cancellations are append-only';
            END IF;
            SELECT selection.workspace_id, selection.project_run_id, selection.account_id
            INTO selection_scope
            FROM contact_research_selection selection
            WHERE selection.id=NEW.selection_id AND selection.workspace_id=NEW.workspace_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'contact research selection cancellation crosses scope';
            END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended(
                selection_scope.workspace_id || ':' || selection_scope.project_run_id::text ||
                ':' || selection_scope.account_id::text,
                0
            ));
            IF EXISTS (
                SELECT 1 FROM entity_research_run run
                JOIN entity_research_job job USING (research_run_id)
                WHERE run.workspace_id=NEW.workspace_id
                  AND run.contact_selection_id=NEW.selection_id
                  AND job.state <> 'terminal'
            ) THEN
                RAISE EXCEPTION
                    'active contact research must terminate before selection cancellation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_entity_research_contact_authority_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_TABLE_NAME='entity_research_run' THEN
                RAISE EXCEPTION 'entity research contact selection authority is immutable';
            END IF;
            RAISE EXCEPTION 'entity research contact launch authority is append-only';
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER entity_research_run_contact_selection_immutable BEFORE UPDATE OF "
        "contact_selection_id ON entity_research_run FOR EACH ROW WHEN "
        "(OLD.contact_selection_id IS DISTINCT FROM NEW.contact_selection_id) EXECUTE FUNCTION "
        "reject_entity_research_contact_authority_mutation()"
    )
    for table in (
        "entity_research_contact_launch",
        "entity_research_contact_job_authority",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION "
            "reject_entity_research_contact_authority_mutation()"
        )


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION contact_research_selection_cancellation_guard()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'contact research selection cancellations are append-only';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in (
        "entity_research_contact_job_authority",
        "entity_research_contact_launch",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}")
    op.execute(
        "DROP TRIGGER IF EXISTS entity_research_run_contact_selection_immutable "
        "ON entity_research_run"
    )
    op.execute("DROP FUNCTION IF EXISTS reject_entity_research_contact_authority_mutation()")
    op.execute("DROP TRIGGER IF EXISTS entity_research_contact_run_complete ON entity_research_run")
    op.execute("DROP FUNCTION IF EXISTS validate_entity_research_contact_run_complete()")
    op.execute(
        "DROP TRIGGER IF EXISTS entity_research_contact_job_scope "
        "ON entity_research_contact_job_authority"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS entity_research_contact_launch_scope "
        "ON entity_research_contact_launch"
    )
    op.execute("DROP FUNCTION IF EXISTS validate_entity_research_contact_launch_row()")
    op.execute("DROP TABLE IF EXISTS entity_research_contact_job_authority")
    op.execute("DROP TABLE IF EXISTS entity_research_contact_launch")
    op.execute(
        "ALTER TABLE entity_research_run DROP CONSTRAINT IF EXISTS "
        "entity_research_run_contact_selection_fk, DROP CONSTRAINT IF EXISTS "
        "entity_research_run_contact_selection_shape, DROP COLUMN IF EXISTS "
        "contact_selection_id"
    )
    # A downgrade is valid only after R7 human-initial selections have been removed with the
    # owning isolated test database.  Existing M8C values satisfy the restored closed enum.
    op.execute(
        "ALTER TABLE contact_research_selection_approval DROP CONSTRAINT "
        "contact_research_selection_approval_kind, ADD CONSTRAINT "
        "contact_research_selection_approval_kind CHECK (("
        "authority_kind='directive_confirmation' AND predecessor_id IS NULL) OR "
        "(authority_kind='human_successor' AND predecessor_id IS NOT NULL))"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION contact_research_selection_approval_guard() RETURNS trigger AS $$
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
               OR (NEW.body_json#>>'{research_directive,directive_id}')::uuid <> NEW.directive_id
               OR (NEW.body_json#>>'{research_directive,version}')::integer <> NEW.directive_version
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
