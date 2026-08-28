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

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from clue_design import site_snapshots as snapshot_dal

from .asset_custody import cache_blob_path, ensure_materialized
from .clone_review import (
    DESKTOP_VIEWPORT,
    RenderedBand,
    build_blind_side_by_side,
    compare_to_reference,
    reference_bands_from_fragments,
)
from .database import NotFoundError
from .design_store import DesignBlobStore, DesignStoreBridge, HybridRepository
from .fragments import (
    FRAGMENT_STATUS_DORMANT,
    GATE_REASONS,
    REPAIR_NOTE_MAX_CHARS,
    FragmentRefused,
    build_fragment_artifact,
    create_web_fragment,
    degraded_headline,
    read_web_fragment,
    repair_reason,
    set_web_fragment_degraded,
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


@dataclass(frozen=True)
class LineageVerdict:
    """One repair lineage, resolved to the single section a page should carry (ruling R-C1).

    A lineage is a clone and everything descended from it: the harvested original, the repair
    that replaced it, the repair that later replaced THAT. Every member is an ordinary approved
    row once a human releases it, so a page assembled by walking the listing one row at a time
    puts the same band down more than once. This type is the answer to "of this whole family,
    which ONE section belongs on the page?".

    ``representative`` is ``None`` only when the family cannot answer that question with one id —
    two sibling repairs both released, neither superseding the other — and then ``ambiguous``
    names the candidates. That is a decision for a human (retire one), never something to guess
    at by picking the newest: both are somebody's deliberate repair of the same band.

    ``ranked_over`` is the other half of that honesty. When NO releasable repair exists the family
    falls back to its oldest approved member, and if more than one approved member was in the
    running that fallback is a ranking — of BROKEN candidates, so it cannot refuse the way
    ``ambiguous`` does (refusing would leave the page with a hole where the band goes). It names
    what it passed over instead, so a silent choice becomes a stated one.
    """

    root: str
    representative: Optional[str]
    ambiguous: tuple[str, ...] = ()
    ranked_over: tuple[str, ...] = ()


def _resolve_lineages(rows: List[JsonObject]) -> Dict[str, LineageVerdict]:
    """``{fragment id: the verdict for its lineage}`` over every row this workspace holds.

    Three passes, and each answers a question the one before it could not:

    1. **Roots.** Walk ``derived_from`` up through every row REGARDLESS of status, so a lineage
       whose original was retired still resolves to one family rather than fragmenting into one
       family per surviving repair.
    2. **Supersession is transitive over DESCENDANTS, not children** (ruling R-X1). Call a member
       *healthy* when it is approved and un-degraded — the two conditions that make it pinnable
       and worth pinning. A healthy member is superseded **iff any descendant of it is healthy**,
       at any depth and through links of any status.

       Both halves of that sentence are scar tissue. Asking about CHILDREN got it wrong twice in
       opposite directions: counting every approved child made a degraded newest repair evict its
       own healthy parent (ruling N1), and then counting only un-degraded children stopped a
       degraded middle shielding its ancestors, so a healthy original and its own healthy
       grandchild both looked like ends of the chain and the family was declared ambiguous
       between them (ruling X1). Descendants answer both at once: a degraded middle is stepped
       over in BOTH directions — it supersedes nothing itself, and it does not hide the healthy
       repair below it from superseding what is above it.
    3. **The representative.** The healthy members with no healthy descendant — the live ends of
       the chain. Exactly one is the answer. Two or more is ``ambiguous``: they are necessarily
       an antichain (a member with a healthy descendant is not in the set at all, so none of them
       can be an ancestor of another), which is what makes "neither replaces the other" true
       rather than merely unproven. None — every repair itself broken, or none released — falls
       back to the family's oldest approved member, exactly ONE, and NAMES what it passed over,
       so the pin is reported through ``needs_repair`` rather than chosen in silence.

    Cycles cannot exist (``derived_from`` must resolve to an existing row at insert time and the
    column is frozen), but both walks carry a seen-set anyway: a lineage walk that could loop
    forever on corrupt data is not a thing to leave to an invariant.
    """
    by_id = {str(row["fragment_id"]): row for row in rows}

    def is_healthy(row: JsonObject) -> bool:
        return row.get("status") == "approved" and not row.get("degraded")

    def root_of(fragment_id: str) -> str:
        seen: set = set()
        current = fragment_id
        while current not in seen:
            seen.add(current)
            row = by_id.get(current)
            parent = row.get("derived_from") if isinstance(row, dict) else None
            if not isinstance(parent, str) or parent not in by_id:
                return current
            current = parent
        return current

    families: Dict[str, List[JsonObject]] = {}
    children: Dict[str, List[str]] = {}
    for fragment_id, row in by_id.items():
        families.setdefault(root_of(fragment_id), []).append(row)
        parent = row.get("derived_from")
        if isinstance(parent, str) and parent in by_id:
            children.setdefault(parent, []).append(fragment_id)

    healthy_below: Dict[str, bool] = {}

    def has_healthy_descendant(fragment_id: str) -> bool:
        """Is anything at all below this row pinnable? Memoised, so a family costs one pass.

        Iterative rather than recursive, with its own explicit stack: a lineage is shallow in
        practice, but a walk whose depth limit is the interpreter's fails with a ``RecursionError``
        rather than an answer, and a thousand-link chain is reachable by repair-of-repair. (This
        walk was recursive under a comment claiming it was not — the comment was the defect.)

        The stack is always the path from ``fragment_id`` down to the row being examined, which is
        what makes the short-circuit sound: the moment anything on it sees a healthy child, every
        row on the stack is an ancestor of that child and is answered in the same breath.
        """
        cached = healthy_below.get(fragment_id)
        if cached is not None:
            return cached
        healthy_below[fragment_id] = False  # cycle guard: a row is not below itself
        stack: List[tuple[str, Any]] = [(fragment_id, iter(children.get(fragment_id, ())))]
        while stack:
            _node_id, child_iter = stack[-1]
            descended = False
            for child_id in child_iter:
                if is_healthy(by_id[child_id]) or healthy_below.get(child_id):
                    for ancestor_id, _ in stack:
                        healthy_below[ancestor_id] = True
                    return True
                if child_id not in healthy_below:
                    healthy_below[child_id] = False
                    stack.append((child_id, iter(children.get(child_id, ()))))
                    descended = True
                    break
            if not descended:
                stack.pop()
        return False

    verdicts: Dict[str, LineageVerdict] = {}
    for root, members in families.items():
        approved = [row for row in members if row.get("status") == "approved"]
        # Oldest first, so the fallback's "oldest approved member" is read off one ordering.
        approved.sort(key=lambda row: (str(row.get("created_at") or ""), str(row["fragment_id"])))
        leaves = [
            row
            for row in members
            if is_healthy(row) and not has_healthy_descendant(str(row["fragment_id"]))
        ]
        leaves.sort(key=lambda row: (str(row.get("created_at") or ""), str(row["fragment_id"])))
        if len(leaves) == 1:
            verdict = LineageVerdict(root=root, representative=str(leaves[0]["fragment_id"]))
        elif len(leaves) > 1:
            verdict = LineageVerdict(
                root=root,
                representative=None,
                ambiguous=tuple(sorted(str(row["fragment_id"]) for row in leaves)),
            )
        else:
            # Nothing releasable in the whole family. Fall back, and say what lost — with two or
            # more broken candidates this pick is a ranking, and an unstated ranking is the thing
            # the ambiguity refusal exists to avoid. It cannot refuse here (every candidate is
            # broken, and a hole where the band goes is worse than a flagged band), so it states.
            verdict = LineageVerdict(
                root=root,
                representative=str(approved[0]["fragment_id"]) if approved else None,
                ranked_over=tuple(
                    sorted(str(row["fragment_id"]) for row in approved[1:])
                ),
            )
        for row in members:
            verdicts[str(row["fragment_id"])] = verdict
    return verdicts


#: The ONE lineage resolution, under its public name (F3.2).
#:
#: Ruling R-X1 settled these semantics after they moved three times in three review rounds, and
#: the record of what "settled" means is the fifteen-shape matrix in the task-17 report. The
#: human-facing inspector card (:mod:`lumen_api.fragment_inspector`) is the second consumer, and
#: it reads THIS function's answers rather than asking the same question again — a second
#: implementation of "which repair supersedes which" would be a second answer.
resolve_fragment_lineages = _resolve_lineages


def _page_url(row: JsonObject) -> Optional[str]:
    """Which page a cloned section came from, read ONE way (ledger T17-M3).

    The mint records it in provenance; a row from a producer that did not falls back to the
    fragment's ``source_url``, which is the same page by construction. Written here rather than
    inline at each reader because the listing had two readers and they disagreed — the ordering
    fell back and the projection did not, so a row with no recorded page url sorted under its
    source url and then reported no page at all.
    """
    provenance = row.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    page_url = provenance.get("page_url") or row.get("source_url")
    return str(page_url) if isinstance(page_url, str) and page_url else None


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
        lineages = _resolve_lineages(all_rows)
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
            self._section_row(row, repairs, lineages)
            for row in ordered[:CLONED_SECTION_LIST_MAX]
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
        """``{repaired fragment id: [the repairs of it]}`` — oldest first, dormant excluded.

        Built over draft, approved and deprecated rows on purpose. A repair is born ``draft``
        (ruling R-I5), so an index of approved rows only would say "nothing has repaired this"
        about a clone somebody repaired an hour ago, and the next turn would compose the same
        replacement again.

        ``dormant`` is the one status left out, and it is left out because D-F8's rule is
        absolute: a dormant section is never offered to the agent, and a repair listed under
        another section's ``repairs`` is being offered. Nothing mints a dormant repair today
        (review finding M4) — this keeps the rule true rather than true-by-accident.
        """
        index: Dict[str, List[JsonObject]] = {}
        for row in rows:
            if row.get("status") == FRAGMENT_STATUS_DORMANT:
                continue
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
            _page_url(row) or "",
            int(index) if isinstance(index, int) else 1_000_000,
            str(row.get("fragment_id") or ""),
        )

    @staticmethod
    def _section_row(
        row: JsonObject,
        repairs: Optional[Dict[str, List[JsonObject]]] = None,
        lineages: Optional[Dict[str, LineageVerdict]] = None,
    ) -> JsonObject:
        provenance = row.get("provenance")
        provenance = provenance if isinstance(provenance, dict) else {}
        slot_keys = provenance.get("slots")
        fragment_id = str(row["fragment_id"])
        mine = list((repairs or {}).get(fragment_id) or [])
        degraded = bool(row.get("degraded"))
        verdict = (lineages or {}).get(fragment_id) or LineageVerdict(
            root=fragment_id, representative=fragment_id
        )
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
            # Same fallback the ORDERING uses (ledger T17-M3). They disagreed: `_document_order`
            # falls back to `source_url` when the mint recorded no `page_url`, and this did not —
            # so such a row sorted under its source url and then projected `page_url: None`,
            # which the recreate reads as a page named "" and refuses as ambiguous. One fallback,
            # written once, so the page a section is sorted onto is the page it reports.
            "page_url": _page_url(row),
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
            # --- the lineage verdict (ruling R-C1) -------------------------------------------
            # `lineage_root` is what an ASSEMBLY groups by: every member of one repair family
            # answers with the same root, so a page can put exactly one of them down however many
            # of them the listing happens to contain.
            "lineage_root": verdict.root,
            # The section that should be pinned INSTEAD of this row, or `None` when this row IS
            # the one. Resolved transitively over the whole family — a repair-of-a-repair wins
            # over its own parent, and a degraded intermediate is stepped over rather than
            # letting the broken original back onto the page. `None` on an unrepaired clone with
            # only a DRAFT repair waiting is the honest answer: it says "somebody has done this
            # work; go and release it", which is a different instruction from "compose one".
            "superseded_by": (
                verdict.representative
                if verdict.representative and verdict.representative != fragment_id
                else None
            ),
            # Two released repairs of one band, neither superseding the other. A human retires
            # one; nothing here picks for them, because both are somebody's deliberate work.
            "lineage_ambiguous": list(verdict.ambiguous),
            # The broken candidates the fallback passed over, when it had to rank. Empty in every
            # ordinary shape; present only when the whole family is broken.
            "lineage_ranked_over": list(verdict.ranked_over),
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

        **A DEGRADED answer also carries its lineage verdict** (ruling N2), and only a degraded
        one. Whoever pins a broken band is about to be told so, and that warning has to be able
        to say whether a released repair already exists — otherwise it tells an author to compose
        a second repair of a band that already has one, which is how two released siblings (and
        the ambiguity refusal that follows) get made. Gated on ``degraded`` because the verdict
        costs a row scan and the answer is used nowhere else: an ordinary healthy pin pays
        nothing, and a page of nine healthy clones still resolves lineage exactly zero times.
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
        degraded = bool(row.get("degraded"))
        verdict = None
        if degraded:
            # The FAMILY, not the library (ledger T17-M2/X3). The resolver never looks outside a
            # family, so reading one through the F3.0 `(workspace_id, derived_from)` index gives
            # the identical verdict for the cost of the lineage instead of the cost of every
            # cloned section this workspace holds — and a pin gate runs on every pin.
            verdict = _resolve_lineages(
                repository.list_web_fragment_lineage(fragment_id)
            ).get(fragment_id)
        return {
            "fragment_id": fragment_id,
            "section_role": row.get("section_role"),
            "label": row.get("label"),
            "source_url": row.get("source_url"),
            "slots": _slot_summary(loaded.slot_manifest),
            "preview_path": self._preview_path(row.get("preview_digest")),
            # D-F6 travels with the PIN, not only with the picker (review finding I4). Every path
            # that puts a cloned section on a page comes through here, so this is the one place
            # that can tell all of them the band is broken.
            "degraded": degraded,
            "degraded_reason": row.get("degraded_reason") if degraded else None,
            "degraded_note": degraded_headline(row.get("degraded_reason")) if degraded else None,
            "derived_from": row.get("derived_from"),
            # `None` on a healthy pin means "not looked up", not "no repair exists" — nothing
            # reads it there. On a degraded pin it is the resolved answer.
            "superseded_by": (
                verdict.representative
                if verdict is not None
                and verdict.representative
                and verdict.representative != fragment_id
                else None
            ),
            "lineage_ambiguous": list(verdict.ambiguous) if verdict is not None else [],
            # Exactly the entry `build_fragment_render_package` writes, so a section inserted
            # mid-turn renders in the agent's own preview through the map that is already
            # threaded — no second render path, and no shape for the two to disagree on.
            "render": {
                "html": loaded.html,
                "css": loaded.css,
                "slot_kinds": slot_kinds(loaded.slot_manifest),
                "asset_digests": list(loaded.asset_digests),
                # Same key `build_fragment_render_package` writes, for the same one reader: a
                # section pinned mid-turn must reach the collision report as what it is, or a
                # repair would be reported as losing styling in the agent's own preview while
                # the identical publish said nothing (ruling R-I1).
                "derived": bool(row.get("derived_from")),
            },
        }

    # --- the behavioural review gate (F3.3, rulings D-F6 / D-F7) -------------------------------

    def mark_degraded(self, fragment_id: str, *, reason: str) -> JsonObject:
        """Record that the behavioural walk measured this clone as broken (F3.3).

        The gate's ONE durable write, and it is deliberately narrow in three ways:

        * **Only the gate's own reason codes** (:data:`~lumen_api.fragments.degraded.GATE_REASONS`)
          are accepted. ``dead_height`` in particular is refused: that code belongs to the
          mint-time detector, whose reconciler re-measures it from a fresh capture and would
          silently clear a verdict about how OUR page renders — the R-I1-narrow rule protects
          these findings precisely because they are spelled differently.
        * **Only ON.** Nothing here can un-break a clone. A marker is cleared by its own
          detector re-measuring (the mint path) or by a human; a review pass that happens not to
          reproduce a defect has not proven the defect is gone.
        * **Never at the model's word.** The tool that calls this computes the reason from
          measured numbers; there is no route by which an agent's argument becomes a marker.
        """
        if reason not in GATE_REASONS:
            raise ValueError(
                f"the behavioural review gate may only record its own reasons {GATE_REASONS!r}; "
                f"{reason!r} belongs to another producer and would be cleared by it"
            )
        return set_web_fragment_degraded(
            workspace_id=self.workspace_id,
            fragment_id=fragment_id,
            degraded=True,
            reason=reason,
        )

    def reference_review(
        self,
        fragment_ids: Iterable[str],
        *,
        capture_png: bytes | None,
        rendered_bands: Sequence[Mapping[str, Any]] = (),
        rendered_viewport_width: int = DESKTOP_VIEWPORT.width,
        blind_seed: str = "",
    ) -> JsonObject:
        """Our page against F0's reference capture, plus the blind side-by-side artifact.

        Lives on the registry rather than in the agent runtime because it is a DATABASE read: the
        reference is the ``design_site_snapshot`` row the ingestion job kept (F0.1), found through
        the pinned fragments' own mint provenance rather than by matching a url — the provenance
        names the exact snapshot each band was cut from, so there is no guessing about which
        capture of which page this page is a clone of.

        Returns an honest ``status: "unavailable"`` with a ``because`` code whenever any half of
        the comparison is missing. A page whose clones predate snapshot custody, a static-tier
        capture that never took a screenshot, and a walk that could not photograph our own page
        are three different problems, and the caller is told which.
        """
        rows = [
            row
            for row in self._repository().list_web_fragments()
            if row.get("fragment_id") in set(fragment_ids)
        ]
        bands, viewport_width, snapshot_id = reference_bands_from_fragments(rows)
        if snapshot_id is None:
            return {"status": "unavailable", "because": "no_snapshot_provenance"}
        try:
            snapshot = self._snapshot_row(snapshot_id)
        except NotFoundError:
            return {"status": "unavailable", "because": "snapshot_missing"}
        screenshot_digest = snapshot.get("screenshot_digest")
        reference_png: bytes | None = None
        if screenshot_digest:
            try:
                reference_png = self.blobs.read(str(screenshot_digest))
            except NotFoundError:
                reference_png = None

        comparison = compare_to_reference(
            reference_png=reference_png,
            capture_png=capture_png,
            reference_viewport_width=viewport_width or snapshot.get("viewport_width"),
            rendered_viewport_width=rendered_viewport_width,
            reference_bands=bands,
            rendered_bands=[
                RenderedBand(
                    fragment_id=str(band.get("fragment_id") or ""),
                    top_px=float(band.get("top_px") or 0.0),
                    height_px=float(band.get("height_px") or 0.0),
                )
                for band in rendered_bands
                if band.get("fragment_id")
            ],
        )

        result: JsonObject = {
            "status": comparison.get("status"),
            "snapshot_id": snapshot_id,
            "page_url": snapshot.get("page_url"),
            "comparison": comparison,
        }
        if comparison.get("status") != "ok":
            result["because"] = comparison.get("because")
        # The blind artifact is composed HERE because this is the only place both pictures are in
        # hand at once — the reference never leaves the workspace's byte custody otherwise.
        #
        # **It is built whenever both pictures exist, even when the COMPARISON abstained**
        # (round-2 re-review, breakage #4). The two are different artifacts answering different
        # questions: the comparison needs matching viewports and readable geometry to report a
        # number, while the blind side-by-side needs two images and a founder's eyes. Gating the
        # artifact on the comparison meant a reference recorded at 1425px (a classic scrollbar)
        # destroyed the CP1 acceptance walk as a side effect of a measurement it does not use.
        if reference_png and capture_png:
            blind = build_blind_side_by_side(
                published_png=capture_png,
                reference_png=reference_png,
                seed=blind_seed or f"{snapshot_id}:{self.workspace_id}",
                published_caption=f"the page we rendered for {snapshot.get('page_url')}",
            )
            result["blind_png"] = blind.image_png
            result["blind_key"] = blind.key
        return result

    def _snapshot_row(self, snapshot_id: str) -> JsonObject:
        """One ``design_site_snapshot`` row — the row only, no html and no stylesheet bytes.

        Deliberately not ``read_site_snapshot``: that loads the page's html and every stylesheet
        it fetched, which for a real homepage is megabytes this comparison never looks at.
        """
        return DesignStoreBridge(self.workspace_id)._run(
            lambda conn: snapshot_dal.get_site_snapshot(
                conn, workspace_id=self.workspace_id, snapshot_id=snapshot_id
            )
        )

    # --- the repair mint (F3.1, ruling D-F6) --------------------------------------------------

    def mint_repair(
        self,
        *,
        replaces: str,
        html: str,
        css: str,
        rung: int,
        note: str,
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
            label=_repair_label(original),
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


#: What a repair's label says it is, before the clone's own words.
_REPAIR_LABEL_PREFIX = "Repaired"


def _repair_label(original: JsonObject) -> str:
    """A repair's human label, anchored on the clone it replaces.

    The original's own label is a page's words ("Hero — Care, on your terms"); a repair that
    invented a new one would sit in the picker looking like a different section entirely.

    **The prefix does not stack** (ledger T17-M6). Repairing a repair used to produce
    "Repaired — Repaired — Hero — Care, on your terms", and a third round another one — a picker
    row whose label is mostly bookkeeping, and bookkeeping the LINEAGE already carries exactly
    and this could only approximate. So the count is stated once: ``Repaired ×2 — Hero — …``,
    and a reader who wants the chain reads the family on the card.
    """
    base = str(original.get("label") or original.get("section_role") or "section").strip()
    generation = 1
    while True:
        prefix, separator, rest = base.partition(" — ")
        if not separator or not prefix.startswith(_REPAIR_LABEL_PREFIX):
            break
        suffix = prefix[len(_REPAIR_LABEL_PREFIX) :].strip()
        if suffix:
            if not (suffix.startswith("×") and suffix[1:].isdigit()):
                break
            generation += int(suffix[1:])
        else:
            generation += 1
        base = rest.strip()
    marker = _REPAIR_LABEL_PREFIX if generation == 1 else f"{_REPAIR_LABEL_PREFIX} ×{generation}"
    return f"{marker} — {base}"[:200]


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
    "LineageVerdict",
]
