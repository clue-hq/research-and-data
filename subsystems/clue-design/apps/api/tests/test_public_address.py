"""The public address of a published site — config first, interim path scheme as the fallback.

Founder ruling R-F5-1: the origin a published site is served from is CONFIGURATION, never a
constant compiled into the API or the editor. `LUMEN_PUBLIC_PAGES_HOST_SUFFIX` blank (the dev
default, and the only setting that exists until DNS + TLS are provisioned) keeps the interim
`/w/{workspace}/p/{slug}` path scheme exactly as it was; setting it moves every site onto its
own host — but only for a site whose workspace actually HAS a handle to put in front of it.

These are pure function tests: no app, no client, no database. `public_site_address` reads its
environment at CALL time, so `monkeypatch.setenv` works regardless of import order.
"""

from __future__ import annotations

import pytest

from lumen_api.public_address import PublicSiteAddress, public_site_address


@pytest.fixture(autouse=True)
def _clean_pages_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neither key is set in a developer's shell; do not inherit one from the runner's."""

    monkeypatch.delenv("LUMEN_PUBLIC_PAGES_HOST_SUFFIX", raising=False)
    monkeypatch.delenv("LUMEN_PUBLIC_PAGES_SCHEME", raising=False)


def test_interim_address_when_no_host_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LUMEN_PUBLIC_PAGES_HOST_SUFFIX", raising=False)
    address = public_site_address(
        request_base_url="http://127.0.0.1:8010/",
        workspace_id="ws1",
        slug="site",
        handle="acme",
    )
    assert address.page_url("/") == "http://127.0.0.1:8010/w/ws1/p/site"
    assert address.page_url("/pricing") == "http://127.0.0.1:8010/w/ws1/p/site/pricing"


def test_host_address_when_suffix_and_handle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LUMEN_PUBLIC_PAGES_HOST_SUFFIX", "pages.cluehq.ai")
    monkeypatch.setenv("LUMEN_PUBLIC_PAGES_SCHEME", "https")
    address = public_site_address(
        request_base_url="http://127.0.0.1:8010/",
        workspace_id="ws1",
        slug="site",
        handle="acme",
    )
    assert address.page_url("/") == "https://acme.pages.cluehq.ai/site"
    assert address.page_url("/pricing") == "https://acme.pages.cluehq.ai/site/pricing"
    assert (
        public_site_address(
            request_base_url="http://x/", workspace_id="ws1", slug="s", handle=None
        ).origin
        == "http://x"
    )


def test_host_mode_needs_a_handle_not_just_a_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both halves, or interim. A blank/whitespace handle is not a subdomain."""

    monkeypatch.setenv("LUMEN_PUBLIC_PAGES_HOST_SUFFIX", "pages.cluehq.ai")
    for handle in (None, "", "   "):
        address = public_site_address(
            request_base_url="http://127.0.0.1:8010/",
            workspace_id="ws1",
            slug="site",
            handle=handle,
        )
        assert address.host_mode is False
        assert address.page_url("/") == "http://127.0.0.1:8010/w/ws1/p/site"


def test_blank_suffix_is_interim_even_with_a_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUMEN_PUBLIC_PAGES_HOST_SUFFIX", "   ")
    address = public_site_address(
        request_base_url="http://127.0.0.1:8010/",
        workspace_id="ws1",
        slug="site",
        handle="acme",
    )
    assert address.host_mode is False
    assert address.site_path == "/w/ws1/p/site"


def test_scheme_defaults_to_https_and_is_overridable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUMEN_PUBLIC_PAGES_HOST_SUFFIX", "pages.local")
    default = public_site_address(
        request_base_url="http://x/", workspace_id="ws1", slug="s", handle="acme"
    )
    assert default.origin == "https://acme.pages.local"
    monkeypatch.setenv("LUMEN_PUBLIC_PAGES_SCHEME", "http")
    overridden = public_site_address(
        request_base_url="http://x/", workspace_id="ws1", slug="s", handle="acme"
    )
    assert overridden.origin == "http://acme.pages.local"


def test_asset_base_keeps_the_workspace_prefix_only_in_interim_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`/p-assets` is workspace-scoped on the shared interim origin and bare on a site host."""

    interim = public_site_address(
        request_base_url="http://127.0.0.1:8010/",
        workspace_id="ws1",
        slug="site",
        handle="acme",
    )
    assert interim.asset_origin == "http://127.0.0.1:8010"
    assert interim.asset_base("ws1") == "http://127.0.0.1:8010/w/ws1"

    monkeypatch.setenv("LUMEN_PUBLIC_PAGES_HOST_SUFFIX", "pages.cluehq.ai")
    hosted = public_site_address(
        request_base_url="http://127.0.0.1:8010/",
        workspace_id="ws1",
        slug="site",
        handle="acme",
    )
    assert hosted.asset_origin == "https://acme.pages.cluehq.ai"
    assert hosted.asset_base("ws1") == "https://acme.pages.cluehq.ai"


def test_the_address_is_frozen() -> None:
    address = public_site_address(
        request_base_url="http://x/", workspace_id="ws1", slug="s", handle=None
    )
    assert isinstance(address, PublicSiteAddress)
    with pytest.raises(Exception):
        address.origin = "http://elsewhere"  # type: ignore[misc]
