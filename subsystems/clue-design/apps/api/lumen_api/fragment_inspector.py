"""The fragment inspector card — what a HUMAN is shown about one cloned section (F3.2).

The agent's view of a cloned section lives in :mod:`lumen_api.agent_cloned_sections`; this is the
other reader of the same rows, and the two are deliberately different shapes. The agent is
choosing which band to put on a page and is told the least that lets it choose well. A human in
the inspector is making the three decisions nothing else can make for them:

* **edit the slot values** of a section that is already on the page (D-F3: slot VALUES only —
  never the fragment's internals, which are somebody else's markup and are frozen);
* **activate a hidden-on-source section** (D-F8): see that the site hides it, see the evidence
  that says so, get a picture of it, and decide;
* **read the degraded → repaired lineage** (D-F6), and retire a repair that is no longer wanted
  (ruling R17-2) — which is the only in-product way out of a lineage with two released repairs.

**Lineage is never re-derived here.** Ruling R-X1 settled the resolution semantics after they
moved three times, and the resolver that implements them lives with the row set it needs
(:func:`lumen_api.agent_cloned_sections.resolve_fragment_lineages`). This module reads its
answers. A second implementation of "which repair supersedes which" would be a second answer.

**``section_index`` is a sort key, not an offset** (F3.0 review carry M3). It numbers the visible
and hidden collections from ONE document-order counter, so on a page that hides something the
visible sections' indices are non-contiguous — which is the truth about where the band sat, and
is not a position in any list.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from clue_storage import StorageBackend

from .agent_cloned_sections import LineageVerdict, resolve_fragment_lineages
from .fragments import (
    ASSET_URL_PREFIX,
    FRAGMENT_STATUS_DORMANT,
    degraded_headline,
    list_web_fragments,
    read_web_fragment,
)

JsonObject = Dict[str, Any]

#: Bumped only for a change a previous reader would MISREAD. Every consumer uses `.get`, so an
#: added key is invisible to an older one rather than wrong to it.
FRAGMENT_CARD_SCHEMA_VERSION = 1

#: A slot's stored fallback is the section's own copy and can be a whole paragraph. The inspector
#: shows it as a placeholder, so it is bounded here rather than at the far end of the wire.
SLOT_FALLBACK_MAX_CHARS = 240

FRAGMENT_STATUS_APPROVED = "approved"
FRAGMENT_STATUS_DEPRECATED = "deprecated"


def fragment_card(
    storage: StorageBackend, *, workspace_id: str, fragment_id: str
) -> JsonObject:
    """Everything the inspector shows about ONE cloned section.

    Reads the payload (for the slot manifest) and the whole workspace's rows (for the lineage).
    The row scan is the ledgered O(n) one every lineage reader pays; an inspector card is drawn
    per human selection, so it is the cheapest of the three consumers.
    """
    loaded = read_web_fragment(storage, workspace_id=workspace_id, fragment_id=fragment_id)
    rows = list_web_fragments(workspace_id=workspace_id)
    return _card(loaded.row, rows=rows, slot_manifest=loaded.slot_manifest)


def dormant_fragment_cards(
    storage: StorageBackend, *, workspace_id: str
) -> List[JsonObject]:
    """Every section the source site hides, as full cards, in document order (D-F8).

    A dormant section is on no page — that is what dormant means — so it can never be reached by
    selecting a node. D-F8 nonetheless makes the inspector the ONE place a human sees and
    activates one, so the inspector needs a list to reach them through, and this is it.

    The payload read is per fragment (the slot manifest lives in the blob), which is why this is
    bounded by dormancy rather than being a general listing: a workspace holds a handful of
    hidden sections and dozens of visible ones.
    """
    rows = list_web_fragments(workspace_id=workspace_id)
    dormant = [row for row in rows if row.get("status") == FRAGMENT_STATUS_DORMANT]
    dormant.sort(key=_document_order)
    cards: List[JsonObject] = []
    for row in dormant:
        loaded = read_web_fragment(
            storage, workspace_id=workspace_id, fragment_id=str(row["fragment_id"])
        )
        cards.append(_card(loaded.row, rows=rows, slot_manifest=loaded.slot_manifest))
    return cards


def _card(
    row: JsonObject, *, rows: List[JsonObject], slot_manifest: JsonObject
) -> JsonObject:
    fragment_id = str(row["fragment_id"])
    provenance = row.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    by_id = {str(candidate["fragment_id"]): candidate for candidate in rows}
    verdict = resolve_fragment_lineages(rows).get(fragment_id) or LineageVerdict(
        root=fragment_id, representative=fragment_id
    )
    degraded = bool(row.get("degraded"))
    hidden = provenance.get("hidden_on_source")
    return {
        "schema_version": FRAGMENT_CARD_SCHEMA_VERSION,
        "fragment_id": fragment_id,
        "label": row.get("label"),
        "section_role": row.get("section_role"),
        "status": row.get("status"),
        "source_url": row.get("source_url"),
        "page_url": provenance.get("page_url") or row.get("source_url"),
        # A SORT KEY, never an offset into the visible list (M3). Both collections are numbered
        # from one document-order counter, so a page that hides a section has gaps here.
        "section_index": provenance.get("section_index"),
        "preview": _preview(row, provenance),
        "slots": _slots(slot_manifest),
        # D-F6, the marker half: what is wrong, and what that reason MEANS.
        "degraded": degraded,
        "degraded_reason": row.get("degraded_reason"),
        "degraded_note": degraded_headline(row.get("degraded_reason")) if degraded else None,
        "degraded_measurement": provenance.get("degraded"),
        # D-F6, the lineage half. `repairs` spans every status: a repair is born `draft` and a
        # human releases it, so an approved-only list would tell somebody "nothing has repaired
        # this" about work done an hour ago.
        "derived_from": row.get("derived_from"),
        "derived_reason": row.get("derived_reason"),
        "repairs": [
            _lineage_entry(candidate)
            for candidate in sorted(
                (
                    candidate
                    for candidate in rows
                    if candidate.get("derived_from") == fragment_id
                ),
                key=lambda candidate: (
                    str(candidate.get("created_at") or ""),
                    str(candidate["fragment_id"]),
                ),
            )
        ],
        "repairs_what": (
            _lineage_entry(by_id[str(row["derived_from"])])
            if isinstance(row.get("derived_from"), str)
            and str(row["derived_from"]) in by_id
            else None
        ),
        "lineage_root": verdict.root,
        "superseded_by": (
            verdict.representative
            if verdict.representative and verdict.representative != fragment_id
            else None
        ),
        "lineage_ambiguous": list(verdict.ambiguous),
        # D-F8: the site hides this one, and here is the evidence that said so.
        "hidden_on_source": hidden if isinstance(hidden, dict) else None,
        "activation": activation_verdict(row),
        "retirement": retirement_verdict(row),
    }


def _preview(row: JsonObject, provenance: JsonObject) -> JsonObject:
    """The picture, and — P-7 — which KIND of picture it is.

    A crop of the source site's screenshot and an isolation render of the artifact's own bytes
    are both honest and are not the same evidence, so the basis travels with the image rather
    than being inferred from the fact that a dormant section could not have had a crop.
    """
    digest = row.get("preview_digest")
    return {
        "path": f"{ASSET_URL_PREFIX}{digest}" if digest else None,
        "digest": digest,
        "basis": provenance.get("preview_basis"),
    }


def _slots(slot_manifest: JsonObject) -> List[JsonObject]:
    """``[{key, kind, fallback}, …]``, sorted, so the card's controls do not shuffle between reads.

    The kind is what decides the control: `text` is a field, `image` an asset picker, `href` a
    link field (F1 ruling #2 — an href rides the node's `text` tag, so the MANIFEST is the only
    thing that remembers it is a link target), `visibility` a toggle.
    """
    entries: List[JsonObject] = []
    for key, entry in sorted((slot_manifest or {}).items()):
        if not isinstance(entry, dict):
            continue
        fallback = entry.get("fallback")
        if isinstance(fallback, str) and len(fallback) > SLOT_FALLBACK_MAX_CHARS:
            fallback = fallback[:SLOT_FALLBACK_MAX_CHARS] + "…"
        entries.append({"key": str(key), "kind": entry.get("kind"), "fallback": fallback})
    return entries


def _lineage_entry(row: JsonObject) -> JsonObject:
    """One member of a lineage, as the card lists it. Enough to tell them apart and act."""
    digest = row.get("preview_digest")
    return {
        "fragment_id": row.get("fragment_id"),
        "label": row.get("label"),
        "status": row.get("status"),
        "degraded": bool(row.get("degraded")),
        "degraded_reason": row.get("degraded_reason"),
        "derived_reason": row.get("derived_reason"),
        "preview_path": f"{ASSET_URL_PREFIX}{digest}" if digest else None,
        "created_at": row.get("created_at"),
    }


def activation_verdict(row: JsonObject) -> JsonObject:
    """May a human wake this section, and if not, what would have to change first (D-F8)?

    Stated as data rather than left for the surface to infer, because the two "no"s are
    different: a section that is not dormant has nothing to wake, and a dormant one with no
    preview needs a picture — which is a BUTTON, not an apology. The gate itself lives in the
    DAL and refuses independently of this; this is what the card shows before anyone presses it.
    """
    status = row.get("status")
    if status != FRAGMENT_STATUS_DORMANT:
        return {
            "activatable": False,
            "reason": "not_dormant",
            "message": "only a section the source site hides is activated this way.",
        }
    if not row.get("preview_digest"):
        return {
            "activatable": False,
            "reason": "no_preview",
            "message": (
                "this section was never rendered on the source site, so there is no picture of "
                "it yet. Generate an isolation render — our engine drawing the section's own "
                "harvested bytes — and then decide."
            ),
        }
    return {"activatable": True, "reason": None, "message": None}


def retirement_verdict(row: JsonObject) -> JsonObject:
    """May a human retire this one (ruling R17-2), and if not, why not.

    **Repairs only** (ruling R17-3). The harvested original is the EVIDENCE D-F6 exists to
    preserve — retiring it to settle an argument between two of its repairs would throw away the
    thing the argument is about — so the affordance is scoped to derived fragments and the row
    itself says so, rather than the surface remembering to.

    Retire is not release. No new approval granularity is introduced here: this moves a repair to
    ``deprecated`` through the same ``set_web_fragment_status`` machinery a section has always
    had, so a lineage holding two released repairs stops being a dead end.
    """
    if not row.get("derived_from"):
        return {
            "retirable": False,
            "reason": "not_a_repair",
            "message": (
                "the harvested original is the evidence a repair is judged against and is never "
                "retired; retire the repair you do not want instead."
            ),
        }
    if row.get("status") == FRAGMENT_STATUS_DEPRECATED:
        return {
            "retirable": False,
            "reason": "already_retired",
            "message": "this repair is already retired.",
        }
    return {"retirable": True, "reason": None, "message": None}


def _document_order(row: JsonObject) -> tuple:
    provenance = row.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    index = provenance.get("section_index")
    return (
        str(provenance.get("page_url") or row.get("source_url") or ""),
        int(index) if isinstance(index, int) else 1_000_000,
        str(row.get("fragment_id") or ""),
    )


def activation_target(row: JsonObject) -> Optional[str]:
    """The status a dormant section is activated INTO, or ``None`` when it is not dormant.

    ``approved`` rather than ``draft``: the human pressing this button IS the approval D-F8 asks
    for, and leaving it ``draft`` would mean the next kit approval releases it as a side effect
    of an unrelated decision — the exact automatic release dormancy exists to prevent.
    """
    if row.get("status") != FRAGMENT_STATUS_DORMANT:
        return None
    return FRAGMENT_STATUS_APPROVED


__all__ = [
    "FRAGMENT_CARD_SCHEMA_VERSION",
    "activation_target",
    "activation_verdict",
    "dormant_fragment_cards",
    "fragment_card",
    "retirement_verdict",
]
