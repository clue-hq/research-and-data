from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient

from clue_design.publishes import DELIVERY_CSP_HEADER

from .conftest import HOST, WS, FakePageReads, edge


def test_serves_the_active_publish_with_the_exact_headers(
    client: TestClient, reads: FakePageReads
) -> None:
    reads.publish("annual-report", "<html>hi</html>")
    response = client.get("/annual-report", headers=edge())
    assert response.status_code == 200
    assert response.text == "<html>hi</html>"
    digest = hashlib.sha256(b"<html>hi</html>").hexdigest()
    assert response.headers["cache-control"] == "public, max-age=60, must-revalidate"
    assert response.headers["etag"] == f'"sha256-{digest}"'
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert response.headers["content-security-policy"] == DELIVERY_CSP_HEADER
    assert "x-robots-tag" not in response.headers
    assert "access-control-allow-origin" not in response.headers


def test_noindex_pages_carry_x_robots_tag(client: TestClient, reads: FakePageReads) -> None:
    reads.publish("abm-acme", "<html>x</html>", noindex=True)
    assert client.get("/abm-acme", headers=edge()).headers["x-robots-tag"] == "noindex"


def test_manifest(client: TestClient, reads: FakePageReads) -> None:
    reads.publish("annual-report", "<html>hi</html>")
    response = client.get("/annual-report/manifest.json", headers=edge())
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["slug"] == "annual-report"
    assert response.headers["cache-control"] == "public, max-age=60, must-revalidate"


def test_unknown_hostname_pending_hostname_and_unknown_slug_are_404(
    client: TestClient, reads: FakePageReads
) -> None:
    reads.publish("annual-report", "<html>hi</html>")
    assert client.get("/annual-report", headers=edge("nobody.example")).status_code == 404
    assert client.get("/missing", headers=edge()).status_code == 404
    page = client.get("/missing", headers=edge())
    assert "<title>Not found</title>" in page.text
    assert WS not in page.text and HOST not in page.text
    assert page.headers["x-robots-tag"] == "noindex"


def test_root_and_unknown_slug_redirect_to_the_fallback_url(
    client: TestClient, reads: FakePageReads
) -> None:
    reads.fallbacks[WS] = "https://www.acme.com"
    for path in ("/", "/missing"):
        response = client.get(path, headers=edge(), follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "https://www.acme.com"
    reads.fallbacks.clear()
    assert client.get("/", headers=edge()).status_code == 404


def test_slug_pattern_is_enforced_before_any_lookup(
    client: TestClient, reads: FakePageReads
) -> None:
    reads.publish("annual-report", "<html>hi</html>")
    for bad in ("/Annual-Report", "/-lead", "/" + "a" * 73, "/annual_report"):
        assert client.get(bad, headers=edge()).status_code == 404


def test_favicon_404_when_none_and_served_when_set(
    client: TestClient, reads: FakePageReads
) -> None:
    assert client.get("/favicon.ico", headers=edge()).status_code == 404
    reads.favicons[WS] = ("image/png", b"\x89PNG")
    response = client.get("/favicon.ico", headers=edge())
    assert response.status_code == 200 and response.content == b"\x89PNG"
    assert response.headers["cache-control"] == "public, max-age=300"


def test_publish_assets_are_integrity_checked_and_immutable(
    client: TestClient, reads: FakePageReads
) -> None:
    data = b"console.log(1)"
    digest = hashlib.sha256(data).hexdigest()
    reads.assets[(WS, digest)] = ("text/javascript; charset=utf-8", data)
    response = client.get(f"/p-assets/{digest}.js", headers=edge())
    assert response.status_code == 200 and response.content == data
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert response.headers["etag"] == f'"sha256-{digest}"'
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "access-control-allow-origin" not in response.headers
    assert client.get(f"/p-assets/{digest}.css", headers=edge()).status_code == 404  # ext mismatch
    assert client.get(f"/p-assets/{'0' * 64}.js", headers=edge()).status_code == 404
    assert client.get("/p-assets/not-a-digest.js", headers=edge()).status_code == 404


def test_asset_store_is_workspace_unscoped(client: TestClient, reads: FakePageReads) -> None:
    data = b"font-bytes"
    digest = hashlib.sha256(data).hexdigest()
    reads.public[digest] = ("font/woff2", data)
    response = client.get(f"/asset-store/{digest}", headers=edge())
    assert response.status_code == 200 and response.headers["content-type"] == "font/woff2"
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert client.get("/asset-store/zzz", headers=edge()).status_code == 404


def test_only_get_and_head(client: TestClient, reads: FakePageReads) -> None:
    reads.publish("annual-report", "<html>hi</html>")
    assert client.post("/annual-report", headers=edge()).status_code == 405
    head = client.head("/annual-report", headers=edge())
    assert head.status_code == 200 and head.content == b""
