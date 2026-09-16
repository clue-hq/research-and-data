"""Logo.dev contract tests use a real HTTP client with an in-memory transport."""

from __future__ import annotations

import io
import json
import logging

import httpx
import pytest
from PIL import Image, ImageDraw


def _png(ink="black", *, opaque=False, empty=False):
    image = Image.new("RGBA", (160, 40), "white" if opaque else (0, 0, 0, 0))
    if not empty:
        ImageDraw.Draw(image).rectangle((10, 10, 150, 30), fill=ink)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _profile(domain="aws.amazon.com", name="Amazon Web Services"):
    return {
        "name": name,
        "domain": domain,
        "indexed_at": "2026-09-15T01:02:03Z",
        "logo": f"https://img.logo.dev/{domain}?token=pk_fixture",
        "brandmark": f"https://img.logo.dev/brand/{domain}/asset-id?token=pk_fixture",
        "social_banners": [f"https://img.logo.dev/brand/{domain}/banner?token=pk_fixture"],
    }


def test_brandmark_is_full_logo_and_square_logo_stays_an_alternative():
    from lumen_ingestion.logo_dev import fetch_logo_dev_family

    body = _png()
    requests = []

    def serve(request):
        requests.append(request)
        if request.url.host == "api.logo.dev":
            assert request.url.path == "/brand/aws.amazon.com"
            assert request.headers["Authorization"] == "Bearer sk_fixture"
            return httpx.Response(200, json=_profile())
        assert request.url.host == "img.logo.dev"
        assert "Authorization" not in request.headers
        assert request.url.params["token"] == "pk_fixture"
        assert request.url.params["theme"] == "auto"
        assert request.url.params["greyscale"] == "false"
        assert request.url.params["fallback"] == "404"
        assert request.url.params["format"] == "png"
        assert request.url.params["size"] == "800"
        return httpx.Response(200, content=body, headers={"content-type": "image/png"})

    with httpx.Client(transport=httpx.MockTransport(serve)) as client:
        cells, extras, notes = fetch_logo_dev_family(
            "https://AWS.amazon.com/", company_name="AWS", secret_key="sk_fixture", client=client
        )
    assert set(cells) == {"light_lockup"}
    full = cells["light_lockup"]
    assert full.body == body
    assert full.source == "logo_dev"
    assert full.origin_url == "https://img.logo.dev/brand/aws.amazon.com/asset-id"
    assert full.evidence["provider_asset_kind"] == "brandmark"
    assert full.evidence["vendor_identity"]["provider_domain"] == "aws.amazon.com"
    assert full.evidence["vendor_identity"]["provider_name"] == "Amazon Web Services"
    assert full.evidence["format"] == "png"
    assert full.evidence["transparent"] is True
    assert len(extras) == 1
    assert extras[0].cell == ""
    assert extras[0].evidence["provider_asset_kind"] == "logo"
    assert extras[0].evidence["vendor_type"] == "icon"
    assert len(requests) == 3  # Banner artwork is never logo-family content.
    public = json.dumps([full.evidence, [x.evidence for x in extras], notes])
    assert "pk_fixture" not in public
    assert "sk_fixture" not in public


def test_missing_secret_refuses_without_a_network_call():
    from lumen_ingestion.logo_dev import fetch_logo_dev_family
    from lumen_ingestion.logo_vendor import VendorCredentialsMissing

    def unexpected(request):
        pytest.fail("missing credentials must not cause a request")

    with (
        httpx.Client(transport=httpx.MockTransport(unexpected)) as client,
        pytest.raises(VendorCredentialsMissing) as caught,
    ):
        fetch_logo_dev_family("aws.amazon.com", secret_key="", client=client)
    assert caught.value.env_vars == ("LOGO_DEV_SECRET_KEY",)


@pytest.mark.parametrize(
    "status,code",
    [(202, "pending"), (401, "auth"), (402, "quota"), (403, "auth"), (429, "quota"), (500, "http")],
)
def test_provider_failures_are_typed_and_do_not_echo_response_secrets(status, code):
    from lumen_ingestion.logo_dev import fetch_logo_dev_family
    from lumen_ingestion.logo_vendor import VendorLookupFailed

    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(status, text="secret sk_fixture token=pk_fixture")
            )
        ) as client,
        pytest.raises(VendorLookupFailed) as caught,
    ):
        fetch_logo_dev_family("aws.amazon.com", secret_key="sk_fixture", client=client)
    assert caught.value.code == code
    assert "fixture" not in str(caught.value)


def test_not_found_is_an_empty_answer():
    from lumen_ingestion.logo_dev import fetch_logo_dev_family

    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(404))) as client:
        cells, extras, notes = fetch_logo_dev_family(
            "aws.amazon.com", secret_key="sk_fixture", client=client
        )
    assert cells == {}
    assert extras == []
    assert any("404" in note for note in notes)


@pytest.mark.parametrize("ink,expected", [("black", "light_lockup"), ("white", "dark_lockup")])
def test_only_the_observed_original_ink_fills_a_theme_cell(ink, expected):
    from lumen_ingestion.logo_dev import fetch_logo_dev_family

    body = _png(ink)
    profile = _profile()
    profile.pop("logo")
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (
                httpx.Response(200, json=profile)
                if request.url.host == "api.logo.dev"
                else httpx.Response(200, content=body, headers={"content-type": "image/png"})
            )
        )
    ) as client:
        cells, _, _ = fetch_logo_dev_family(
            "aws.amazon.com", secret_key="sk_fixture", client=client
        )
    assert set(cells) == {expected}
    assert cells[expected].body == body


@pytest.mark.parametrize(
    "asset",
    [_png(opaque=True), _png(empty=True), b"not-an-image"],
    ids=["opaque", "empty", "invalid"],
)
def test_nontransparent_empty_or_invalid_images_never_become_family_assets(asset):
    from lumen_ingestion.logo_dev import fetch_logo_dev_family

    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (
                httpx.Response(200, json=_profile())
                if request.url.host == "api.logo.dev"
                else httpx.Response(200, content=asset, headers={"content-type": "image/png"})
            )
        )
    ) as client:
        cells, extras, notes = fetch_logo_dev_family(
            "aws.amazon.com", secret_key="sk_fixture", client=client
        )
    assert cells == {}
    assert extras == []
    assert any("transparent" in note or "decode" in note for note in notes)


@pytest.mark.parametrize(
    "src",
    [
        "https://evil.invalid/a?token=pk_fixture",
        "http://img.logo.dev/aws.amazon.com?token=pk_fixture",
        "https://img.logo.dev.evil.invalid/aws.amazon.com?token=pk_fixture",
        "https://user:pass@img.logo.dev/aws.amazon.com?token=pk_fixture",
        "https://img.logo.dev:8000/aws.amazon.com?token=pk_fixture",
        "https://img.logo.dev/?token=pk_fixture",
        "https://img.logo.dev/aws.amazon.com",
        "https://img.logo.dev/amazon.com?token=pk_fixture",
        "https://img.logo.dev/brand/amazon.com/asset?token=pk_fixture",
        "https://img.logo.dev/brand/aws.amazon.com/../amazon.com?token=pk_fixture",
    ],
)
def test_invalid_asset_locations_are_not_fetched_or_disclosed(src):
    from lumen_ingestion.logo_dev import fetch_logo_dev_family

    profile = _profile()
    profile["brandmark"] = src
    profile.pop("logo")
    requests = []

    def serve(request):
        requests.append(request)
        return httpx.Response(200, json=profile)

    with httpx.Client(transport=httpx.MockTransport(serve)) as client:
        cells, extras, notes = fetch_logo_dev_family(
            "aws.amazon.com", secret_key="sk_fixture", client=client
        )
    assert cells == {}
    assert extras == []
    assert len(requests) == 1
    assert src not in str(notes)
    assert "pk_fixture" not in str(notes)


def test_cdn_redirect_cannot_escape_the_allowlist_even_with_redirecting_client():
    from lumen_ingestion.logo_dev import fetch_logo_dev_family

    requests = []

    def serve(request):
        requests.append(request)
        if request.url.host == "api.logo.dev":
            return httpx.Response(200, json=_profile())
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    with httpx.Client(transport=httpx.MockTransport(serve), follow_redirects=True) as client:
        cells, extras, _ = fetch_logo_dev_family(
            "aws.amazon.com", secret_key="sk_fixture", client=client
        )
    assert not cells and not extras
    assert {r.url.host for r in requests} == {"api.logo.dev", "img.logo.dev"}


def test_client_credentials_and_tokens_cannot_escape_via_downloads_or_logs(caplog):
    from lumen_ingestion.logo_dev import fetch_logo_dev_family

    caplog.set_level(logging.INFO, logger="httpx")
    asset_headers = []

    def serve(request):
        if request.url.host == "api.logo.dev":
            assert request.headers["authorization"] == "Bearer sk_fixture"
            return httpx.Response(200, json=_profile())
        asset_headers.append(request.headers)
        return httpx.Response(200, content=_png(), headers={"content-type": "image/png"})

    with httpx.Client(
        transport=httpx.MockTransport(serve),
        auth=("secret-user", "secret-password"),
        headers={"authorization": "Bearer unrelated-secret", "cookie": "secret-cookie"},
    ) as client:
        cells, extras, notes = fetch_logo_dev_family(
            "aws.amazon.com", secret_key="sk_fixture", client=client
        )
    assert cells
    assert all("authorization" not in h and "cookie" not in h for h in asset_headers)
    public = str(([c.origin_url for c in [*cells.values(), *extras]], notes)) + caplog.text
    assert "pk_fixture" not in public
    assert "sk_fixture" not in public
    assert "secret-password" not in public


@pytest.mark.parametrize(
    "error_type,code", [(httpx.ReadTimeout, "timeout"), (httpx.ConnectError, "http")]
)
def test_transport_exception_text_is_never_exposed(error_type, code):
    from lumen_ingestion.logo_dev import fetch_logo_dev_family
    from lumen_ingestion.logo_vendor import VendorLookupFailed

    def serve(request):
        raise error_type("Authorization: Bearer sk_fixture; token=pk_fixture", request=request)

    with (
        httpx.Client(transport=httpx.MockTransport(serve)) as client,
        pytest.raises(VendorLookupFailed) as caught,
    ):
        fetch_logo_dev_family("aws.amazon.com", secret_key="sk_fixture", client=client)
    assert caught.value.code == code
    assert "fixture" not in str(caught.value)


@pytest.mark.parametrize("payload", [[], {"name": "AWS"}])
def test_malformed_or_unverifiable_profiles_are_refused_before_download(payload):
    from lumen_ingestion.logo_dev import fetch_logo_dev_family
    from lumen_ingestion.logo_vendor import VendorLookupFailed

    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
        ) as client,
        pytest.raises(VendorLookupFailed) as caught,
    ):
        fetch_logo_dev_family("aws.amazon.com", secret_key="sk_fixture", client=client)
    assert caught.value.code in {"malformed", "identity_unverified"}


@pytest.mark.parametrize(
    "requested,name,returned,returned_name",
    [
        ("aws.amazon.com", "AWS", "amazon.com", "Amazon"),
        ("cloud.google.com", "Google Cloud", "google.com", "Google"),
        ("cloud.google.com", "Google Cloud", "cloud.google.com", "Google"),
    ],
)
def test_parent_company_profile_cannot_replace_the_requested_brand(
    requested, name, returned, returned_name
):
    from lumen_ingestion.logo_dev import fetch_logo_dev_family
    from lumen_ingestion.logo_vendor import VendorLookupFailed

    requests = []

    def serve(request):
        requests.append(request)
        return httpx.Response(200, json=_profile(returned, returned_name))

    with (
        httpx.Client(transport=httpx.MockTransport(serve)) as client,
        pytest.raises(VendorLookupFailed) as caught,
    ):
        fetch_logo_dev_family(requested, company_name=name, secret_key="sk_fixture", client=client)
    assert caught.value.code == "identity_mismatch"
    assert len(requests) == 1


def test_oversize_asset_stops_the_download_and_closes_the_stream():
    from lumen_ingestion.logo_dev import fetch_logo_dev_family

    class Oversize(httpx.SyncByteStream):
        read_past_limit = False
        closed = False

        def __iter__(self):
            yield b"x" * (15 * 1024 * 1024 + 1)
            self.read_past_limit = True
            yield b"more"

        def close(self):
            self.closed = True

    body = Oversize()
    profile = _profile()
    profile.pop("logo")
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (
                httpx.Response(200, json=profile)
                if request.url.host == "api.logo.dev"
                else httpx.Response(200, stream=body, headers={"content-type": "image/png"})
            )
        )
    ) as client:
        cells, extras, notes = fetch_logo_dev_family(
            "aws.amazon.com", secret_key="sk_fixture", client=client
        )
    assert not cells and not extras
    assert not body.read_past_limit
    assert body.closed
    assert any("size" in note for note in notes)


def test_malformed_json_is_a_typed_degrade():
    from lumen_ingestion.logo_dev import fetch_logo_dev_family
    from lumen_ingestion.logo_vendor import VendorLookupFailed

    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=b"not-json sk_fixture")
            )
        ) as client,
        pytest.raises(VendorLookupFailed) as caught,
    ):
        fetch_logo_dev_family("aws.amazon.com", secret_key="sk_fixture", client=client)
    assert caught.value.code == "malformed"
    assert "fixture" not in str(caught.value)


def test_asset_auth_failures_leave_a_safe_partial_family():
    from lumen_ingestion.logo_dev import fetch_logo_dev_family

    def serve(request):
        if request.url.host == "api.logo.dev":
            return httpx.Response(200, json=_profile())
        if "/brand/" in request.url.path:
            return httpx.Response(401, text="token=pk_fixture")
        return httpx.Response(200, content=_png(), headers={"content-type": "image/png"})

    with httpx.Client(transport=httpx.MockTransport(serve)) as client:
        cells, extras, notes = fetch_logo_dev_family(
            "aws.amazon.com", secret_key="sk_fixture", client=client
        )
    assert not cells
    assert len(extras) == 1
    assert any("401" in note for note in notes)
    assert "pk_fixture" not in str(notes)


def test_server_transform_parameters_are_overridden_without_changing_colors():
    from lumen_ingestion.logo_dev import fetch_logo_dev_family

    profile = _profile()
    profile.pop("logo")
    profile["brandmark"] += "&theme=dark&theme=light&greyscale=true&fallback=monogram"
    body = _png("#18a580")

    def serve(request):
        if request.url.host == "api.logo.dev":
            return httpx.Response(200, json=profile)
        assert request.url.params.get_list("theme") == ["auto"]
        assert request.url.params.get_list("greyscale") == ["false"]
        assert request.url.params.get_list("fallback") == ["404"]
        return httpx.Response(200, content=body, headers={"content-type": "image/png"})

    with httpx.Client(transport=httpx.MockTransport(serve)) as client:
        cells, _, _ = fetch_logo_dev_family(
            "aws.amazon.com", secret_key="sk_fixture", client=client
        )
    assert cells["light_lockup"].body == body


@pytest.mark.parametrize("domain", ["", "https://[broken", "https://user:password@aws.amazon.com"])
def test_invalid_domains_degrade_before_spending_a_request(domain):
    from lumen_ingestion.logo_dev import fetch_logo_dev_family
    from lumen_ingestion.logo_vendor import VendorLookupFailed

    def unexpected(request):
        pytest.fail("invalid input must not spend a provider request")

    with (
        httpx.Client(transport=httpx.MockTransport(unexpected)) as client,
        pytest.raises(VendorLookupFailed) as caught,
    ):
        fetch_logo_dev_family(domain, secret_key="sk_fixture", client=client)
    assert caught.value.code == "http"
    assert "password" not in str(caught.value)


def test_exact_domain_normalization_uses_the_shared_identity_rules():
    from lumen_ingestion.logo_dev import fetch_logo_dev_family

    profile = _profile()
    profile.pop("logo")

    def serve(request):
        if request.url.host == "api.logo.dev":
            assert request.url.path == "/brand/aws.amazon.com"
            return httpx.Response(200, json=profile)
        return httpx.Response(200, content=_png(), headers={"content-type": "image/png"})

    with httpx.Client(transport=httpx.MockTransport(serve)) as client:
        cells, _, _ = fetch_logo_dev_family(
            " //www.AWS.amazon.com./ ", secret_key="sk_fixture", client=client
        )
    assert cells["light_lockup"].evidence["vendor_identity"]["requested_domain"] == "aws.amazon.com"
