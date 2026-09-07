"""The fragment inspector card — what a HUMAN is shown about one cloned section (F3.2).

The agent's view of a cloned section lives in :mod:`lumen_api.agent_cloned_sections`; this is the
other reader of the same rows, and the two are deliberately different shapes. The agent is
choosing which band to put on a page and is told the least that lets it choose well. A human in
the inspector is making the three decisions nothing else can make for them:

* **edit the slot values** of a section that is already on the page (D-F3 (Option A) + R-A6
  amendment (2026-09-04): a clone moves as a whole and exposes slot values AND per-element text
  overrides; nothing else inside it is editable — the fragment's internals are somebody else's
  markup and stay frozen, and an override is a per-instance value on the document's fragment node
  rather than an edit of that markup, so it is read from the document, not from this card);
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
    list_web_fragment_lineage,
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

    Reads the payload (for the slot manifest) and this fragment's FAMILY rows (for the lineage).
    Every row-derived field on the card — the direct repairs, what it repairs, the full family,
    the verdict — is about the lineage and nothing else, so the family read answers all of them
    exactly and reads a handful of rows rather than the workspace's whole library (ledger T17-M2).
    """
    loaded = read_web_fragment(storage, workspace_id=workspace_id, fragment_id=fragment_id)
    rows = list_web_fragment_lineage(workspace_id=workspace_id, fragment_id=fragment_id)
    return _card(
        loaded.row,
        rows=rows,
        lineages=resolve_fragment_lineages(rows),
        slot_manifest=loaded.slot_manifest,
    )


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
    # Resolved ONCE for the whole listing rather than once per card: the resolver is a pure
    # function of the same row set every card in this call shares, so re-running it per dormant
    # section would be N full lineage resolutions to answer the same question N times.
    lineages = resolve_fragment_lineages(rows)
    dormant = [row for row in rows if row.get("status") == FRAGMENT_STATUS_DORMANT]
    dormant.sort(key=_document_order)
    cards: List[JsonObject] = []
    for row in dormant:
        loaded = read_web_fragment(
            storage, workspace_id=workspace_id, fragment_id=str(row["fragment_id"])
        )
        cards.append(
            _card(
                loaded.row,
                rows=rows,
                lineages=lineages,
                slot_manifest=loaded.slot_manifest,
            )
        )
    return cards


def _card(
    row: JsonObject,
    *,
    rows: List[JsonObject],
    lineages: Dict[str, LineageVerdict],
    slot_manifest: JsonObject,
) -> JsonObject:
    fragment_id = str(row["fragment_id"])
    provenance = row.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    by_id = {str(candidate["fragment_id"]): candidate for candidate in rows}
    verdict = lineages.get(fragment_id) or LineageVerdict(
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
        # D-F6, the lineage half. There is no direct-children list here on purpose (F3.4, T18
        # re-review): ruling R18-1 made the card carry the whole FAMILY, every entry of which
        # names its own `derived_from`, so "the repairs of this row" is a filter over `family`
        # rather than a second list saying a subset of the same thing. It was carried for one
        # release, rendered by nothing, and parsed by two clients that then ignored it.
        "derived_from": row.get("derived_from"),
        "derived_reason": row.get("derived_reason"),
        "repairs_what": (
            _lineage_entry(by_id[str(row["derived_from"])])
            if isinstance(row.get("derived_from"), str)
            and str(row["derived_from"]) in by_id
            else None
        ),
        # RULING R18-1: every repair in the family, from the card of ANY member — not just this
        # row's direct children, which is why the direct-children list above it is gone (F3.4).
        # A repair is on no page unless somebody pinned it, so "select the repair" is not a way
        # to reach one, and a grandchild leaf listed under nobody had a Retire button nowhere at
        # all — leaving the contested-lineage dead end R17-2 exists to end still a dead end, with
        # the affordance built and unreachable.
        "lineage_root": verdict.root,
        "family": _family(fragment_id, rows=rows, lineages=lineages),
        "superseded_by": (
            verdict.representative
            if verdict.representative and verdict.representative != fragment_id
            else None
        ),
        "lineage_ambiguous": list(verdict.ambiguous),
        # Ruling R-X4: every released member of this family is broken, and the one the resolver
        # seated (the newest, by default) is on the page flagged rather than fixed. The human
        # card is where "requiring review" is finally read by a person, so it says so here too.
        "lineage_degraded_fallback": verdict.degraded_fallback,
        "lineage_ranked_over": list(verdict.ranked_over),
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
        # The ROW's own answer wins, and it is only ever set by the attach: it describes the
        # picture that is actually there. Falling through to the mint's provenance is right for
        # every row whose picture the mint made — and only for those, which is why the row is
        # asked first. See `attach_web_fragment_preview` for the two rows the fallback would
        # mislabel.
        "basis": row.get("preview_basis") or provenance.get("preview_basis"),
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


def _family(
    fragment_id: str, *, rows: List[JsonObject], lineages: Dict[str, LineageVerdict]
) -> List[JsonObject]:
    """Every member of THIS row's lineage, oldest first, each with its own retire verdict.

    **Ruling R18-1**: every repair in a family must be retire-reachable from the card of any
    family member that is selectable on the page. The parent/child list cannot deliver that —
    a repair-of-a-repair is nobody's direct child except its own parent's, and its parent is
    typically on no page — so the card carries the family instead.

    Membership is the RESOLVER's, not this module's: two rows are family iff they share a
    ``lineage_root``, which is the answer `_resolve_lineages` already computed by walking
    ``derived_from`` up through rows of every status (ruling R-X1). Nothing here re-derives it —
    the same rule computed twice is two rules, and this one moved three times before it settled.

    Each entry carries `derived_from` and its own `retirement`, so the surface renders a button
    where one is lawful and a reason where it is not, without knowing R17-3.
    """
    root = (lineages.get(fragment_id) or LineageVerdict(root=fragment_id, representative=None)).root
    members = [
        candidate
        for candidate in rows
        if (
            lineages.get(str(candidate["fragment_id"]))
            or LineageVerdict(
                root=str(candidate["fragment_id"]), representative=None
            )
        ).root
        == root
    ]
    members.sort(
        key=lambda candidate: (
            str(candidate.get("created_at") or ""),
            str(candidate["fragment_id"]),
        )
    )
    return [
        {
            **_lineage_entry(candidate),
            "derived_from": candidate.get("derived_from"),
            "is_root": str(candidate["fragment_id"]) == root,
            "retirement": retirement_verdict(candidate),
        }
        for candidate in members
    ]


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
