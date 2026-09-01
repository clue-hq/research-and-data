"""Brandfetch vendor rung: settings, parsing, cell mapping, network driver."""

from __future__ import annotations


def test_brandfetch_settings_fields_exist_with_safe_defaults(monkeypatch):
    # Fresh Settings instance so developer .env values don't leak into assertions.
    from py_lumen_config.config import Settings

    for var in (
        "BRANDFETCH_API_KEY",
        "BRANDFETCH_CLIENT_ID",
        "BRANDFETCH_API_BASE_URL",
        "BRANDFETCH_TIMEOUT_S",
    ):
        monkeypatch.delenv(var, raising=False)
    fresh = Settings(_env_file=None)
    assert fresh.brandfetch_api_key == ""
    assert fresh.brandfetch_client_id == ""
    assert fresh.brandfetch_api_base_url == "https://api.brandfetch.io"
    assert fresh.brandfetch_timeout_s == 20.0


def test_brandfetch_settings_load_from_env(monkeypatch):
    from py_lumen_config.config import Settings

    monkeypatch.setenv("BRANDFETCH_API_KEY", "bf_test_key")
    monkeypatch.setenv("BRANDFETCH_CLIENT_ID", "idTESTCLIENT")
    monkeypatch.setenv("BRANDFETCH_TIMEOUT_S", "5.5")
    fresh = Settings(_env_file=None)
    assert fresh.brandfetch_api_key == "bf_test_key"
    assert fresh.brandfetch_client_id == "idTESTCLIENT"
    assert fresh.brandfetch_timeout_s == 5.5


# A trimmed real-shaped Brand API response (the schema's logos[] shape:
# theme dark|light|null, type icon|logo|symbol|other, formats[] with
# src/format/width/height/size/background).
BRAND_PAYLOAD = {
    "name": "Acme",
    "domain": "acme.com",
    "logos": [
        {  # their theme "dark" = dark-colored art FOR LIGHT backgrounds
            "theme": "dark",
            "type": "logo",
            "tags": [],
            "formats": [
                {"src": "https://asset.brandfetch.io/a/lockup-dark.svg", "format": "svg",
                 "width": 400, "height": 80, "size": 4000, "background": "transparent"},
                {"src": "https://asset.brandfetch.io/a/lockup-dark.png", "format": "png",
                 "width": 800, "height": 160, "size": 20000, "background": "transparent"},
            ],
        },
        {
            "theme": "light",
            "type": "symbol",
            "tags": [],
            "formats": [
                {"src": "https://asset.brandfetch.io/a/symbol-light.png", "format": "png",
                 "width": 300, "height": 300, "size": 9000, "background": "transparent"},
            ],
        },
        {  # icon must be ignored entirely (founder ruling i)
            "theme": "dark",
            "type": "icon",
            "tags": [],
            "formats": [
                {"src": "https://asset.brandfetch.io/a/icon.png", "format": "png",
                 "width": 128, "height": 128, "size": 3000, "background": None},
            ],
        },
        {  # photographic assets are never logos
            "theme": None,
            "type": "logo",
            "tags": ["photographic"],
            "formats": [
                {"src": "https://asset.brandfetch.io/a/photo.jpeg", "format": "jpeg",
                 "width": 900, "height": 600, "size": 90000, "background": None},
            ],
        },
    ],
}


def test_cell_name_builds_the_four_cells_and_rejects_junk():
    from lumen_ingestion.logo_family import CELL_NAMES, cell_name

    assert CELL_NAMES == ("light_lockup", "dark_lockup", "light_mark", "dark_mark")
    assert cell_name("light", "lockup") == "light_lockup"
    assert cell_name("dark", "mark") == "dark_mark"
    import pytest as _pytest
    with _pytest.raises(ValueError):
        cell_name("adaptive", "lockup")
    with _pytest.raises(ValueError):
        cell_name("light", "wordmark")


def test_parse_brand_payload_keeps_vendor_vocabulary_and_drops_nothing():
    from lumen_ingestion.logo_vendor import parse_brand_payload

    assets = parse_brand_payload(BRAND_PAYLOAD)
    # Parsing is faithful: all four entries survive; filtering is mapping's job.
    assert [a.type for a in assets] == ["logo", "symbol", "icon", "logo"]
    assert assets[0].theme == "dark"
    assert assets[3].tags == ["photographic"]
    assert assets[0].formats[0]["format"] == "svg"


def test_parse_brand_payload_tolerates_malformed_entries():
    from lumen_ingestion.logo_vendor import parse_brand_payload

    assert parse_brand_payload({}) == []
    assert parse_brand_payload({"logos": "nope"}) == []
    assets = parse_brand_payload({"logos": [{"type": "logo"}, 42, {"formats": []}]})
    # Entries missing fields normalize (theme None, tags [], formats []); non-dicts drop.
    assert len(assets) == 2 and assets[0].type == "logo"


def test_pick_format_prefers_svg_then_largest_transparent_raster():
    from lumen_ingestion.logo_vendor import parse_brand_payload, pick_format

    assets = parse_brand_payload(BRAND_PAYLOAD)
    assert pick_format(assets[0])["format"] == "svg"
    assert pick_format(assets[1])["src"].endswith("symbol-light.png")

    from lumen_ingestion.logo_vendor import VendorAsset
    raster_only = VendorAsset(theme=None, type="logo", tags=[], formats=[
        {"src": "s", "format": "png", "width": 100, "height": 20, "size": 1,
         "background": None},
        {"src": "b", "format": "webp", "width": 600, "height": 120, "size": 2,
         "background": "transparent"},
    ])
    assert pick_format(raster_only)["src"] == "b"
    assert pick_format(VendorAsset(theme=None, type="logo", tags=[], formats=[])) is None
