"""The asset library's Logo search (`lumen_api/logo_search.py` + the two `/assets/logo-search`
routes): every version the shared lookup found comes back as an inline preview and nothing is
saved, then the ONE version the person clicks is registered as a workspace asset.

The lookup itself (Brandfetch + the ladder + the arbiter + the cache) has its own suites; here it
is replaced by a fixed family so the routes are exercised without the network.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import make_client
from lumen_agent.tools import logo_fetch
from lumen_agent.tools.logo_fetch import LogoFetchOutcome, PreparedLogo
from lumen_api import logo_search
from lumen_api.main import create_app
from lumen_ingestion.capture.net import CaptureError


def _svg(fill: str) -> bytes:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 10">'
        f'<rect width="40" height="10" fill="{fill}"/></svg>'
    ).encode()


def _prepared(cell: str, source: str, fill: str, *, evidence: dict | None = None) -> PreparedLogo:
    import hashlib

    body = _svg(fill)
    return PreparedLogo(
        cell=cell,
        source=source,
        asset_id=f"asset_ing_{hashlib.sha256(body).hexdigest()[:16]}",
        label=f"stripe.com logo ({cell})",
        body=body,
        content_type="image/svg+xml",
        provenance={"created_by": "brandfetch" if source == "brandfetch" else "logo_ladder",
                    "source_label": "brandfetch" if source == "brandfetch" else "website",
                    "confidence": 0.9},
        source_ref={"kind": "website", "url": "https://stripe.com/img/logo.svg", "captured_at": None},
        evidence={"cell": cell, "source": source, **(evidence or {})},
    )


def _family() -> LogoFetchOutcome:
    return LogoFetchOutcome(
        status="ok",
        site="https://stripe.com/",
        company=None,
        # Deliberately out of display order: the payload sorts cells into the tile order.
        prepared=[
            _prepared("light_mark", "brandfetch", "#635bff"),
            _prepared("light_lockup", "brandfetch", "#635bff"),
            _prepared("dark_lockup", "ladder", "#ffffff"),
        ],
        alternatives=[_prepared("unclassified", "brandfetch", "#0a2540", evidence={"vendor_type": "icon"})],
    )


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return make_client(create_app(tmp_path / "engine-cache"))


def test_payload_names_every_version_in_tile_order_with_a_preview() -> None:
    payload = logo_search.search_payload(_family(), query="stripe.com")

    assert payload["name"] == "stripe.com"
    assert [(logo["kind"], logo["background"], logo["source"]) for logo in payload["logos"]] == [
        ("Full logo", "light", "Brandfetch"),
        ("Full logo", "dark", "Website"),
        ("Icon", "light", "Brandfetch"),
        # An alternative that competed for no cell claims no background.
        ("Icon", None, "Brandfetch"),
    ]
    first = payload["logos"][0]
    assert first["preview"].startswith("data:image/svg+xml;base64,")
    assert base64.b64decode(first["preview"].split(",", 1)[1]) == _svg("#635bff")


def test_payload_for_nothing_found_is_an_empty_list() -> None:
    assert logo_search.search_payload(None, query="nowhere.example") == {
        "query": "nowhere.example", "name": None, "logos": [],
    }


def test_search_then_save_registers_only_the_clicked_version(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def fake_fetch(url: str, **kwargs):
        calls.append(url)
        return _family()

    monkeypatch.setattr(logo_fetch, "fetch_logo_family", fake_fetch)

    searched = client.post("/assets/logo-search", json={"url": "stripe.com"})
    assert searched.status_code == 200, searched.text
    logos = searched.json()["logos"]
    assert len(logos) == 4

    found_ids = {logo["asset_id"] for logo in logos}

    def registered_ids() -> set[str]:
        listed = client.get("/assets", params={"kind": "vector", "limit": 200})
        assert listed.status_code == 200, listed.text
        return {asset["id"] for asset in listed.json()["assets"]} & found_ids

    # The search saved nothing: none of the versions is in the workspace registry.
    assert registered_ids() == set()

    chosen = logos[1]
    saved = client.post(
        "/assets/logo-search/save", json={"url": "stripe.com", "asset_id": chosen["asset_id"]}
    )
    assert saved.status_code == 200, saved.text
    record = saved.json()["asset"]
    assert record["id"] == chosen["asset_id"]
    assert "logo-ladder" in record["tags"]
    assert record["source"]["kind"] == "website"

    served = client.get(f"/assets/{record['id']}/bytes")
    assert served.status_code == 200
    assert served.content == _svg("#ffffff")

    # Only the clicked version was registered.
    assert registered_ids() == {chosen["asset_id"]}

    # Saving it again converges on the same row instead of failing or duplicating.
    again = client.post(
        "/assets/logo-search/save", json={"url": "stripe.com", "asset_id": chosen["asset_id"]}
    )
    assert again.status_code == 200, again.text
    assert again.json()["asset"]["id"] == record["id"]
    assert calls == ["stripe.com", "stripe.com", "stripe.com"]


def test_save_of_a_version_the_lookup_no_longer_returns_is_refused(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(logo_fetch, "fetch_logo_family", lambda url, **kwargs: _family())

    response = client.post(
        "/assets/logo-search/save", json={"url": "stripe.com", "asset_id": "asset_ing_0000000000000000"}
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "logo_search.stale"


def test_an_unreachable_site_is_an_empty_result_not_an_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unreachable(url: str, **kwargs):
        raise CaptureError("LUMI0503", "the page could not be fetched")

    monkeypatch.setattr(logo_fetch, "fetch_logo_family", unreachable)

    response = client.post("/assets/logo-search", json={"url": "some-startup.io"})
    assert response.status_code == 200, response.text
    assert response.json()["logos"] == []


def test_a_url_with_no_host_is_refused_in_plain_words(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def bad(url: str, **kwargs):
        raise ValueError("could not read a host")

    monkeypatch.setattr(logo_fetch, "fetch_logo_family", bad)

    response = client.post("/assets/logo-search", json={"url": "https://"})
    assert response.status_code == 422
    assert response.json()["detail"]["message"] == "Enter a website, like stripe.com."
