"""Run-workspace scaffolding and turn-state initialization (D8/M3)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from py_lumen_obs import get_logger

from .frame import render_ad_dna_card_text, render_pregenerated_assets_text
from .tools.substrate import LumenDesignTools
from .tools.view import _reference_entries

logger = get_logger("lumen_agent.workspace")



def workspace_root(tools: LumenDesignTools) -> Path:
    return tools.trace_dir / "workspace"


def _brand_kit_ref(tools: LumenDesignTools) -> dict:
    """{id, version, name} from the effective brand context, or {} for the
    platform default (no attached kit)."""
    brand = tools.effective_brand_context or {}
    kit_id = brand.get("brand_kit_id") or brand.get("id")
    if not kit_id and tools.brand_card:
        kit = tools.brand_card.get("kit") or {}
        kit_id = kit.get("id")
        return {
            "id": kit_id or "",
            "version": kit.get("version") or "",
            "name": kit.get("name") or "",
        }
    if not kit_id:
        return {}
    return {
        "id": kit_id,
        "version": brand.get("brand_kit_version") or brand.get("version") or "",
        "name": brand.get("name") or brand.get("brand_kit_name") or "",
    }


def _first_page_id(tools: LumenDesignTools) -> Optional[str]:
    pages = (tools.scene or {}).get("pages") or {}
    for page_id in pages:
        return page_id
    return None


def initial_turn_state(tools: LumenDesignTools, prompt: str) -> dict:
    """The initial constitution values (§3), sourced from config/tools."""
    return {
        "seeded": tools.seeded_from_initial_scene,
        "chip_target_node_ids": list(tools.config.turn_target_node_ids or []),
        "brand_kit_ref": _brand_kit_ref(tools),
        "artboard_id": _first_page_id(tools),
        "turn_request": prompt,
        "current_round": 0,
        # RC: attachment-ordered reference ids (empty list when none rode this turn).
        "reference_asset_ids": [aid for (_i, aid, _e) in _reference_entries(tools)],
    }


def _reference_record_label(record: dict) -> str:
    """A human-facing filename/label for a reference, dug out of the engine asset
    record defensively (the record shape is API-owned; RC only CONSUMES it). Falls
    back to an em dash so the table never renders a bare `None`."""
    if not isinstance(record, dict):
        return "—"
    provenance = record.get("provenance") or {}
    for value in (
        record.get("label"),
        record.get("name"),
        record.get("filename"),
        provenance.get("source_label"),
        provenance.get("filename"),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "—"


def _render_references_md(tools: LumenDesignTools) -> str:
    """The mechanical reference metadata table (D4). One row per reference IN
    ORDER; advisory describe text clearly marked. This file is METADATA ONLY — the
    pixels are seen via view("reference:<n>"), and the DIRECTOR (not this scaffold)
    writes reference-brief.md by perceiving them."""
    entries = _reference_entries(tools)
    lines: list[str] = [
        f"# References — run {tools.run_id}",
        "",
        f"The user attached {len(entries)} reference image(s) to THIS turn. The rows "
        "below are metadata only — an index, never the pixels.",
        "",
        "- To SEE a reference, call `view(\"reference:<n>\")` (1-based, matching the "
        "index column) — judge by looking, never from this metadata.",
        "- `reference-brief.md` does not exist yet: the Design Director MUST write it "
        "(by viewing every reference) BEFORE round 1. This table does not describe "
        "the references — it only lists them.",
        "- Any `advisory title/description` below is optional describe-chain text; it "
        "is NOT load-bearing and is frequently absent — never trust it over the pixels.",
        "",
        "| # | asset_id | label / filename | mime | dims | dominant colors | advisory title | advisory description |",
        "|---|----------|------------------|------|------|-----------------|----------------|----------------------|",
    ]
    for index, asset_id, entry in entries:
        record = entry.get("record") or {}
        width, height = entry.get("width"), entry.get("height")
        dims = f"{width}×{height}" if width and height else "—"
        colors = ", ".join(entry.get("dominant_colors") or []) or "—"
        title = (entry.get("title") or "—").replace("|", "\\|").replace("\n", " ")
        description = (entry.get("description") or "—").replace("|", "\\|").replace("\n", " ")
        label = _reference_record_label(record).replace("|", "\\|")
        mime = entry.get("mime_type") or "—"
        lines.append(
            f"| {index} | {asset_id} | {label} | {mime} | {dims} | {colors} | {title} | {description} |"
        )
    lines.append("")
    return "\n".join(lines)


def scaffold_workspace(tools: LumenDesignTools, prompt: str) -> Path:
    """Create the run workspace and seed its canonical files (§2)."""
    workspace = workspace_root(tools)
    rounds = workspace / "rounds"
    previews = workspace / "previews"
    workspace.mkdir(parents=True, exist_ok=True)
    rounds.mkdir(parents=True, exist_ok=True)
    previews.mkdir(parents=True, exist_ok=True)

    header = f"# Design turn brief — run {tools.run_id}\n\n"
    (workspace / "brief.md").write_text(header + prompt, encoding="utf-8")

    (workspace / "brand_card.json").write_text(
        json.dumps(tools.brand_card, indent=2), encoding="utf-8"
    )

    # The author receives these in its frame; the Director needs the same current-turn
    # discovery surface before choosing imagery. Reuse the renderers and the placement
    # lookup so a missing/unready library record is never advertised as usable artwork.
    ad_sections: list[str] = []
    if tools.config.ad_dna_card:
        ad_sections.append(render_ad_dna_card_text(tools.config.ad_dna_card))
    library = {
        asset_id: entry
        for asset_id in (tools.config.asset_library or {})
        if (entry := tools._library_asset_entry(asset_id)) is not None
    }
    grounds = render_pregenerated_assets_text(
        tools.config.ad_pregenerated_assets or [], library
    )
    if grounds:
        ad_sections.append("## Backgrounds already made for this brand\n\n" + grounds)
    if ad_sections:
        (workspace / "ad-assets.md").write_text(
            "# Current-turn ad assets (advisory)\n\n" + "\n\n".join(ad_sections) + "\n",
            encoding="utf-8",
        )

    (workspace / "state.json").write_text(
        json.dumps(initial_turn_state(tools, prompt), indent=2), encoding="utf-8"
    )

    # RC: references.md ONLY when references rode the turn. No references → this
    # file never appears and reference-brief.md is never mentioned anywhere — the
    # scaffold is byte-identical to a pre-RC turn (pinned by test).
    if tools.config.reference_assets:
        (workspace / "references.md").write_text(
            _render_references_md(tools), encoding="utf-8"
        )

    (rounds / "index.md").write_text(
        f"# Rounds — run {tools.run_id}\n\n"
        "One line per round: round number, verdict, and the one mistake the next "
        "round must not repeat.\n",
        encoding="utf-8",
    )
    logger.debug(
        "workspace_scaffolded",
        run_id=tools.run_id,
        workspace=str(workspace),
        seeded=tools.seeded_from_initial_scene,
    )
    return workspace
