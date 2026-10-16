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
import copy
import hashlib
import io
import json
from dataclasses import replace
from pathlib import Path

from lumen_agent.config import AgentRuntimeConfig
from lumen_agent.tools import view as view_mod
from lumen_agent.tools.asset_preview import asset_preview_path
from lumen_agent.tools.web_substrate import LumenWebTools

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_web_asset_view_exposes_preview_alpha_without_mutation_or_original_claim(tmp_path):
    from PIL import Image, ImageDraw

    tools = _tools(tmp_path)
    # Paletted transparency is used by the held product assets too. The preview
    # can differ from the original; only these decoded bytes are being measured.
    image = Image.new("P", (512, 256), 0)
    image.putpalette([0, 0, 0, 255, 255, 255] + [0] * 762)
    image.info["transparency"] = bytes([0, 255])
    ImageDraw.Draw(image).rectangle((128, 64, 383, 191), fill=1)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    raw = buf.getvalue()
    digest = hashlib.sha256(raw).hexdigest()
    ref = f"sha256/{digest[:2]}/{digest}"
    path = tmp_path / "store" / ref
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    record = _raster_record("product", thumb_ref=ref, thumb_size=(512, 256))
    tools.web_doc["assets"] = {"product": record}
    before = copy.deepcopy(tools.web_doc)

    blocks = tools._view_content("asset:product", can_render=False)
    assert len([b for b in blocks if b["type"] == "image"]) == 2
    receipt = json.loads(blocks[2]["text"])
    assert receipt["preview_alpha"] == {
        "width_px": 512, "height_px": 256,
        "transparent_pixels": 98304, "opaque_pixels": 32768,
        "translucent_pixels": 0, "visible_bounds_px": [128, 64, 384, 192],
    }
    assert receipt["preview_sha256"] == digest
    assert receipt["composition"] == "unclassified"
    assert receipt["decoded_frame_index"] == 0
    assert "not proof about an unavailable original" in receipt["inspection_only"]
    comparison = Image.open(io.BytesIO(base64.b64decode(blocks[3]["data"])))
    assert comparison.getpixel((0, 0)) == (255, 255, 255)
    assert comparison.getpixel((comparison.width - 1, 0)) == (32, 32, 32)
    assert tools.web_doc == before
    assert path.read_bytes() == raw


def test_web_opaque_preview_reports_pixels_without_inventing_a_composite(tmp_path):
    tools = _tools(tmp_path)
    ref = _blob(tmp_path / "store", "e" * 64, (512, 256))
    tools.web_doc["assets"] = {"photo": _raster_record("photo", thumb_ref=ref)}
    blocks = tools._view_content("asset:photo")
    receipts = [json.loads(b["text"]) for b in blocks
                if b["type"] == "text" and b["text"].startswith('{"preview_alpha"')]
    assert len(receipts) == 1, "Opaque pixels need an explicit receipt, not silence"
    assert receipts[0]["preview_alpha"]["opaque_pixels"] == 512 * 256
    assert receipts[0]["preview_alpha"]["transparent_pixels"] == 0
    assert receipts[0]["composition"] == "unclassified"
    assert len([b for b in blocks if b["type"] == "image"]) == 1


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
    thumb_size: tuple[int | None, int | None] = (256, 160),
    primary_ref: str = "sha256/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
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
            "location": {"provider": "opaque_asset_store", "opaque_ref": "sha256/bb/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},
        },
        "vector": {"width": 240.0, "height": 48.0},
    }


def _legacy_svg_record(asset_id: str) -> dict:
    """A vector ingested BEFORE W1.2: the helper attached a self-referential
    "thumbnail" whose location is the SVG bytes themselves. Nothing can decode
    it as a raster, so it must not be served as one."""
    record = _svg_record(asset_id)
    record["media"]["thumbnail"] = {
        "location": {"provider": "opaque_asset_store", "opaque_ref": "sha256/bb/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},
        "mime_type": "image/svg+xml",
        "pixel_width": None,
        "pixel_height": None,
    }
    return record


def _rasterized_svg_record(asset_id: str, thumb_ref: str) -> dict:
    """A vector ingested AFTER W1.2: a real PNG thumbnail beside the SVG."""
    record = _svg_record(asset_id)
    record["media"]["thumbnail"] = {
        "location": {"provider": "opaque_asset_store", "opaque_ref": thumb_ref},
        "mime_type": "image/png",
        "pixel_width": 2560,
        "pixel_height": 512,
    }
    return record


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
    # BOTH dimensions. The attached image is the 256px thumbnail (and a small one
    # is upscaled on the way out), so reporting only the preview size told the
    # director every kit asset was ~256px — the one fact that decides whether an
    # asset can carry a full-bleed band, reported wrong for every thumbnailed
    # asset in the kit.
    assert "source 1600x1000px" in text
    assert "preview 256x160px" in text
    assert "brand_guide" in text
    assert any(b.get("type") == "image" for b in blocks)
    assert "asset_viewed" in _trace_summaries(tools)


def test_a_full_size_preview_reports_its_dimensions_once(tmp_path: Path):
    """No thumbnail → the preview IS the source raster, so there are not two
    numbers to report and the text does not invent a distinction."""
    store = tmp_path / "store"
    ref = _blob(store, "9" * 64, (1600, 1000))
    record = _raster_record("asset_kit_raw", thumb_ref=None, primary_ref=ref)
    tools = _tools(tmp_path, brand_kit_assets={"asset_kit_raw": {"record": record}})

    blocks = tools._view_content("asset:asset_kit_raw")
    text = blocks[0]["text"]

    assert "source 1600x1000px" in text
    assert "preview" not in text
    measured = json.loads(blocks[2]["text"])["preview_alpha"]
    assert (measured["width_px"], measured["height_px"]) == (1600, 1000)


def test_dimensions_are_omitted_when_the_record_carries_none(tmp_path: Path):
    """A record with neither source nor preview dims says the rest honestly
    rather than printing a made-up size."""
    store = tmp_path / "store"
    ref = _blob(store, "8" * 64, (600, 400))
    record = _raster_record("asset_kit_bare", thumb_ref=ref, thumb_size=(None, None))
    record.pop("raster")
    tools = _tools(tmp_path, brand_kit_assets={"asset_kit_bare": {"record": record}})

    blocks = tools._view_content("asset:asset_kit_bare")
    text = blocks[0]["text"]

    assert "px" not in text
    assert "source brand_guide" in text
    # Missing catalog dimensions remain absent from the label; decoded preview
    # measurements are separate evidence, never invented original dimensions.
    measured = json.loads(blocks[2]["text"])["preview_alpha"]
    assert (measured["width_px"], measured["height_px"]) == (600, 400)
    assert any(b.get("type") == "image" for b in tools._view_content("asset:asset_kit_bare"))


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
    assert "source 1600x1000px" in text
    assert "preview 300x200px" in text
    assert "generated" in text
    assert any(b.get("type") == "image" for b in blocks)


def test_workspace_library_asset_is_viewable(tmp_path: Path):
    """`search_assets` hands the director library ids and the prompt tells it to
    look before deciding — so the library is the third place an id resolves from,
    not a hole the director falls into."""
    store = tmp_path / "store"
    ref = _blob(store, "7" * 64, (256, 160))
    record = _raster_record(
        "asset_lib_photo", thumb_ref=ref, source_kind="uploaded", label="record label"
    )
    tools = _tools(
        tmp_path,
        asset_library={
            "asset_lib_photo": {
                "record": record,
                "title": "Warehouse floor",
                "description": "A wide shot of the packing line.",
            }
        },
    )

    blocks = tools._view_content("asset:asset_lib_photo")

    text = _texts(blocks)
    assert "asset_lib_photo" in text
    assert "Warehouse floor" in text
    assert "source 1600x1000px" in text
    assert "source uploaded" in text
    assert any(b.get("type") == "image" for b in blocks)


def test_unknown_asset_id_lists_available_ids_capped_at_twelve(tmp_path: Path):
    store = tmp_path / "store"
    ref = _blob(store, "e" * 64, (256, 160))
    manifest = {
        f"asset_kit_{i:02d}": {"record": _raster_record(f"asset_kit_{i:02d}", thumb_ref=ref)}
        for i in range(15)
    }
    tools = _tools(
        tmp_path,
        brand_kit_assets=manifest,
        asset_library={
            "asset_lib_photo": {"record": _raster_record("asset_lib_photo", thumb_ref=ref)}
        },
    )
    tools.web_doc["assets"] = {"asset_img_web_0": _raster_record("asset_img_web_0", thumb_ref=ref)}

    blocks = tools._view_content("asset:asset_nope")

    assert all(b.get("type") == "text" for b in blocks)
    text = _texts(blocks)
    assert "asset_nope" in text
    # All THREE sources are offered — the document registry and the library too,
    # not just the kit.
    assert "asset_img_web_0" in text
    assert "Library assets: asset_lib_photo" in text
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
    # The vector cause is named — for a mime that actually IS one.
    assert "vector" in text
    assert "asset_no_preview" in _trace_summaries(tools)


def test_a_legacy_self_referential_svg_thumbnail_says_so_instead_of_failing_to_view(
    tmp_path: Path,
):
    """The real Stripe `logo.svg` record's shape. Before the resolver learned to
    read the thumbnail's mime, this path handed the viewer the SVG bytes as if
    they were a raster and the director got a PIL decode failure — noise where
    the designed answer is one honest sentence."""
    store = tmp_path / "store"
    store.mkdir(parents=True, exist_ok=True)
    (store / "sha256/bb").mkdir(parents=True, exist_ok=True)
    (store / "sha256/bb/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb").write_bytes(b"<svg xmlns='http://www.w3.org/2000/svg'/>")
    tools = _tools(
        tmp_path,
        brand_kit_assets={"asset_logo_legacy": {"record": _legacy_svg_record("asset_logo_legacy")}},
    )

    blocks = tools._view_content("asset:asset_logo_legacy")

    assert all(b.get("type") == "text" for b in blocks)
    text = _texts(blocks)
    assert "no raster preview" in text
    assert "view failed" not in text
    assert "asset_no_preview" in _trace_summaries(tools)


def test_a_non_vector_unpreviewable_mime_is_not_called_a_vector(tmp_path: Path):
    """The no-preview string states only what is established: this media has no
    raster the vision APIs read. Blaming "a vector with no thumbnail" for a TIFF
    would send the reader hunting the wrong cause."""
    record = _raster_record("asset_kit_tiff", thumb_ref=None, primary_ref="sha256/33/3333333333333333333333333333333333333333333333333333333333333333")
    record["media"]["mime_type"] = "image/tiff"
    tools = _tools(tmp_path, brand_kit_assets={"asset_kit_tiff": {"record": record}})

    text = _texts(tools._view_content("asset:asset_kit_tiff"))

    assert "no raster preview" in text
    assert "image/tiff" in text
    assert "vector" not in text


def test_missing_preview_bytes_are_reported_honestly(tmp_path: Path):
    """The record names a thumbnail ref that is not on disk — never an exception,
    never a silent empty block."""
    record = _raster_record("asset_kit_gone", thumb_ref="sha256/ff/ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff")
    tools = _tools(
        tmp_path, brand_kit_assets={"asset_kit_gone": {"record": record}}
    )

    blocks = tools._view_content("asset:asset_kit_gone")

    assert all(b.get("type") == "text" for b in blocks)
    text = _texts(blocks)
    assert "asset_kit_gone" in text
    assert "missing" in text
    assert "asset_missing_file" in _trace_summaries(tools)


# --- the label chain ---------------------------------------------------------


def test_label_falls_back_through_record_then_source_then_the_id(tmp_path: Path):
    """Manifest title → record label → the placement label the registration wrote
    onto `source` → the id itself. Every link is a shape real records take, so
    every link is walked here rather than assumed."""
    store = tmp_path / "store"
    ref = _blob(store, "5" * 64, (256, 160))

    # No manifest title: the record's own label speaks.
    record = _raster_record("asset_a", thumb_ref=ref, label="Engine label")
    tools = _tools(tmp_path, brand_kit_assets={"asset_a": {"record": record}})
    assert "Engine label" in _texts(tools._view_content("asset:asset_a"))

    # No record label either: `_use_brand_asset`/`_use_library_asset` stamp the
    # resolved placement label onto source.
    record = _raster_record("asset_b", thumb_ref=ref, label="")
    record.pop("label")
    record["source"]["label"] = "Placement label"
    tools = _tools(tmp_path, brand_kit_assets={"asset_b": {"record": record}})
    assert "Placement label" in _texts(tools._view_content("asset:asset_b"))

    # Nothing nameable anywhere: the id, never a blank or a fabrication.
    record = _raster_record("asset_c", thumb_ref=ref)
    record.pop("label")
    record["source"].pop("label")
    tools = _tools(tmp_path, brand_kit_assets={"asset_c": {"record": record}})
    assert "view: asset asset_c — asset_c" in _texts(tools._view_content("asset:asset_c"))


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
        _raster_record("asset_kit_hero", thumb_ref="sha256/cc/cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"),
        _raster_record("asset_kit_raw", thumb_ref=None, primary_ref="sha256/dd/dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"),
        _svg_record("asset_logo_svg"),
    ):
        assert tools._asset_preview_path(record) == asset_preview_path(
            record, config.effective_asset_store_root
        )


def test_shared_resolver_prefers_thumbnail_then_raster_then_nothing(tmp_path: Path):
    store = tmp_path / "store"

    thumbed = _raster_record("a", thumb_ref="sha256/11/1111111111111111111111111111111111111111111111111111111111111111")
    assert asset_preview_path(thumbed, store) == (
        str(store / "sha256/11/1111111111111111111111111111111111111111111111111111111111111111"),
        256,
        160,
    )

    raw = _raster_record("b", thumb_ref=None, primary_ref="sha256/22/2222222222222222222222222222222222222222222222222222222222222222")
    assert asset_preview_path(raw, store) == (str(store / "sha256/22/2222222222222222222222222222222222222222222222222222222222222222"), 1600, 1000)

    assert asset_preview_path(_svg_record("c"), store) is None


def test_a_thumbnail_that_is_not_a_raster_is_not_served_as_one(tmp_path: Path):
    """Every SVG ingested before W1.2 carries a self-referential "thumbnail"
    pointing back at the SVG bytes. Trusting it handed the viewer a path PIL
    cannot decode — a contained "view failed" string where the designed answer
    is the honest "no raster preview". A thumbnail block only counts as a
    preview when its declared mime is one the vision APIs actually read."""
    store = tmp_path / "store"

    assert asset_preview_path(_legacy_svg_record("legacy"), store) is None


def test_a_thumbnail_with_no_declared_mime_is_still_trusted_as_a_raster(tmp_path: Path):
    """The check is on a mime that IS present and unreadable — a block without
    one keeps today's behavior. Every real writer stamps `image/png`, and
    records in flight must not lose their preview to a missing field."""
    store = tmp_path / "store"
    record = _raster_record("d", thumb_ref="sha256/44/4444444444444444444444444444444444444444444444444444444444444444")
    assert "mime_type" not in record["media"]["thumbnail"]

    assert asset_preview_path(record, store) == (str(store / "sha256/44/4444444444444444444444444444444444444444444444444444444444444444"), 256, 160)


def test_a_rasterized_vector_resolves_to_its_png_thumbnail(tmp_path: Path):
    """W1.2's ingest output: the SVG record now carries a real PNG beside it,
    and that is what the lanes look at."""
    store = tmp_path / "store"
    record = _rasterized_svg_record("logo", "sha256/55/5555555555555555555555555555555555555555555555555555555555555555")

    assert asset_preview_path(record, store) == (str(store / "sha256/55/5555555555555555555555555555555555555555555555555555555555555555"), 2560, 512)


# --- D3: a vector the agent can actually look at ------------------------------
#
# apollo.io, W5: `view("asset:<svg>")` answered `asset_unavailable`, so the agent
# PLACED logos it could never see -- which is how an OpenAI glyph shipped in an
# apollo ad. It flagged the mark twice from metadata alone ("renders as the
# asterisk-A mark, not a wordmark") because looking was not on offer.



def _seed_svg_blob(tmp_path: Path) -> None:
    """Materialized SVG bytes at the record's digest path — the production
    contract (the API manifest read-throughs land bytes in the engine cache
    before a turn). The rasterizer's byte precheck refuses to hand the engine
    an absent blob (it would paint a BLANK plate and warn, and the blank would
    be cached per digest — the Wave-C D3 probe-D poisoning)."""
    blob = tmp_path / "store" / "sha256" / "bb" / ("b" * 64)
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(b"<svg xmlns='http://www.w3.org/2000/svg'/>")


class _RasterizingCore:
    """Stand-in for the engine helper: renders any scene to one PNG artifact.

    Mirrors the real contract the ingestion pipeline relies on -- pixel bytes
    arrive as a list of ints under `bytes`, never `bytes_base64`.
    """

    def __init__(self) -> None:
        self.exports = 0

    def new_scene(self, doc_id, title):
        return {"id": doc_id, "title": title, "pages": {}, "assets": {}}

    def apply_operations(self, scene, operations):
        self.last_operations = operations
        return {"scene": scene}

    def export_preview(self, scene, fmt, **kwargs):
        from PIL import Image

        self.exports += 1
        self.last_scene = scene
        buffer = io.BytesIO()
        Image.new("RGB", (512, 512), (200, 40, 40)).save(buffer, format="PNG")
        return {"export": {"artifacts": [{"bytes": list(buffer.getvalue())}]}}


def test_an_svg_asset_is_rasterized_on_demand_and_becomes_viewable(tmp_path: Path):
    """THE red case. Same fixture as
    `test_svg_without_a_thumbnail_says_so_instead_of_faking_a_preview`, which
    pins the pre-fix answer: without an engine to rasterize with, that test
    still gets `asset_no_preview`. With one, the agent gets pixels."""
    _seed_svg_blob(tmp_path)
    tools = _tools(
        tmp_path,
        brand_kit_assets={"asset_logo_svg": {"record": _svg_record("asset_logo_svg")}},
    )
    tools.core = _RasterizingCore()

    blocks = tools._view_content("asset:asset_logo_svg")

    assert any(b.get("type") == "image" for b in blocks), _texts(blocks)
    assert _emitted_image(blocks).size == (512, 512)
    assert "asset_no_preview" not in _trace_summaries(tools)
    # The asset really was handed to the engine as an image node in a page.
    assert tools.core.last_scene["assets"]["asset_logo_svg"]["id"] == "asset_logo_svg"


def test_a_legacy_self_referential_svg_thumbnail_is_rasterized_too(tmp_path: Path):
    """The pre-W1.2 shape -- a "thumbnail" that is the SVG bytes again. The
    resolver still refuses to serve it as a raster; the rasterizer supplies one."""
    _seed_svg_blob(tmp_path)
    tools = _tools(
        tmp_path,
        brand_kit_assets={
            "asset_logo_legacy": {"record": _legacy_svg_record("asset_logo_legacy")}
        },
    )
    tools.core = _RasterizingCore()

    blocks = tools._view_content("asset:asset_logo_legacy")

    assert any(b.get("type") == "image" for b in blocks), _texts(blocks)


def test_the_rasterized_preview_is_cached_per_digest(tmp_path: Path):
    """An engine round-trip is expensive; looking twice must not pay twice."""
    _seed_svg_blob(tmp_path)
    tools = _tools(
        tmp_path,
        brand_kit_assets={"asset_logo_svg": {"record": _svg_record("asset_logo_svg")}},
    )
    tools.core = _RasterizingCore()

    tools._view_content("asset:asset_logo_svg")
    tools._view_content("asset:asset_logo_svg")

    assert tools.core.exports == 1


def test_a_raster_asset_never_reaches_the_rasterizer(tmp_path: Path):
    """Only vectors take the engine path -- `vector_source_digest` gates on the
    record's own mime, so a PNG with a broken thumbnail is not re-rendered."""
    from lumen_agent.tools.asset_preview import rasterize_vector_preview, vector_source_digest

    record = _raster_record("asset_kit_hero", thumb_ref=None)
    assert vector_source_digest(record) is None
    core = _RasterizingCore()
    assert rasterize_vector_preview(core, record, "asset_kit_hero", tmp_path) is None
    assert core.exports == 0


def test_an_engine_that_declines_leaves_the_honest_refusal_in_place(tmp_path: Path):
    """A rasterizer that fails must degrade to the designed sentence, never to
    a traceback or a path nothing can decode."""

    class _DecliningCore(_RasterizingCore):
        def export_preview(self, scene, fmt, **kwargs):
            raise RuntimeError("helper unavailable")

    tools = _tools(
        tmp_path,
        brand_kit_assets={"asset_logo_svg": {"record": _svg_record("asset_logo_svg")}},
    )
    tools.core = _DecliningCore()

    blocks = tools._view_content("asset:asset_logo_svg")

    assert all(b.get("type") == "text" for b in blocks)
    assert "no raster preview" in _texts(blocks)
    assert "asset_no_preview" in _trace_summaries(tools)


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
