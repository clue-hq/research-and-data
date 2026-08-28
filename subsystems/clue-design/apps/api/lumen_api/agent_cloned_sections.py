"""The workspace's cloned sections, as one website turn's capability (clone-fidelity F2.3).

Ingestion clones every section of a walked site into a fragment artifact (F2.2) and a human
releases them by approving the brand kit they came from. This module is how the WEB LANE's agent
reaches them: one injected object, exactly like
:class:`~lumen_api.agent_custom_components.DurableAgentCustomComponentRegistry`, because the agent
runtime is fleet work that holds no database handle and must never be given one.

Four questions, four methods, in the order a turn asks them:

* :meth:`DurableAgentClonedSectionRegistry.list_sections` — "what can I reuse?" Rows only, no
  blob read, **approved only**. A ``draft`` section is minted but unreleased and a ``deprecated``
  one is retired; offering either would be offering something the document write will refuse.
  Since F3.1 each row also says whether it is BROKEN (``degraded``, with the reason and a
  sentence about it), whether it is itself a repair (``derived_from``), and whether somebody has
  already repaired it (``repairs`` / ``superseded_by``) — because D-F6 makes "offer this clone as
  if it were healthy" the exact failure the ladder exists to prevent.
* :meth:`DurableAgentClonedSectionRegistry.describe` — "what do the ones I am about to show
  actually look like, and where can they be re-filled?" One payload read and one preview
  materialization per id, so the cost is bounded by what the agent will SEE, not by what the
  workspace holds.
* :meth:`DurableAgentClonedSectionRegistry.resolve_insertable` — "may I pin this one, and what
  does it render as?" The permission half is **not decided here**: it asks
  :meth:`HybridRepository.validate_fragment_reference_changes`, the same gate the document write
  runs, against a probe document that pins exactly this fragment. So the agent's refusal and the
  write's refusal are the same refusal, with the same code, and a future change to what
  "approved" means cannot mean two different things in two places.
* :meth:`DurableAgentClonedSectionRegistry.mint_repair` — "this clone is broken; here is what
  replaces it" (F3.1, ruling D-F6). The replacement travels through the SAME sanitize → detect →
  scope → address → insert path a harvested section does, carries ``derived_from`` +
  ``derived_reason`` lineage, and is born ``draft`` like every other clone: a repair is released
  by the same human surface, never by the thing that made it.

Workspace-scoped throughout: the repository and the byte store both take their tenant from the
injected blob-store handle, and a foreign fragment id is simply unresolvable — the same
fail-closed answer an absent one gets.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .asset_custody import cache_blob_path, ensure_materialized
from .database import NotFoundError
from .design_store import DesignBlobStore, HybridRepository
from .fragments import (
    REPAIR_NOTE_MAX_CHARS,
    FragmentRefused,
    build_fragment_artifact,
    create_web_fragment,
    degraded_headline,
    read_web_fragment,
    repair_reason,
)
from .fragments.cssscope import PRELUDE_REFERENCE_STRIP
from .fragments.render import slot_kinds
from .fragments.sanitize import sanitize_fragment_html

# The SAME slot detector minting uses. Imported rather than reimplemented (and rather than
# forked into a "repair detector"): a repair that offered different slots from the clone it
# replaces would be a different editing surface for the same band, which is exactly the kind of
# drift the F2.3 vocabulary exists to prevent. `lumen_ingestion` already imports `lumen_api`
# (`main.py`, `fleet_handler.py` do the same in the other direction) and `slotdetect` itself
# pulls only `lumen_api.fragments`, so there is no cycle to be had here.
from lumen_ingestion.sections.slotdetect import detect_slots

JsonObject = Dict[str, Any]

#: How many approved sections one turn may be shown. A bound, not a judgement about workspaces:
#: the list is scored in Python by the discovery tool (which returns a handful), so this only has
#: to keep an enormous library out of one turn's memory. Ingestion mints at most
#: ``LUMEN_FRAGMENT_MINT_CAP`` (40) sections per walk, so this is several sites' worth.
CLONED_SECTION_LIST_MAX = 200

#: The by-value shape's version, mirroring the render package's own. Bump only for a change a
#: previous reader would MISREAD.
#:
#: F3.1 added ``degraded``/``degraded_reason``/``degraded_note``, the lineage pair, ``repairs``
#: and ``superseded_by`` to each row, and left this at 1 on the render package's own terms: every
#: reader of this shape uses ``.get``, so a key an older reader does not look at cannot be
#: misread by it — it simply does not see that a clone is broken, which is exactly the state it
#: was already in.
CLONED_SECTION_SCHEMA_VERSION = 1

#: The page id a probe document uses. Never persisted — it exists for the length of one gate call.
_PROBE_PAGE_ID = "home"
_PROBE_NODE_ID = "probe_cloned_section"


def _probe_web_doc(fragment_id: str) -> JsonObject:
    """The smallest valid-shaped document that pins one fragment.

    The gate is keyed on ``(page id, node id) -> fragment id`` and compares a BEFORE document
    against an AFTER one, so asking it "may this fragment be pinned?" means handing it an empty
    before and an after that pins exactly this fragment and nothing else. Nothing renders,
    validates or persists this document; only :func:`lumen_api.database.fragment_references`
    reads it.
    """
    return {
        "schema_version": 1,
        "id": "probe",
        "title": "",
        "pages": [
            {
                "id": _PROBE_PAGE_ID,
                "name": "Home",
                "route": "/",
                "root": "root",
                "nodes": {
                    "root": {
                        "id": "root",
                        "kind": "container",
                        "children": [_PROBE_NODE_ID],
                    },
                    _PROBE_NODE_ID: {
                        "id": _PROBE_NODE_ID,
                        "kind": "fragment",
                        "fragment_id": fragment_id,
                    },
                },
            }
        ],
        "assets": {},
    }


def _preferred_repair(repairs: List[JsonObject]) -> Optional[str]:
    """The repair a page should pin instead of the clone it replaces, or ``None``.

    Approved (the pin gate accepts nothing else) and not itself degraded (a repair that a later
    pass found broken is not an improvement on the thing it replaced). ``repairs`` arrives
    oldest-first, so the last match is the newest.
    """
    releasable = [
        repair
        for repair in repairs
        if repair.get("status") == "approved" and not repair.get("degraded")
    ]
    return str(releasable[-1]["fragment_id"]) if releasable else None


def _slot_summary(slot_manifest: Any) -> List[JsonObject]:
    """``[{key, kind}, …]`` — the half of an artifact's slot manifest an author must see.

    Sorted by key so the same section reads the same way every turn (a manifest is a dict, and a
    picker whose rows shuffle between calls teaches the model that ordering means something).
    The fallbacks are deliberately left behind: they are already in the markup the agent can see
    in the preview, and a section's default paragraph can be arbitrarily long.
    """
    return [
        {"key": key, "kind": kind}
        for key, kind in sorted(slot_kinds(slot_manifest or {}).items())
    ]


class DurableAgentClonedSectionRegistry:
    """The sole cloned-section capability exposed to one website-mode agent turn."""

    def __init__(self, *, blobs: DesignBlobStore, cache_dir: str | Path) -> None:
        # The byte store carries the tenant; the row store is built from it rather than
        # re-derived, so the two can never name different workspaces (the D4/D5 rule the
        # custom-component registry follows).
        self.blobs = blobs
        self.workspace_id = blobs.workspace_id
        # The TURN's engine cache, threaded in rather than re-derived: a fleet worker injects its
        # own, and staging preview bytes in one tree while the runtime reads another would show
        # the agent nothing while every digest looked healthy.
        self.cache_dir = Path(cache_dir)

    def _repository(self) -> HybridRepository:
        return HybridRepository(self.workspace_id)

    # --- discovery ---------------------------------------------------------------------------

    def list_sections(self, section_role: Optional[str] = None) -> JsonObject:
        """Every approved cloned section this workspace holds, newest first. No blob is read.

        ``slot_keys`` comes off the ROW's provenance (ingestion records it there), not out of the
        payload: a picker must be able to say "this one has a headline and a CTA" without opening
        one blob per section. The authoritative kinds arrive with :meth:`describe`, for the
        handful of sections that are actually shown.

        **One read, two answers** (F3.1). The repair index needs every row whatever its status —
        a repair minted last turn is ``draft`` until a human releases it, and the whole point of
        showing it is so the next turn does not mint a second one — so the scan is unfiltered and
        the approved-only rule is applied here, in Python, rather than by a second query. The
        result the caller sees is unchanged: approved sections, in document order.
        """
        all_rows = self._repository().list_web_fragments()
        repairs = self._repair_index(all_rows)
        rows = [
            row
            for row in all_rows
            if row.get("status") == "approved"
            and (section_role is None or row.get("section_role") == section_role)
        ]
        # DOCUMENT ORDER, not registry recency (W5). A picker's rows are a page read top to
        # bottom — nav, hero, proof, footer — and "newest first" scattered that into the order
        # the minter happened to write rows in, which carries no meaning a human can use. Page
        # first so a multi-page walk stays grouped, then the section's own index within it.
        ordered = sorted(rows, key=self._document_order)
        sections = [
            self._section_row(row, repairs) for row in ordered[:CLONED_SECTION_LIST_MAX]
        ]
        return {
            "schema_version": CLONED_SECTION_SCHEMA_VERSION,
            "workspace_id": self.workspace_id,
            "sections": sections,
            # What EXISTS, beside what is shown. A caller that sees eight rows and no total
            # cannot tell a complete answer from a truncated one.
            "total": len(rows),
        }

    @staticmethod
    def _repair_index(rows: List[JsonObject]) -> Dict[str, List[JsonObject]]:
        """``{repaired fragment id: [the repairs of it]}`` — every status, oldest first.

        Built over ALL rows on purpose. A repair is born ``draft`` (ruling R-I5), so an index of
        approved rows only would say "nothing has repaired this" about a clone somebody repaired
        an hour ago, and the next turn would compose the same replacement again.
        """
        index: Dict[str, List[JsonObject]] = {}
        for row in rows:
            parent = row.get("derived_from")
            if isinstance(parent, str) and parent:
                index.setdefault(parent, []).append(row)
        for entries in index.values():
            entries.sort(key=lambda row: (str(row.get("created_at") or ""), str(row["fragment_id"])))
        return index

    @staticmethod
    def _document_order(row: JsonObject) -> tuple:
        provenance = row.get("provenance")
        provenance = provenance if isinstance(provenance, dict) else {}
        index = provenance.get("section_index")
        return (
            str(provenance.get("page_url") or row.get("source_url") or ""),
            int(index) if isinstance(index, int) else 1_000_000,
            str(row.get("fragment_id") or ""),
        )

    @staticmethod
    def _section_row(
        row: JsonObject, repairs: Optional[Dict[str, List[JsonObject]]] = None
    ) -> JsonObject:
        provenance = row.get("provenance")
        provenance = provenance if isinstance(provenance, dict) else {}
        slot_keys = provenance.get("slots")
        fragment_id = str(row["fragment_id"])
        mine = list((repairs or {}).get(fragment_id) or [])
        degraded = bool(row.get("degraded"))
        return {
            "fragment_id": row["fragment_id"],
            "section_role": row.get("section_role"),
            "label": row.get("label"),
            "status": row.get("status"),
            "source_url": row.get("source_url"),
            "source_kit_id": row.get("source_kit_id"),
            "source_kit_version": row.get("source_kit_version"),
            "preview_digest": row.get("preview_digest"),
            "slot_keys": [str(key) for key in slot_keys]
            if isinstance(slot_keys, list)
            else [],
            "page_url": provenance.get("page_url"),
            # Where this section sat on its page — the one fact that makes a list of clones read
            # like the page it came from rather than like a registry dump.
            "section_index": provenance.get("section_index"),
            "created_at": row.get("created_at"),
            # --- D-F6: is this clone broken, is it a repair, and has it been repaired? --------
            "degraded": degraded,
            "degraded_reason": row.get("degraded_reason") if degraded else None,
            # The reason CODE is for a machine; this is the sentence the ladder decision turns
            # on. Only when there is something to say — an unbroken clone gets no note at all
            # rather than a cheerful one.
            "degraded_note": degraded_headline(row.get("degraded_reason")) if degraded else None,
            "derived_from": row.get("derived_from"),
            "derived_reason": row.get("derived_reason"),
            "repairs": [
                {
                    "fragment_id": str(repair["fragment_id"]),
                    "status": repair.get("status"),
                    "degraded": bool(repair.get("degraded")),
                    "derived_reason": repair.get("derived_reason"),
                }
                for repair in mine
            ],
            # The repair that should be pinned INSTEAD of this row, when one is releasable. The
            # newest approved, un-degraded repair wins: repairs accumulate (a rung-3 fallback can
            # itself be replaced by a rung-2 rebuild later) and the last one a human released is
            # the one they meant. `None` is the honest answer for a clone with only a draft
            # repair waiting — it says "somebody has done this work; go and release it", which is
            # a different instruction from "compose a replacement".
            "superseded_by": _preferred_repair(mine),
        }

    def describe(self, fragment_ids: Iterable[str]) -> Dict[str, JsonObject]:
        """Slot kinds and viewable pixels for the sections a turn is about to show.

        Fail-SOFT per id, like every other by-value resolution on this path: an id whose row or
        payload will not resolve is simply absent from the answer, so one purged blob costs one
        row's detail rather than the whole discovery call.
        """
        described: Dict[str, JsonObject] = {}
        for fragment_id in dict.fromkeys(fragment_ids):
            try:
                loaded = read_web_fragment(
                    self.blobs.storage,
                    workspace_id=self.workspace_id,
                    fragment_id=fragment_id,
                )
            except (NotFoundError, FragmentRefused):
                continue
            described[fragment_id] = {
                "slots": _slot_summary(loaded.slot_manifest),
                "preview_path": self._preview_path(loaded.row.get("preview_digest")),
            }
        return described

    def _preview_path(self, preview_digest: Any) -> Optional[str]:
        """The on-disk path of a section's preview image, materializing it if need be.

        The read-through pattern the scene asset library already uses: durable bytes are copied
        into the turn's engine cache so the runtime — which resolves images by PATH — can attach
        them. Fail-soft: a digest with no durable bytes yields ``None`` and the runtime says so
        honestly instead of attaching a broken image.
        """
        if not isinstance(preview_digest, str) or not preview_digest:
            return None
        ensure_materialized(self.blobs, self.cache_dir, [preview_digest])
        path = cache_blob_path(self.cache_dir, preview_digest)
        return str(path) if path.is_file() else None

    # --- the insert gate ---------------------------------------------------------------------

    def resolve_insertable(self, fragment_id: str) -> JsonObject:
        """May this fragment be pinned, and what does it render as?

        Raises :class:`~lumen_api.database.FragmentReferenceError` — the document write's own
        exception, with the document write's own code — when it may not. Nothing about status is
        re-decided here; see the module docstring.
        """
        repository = self._repository()
        # THE GATE. Not a status comparison of our own: the same call `update_web_document` makes,
        # so "approved" has exactly one definition in this codebase.
        repository.validate_fragment_reference_changes(
            before_web_doc={}, after_web_doc=_probe_web_doc(fragment_id)
        )
        loaded = read_web_fragment(
            self.blobs.storage,
            workspace_id=self.workspace_id,
            fragment_id=fragment_id,
        )
        row = loaded.row
        return {
            "fragment_id": fragment_id,
            "section_role": row.get("section_role"),
            "label": row.get("label"),
            "source_url": row.get("source_url"),
            "slots": _slot_summary(loaded.slot_manifest),
            "preview_path": self._preview_path(row.get("preview_digest")),
            # Exactly the entry `build_fragment_render_package` writes, so a section inserted
            # mid-turn renders in the agent's own preview through the map that is already
            # threaded — no second render path, and no shape for the two to disagree on.
            "render": {
                "html": loaded.html,
                "css": loaded.css,
                "slot_kinds": slot_kinds(loaded.slot_manifest),
                "asset_digests": list(loaded.asset_digests),
            },
        }

    # --- the repair mint (F3.1, ruling D-F6) --------------------------------------------------

    def mint_repair(
        self,
        *,
        replaces: str,
        html: str,
        css: str,
        rung: int,
        note: str,
        label: str | None = None,
    ) -> JsonObject:
        """Mint the replacement for a broken clone as a NEW, lineage-carrying fragment.

        ``html`` is the ENGINE's own render of the composed replacement section and ``css`` the
        utilities that render compiles against the document's theme — never markup a model
        emitted directly (orchestrator ruling R17-1). The two arrive from the agent side because
        that is where the engine and the pinned kit are; everything that decides what a fragment
        IS happens here, on the identical path a harvested section takes:

        sanitize (fail-closed on an un-rehosted byte reference, handlers stripped, banned
        elements dropped) → detect slots on the sanitized markup → annotate → scope the CSS under
        the fragment's own wrapper → content-address → insert the row. There is no second
        sanitizer and no relaxed one: a repair carrying an ``on*`` handler loses it exactly as a
        cloned section does, and a repair pointing at bytes we do not hold refuses exactly as a
        cloned section does.

        **Born ``draft``, and that is the whole release story** (ruling R-I5). A repair is
        released by the same human kit-approval surface every other clone goes through; nothing
        here can put one on a page. The caller therefore gets ``insertable: False`` back for a
        fresh repair and must say so rather than pretending the page now pins it.

        **Convergence is reported, never papered over.** The id is the content, so a repair whose
        sanitized output is byte-identical to a fragment this workspace already holds converges
        onto THAT row and keeps ITS lineage, status and label (``insert_web_fragment``'s
        first-writer-wins rule). The probe below asks the question BEFORE writing, so the answer
        is a fact in the result rather than something a caller has to infer from a lineage that
        does not match what it asked for.
        """
        repository = self._repository()
        original = repository.find_web_fragment(replaces)
        if original is None:
            raise FragmentRefused(
                "fragment.unresolved",
                f"cannot repair {replaces!r}: this workspace holds no such fragment",
                reference=replaces,
            )

        # The mint path's own order, not a re-arrangement of it: a slot must never be stamped on
        # an element the sanitizer was about to remove (`sections/mint.py`'s standing rule).
        sanitized = sanitize_fragment_html(html, rehosted={})
        detected = detect_slots(sanitized.html)

        # What the original's markup literally is, for the "did this repair anything?" check
        # below. Fail-SOFT on an unreadable original: a purged payload must not block repairing
        # the very fragment most in need of it, and nothing about preserving the original
        # depends on this read.
        try:
            existing_html = read_web_fragment(
                self.blobs.storage, workspace_id=self.workspace_id, fragment_id=replaces
            ).html
        except (NotFoundError, FragmentRefused):
            existing_html = None

        probe = build_fragment_artifact(
            html=sanitized.html,
            css=css,
            rehosted={},
            slots=list(detected.specs),
            preview_digest=None,
            prelude_reference=PRELUDE_REFERENCE_STRIP,
        )
        already = repository.find_web_fragment(probe.fragment_id)
        if existing_html is not None and probe.payload["html"] == existing_html:
            # A "repair" that reproduces the broken band is not one. Without this it would mint
            # as a NEW fragment holding the same markup — and NOT degraded, because the marker is
            # a row-level judgement rather than part of the content, so it does not follow the
            # bytes. A clean-looking duplicate of a band the pipeline has already measured as
            # broken is the one outcome D-F6 exists to prevent.
            #
            # Compared on the STORED form (sanitized and slot-annotated), because that is what a
            # fragment's markup literally is. The error direction is toward allowing a mint: an
            # original whose slots were stamped by something other than this detector annotates
            # differently and is not caught. That is the safe way round — the original survives
            # either way, and refusing a genuine repair would be the worse mistake.
            raise FragmentRefused(
                "fragment.repair_unchanged",
                f"this repair's markup is identical to {replaces}, so it repairs nothing. Walk "
                "the ladder: reproduce the experience with supported primitives, build an "
                "equivalent interaction, or compose a compact static fallback with the "
                "artificial height removed.",
                reference=replaces,
            )

        reason = repair_reason(
            rung=rung, trigger=original.get("degraded_reason"), note=note
        )
        row, artifact = create_web_fragment(
            self.blobs.storage,
            workspace_id=self.workspace_id,
            html=sanitized.html,
            css=css,
            rehosted={},
            slots=list(detected.specs),
            source_url=str(original.get("source_url") or ""),
            section_role=str(original.get("section_role") or "other"),
            label=label or _repair_label(original),
            source_kit_id=original.get("source_kit_id"),
            source_kit_version=original.get("source_kit_version"),
            preview=None,
            provenance=_repair_provenance(original, rung=rung, note=note, replaces=replaces),
            prelude_reference=PRELUDE_REFERENCE_STRIP,
            derived_from=replaces,
            derived_reason=reason,
        )
        converged = already is not None
        return {
            "fragment_id": artifact.fragment_id,
            "replaces": replaces,
            "status": row.get("status"),
            "section_role": row.get("section_role"),
            "label": row.get("label"),
            "derived_from": row.get("derived_from"),
            "derived_reason": row.get("derived_reason"),
            "requested_derived_reason": reason,
            "slot_keys": list(detected.keys),
            "asset_digests": list(artifact.payload.get("asset_digests") or []),
            # The FIRST pass's notes are the real ones. `create_web_fragment` sanitizes again
            # (idempotently) over markup this method already cleaned, so the artifact's own notes
            # are silent about everything that was actually removed.
            "sanitizer_notes": list(sanitized.notes) + list(artifact.notes),
            # Content addressing, stated (F3.0 §6.4). `converged` says this repair WAS already
            # here; the two lineage keys beside it say whose repair the surviving row records,
            # which is not necessarily this one.
            "converged": converged,
            "lineage_kept": row.get("derived_from") == replaces
            and row.get("derived_reason") == reason,
            # A fresh repair is `draft`, so the answer is almost always False — and it is the
            # caller's job to say so out loud rather than to imply a pin that did not happen.
            "insertable": row.get("status") == "approved",
        }


def _repair_label(original: JsonObject) -> str:
    """A repair's human label, anchored on the clone it replaces.

    The original's own label is a page's words ("Hero — Care, on your terms"); a repair that
    invented a new one would sit in the picker looking like a different section entirely.
    """
    base = str(original.get("label") or original.get("section_role") or "section").strip()
    return f"Repaired — {base}"[:200]


def _repair_provenance(
    original: JsonObject, *, rung: int, note: str, replaces: str
) -> JsonObject:
    """What a repair records about itself, and what it inherits about where it belongs.

    ``page_url``/``section_index`` are COPIED from the clone it replaces, deliberately: document
    order is what makes the picker read like the page (W5), and a repair that recorded no
    position would drop to the end of a recreated homepage — which is precisely the "adds
    nothing, reorders nothing" property F3.1 exists to guarantee.
    """
    inherited = original.get("provenance")
    inherited = inherited if isinstance(inherited, dict) else {}
    return {
        "page_url": inherited.get("page_url") or original.get("source_url"),
        "section_index": inherited.get("section_index"),
        "section_role": original.get("section_role"),
        "repair": {
            "replaces": replaces,
            "rung": rung,
            "trigger": original.get("degraded_reason"),
            "trigger_evidence": inherited.get("degraded"),
            "note": " ".join((note or "").split())[:REPAIR_NOTE_MAX_CHARS],
            "composed_by": "web-agent",
            "source": "engine_render",
        },
    }


__all__ = [
    "CLONED_SECTION_LIST_MAX",
    "CLONED_SECTION_SCHEMA_VERSION",
    "DurableAgentClonedSectionRegistry",
]
