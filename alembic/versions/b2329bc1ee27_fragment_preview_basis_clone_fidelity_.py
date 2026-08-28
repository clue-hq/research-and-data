"""fragment preview basis (clone-fidelity F3.2 fix round)

Revision ID: b2329bc1ee27
Revises: 1acd1b1d13f7
Create Date: 2026-08-28

**What P-7 asked for that ``1acd1b1d13f7`` did not deliver.** That migration let a picture be
attached to a fragment that had none. It did not record WHICH KIND of picture, and the ruling is
explicit that an isolation render must be *labeled as an isolation render, NOT a source-site
screenshot crop* — because the two are different evidence and a human activating a hidden clone is
deciding on the strength of one of them.

The label had nowhere durable to live. A fragment's ``provenance_json`` records
``preview_basis`` at MINT time (``measured`` / ``inferred-above-first-band`` / …) and is frozen
with the artifact, correctly — it is the mint's own account of what it saw. But a picture attached
later is not the mint's picture, and reading the mint's word for it produces two wrong answers:

* a repair's provenance names no basis at all, so its isolation render is silently **unlabelled**;
* a section the capture measured but could not crop (no screenshot stored — a branch the mint
  handles explicitly and warns about) is born ``preview_digest IS NULL`` with
  ``provenance.preview_basis = 'measured'``. Attach an isolation render to that row and the card
  reports a picture our own engine drew as a crop of the live site. That is the precise
  substitution P-7 forbids.

So the basis becomes a property of the PICTURE: one column beside ``preview_digest``, written by
the same one-way attach, under the same rule. NULL means "this row's picture, if any, is the one
the mint made, and provenance describes it" — which is true of every row that exists today, so the
column is born NULL and nothing is backfilled.

Two constraints state the pairing rather than trusting it: a basis may not exist without a picture
to be the basis OF, and it may not be empty. The trigger gains the mirror of the ``preview_digest``
clause: attachable once, never revised.

Reversible. ``downgrade()`` reinstalls the F3.2 trigger verbatim and drops the column, which
returns the card to reading provenance alone — the state this migration exists to correct, so the
downgrade is lossy in labelling only and destroys no picture.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2329bc1ee27"
down_revision: str | None = "1acd1b1d13f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: The F3.2b trigger: ``preview_basis`` joins ``preview_digest`` in the attach-once clause. They
#: are one fact in two columns — the picture and what kind of picture it is — so they get one rule.
_F32B_TRIGGER = """
CREATE OR REPLACE FUNCTION design_web_fragment_reject_content_update() RETURNS trigger AS $$
BEGIN
    IF OLD.preview_digest IS NOT NULL
       AND NEW.preview_digest IS DISTINCT FROM OLD.preview_digest
    THEN
        RAISE EXCEPTION
            'design_web_fragment.preview_digest is attached once and never replaced: this row '
            'already has a preview. Mint a new fragment instead of re-picturing one.';
    END IF;
    IF OLD.preview_basis IS NOT NULL
       AND NEW.preview_basis IS DISTINCT FROM OLD.preview_basis
    THEN
        RAISE EXCEPTION
            'design_web_fragment.preview_basis records how the attached picture was made and is '
            'never revised: a picture does not become a different kind of evidence later.';
    END IF;
    IF (NEW.fragment_id, NEW.workspace_id,
        NEW.source_url, NEW.section_role, NEW.label, NEW.payload_digest,
        NEW.provenance_json, NEW.created_at,
        NEW.derived_from, NEW.derived_reason)
       IS DISTINCT FROM
       (OLD.fragment_id, OLD.workspace_id,
        OLD.source_url, OLD.section_role, OLD.label, OLD.payload_digest,
        OLD.provenance_json, OLD.created_at,
        OLD.derived_from, OLD.derived_reason)
    THEN
        RAISE EXCEPTION
            'design_web_fragment is immutable (content-addressed): only status, the source '
            'brand-kit binding, the degraded marker and a first preview may change. Mint a new '
            'fragment instead of editing one.';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""

#: F3.2's, verbatim (``1acd1b1d13f7``) — the downgrade target.
_F32_TRIGGER = """
CREATE OR REPLACE FUNCTION design_web_fragment_reject_content_update() RETURNS trigger AS $$
BEGIN
    IF OLD.preview_digest IS NOT NULL
       AND NEW.preview_digest IS DISTINCT FROM OLD.preview_digest
    THEN
        RAISE EXCEPTION
            'design_web_fragment.preview_digest is attached once and never replaced: this row '
            'already has a preview. Mint a new fragment instead of re-picturing one.';
    END IF;
    IF (NEW.fragment_id, NEW.workspace_id,
        NEW.source_url, NEW.section_role, NEW.label, NEW.payload_digest,
        NEW.provenance_json, NEW.created_at,
        NEW.derived_from, NEW.derived_reason)
       IS DISTINCT FROM
       (OLD.fragment_id, OLD.workspace_id,
        OLD.source_url, OLD.section_role, OLD.label, OLD.payload_digest,
        OLD.provenance_json, OLD.created_at,
        OLD.derived_from, OLD.derived_reason)
    THEN
        RAISE EXCEPTION
            'design_web_fragment is immutable (content-addressed): only status, the source '
            'brand-kit binding, the degraded marker and a first preview may change. Mint a new '
            'fragment instead of editing one.';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE design_web_fragment
            ADD COLUMN preview_basis text,
            -- A basis with no picture is a leftover, and an empty one is not a label.
            ADD CONSTRAINT design_web_fragment_preview_basis_pair
                CHECK (preview_basis IS NULL
                       OR (preview_digest IS NOT NULL AND length(btrim(preview_basis)) > 0))
        """
    )
    op.execute(
        "COMMENT ON COLUMN design_web_fragment.preview_basis IS 'How the ATTACHED picture was "
        "made (F3.2, ruling P-7) — today only ''isolation_render''. NULL means the row''s "
        "picture, if any, is the mint''s own crop and provenance_json.preview_basis describes "
        "it. Attachable once, beside preview_digest, and never revised.'"
    )
    op.execute(_F32B_TRIGGER)


def downgrade() -> None:
    op.execute(_F32_TRIGGER)
    op.execute(
        """
        ALTER TABLE design_web_fragment
            DROP CONSTRAINT design_web_fragment_preview_basis_pair,
            DROP COLUMN preview_basis
        """
    )
