"""find_handles: PDL for X and Facebook, a same-handle Instagram check; all are candidates."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

from pydantic import SecretStr

from clue_api.footprint.handles import HandleCandidate, find_handles
from clue_api.footprint.pdl_client import pdl_person
from clue_api.footprint.social_video import x_video_file
from clue_config.secrets import Secrets
from clue_spend.calls import ProviderCaller
from clue_spend.sinks import MemoryLedger, MemoryRawSink
from clue_spend.transport import HttpResponse, ScriptedTransport

TOKEN, PDL = SecretStr("t"), SecretStr("p")


def wire(*responses):
    transport = ScriptedTransport(list(responses))
    ledger = MemoryLedger()
    caller = ProviderCaller(
        transport=transport,
        raw_sink=MemoryRawSink(),
        ledger=ledger,
        now=lambda: datetime.now(UTC),
        sleep=lambda _: None,
    )
    return caller, transport, ledger


def reply(value, status=200, micro="1880"):
    return HttpResponse(
        status,
        {"content-type": "application/json", "X-Treg-Cost-Micro": micro},
        json.dumps(value).encode(),
    )


PDL_MATCH = {
    "status": 200,
    "likelihood": 9,
    "data": {
        "twitter_username": "adaex",
        "twitter_url": "twitter.com/adaex",
        "facebook_username": "ada.example",
        "facebook_url": "facebook.com/ada.example",
    },
}


def ig_profile(private, bio="CISO at Acme"):
    return {"data": {"user": {"is_private": private, "biography": bio, "full_name": "Ada Example"}}}


def q(request):
    return {k: v[0] for k, v in parse_qs(urlsplit(request.url).query).items()}


def test_handles_are_candidates_with_source():
    caller, transport, _ = wire(
        reply(PDL_MATCH),
        reply(ig_profile(False)),  # ada-example (LinkedIn id)
        reply({"message": "User not found"}, 404, "0"),  # adaex
        reply({"message": "User not found"}, 404, "0"),  # ada.example
    )
    found = find_handles(
        caller,
        TOKEN,
        PDL,
        name="Ada Example",
        company="Acme",
        linkedin_url="https://www.linkedin.com/in/ada-example/",
    )
    assert all(isinstance(h, HandleCandidate) for h in found)
    assert [(h.platform, h.handle, h.source) for h in found] == [
        ("x", "adaex", "pdl"),
        ("facebook", "ada.example", "pdl"),
        ("instagram", "ada-example", "same_handle"),
    ]
    assert found[2].bio == "CISO at Acme" and found[2].private is False
    pdl_query = q(transport.requests[0])
    assert pdl_query["profile"] == "https://www.linkedin.com/in/ada-example/"
    assert transport.requests[0].headers["X-Api-Key"] == "p"


def test_private_instagram_marked():
    caller, *_ = wire(reply(ig_profile(True)))
    found = find_handles(
        caller, TOKEN, None, name="Ada", company=None, linkedin_url="https://linkedin.com/in/ada"
    )
    assert found == [
        HandleCandidate(
            platform="instagram",
            handle="ada",
            url="https://www.instagram.com/ada/",
            source="same_handle",
            private=True,
            bio="CISO at Acme",
        )
    ]


def test_no_pdl_key_returns_instagram_only():
    caller, transport, _ = wire(reply({"message": "User not found"}, 404, "0"))
    found = find_handles(
        caller, TOKEN, None, name="Ada", company=None, linkedin_url="https://linkedin.com/in/ada"
    )
    assert found == [] and len(transport.requests) == 1


def test_pdl_no_match_is_none_and_costs_nothing():
    caller, _, ledger = wire(
        HttpResponse(404, {"content-type": "application/json"}, b'{"status":404}')
    )
    assert pdl_person(caller, PDL, name="Ada", company="Acme", linkedin_url=None) is None
    result = [r for r in ledger.rows if r.phase == "result"][0]
    assert not result.cost_usd


def test_pdl_match_is_priced():
    caller, _, ledger = wire(
        HttpResponse(200, {"content-type": "application/json"}, json.dumps(PDL_MATCH).encode())
    )
    assert (
        pdl_person(caller, PDL, name="Ada", company="Acme", linkedin_url=None) == PDL_MATCH["data"]
    )
    result = [r for r in ledger.rows if r.phase == "result"][0]
    assert float(result.cost_usd) == 0.28


def test_x_post_link_gives_its_best_mp4():
    tweet = {
        "legacy": {
            "extended_entities": {
                "media": [
                    {
                        "video_info": {
                            "variants": [
                                {
                                    "content_type": "video/mp4",
                                    "bitrate": 256000,
                                    "url": "https://video.twimg.com/low.mp4",
                                },
                                {
                                    "content_type": "video/mp4",
                                    "bitrate": 2176000,
                                    "url": "https://video.twimg.com/high.mp4",
                                },
                                {
                                    "content_type": "application/x-mpegURL",
                                    "url": "https://video.twimg.com/pl.m3u8",
                                },
                            ]
                        }
                    }
                ]
            }
        }
    }
    caller, transport, _ = wire(reply(tweet))
    assert (
        x_video_file(caller, TOKEN, "https://x.com/ada/status/123")
        == "https://video.twimg.com/high.mp4"
    )
    assert "scrapecreators.x.v1-twitter-tweet" in transport.requests[0].url


def test_x_post_without_video_is_none():
    caller, *_ = wire(reply({"legacy": {"full_text": "no video"}}))
    assert x_video_file(caller, TOKEN, "https://x.com/ada/status/123") is None


def test_pdl_key_loads_from_either_name(monkeypatch):
    monkeypatch.setenv("PDL_API_KEY", "shared")
    assert Secrets(_env_file=None).pdl_api_key.get_secret_value() == "shared"
    monkeypatch.setenv("CLUE_PDL_API_KEY", "ours")
    assert Secrets(_env_file=None).pdl_api_key.get_secret_value() == "ours"


def test_treg_out_of_credit_keeps_the_pdl_handles():
    """treg stopping selling during the Instagram check leaves the X and Facebook candidates PDL
    already found, and the remaining Instagram checks are not sent."""
    out_of_credit = HttpResponse(
        402,
        {"content-type": "application/json", "X-Treg-Error": "1"},
        b'{"detail": "insufficient_balance"}',
    )
    caller, transport, _ = wire(reply(PDL_MATCH), out_of_credit)
    found = find_handles(
        caller,
        TOKEN,
        PDL,
        name="Ada Example",
        company="Acme",
        linkedin_url="https://www.linkedin.com/in/ada-example/",
    )
    assert [(h.platform, h.handle) for h in found] == [("x", "adaex"), ("facebook", "ada.example")]
    assert len(transport.requests) == 2
