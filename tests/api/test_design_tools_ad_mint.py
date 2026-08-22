import os
from uuid import NAMESPACE_URL, uuid5

import pytest

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
