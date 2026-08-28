"""fragment isolation preview attach (clone-fidelity F3.2)

Revision ID: 1acd1b1d13f7
Revises: 86058922dc16
Create Date: 2026-08-28

One relaxation of the immutability trigger, for one column, in one direction: a row whose
``preview_digest`` is NULL may have one attached; a row that already has one may never have it
changed or removed.

**Why it has to move at all.** D-F8 makes a usable preview the condition a human activates a
dormant clone on, and a section the source site HIDES was never rendered — so the capture holds
no pixels of it, ``crop_extent`` correctly refuses to borrow a neighbour's, and every real dormant
fragment is born ``preview_digest IS NULL``. F3.0 recorded the consequence honestly: the activate
path always refuses, and the D-F8 loop cannot close until something renders the hidden section.
Orchestrator ruling **P-7** closes it with an ISOLATION RENDER — our engine rendering the
artifact's own harvested bytes — and says to store the result "as the fragment's preview through
the normal preview path so ``set_web_fragment_status`` succeeds". The trigger installed by
``611add94c5a4`` froze ``preview_digest``, so that store is exactly what this migration permits.
Ruling **R17-2** needs the same door for the same reason from the other side: a repair is minted
with no preview either, and a human asked to release one is being asked to approve a section
nobody can look at.

**Why one-way is the whole of it.** ``preview_digest`` is part of the artifact's IDENTITY bytes —
the fragment id is a sha256 that includes it — so a preview attached after the fact is
deliberately NOT content: it is a picture OF the content, taken later, by a different renderer,
and the payload's own record of what was minted stays exactly as it was. Filling an absent value
adds a fact; changing a present one would rewrite the picture a human already made a decision
against, and no path here needs to. So NULL → digest is allowed, digest → anything else is not,
and the message says which of the two happened.

Nothing else about the discipline moves: the payload, the provenance, the label, the ids,
``created_at`` and the lineage pair stay in the frozen tuple, and ``status``, the kit binding and
the degraded marker stay the mutable three.

Reversible. ``downgrade()`` reinstalls the F3.0 trigger verbatim, which re-freezes the column.
Rows that acquired a preview keep it — the trigger governs UPDATEs, not the values already
stored — so the downgrade is lossless and simply closes the door again.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1acd1b1d13f7"
down_revision: str | None = "86058922dc16"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: The F3.2 trigger. ``preview_digest`` leaves the frozen tuple and gets its own clause, so the
#: one legal transition is stated as a transition rather than as an absence.
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

#: F3.0's, verbatim (``86058922dc16``) — the downgrade target.
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


def upgrade() -> None:
    op.execute(_F32_TRIGGER)
    op.execute(
        "COMMENT ON COLUMN design_web_fragment.preview_digest IS 'The picture a human decides on. "
        "Born from the capture''s own crop where one exists; attachable ONCE afterwards (F3.2, "
        "ruling P-7) from an isolation render of the artifact''s own bytes, which is the only way "
        "a hidden-on-source section or a composed repair can ever have one.'"
    )


def downgrade() -> None:
    op.execute(_F30_TRIGGER)
    op.execute("COMMENT ON COLUMN design_web_fragment.preview_digest IS NULL")
