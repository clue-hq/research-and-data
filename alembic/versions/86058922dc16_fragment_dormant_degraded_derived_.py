"""fragment dormant status, degraded marker, repair lineage (clone-fidelity F3.0)

Revision ID: 86058922dc16
Revises: 20757986d457
Create Date: 2026-08-27

Three founder rulings (2026-08-28) land on ``design_web_fragment`` at once, and the point of
doing them in ONE migration is that they are three different KINDS of fact about the same row —
mixing them up is what the shape below exists to prevent.

**D-F8 — ``dormant`` is a STATUS.** A section the source site hides used to be dropped with a
loud diagnostic. It is now preserved, and preserved as something no automatic path can release:
the kit approval cascade only ever moves ``draft`` ⇄ ``approved`` so it steps over dormancy by
construction, default agent discovery is approved-only, the document-write gate refuses any pin
that is not ``approved``, and the only door out is a human — refused unless the row carries a
``preview_digest``, because activation without something to look at is not a human decision, it
is a click. So it belongs in the lifecycle vocabulary beside ``draft``/``approved``/
``deprecated``, and the CHECK is widened to hold it.

**D-F6 — ``degraded`` is a MARKER, not a status.** "This clone is broken" is orthogonal to
"has a human blessed it": the harvested original stays approved and stays pinnable while it is
the only thing that exists, and it is marked broken so the repair ladder can find it. Making it
a status would have forced a choice between the two facts and lost one of them. Hence a boolean
plus its reason, with a both-or-neither CHECK — a marker with no reason is an accusation nobody
can act on, and a reason with no marker is a leftover.

**D-F6 — ``derived_from``/``derived_reason`` is LINEAGE.** A repair never edits the original
(the original is evidence, and the table is content-addressed besides): it is a NEW fragment that
names the one it repairs and says why. The composite self-FK is what makes that a fact rather
than a hope — a lineage pointer resolves to a fragment THIS workspace holds, or the write fails.
``ON DELETE RESTRICT`` follows the kit link's own ruling: deleting the original a live repair
descends from fails loudly rather than orphaning the lineage.

**The immutability discipline is unchanged in kind.** The trigger installed by ``611add94c5a4``
and relaxed for the kit binding by ``20757986d457`` is relaxed once more, for the degraded marker
only: it is a JUDGEMENT about the section (the same species as ``status``), and F3.3's behavioural
review gate must be able to record one it makes later. Lineage joins the FROZEN half — how a row
came to exist cannot be rewritten — and everything that defines the artifact stays exactly as
frozen as it was.

Reversible. ``downgrade()`` restores the F2.2 trigger and the F1.2 status CHECK, and drops the
four columns with their constraints and index. Any row still ``dormant`` is moved to
``deprecated`` rather than to ``draft``: the old vocabulary has no word for "preserved but never
to be auto-released", and ``deprecated`` is the only member of it that a kit approval cannot
sweep up — demoting to ``draft`` would hand the cascade exactly the sections D-F8 exists to keep
away from it.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "86058922dc16"
down_revision: str | None = "20757986d457"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: Mutable: the lifecycle flag, the kit binding (``20757986d457``), and the degraded marker.
#: Everything else — including the new lineage pair — is the artifact or its origin story.
_F30_TRIGGER = """
CREATE OR REPLACE FUNCTION design_web_fragment_reject_content_update() RETURNS trigger AS $$
BEGIN
    IF (NEW.fragment_id, NEW.workspace_id,
        NEW.source_url, NEW.section_role, NEW.label, NEW.payload_digest,
        NEW.preview_digest, NEW.provenance_json, NEW.created_at,
        NEW.derived_from, NEW.derived_reason)
       IS DISTINCT FROM
       (OLD.fragment_id, OLD.workspace_id,
        OLD.source_url, OLD.section_role, OLD.label, OLD.payload_digest,
        OLD.preview_digest, OLD.provenance_json, OLD.created_at,
        OLD.derived_from, OLD.derived_reason)
    THEN
        RAISE EXCEPTION
            'design_web_fragment is immutable (content-addressed): only status, the source '
            'brand-kit binding and the degraded marker may change. Mint a new fragment instead '
            'of editing one.';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""

_F22_TRIGGER = """
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


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE design_web_fragment
            DROP CONSTRAINT design_web_fragment_status_known,
            ADD CONSTRAINT design_web_fragment_status_known
                CHECK (status IN ('draft', 'approved', 'deprecated', 'dormant'))
        """
    )
    op.execute(
        """
        ALTER TABLE design_web_fragment
            ADD COLUMN degraded        boolean NOT NULL DEFAULT false,
            ADD COLUMN degraded_reason text,
            ADD COLUMN derived_from    text,
            ADD COLUMN derived_reason  text,
            -- A marker with no reason is an accusation nobody can act on; a reason with no
            -- marker is a leftover. Both-or-neither, and the reason has to say something.
            ADD CONSTRAINT design_web_fragment_degraded_pair
                CHECK (degraded = (degraded_reason IS NOT NULL)
                       AND (degraded_reason IS NULL OR length(btrim(degraded_reason)) > 0)),
            ADD CONSTRAINT design_web_fragment_derived_pair
                CHECK ((derived_from IS NULL) = (derived_reason IS NULL)
                       AND (derived_reason IS NULL OR length(btrim(derived_reason)) > 0)),
            ADD CONSTRAINT design_web_fragment_derived_from_shape
                CHECK (derived_from IS NULL OR derived_from ~ '^frag_[0-9a-f]{16}$'),
            -- The id is a content address, so a fragment deriving from itself is not a cycle,
            -- it is a row claiming to repair the artifact it IS.
            ADD CONSTRAINT design_web_fragment_derived_not_self
                CHECK (derived_from IS NULL OR derived_from <> fragment_id),
            -- Tenancy is structural here for the same reason it is on the kit link: the id is a
            -- global content address, so a neighbour's fragment id is a REAL id.
            ADD CONSTRAINT design_web_fragment_derived_from_fk
                FOREIGN KEY (derived_from, workspace_id)
                REFERENCES design_web_fragment (fragment_id, workspace_id)
                ON DELETE RESTRICT
        """
    )
    op.execute(
        "COMMENT ON COLUMN design_web_fragment.degraded IS 'D-F6: this harvested clone is "
        "broken (today: dead scroll height detected at mint). Orthogonal to status — a degraded "
        "original stays approved and pinnable until its repair exists, because it is the "
        "evidence.'"
    )
    op.execute(
        "COMMENT ON COLUMN design_web_fragment.derived_from IS 'D-F6: the fragment this one "
        "repairs. A repair is a NEW fragment through the same sanitizer/mint path; the original "
        "is never edited.'"
    )
    # The lineage read: "what repaired this?" / "what is this a repair of?" — the inspector's.
    op.execute(
        "CREATE INDEX design_web_fragment_derived_from "
        "ON design_web_fragment (workspace_id, derived_from) "
        "WHERE derived_from IS NOT NULL"
    )
    op.execute(_F30_TRIGGER)


def downgrade() -> None:
    op.execute(_F22_TRIGGER)
    op.execute("DROP INDEX design_web_fragment_derived_from")
    op.execute(
        """
        ALTER TABLE design_web_fragment
            DROP CONSTRAINT design_web_fragment_derived_from_fk,
            DROP CONSTRAINT design_web_fragment_derived_not_self,
            DROP CONSTRAINT design_web_fragment_derived_from_shape,
            DROP CONSTRAINT design_web_fragment_derived_pair,
            DROP CONSTRAINT design_web_fragment_degraded_pair,
            DROP COLUMN derived_reason,
            DROP COLUMN derived_from,
            DROP COLUMN degraded_reason,
            DROP COLUMN degraded
        """
    )
    # See the module docstring: `deprecated`, never `draft` — the old vocabulary's only member a
    # kit approval cannot sweep up.
    op.execute("UPDATE design_web_fragment SET status = 'deprecated' WHERE status = 'dormant'")
    op.execute(
        """
        ALTER TABLE design_web_fragment
            DROP CONSTRAINT design_web_fragment_status_known,
            ADD CONSTRAINT design_web_fragment_status_known
                CHECK (status IN ('draft', 'approved', 'deprecated'))
        """
    )
