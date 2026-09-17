"""On-demand source discovery must lead to actual current-turn pixels, offline."""

import base64
import copy
import json
from dataclasses import replace

import pytest
from lumen_agent.fs_backend import AgentWorkspaceBackend
from lumen_agent.image_crop import crop_source_pixels, has_generated_image_origin
from lumen_agent.tools.view import make_view_tool
from lumen_agent.workspace import scaffold_workspace
from test_scene_view_generated_assets import _raster, _tools


def _entry(tmp_path, asset_id, *, source_kind="uploaded", **metadata):
    record, raw = _raster(tmp_path / "store", asset_id, (12, 34, 56))
    record["source"] = {"kind": source_kind}
    return {"record": record, **metadata}, raw


def _catalog(tools):
    workspace = scaffold_workspace(tools, "Tell the customer's story")
    state = json.loads((workspace / "state.json").read_text())
    assert "source_assets_path" in state, "No discoverable current-turn source catalog"
    backend = AgentWorkspaceBackend(tools.config.workspace_root)
    result = backend.download_files([state["source_assets_path"]])[0]
    assert result.error is None, result
    return json.loads(result.content), state, result.content


def test_older_public_source_outside_opening_four_is_discoverable_and_viewable(tmp_path):
    refs = {}
    for index in range(4):
        entry, _ = _entry(tmp_path, f"new_guide_{index}")
        entry.update(order=index, preview_digest=entry["record"]["media"]["digest"]["value"])
        refs[f"new_guide_{index}"] = entry
    older, raw = _entry(
        tmp_path, "older_customer_ad", title="Turn your lock screen into a styling canvas",
        description="A published customer story", role="customer example",
    )
    older["record"]["provenance"] = {
        "source_label": "Public advertiser example",
        "source_url": "https://www.linkedin.com/ad-library/detail/1541315494",
    }
    tools = _tools(
        tmp_path, scene_skill_bundle="candidate", reference_assets=refs,
        asset_library={"older_customer_ad": older},
    )
    before = copy.deepcopy(tools.scene)

    catalog, state, _ = _catalog(tools)

    row = next(row for row in catalog["assets"] if row["asset_id"] == "older_customer_ad")
    assert row["available_via"] == ["library"]
    assert row["reference_index"] is None
    assert row["view_target"] == "asset:older_customer_ad"
    assert row["title"] == "Turn your lock screen into a styling canvas"
    assert row["description"] == "A published customer story"
    assert row["role"] == "customer example"
    assert row["source_kind"] == "uploaded"
    assert row["generated_origin"] is None
    assert row["dimensions"] == {"width": 512, "height": 512}
    assert row["mime_type"] == "image/png"
    assert row["provenance"]["source_url"] == "https://www.linkedin.com/ad-library/detail/1541315494"
    assert state["reference_asset_ids"] == [f"new_guide_{i}" for i in range(4)]
    for row in catalog["assets"]:
        blocks = make_view_tool(tools).invoke({"target": row["view_target"]})
        images = [block for block in blocks if block["type"] == "image"]
        assert len(images) == 1, blocks
        assert base64.b64decode(images[0]["data"]) == raw
    assert tools.scene == before
    assert tools.operations_ledger == []


def test_unready_mismatched_missing_or_nonimage_sources_are_not_advertised(tmp_path):
    ready, _ = _entry(tmp_path, "ready")
    pending, _ = _entry(tmp_path, "pending")
    pending["record"]["status"] = "pending"
    mismatch, _ = _entry(tmp_path, "another_id")
    missing, _ = _entry(tmp_path, "missing")
    missing["record"]["media"]["digest"]["value"] = "f" * 64
    nonimage, _ = _entry(tmp_path, "font")
    nonimage["record"]["media"]["mime_type"] = "font/woff2"
    reference, _ = _entry(tmp_path, "missing_reference")
    reference.update(order=0, preview_digest="e" * 64)
    tools = _tools(
        tmp_path, scene_skill_bundle="candidate",
        brand_kit_assets={"pending": pending},
        asset_library={"ready": ready, "mismatch": mismatch, "missing": missing, "font": nonimage},
        reference_assets={"missing_reference": reference},
    )

    catalog, _, _ = _catalog(tools)

    assert [row["asset_id"] for row in catalog["assets"]] == ["ready"]
    assert catalog["unavailable_count"] == 5
    assert catalog["unavailable_counts"] == {
        "not_ready_or_mismatched": 2, "preview_unavailable": 3,
    }


def test_duplicate_ids_follow_view_precedence_and_reference_order_deterministically(tmp_path):
    kit, raw = _entry(tmp_path, "shared", title="Kit title")
    library = copy.deepcopy(kit)
    library["title"] = "Library title must not override the viewed kit"
    reference = copy.deepcopy(kit)
    reference.update(order=1, preview_digest=kit["record"]["media"]["digest"]["value"])
    first, _ = _entry(tmp_path, "z_first_reference")
    first.update(order=0, preview_digest=first["record"]["media"]["digest"]["value"])
    extra, _ = _entry(tmp_path, "a_library")
    tools = _tools(
        tmp_path, scene_skill_bundle="candidate", brand_kit_assets={"shared": kit},
        reference_assets={"shared": reference, "z_first_reference": first},
        asset_library={"shared": library, "a_library": extra},
    )
    catalog, state, original = _catalog(tools)
    rows = catalog["assets"]
    assert [row["asset_id"] for row in rows] == ["a_library", "shared", "z_first_reference"]
    shared = rows[1]
    assert shared["available_via"] == ["reference", "brand_kit", "library"]
    assert shared["title"] == "Kit title"
    assert shared["reference_index"] == 2
    assert shared["view_target"] == "asset:shared"
    assert rows[2]["view_target"] == "reference:1"
    assert state["reference_asset_ids"] == ["z_first_reference", "shared"]
    blocks = make_view_tool(tools).invoke({"target": shared["view_target"]})
    assert base64.b64decode(next(b["data"] for b in blocks if b["type"] == "image")) == raw
    tools.config = replace(
        tools.config,
        reference_assets=dict(reversed(list(tools.config.reference_assets.items()))),
        asset_library=dict(reversed(list(tools.config.asset_library.items()))),
    )
    assert _catalog(tools)[2] == original


def test_generated_unknown_and_missing_description_stay_honest_without_locator_leaks(tmp_path):
    generated, _ = _entry(tmp_path, "generated", source_kind="generated")
    generated["record"]["source"].update(
        prompt="Do not disclose this prompt", source_asset_id="source_original",
        source_url="file:///private/custody.png",
    )
    generated["record"]["media"]["location"] = {
        "url": "https://storage.example/private-custody", "opaque_ref": "/private/blob-locator",
    }
    generated["record"]["raw_base64"] = "PRIVATE_BASE64_PAYLOAD"
    unknown, _ = _entry(tmp_path, "unknown")
    unknown["record"].pop("label")
    unknown["record"].pop("source")
    seeded, _ = _entry(tmp_path, "seeded_prior_generated", source_kind="generated")
    tools = _tools(
        tmp_path, scene_skill_bundle="candidate",
        assets={"seeded_prior_generated": seeded["record"]},
        asset_library={"generated": generated, "unknown": unknown},
    )

    catalog, state, serialized = _catalog(tools)

    generated_row, unknown_row = catalog["assets"]
    assert generated_row["source_kind"] == "generated"
    assert generated_row["generated_origin"] is True
    assert generated_row["available_via"] == ["library"]
    assert generated_row["provenance"]["source_asset_id"] == "source_original"
    assert unknown_row["source_kind"] == "unknown"
    assert unknown_row["generated_origin"] is None
    assert unknown_row["title"] is None and unknown_row["label"] is None
    assert unknown_row["description"] is None and unknown_row["description_status"] == "missing"
    assert state["reference_asset_ids"] == []
    text = serialized.decode()
    for private in (
        "Do not disclose", "private-custody", "/private/", "PRIVATE_BASE64",
        "seeded_prior_generated",
    ):
        assert private not in text
    assert "record" not in generated_row


@pytest.mark.parametrize("generated", [False, True])
def test_manual_crop_discloses_recorded_origin_without_changing_pixel_availability(
    tmp_path, generated,
):
    entry, raw = _entry(tmp_path, "crop", source_kind="manual")
    record = entry["record"]
    cropped = crop_source_pixels(
        raw, source_asset_id="parent", mime_type="image/png", rect=[0, 0, 512, 512],
        source_generated=generated,
    )
    raw = cropped.png_bytes
    digest = cropped.receipt["output_digest"]
    output = tmp_path / "store" / "sha256" / digest[:2] / digest
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(raw)
    record["media"]["digest"]["value"] = digest
    record["provenance"] = {"notes": ["asset_derivation=" + json.dumps({
        **cropped.receipt,
        "private_prompt": "PRIVATE_GENERATION_PROMPT",
        "private_path": "/private/source-custody",
    })]}
    tools = _tools(tmp_path, scene_skill_bundle="candidate", asset_library={"crop": entry})
    before = copy.deepcopy(tools.scene)
    catalog, state, serialized = _catalog(tools)
    row = catalog["assets"][0]
    assert row["source_kind"] == "manual"
    assert row["generated_origin"] is generated
    assert has_generated_image_origin(record) is generated
    assert row["available_via"] == ["library"]
    assert row["view_target"] == "asset:crop"
    assert state["reference_asset_ids"] == []
    blocks = make_view_tool(tools).invoke({"target": row["view_target"]})
    assert base64.b64decode(next(b["data"] for b in blocks if b["type"] == "image")) == raw
    assert tools.scene == before and tools.operations_ledger == []
    for private in (b"PRIVATE_GENERATION_PROMPT", b"/private/", b"asset_derivation="):
        assert private not in serialized


@pytest.mark.parametrize(
    "invalid", ["stale_digest", "bad_digest", "wrong_type", "malformed", "absent"],
)
def test_invalid_or_absent_crop_receipts_leave_generated_origin_unknown(tmp_path, invalid):
    entry, _ = _entry(tmp_path, "crop", source_kind="manual")
    receipt = {
        "version": 1, "operation": "crop_image", "source_asset_id": "parent",
        "source_digest": "a" * 64,
        "output_digest": entry["record"]["media"]["digest"]["value"],
        "source_generated": False,
    }
    if invalid == "stale_digest":
        receipt["output_digest"] = "b" * 64
    elif invalid == "bad_digest":
        receipt["source_digest"] = "forged"
    elif invalid == "wrong_type":
        receipt["source_generated"] = "false"
    body = "PRIVATE_INVALID_JSON" if invalid == "malformed" else json.dumps(receipt)
    notes = [] if invalid == "absent" else ["asset_derivation=" + body]
    entry["record"]["provenance"] = {"notes": notes}
    catalog, _, serialized = _catalog(_tools(
        tmp_path, scene_skill_bundle="candidate", asset_library={"crop": entry},
    ))
    assert catalog["assets"][0]["generated_origin"] is None
    assert has_generated_image_origin(entry["record"]) is False
    assert catalog["assets"][0]["source_kind"] == "manual"
    assert catalog["assets"][0]["available_via"] == ["library"]
    assert b"PRIVATE_INVALID_JSON" not in serialized


def test_invalid_kit_entry_cannot_advertise_shadowed_library_pixels(tmp_path):
    valid, _ = _entry(tmp_path, "same_id")
    invalid = copy.deepcopy(valid)
    invalid["record"]["media"]["digest"]["value"] = "0" * 64
    tools = _tools(
        tmp_path, scene_skill_bundle="candidate", brand_kit_assets={"same_id": invalid},
        asset_library={"same_id": valid},
    )
    catalog, _, _ = _catalog(tools)
    assert catalog["assets"] == []
    assert catalog["unavailable_count"] == 1


def test_empty_candidate_catalog_is_readable_and_explicit(tmp_path):
    catalog, _, _ = _catalog(_tools(tmp_path, scene_skill_bundle="candidate"))
    assert catalog["assets"] == []
    assert catalog["unavailable_count"] == 0
    assert catalog["metadata_only"] is True


def test_legacy_workspace_keeps_source_catalog_and_pointer_absent(tmp_path):
    entry, _ = _entry(tmp_path, "available")
    tools = _tools(tmp_path, scene_skill_bundle="legacy", asset_library={"available": entry})
    workspace = scaffold_workspace(tools, "Inspect artwork")
    assert not (workspace / "source_assets.json").exists()
    assert "source_assets_path" not in json.loads((workspace / "state.json").read_text())
