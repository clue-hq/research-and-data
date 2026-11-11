"""Podcast and video searches never turn a failure into "no results" or throw away what was found.

Each search keeps its own results; a failure is counted and named in the tally; YouTube's
rate-limit and quota refusals send the remaining searches to Exa; an Exa refusal is checked, never
read as zero hits; Exa running out of credit stops Exa only (review findings I2, I3).
"""

from __future__ import annotations

import json

from clue_api.footprint.podcast_search import find_podcasts
from clue_api.footprint.search_tally import SourceStopped
from clue_api.footprint.video_search import find_videos
from clue_spend.transport import HttpResponse
from tests.footprint.test_video_search import KEYS, VID1, VID2, details, search, wire

VID3 = "ccccccccccc"


def youtube_refusal(status, reason, message="refused"):
    body = {"error": {"code": status, "message": message, "errors": [{"reason": reason}]}}
    return HttpResponse(status, {"content-type": "application/json"}, json.dumps(body).encode())


def server_error():
    return HttpResponse(500, {"content-type": "application/json"}, b'{"error": "backend"}')


def exa_returning(*ids, calls=None):
    def exa(query: str) -> list[str]:
        if calls is not None:
            calls.append(query)
        return [f"https://www.youtube.com/watch?v={v}" for v in ids]

    return exa


# --- Videos -------------------------------------------------------------------------------------


def test_a_failed_search_keeps_the_others_and_is_tried_on_exa():
    calls: list[str] = []
    caller, _ = wire(search(VID1), server_error(), server_error(), details(VID1, VID2))
    leads, tally = find_videos(
        caller, KEYS, ["one", "two"], exa_fallback=exa_returning(VID2, calls=calls)
    )
    assert [lead.video_id for lead in leads] == [VID1, VID2]
    assert [lead.source for lead in leads] == ["youtube", "exa"]
    assert calls == ["two"]
    assert tally.state == "partial" and "[2]" in tally.gaps[0] and "HTTP 500" in tally.gaps[0]


def test_rate_limit_sends_the_rest_to_exa_and_keeps_what_youtube_found():
    calls: list[str] = []
    caller, _ = wire(
        search(VID1),
        youtube_refusal(403, "rateLimitExceeded"),
        youtube_refusal(403, "rateLimitExceeded"),
    )
    leads, tally = find_videos(
        caller, KEYS, ["one", "two", "three"], exa_fallback=exa_returning(VID2, calls=calls)
    )
    assert [lead.video_id for lead in leads] == [VID1, VID2]
    assert calls == ["two", "three"]
    assert tally.state == "partial"
    assert any("rate limit" in g and "[2]" in g for g in tally.gaps)


def test_quota_gone_is_a_note_and_the_rest_go_to_exa():
    calls: list[str] = []
    caller, _ = wire(search(VID1), youtube_refusal(403, "quotaExceeded"))
    leads, tally = find_videos(
        caller, KEYS, ["one", "two"], exa_fallback=exa_returning(VID2, calls=calls)
    )
    assert [lead.video_id for lead in leads] == [VID1, VID2] and calls == ["two"]
    # Asking again today would hit the same daily quota: told, but not a failure to retry.
    assert tally.state == "complete" and any("daily quota" in g for g in tally.gaps)


def test_exa_refusal_is_a_failure_not_zero_results():
    def exa(query: str) -> list[str]:
        raise ValueError("exa HTTP 429")

    caller, _ = wire(youtube_refusal(403, "quotaExceeded"))
    leads, tally = find_videos(caller, KEYS, ["one"], exa_fallback=exa)
    assert leads == [] and tally.state == "unavailable"
    assert any("exa HTTP 429" in g for g in tally.gaps)


def test_exa_out_of_credit_stops_exa_only():
    asked: list[str] = []

    def exa(query: str) -> list[str]:
        asked.append(query)
        raise SourceStopped("exa", "payment_required")

    caller, _ = wire(youtube_refusal(403, "quotaExceeded"))
    leads, tally = find_videos(caller, KEYS, ["one", "two"], exa_fallback=exa)
    assert asked == ["one"] and tally.stopped == {"exa": "payment_required"}
    assert tally.state == "unavailable" and any("Exa" in g and "[2]" in g for g in tally.gaps)


def test_details_failure_keeps_the_videos_without_details():
    caller, _ = wire(search(VID1, VID2), server_error(), server_error())
    leads, tally = find_videos(caller, KEYS, ["one"], exa_fallback=None)
    assert [lead.video_id for lead in leads] == [VID1, VID2]
    assert all(lead.title is None for lead in leads)
    assert tally.state == "partial" and any("details" in g.lower() for g in tally.gaps)


def test_every_search_failing_is_unavailable():
    caller, _ = wire(server_error(), server_error())
    leads, tally = find_videos(caller, KEYS, ["one"], exa_fallback=None)
    assert leads == [] and tally.state == "unavailable"


def test_all_searches_answering_nothing_is_complete():
    caller, _ = wire(search(), search())
    leads, tally = find_videos(caller, KEYS, ["one", "two"], exa_fallback=None)
    assert leads == [] and tally.state == "complete" and tally.gaps == []


# --- Podcasts -----------------------------------------------------------------------------------


def apple(*titles):
    rows = [{"trackName": t, "collectionName": "Show", "description": "d"} for t in titles]
    return HttpResponse(200, {}, json.dumps({"results": rows}).encode())


class Hit:
    def __init__(self, title):
        self.url = f"https://exa.ai/library/podcast/{title}"
        self.title = title
        self.published_date = None
        self.text = ""
        self.highlights = []


def test_exa_out_of_credit_keeps_apple_and_stops_exa_for_the_rest():
    asked: list[str] = []

    def exa(query):
        asked.append(query)
        raise SourceStopped("exa", "payment_required")

    caller, _ = wire(apple("Ep 1"), apple("Ep 2"))
    leads, tally = find_podcasts(caller, KEYS, ["one", "two"], exa_search=exa)
    assert [lead.title for lead in leads] == ["Ep 1", "Ep 2"]
    assert asked == ["one"] and tally.stopped == {"exa": "payment_required"}
    assert tally.state == "partial"


def test_a_failed_source_is_counted_and_the_others_kept():
    def exa(query):
        raise ValueError("exa HTTP 500")

    caller, _ = wire(apple("Ep 1"))
    leads, tally = find_podcasts(caller, KEYS, ["one"], exa_search=exa)
    assert [lead.title for lead in leads] == ["Ep 1"]
    assert tally.state == "partial" and any("exa HTTP 500" in g for g in tally.gaps)


def test_apple_feed_lookup_failure_is_named():
    row = {"trackName": "Ep 1", "collectionName": "Show", "description": "d", "collectionId": 7}
    caller, _ = wire(
        HttpResponse(200, {}, json.dumps({"results": [row]}).encode()),
        server_error(),
        server_error(),
    )
    leads, tally = find_podcasts(caller, KEYS, ["one"], exa_search=lambda q: [Hit("Ep 9")])
    assert leads[0].feed_url is None
    assert tally.state == "partial" and any("lookup" in g for g in tally.gaps)


def test_every_podcast_source_failing_is_unavailable():
    def exa(query):
        raise ValueError("exa HTTP 500")

    caller, _ = wire(server_error(), server_error())
    leads, tally = find_podcasts(caller, KEYS, ["one"], exa_search=exa)
    assert leads == [] and tally.state == "unavailable"
