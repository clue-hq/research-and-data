"""The workspace's cloned sections, as one website turn's capability (clone-fidelity F2.3).

Ingestion clones every section of a walked site into a fragment artifact (F2.2) and a human
releases them by approving the brand kit they came from. This module is how the WEB LANE's agent
reaches them: one injected object, exactly like
:class:`~lumen_api.agent_custom_components.DurableAgentCustomComponentRegistry`, because the agent
runtime is fleet work that holds no database handle and must never be given one.

Three questions, three methods, in the order a turn asks them:

* :meth:`DurableAgentClonedSectionRegistry.list_sections` — "what can I reuse?" Rows only, no
  blob read, **approved only**. A ``draft`` section is minted but unreleased and a ``deprecated``
  one is retired; offering either would be offering something the document write will refuse.
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
from .fragments import FragmentRefused, read_web_fragment
from .fragments.render import slot_kinds

JsonObject = Dict[str, Any]

#: How many approved sections one turn may be shown. A bound, not a judgement about workspaces:
#: the list is scored in Python by the discovery tool (which returns a handful), so this only has
#: to keep an enormous library out of one turn's memory. Ingestion mints at most
#: ``LUMEN_FRAGMENT_MINT_CAP`` (40) sections per walk, so this is several sites' worth.
CLONED_SECTION_LIST_MAX = 200

#: The by-value shape's version, mirroring the render package's own. Bump only for a change a
#: previous reader would MISREAD.
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
        """
        rows = self._repository().list_web_fragments(
            section_role=section_role, status="approved"
        )
        sections = [self._section_row(row) for row in rows[:CLONED_SECTION_LIST_MAX]]
        return {
            "schema_version": CLONED_SECTION_SCHEMA_VERSION,
            "workspace_id": self.workspace_id,
            "sections": sections,
        }

    @staticmethod
    def _section_row(row: JsonObject) -> JsonObject:
        provenance = row.get("provenance")
        provenance = provenance if isinstance(provenance, dict) else {}
        slot_keys = provenance.get("slots")
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
            "created_at": row.get("created_at"),
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


__all__ = [
    "CLONED_SECTION_LIST_MAX",
    "CLONED_SECTION_SCHEMA_VERSION",
    "DurableAgentClonedSectionRegistry",
]
