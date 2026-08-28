"""web fragment kit rebinding (clone-fidelity F2.2)

A fragment's row is immutable because the row IS its content — the id is the sha256 of the
artifact, so anything that changed the markup, the CSS, the digests or the slots would be a
different fragment and the trigger installed by ``611add94c5a4`` says so.

``source_kit_id`` / ``source_kit_version`` are the one pair on that row that is **not** content.
They record which capture minted this section, and they are what the brand-kit approval flow
reads to decide whose approval releases it. Freezing them created a trap: re-ingesting the same
site publishes kit version 2, the re-mint converges onto the version-1 row it already wrote
(``ON CONFLICT DO NOTHING``), and the row stays pointed at version 1 — so approving version 2
flips nothing and that fragment sits ``draft`` forever with no surface that can release it.

So the trigger is relaxed for exactly that pair. Everything that defines the artifact —
``payload_digest``, ``preview_digest``, ``provenance_json``, ``source_url``, ``section_role``,
``label``, the ids, ``created_at`` — stays frozen, and the composite FK to
``design_brand_kit`` still forces any new binding to be a kit in the SAME workspace. The policy
about which rebindings are legitimate (forward, within one lineage, never sideways into another
brand's) lives in ``clue_design.web_fragments.insert_web_fragment``, where it can be read and
tested, rather than being spelled twice.

Revision ID: 20757986d457
Revises: 611add94c5a4
Create Date: 2026-08-27
"""

from alembic import op

revision = "20757986d457"
down_revision = "611add94c5a4"
branch_labels = None
depends_on = None


_RELAXED = """
CREATE OR REPLACE FUNCTION design_web_fragment_reject_content_update() RETURNS trigger AS $$
BEGIN
    IF (NEW.fragment_id, NEW.workspace_id,
        NEW.source_url, NEW.section_role, NEW.label, NEW.payload_digest,
        NEW.preview_digest, NEW.provenance_json, NEW.created_at)
       IS DISTINCT FROM
       (OLD.fragment_id, OLD.workspace_id,
        OLD.source_url, OLD.section_role, OLD.label, OLD.payload_digest,
        OLD.preview_digest, OLD.provenance_json, OLD.created_at)
    THEN
        RAISE EXCEPTION
            'design_web_fragment is immutable (content-addressed): only status and the '
            'source brand-kit binding may change. Mint a new fragment instead of editing one.';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""

_ORIGINAL = """
CREATE OR REPLACE FUNCTION design_web_fragment_reject_content_update() RETURNS trigger AS $$
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


def upgrade() -> None:
    op.execute(_RELAXED)


def downgrade() -> None:
    op.execute(_ORIGINAL)
