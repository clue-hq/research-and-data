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

import hashlib
from urllib.parse import urlsplit
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from clue_design import site_snapshots as snapshot_dal
from clue_design.web_fragments import fragment_has_kit_binding
from py_lumen_config import settings

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
    CAMPAIGN_SHELL_ROLES,
    CAMPAIGN_SHELL_SOURCE_URL,
    COBRAND_PLACEHOLDER_ASSET_ID,
    COBRAND_PLACEHOLDER_MEDIA_TYPE,
    COBRAND_PLACEHOLDER_PNG,
    COMPOSED_CAMPAIGN_SHELL,
    FRAGMENT_STATUS_DORMANT,
    GATE_REASONS,
    REPAIR_NOTE_MAX_CHARS,
    WEB_FRAGMENT_SOURCE_KEY,
    FragmentRefused,
    build_fragment_artifact,
    campaign_shell_shape_notes,
    campaign_shell_slots,
    create_web_fragment,
    degraded_headline,
    read_web_fragment,
    repair_reason,
    set_web_fragment_degraded,
    set_web_fragment_status,
)
from .fragments.behavior import inspect_fragment_behavior
from .fragments.native import native_render_fields
from .fragments.cssscope import PRELUDE_REFERENCE_STRIP, scope_fragment_css
from .fragments.isolation import IsolationFonts
from .fragments.render import slot_kinds
from .fragments.registry import create_href_repaired_fragment
from .fragments.sanitize import sanitize_fragment_html

# The SAME slot detector minting uses. Imported rather than reimplemented (and rather than
# forked into a "repair detector"): a repair that offered different slots from the clone it
# replaces would be a different editing surface for the same band, which is exactly the kind of
# drift the F2.3 vocabulary exists to prevent. `lumen_ingestion` already imports `lumen_api`
# (`main.py`, `fleet_handler.py` do the same in the other direction) and `slotdetect` itself
# pulls only `lumen_api.fragments`, so there is no cycle to be had here.
from lumen_ingestion.sections.slotdetect import detect_slots
from lumen_ingestion.sections.source_flow import SourceFlowUnavailable, compile_source_flow
from lumen_ingestion.site_snapshot import read_site_snapshot

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


#: The two answers ruling R-X4 (founder, 2026-08-29) settled between, when EVERY released member
#: of a repair family is marked broken and something still has to go on the page.
#:
#: * :data:`DEGRADED_REPAIR_KEEP_FLAGGED` — the DEFAULT, and the founder's own words: "keep the
#:   newer repair selected, but clearly flag it as degraded and requiring review. Never silently
#:   return to a known-broken original." The NEWEST approved member wins.
#: * :data:`DEGRADED_REPAIR_FALLBACK_ORIGINAL` — the pre-ruling behaviour, kept as a deliberate
#:   deployment choice rather than deleted: the OLDEST approved member wins, which for a family
#:   that still holds its harvested original IS the original.
#:
#: One env option, two values: ``LUMEN_DEGRADED_REPAIR_SELECTION`` (see the repo-root and design
#: ``.env.example``). Nothing else about the resolver looks at it — every family with a healthy
#: member, and every ambiguous family, answers identically under both.
DEGRADED_REPAIR_KEEP_FLAGGED = "keep_flagged"
DEGRADED_REPAIR_FALLBACK_ORIGINAL = "fallback_original"
DEGRADED_REPAIR_SELECTIONS = (
    DEGRADED_REPAIR_KEEP_FLAGGED,
    DEGRADED_REPAIR_FALLBACK_ORIGINAL,
)


def degraded_repair_selection() -> str:
    """The configured selection, read at CALL time rather than at import.

    Import-time capture would freeze whatever the first module to touch this held, which in a
    fleet worker is decided by import order rather than by the deployment. The read is a
    settings attribute lookup — free beside the row scan it accompanies.
    """
    return str(settings.lumen_degraded_repair_selection)


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
    falls back to ONE approved member, and if more than one approved member was in the running
    that fallback is a ranking — of BROKEN candidates, so it cannot refuse the way ``ambiguous``
    does (refusing would leave the page with a hole where the band goes). It names what it passed
    over instead, so a silent choice becomes a stated one.

    ``degraded_fallback`` says that that arm is the one this verdict came out of: every released
    member of the family is broken, so whatever is pinned needs review (ruling R-X4). It is
    ``True`` even when nothing was ranked — a family whose single approved member is broken is
    still a page carrying a band nobody has fixed — which is exactly the case ``ranked_over``
    alone cannot report.
    """

    root: str
    representative: Optional[str]
    ambiguous: tuple[str, ...] = ()
    ranked_over: tuple[str, ...] = ()
    degraded_fallback: bool = False


def _resolve_lineages(
    rows: List[JsonObject], *, selection: Optional[str] = None
) -> Dict[str, LineageVerdict]:
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
       back to exactly ONE approved member and NAMES what it passed over, so the pin is reported
       through ``needs_repair`` rather than chosen in silence.

    **Which member the fallback picks is FOUNDER RULING R-X4 (2026-08-29), and it is the one
    thing here a deployment chooses.** Under the default ``keep_flagged`` it is the NEWEST
    approved member — "never silently return to a known-broken original" — and under
    ``fallback_original`` it is the oldest, which for a family that still holds its harvested
    original is that original. Either way the verdict comes back with ``degraded_fallback`` set,
    because the answer is a broken band whichever end of the family it came from.

    ``selection`` is a PARAMETER with an env-backed default rather than a read inside the loop:
    one resolution must not straddle two policies, and a caller that wants to reason about both
    (the matrix test) should not have to mutate the process.

    Cycles cannot exist (``derived_from`` must resolve to an existing row at insert time and the
    column is frozen), but both walks carry a seen-set anyway: a lineage walk that could loop
    forever on corrupt data is not a thing to leave to an invariant.
    """
    chosen = selection if selection is not None else degraded_repair_selection()
    if chosen not in DEGRADED_REPAIR_SELECTIONS:
        # Loud, not defaulted. The two values differ in exactly the way ruling R-X4 is about —
        # whether a page may seat a known-broken original — so guessing one would be the system
        # silently deciding for a deployment that believed it had decided.
        raise ValueError(
            f"unknown degraded-repair selection {chosen!r}: expected one of "
            + " | ".join(DEGRADED_REPAIR_SELECTIONS)
        )
    by_id = {str(row["fragment_id"]): row for row in rows}

    def is_healthy(row: JsonObject) -> bool:
        return row.get("status") == "approved" and not row.get("degraded")

    def is_campaign_variant(row: JsonObject) -> bool:
        """A CAMPAIGN VARIANT is a sibling band, never a successor (founder ruling 2026-09-04).

        A repair exists to REPLACE a broken original, so it rightly becomes what pins of the
        original resolve to. A variant exists to serve one campaign — the homepage hero with
        one CTA and an eyebrow — and must never hijack the canonical band: found live on the
        third solo Ramp run, where the agent correctly refused to derive from Stripe's real
        hero because "deriving from the homepage hero would replace Stripe's captured band for
        every future pin", and lost the whole DERIVE-VARIANT rung to that (true) fear. The
        marker is the note prefix the repair-cloned-sections skill mandates for variants
        (`repair_reason` embeds the note in `derived_reason`); a variant keeps `derived_from`
        as provenance but starts its own family, so pins of the original keep resolving to
        the original (or its genuine repairs), and later pages pin the variant by its own id.
        """
        reason = row.get("derived_reason")
        return isinstance(reason, str) and "campaign variant" in reason.lower()

    def lineage_parent(row: JsonObject) -> str | None:
        """The parent for RESOLUTION purposes: a variant's link is provenance only."""
        if is_campaign_variant(row):
            return None
        parent = row.get("derived_from")
        return parent if isinstance(parent, str) and parent in by_id else None

    def root_of(fragment_id: str) -> str:
        seen: set = set()
        current = fragment_id
        while current not in seen:
            seen.add(current)
            row = by_id.get(current)
            parent = lineage_parent(row) if isinstance(row, dict) else None
            if parent is None:
                return current
            current = parent
        return current

    families: Dict[str, List[JsonObject]] = {}
    children: Dict[str, List[str]] = {}
    for fragment_id, row in by_id.items():
        families.setdefault(root_of(fragment_id), []).append(row)
        parent = lineage_parent(row)
        if parent is not None:
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
            #
            # R-X4: WHICH end of `approved` (it is sorted oldest first) is the deployment's one
            # choice. `keep_flagged` takes the last — the newest repair stays on the page,
            # flagged — and `fallback_original` takes the first, which for a family that still
            # holds its harvested original is that original.
            keeps_newest = chosen == DEGRADED_REPAIR_KEEP_FLAGGED
            chosen_row = (approved[-1] if keeps_newest else approved[0]) if approved else None
            passed_over = [row for row in approved if row is not chosen_row]
            verdict = LineageVerdict(
                root=root,
                representative=str(chosen_row["fragment_id"]) if chosen_row else None,
                ranked_over=tuple(
                    sorted(str(row["fragment_id"]) for row in passed_over)
                ),
                # "Every released member of this family is broken", which is the thing a human
                # has to be told — including in the single-broken-member family, where nothing
                # was ranked but the band on the page still needs somebody. A family with NO
                # approved member pins nothing, so there is nothing to flag; and it is asked of
                # the MEMBERS rather than of this arm being reached, because the arm is also
                # (harmlessly) reached by the corrupt-data cycle shape, where the answer is a
                # perfectly healthy row and calling it degraded would be a lie.
                degraded_fallback=chosen_row is not None
                and not any(is_healthy(row) for row in members),
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

    def __init__(
        self,
        *,
        blobs: DesignBlobStore,
        cache_dir: str | Path,
        isolation_fonts: Callable[[Mapping[str, Any]], IsolationFonts | None] | None = None,
    ) -> None:
        # The byte store carries the tenant; the row store is built from it rather than
        # re-derived, so the two can never name different workspaces (the D4/D5 rule the
        # custom-component registry follows).
        self.blobs = blobs
        self.workspace_id = blobs.workspace_id
        # The TURN's engine cache, threaded in rather than re-derived: a fleet worker injects its
        # own, and staging preview bytes in one tree while the runtime reads another would show
        # the agent nothing while every digest looked healthy.
        self.cache_dir = Path(cache_dir)
        self._isolation_fonts = isolation_fonts

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
        by_id = {str(row["fragment_id"]): row for row in all_rows}
        # A repair keeps its family's captured source position, even if its own
        # provenance intentionally lacks the original snapshot/layout identity.
        def source_order(row):
            verdict = lineages.get(str(row["fragment_id"]))
            original = by_id.get(verdict.root, row) if verdict else row
            return (*self._document_order(original)[:-1], str(row["fragment_id"]))

        ordered = sorted(rows, key=source_order)
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
        path: tuple = ()
        recovery = provenance.get("recovery") or {}
        parent = recovery.get("parent_dom_path")
        member = provenance.get("dom_path")
        recovered_index = recovery.get("parent_section_index")
        if (
            recovery.get("mode") == "authored-descendant-after-refusal"
            and type(recovered_index) is int and recovered_index >= 0
            and isinstance(parent, (list, tuple)) and isinstance(member, (list, tuple))
            and parent and len(member) > len(parent)
            and all(type(i) is int and i >= 0 for i in (*parent, *member))
            and list(member[:len(parent)]) == list(parent)
        ):
            index, path = recovered_index, tuple(member[len(parent):])
        return (
            _page_url(row) or "",
            int(index) if type(index) is int else 1_000_000,
            path,
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
            "source_kit_bindings": row.get("source_kit_bindings", []),
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
            # --- F4.1: was this section COMPOSED rather than harvested? ----------------------
            # `campaign_shell` for the two ABM shells (ruling R23-1's provenance marker), `None`
            # for every band lifted off a real page. Two readers depend on it: the picker, so an
            # author can tell the client's own footer from the campaign one, and the whole-page
            # recreate, which must not plant a shell on a recreated homepage or let one make the
            # workspace's page set look ambiguous.
            "composed": (
                str(provenance["composed"])
                if isinstance(provenance.get("composed"), str) and provenance["composed"]
                else None
            ),
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
            # Ruling R-X4: every released member of this family is broken, so whatever is pinned
            # from it is degraded AND REQUIRING REVIEW. `lineage_ranked_over` alone cannot say
            # this — it is empty when the family holds exactly one approved member, which is
            # still a page carrying a band nobody has fixed.
            "lineage_degraded_fallback": verdict.degraded_fallback,
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

    def read_source(self, fragment_id: str) -> JsonObject:
        """A cloned section's REAL SOURCE — its captured HTML and scoped CSS — plus its slots.

        The raw lane's whole premise is "remix the original's actual bytes", and until this
        existed no tool showed the agent those bytes: `search_cloned_sections` lists slots and a
        preview handle, `view` shows a picture. Found live 2026-09-04 (third solo Ramp run): the
        agent spent eight calls grepping the workspace filesystem — other runs' directories
        included — for clone markup that lives in blob storage, then composed from memory. This
        is a read of any fragment the workspace holds (draft or released; inspecting is not
        pinning, and the pin gate is unchanged), the same payload every pin resolves through.
        """
        loaded = read_web_fragment(
            self.blobs.storage,
            workspace_id=self.workspace_id,
            fragment_id=fragment_id,
        )
        row = loaded.row
        payload = loaded.payload
        provenance = row.get("provenance")
        provenance = provenance if isinstance(provenance, dict) else {}
        # Only capture evidence, never arbitrary provider payloads or reconstructed facts.
        # created_at is a registry timestamp, not a claim that the source was fetched then.
        capture_evidence = {
            key: provenance[key]
            for key in (
                "snapshot_id", "viewport_width", "preview_basis", "geometry",
                "dead_height_check", "hidden_on_source", "recovery", "degraded",
            )
            if key in provenance
        }
        return {
            "fragment_id": fragment_id,
            "section_role": row.get("section_role"),
            "label": row.get("label"),
            "source_url": row.get("source_url"),
            "status": row.get("status"),
            "derived_from": row.get("derived_from"),
            "source_kit_id": row.get("source_kit_id"),
            "source_kit_version": row.get("source_kit_version"),
            "source_kit_bindings": row.get("source_kit_bindings", []),
            "page_url": _page_url(row),
            "section_index": provenance.get("section_index"),
            "created_at": row.get("created_at"),
            "payload_digest": row.get("payload_digest"),
            "degraded": bool(row.get("degraded")),
            "degraded_reason": row.get("degraded_reason"),
            "composed": provenance.get("composed"),
            "capture_evidence": capture_evidence,
            "behavior_evidence": inspect_fragment_behavior(
                str(payload.get("html") or ""), payload.get("native_dependencies")
            ),
            "slots": _slot_summary(loaded.slot_manifest),
            "html": str(payload.get("html") or ""),
            "css": str(payload.get("css") or ""),
        }

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
        provenance = row.get("provenance")
        provenance = provenance if isinstance(provenance, dict) else {}
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
            # --- F4.1's composed marker, on the PIN path too (T23 finding N6) -----------------
            # The picker projects it (`_section_row`), but every door that puts a section on a
            # page rebuilds its turn-local row from THIS answer — so without it the marker was
            # erased at the exact moment an author is most likely to look at what they just
            # pinned, and the view tool told them a browser had measured a shell that was
            # composed from the brand kit. The provenance is already read here; this costs a key.
            "composed": (
                str(provenance["composed"])
                if isinstance(provenance.get("composed"), str) and provenance["composed"]
                else None
            ),
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
            # R-X4, on the PIN path too: the band about to go on the page is the newest of a
            # wholly broken family, which the warning has to say out loud rather than reporting
            # a repair as if releasing it had fixed anything.
            "lineage_ranked_over": list(verdict.ranked_over) if verdict is not None else [],
            "lineage_degraded_fallback": (
                verdict.degraded_fallback if verdict is not None else False
            ),
            # Exactly the entry `build_fragment_render_package` writes, so a section inserted
            # mid-turn renders in the agent's own preview through the map that is already
            # threaded — no second render path, and no shape for the two to disagree on.
            "render": {
                **native_render_fields(loaded.payload),
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

    def prepare_source_flows(self, fragment_ids: Sequence[str]) -> JsonObject:
        """Read exact captured envelopes after the ordinary per-fragment release gate.

        No artifact, release state, snapshot or asset is written. Each snapshot is
        loaded once per call. Missing/unsupported source context is returned as an
        explicit assembly gap, never replaced by measured or invented spacing.
        """
        if (
            len(fragment_ids) > CLONED_SECTION_LIST_MAX
            or len(set(fragment_ids)) != len(fragment_ids)
        ):
            raise SourceFlowUnavailable("bound", "assembly ids exceed the supported bound")
        repository = self._repository()
        rows = {}
        buckets = {}
        gaps = []

        def read(fid):
            if fid not in rows:
                rows[fid] = repository.find_web_fragment(fid)
            return rows[fid]

        for fid in fragment_ids:
            repository.validate_fragment_reference_changes(
                before_web_doc={}, after_web_doc=_probe_web_doc(fid)
            )
            row = read(fid)
            original = row
            seen = set()
            while original.get("derived_from"):
                parent_id = str(original["derived_from"])
                if parent_id in seen or len(seen) >= 40:
                    raise SourceFlowUnavailable(
                        "lineage", "source lineage is cyclic or exceeds bound"
                    )
                seen.add(parent_id)
                original = read(parent_id)
            p = original.get("provenance") or {}
            recovery = p.get("recovery") or {}
            if recovery.get("mode") != "authored-descendant-after-refusal":
                continue
            path = recovery.get("parent_dom_path")
            if (
                not isinstance(path, (list, tuple))
                or not path
                or any(type(i) is not int or i < 0 for i in path)
            ):
                gaps.append(
                    {
                        "code": "source_flow.source_mismatch",
                        "member_ids": [fid],
                        "message": "captured parent path is absent or invalid",
                    }
                )
                continue
            key = (str(p.get("snapshot_id") or ""), tuple(path))
            buckets.setdefault(key, []).append(row)

        snapshots = {}
        groups = []
        for (snapshot_id, _), members in buckets.items():
            ids = [str(row["fragment_id"]) for row in members]
            try:
                if any(row.get("derived_from") for row in members):
                    raise SourceFlowUnavailable(
                        "incompatible_repair",
                        "repaired member has no verified shared source layout",
                    )
                if not snapshot_id:
                    raise SourceFlowUnavailable(
                        "snapshot_unavailable", "recovery has no immutable snapshot id"
                    )
                if snapshot_id not in snapshots:
                    try:
                        snapshots[snapshot_id] = read_site_snapshot(
                            self.blobs.storage,
                            workspace_id=self.workspace_id,
                            snapshot_id=snapshot_id,
                        )
                    except Exception:  # custody boundary; do not leak storage paths or row details
                        snapshots[snapshot_id] = None
                snapshot = snapshots[snapshot_id]
                if snapshot is None:
                    raise SourceFlowUnavailable(
                        "snapshot_unavailable", "immutable captured source could not be read"
                    )
                groups.append(compile_source_flow(snapshot, members))
            except SourceFlowUnavailable as error:
                gaps.append({"code": error.code, "member_ids": ids, "message": str(error)[:500]})
        return {"groups": groups, "gaps": gaps, "fidelity_verified": False}

    # --- the repair mint (F3.1, ruling D-F6) --------------------------------------------------

    def mint_href_repair(
        self, *, replaces: str, replacements: Mapping[str, str] | None = None,
        label_replacements: Mapping[str, str] | None = None, rung: int, note: str,
        text_edits: list[dict[str, str]] | None = None,
    ) -> JsonObject:
        """Repair exact anchors/text from held source; preserve markup, assets and CSS."""
        original = self._repository().find_web_fragment(replaces)
        if original is None:
            raise FragmentRefused("fragment.unresolved", "this workspace holds no such fragment")
        reason = repair_reason(rung=rung, trigger=original.get("degraded_reason"), note=note)
        provenance = _repair_provenance(original, rung=rung, note=note, replaces=replaces)
        provenance["repair"]["source"] = (
            "captured_text_repair" if text_edits is not None else
            "captured_anchor_repair" if label_replacements is not None else "captured_href_repair"
        )
        row, repair, converged = create_href_repaired_fragment(
            self.blobs.storage, workspace_id=self.workspace_id, replaces=replaces,
            replacements=replacements, label=_repair_label(original), derived_reason=reason,
            provenance=provenance, label_replacements=label_replacements, text_edits=text_edits,
        )
        fragment_id = repair.artifact.fragment_id
        if row.get("status") == "draft":
            try:
                row = set_web_fragment_status(
                    workspace_id=self.workspace_id, fragment_id=fragment_id, status="approved",
                )
            except Exception as error:
                raise FragmentRefused(
                    "repair.release_unconfirmed",
                    f"repair {fragment_id} was minted, but release could not be confirmed; "
                    "the page is unchanged",
                    reference=fragment_id,
                ) from error
        return {
            "fragment_id": fragment_id, "status": row.get("status"),
            "derived_from": row.get("derived_from"), "match_counts": repair.match_counts,
            "label_match_counts": repair.label_match_counts,
            "text_match_paths": repair.text_match_paths,
            "derived_reason": row.get("derived_reason"), "requested_derived_reason": reason,
            "converged": converged,
            "lineage_kept": (
                row.get("derived_from") == replaces and row.get("derived_reason") == reason
            ),
            "slot_keys": list(repair.artifact.payload["slot_manifest"]),
            "insertable": row.get("status") == "approved",
        }

    def mint_repair(
        self,
        *,
        replaces: str,
        html: str,
        css: str,
        rung: int,
        note: str,
        release: bool = False,
        native_dependencies: dict[str, Any] | None = None,
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

        # A shell-role repair mints under the SHELL contract (ruling R23-F1, fix-round I2): the
        # campaign-shell shape check runs on it exactly as on the shell it replaces — this door
        # was the one producer of `campaign_header` fragments the check never saw — and its
        # editing surface is the RULED slots, not whatever the harvest detector finds. Since
        # founder ruling R-F5-8 what the check finds is ADVICE the caller hands back, never a
        # refusal: a nav-carrying repair mints, with the note attached. A repair whose markup
        # dropped a marker class still refuses typed at the annotator
        # (`fragment.slot_selector_unmatched`) — that is a broken slot surface, not a taste.
        original_role = str(original.get("section_role") or "other")
        shape_notes: list[str] = []
        if original_role in CAMPAIGN_SHELL_ROLES:
            shape_notes = campaign_shell_shape_notes(original_role, sanitized.html)
            slot_specs = list(campaign_shell_slots(original_role))
        else:
            slot_specs = list(detect_slots(sanitized.html).specs)

        # The original's markup AND CSS, for the "did this repair anything?" check
        # below. Fail-SOFT on an unreadable original: a purged payload must not block repairing
        # the very fragment most in need of it, and nothing about preserving the original
        # depends on this read.
        try:
            existing = read_web_fragment(
                self.blobs.storage, workspace_id=self.workspace_id, fragment_id=replaces
            )
        except (NotFoundError, FragmentRefused):
            existing = None

        if existing is not None and existing.payload.get("native_dependencies") and native_dependencies is None:
            raise FragmentRefused(
                "fragment.native_dependency_unsupported",
                "raw HTML/CSS repair of a native fragment cannot preserve its declared behavior; "
                "use exact text/link edits or a checked vocabulary replacement",
            )

        probe = build_fragment_artifact(
            html=sanitized.html,
            css=css,
            rehosted={},
            slots=slot_specs,
            preview_digest=None,
            prelude_reference=PRELUDE_REFERENCE_STRIP,
            source_fragment_id=replaces,
            native_dependencies=native_dependencies,
        )
        already = repository.find_web_fragment(probe.fragment_id)
        original_css = None
        if existing is not None:
            original_css = scope_fragment_css(
                existing.css, fragment_id=probe.fragment_id, source_fragment_id=replaces,
                rehosted={}, prelude_reference=PRELUDE_REFERENCE_STRIP,
            ).css
        if (
            existing is not None and probe.payload["html"] == existing.html
            and probe.payload["css"] == original_css
            and probe.payload["slot_manifest"] == existing.slot_manifest
            and probe.payload.get("native_dependencies") == existing.payload.get("native_dependencies")
        ):
            # A "repair" that reproduces the broken band is not one. Without this it would mint
            # as a NEW fragment holding the same markup — and NOT degraded, because the marker is
            # a row-level judgement rather than part of the content, so it does not follow the
            # bytes. A clean-looking duplicate of a band the pipeline has already measured as
            # broken is the one outcome D-F6 exists to prevent.
            #
            # Compare stored markup and CSS under one namespace: changing CSS alone can repair
            # real geometry, while an identical band with a new namespace is still a no-op.
            # The error direction is toward allowing a mint: an
            # original whose slots were stamped by something other than this detector annotates
            # differently and is not caught. That is the safe way round — the original survives
            # either way, and refusing a genuine repair would be the worse mistake.
            raise FragmentRefused(
                "fragment.repair_unchanged",
                f"this repair's markup and effective CSS are identical to {replaces}, "
                "so it repairs nothing. Walk "
                "the ladder: reproduce the experience with supported primitives, build an "
                "equivalent interaction, or compose a compact static fallback with the "
                "artificial height removed.",
                reference=replaces,
            )

        reason = repair_reason(
            rung=rung, trigger=original.get("degraded_reason"), note=note
        )
        # `release` (founder ruling A, 2026-08-30): a RAW-CSS repair must be pinned to render,
        # and the persistence gate forbids draft pins — so the raw path mints and releases in
        # one act, R-I5 honored (birth is draft; release is the ordinary explicit transition).
        # The vocabulary path keeps release=False and R-X9's chat door unchanged.
        row, artifact = create_web_fragment(
            self.blobs.storage,
            workspace_id=self.workspace_id,
            html=sanitized.html,
            css=css,
            rehosted={},
            slots=slot_specs,
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
            source_fragment_id=replaces,
            native_dependencies=native_dependencies,
        )
        converged = already is not None
        status = str(row.get("status") or "")
        if release and status == "draft":
            released = set_web_fragment_status(
                workspace_id=self.workspace_id,
                fragment_id=str(row["fragment_id"]),
                status="approved",
            )
            status = str(released.get("status") or status)
            row = dict(row)
            row["status"] = status
        return {
            "fragment_id": artifact.fragment_id,
            "replaces": replaces,
            "status": row.get("status"),
            "section_role": row.get("section_role"),
            "label": row.get("label"),
            "derived_from": row.get("derived_from"),
            "derived_reason": row.get("derived_reason"),
            "requested_derived_reason": reason,
            "slot_keys": [spec.key for spec in slot_specs],
            "asset_digests": list(artifact.payload.get("asset_digests") or []),
            # Private runtime fact: exact stored DOM equality preserves human override paths;
            # identical keys alone would not. No second source read is needed at the swap.
            "preserves_pin_content": bool(
                existing is not None and artifact.payload["html"] == existing.html
                and slot_kinds(artifact.payload["slot_manifest"]) == slot_kinds(existing.slot_manifest)
            ),
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
            # R-F5-8: the campaign-shell shape is PRACTICE, not a gate. What the shape check
            # found (if anything) rides back as sentences the agent reads and judges — the mint
            # happened either way, because links are structurally free.
            "advice": shape_notes,
            # A fresh repair is `draft`, so the answer is almost always False — and it is the
            # caller's job to say so out loud rather than to imply a pin that did not happen.
            "insertable": row.get("status") == "approved",
        }

    # --- composing a NEW raw-CSS section (founder ruling 2026-08-30) ---------------------------

    def compose_section(
        self,
        html: str,
        css: str,
        *,
        section_role: str = "other",
        label: str | None = None,
        note: str,
    ) -> JsonObject:
        """Mint an AGENT-COMPOSED section from raw HTML + raw CSS — full fidelity, same door.

        The raw-CSS authoring lane (founder ruling 2026-08-30): the agent writes real HTML and
        real CSS — its native language, and the only representation that can match a source
        site's fidelity — and the result becomes a first-class library fragment through the
        EXACT pipeline every captured byte already passes: `sanitize_fragment_html` (scripts and
        handlers stripped, every byte reference fail-closed against registered assets),
        `annotate/detect` slots (so the band stays rebindable later), `scope_fragment_css`
        (selectors caged under the wrapper class, cascade layers flattened, markup-breakout
        gate). No parallel trust surface exists: what ingestion may not store, this may not
        store either.

        **Born released, deliberately.** The founder's autonomy ruling: an agent-composed
        section carries no human release door — it is minted and immediately approved, so the
        composing run can pin it with the ordinary `insert_cloned_section`. R-I5's birth rule is
        honored, not bypassed: the mint births `draft` and the release is the same explicit
        `set_web_fragment_status` transition every other release uses, recorded in provenance.

        **Shell roles keep their contract.** A composed `campaign_header`/`campaign_footer`
        runs the same campaign-shell shape check and takes the same RULED slot set as every other
        producer of those roles (R23-F1) — this door does not bypass R23-3, and since founder
        ruling R-F5-8 that check's findings come back in `advice` rather than refusing the mint.

        Provenance carries ``composed: "agent"`` — listed and insertable like any released
        section, and excluded from whole-page recreates exactly like the campaign shells
        (a composed band came off no source page).
        """
        cleaned_note = " ".join((note or "").split())
        if not cleaned_note:
            raise FragmentRefused(
                "fragment.compose_note_missing",
                "note is one line saying what this composed section is for; it is recorded "
                "permanently in provenance, so it cannot be blank.",
            )
        clean_role = (section_role or "other").strip().lower() or "other"
        sanitized = sanitize_fragment_html(html, rehosted={})
        shape_notes: list[str] = []
        if clean_role in CAMPAIGN_SHELL_ROLES:
            shape_notes = campaign_shell_shape_notes(clean_role, sanitized.html)
            slot_specs = list(campaign_shell_slots(clean_role))
        else:
            slot_specs = list(detect_slots(sanitized.html).specs)

        row, artifact = create_web_fragment(
            self.blobs.storage,
            workspace_id=self.workspace_id,
            html=sanitized.html,
            css=css,
            rehosted={},
            slots=slot_specs,
            source_url="composed:agent",
            section_role=clean_role,
            label=label or f"Composed — {cleaned_note[:80]}",
            preview=None,
            provenance={
                "composed": "agent",
                "note": cleaned_note,
                "released_by": "agent-compose (founder autonomy ruling 2026-08-30)",
            },
            prelude_reference=PRELUDE_REFERENCE_STRIP,
        )
        status = str(row.get("status") or "")
        if status == "draft":
            released = set_web_fragment_status(
                workspace_id=self.workspace_id,
                fragment_id=str(row["fragment_id"]),
                status="approved",
            )
            status = str(released.get("status") or status)
        return {
            "fragment_id": str(row["fragment_id"]),
            "status": status,
            "section_role": row.get("section_role"),
            "label": row.get("label"),
            "slot_keys": [spec.key for spec in slot_specs],
            "asset_digests": list(artifact.payload.get("asset_digests") or []),
            "sanitizer_notes": list(sanitized.notes) + list(artifact.notes),
            # R-F5-8: the campaign-shell shape is PRACTICE, not a gate. What the shape check
            # found (if anything) rides back as sentences the agent reads and judges — the mint
            # happened either way, because links are structurally free.
            "advice": shape_notes,
            # Content addressing: identical bytes converge onto the existing row
            # (first-writer-wins), whose status/lineage survive.
            "insertable": status == "approved",
        }

    # --- releasing ONE repair (F4.4, FOUNDER RULING R-X9) --------------------------------------

    def render_repair_preview(
        self, fragment_id: str, core: Any, *, shoot: Optional[Any] = None
    ) -> Optional[str]:
        """Photograph a repair's own bytes in isolation and hang the picture on its row (P-7).

        The same machinery ``POST /web/fragments/{id}/preview`` runs, reachable from a turn: a
        repair is composed and minted with ``preview=None`` (nobody ever photographed it), and
        ruling R-X9 says a human may not be asked to approve a section nobody can look at. So the
        evidence has to be MAKEABLE from where the asking happens.

        Returns the attached digest, or ``None`` when the row already carries a preview (a
        preview is attached once, never replaced — the decision that was made was made against
        the picture that is there). Every genuine failure raises
        :class:`~lumen_api.fragments.isolation.IsolationRenderFailed` with a code, because a
        release flow that quietly proceeds without a picture is the thing the ruling forbids.

        ``shoot`` is the browser half, injectable for the same reason the route's is (F3.4): a
        test that had to reach in and rebind a module attribute to avoid launching Chromium is a
        test that can silently stop exercising the seam it was written for.
        """
        from .fragments import (
            ISOLATION_PREVIEW_MEDIA_TYPE,
            attach_web_fragment_preview,
            render_isolation_preview,
        )

        loaded = read_web_fragment(
            self.blobs.storage, workspace_id=self.workspace_id, fragment_id=fragment_id
        )
        if loaded.row.get("preview_digest"):
            return None
        # Keep the sealed stylesheet; only its pinned kit's font-face declarations are supplied
        # by the composition root, through the same font resolver the page render uses.
        fonts = self._isolation_fonts(loaded.row) if self._isolation_fonts else None
        kwargs = {"shoot": shoot} if shoot is not None else {}
        png, page = render_isolation_preview(
            core, loaded, read_blob=self.blobs.read_blob, fonts=fonts, **kwargs
        )
        row = attach_web_fragment_preview(
            self.blobs.storage,
            workspace_id=self.workspace_id,
            fragment_id=fragment_id,
            preview=png,
            preview_basis=page.basis,
            media_type=ISOLATION_PREVIEW_MEDIA_TYPE,
        )
        return row.get("preview_digest")

    def release_repair(self, fragment_id: str) -> JsonObject:
        """Release exactly ONE draft repair, because a human said so (ruling R-X9).

        FOUNDER RULING R-X9 (2026-08-29): "require individual approval for each repair; brand-kit
        approval should not silently approve later repairs". The kit cascade no longer moves a
        row with ``derived_from`` set (``clue_design.web_fragments.sync_kit_fragment_approval``),
        which leaves repairs with no release surface at all — this is that surface, and it is the
        enactment of a human's answer in a conversation, never a decision of its own.

        Three structural gates, all fail-closed and all typed:

        * **it must be a repair.** ``derived_from IS NULL`` is a harvested original or a composed
          campaign shell, and those keep the release law they already have (the kit approval, and
          T23's re-approval for shells). Releasing one through here would be a second, quieter
          door onto a surface that already has one.
        * **it must still be a draft.** An already-approved row is nothing to release, and
          ``deprecated``/``dormant`` are narrower decisions somebody made deliberately — a
          "release" that undid a retirement would be this tool overruling a human by accident.
        * **it must have a usable preview.** Nothing here can decide blindly on a human's behalf,
          so a repair no picture exists of is refused by name rather than released on trust. The
          remedy is one call away (:meth:`render_repair_preview`), which is why the refusal names
          it instead of merely reporting the gap.

        One id per call, deliberately. "Individual approval for each repair" is not a shape a
        batch can have.
        """
        repository = self._repository()
        row = repository.find_web_fragment(fragment_id)
        if row is None:
            raise FragmentRefused(
                "fragment.unresolved",
                f"this workspace holds no fragment {fragment_id!r}, so there is nothing to "
                "release",
                reference=fragment_id,
            )
        if not row.get("derived_from"):
            raise FragmentRefused(
                "repair.not_a_repair",
                f"{fragment_id} is not a repair — it is a harvested section or a composed "
                "shell, and those are released by approving the brand kit they belong to. This "
                "door exists only for a repair somebody composed to replace a broken band.",
                reference=fragment_id,
            )
        status = str(row.get("status") or "")
        if status != "draft":
            raise FragmentRefused(
                "repair.not_releasable",
                f"repair {fragment_id} is {status!r}, not 'draft': "
                + (
                    "it is already released, so there is nothing to do"
                    if status == "approved"
                    else "a retired or dormant section is somebody's deliberate narrower "
                    "decision, and releasing it here would overrule them"
                ),
                reference=fragment_id,
            )
        if not row.get("preview_digest"):
            raise FragmentRefused(
                "repair.no_preview",
                f"repair {fragment_id} has no preview image, so nobody can see what they would "
                "be approving. Render one first — the isolation render draws the repair's own "
                "bytes — and show it, then ask.",
                reference=fragment_id,
            )
        released = set_web_fragment_status(
            workspace_id=self.workspace_id, fragment_id=fragment_id, status="approved"
        )
        return {
            "fragment_id": fragment_id,
            "status": released.get("status"),
            "derived_from": released.get("derived_from"),
            "derived_reason": released.get("derived_reason"),
            "label": released.get("label"),
            "section_role": released.get("section_role"),
            "preview_digest": released.get("preview_digest"),
        }

    # --- the campaign shells (F4.1, rulings R23-1/2/3) -----------------------------------------

    def campaign_shell_placeholder(self) -> JsonObject:
        """Give the co-brand placeholder durable custody, and hand back what pins it.

        Returns ``{asset_id, digest, media_type, byte_length, record}`` — the engine
        ``AssetRecord`` the composing turn upserts into its scratch document, plus the digest the
        artifact will cite. Idempotent: the blob is content-addressed, so calling this on every
        mint costs one row lookup and no bytes after the first time.

        It exists because the engine refuses an ``<img>`` with no asset (``LUMW0111``), and the
        header must carry a co-brand image element whose default is NOTHING. See
        :data:`~lumen_api.fragments.campaign_shell.COBRAND_PLACEHOLDER_PNG` for why an invisible
        1×1 is the honest spelling of an empty logo slot rather than a synthesized one.
        """
        self.blobs.register(
            COBRAND_PLACEHOLDER_PNG,
            media_type=COBRAND_PLACEHOLDER_MEDIA_TYPE,
            source_key=WEB_FRAGMENT_SOURCE_KEY,
        )
        digest = hashlib.sha256(COBRAND_PLACEHOLDER_PNG).hexdigest()
        return {
            "asset_id": COBRAND_PLACEHOLDER_ASSET_ID,
            "digest": digest,
            "media_type": COBRAND_PLACEHOLDER_MEDIA_TYPE,
            "byte_length": len(COBRAND_PLACEHOLDER_PNG),
            "record": {
                "id": COBRAND_PLACEHOLDER_ASSET_ID,
                "label": "Co-brand placeholder",
                "kind": "raster_image",
                "status": "ready",
                "source": {
                    "kind": "generated",
                    "model": COMPOSED_CAMPAIGN_SHELL,
                    "request_id": None,
                },
                "media": {
                    "mime_type": COBRAND_PLACEHOLDER_MEDIA_TYPE,
                    "filename": "campaign-shell-cobrand.png",
                    "byte_length": len(COBRAND_PLACEHOLDER_PNG),
                    "digest": {"algorithm": "sha256", "value": digest},
                    "location": None,
                },
            },
        }

    #: How many harvested bands the legal-link scan opens. The client's legal links live in their
    #: footer; a handful of the newest footer/nav clones is all the evidence there is, and each
    #: one costs a payload read.
    LEGAL_EVIDENCE_MAX = 4

    def legal_link_evidence(self, *, kit_id: Optional[str] = None) -> List[tuple]:
        """``[(html, page_url), …]`` from this workspace's RELEASED footer clones.

        The seller's own privacy and terms links, in the markup their own site produced — which
        is the only place F4.1 will take them from. Fail-SOFT per row: a purged payload costs its
        own evidence and nothing else, because a footer with no legal block is a correct footer
        (R23-2's empty-and-clean) and must never be the reason a shell refuses to mint.

        Three filters, each a fix-round I3 rule about what may supply the links that ship on
        every ABM page:

        * **``approved`` only.** A ``dormant`` footer is hidden on the source site (D-F8), a
          ``deprecated`` one is retired, and a ``draft`` one has not been judged fit to reuse —
          none of them is evidence of what the seller's live site links.
        * **``footer`` role only.** A nav is full of product links — the exact false-positive
          surface C1 closed — and the legal block lives in the footer.
        * **This kit's rows, when ``kit_id`` is given.** In a multi-brand workspace another
          brand's footer is another brand's law.
        """
        rows = [
            row
            for row in self._repository().list_web_fragments()
            if row.get("section_role") == "footer"
            and row.get("status") == "approved"
            and (kit_id is None or fragment_has_kit_binding(row, kit_id))
        ]
        evidence: List[tuple] = []
        for row in rows[: self.LEGAL_EVIDENCE_MAX]:
            try:
                loaded = read_web_fragment(
                    self.blobs.storage,
                    workspace_id=self.workspace_id,
                    fragment_id=str(row["fragment_id"]),
                )
            except (NotFoundError, FragmentRefused):
                continue
            evidence.append((loaded.html, _page_url(row) or ""))
        return evidence

    def mint_campaign_shell(
        self,
        *,
        role: str,
        html: str,
        css: str,
        label: str,
        source_kit_id: Optional[str] = None,
        source_kit_version: Optional[int] = None,
        composition: Optional[Mapping[str, Any]] = None,
    ) -> JsonObject:
        """Mint one campaign shell — the identical fragment path, plus the shape check's notes.

        ``html`` is the ENGINE's own render of the composed shell (ruling R23-1, the same rule the
        repair mint obeys) and ``css`` the utilities that render compiles against the kit's theme.
        The order below is the mint pipeline's own, unchanged:

        sanitize (fail-closed on an un-rehostable byte reference, handlers stripped, banned
        elements dropped) → **the campaign-shell shape check** → annotate the RULED slots → scope
        the CSS under the fragment's wrapper → content-address → insert the row.

        The one addition is :func:`campaign_shell_shape_notes`, and it sits HERE rather than in
        the composer on purpose (ruling R23-3): the practice is about SHELLS, and a rule known
        only to the thing that writes the markup is a rule about that writer. It runs on the
        SANITIZED form — what the artifact will literally be — so a link the sanitizer would have
        kept is a link the check has seen. Founder ruling R-F5-8 (2026-09-02) made its findings
        ADVICE: they ride back in the result's `advice`, and the shell mints regardless. Links
        are structurally free; the agent is told, not stopped.

        Slots are the RULED ones, not detected ones. A campaign shell's editing surface is the
        contract in R23-2, and running the harvest detector over it would offer whatever the
        composition happened to look like — a different surface every time the strip changes.

        Born ``draft`` like every other fragment (ruling R-I5): a human releases the shells by
        approving the brand kit they belong to. Content-addressed like every other fragment, so
        re-minting the same shell for the same kit converges onto the row that already holds it
        rather than growing a second one.
        """
        if role not in CAMPAIGN_SHELL_ROLES:
            raise ValueError(
                f"{role!r} is not a campaign shell role; expected one of "
                f"{', '.join(CAMPAIGN_SHELL_ROLES)}"
            )
        sanitized = sanitize_fragment_html(html, rehosted={})
        shape_notes = campaign_shell_shape_notes(role, sanitized.html)
        slots = campaign_shell_slots(role)

        probe = build_fragment_artifact(
            html=sanitized.html,
            css=css,
            rehosted={},
            slots=list(slots),
            preview_digest=None,
            prelude_reference=PRELUDE_REFERENCE_STRIP,
        )
        already = self._repository().find_web_fragment(probe.fragment_id)

        provenance: JsonObject = {
            # The marker every surface reads to tell a shell from a harvested clone.
            "composed": COMPOSED_CAMPAIGN_SHELL,
            "shell_role": role,
            "slots": [spec.key for spec in slots],
            # NOT a page url, and deliberately absent rather than faked: a shell sat on no page,
            # so it takes part in no page's recreate and no page's ordering.
            "page_url": None,
            "section_index": None,
            "section_role": role,
        }
        if composition:
            provenance["composition"] = dict(composition)

        row, artifact = create_web_fragment(
            self.blobs.storage,
            workspace_id=self.workspace_id,
            html=sanitized.html,
            css=css,
            rehosted={},
            slots=list(slots),
            source_url=CAMPAIGN_SHELL_SOURCE_URL,
            section_role=role,
            label=label,
            source_kit_id=source_kit_id,
            source_kit_version=source_kit_version,
            preview=None,
            provenance=provenance,
            prelude_reference=PRELUDE_REFERENCE_STRIP,
        )
        return {
            "fragment_id": artifact.fragment_id,
            "shell_role": role,
            "section_role": row.get("section_role"),
            "status": row.get("status"),
            "label": row.get("label"),
            "composed": COMPOSED_CAMPAIGN_SHELL,
            "slot_keys": [spec.key for spec in slots],
            "slot_manifest": dict(artifact.payload.get("slot_manifest") or {}),
            "asset_digests": list(artifact.payload.get("asset_digests") or []),
            # The FIRST pass's notes are the real ones (`create_web_fragment` sanitizes again,
            # idempotently, over markup this method already cleaned).
            "sanitizer_notes": list(sanitized.notes) + list(artifact.notes),
            # R-F5-8: the campaign-shell shape is PRACTICE, not a gate. What the shape check
            # found (if anything) rides back as sentences the agent reads and judges — the mint
            # happened either way, because links are structurally free.
            "advice": shape_notes,
            # Content addressing, said out loud: the same shell for the same kit converges.
            "converged": already is not None,
            "insertable": row.get("status") == "approved",
        }


    # --- site header and footer templates (site element inspector, plan 6) ----------------------

    #: Where each template role is derived from: the kit's captured bands of this role.
    SITE_TEMPLATE_SOURCES = {"site_header": "nav", "site_footer": "footer"}

    def mint_site_template(self, *, role: str, source_fragment_id: str) -> JsonObject:
        """Mint one ABM header or footer template from a captured nav or footer band (rulings R4-R6).

        The derivation (:func:`~lumen_api.fragments.site_templates.derive_site_template`) is
        deterministic; the markup it returns goes through the identical fragment door every clone and
        repair goes through (sanitize, annotate its slots, scope the CSS against the source's,
        content-address, insert). **Released at once** (founder 2026-10-18: no approval gate), so the
        agent is offered it as soon as it exists. Converges onto the row that already holds the same
        template when it is minted again.
        """
        from .fragments.site_templates import COMPOSED_SITE_TEMPLATE, SITE_TEMPLATE_ROLES, derive_site_template

        if role not in SITE_TEMPLATE_ROLES:
            raise ValueError(f"{role!r} is not a site template role")
        original = self._repository().find_web_fragment(source_fragment_id)
        if original is None:
            raise FragmentRefused(
                "fragment.unresolved",
                f"cannot derive a template from {source_fragment_id!r}: this workspace holds no such fragment",
                reference=source_fragment_id,
            )
        loaded = read_web_fragment(self.blobs.storage, workspace_id=self.workspace_id, fragment_id=source_fragment_id)
        placeholder = self.campaign_shell_placeholder()
        derived = derive_site_template(role, loaded.html, placeholder_src=f"/asset-store/{placeholder['digest']}")
        sanitized = sanitize_fragment_html(derived.html, rehosted={})
        source_url = str(original.get("source_url") or "")
        seller = (urlsplit(source_url).hostname or "the seller").removeprefix("www.")
        label = f"{'Header' if role == 'site_header' else 'Footer'} template — {seller}"
        row, artifact = create_web_fragment(
            self.blobs.storage,
            workspace_id=self.workspace_id,
            html=sanitized.html,
            css=f"{loaded.css}\n{derived.css_addition}" if derived.css_addition else loaded.css,
            rehosted={},
            slots=list(derived.slots),
            source_url=source_url,
            section_role=role,
            label=label,
            source_kit_id=original.get("source_kit_id"),
            source_kit_version=original.get("source_kit_version"),
            preview=None,
            provenance={
                "composed": COMPOSED_SITE_TEMPLATE,
                "shell_role": role,
                "source_fragment_id": source_fragment_id,
                "page_url": _page_url(original),
                "section_index": None,
                "section_role": role,
                "slots": [spec.key for spec in derived.slots],
            },
            prelude_reference=PRELUDE_REFERENCE_STRIP,
            derived_from=source_fragment_id,
            derived_reason="site template",
            source_fragment_id=source_fragment_id,
        )
        status = str(row.get("status") or "")
        if status == "draft":
            status = str(
                set_web_fragment_status(workspace_id=self.workspace_id, fragment_id=artifact.fragment_id, status="approved").get("status")
                or "approved"
            )
        return {
            "fragment_id": artifact.fragment_id,
            "role": role,
            "status": status,
            "label": row.get("label") or label,
            "slot_keys": [spec.key for spec in derived.slots],
            "notes": list(derived.notes) + list(sanitized.notes),
            "converged": row.get("derived_from") == source_fragment_id and status == "approved",
        }

    def site_template_sources(self, *, kit_id: str, kit_version: int) -> Dict[str, Optional[JsonObject]]:
        """Each template role's best captured band of one kit version (ruling R4): the home page's,
        else the shortest page path, else document order; a degraded band is never used. None for a
        role the kit captured no usable band for."""
        rows = [
            row
            for row in self._repository().list_web_fragments()
            if row.get("source_kit_id") == kit_id
            and int(row.get("source_kit_version") or -1) == int(kit_version)
            and not row.get("degraded")
            and str(row.get("status") or "") in {"draft", "approved"}
        ]

        def rank(row: JsonObject) -> tuple:
            path = urlsplit(_page_url(row) or "").path or "/"
            return (path != "/", len(path), path, *self._document_order(row))

        return {
            role: min((row for row in rows if row.get("section_role") == band), key=rank, default=None)
            for role, band in self.SITE_TEMPLATE_SOURCES.items()
        }

    def mint_site_templates(self, *, kit_id: str, kit_version: int) -> List[JsonObject]:
        """Both templates of one kit version, each from its best captured band. A role with no usable
        band, or whose band is not derivable, is skipped with the reason."""
        from .fragments.site_templates import TemplateNotDerivable

        results: List[JsonObject] = []
        for role, source in self.site_template_sources(kit_id=kit_id, kit_version=kit_version).items():
            if source is None:
                results.append({"role": role, "skipped": f"no captured {self.SITE_TEMPLATE_SOURCES[role]}"})
                continue
            try:
                results.append(self.mint_site_template(role=role, source_fragment_id=str(source["fragment_id"])))
            except (TemplateNotDerivable, FragmentRefused) as error:
                results.append({"role": role, "skipped": getattr(error, "reason", None) or str(error)})
        return results


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

    ``composed`` is inherited too (ruling R23-F1, fix-round I2): a repair of a campaign shell is
    still a composed shell, and every surface that reads the marker — the picker's note, the
    recreate's exclusion — must see it on the repair or the §1.8 defects re-enter through this
    door. For a composed original, ``page_url`` stays ``None`` rather than falling back to the
    ``composed:`` sentinel ``source_url``: a shell sat on no page, and neither does its repair.
    """
    inherited = original.get("provenance")
    inherited = inherited if isinstance(inherited, dict) else {}
    composed = inherited.get("composed")
    composed = composed if isinstance(composed, str) and composed else None
    provenance: JsonObject = {
        "page_url": inherited.get("page_url")
        or (None if composed else original.get("source_url")),
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
    if composed:
        provenance["composed"] = composed
        shell_role = inherited.get("shell_role")
        if isinstance(shell_role, str) and shell_role:
            provenance["shell_role"] = shell_role
    return provenance


__all__ = [
    "CLONED_SECTION_LIST_MAX",
    "CLONED_SECTION_SCHEMA_VERSION",
    "DurableAgentClonedSectionRegistry",
    "LineageVerdict",
]
