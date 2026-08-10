"""committee selection claims ride the project run

Revision ID: c6d84aa84b79
Revises: 0070930672a4
Create Date: 2026-08-06 19:26:00.763059+00:00

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
revision: str = "c6d84aa84b79"
down_revision: str | None = "0070930672a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Accept project-run-stamped committee claims in the selection guard.

    M8D stamps committee-discovery claims with the exact *project run*: the M8C C1 lineage
    trigger requires a Sumble professional claim's ``run_id`` to equal its ready operation's
    ``project_run_id``, and ``discover_committee`` stamps the whole committee set uniformly.
    Historical M8C rows rode the per-account deep run instead. The guard now accepts exactly
    those two run identities — first proven necessary by the R10 live canary, where a real
    admitted committee member could not be selected for contact research. Cross-account and
    cross-contact protection is unchanged: the claim must still be entity-bound to the exact
    target contact, current, and ``committee_discovery``-mode.
    """

    op.execute(_WIDENED_GUARD)


def downgrade() -> None:
    op.execute(_ACCOUNT_RUN_ONLY_GUARD)


_WIDENED_GUARD = r"""CREATE OR REPLACE FUNCTION public.contact_research_selection_guard()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
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
                          AND c.run_id IN (NEW.account_run_id, NEW.project_run_id)
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
        $function$

"""

_ACCOUNT_RUN_ONLY_GUARD = r"""CREATE OR REPLACE FUNCTION public.contact_research_selection_guard()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
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
        $function$

"""
