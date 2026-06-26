"""m13.3 learning loop (config_revision ledger)

Revision ID: 15b6b816abe4
Revises: f9483ab9aafa
Create Date: 2026-06-26 20:25:16.175433+00:00

M13.3's learning loop reweights source profiles (M4.6) and the fit/intent scoring rubric (M3.4)
from measured outcomes, as **versioned config revisions, never in-place mutation**. This table is
the governance **ledger**: a proposal (``status=proposed``) carries the full new payload;
``promote`` writes the real versioned store (a new ``icp_spec`` version for a rubric, a new
``source_profile_override`` version for a profile) and stamps the row ``promoted`` +
``applied_version``. The engine (M6 scorer, M4 planner) reads the existing stores — never this
table — so reproducibility (a run started before a promotion keeps its pinned version) holds for
free. No change to ``claim`` / ``disposition`` / ``account_handoff`` / ``source_yield`` (the metric
table is extended read-side only, no DDL).

Enums (``config_revision_target`` / ``config_revision_status``) mirror ``core.enums``
(``ConfigRevisionTarget`` / ``ConfigRevisionStatus``); parity-tested in ``tests/review/`` (the same
StrEnum discipline as the M13.1/M13.2 enums). ``PromotionMode`` is a runtime arg, not a column.

Soft FK (no ``REFERENCES``, like ``claim``/``disposition``): ``config_revision.parent_revision`` is
the prior revision in the proposal lineage; integrity is enforced in the write path so milestone
migrations stay order-independent.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "15b6b816abe4"
down_revision: str | None = "f9483ab9aafa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. enums (mirror core.enums.ConfigRevisionTarget / ConfigRevisionStatus) ------------------
    op.execute("CREATE TYPE config_revision_target AS ENUM ('source_profile', 'scoring_rubric')")
    op.execute("CREATE TYPE config_revision_status AS ENUM ('proposed', 'promoted', 'rejected')")
    # Extend icp_created_from so a promoted rubric reweight stamps an accurate provenance on the new
    # icp_spec version it writes (mirrors core.enums ICPCreatedFrom.FEEDBACK_REWEIGHT, appended).
    op.execute("ALTER TYPE icp_created_from ADD VALUE IF NOT EXISTS 'feedback_reweight'")

    # 2. config_revision: the audited proposal/promotion ledger ---------------------------------
    op.execute(
        """
        CREATE TABLE config_revision (
            id                uuid NOT NULL,
            target            config_revision_target NOT NULL,
            client_id         text NOT NULL,
            icp_key           text NOT NULL DEFAULT '',
            -- the parent ICP-spec version the revision was derived from (D5: per icp_key+version).
            icp_spec_version  int NOT NULL,
            -- the prior config_revision in the proposal lineage (soft self-FK; NULL for the first).
            parent_revision   uuid,
            -- the full new payload: a serialized icp_spec.scoring_rubric slot, or the full new
            -- source_profile_override weighted_sources slots keyed by (pack_key, field_class).
            payload_json      jsonb NOT NULL,
            -- the proposal's provenance: {dataset_ref | yield_metrics_ref} it was derived from.
            derived_from_json jsonb NOT NULL DEFAULT '{}'::jsonb,
            -- the decomposed, per-moved-weight rationale (the explainability surface, AC: "which
            -- signals and disposition outcomes drove the change").
            explanation_json  jsonb NOT NULL DEFAULT '{}'::jsonb,
            -- whether every weight move was within the auto-promote bound (the gate signal: an
            -- out-of-bounds move requires PromotionMode.HUMAN).
            within_bounds     boolean NOT NULL DEFAULT true,
            status            config_revision_status NOT NULL DEFAULT 'proposed',
            proposed_by       text,
            proposed_at       timestamptz NOT NULL DEFAULT now(),
            promoted_by       text,
            promoted_at       timestamptz,
            -- the target store version this revision produced on promote (the audit link to the new
            -- icp_spec.version / source_profile_override.version); NULL until promoted.
            applied_version   int,
            created_at        timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT config_revision_pkey PRIMARY KEY (id),
            -- Proposal idempotency + lineage: one proposal per (target, scope, parent). NULLS NOT
            -- DISTINCT (pg15+) so a NULL parent (first proposal) doesn't admit duplicate
            -- same-parent proposals (mirrors 0009 source_profile_*_slot).
            CONSTRAINT config_revision_lineage UNIQUE NULLS NOT DISTINCT
                (target, client_id, icp_key, icp_spec_version, parent_revision),
            CONSTRAINT config_revision_icp_version_positive CHECK (icp_spec_version >= 1),
            CONSTRAINT config_revision_applied_version_positive
                CHECK (applied_version IS NULL OR applied_version >= 1),
            -- A promoted revision has its promotion timestamp; a proposed/rejected one does not.
            CONSTRAINT config_revision_promoted_stamp CHECK (
                (status = 'promoted') = (promoted_at IS NOT NULL)
            ),
            -- applied_version is set only by a promotion.
            CONSTRAINT config_revision_applied_iff_promoted CHECK (
                applied_version IS NULL OR status = 'promoted'
            ),
            -- the lineage self-reference never points at itself.
            CONSTRAINT config_revision_parent_not_self CHECK (parent_revision IS DISTINCT FROM id)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE config_revision IS 'M13.3 learning-loop governance ledger: one row per "
        "proposed source-profile/scoring-rubric reweight (substrate 9). promote() writes the real "
        "versioned store (icp_spec / source_profile_override) and stamps the row promoted + "
        "applied_version; the engine reads the stores, never this ledger. Append-only audit.'"
    )

    # Read paths: the latest revision per scope/target, and finding open (proposed) revisions.
    op.execute(
        "CREATE INDEX config_revision_scope ON config_revision "
        "(client_id, icp_key, target, icp_spec_version)"
    )
    op.execute("CREATE INDEX config_revision_status ON config_revision (status)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS config_revision")
    op.execute("DROP TYPE IF EXISTS config_revision_status")
    op.execute("DROP TYPE IF EXISTS config_revision_target")
    # The 'feedback_reweight' label added to icp_created_from is left in place — Postgres has no
    # ALTER TYPE ... DROP VALUE; a documented no-op (same as the M13.1 campaign_phase 'review' add).
