"""Logo search for the editor's asset library (founder request 2026-10-16).

A person types any company's website into the asset library's "Logo search" tab and sees every
logo version the shared lookup found — Brandfetch plus the official-site logo ladder, arbitrated
and cached per workspace (`lumen_agent.tools.logo_fetch.fetch_logo_family`, the same lookup the
design agent's `fetch_logo` tool runs). Nothing is chosen for them and nothing is saved by the
search: every version is returned as an inline preview, and only the one they click is ingested
and registered (`find_logo`, then the route's ingest + register).

The search and the save are two calls on purpose. The save re-runs the lookup, which the durable
family cache answers for any family the search could stand behind, so it is free and returns the
same content-addressed ids the search showed.
"""

from __future__ import annotations

import base64
from typing import Any, Dict, List, Optional

JsonObject = Dict[str, Any]

__all__ = ["CELL_ORDER", "find_logo", "logo_payload", "search_payload"]

#: The four recommended cells, in the order the tiles show them, and what each one is called.
CELL_ORDER = ("light_lockup", "dark_lockup", "light_mark", "dark_mark")
_CELL_LABELS = {
    "light_lockup": ("Full logo", "light"),
    "dark_lockup": ("Full logo", "dark"),
    "light_mark": ("Icon", "light"),
    "dark_mark": ("Icon", "dark"),
}


def logo_payload(prepared: Any) -> JsonObject:
    """One tile: what the version is, which background it is for, who served it, and its bytes.

    An alternative carries the cell it competed for, so it is described like that cell; one that
    competed for none (the vendor's `icon` / `other` types) is named by the vendor's type and
    claims no background, because a vendor theme label is a hint, never proof.
    """
    kind, background = _CELL_LABELS.get(prepared.cell, (None, None))
    if kind is None:
        kind = "Icon" if (prepared.evidence or {}).get("vendor_type") == "icon" else "Logo"
    encoded = base64.b64encode(prepared.body).decode("ascii")
    return {
        "asset_id": prepared.asset_id,
        "kind": kind,
        "background": background,
        "source": "Brandfetch" if prepared.source == "brandfetch" else "Website",
        "content_type": prepared.content_type,
        "preview": f"data:{prepared.content_type};base64,{encoded}",
    }


def _ordered_cells(prepared: List[Any]) -> List[Any]:
    rank = {name: index for index, name in enumerate(CELL_ORDER)}
    return sorted(prepared, key=lambda item: rank.get(item.cell, len(rank)))


def search_payload(outcome: Optional[Any], *, query: str) -> JsonObject:
    """The search response. `outcome` is None when no source could be reached or attributed."""
    from lumen_ingestion import logo_ladder

    if outcome is None:
        return {"query": query, "name": None, "logos": []}
    host = logo_ladder.host_of(outcome.site)
    logos = [logo_payload(item) for item in _ordered_cells(outcome.prepared)]
    logos += [logo_payload(item) for item in outcome.alternatives]
    return {
        "query": query,
        "name": logo_ladder.registrable_domain(host) or host,
        "logos": logos,
    }


def find_logo(outcome: Optional[Any], asset_id: str) -> Optional[Any]:
    """The prepared version with this content-addressed id, cell or alternative."""
    if outcome is None:
        return None
    for item in [*outcome.prepared, *outcome.alternatives]:
        if item.asset_id == asset_id:
            return item
    return None
