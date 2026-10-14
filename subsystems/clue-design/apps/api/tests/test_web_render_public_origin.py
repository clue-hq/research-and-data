"""The origin written into served web markup is the one a BROWSER can reach.

Behind the platform's server-side proxy the design API's ``request.base_url`` is its private
service host, so image and kit-font URLs derived from it were unreachable from the browser
(production, 2026-10-14: seeded web pages rendered broken images and fallback fonts).
``LUMEN_API_ORIGIN`` names the public origin and wins when set; the request's own base stays
the dev-stack behaviour, where the browser reaches the API directly.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from lumen_api.main import public_api_origin


def _request(base_url: str) -> SimpleNamespace:
    return SimpleNamespace(base_url=base_url)


def test_configured_public_origin_wins_over_the_request_base(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LUMEN_API_ORIGIN", "https://app.example.test/api/clue/design-public/")
    origin = public_api_origin(_request("http://design-api.railway.internal:8010/"))
    assert origin == "https://app.example.test/api/clue/design-public"
    assert origin + "/asset-store/" + "a" * 64 == (
        "https://app.example.test/api/clue/design-public/asset-store/" + "a" * 64
    )


def test_request_base_is_used_when_no_public_origin_is_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("LUMEN_API_ORIGIN", raising=False)
    assert public_api_origin(_request("http://127.0.0.1:8012/")) == "http://127.0.0.1:8012"


def test_blank_public_origin_counts_as_unset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LUMEN_API_ORIGIN", "   ")
    assert public_api_origin(_request("http://127.0.0.1:8012/")) == "http://127.0.0.1:8012"
