"""Run-workspace scaffolding and turn-state initialization (D8/M3)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from py_lumen_obs import get_logger

from .engine_mirror import record_pixel_dims
from .frame import render_ad_dna_card_text, render_pregenerated_assets_text
from .image_crop import recorded_generated_image_origin
from .paths import to_virtual
from .platform_reads import write_seller_knowledge
from .tools.asset_preview import PREVIEWABLE_MIME_TYPES, blob_path_for_digest
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
    review_profile = tools._native_copy_review_profile()
    return {
        "seeded": tools.seeded_from_initial_scene,
        "chip_target_node_ids": list(tools.config.turn_target_node_ids or []),
        "brand_kit_ref": _brand_kit_ref(tools),
        "artboard_id": _first_page_id(tools),
        "turn_request": prompt,
        "current_round": 0,
        # RC: attachment-ordered reference ids (empty list when none rode this turn).
        "reference_asset_ids": [aid for (_i, aid, _e) in _reference_entries(tools)],
        **({"native_copy_review_profile": review_profile} if review_profile is not None else {}),
        **(
            {"source_assets_path": to_virtual(
                workspace_root(tools) / "source_assets.json", tools.config,
            )}
            if tools.config.scene_skill_bundle == "candidate" else {}
        ),
    }


def _source_provenance(record: dict) -> dict:
    """Copy evidence pointers, never media custody locations or generation prompts."""
    source = record.get("source") or {}
    provenance = record.get("provenance") or {}
    pointers = {
        key: provenance.get(key)
        for key in (
            "source_label", "source", "provider", "creative_id", "ad_id",
            "advertiser_name", "advertiser_page_id", "view_details_link", "source_url",
        )
    }
    pointers["source_asset_id"] = source.get("source_asset_id") or source.get("asset_id")
    pointers["source_url"] = source.get("source_url") or source.get("url") or pointers["source_url"]
    result = {}
    for key, value in pointers.items():
        if not isinstance(value, str) or not value.strip():
            continue
        if key in {"source_url", "view_details_link"}:
            try:
                url = urlsplit(value)
                if (
                    url.scheme not in {"http", "https"}
                    or not url.hostname or url.username or url.password
                ):
                    continue
            except ValueError:
                continue
        result[key] = value
    return result


def _source_assets_catalog(tools: LumenDesignTools) -> dict:
    """Metadata for this run's already available sources, not a corpus search."""
    references = {aid: (index, entry) for index, aid, entry in _reference_entries(tools)}
    kit = tools.config.brand_kit_assets or {}
    library = tools.config.asset_library or {}
    assets = []
    unavailable = {"not_ready_or_mismatched": 0, "preview_unavailable": 0}

    def ready(entry, asset_id):
        record = entry.get("record") if isinstance(entry, dict) else None
        return (
            isinstance(record, dict)
            and record.get("id") == asset_id and record.get("status") == "ready"
        )

    for asset_id in sorted(set(references) | set(kit) | set(library)):
        reference_index, reference = references.get(asset_id, (None, None))
        library_entry = tools._library_asset_entry(asset_id)
        # Match view's kit-before-library resolution, including a kit entry that
        # shadows a library record. Never advertise the library's different pixels.
        entry = kit.get(asset_id)
        if not isinstance(entry, dict):
            entry = library_entry
        asset_ready = ready(entry, asset_id)
        preview = tools._asset_preview_path(entry["record"]) if asset_ready else None
        asset_available = preview is not None and Path(preview[0]).is_file()
        reference_ready = ready(reference, asset_id)
        reference_available = False
        if reference_ready:
            digest = reference.get("preview_digest")
            mime = (
                reference.get("mime_type")
                or (reference["record"].get("media") or {}).get("mime_type")
            )
            reference_available = bool(
                digest and mime in PREVIEWABLE_MIME_TYPES
                and blob_path_for_digest(tools.config.effective_asset_store_root, digest).is_file()
            )
        if not asset_available and not reference_available:
            reason = (
                "preview_unavailable" if asset_ready or reference_ready
                else "not_ready_or_mismatched"
            )
            unavailable[reason] += 1
            continue
        selected = entry if asset_available else reference
        record = selected["record"]
        dimensions = record_pixel_dims(record)
        source_kind = (record.get("source") or {}).get("kind")
        description = selected.get("description")
        description = description if isinstance(description, str) and description.strip() else None
        assets.append({
            "asset_id": asset_id,
            "available_via": (
                (["reference"] if reference_available else [])
                + (
                    ["brand_kit"]
                    if asset_available and ready(kit.get(asset_id), asset_id) else []
                )
                + (["library"] if asset_available and library_entry is not None else [])
            ),
            "reference_index": reference_index if reference_available else None,
            "view_target": (
                f"asset:{asset_id}" if asset_available else f"reference:{reference_index}"
            ),
            "label": record.get("label"),
            "title": selected.get("title"),
            "description": description,
            "description_status": "supplied" if description is not None else "missing",
            "role": selected.get("role"),
            "source_kind": (
                source_kind if isinstance(source_kind, str) and source_kind else "unknown"
            ),
            "generated_origin": recorded_generated_image_origin(record),
            "mime_type": (record.get("media") or {}).get("mime_type") or selected.get("mime_type"),
            "dimensions": {"width": dimensions[0], "height": dimensions[1]} if dimensions else None,
            "provenance": _source_provenance(record),
        })
    return {
        "schema_version": 1,
        "metadata_only": True,
        "scope": (
            "Current-turn by-value references, kit and eligible library; "
            "not the full harvested corpus."
        ),
        "observation": (
            "Use each view_target to inspect pixels. Descriptions are advisory; "
            "source_kind is the recorded value, not advertiser verification. "
            "generated_origin is recorded ancestry (null means unknown); "
            "false or null does not authenticate advertiser evidence. "
            "Generated sources are not promoted to references. "
            "Availability checks existing previews; image decoding is deferred to view."
        ),
        "assets": assets,
        "unavailable_count": sum(unavailable.values()),
        "unavailable_counts": unavailable,
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
    origin_sentence = (
        f"This turn has {len(entries)} reference image(s) available to the design agent."
        if tools.config.scene_skill_bundle == "candidate"
        else f"The user attached {len(entries)} reference image(s) to THIS turn."
    )
    direction_instruction = (
        "- Record the observed reference properties and source roles in the shared "
        "`creative-direction.json` before authoring. This table only lists the inputs."
        if tools.config.scene_skill_bundle == "candidate"
        else "- `reference-brief.md` does not exist yet: the Design Director MUST write it "
        "(by viewing every reference) BEFORE round 1. This table does not describe "
        "the references — it only lists them."
    )
    lines: list[str] = [
        f"# References — run {tools.run_id}",
        "",
        f"{origin_sentence} The rows "
        "below are metadata only — an index, never the pixels.",
        "",
        "- To SEE a reference, call `view(\"reference:<n>\")` (1-based, matching the "
        "index column) — judge by looking, never from this metadata.",
        direction_instruction,
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

    state = initial_turn_state(tools, prompt)
    # Harness alignment I11 (founder ruling 2026-10-17): the solo scene agent reads the person's
    # message in the conversation itself, so it gets no brief.md copy of it (and a copy an earlier
    # turn left in a persistent session folder is removed, so it can never be read as current).
    # The trio prompts still read brief.md, so other configurations keep it.
    solo = bool(getattr(tools.config, "scene_solo", False))
    if solo:
        (workspace / "brief.md").unlink(missing_ok=True)
    else:
        header = f"# Design turn brief — run {tools.run_id}\n\n"
        # Harness alignment I9: the minimum text size reaches the agent once, in the system
        # prompt; the brief no longer repeats it with evaluation-harness wording.
        (workspace / "brief.md").write_text(header + prompt, encoding="utf-8")

    (workspace / "brand_card.json").write_text(
        json.dumps(tools.brand_card, indent=2), encoding="utf-8"
    )
    # Design note 2026-09-19: the seller's own knowledge, pinned by the platform for this leg,
    # lands next to the brand card as ordinary files the agent reads (and cannot write — see
    # fs_backend's readonly_subdirs). Written once per pin: a second turn in the same session
    # finds the same tree and writes nothing.
    if tools.config.platform_reads is not None:
        write_seller_knowledge(workspace, tools.config.platform_reads, record=tools.record)
    if tools.config.scene_skill_bundle == "candidate" and tools.brand_card:
        # A separate on-demand data file keeps the injected card compact without
        # hiding supplied palette choices. Preserve aliases and mode variants;
        # the engine remains the authority for their resolved active values.
        kit = tools.config.brand_kit or {}
        color_catalog = {
            "kit": {"id": kit.get("id"), "version": kit.get("version")},
            "modes": kit.get("modes") or {},
            "colors": {
                name: {key: row[key] for key in ("role", "description", "value", "provenance") if key in row}
                for name, row in ((kit.get("tokens") or {}).get("colors") or {}).items()
                if isinstance(row, dict)
            },
        }
        # One complete token per line lets a normal file read expose the full
        # palette instead of paginating through each token's nested metadata.
        # Keep the JSON shape, insertion order and source values unchanged.
        color_rows = ",\n".join(
            f"    {json.dumps(name)}: {json.dumps(row)}"
            for name, row in color_catalog["colors"].items()
        )
        (workspace / "brand_colors.json").write_text(
            "\n".join([
                "{",
                f'  "kit": {json.dumps(color_catalog["kit"])},',
                f'  "modes": {json.dumps(color_catalog["modes"])},',
                '  "colors": {',
                color_rows,
                "  }",
                "}",
            ]), encoding="utf-8",
        )

    if tools.config.scene_skill_bundle == "candidate":
        (workspace / "source_assets.json").write_text(
            json.dumps(_source_assets_catalog(tools), indent=2), encoding="utf-8",
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

    # Harness alignment I11: the state FILE does not repeat the message for the solo agent; the
    # graph state keeps `turn_request` for the runtime.
    file_state = {k: v for k, v in state.items() if not (solo and k == "turn_request")}
    (workspace / "state.json").write_text(
        json.dumps(file_state, indent=2), encoding="utf-8"
    )

    # RC: references.md ONLY when references rode the turn. No references → this
    # file never appears and reference-brief.md is never mentioned anywhere — the
    # scaffold is byte-identical to a pre-RC turn (pinned by test).
    if tools.config.reference_assets:
        (workspace / "references.md").write_text(
            _render_references_md(tools), encoding="utf-8"
        )

    # The index belongs to the SESSION, not the turn: a second turn scaffolding into
    # a workspace that survived appends its own heading instead of erasing what the
    # earlier turns wrote (the rounds beneath it are never deleted either).
    index = rounds / "index.md"
    header = (
        "# Rounds — this design session\n\n"
        "One line per round: round number, verdict, and the one mistake the next "
        "round must not repeat.\n"
    )
    if not index.exists():
        index.write_text(header, encoding="utf-8")
    with index.open("a", encoding="utf-8") as handle:
        handle.write(f"\n## Turn {tools.run_id}\n")
    logger.debug(
        "workspace_scaffolded",
        run_id=tools.run_id,
        workspace=str(workspace),
        seeded=tools.seeded_from_initial_scene,
    )
    return workspace
