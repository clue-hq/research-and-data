"""design site snapshot capture custody (clone F0.1)

Revision ID: 4fb8a2ff791b
Revises: 50ce19bf5ef7
Create Date: 2026-08-26

One table, ``design_site_snapshot``: what a website ingestion actually SAW, kept.

Until now a website ingestion built a ``SiteSnapshot`` in memory — the post-JS HTML, every
stylesheet it fetched, and (on the rendered tier) a full-page screenshot — handed it to the
evidence builder, and dropped it. Only ``BrandEvidence`` survived, and evidence is a summary:
colors, fonts, a handful of measurements. Nothing downstream could ever go back and read the
markup or the CSS the brand actually ships, which is precisely what a section-level clone needs
(clone-fidelity plan, phase F0.1/F0.4).

**Bytes are not here.** They live in the design blob namespace (``{workspace}/design/{sha256}``,
ruling R-D4-2) with an ``artifact`` row apiece, written through
``clue_design.storage.register_design_bytes`` under the new ``source_key``
``design_site_snapshot``. This row holds the DIGESTS, which makes re-ingesting an unchanged site
free: content addressing collapses identical html/css/screenshot bytes onto the blobs already
stored, and only the row is new.

**One row per (job, page).** ``page_index`` 0 is the entry page; a multi-page capture (F0.4) adds
its pages in order. ``snapshot_id`` is derived from ``(job_id, page_url)`` — the same pair the
UNIQUE constraint protects — so a re-offered job (the D5 Round C reaper re-offers a worker that
died mid-flight) converges on the rows its earlier attempt wrote instead of accumulating a second
copy of every page. The UNIQUE constraint is what makes that convergence a guarantee rather than
a habit: a caller that mints an id its own way and collides on ``(job_id, page_url)`` is refused
by the database.

The job link is a COMPOSITE foreign key, which needs a matching unique constraint on the parent —
so ``design_ingestion_job`` gains ``UNIQUE (job_id, workspace_id)`` (redundant with its primary
key, and that is the point: it is the addressable target that makes the child's tenancy
structural). Without it a snapshot row could name a job in another workspace, and design tenancy
laws are structural here, not handler code.

``ON DELETE RESTRICT``, deliberately, and NOT cascade. A snapshot row is **durable clone source**
— phase F2's section harvest reads the html and CSS out of it — not execution-plane bookkeeping
that happens to be keyed to a job. The sibling precedent is explicit about the same species:
migration ``50ce19bf5ef7`` kept ``design_ad_creative.harvest_job_id`` a recorded reference rather
than an FK precisely so no future job pruner could silently delete a brand's references by
deleting the job that fetched them. Here the FK earns its place (it is what makes the child's
tenancy structural), so the coupling is broken the other way instead: RESTRICT keeps referential
integrity AND makes a job pruner that meets clone-source rows fail LOUDLY against them rather
than destroy them. Loud, not silent, is this phase's whole theme. A pruner that genuinely wants
those rows gone deletes them explicitly, which is a decision someone made rather than a
side effect nobody saw.

The BLOBS are not reachable from either direction: they are content-addressed artifacts with
their own custody, and the asset/blob GC owns the decision to destroy bytes.

Hand-written and reversible: ``downgrade()`` drops the table and the parent's added constraint.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4fb8a2ff791b"
down_revision: str | None = "50ce19bf5ef7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The composite FK target. Redundant with design_ingestion_job's primary key on job_id
    # alone; it exists so a child row can reference (job_id, workspace_id) as a unit.
    op.execute(
        "ALTER TABLE design_ingestion_job "
        "ADD CONSTRAINT design_ingestion_job_workspace_unique UNIQUE (job_id, workspace_id)"
    )

    op.execute(
        """
        CREATE TABLE design_site_snapshot (
            snapshot_id   text NOT NULL,
            workspace_id  text NOT NULL,
            job_id        text NOT NULL,
            page_url      text NOT NULL,
            page_index    integer NOT NULL,
            html_digest   text NOT NULL,
            stylesheets_json jsonb NOT NULL DEFAULT '[]'::jsonb,
            screenshot_digest text,
            viewport_width    integer,
            captured_at   timestamptz NOT NULL,
            meta_json     jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at    timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT design_site_snapshot_pkey PRIMARY KEY (snapshot_id),
            -- Tenancy is structural: the snapshot and its job are one workspace's, together.
            -- RESTRICT, not CASCADE — these rows are durable clone source, and a job pruner
            -- must fail loudly against them rather than take them with the job (see docstring).
            CONSTRAINT design_site_snapshot_job_fk FOREIGN KEY (job_id, workspace_id)
                REFERENCES design_ingestion_job (job_id, workspace_id) ON DELETE RESTRICT,
            CONSTRAINT design_site_snapshot_job_page_unique UNIQUE (job_id, page_url),
            CONSTRAINT design_site_snapshot_page_index_nonneg CHECK (page_index >= 0),
            CONSTRAINT design_site_snapshot_stylesheets_array
                CHECK (jsonb_typeof(stylesheets_json) = 'array'),
            CONSTRAINT design_site_snapshot_meta_object
                CHECK (jsonb_typeof(meta_json) = 'object'),
            -- A digest names a blob; a malformed one names nothing and must not be storable.
            CONSTRAINT design_site_snapshot_html_digest_shape
                CHECK (html_digest ~ '^[0-9a-f]{64}$'),
            CONSTRAINT design_site_snapshot_screenshot_digest_shape
                CHECK (screenshot_digest IS NULL OR screenshot_digest ~ '^[0-9a-f]{64}$'),
            CONSTRAINT design_site_snapshot_viewport_positive
                CHECK (viewport_width IS NULL OR viewport_width > 0)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_site_snapshot IS 'What one website ingestion captured, kept "
        "(clone-fidelity F0.1): post-JS HTML, every fetched stylesheet and the full-page "
        "screenshot, content-addressed in the design blob namespace under source_key "
        "design_site_snapshot. One row per (ingestion job, page); page_index 0 is the entry "
        "page. screenshot_digest is NULL on the static tier, which has no rendered page to "
        "shoot. The screenshot doubles as the reference image for the screenshot-vs-source "
        "review gate. Durable clone source, not job bookkeeping: the job FK is ON DELETE "
        "RESTRICT, so deleting a job that captured pages fails loudly instead of destroying "
        "what a later clone tier reads.'"
    )
    op.execute(
        "CREATE INDEX design_site_snapshot_job "
        "ON design_site_snapshot (workspace_id, job_id, page_index)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE design_site_snapshot")
    op.execute(
        "ALTER TABLE design_ingestion_job DROP CONSTRAINT design_ingestion_job_workspace_unique"
    )
