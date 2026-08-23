"""W1.1 — `view("asset:<id>")` on the WEB lane.

The website trio is required to make an explicit imagery decision (D4), but the
web `view` tool had no way to look at an asset's actual pixels: `asset:` existed
only on the scene lane. A decision made off titles and tags alone is a decision
made blind — the kit's "hero" can be a 296x124 crop and its "texture" a QR code.

These tests pin the four honest outcomes of the web branch (viewed / unknown /
no raster preview / missing bytes), the capped id listing, the advertised target,
and the fact that the scene lane now delegates to the SAME shared resolver so the
two lanes cannot drift.
"""

from __future__ import annotations

import base64
import io
import json
from dataclasses import replace
from pathlib import Path

from lumen_agent.config import AgentRuntimeConfig
from lumen_agent.tools import view as view_mod
from lumen_agent.tools.asset_preview import asset_preview_path
from lumen_agent.tools.web_substrate import LumenWebTools

REPO_ROOT = Path(__file__).resolve().parents[3]


# --- fixtures ----------------------------------------------------------------


def _blob(store_root: Path, digest: str, size: tuple[int, int]) -> str:
    """Write a real PNG at the content-addressed ref and return the ref."""
    from PIL import Image

    ref = f"sha256/{digest[:2]}/{digest}"
    path = store_root / ref
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (10, 20, 30)).save(path, format="PNG")
    return ref


def _raster_record(
    asset_id: str,
    *,
    thumb_ref: str | None,
    thumb_size: tuple[int, int] = (256, 160),
    primary_ref: str = "sha256/aa/aaaa",
    source_kind: str = "brand_guide",
    label: str = "Hero photograph",
) -> dict:
    media: dict = {
        "mime_type": "image/png",
        "filename": f"{asset_id}.png",
        "location": {"provider": "opaque_asset_store", "opaque_ref": primary_ref},
    }
    if thumb_ref is not None:
        media["thumbnail"] = {
            "location": {"provider": "opaque_asset_store", "opaque_ref": thumb_ref},
            "pixel_width": thumb_size[0],
            "pixel_height": thumb_size[1],
        }
    return {
        "id": asset_id,
        "label": label,
        "kind": "raster",
        "status": "ready",
        "source": {"kind": source_kind, "source_asset_id": asset_id, "label": label},
        "media": media,
        "raster": {"pixel_width": 1600, "pixel_height": 1000},
    }


def _svg_record(asset_id: str) -> dict:
    """A vector asset with NO derived thumbnail — the honest 'nothing to look at'
    case. W1.2 changes what INGEST produces; it does not change this record, so
    this fixture stays valid after it lands."""
    return {
        "id": asset_id,
        "label": "Acme wordmark",
        "kind": "logo",
        "status": "ready",
        "source": {"kind": "brand_guide", "source_asset_id": asset_id},
        "media": {
            "mime_type": "image/svg+xml",
            "filename": f"{asset_id}.svg",
            "location": {"provider": "opaque_asset_store", "opaque_ref": "sha256/bb/bbbb"},
        },
        "vector": {"width": 240.0, "height": 48.0},
    }


def _tools(tmp_path: Path, **cfg) -> LumenWebTools:
    """A LumenWebTools over a hand-seeded WebDoc (no core helper, no browser)."""
    config = replace(
        AgentRuntimeConfig.from_env(REPO_ROOT),
        trace_dir=tmp_path / "workspace_root",
        asset_store_root=tmp_path / "store",
        **cfg,
    )
    seed = {
        "schema_version": 1,
        "id": "doc_web_test",
        "title": "Test site",
        "theme": {},
        "custom_css": "",
        "pages": [
            {
                "id": "home",
                "name": "Home",
                "route": "/",
                "root": "root",
                "nodes": {
                    "root": {"id": "root", "kind": "container", "classes": "", "new_tab": False}
                },
            }
        ],
        "assets": {},
    }
    return LumenWebTools(config, "Build a page", initial_web_doc=seed)


def _texts(blocks: list) -> str:
    return "\n".join(b["text"] for b in blocks if b.get("type") == "text")


def _emitted_image(blocks: list):
    from PIL import Image

    payload = [b for b in blocks if b.get("type") == "image"][0]["data"]
    return Image.open(io.BytesIO(base64.b64decode(payload)))


def _trace_summaries(tools: LumenWebTools) -> list[str]:
    lines = (tools.trace_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line).get("output_summary") for line in lines]


# --- the four outcomes -------------------------------------------------------


def test_kit_manifest_asset_is_viewable(tmp_path: Path):
    store = tmp_path / "store"
    ref = _blob(store, "c" * 64, (256, 160))
    record = _raster_record("asset_kit_hero", thumb_ref=ref)
    tools = _tools(
        tmp_path,
        brand_kit_assets={
            "asset_kit_hero": {"record": record, "title": "Team at the bench"}
        },
    )

    blocks = tools._view_content("asset:asset_kit_hero")

    text = _texts(blocks)
    assert "asset_kit_hero" in text
    # The manifest TITLE is the human label when present (it is what the brand
    # card's inventory shows the director).
    assert "Team at the bench" in text
    assert "256x160px" in text
    assert "brand_guide" in text
    assert any(b.get("type") == "image" for b in blocks)
    assert "asset_viewed" in _trace_summaries(tools)


def test_document_registry_asset_is_viewable(tmp_path: Path):
    """An asset already registered into the WebDoc (generated, or placed from the
    kit/library) is viewable by the same target — the registry value IS the
    record, not a manifest entry."""
    store = tmp_path / "store"
    ref = _blob(store, "d" * 64, (300, 200))
    record = _raster_record(
        "asset_img_web_0",
        thumb_ref=ref,
        thumb_size=(300, 200),
        source_kind="generated",
        label="Generated hero",
    )
    tools = _tools(tmp_path)
    tools.web_doc["assets"] = {"asset_img_web_0": record}

    blocks = tools._view_content("asset:asset_img_web_0")

    text = _texts(blocks)
    assert "asset_img_web_0" in text
    assert "Generated hero" in text
    assert "300x200px" in text
    assert "generated" in text
    assert any(b.get("type") == "image" for b in blocks)


def test_unknown_asset_id_lists_available_ids_capped_at_twelve(tmp_path: Path):
    store = tmp_path / "store"
    ref = _blob(store, "e" * 64, (256, 160))
    manifest = {
        f"asset_kit_{i:02d}": {"record": _raster_record(f"asset_kit_{i:02d}", thumb_ref=ref)}
        for i in range(15)
    }
    tools = _tools(tmp_path, brand_kit_assets=manifest)
    tools.web_doc["assets"] = {"asset_img_web_0": _raster_record("asset_img_web_0", thumb_ref=ref)}

    blocks = tools._view_content("asset:asset_nope")

    assert all(b.get("type") == "text" for b in blocks)
    text = _texts(blocks)
    assert "asset_nope" in text
    # The document registry's id is offered too.
    assert "asset_img_web_0" in text
    # Capped: the first 12 sorted kit ids are named, the last 3 are NOT, and the
    # overflow is stated rather than silently swallowed.
    assert "asset_kit_00" in text and "asset_kit_11" in text
    assert "asset_kit_12" not in text
    assert "3 more" in text
    assert "asset_unknown" in _trace_summaries(tools)


def test_svg_without_a_thumbnail_says_so_instead_of_faking_a_preview(tmp_path: Path):
    tools = _tools(
        tmp_path,
        brand_kit_assets={"asset_logo_svg": {"record": _svg_record("asset_logo_svg")}},
    )

    blocks = tools._view_content("asset:asset_logo_svg")

    assert all(b.get("type") == "text" for b in blocks)
    text = _texts(blocks)
    assert "asset_logo_svg" in text
    assert "no raster preview" in text
    assert "image/svg+xml" in text
    assert "asset_no_preview" in _trace_summaries(tools)


def test_missing_preview_bytes_are_reported_honestly(tmp_path: Path):
    """The record names a thumbnail ref that is not on disk — never an exception,
    never a silent empty block."""
    record = _raster_record("asset_kit_gone", thumb_ref="sha256/ff/ffff")
    tools = _tools(
        tmp_path, brand_kit_assets={"asset_kit_gone": {"record": record}}
    )

    blocks = tools._view_content("asset:asset_kit_gone")

    assert all(b.get("type") == "text" for b in blocks)
    text = _texts(blocks)
    assert "asset_kit_gone" in text
    assert "missing" in text
    assert "asset_missing_file" in _trace_summaries(tools)


# --- the shared contracts ----------------------------------------------------


def test_asset_view_image_rides_the_many_image_ceiling(tmp_path: Path):
    """G5: every web view image clamps to 2000px — a kit image is no exception,
    since it lands in the same accumulating conversation as the page captures."""
    store = tmp_path / "store"
    ref = _blob(store, "a" * 64, (4200, 2400))
    record = _raster_record("asset_kit_big", thumb_ref=ref, thumb_size=(4200, 2400))
    tools = _tools(tmp_path, brand_kit_assets={"asset_kit_big": {"record": record}})

    emitted = _emitted_image(tools._view_content("asset:asset_kit_big"))

    assert max(emitted.size) <= view_mod._VISION_MANY_IMAGE_MAX_PX


def test_unknown_target_error_advertises_the_asset_target(tmp_path: Path):
    tools = _tools(tmp_path)
    text = _texts(tools._view_content("nonsense"))
    assert "asset:<asset_id>" in text


def test_asset_branch_is_identical_for_both_role_variants(tmp_path: Path):
    """The `can_render` asymmetry exists only for the preview refusals — an asset
    view has no dependency on a render, so both roles get the same answer."""
    store = tmp_path / "store"
    ref = _blob(store, "b" * 64, (256, 160))
    record = _raster_record("asset_kit_hero", thumb_ref=ref)
    tools = _tools(tmp_path, brand_kit_assets={"asset_kit_hero": {"record": record}})

    director = tools._view_content("asset:asset_kit_hero", can_render=True)
    author = tools._view_content("asset:asset_kit_hero", can_render=False)

    assert _texts(director) == _texts(author)
    # …and it is the real answer in both, not a shared refusal.
    assert "Hero photograph" in _texts(director)
    assert any(b.get("type") == "image" for b in director)
    assert any(b.get("type") == "image" for b in author)


def test_scene_lane_delegates_to_the_shared_resolver(tmp_path: Path, monkeypatch):
    """The extraction cannot drift: LumenDesignTools._asset_preview_path returns
    exactly what the shared resolver returns for the same record + store root."""
    from agent_fixtures import FakeCoreClient, runtime_config
    from lumen_agent.tools.substrate import LumenDesignTools

    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    config = replace(runtime_config(tmp_path), asset_store_root=tmp_path / "store")
    tools = LumenDesignTools(config, "Make a poster")

    for record in (
        _raster_record("asset_kit_hero", thumb_ref="sha256/cc/cccc"),
        _raster_record("asset_kit_raw", thumb_ref=None, primary_ref="sha256/dd/dddd"),
        _svg_record("asset_logo_svg"),
    ):
        assert tools._asset_preview_path(record) == asset_preview_path(
            record, config.effective_asset_store_root
        )


def test_shared_resolver_prefers_thumbnail_then_raster_then_nothing(tmp_path: Path):
    store = tmp_path / "store"

    thumbed = _raster_record("a", thumb_ref="sha256/11/1111")
    assert asset_preview_path(thumbed, store) == (
        str(store / "sha256/11/1111"),
        256,
        160,
    )

    raw = _raster_record("b", thumb_ref=None, primary_ref="sha256/22/2222")
    assert asset_preview_path(raw, store) == (str(store / "sha256/22/2222"), 1600, 1000)

    assert asset_preview_path(_svg_record("c"), store) is None


# --- the prompts advertise it ------------------------------------------------


def test_both_roles_are_told_they_can_look_at_an_asset():
    from lumen_agent.prompts_web import build_web_author_prompt, build_web_orchestrator_prompt

    director = build_web_orchestrator_prompt(
        doc_title="Acme",
        has_existing_content=False,
        brand_card="{}",
        review_cap=2,
        author_cap=2,
    )
    author = build_web_author_prompt(brand_card="{}", theme_token_names="primary, accent")
    assert 'view("asset:' in director
    assert 'view("asset:' in author
