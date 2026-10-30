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


# --- the brand's ad list opens ad-assets.md (spec 2026-10-30, reference ads §5.5) -------------

BRAND_ADS = [
    {"asset_id": "asset_ad_1", "from": "linkedin_ad", "headline": "Spend less",
     "commentary": "Copy.", "title": "Teal", "description": "A teal card.", "width": 1200,
     "height": 628, "created_at": "2026-10-02"},
    {"asset_id": "asset_ad_2", "from": "marked_by_person", "headline": None, "commentary": None,
     "title": None, "description": None, "width": None, "height": None, "created_at": None},
]


def test_the_ad_list_opens_ad_assets_md(tmp_path, monkeypatch):
    tools, prompt = _turn(
        tmp_path,
        monkeypatch,
        ad_dna_card=AD_DNA_CARD,
        brand_ads=BRAND_ADS,
        asset_library={row["asset_id"]: _entry(row["asset_id"]) for row in BRAND_ADS},
    )
    text = (tools.trace_dir / "workspace" / "ad-assets.md").read_text()
    assert text.index("# The brand's ads") < text.index(PROSE)
    assert "— 2 in all." in text and "`asset_ad_1`" in text and "LinkedIn ad" in text
    assert "ad-assets.md" in prompt


def test_person_marked_ads_alone_still_write_the_file(tmp_path, monkeypatch):
    tools, prompt = _turn(
        tmp_path,
        monkeypatch,
        brand_ads=BRAND_ADS[1:],
        asset_library={"asset_ad_2": _entry("asset_ad_2")},
    )
    text = (tools.trace_dir / "workspace" / "ad-assets.md").read_text()
    assert "`asset_ad_2`" in text and "— 1 in all." in text
    assert "ad-assets.md" in prompt


def test_an_ad_this_turn_cannot_open_is_not_listed(tmp_path, monkeypatch):
    tools, prompt = _turn(
        tmp_path, monkeypatch, brand_ads=BRAND_ADS, asset_library={"asset_ad_2": _entry("asset_ad_2")}
    )
    text = (tools.trace_dir / "workspace" / "ad-assets.md").read_text()
    assert "asset_ad_1" not in text and "— 1 in all." in text
