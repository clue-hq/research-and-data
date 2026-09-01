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
    monkeypatch.setenv("BRANDFETCH_API_BASE_URL", "https://example.test")
    monkeypatch.setenv("BRANDFETCH_TIMEOUT_S", "5.5")
    fresh = Settings(_env_file=None)
    assert fresh.brandfetch_api_key == "bf_test_key"
    assert fresh.brandfetch_client_id == "idTESTCLIENT"
    assert fresh.brandfetch_api_base_url == "https://example.test"
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


def _mini_svg(fill: str = "#111111") -> bytes:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="40" '
        f'viewBox="0 0 120 40"><rect width="120" height="40" fill="{fill}"/></svg>'
    ).encode()


def _mini_png(rgb=(16, 24, 32), size=64) -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGBA", (size, size), rgb + (255,)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_map_vendor_assets_inverts_theme_and_skips_icon_and_photographic():
    from lumen_ingestion.logo_vendor import map_vendor_assets_to_cells, parse_brand_payload

    fetched = {
        "https://asset.brandfetch.io/a/lockup-dark.svg": (_mini_svg("#101820"), "image/svg+xml"),
        "https://asset.brandfetch.io/a/symbol-light.png": (_mini_png(), "image/png"),
    }
    cells, notes = map_vendor_assets_to_cells(
        parse_brand_payload(BRAND_PAYLOAD), download=lambda url: fetched.get(url)
    )
    # vendor theme=dark logo -> OUR light_lockup; vendor theme=light symbol -> OUR dark_mark
    assert set(cells) == {"light_lockup", "dark_mark"}
    assert cells["light_lockup"].source == "brandfetch"
    assert cells["light_lockup"].content_type == "image/svg+xml"
    assert cells["dark_mark"].origin_url.endswith("symbol-light.png")
    # icon and photographic never became cells; photographic skip is said out loud
    assert any("photographic" in n for n in notes)


def test_map_vendor_assets_null_theme_is_classified_from_the_bytes():
    from lumen_ingestion.logo_vendor import VendorAsset, map_vendor_assets_to_cells

    dark_ink = VendorAsset(theme=None, type="logo", tags=[], formats=[
        {"src": "u1", "format": "svg", "width": 120, "height": 40, "size": 1,
         "background": "transparent"},
    ])
    cells, _ = map_vendor_assets_to_cells(
        [dark_ink], download=lambda url: (_mini_svg("#101820"), "image/svg+xml")
    )
    # near-black ink -> light_variant verdict -> made for LIGHT backgrounds
    assert list(cells) == ["light_lockup"]
    assert "classified" in cells["light_lockup"].evidence.get("theme_basis", "")


def test_map_vendor_assets_refuses_unrenderable_svg_and_failed_downloads():
    from lumen_ingestion.logo_vendor import VendorAsset, map_vendor_assets_to_cells

    sprite = b'<svg xmlns="http://www.w3.org/2000/svg"><use href="s.svg#x"/></svg>'
    assets = [
        VendorAsset(theme="dark", type="logo", tags=[], formats=[
            {"src": "sprite", "format": "svg", "width": 0, "height": 0, "size": 1,
             "background": None}]),
        VendorAsset(theme="dark", type="symbol", tags=[], formats=[
            {"src": "gone", "format": "png", "width": 300, "height": 300, "size": 1,
             "background": None}]),
    ]
    fetched = {"sprite": (sprite, "image/svg+xml"), "gone": None}
    cells, notes = map_vendor_assets_to_cells(
        assets, download=lambda url: fetched.get(url)
    )
    assert cells == {}
    assert any("cannot paint" in n or "renderable" in n for n in notes)
    assert any("download failed" in n for n in notes)


def test_map_vendor_assets_first_asset_wins_per_cell():
    from lumen_ingestion.logo_vendor import VendorAsset, map_vendor_assets_to_cells

    first = VendorAsset(theme="dark", type="logo", tags=[], formats=[
        {"src": "one", "format": "svg", "width": 120, "height": 40, "size": 1,
         "background": None}])
    second = VendorAsset(theme="dark", type="logo", tags=[], formats=[
        {"src": "two", "format": "svg", "width": 120, "height": 40, "size": 1,
         "background": None}])
    cells, _ = map_vendor_assets_to_cells(
        [first, second], download=lambda url: (_mini_svg(), "image/svg+xml")
    )
    assert cells["light_lockup"].origin_url == "one"


def test_map_vendor_assets_refuses_undecodable_raster():
    from lumen_ingestion.logo_vendor import VendorAsset, map_vendor_assets_to_cells

    garbage = VendorAsset(theme="dark", type="symbol", tags=[], formats=[
        {"src": "g", "format": "png", "width": 300, "height": 300, "size": 1,
         "background": None}])
    cells, notes = map_vendor_assets_to_cells(
        [garbage], download=lambda url: (b"not-a-png-at-all", "image/png")
    )
    assert cells == {}
    assert any("cannot be decoded" in n for n in notes)


def _vendor_transport(handler):
    import httpx

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_vendor_family_happy_path_builds_cells():
    import httpx

    from lumen_ingestion.logo_vendor import fetch_vendor_family

    def handler(request: httpx.Request) -> httpx.Response:
        # cdn.brandfetch.io answers 302 x-bf-error=user_agent_required to a
        # UA-less request; httpx's default happens to pass, but that is a
        # library default, not our contract. Pinned on BOTH request kinds.
        assert request.headers.get("User-Agent") == "clue-design-logo-vendor/1 (+httpx)"
        if request.url.path == "/v2/brands/domain/acme.com":
            assert request.headers["Authorization"] == "Bearer bf_test_key"
            return httpx.Response(200, json=BRAND_PAYLOAD)
        if request.url.path.endswith("lockup-dark.svg"):
            return httpx.Response(200, content=_mini_svg("#101820"),
                                  headers={"content-type": "image/svg+xml"})
        if request.url.path.endswith("symbol-light.png"):
            return httpx.Response(200, content=_mini_png(),
                                  headers={"content-type": "image/png"})
        return httpx.Response(404)

    with _vendor_transport(handler) as client:
        cells, notes = fetch_vendor_family(
            "https://www.acme.com/pricing", api_key="bf_test_key", client=client
        )
    assert set(cells) == {"light_lockup", "dark_mark"}


def test_fetch_vendor_family_404_is_an_answer_and_429_is_typed():
    import httpx
    import pytest as _pytest

    from lumen_ingestion.logo_vendor import VendorLookupFailed, fetch_vendor_family

    with _vendor_transport(lambda r: httpx.Response(404)) as client:
        cells, notes = fetch_vendor_family("acme.com", api_key="k", client=client)
    assert cells == {} and any("no record" in n for n in notes)

    with _vendor_transport(lambda r: httpx.Response(429)) as client:
        with _pytest.raises(VendorLookupFailed) as err:
            fetch_vendor_family("acme.com", api_key="k", client=client)
    assert err.value.code == "quota"

    with _vendor_transport(lambda r: httpx.Response(401)) as client:
        with _pytest.raises(VendorLookupFailed) as err:
            fetch_vendor_family("acme.com", api_key="bad", client=client)
    assert err.value.code == "auth" and "BRANDFETCH_API_KEY" in err.value.message


def test_fetch_vendor_family_blank_key_raises_credentials_missing():
    import pytest as _pytest

    from lumen_ingestion.logo_vendor import VendorCredentialsMissing, fetch_vendor_family

    with _pytest.raises(VendorCredentialsMissing):
        fetch_vendor_family("acme.com", api_key="")


def test_fetch_vendor_family_never_fetches_off_allowlist_hosts():
    import httpx

    from lumen_ingestion.logo_vendor import fetch_vendor_family

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        if request.url.path.startswith("/v2/brands/domain/"):
            return httpx.Response(200, json={"logos": [
                {"theme": "dark", "type": "logo", "tags": [], "formats": [
                    {"src": "https://evil.example/lockup.svg", "format": "svg",
                     "width": 100, "height": 40, "size": 1, "background": None}]}]})
        return httpx.Response(200, content=_mini_svg(), headers={"content-type": "image/svg+xml"})

    with _vendor_transport(handler) as client:
        cells, notes = fetch_vendor_family("acme.com", api_key="k", client=client)
    assert cells == {}
    assert "evil.example" not in seen
    assert any("allowlist" in n for n in notes)


def test_fetch_vendor_family_timeout_and_malformed_are_typed():
    import httpx
    import pytest as _pytest

    from lumen_ingestion.logo_vendor import VendorLookupFailed, fetch_vendor_family

    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated", request=request)

    with _vendor_transport(slow) as client:
        with _pytest.raises(VendorLookupFailed) as err:
            fetch_vendor_family("acme.com", api_key="k", client=client)
    assert err.value.code == "timeout"

    with _vendor_transport(lambda r: httpx.Response(200, content=b"<html>not json</html>")) as client:
        with _pytest.raises(VendorLookupFailed) as err:
            fetch_vendor_family("acme.com", api_key="k", client=client)
    assert err.value.code == "malformed"
