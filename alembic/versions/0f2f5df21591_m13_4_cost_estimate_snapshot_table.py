"""m13_4 cost_estimate snapshot table

Revision ID: 0f2f5df21591
Revises: c48ebe0a1e62
Create Date: 2026-06-26 01:25:33.754454+00:00

M13.4 adds the **``cost_estimate``** snapshot table — the durable pre-run cost projection the
client-facing observability surface records (Doc C §5: "~N discovered → ~M go deep → est \\$X",
recomputed as the tier cutoffs change at the M6.4 checkpoint). It is the one materialization the
otherwise read-only :class:`~clue_research.review.ObservabilitySurface` writes (the interface allows
writing/refreshing materialized views only — never the domain write path).

**Append-only snapshots.** Each ``pre_run_estimate`` call appends one row, so the table is the
history of estimates as cutoffs are adjusted — read latest-by-``computed_at`` per run. There is no
UNIQUE scope key (multiple snapshots per run is the point); the ``(campaign_run_id, computed_at)``
index serves the "latest estimate for this run" read.

Conventions: numeric money columns (``numeric``, exact for budget sums) with named non-negative
CHECKs (mirroring ``source_yield`` / ``handoff_event``); counts CHECKed non-negative; the
``cutoffs_json`` JSONB is the tier→cutoff map the estimate was computed against; PK defaults to
``gen_random_uuid()`` (PG13+ builtin — no extension). **No new PG enum** (zero enum-parity burden).
Soft FK on ``campaign_run_id`` (no ``REFERENCES``, mirroring ``handoff_event`` / ``claim`` so
milestone migrations stay order-independent; integrity is enforced in the write path).

``downgrade()`` drops the index then the table (CI runs up → down → up); no enum/type/trigger to
reverse, so the "no domain tables at the M0 head" invariant stays green automatically.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0f2f5df21591"
down_revision: str | None = "c48ebe0a1e62"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE cost_estimate (
            id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            campaign_run_id      uuid NOT NULL,
            icp_spec_version     int NOT NULL DEFAULT 1,
            discovered_count     int NOT NULL,
            projected_deep_count int NOT NULL,
            cutoffs_json         jsonb NOT NULL DEFAULT '{}'::jsonb,
            estimated_cents      numeric NOT NULL DEFAULT 0,
            computed_at          timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT cost_estimate_icp_version_positive CHECK (icp_spec_version >= 1),
            CONSTRAINT cost_estimate_discovered_nonneg CHECK (discovered_count >= 0),
            CONSTRAINT cost_estimate_projected_nonneg CHECK (projected_deep_count >= 0),
            CONSTRAINT cost_estimate_estimated_nonneg CHECK (estimated_cents >= 0)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE cost_estimate IS 'M13.4 pre-run cost-estimate snapshots (Doc C §5): one "
        "row per recompute (~N discovered -> ~M deep -> est $X), appended as tier cutoffs change. "
        "The one materialization the read-only ObservabilitySurface writes; read latest-by-"
        "computed_at per campaign_run.'"
    )
    # Latest-snapshot read: a run's estimates newest-first.
    op.execute(
        "CREATE INDEX cost_estimate_run_computed "
        "ON cost_estimate (campaign_run_id, computed_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS cost_estimate_run_computed")
    op.execute("DROP TABLE IF EXISTS cost_estimate")
