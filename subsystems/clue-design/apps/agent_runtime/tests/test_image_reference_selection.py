"""Selected library pixels must reach generation, without changing turn context.

Exercises the public asset tool and provider boundary. No network or model spend.
"""

import hashlib
import json

import pytest
from agent_fixtures import FakeCoreClient
from test_deepagent_harness import (
    _give_page,
    _install_image_model,
    _reference_config,
    _solid_png,
    _tools_only,
)
from test_scene_asset_library import _library_tools


def _provider(monkeypatch):
    calls = {}
    provenance = {"created_by": "agent", "source_label": "image generation", "notes": []}
    _install_image_model(monkeypatch, calls, provenance)
    return calls


def test_public_tool_uses_selected_library_original_and_reports_custody(tmp_path, monkeypatch):
    tools, record, thumbnail = _library_tools(tmp_path, monkeypatch)
    _give_page(tools)
    calls = _provider(monkeypatch)
    before = tools.config.asset_library.copy()

    result = json.loads(
        tools.asset(
            action="generate_image",
            prompt="a new companion ground",
            reference_asset_ids=[record["id"]],
        )
    )["image"]

    assert result["mode"] == "model"
    pixels, mime = calls["reference_images"][0]
    assert pixels != thumbnail, "Generation needs the original, not the contact-sheet thumbnail"
    assert hashlib.sha256(pixels).hexdigest() == record["media"]["digest"]["value"]
    assert mime == "image/png"
    assert result["reference_inputs"] == [
        {
            "asset_id": record["id"],
            "digest": record["media"]["digest"]["value"],
            "mime_type": "image/png",
        }
    ]
    assert tools.config.asset_library == before
    assert tools.config.reference_assets is None


def test_explicit_selection_replaces_attachments_and_preserves_order(tmp_path, monkeypatch):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    first, second = _solid_png(544), _solid_png(576)
    tools = _tools_only(
        _reference_config(
            tmp_path,
            [
                {"asset_id": "ref_a", "png": first, "order": 0},
                {"asset_id": "ref_b", "png": second, "order": 1},
            ],
        )
    )
    _give_page(tools)
    calls = _provider(monkeypatch)

    result = json.loads(
        tools.asset(
            action="generate_image",
            prompt="selected treatment",
            reference_asset_ids=["ref_b", "ref_a", "ref_b"],
        )
    )["image"]
    assert calls["reference_images"] == [(second, "image/png"), (first, "image/png")]
    assert [r["asset_id"] for r in result["reference_inputs"]] == ["ref_b", "ref_a"]

    plain = json.loads(
        tools.asset(
            action="generate_image",
            prompt="independent new concept",
            reference_asset_ids=[],
        )
    )["image"]
    assert calls["reference_images"] is None
    assert plain["reference_inputs"] == []


@pytest.mark.parametrize(
    "failure", ["unknown", "missing", "corrupt", "digest", "not_ready", "too_many"]
)
def test_invalid_selection_refuses_before_spend_or_scene_mutation(tmp_path, monkeypatch, failure):
    from lumen_agent.tools.asset_preview import blob_path_for_digest

    tools, record, _ = _library_tools(tmp_path, monkeypatch)
    _give_page(tools)
    selected = [record["id"]]
    blob = blob_path_for_digest(
        tools.config.effective_asset_store_root, record["media"]["digest"]["value"]
    )
    if failure == "unknown":
        selected = ["asset_from_another_workspace"]
    elif failure == "missing":
        blob.unlink()
    elif failure == "corrupt":
        blob.write_bytes(b"not the frozen reference bytes")
    elif failure == "digest":
        record["media"]["digest"]["value"] = "../../outside-the-cache"
    elif failure == "not_ready":
        record["status"] = "archived"
    else:
        selected = [f"ref_{i}" for i in range(5)]
    before = json.dumps(tools.scene, sort_keys=True)
    calls = _provider(monkeypatch)

    result = json.loads(
        tools.asset(
            action="generate_image",
            prompt="must use selected source",
            reference_asset_ids=selected,
        )
    )["image"]

    assert result["status"] == "error"
    assert result["error_code"].startswith("image.reference_")
    assert calls == {}, "Do not silently pay for unconditioned pixels"
    assert json.dumps(tools.scene, sort_keys=True) == before


def test_selected_pixels_separate_cache_entries_and_cache_keeps_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    tools = _tools_only(
        _reference_config(
            tmp_path,
            [
                {"asset_id": "ref_a", "png": _solid_png(544), "order": 0},
                {"asset_id": "ref_b", "png": _solid_png(576), "order": 1},
            ],
        )
    )
    _give_page(tools)
    calls = _provider(monkeypatch)
    results = []
    for selection in (["ref_a"], ["ref_b"], ["ref_a"]):
        calls.clear()
        results.append(
            json.loads(
                tools.asset(
                    action="generate_image",
                    prompt="same prompt",
                    reference_asset_ids=selection,
                )
            )["image"]
        )
    assert [r["mode"] for r in results] == ["model", "model", "cached"]
    assert results[0]["reference_inputs"] != results[1]["reference_inputs"]
    assert results[0]["reference_inputs"] == results[2]["reference_inputs"]
    assert calls == {}


def test_unconfigured_model_does_not_claim_selected_reference_conditioning(tmp_path, monkeypatch):
    from types import SimpleNamespace

    tools, record, _ = _library_tools(tmp_path, monkeypatch)
    _give_page(tools)
    monkeypatch.setattr(
        "lumen_agent.tools.substrate.image_provider",
        SimpleNamespace(is_configured=lambda: False),
    )
    image = json.loads(
        tools.asset(
            action="generate_image",
            prompt="requires the selected pixels",
            reference_asset_ids=[record["id"]],
        )
    )["image"]
    assert image["mode"] == "placeholder"
    assert image["fallback"]["conditioning_lost"] is True
    assert "reference_inputs" not in image
