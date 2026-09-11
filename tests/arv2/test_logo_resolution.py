"""The mark-type logo rule (founder rulings 2026-09-11) and the Brandfetch hop.

Fixture URLs are the shapes the proof of concept measured over the first Insight Health run:
LinkedIn company marks (kept), site-hosted banners and photos (dropped), LinkedIn's default
placeholder (dropped), and Brand API payloads with and without an ``icon``.
"""

from __future__ import annotations

import json

import pytest
from pydantic import SecretStr

from clue_api.arv2.calls import ProviderCaller
from clue_api.arv2.logo_resolution import (
    BrandfetchClient,
    brandfetch_halt_rule,
    icon_from_brand,
    websets_mark_url,
)
from clue_api.arv2.transport import HttpResponse, ScriptedTransport

from .test_exa_websets_client import _caller

MARK = "https://media.licdn.com/dms/image/v2/C4E0BAQFVxTYC/company-logo_200_200/0?e=2147483647"


@pytest.mark.parametrize(
    ("url", "kept"),
    [
        (MARK, True),
        ("https://www.inova.org/themes/custom/inova_public/img/inova-opengraph.jpg", False),
        ("https://www.southern-ortho.com/wp-content/uploads/2024/08/s-o-team.jpg", False),
        ("https://static.licdn.com/aero-v1/sc/h/cs8pjfgyw96g44ln9r7tct85f", False),
        ("http://media.licdn.com/dms/image/company-logo_200_200/0", False),
        (None, False),
        ("", False),
    ],
)
def test_only_a_linkedin_company_mark_is_kept_from_websets(url: str | None, kept: bool) -> None:
    assert (websets_mark_url(url) == url) is kept if kept else websets_mark_url(url) is None


def test_the_icon_is_taken_from_a_brand_payload_and_a_wordmark_never_substitutes() -> None:
    brand = {
        "logos": [
            {
                "type": "logo",
                "formats": [{"format": "png", "width": 318, "src": "https://cdn/logo.png"}],
            },
            {
                "type": "icon",
                "formats": [
                    {"format": "svg", "src": "https://cdn/icon.svg"},
                    {"format": "png", "width": 400, "src": "https://cdn/icon-400.png"},
                    {"format": "jpeg", "width": 704, "src": "https://cdn/icon-704.jpeg"},
                ],
            },
        ]
    }
    # The largest raster that fits the screens' ceiling wins; SVG is never streamed.
    assert icon_from_brand(brand) == "https://cdn/icon-400.png"
    wordmark_only = {"logos": [brand["logos"][0]]}
    assert icon_from_brand(wordmark_only) is None
    assert icon_from_brand({}) is None
    # Only oversized rasters: the smallest of them, still a mark.
    big = {
        "logos": [
            {
                "type": "icon",
                "formats": [
                    {"format": "jpeg", "width": 704, "src": "https://cdn/704.jpeg"},
                    {"format": "png", "width": 1024, "src": "https://cdn/1024.png"},
                ],
            }
        ]
    }
    assert icon_from_brand(big) == "https://cdn/704.jpeg"


def test_the_brandfetch_hop_reads_the_icon_and_treats_404_as_no_brand() -> None:
    payload = {
        "logos": [
            {
                "type": "icon",
                "formats": [
                    {"format": "png", "width": 400, "src": "https://cdn.brandfetch.io/idY/icon.png"}
                ],
            }
        ]
    }
    caller, transport = _caller(
        [
            HttpResponse(
                status=200,
                headers={"content-type": "application/json"},
                body=json.dumps(payload).encode(),
            ),
            HttpResponse(status=404, headers={"content-type": "application/json"}, body=b"{}"),
        ]
    )
    client = BrandfetchClient(caller, api_key=SecretStr("k"), base_url="https://api.brandfetch.io")
    assert client.icon_url("inova.org", label="logo:inova.org") == (
        "https://cdn.brandfetch.io/idY/icon.png"
    )
    assert client.icon_url("nobody.example", label="logo:nobody.example") is None
    sent = transport.requests
    assert sent[0].url == "https://api.brandfetch.io/v2/brands/inova.org"
    assert sent[0].headers["authorization"] == "Bearer k"


def test_halt_rule_names_credential_and_quota_refusals_only() -> None:
    assert brandfetch_halt_rule(HttpResponse(status=401)) == "brandfetch_unauthorized"
    assert brandfetch_halt_rule(HttpResponse(status=429)) == "brandfetch_quota"
    assert brandfetch_halt_rule(HttpResponse(status=404)) is None
    assert brandfetch_halt_rule(HttpResponse(status=200)) is None


def test_provider_caller_import_is_the_lane_seam() -> None:
    assert ProviderCaller is not None and ScriptedTransport is not None
