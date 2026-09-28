"""design web publish pages

Revision ID: 6893f29b6973
Revises: 6eff96862040
Create Date: 2026-09-03

F5 multi-page publishing: a published site is ONE HTML PER ROUTE, not one blob. Two tables, and
the split between them is the whole design.

``design_web_publish_revision_page`` is **history**: one row per ``(publish_id, route)``, born
with its immutable parent package and, like that parent, rejected on UPDATE and DELETE by
trigger (mirroring ``design_web_publish_revision_reject_update``/``_reject_delete`` from
``86a9ce389e6e``). A publish package's pages are part of its content address — they must be as
un-rewritable as the package itself, or rolling back to a revision would no longer restore what
that revision actually served.

``design_web_publish_page`` is **derived**: the materialized current site, one row per
``(workspace_id, slug, route)``, holding exactly the pages of whichever revision
``design_web_publish`` currently serves. Publishing replaces it wholesale (delete-then-insert
from the new revision's pages) so a route dropped from the new revision stops serving instead of
lingering; rollback re-materializes it from the revision that swaps back in. Because it is
derived it may be regenerated at any time from the revision pages, and it CASCADEs off the
publish row it decorates.

**Tenancy is structural**, as in every design table since the D1 port. The current-pages PK leads
with ``workspace_id`` and its FK targets ``design_web_publish (workspace_id, slug)``, so one
tenant's route is neither readable nor overwritable from another workspace.

The revision-pages table carries ``workspace_id`` too — it is *not* enough to key it on the
publish id, and that is not a stylistic point. ``publish_id`` is a CONTENT ADDRESS
(``webpub_<package_digest>``), so two workspaces that publish byte-identical output legitimately
mint the SAME id; that is exactly why ``design_web_publish_revision``'s own primary key is
``(publish_id, workspace_id)`` rather than ``publish_id``. A pages table keyed on
``(publish_id, route)`` would therefore let the second tenant's insert hit ``ON CONFLICT DO
NOTHING`` against the first tenant's rows and then serve them — a cross-tenant read of another
workspace's page bytes through a shared digest. Keyed ``(publish_id, workspace_id, route)`` with
a composite FK to the parent's real key, that is unrepresentable.

**Back-compat is deliberate.** ``design_web_publish.html`` keeps holding the site's ``/`` page,
so every pre-F5 reader is untouched, and a publish whose revision carried no pages simply
materializes zero rows — the serving layer reads that emptiness as "legacy single-html publish"
and falls back to ``html`` at ``/``. Nothing is backfilled: old revisions genuinely had one page.

Hand-written and reversible: ``downgrade()`` drops both tables and both trigger functions in
dependency order (CI runs up -> down -> up).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6893f29b6973"
down_revision: str | None = "6eff96862040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- design_web_publish_revision_page: immutable per-route history ------------------------
    op.execute(
        """
        CREATE TABLE design_web_publish_revision_page (
            publish_id   text NOT NULL,
            workspace_id text NOT NULL,
            route        text NOT NULL,
            page_id      text NOT NULL,
            html         text NOT NULL,
            html_digest  text NOT NULL,

            -- workspace_id is load-bearing, not decoration: publish_id is a content address
            -- two tenants can legitimately share. See the docstring.
            CONSTRAINT design_web_publish_revision_page_pkey
                PRIMARY KEY (publish_id, workspace_id, route),
            CONSTRAINT design_web_publish_revision_page_revision_fk
                FOREIGN KEY (publish_id, workspace_id)
                REFERENCES design_web_publish_revision (publish_id, workspace_id)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_web_publish_revision_page IS 'Per-route HTML of an immutable "
        "web publish package (F5): one row per (publish_id, workspace_id, route). Append-only "
        "like its parent — UPDATE and DELETE are rejected by trigger — because a package''s "
        "pages are part of what rolling back to it must restore. workspace_id is in the key "
        "because publish_id is a content address two tenants can share.'"
    )
    op.execute(
        """
        CREATE FUNCTION design_web_publish_revision_page_reject_update() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'design_web_publish_revision_page is immutable: a publish package''s pages are '
                'content-addressed history; publish a new package instead of updating one.';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE FUNCTION design_web_publish_revision_page_reject_delete() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'design_web_publish_revision_page is append-only: publish history is never '
                'deleted (unpublish flips design_web_publish.status, not history).';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER design_web_publish_revision_page_no_update "
        "BEFORE UPDATE ON design_web_publish_revision_page "
        "FOR EACH ROW EXECUTE FUNCTION design_web_publish_revision_page_reject_update()"
    )
    op.execute(
        "CREATE TRIGGER design_web_publish_revision_page_no_delete "
        "BEFORE DELETE ON design_web_publish_revision_page "
        "FOR EACH ROW EXECUTE FUNCTION design_web_publish_revision_page_reject_delete()"
    )

    # --- design_web_publish_page: the materialized current site -------------------------------
    op.execute(
        """
        CREATE TABLE design_web_publish_page (
            workspace_id text NOT NULL,
            slug         text NOT NULL,
            route        text NOT NULL,
            page_id      text NOT NULL,
            html         text NOT NULL,
            html_digest  text NOT NULL,

            -- Workspace-first, like every design table since the D1 port.
            CONSTRAINT design_web_publish_page_pkey PRIMARY KEY (workspace_id, slug, route),
            -- Derived from the publish row it decorates: it dies with it.
            CONSTRAINT design_web_publish_page_publish_fk FOREIGN KEY (workspace_id, slug)
                REFERENCES design_web_publish (workspace_id, slug) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_web_publish_page IS 'The materialized current site (F5): one "
        "row per (workspace, slug, route), holding exactly the pages of the revision "
        "design_web_publish currently serves. Derived — publishing replaces it wholesale and "
        "rollback re-materializes it from the revision that swaps back in, so a route dropped "
        "from a new revision stops serving. Zero rows means a legacy single-html publish, whose "
        "/ page is design_web_publish.html.'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE design_web_publish_page")
    op.execute("DROP TABLE design_web_publish_revision_page")
    op.execute("DROP FUNCTION design_web_publish_revision_page_reject_update()")
    op.execute("DROP FUNCTION design_web_publish_revision_page_reject_delete()")
