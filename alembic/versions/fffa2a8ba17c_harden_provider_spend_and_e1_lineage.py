"""harden provider spend and e1 lineage

Revision ID: fffa2a8ba17c
Revises: f2c0b2ed21dd
Create Date: 2026-08-03 10:38:23.227990+00:00

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
revision: str = "fffa2a8ba17c"
down_revision: str | None = "f2c0b2ed21dd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Some long-lived D4 databases applied an early form of 413e800f79b5 that created a global
    # review-task FK before that revision was corrected to the workspace-composite contract. A
    # clean migration chain is already correct; this idempotent block repairs only the historical
    # drift so a foreign tenant cannot attach another workspace's identity-review decision.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'discovery_candidate_link'::regclass
                  AND conname = 'discovery_candidate_link_review_task_id_fkey'
            ) THEN
                ALTER TABLE discovery_candidate_link
                    DROP CONSTRAINT discovery_candidate_link_review_task_id_fkey;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'identity_review_task'::regclass
                  AND conname = 'identity_review_task_workspace_anchor'
            ) THEN
                ALTER TABLE identity_review_task ADD CONSTRAINT
                    identity_review_task_workspace_anchor UNIQUE (id, workspace_id);
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'discovery_candidate_link'::regclass
                  AND conname = 'discovery_candidate_review_task_workspace_fk'
            ) THEN
                ALTER TABLE discovery_candidate_link ADD CONSTRAINT
                    discovery_candidate_review_task_workspace_fk
                    FOREIGN KEY (review_task_id, workspace_id)
                    REFERENCES identity_review_task (id, workspace_id);
            END IF;
        END;
        $$
        """
    )
    op.execute(
        "ALTER TABLE discovery_candidate_link DROP CONSTRAINT discovery_candidate_link_shape"
    )
    op.execute(
        """
        ALTER TABLE discovery_candidate_link
        ADD CONSTRAINT discovery_candidate_link_shape CHECK (
            (admission_status = 'pending' AND account_entity_id IS NULL
                AND survivor_entity_id IS NULL AND disposition_reason IS NULL
                AND review_task_id IS NULL)
            OR (admission_status = 'review_required' AND account_entity_id IS NULL
                AND survivor_entity_id IS NULL AND disposition_reason IS NULL
                AND review_task_id IS NOT NULL)
            OR (admission_status = 'admitted' AND account_entity_id IS NOT NULL
                AND survivor_entity_id = account_entity_id AND disposition_reason IS NULL)
            OR (admission_status = 'merged' AND account_entity_id IS NOT NULL
                AND survivor_entity_id IS NOT NULL
                AND survivor_entity_id <> account_entity_id
                AND disposition_reason IS NOT NULL)
            OR (admission_status = 'excluded' AND account_entity_id IS NULL
                AND survivor_entity_id IS NULL AND disposition_reason IS NOT NULL)
        )
        """
    )

    # Once an E1 operation reaches a terminal or spend-quarantine state, the accounting and
    # evidence tuple is permanent. Operator recovery from an unknown spend outcome must be an
    # explicit future adjudication record, never an in-place rewrite of the paid ledger.
    op.execute(
        """
        CREATE FUNCTION targeted_enrichment_reject_terminal_mutation() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'targeted enrichment operations cannot be deleted';
            END IF;
            IF OLD.state IN (
                'succeeded', 'failed_terminal', 'spend_outcome_unknown', 'cancelled'
            ) AND NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION 'terminal targeted enrichment operation is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER targeted_enrichment_operation_terminal_immutable "
        "BEFORE UPDATE OR DELETE ON targeted_enrichment_operation FOR EACH ROW "
        "EXECUTE FUNCTION targeted_enrichment_reject_terminal_mutation()"
    )

    # The globally unique claim id alone did not prove tenant/entity/field lineage. These triggers
    # make both the selected-tier authorization and every resolved field claim fail closed at the
    # database boundary.
    op.execute(
        """
        CREATE FUNCTION targeted_enrichment_validate_tier_claim() RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM claim
                 WHERE id = NEW.tier_claim_id
                   AND workspace_id = NEW.workspace_id
                   AND entity_id = NEW.account_id
                   AND field_key = 'account.scoring.tier'
                   AND superseded_by IS NULL
            ) THEN
                RAISE EXCEPTION
                    'targeted enrichment tier claim must be live and match workspace/account/field';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER targeted_enrichment_target_tier_claim_lineage "
        "BEFORE INSERT OR UPDATE OF tier_claim_id, workspace_id, account_id "
        "ON targeted_enrichment_target FOR EACH ROW "
        "EXECUTE FUNCTION targeted_enrichment_validate_tier_claim()"
    )
    op.execute(
        """
        CREATE FUNCTION targeted_enrichment_validate_result_claim() RETURNS trigger AS $$
        BEGIN
            IF NEW.claim_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM claim
                 WHERE id = NEW.claim_id
                   AND entity_id = NEW.account_id
                   AND field_key = NEW.field_key
                   AND (
                       workspace_id = NEW.workspace_id
                       OR (workspace_id IS NULL AND reuse_scope = 'public_footprint')
                   )
            ) THEN
                RAISE EXCEPTION
                    'targeted enrichment result claim must match workspace/account/field';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER targeted_enrichment_result_claim_lineage "
        "BEFORE INSERT OR UPDATE OF claim_id, workspace_id, account_id, field_key "
        "ON targeted_enrichment_field_result FOR EACH ROW "
        "EXECUTE FUNCTION targeted_enrichment_validate_result_claim()"
    )

    # A differently bundled request must not repurchase the same account/field in the same
    # observation window. All E1 reservations serialize on project_run before inserting these rows,
    # so this cross-operation check is race-safe on the supported write path.
    op.execute(
        """
        CREATE FUNCTION targeted_enrichment_reject_overlapping_field() RETURNS trigger AS $$
        BEGIN
            IF EXISTS (
                SELECT 1
                  FROM targeted_enrichment_field_result prior
                  JOIN targeted_enrichment_operation prior_operation
                    ON prior_operation.id = prior.operation_id
                   AND prior_operation.workspace_id = prior.workspace_id
                  JOIN targeted_enrichment_operation new_operation
                    ON new_operation.id = NEW.operation_id
                   AND new_operation.workspace_id = NEW.workspace_id
                 WHERE prior.workspace_id = NEW.workspace_id
                   AND prior.account_id = NEW.account_id
                   AND prior.field_key = NEW.field_key
                   AND prior.operation_id <> NEW.operation_id
                   AND prior_operation.observation_window = new_operation.observation_window
            ) THEN
                RAISE EXCEPTION
                    'targeted enrichment field already reserved in this observation window';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER targeted_enrichment_field_no_overlap "
        "BEFORE INSERT ON targeted_enrichment_field_result FOR EACH ROW "
        "EXECUTE FUNCTION targeted_enrichment_reject_overlapping_field()"
    )

    # D6 and E1 ledgers predate project-run settlement. Bring existing terminal charges into the
    # shared burn-down once; new terminal transitions are settled transactionally by the runtime.
    op.execute(
        """
        WITH provider_charge AS (
            SELECT project_run_id, sum(cost_cents_charged) AS cost
            FROM (
                SELECT batch.project_run_id, operation.cost_cents_charged
                FROM discovery_operation operation
                JOIN discovery_batch batch
                  ON batch.id = operation.batch_id
                 AND batch.workspace_id = operation.workspace_id
                WHERE operation.state = 'succeeded'
                UNION ALL
                SELECT operation.project_run_id, operation.cost_cents_charged
                FROM targeted_enrichment_operation operation
                WHERE operation.state = 'succeeded'
            ) charged
            GROUP BY project_run_id
        )
        UPDATE project_run run
           SET spent_cents = run.spent_cents + provider_charge.cost,
               updated_at = now()
          FROM provider_charge
         WHERE run.id = provider_charge.project_run_id
        """
    )


def downgrade() -> None:
    # The preceding D4 revision's canonical schema already contains the workspace-composite review
    # FK. Keep the repaired form when stepping back to it; only this revision's new E1/provider
    # guards and accounting backfill are reversed below.
    # Reverse both the historical backfill and all transactional provider settlements made while
    # this revision was active; unrelated project spend remains intact.
    op.execute(
        """
        WITH provider_charge AS (
            SELECT project_run_id, sum(cost_cents_charged) AS cost
            FROM (
                SELECT batch.project_run_id, operation.cost_cents_charged
                FROM discovery_operation operation
                JOIN discovery_batch batch
                  ON batch.id = operation.batch_id
                 AND batch.workspace_id = operation.workspace_id
                WHERE operation.state = 'succeeded'
                UNION ALL
                SELECT operation.project_run_id, operation.cost_cents_charged
                FROM targeted_enrichment_operation operation
                WHERE operation.state = 'succeeded'
            ) charged
            GROUP BY project_run_id
        )
        UPDATE project_run run
           SET spent_cents = greatest(0, run.spent_cents - provider_charge.cost),
               updated_at = now()
          FROM provider_charge
         WHERE run.id = provider_charge.project_run_id
        """
    )
    op.execute(
        "DROP TRIGGER targeted_enrichment_field_no_overlap ON targeted_enrichment_field_result"
    )
    op.execute("DROP FUNCTION targeted_enrichment_reject_overlapping_field()")
    op.execute(
        "DROP TRIGGER targeted_enrichment_result_claim_lineage ON targeted_enrichment_field_result"
    )
    op.execute("DROP FUNCTION targeted_enrichment_validate_result_claim()")
    op.execute(
        "DROP TRIGGER targeted_enrichment_target_tier_claim_lineage ON targeted_enrichment_target"
    )
    op.execute("DROP FUNCTION targeted_enrichment_validate_tier_claim()")
    op.execute(
        "DROP TRIGGER targeted_enrichment_operation_terminal_immutable "
        "ON targeted_enrichment_operation"
    )
    op.execute("DROP FUNCTION targeted_enrichment_reject_terminal_mutation()")
