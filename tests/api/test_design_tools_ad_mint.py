import os
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pytest

from clue_api import design_tools
from clue_api.design_tools import AD_FORMAT_PRESETS, ad_birth_page, mint_empty_ad_document


def test_presets_are_the_ratified_set():
    assert AD_FORMAT_PRESETS == {
        "square": (1200, 1200),
        "portrait": (1080, 1350),
        "story": (1080, 1920),
        "landscape": (1200, 628),
    }


def test_ad_birth_page_mirrors_the_seed_shape():
    page = ad_birth_page(document_id="doc_x", format_key="story", width=1080, height=1920)
    assert page["id"] == "page_" + uuid5(NAMESPACE_URL, "clue:genad:birth-page:doc_x").hex[:16]
    assert page["size"]["width"] == 1080.0 and page["size"]["height"] == 1920.0
    assert page["size"]["unit"] == "pt" and page["size"]["preset"] == "custom"
    assert page["size"]["orientation"] == "portrait"
    assert page["size"]["source"] == {"width": 1080.0, "height": 1920.0, "unit": "px"}
    assert page["size"]["output"] == {"raster": {"width_px": 1080, "height_px": 1920}}
    assert page["children"] == [] and page["bleed"] is None and page["safe_area"] is None
    assert page["background"] == []
    assert page["name"] == "Story"


def test_ad_birth_page_landscape_orientation():
    page = ad_birth_page(document_id="doc_y", format_key="landscape", width=1200, height=628)
    assert page["size"]["orientation"] == "landscape"


@pytest.mark.skipif(
    not os.environ.get("LUMEN_CORE_HELPER"), reason="needs the design engine helper binary"
)
def test_mint_empty_ad_document_round_trips_the_engine():
    scene = mint_empty_ad_document(
        document_id="doc_mint_ad_1",
        title="Test ad",
        format_key="square",
        width=1200,
        height=1200,
        brand_kit_ref=None,
    )
    assert scene["meta"]["id"] == "doc_mint_ad_1"
    assert scene["meta"]["title"] == "Test ad"
    assert scene["meta"]["artifact_type"] == "square_ad"
    assert scene["meta"]["medium"] == "ad"
    assert scene["meta"].get("brand_kit") is None
    assert len(scene["pages"]) == 1
    (page,) = scene["pages"].values()
    assert page["size"]["width"] == 1200.0
    assert scene["nodes"] == {}


# --- the minter, driven against a FAKE core ---------------------------------
#
# The engine round-trip above skips without `LUMEN_CORE_HELPER`, which left the minter's own
# composition — what it asks the engine for, and the brand-kit stamp it applies afterwards —
# with no coverage on the default gate. These run everywhere: the engine is replaced by a fake
# that records its arguments, so what is asserted is the minter's contract, not the engine's.


class _FakeCore:
    """Records what the minter asked for and returns a minimal, engine-shaped answer."""

    def __init__(self) -> None:
        self.new_scene_args: tuple[Any, ...] | None = None
        self.applied_ops: list[dict[str, Any]] | None = None
        self.applied_scene: dict[str, Any] | None = None

    def new_scene(self, document_id, title, artifact_type=None, medium=None):
        self.new_scene_args = (document_id, title, artifact_type, medium)
        return {
            "meta": {
                "id": document_id,
                "title": title,
                "artifact_type": artifact_type,
                "medium": medium,
            },
            "pages": {},
            "nodes": {},
        }

    def apply_operations(self, scene, operations, scope=None):
        self.applied_scene = scene
        self.applied_ops = list(operations)
        pages = {op["page"]["id"]: op["page"] for op in operations if op["kind"] == "add_page"}
        return {"scene": {**scene, "pages": pages}}


@pytest.fixture()
def fake_core(monkeypatch: pytest.MonkeyPatch) -> _FakeCore:
    """Replace the module-level `_core_client` the minter calls.

    It is `lru_cache`d, so the FUNCTION reference is swapped for a plain lambda rather than the
    cache being primed — that leaves the real client's cache untouched for anyone else, and
    `monkeypatch` restores the original (cache and all) at teardown.
    """

    core = _FakeCore()
    monkeypatch.setattr(design_tools, "_core_client", lambda: core)
    return core


def test_the_minter_asks_the_engine_for_the_ad_shaped_scene(fake_core: _FakeCore):
    """`new_scene` carries the ad's identity: the format-derived artifact type and medium."""

    mint_empty_ad_document(
        document_id="doc_fake_1",
        title="Harbor launch",
        format_key="story",
        width=1080,
        height=1920,
        brand_kit_ref=None,
    )

    assert fake_core.new_scene_args == ("doc_fake_1", "Harbor launch", "story_ad", "ad")


def test_the_minter_applies_exactly_one_add_page_holding_the_birth_page(fake_core: _FakeCore):
    """One artboard, and it is `ad_birth_page`'s output verbatim — the deterministic page id
    is what makes a replayed birth converge, so the minter must not re-derive its own."""

    mint_empty_ad_document(
        document_id="doc_fake_2",
        title="Harbor launch",
        format_key="landscape",
        width=1200,
        height=628,
        brand_kit_ref=None,
    )

    assert fake_core.applied_ops == [
        {
            "kind": "add_page",
            "page": ad_birth_page(
                document_id="doc_fake_2", format_key="landscape", width=1200, height=628
            ),
        }
    ]
    # ...applied to the scene the engine just minted, never to a hand-built one.
    assert fake_core.applied_scene is not None
    assert fake_core.applied_scene["meta"]["id"] == "doc_fake_2"


def test_an_explicit_brand_kit_ref_is_stamped_onto_the_minted_scene(fake_core: _FakeCore):
    """The web path's rule (`theme.brand_kit`): an explicit ref is authoritative."""

    scene = mint_empty_ad_document(
        document_id="doc_fake_3",
        title="Harbor launch",
        format_key="square",
        width=1200,
        height=1200,
        brand_kit_ref={"id": "k", "version": 3},
    )

    assert scene["meta"]["brand_kit"] == {"id": "k", "version": 3}


def test_the_stamped_brand_kit_ref_is_copied_not_aliased(fake_core: _FakeCore):
    """A caller mutating its own dict afterwards must not rewrite the minted scene."""

    ref = {"id": "k", "version": 3}
    scene = mint_empty_ad_document(
        document_id="doc_fake_3b",
        title="Harbor launch",
        format_key="square",
        width=1200,
        height=1200,
        brand_kit_ref=ref,
    )
    ref["version"] = 99

    assert scene["meta"]["brand_kit"] == {"id": "k", "version": 3}


def test_no_brand_kit_ref_leaves_the_key_ABSENT_for_the_dal_to_stamp(fake_core: _FakeCore):
    """Absent, not `None`: the DAL's creation contract stamps the workspace's latest approved
    kit at birth only when the key is missing (the Task-1 seam), so an explicit null would
    silently opt a chat-born ad out of its own brand."""

    scene = mint_empty_ad_document(
        document_id="doc_fake_4",
        title="Harbor launch",
        format_key="square",
        width=1200,
        height=1200,
        brand_kit_ref=None,
    )

    assert "brand_kit" not in scene["meta"]
