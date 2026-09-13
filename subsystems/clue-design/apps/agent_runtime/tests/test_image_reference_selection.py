"""Selected library pixels must reach generation, without changing turn context.

Exercises the public asset tool and provider boundary. No network or model spend.
"""

import hashlib
import json
from types import SimpleNamespace

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


def test_public_tool_carries_role_and_operation_semantics_to_provider_and_cache(
    tmp_path, monkeypatch
):
    tools, record, _ = _library_tools(tmp_path, monkeypatch)
    _give_page(tools)
    calls = _provider(monkeypatch)
    modes = []
    for role in ("treatment", "composition", "composition"):
        calls.clear()
        result = json.loads(tools.asset(
            action="generate_image", prompt="a companion",
            reference_asset_ids=[record["id"]], reference_roles=[role],
            reference_framing="Preserve the supplied treatment.", operation="close_companion",
        ))["image"]
        modes.append(result["mode"])
        if result["mode"] == "model":
            assert calls["reference_roles"] == [role]
            assert calls["operation"] == "close_companion"
    assert modes == ["model", "model", "cached"]


@pytest.mark.parametrize("action", ["generate_image", "edit_image"])
def test_public_tool_returns_the_persisted_receipt_on_fresh_and_cached_images(
    tmp_path, monkeypatch, action
):
    tools, record, _ = _library_tools(tmp_path, monkeypatch)
    _give_page(tools)
    tools.scene["assets"][record["id"]] = record
    tools.scene["nodes"]["hero"] = {
        "id": "hero", "kind": {"kind": "image", "asset_id": record["id"]},
        "asset_placement": {"fit": "contain", "focal_point": {"x": 0.2, "y": 0.7}},
    }
    receipt = {
        "provider_operation": "generate" if action == "generate_image" else "edit",
        "operation": "close_companion",
        "output_dimensions": {"width": 512, "height": 512},
    }
    calls = []

    def fake_model(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            image_bytes=_solid_png(512), mime_type="image/png", model="test/image-model",
            provenance={"created_by": "agent", "notes": ["image_request=" + json.dumps(receipt)]},
            license={"name": "generated_commercial_use", "allow_export": True},
        )

    monkeypatch.setattr("lumen_agent.tools.substrate.image_provider", SimpleNamespace(
        is_configured=lambda: True, configured_model_id=lambda: "test/image-model",
        generate=fake_model, edit=fake_model,
    ))
    arguments = (
        {"reference_asset_ids": [record["id"]]} if action == "generate_image"
        else {"node_id": "hero"}
    )
    key = "image" if action == "generate_image" else "image_edit"
    outputs = [json.loads(tools.asset(
        action=action, prompt="same companion", operation="close_companion", **arguments,
    ))[key] for _ in range(2)]
    assert [output["mode"] for output in outputs] == ["model", "cached"]
    assert len(calls) == 1
    assert all(output["image_request_receipt"] == receipt for output in outputs)
    if action == "edit_image":
        assert all(output["source_asset_id"] == record["id"] for output in outputs)
        assert all(output["placement"]["fit"] == "contain" for output in outputs)


@pytest.mark.parametrize("roles", [["invalid"], [], ["source", "treatment"]])
def test_bad_roles_refuse_without_provider_or_scene_write(tmp_path, monkeypatch, roles):
    tools, record, _ = _library_tools(tmp_path, monkeypatch)
    _give_page(tools)
    calls = _provider(monkeypatch)
    before = json.dumps(tools.scene, sort_keys=True)
    result = json.loads(tools.asset(
        action="generate_image", prompt="companion",
        reference_asset_ids=[record["id"]], reference_roles=roles,
    ))
    assert result["image"]["status"] == "error"
    assert calls == {}
    assert json.dumps(tools.scene, sort_keys=True) == before


@pytest.mark.parametrize("empty_selection", [False, True])
def test_source_edit_refuses_selected_references_before_provider_or_scene_write(
    tmp_path, monkeypatch, empty_selection
):
    tools, record, _ = _library_tools(tmp_path, monkeypatch)
    _give_page(tools)
    tools.scene["assets"][record["id"]] = record
    tools.scene["nodes"]["hero"] = {
        "id": "hero", "kind": {"kind": "image", "asset_id": record["id"]},
        "asset_placement": {"fit": "contain", "focal_point": {"x": 0.2, "y": 0.7}},
    }
    calls = []

    def fake_edit(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            image_bytes=_solid_png(512), mime_type="image/png", model="test/image-model",
            provenance={"created_by": "agent", "notes": []},
            license={"name": "generated_commercial_use", "allow_export": True},
        )

    monkeypatch.setattr("lumen_agent.tools.substrate.image_provider", SimpleNamespace(
        is_configured=lambda: True, configured_model_id=lambda: "test/image-model",
        edit=fake_edit,
    ))
    before = json.dumps(tools.scene, sort_keys=True)
    result = json.loads(tools.asset(
        action="edit_image", node_id="hero", prompt="Use the selected treatment",
        reference_asset_ids=[] if empty_selection else [record["id"]],
    ))

    assert result.get("status") == "error", result
    assert result.get("error_code") == "asset.bad_request", result
    assert calls == [], "An unsupported reference selection must not spend on a source-only edit"
    assert json.dumps(tools.scene, sort_keys=True) == before


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
