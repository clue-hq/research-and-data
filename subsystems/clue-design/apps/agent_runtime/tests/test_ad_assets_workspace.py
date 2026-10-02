"""The Director can discover the same reachable ad bank as the author."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from lumen_agent.harness import create_design_deepagent
from lumen_agent.prompts import build_orchestrator_prompt
from test_ad_dna_frame_context import AD_DNA_CARD, PROSE
from test_fast_loop import BRAND_KIT, _install_deepagents_stub, fast_config


def _turn(tmp_path, monkeypatch, **overrides):
    capture: dict = {}
    _install_deepagents_stub(monkeypatch, capture)
    _, tools = create_design_deepagent(
        "Compose a hospitality ad from suitable existing artwork",
        replace(fast_config(tmp_path, brand_kit=BRAND_KIT), **overrides),
    )
    return tools, capture["kwargs"]["system_prompt"]


def _entry(asset_id, status="ready"):
    return {"record": {"id": asset_id, "status": status, "kind": "raster_image"}}


@pytest.mark.parametrize("fast_loop", [False, True])
def test_director_is_pointed_to_current_run_file_with_all_twelve_grounds(
    tmp_path, monkeypatch, fast_loop
):
    assets = [
        {"asset_id": f"asset_gen_{i:02d}", "style_group": "Soft field", "shape": "square"}
        for i in range(12)
    ]
    tools, prompt = _turn(
        tmp_path,
        monkeypatch,
        fast_loop=fast_loop,
        ad_dna_card=AD_DNA_CARD,
        ad_pregenerated_assets=assets,
        asset_library={row["asset_id"]: _entry(row["asset_id"]) for row in assets},
    )
    path = tools.trace_dir / "workspace" / "ad-assets.md"
    assert path.is_file(), "Director has no discoverable current-turn ad bank"
    text = path.read_text()
    assert PROSE in text
    for row in assets:
        assert text.count(f'`{row["asset_id"]}`') == 1
    assert f"/{tools.run_id}/workspace/ad-assets.md" in prompt
    assert str(tools.trace_dir) not in prompt
    assert prompt.index("ad-assets.md") < prompt.index("2. Look before deciding:")
    assert json.loads((path.parent / "brand_card.json").read_text()) == tools.brand_card
    assert tools.operations_ledger == []


def test_shared_bank_omits_missing_unready_and_mismatched_library_records(tmp_path, monkeypatch):
    ids = ["asset_gen_ready", "asset_gen_missing", "asset_gen_pending", "asset_gen_wrong"]
    tools, _ = _turn(
        tmp_path,
        monkeypatch,
        ad_pregenerated_assets=[{"asset_id": aid} for aid in ids],
        asset_library={
            "asset_gen_ready": _entry("asset_gen_ready"),
            "asset_gen_pending": _entry("asset_gen_pending", "pending"),
            "asset_gen_wrong": _entry("asset_gen_another"),
        },
    )
    path = tools.trace_dir / "workspace" / "ad-assets.md"
    assert path.is_file()
    text = path.read_text()
    assert "asset_gen_ready" in text
    for aid in ids[1:]:
        assert aid not in text


@pytest.mark.parametrize("library", [None, {}])
def test_unreachable_bank_does_not_advertise_a_missing_file(tmp_path, monkeypatch, library):
    tools, prompt = _turn(
        tmp_path,
        monkeypatch,
        ad_pregenerated_assets=[{"asset_id": "asset_gen_missing"}],
        asset_library=library,
    )
    assert not (tools.trace_dir / "workspace" / "ad-assets.md").exists()
    assert "ad-assets.md" not in prompt


def test_dna_only_lane_is_available_as_advisory_context(tmp_path, monkeypatch):
    tools, prompt = _turn(tmp_path, monkeypatch, ad_dna_card=AD_DNA_CARD)
    path = tools.trace_dir / "workspace" / "ad-assets.md"
    assert path.is_file()
    assert PROSE in path.read_text()
    assert "It is context, not a rule." in path.read_text()
    assert "ad-assets.md" in prompt


def test_absent_lane_keeps_director_prompt_and_workspace_unchanged(tmp_path, monkeypatch):
    tools, prompt = _turn(tmp_path, monkeypatch, fast_loop=False)
    assert not (tools.trace_dir / "workspace" / "ad-assets.md").exists()
    assert prompt == build_orchestrator_prompt(f"/{tools.run_id}/workspace")
