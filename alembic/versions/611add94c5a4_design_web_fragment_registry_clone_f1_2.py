"""design web fragment registry (clone F1.2)

Revision ID: 611add94c5a4
Revises: 4fb8a2ff791b
Create Date: 2026-08-27

One table, ``design_web_fragment``: the durable registry a ``WebNodeKind::Fragment`` document
node points AT.

F1.1 gave the web document a node kind for a verbatim cloned section — a leaf carrying only a
``frag_<16 hex>`` id and a bounded map of flat scalar slot values. It deliberately carries no
markup, because sanitization happens exactly ONCE, at artifact creation, and everything
downstream trusts stored artifact HTML absolutely. This table is the other end of that pointer.

**Bytes are not here**, exactly as with ``design_site_snapshot`` (F0.1, migration
``4fb8a2ff791b``). The artifact payload — sanitized html with its slot markers, CSS scoped under
the fragment's wrapper class, the digests of every asset it displays, the slot manifest, the
preview digest — is one content-addressed JSON blob in the design blob namespace
(``{workspace}/design/{sha256}``) under ``source_key = "design_web_fragment"``. The row holds
``payload_digest`` and the provenance that says where the section came from.

**The id IS the content**, so there is no update path for a payload: creation is the only write,
a re-mint of the same section converges onto the row it already wrote, and a different section is
a different id. The one mutable column is ``status`` — row-level metadata (has a human blessed
this section for reuse?), not payload mutation — and the trigger below enforces exactly that
split: any UPDATE that changes anything else raises. Its vocabulary MIRRORS the nearest existing
design registry lifecycle, ``design_brand_approval_status``: ``draft`` → ``approved`` →
``deprecated``. It is a CHECK on a text column rather than a new Postgres ENUM because that is
what every design table added since the D1 port does (``design_ad_creative``,
``design_site_snapshot``), and because ``clue_design.enums`` is explicitly the home of
vocabularies that were closed in the MERGED subsystem — this one is new.

``brand_approval_status``'s fourth member, ``generated_unreviewed``, is deliberately not mirrored:
it distinguishes a machine-built brand kit from a hand-built one, and EVERY fragment is machine
built, so the distinction would carry no information here.

**Tenancy is structural.** The primary key is ``(fragment_id, workspace_id)``, not the id alone.
The id is a global content address, so two tenants who clone the same public section legitimately
mint the same id — and under a single-column key the second one would collide with, or silently
read, the first one's row. Accounts and their enrichment are workspace-local by founder ruling
(2026-07-22); a cloned section is the same species of material and gets the same treatment. The
brand-kit link is a COMPOSITE foreign key through ``design_brand_kit_workspace_anchor``, so a
fragment cannot name another workspace's kit.

``ON DELETE RESTRICT`` on that link, following F0.1's ruling verbatim: a fragment is durable
clone material, not bookkeeping keyed to a kit. Deleting a brand kit that fathered fragments
fails LOUDLY rather than destroying the sections harvested from it; a caller that really wants
them gone deletes them on purpose. The kit link is nullable (born-nullable, the O2 precedent) —
a fragment can be minted from a page that was never turned into a kit — with a both-or-neither
CHECK so half a reference can never be stored.

Hand-written and reversible: ``downgrade()`` drops the table, its trigger and its function.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "611add94c5a4"
down_revision: str | None = "4fb8a2ff791b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE design_web_fragment (
            fragment_id     text NOT NULL,
            workspace_id    text NOT NULL,
            source_kit_id      text,
            source_kit_version integer,
            source_url      text NOT NULL,
            section_role    text NOT NULL,
            label           text,
            status          text NOT NULL DEFAULT 'draft',
            payload_digest  text NOT NULL,
            preview_digest  text,
            provenance_json jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at      timestamptz NOT NULL DEFAULT now(),
            updated_at      timestamptz NOT NULL DEFAULT now(),

            -- The id is a global content address; the ROW is one tenant's. See the docstring.
            CONSTRAINT design_web_fragment_pkey PRIMARY KEY (fragment_id, workspace_id),
            CONSTRAINT design_web_fragment_workspace_fk FOREIGN KEY (workspace_id)
                REFERENCES workspace (workspace_id),
            -- RESTRICT, not CASCADE: deleting the kit a section was harvested from must fail
            -- loudly, never take the section with it (F0.1's ruling, same species of material).
            CONSTRAINT design_web_fragment_kit_fk
                FOREIGN KEY (source_kit_id, source_kit_version, workspace_id)
                REFERENCES design_brand_kit (brand_kit_id, version, workspace_id)
                ON DELETE RESTRICT,
            CONSTRAINT design_web_fragment_kit_pair
                CHECK ((source_kit_id IS NULL) = (source_kit_version IS NULL)),
            -- The id is interpolated into a CSS class and an HTML wrapper class downstream, so
            -- an id carrying anything but lowercase hex is refused here rather than escaped
            -- there. Same grammar the engine enforces (lumen_web::doc::fragment_id_is_valid).
            CONSTRAINT design_web_fragment_id_shape
                CHECK (fragment_id ~ '^frag_[0-9a-f]{16}$'),
            CONSTRAINT design_web_fragment_payload_digest_shape
                CHECK (payload_digest ~ '^[0-9a-f]{64}$'),
            CONSTRAINT design_web_fragment_preview_digest_shape
                CHECK (preview_digest IS NULL OR preview_digest ~ '^[0-9a-f]{64}$'),
            CONSTRAINT design_web_fragment_status_known
                CHECK (status IN ('draft', 'approved', 'deprecated')),
            CONSTRAINT design_web_fragment_section_role_present
                CHECK (length(btrim(section_role)) > 0),
            CONSTRAINT design_web_fragment_source_url_present
                CHECK (length(btrim(source_url)) > 0),
            CONSTRAINT design_web_fragment_provenance_object
                CHECK (jsonb_typeof(provenance_json) = 'object')
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE design_web_fragment IS 'The fragment registry (clone-fidelity F1.2): "
        "one row per verbatim cloned website section, which a WebNodeKind::Fragment document "
        "node pins by id. The artifact payload — sanitized html with data-lumen-slot markers, "
        "CSS scoped under .lumen-frag-<id>, asset digests, slot manifest, preview digest — is a "
        "content-addressed JSON blob in the design blob namespace under source_key "
        "design_web_fragment; this row holds its digest and its provenance. Immutable except "
        "for status: the id is the content, so a re-mint converges and a change is a new "
        "fragment. Keyed (fragment_id, workspace_id) because the id is a global content address "
        "while the row is one tenant''s.'"
    )
    op.execute(
        """
        CREATE FUNCTION design_web_fragment_reject_content_update() RETURNS trigger AS $$
        BEGIN
            IF (NEW.fragment_id, NEW.workspace_id, NEW.source_kit_id, NEW.source_kit_version,
                NEW.source_url, NEW.section_role, NEW.label, NEW.payload_digest,
                NEW.preview_digest, NEW.provenance_json, NEW.created_at)
               IS DISTINCT FROM
               (OLD.fragment_id, OLD.workspace_id, OLD.source_kit_id, OLD.source_kit_version,
                OLD.source_url, OLD.section_role, OLD.label, OLD.payload_digest,
                OLD.preview_digest, OLD.provenance_json, OLD.created_at)
            THEN
                RAISE EXCEPTION
                    'design_web_fragment is immutable (content-addressed): only status may '
                    'change. Mint a new fragment instead of editing one.';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER design_web_fragment_no_content_update "
        "BEFORE UPDATE ON design_web_fragment "
        "FOR EACH ROW EXECUTE FUNCTION design_web_fragment_reject_content_update()"
    )
    # The picker's read: this workspace's fragments of one section role, newest first.
    op.execute(
        "CREATE INDEX design_web_fragment_role "
        "ON design_web_fragment (workspace_id, section_role, created_at DESC)"
    )
    # The provenance read: everything harvested from one brand kit's site.
    op.execute(
        "CREATE INDEX design_web_fragment_kit "
        "ON design_web_fragment (workspace_id, source_kit_id, source_kit_version)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE design_web_fragment")
    op.execute("DROP FUNCTION design_web_fragment_reject_content_update()")
