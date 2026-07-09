"""Run-workspace scaffolding and turn-state initialization (D8/M3)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .tools.substrate import LumenDesignTools



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
    }


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

    (workspace / "state.json").write_text(
        json.dumps(initial_turn_state(tools, prompt), indent=2), encoding="utf-8"
    )

    (rounds / "index.md").write_text(
        f"# Rounds — run {tools.run_id}\n\n"
        "One line per round: round number, verdict, and the one mistake the next "
        "round must not repeat.\n",
        encoding="utf-8",
    )
    return workspace
