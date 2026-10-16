"""Website optimizer renditions are alternatives, not separate creative ideas."""

from __future__ import annotations

from copy import deepcopy
from urllib.parse import urlencode

from test_web_search_assets import _record, _search, _tools


def _variant(
    asset_id,
    width,
    height,
    *,
    source="/customer/hotel.jpg?crop=portrait",
    deployment="release-a",
    status="ready",
):
    record = _record(asset_id, width=width, height=height, status=status, label="image")
    record["source"] = {
        "kind": "website",
        "captured_at": "2026-09-20T12:00:00Z",
        "url": "https://brand.example/_next/image?"
        + urlencode(
            {
                "url": source,
                "w": width,
                "q": 75,
                "dpl": deployment,
            }
        ),
    }
    return {"record": record}


def test_general_search_groups_renditions_and_preserves_exact_records(tmp_path):
    library = {"tiny": _variant("tiny", 48, 72), "sharp": _variant("sharp", 480, 720)}
    before = deepcopy(library)
    result = _search(_tools(tmp_path, asset_library=library), "image")
    assert [r["asset_id"] for r in result["results"]] == ["sharp"]
    family = result["results"][0]["rendition_family"]
    assert family["variant_count"] == 2
    assert family["preferred_asset_id"] == "sharp"
    assert library == before


def test_exact_thumbnail_id_returns_it_and_names_a_better_available_variant(tmp_path):
    library = {"tiny": _variant("tiny", 48, 72), "sharp": _variant("sharp", 480, 720)}
    result = _search(_tools(tmp_path, asset_library=library), "tiny")
    assert result["results"][0]["asset_id"] == "tiny"
    assert result["results"][0]["id_match"] is True
    assert result["results"][0]["rendition_family"]["preferred_asset_id"] == "sharp"
    assert result["results"][0]["resolution"]["width_px"] == 48


def test_caption_match_on_thumbnail_can_find_sharper_sibling(tmp_path):
    library = {"tiny": _variant("tiny", 48, 72), "sharp": _variant("sharp", 480, 720)}
    library["tiny"]["description"] = "Hotel terrace in afternoon sunlight"
    result = _search(_tools(tmp_path, asset_library=library), "terrace")
    assert [r["asset_id"] for r in result["results"]] == ["sharp"]
    assert result["results"][0]["rendition_family"]["matched_asset_id"] == "tiny"


def test_crop_deployment_and_capture_are_distinct_families(tmp_path):
    library = {
        "portrait": _variant("portrait", 480, 720),
        "landscape": _variant("landscape", 720, 480, source="/customer/hotel.jpg?crop=landscape"),
        "new_release": _variant("new_release", 480, 720, deployment="release-b"),
        "new_capture": _variant("new_capture", 480, 720),
    }
    library["new_capture"]["record"]["source"]["captured_at"] = "2026-09-21T12:00:00Z"
    result = _search(_tools(tmp_path, asset_library=library), "image")
    assert len(result["results"]) == 4


def test_nonready_larger_variant_never_displaces_ready_one(tmp_path):
    library = {
        "tiny": _variant("tiny", 48, 72),
        "sharp": _variant("sharp", 480, 720, status="processing"),
    }
    result = _search(_tools(tmp_path, asset_library=library), "image")
    assert result["results"][0]["asset_id"] == "tiny"
    assert result["results"][0]["rendition_family"]["preferred_asset_id"] == "tiny"


def test_required_pixels_are_checked_against_decoded_size_not_url_width(tmp_path):
    asset = _variant("avatar", 128, 128)
    asset["record"]["source"]["url"] = asset["record"]["source"]["url"].replace("w=128", "w=2048")
    result = _search(
        _tools(tmp_path, asset_library={"avatar": asset}),
        "image",
        min_width_px=600,
        min_height_px=400,
    )
    row = result["results"][0]
    assert row["resolution"]["meets_requested_pixels"] is False
    assert row["resolution"]["width_px"] == 128
    assert "larger source" in row["resolution"]["guidance"]


def test_two_explicit_ids_in_same_family_both_survive_in_query_order(tmp_path):
    library = {"tiny": _variant("tiny", 48, 72), "sharp": _variant("sharp", 480, 720)}
    rows = _search(_tools(tmp_path, asset_library=library), "tiny sharp")["results"]
    assert [r["asset_id"] for r in rows] == ["tiny", "sharp"]
    assert all(r["id_match"] for r in rows)


def test_unproven_or_different_urls_never_group(tmp_path):
    for suffix in ("&crop=other", "&q=90", "&w=48", "#fragment"):
        library = {"tiny": _variant("tiny", 48, 72), "sharp": _variant("sharp", 480, 720)}
        library["tiny"]["record"]["source"]["url"] += suffix
        assert _search(_tools(tmp_path, asset_library=library), "image")["count"] == 2
    library = {"tiny": _variant("tiny", 48, 72), "sharp": _variant("sharp", 480, 720)}
    for asset in library.values():
        asset["record"]["source"]["url"] = asset["record"]["source"]["url"].replace(
            "/_next/image", "/custom/image"
        )
    assert _search(_tools(tmp_path, asset_library=library), "image")["count"] == 2


def test_missing_capture_or_changed_aspect_never_substitutes(tmp_path):
    library = {"tiny": _variant("tiny", 48, 72), "sharp": _variant("sharp", 480, 480)}
    assert _search(_tools(tmp_path, asset_library=library), "image")["count"] == 2
    library["sharp"] = _variant("sharp", 480, 720)
    for asset in library.values():
        del asset["record"]["source"]["captured_at"]
    assert _search(_tools(tmp_path, asset_library=library), "image")["count"] == 2


def test_alternative_summaries_are_bounded_and_only_selected_source_is_registered(tmp_path):
    library = {f"photo_{i}": _variant(f"photo_{i}", i * 48, i * 72) for i in range(1, 14)}
    tools = _tools(tmp_path, asset_library=library)
    rows = _search(tools, "image")["results"]
    assert len(rows) == 1
    assert rows[0]["asset_id"] == "photo_13"
    family = rows[0]["rendition_family"]
    assert family["variant_count"] == 13
    assert len(family["variants"]) == 8
    assert family["variants_truncated"] is True
    assert len(tools.grounding_report()["sources"]) == 1


def test_small_unknown_and_vector_resolution_are_honest(tmp_path):
    records = {i: {"record": _record(i)} for i in ("unknown", "vector", "small")}
    records["unknown"]["record"].pop("raster")
    records["vector"]["record"]["kind"] = "vector"
    records["small"] = _variant("small", 64, 64)
    tools = _tools(tmp_path, asset_library=records)
    unknown = _search(tools, "unknown", min_width_px=600)["results"][0]["resolution"]
    vector = _search(tools, "vector", min_width_px=600)["results"][0]["resolution"]
    small = _search(tools, "small")["results"][0]["resolution"]
    assert unknown["meets_requested_pixels"] is None
    assert unknown["width_px"] is None
    assert vector["type"] == "vector"
    assert vector["meets_requested_pixels"] is None
    assert "not a hero" in small["guidance"]


def test_bad_resolution_inputs_return_tool_error(tmp_path):
    tools = _tools(tmp_path)
    for value in (0, -1, True, 0.5, "600"):
        result = _search(tools, "image", min_width_px=value)
        assert result["status"] == "error"
        assert "positive integer" in str(result)
