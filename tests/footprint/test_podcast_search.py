"""find_podcasts: Apple and Podcast Index episodes in one list, nothing dropped (bodies made up)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from pydantic import SecretStr

from clue_api.footprint.media_sources import MediaSourceKeys
from clue_api.footprint.podcast_search import EpisodeLead, find_podcasts
from clue_spend.calls import ProviderCaller
from clue_spend.sinks import MemoryLedger, MemoryRawSink
from clue_spend.transport import HttpResponse, ScriptedTransport

KEYS = MediaSourceKeys(podcast_index_key=SecretStr("k"), podcast_index_secret=SecretStr("s"))


def wire(*responses):
    transport = ScriptedTransport(list(responses))
    caller = ProviderCaller(
        transport=transport,
        raw_sink=MemoryRawSink(),
        ledger=MemoryLedger(),
        now=lambda: datetime.now(UTC),
        sleep=lambda _: None,
    )
    return caller, transport


def ok(value):
    return HttpResponse(200, {"content-type": "application/json"}, json.dumps(value).encode())


def apple_episode(title, desc, date, *, show="Show A", feed=None, cid=11):
    return {
        "trackName": title,
        "collectionName": show,
        "releaseDate": date,
        "description": desc,
        "episodeUrl": f"https://audio.example/{title}.mp3",
        "feedUrl": feed,
        "collectionId": cid,
        "trackViewUrl": f"https://podcasts.apple.com/ep/{title}",
    }


def pi_episode(title, desc, stamp, *, show="Show A", feed="https://feeds.example/a.xml"):
    return {
        "title": title,
        "feedTitle": show,
        "datePublished": stamp,
        "description": desc,
        "enclosureUrl": f"https://audio.example/{title}.mp3",
        "feedUrl": feed,
        "link": f"https://showa.example/{title}",
        "transcriptUrl": "https://showa.example/t.vtt",
    }


def script(apple_eps, pi_eps, pi_feeds=(), lookups=()):
    return [
        ok({"results": apple_eps}),
        ok({"items": pi_eps}),
        ok({"feeds": list(pi_feeds)}),
        *[ok({"results": [{"feedUrl": f}]}) for f in lookups],
    ]


def test_podcasts_merge_duplicates_across_sources():
    caller, transport = wire(
        *script(
            [
                apple_episode(
                    "Zero trust at scale",
                    "Ada Example of Acme joins",
                    "2025-03-01T00:00:00Z",
                    feed="https://feeds.example/a.xml",
                )
            ],
            [pi_episode("Zero trust at scale", "Ada Example of Acme joins", 1740787200)],
        )
    )
    leads, gaps = find_podcasts(caller, KEYS, "Ada Example", "Acme")
    assert gaps == []
    assert len(leads) == 1 and isinstance(leads[0], EpisodeLead)
    lead = leads[0]
    assert sorted(lead.sources) == ["apple", "podcast_index"]
    assert lead.transcript_url == "https://showa.example/t.vtt"
    assert lead.feed_url == "https://feeds.example/a.xml"
    urls = [r.url for r in transport.requests]
    assert "entity=podcastEpisode" in urls[0]
    assert "search/byperson" in urls[1] and "search/byterm" in urls[2]


def test_podcasts_naming_results_first_and_missing_feed_filled():
    caller, _ = wire(
        *script(
            [
                apple_episode("Newest, unrelated", "cooking", "2026-01-01T00:00:00Z", cid=1),
                apple_episode("Older with Ada Example", "Acme CISO", "2024-01-01T00:00:00Z", cid=2),
            ],
            [],
            lookups=["https://feeds.example/one.xml", "https://feeds.example/two.xml"],
        )
    )
    leads, _ = find_podcasts(caller, KEYS, "Ada Example", "Acme")
    assert [lead.title for lead in leads] == ["Older with Ada Example", "Newest, unrelated"]
    assert leads[0].names_match and not leads[1].names_match
    assert {lead.feed_url for lead in leads} == {
        "https://feeds.example/one.xml",
        "https://feeds.example/two.xml",
    }


def test_podcasts_never_dropped():
    caller, _ = wire(
        *script([apple_episode("No mention", "gardening", "2025-01-01T00:00:00Z", feed="f")], [])
    )
    leads, _ = find_podcasts(caller, KEYS, "Ada Example", None)
    assert [lead.title for lead in leads] == ["No mention"]


def test_shows_from_byterm_are_leads_too():
    caller, _ = wire(
        *script(
            [],
            [],
            pi_feeds=[
                {
                    "title": "The Ada Example Show",
                    "url": "https://feeds.example/ada.xml",
                    "description": "hosted by Ada Example",
                }
            ],
        )
    )
    leads, _ = find_podcasts(caller, KEYS, "Ada Example", None)
    assert leads[0].kind == "show" and leads[0].feed_url == "https://feeds.example/ada.xml"


def test_without_podcast_index_keys_apple_only_and_gap():
    caller, transport = wire(ok({"results": []}))
    leads, gaps = find_podcasts(caller, MediaSourceKeys(), "Ada Example", None)
    assert leads == [] and gaps == ["podcast_index_keys_missing"] and len(transport.requests) == 1


def test_a_failing_source_is_a_gap_not_an_error():
    caller, _ = wire(
        HttpResponse(500, {}, b"down"),
        HttpResponse(500, {}, b"down"),
        ok({"items": [pi_episode("Talk", "Ada Example", 1740787200)]}),
        ok({"feeds": []}),
    )
    leads, gaps = find_podcasts(caller, KEYS, "Ada Example", None)
    assert [lead.title for lead in leads] == ["Talk"] and gaps and "apple" in gaps[0]
