"""find_videos: the agent's own searches on YouTube, full details, Exa when the quota is gone."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

from pydantic import SecretStr

from clue_api.footprint.media_sources import MediaSourceKeys
from clue_api.footprint.video_search import VideoLead, find_videos
from clue_spend.calls import ProviderCaller
from clue_spend.sinks import MemoryLedger, MemoryRawSink
from clue_spend.transport import HttpResponse, ScriptedTransport

KEYS = MediaSourceKeys(youtube_api_key=SecretStr("yt"))
VID1, VID2 = "aaaaaaaaaaa", "bbbbbbbbbbb"


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


QUOTA = HttpResponse(
    403,
    {"content-type": "application/json"},
    json.dumps({"error": {"errors": [{"reason": "quotaExceeded"}], "code": 403}}).encode(),
)


def search(*ids):
    return ok({"items": [{"id": {"videoId": v}} for v in ids]})


def details(*ids):
    return ok(
        {
            "items": [
                {
                    "id": v,
                    "snippet": {
                        "title": f"Talk {v}",
                        "channelTitle": "Conf",
                        "publishedAt": "2025-05-01T10:00:00Z",
                        "description": "Ada Example on zero trust https://acme.example/blog",
                        "tags": ["zero trust", "Ada Example"],
                    },
                    "contentDetails": {"duration": "PT35M10S"},
                }
                for v in ids
            ]
        }
    )


def q(request):
    return parse_qs(urlsplit(request.url).query)


def test_videos_full_details():
    caller, transport = wire(search(VID1), search(VID1, VID2), details(VID1, VID2))
    queries = ['"Ada Example"', '"Ada Example" Acme']
    leads, gaps = find_videos(caller, KEYS, queries, exa_fallback=None)
    assert gaps == [] and [lead.video_id for lead in leads] == [VID1, VID2]
    assert leads[0].found_by == queries and leads[1].found_by == ['"Ada Example" Acme']
    lead = leads[0]
    assert isinstance(lead, VideoLead) and lead.duration_s == 2110 and lead.channel == "Conf"
    assert lead.tags == ["zero trust", "Ada Example"] and lead.links == [
        "https://acme.example/blog"
    ]
    assert lead.url == f"https://www.youtube.com/watch?v={VID1}" and lead.source == "youtube"
    assert q(transport.requests[0])["q"] == ['"Ada Example"']
    assert q(transport.requests[1])["q"] == ['"Ada Example" Acme']
    assert q(transport.requests[2])["id"] == [f"{VID1},{VID2}"]


def test_video_quota_falls_back_to_exa():
    calls: list[str] = []

    def exa(query: str) -> list[str]:
        calls.append(query)
        return [f"https://www.youtube.com/watch?v={VID2}", "https://example.com/not-youtube"]

    caller, _ = wire(QUOTA, QUOTA)
    leads, gaps = find_videos(caller, KEYS, ['"Ada Example"', "Acme panel"], exa_fallback=exa)
    assert calls == ['"Ada Example"', "Acme panel"]
    assert gaps == ["youtube_quota_exhausted_used_exa"]
    assert [(lead.video_id, lead.source) for lead in leads] == [(VID2, "exa")]


def test_video_quota_without_fallback_returns_gap():
    caller, _ = wire(QUOTA)
    leads, gaps = find_videos(caller, KEYS, ['"Ada Example"'], exa_fallback=None)
    assert leads == [] and gaps == ["youtube_quota_exhausted"]


def test_no_youtube_key_uses_exa():
    caller, _ = wire()
    leads, gaps = find_videos(
        caller,
        MediaSourceKeys(),
        ['"Ada Example"'],
        exa_fallback=lambda q: [f"https://youtu.be/{VID1}"],
    )
    assert [lead.video_id for lead in leads] == [VID1] and gaps == [
        "youtube_data_api_key_missing_used_exa"
    ]


def test_videos_keep_the_order_found_and_rank_nothing():
    caller, transport = wire(search(VID2, VID1), details(VID1, VID2))
    leads, _ = find_videos(caller, KEYS, ["Acme CISO keynote"], exa_fallback=None)
    assert [lead.video_id for lead in leads] == [VID2, VID1]
    assert q(transport.requests[0])["q"] == ["Acme CISO keynote"]
