"""find_podcasts: the agent's own searches, each run on Apple, Podcast Index and Exa's podcast
transcripts; one list, nothing dropped or ranked by name (bodies made up)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

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
    """One search's answers in request order: Apple, Podcast Index byperson, byterm."""
    return [
        ok({"results": apple_eps}),
        ok({"items": pi_eps}),
        ok({"feeds": list(pi_feeds)}),
        *[ok({"results": [{"feedUrl": f}]}) for f in lookups],
    ]


def term(request):
    query = parse_qs(urlsplit(request.url).query)
    return (query.get("term") or query.get("q"))[0]


def exa_page(title, *, show="Show A", guests="[Ada Example](https://exa.ai/library/person/a)"):
    return (
        f"# {title}\n\n"
        f"- **Podcast:** [{show}](https://exa.ai/library/podcast/s1)\n"
        "- **Published:** 2026-06-15T06:00:00+00:00\n"
        "- **Duration:** 06:37.427\n"
        "- **Language:** en\n"
        "- **Hosts:** [Host One](https://exa.ai/library/person/h)\n"
        f"- **Guests:** {guests}\n\n"
        "## Transcript\n\n**Host One · 00:00.0–00:30.0**\n\nJoining me today is Ada Exampel."
    )


def exa_hit(title, **kw):
    return SimpleNamespace(
        url=f"https://exa.ai/library/podcast/s1/episode/{title[:3]}",
        title=title,
        published_date="2026-06-15T06:00:00.000Z",
        text=exa_page(title, **kw),
        highlights=("Joining me today is Ada Exampel, Executive Director at Acme.",),
    )


def exa_returning(*hits_by_query):
    asked: list[str] = []
    answers = list(hits_by_query)

    def search(query):
        asked.append(query)
        return answers.pop(0) if answers else []

    return search, asked


def test_every_search_runs_on_every_source():
    exa, asked = exa_returning([], [])
    caller, transport = wire(*script([], []), *script([], []))
    queries = ['"Ada Example" podcast', '"Ada Example" Acme']
    leads, tally = find_podcasts(caller, KEYS, queries, exa_search=exa)
    assert leads == [] and tally.gaps == [] and tally.state == "complete"
    urls = [r.url for r in transport.requests]
    assert [term(r) for r in transport.requests] == [queries[0]] * 3 + [queries[1]] * 3
    assert "entity=podcastEpisode" in urls[0]
    assert "search/byperson" in urls[1] and "search/byterm" in urls[2]
    assert asked == queries


def test_one_episode_found_twice_is_listed_once_with_both_searches():
    caller, _ = wire(
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
        ),
        *script([], [pi_episode("Zero trust at scale", "Ada Example of Acme joins", 1740787200)]),
    )
    leads, tally = find_podcasts(caller, KEYS, ["Ada Example", "Acme CISO"], exa_search=None)
    assert len(leads) == 1 and isinstance(leads[0], EpisodeLead)
    lead = leads[0]
    assert lead.found_by == ["Ada Example", "Acme CISO"]
    assert sorted(lead.sources) == ["apple", "podcast_index"]
    assert lead.transcript_url == "https://showa.example/t.vtt"
    assert lead.feed_url == "https://feeds.example/a.xml"
    assert tally.gaps == ["Exa's podcast transcripts are not available in this job: not searched."]


def test_no_ranking_by_name_order_is_as_found():
    caller, _ = wire(
        *script(
            [
                apple_episode("Newest, unrelated", "cooking", "2026-01-01T00:00:00Z", cid=1),
                apple_episode("Older with Ada Exampel", "Acme", "2024-01-01T00:00:00Z", cid=2),
            ],
            [],
            lookups=["https://feeds.example/one.xml", "https://feeds.example/two.xml"],
        )
    )
    leads, _ = find_podcasts(caller, KEYS, ["Ada Example"], exa_search=None)
    assert [lead.title for lead in leads] == ["Newest, unrelated", "Older with Ada Exampel"]
    assert not hasattr(leads[0], "names_match")
    assert {lead.feed_url for lead in leads} == {
        "https://feeds.example/one.xml",
        "https://feeds.example/two.xml",
    }


def test_exa_transcript_hit_carries_passages_and_the_people_it_heard():
    hit = exa_hit(
        "The SME cyber shield",
        guests="Bo Plain, [Ada Example](https://exa.ai/library/person/a)",
    )
    exa, _ = exa_returning([hit])
    caller, _ = wire(*script([], []))
    leads, tally = find_podcasts(caller, KEYS, ['"Ada Example"'], exa_search=exa)
    assert tally.gaps == []
    lead = leads[0]
    assert lead.title == "The SME cyber shield" and lead.show == "Show A"
    assert lead.sources == ["exa_podcasts"] and lead.found_by == ['"Ada Example"']
    assert lead.exa_url == hit.url
    assert lead.passages == list(hit.highlights)
    assert lead.heard_hosts == ["Host One"]
    assert lead.heard_guests == ["Bo Plain", "Ada Example"]
    assert lead.duration_s == 397
    assert lead.published_at == datetime(2026, 6, 15, 6, 0, tzinfo=UTC)


def test_exa_hit_merges_with_the_same_episode_from_apple():
    exa, _ = exa_returning([exa_hit("Zero trust at scale")])
    caller, _ = wire(
        *script(
            [apple_episode("Zero trust at scale", "a talk", "2026-06-15T00:00:00Z", feed="f")], []
        )
    )
    leads, _ = find_podcasts(caller, KEYS, ["Ada Example"], exa_search=exa)
    assert len(leads) == 1
    lead = leads[0]
    assert sorted(lead.sources) == ["apple", "exa_podcasts"]
    assert lead.audio_url == "https://audio.example/Zero trust at scale.mp3"
    assert lead.passages and lead.heard_guests == ["Ada Example"]


def test_exa_failure_is_a_gap_and_the_rest_still_answer():
    def broken(query):
        raise ValueError("exa HTTP 500")

    caller, _ = wire(*script([apple_episode("Talk", "x", "2025-01-01T00:00:00Z", feed="f")], []))
    leads, tally = find_podcasts(caller, KEYS, ["Ada Example"], exa_search=broken)
    assert [lead.title for lead in leads] == ["Talk"]
    assert tally.gaps == ["Exa podcast search [1] 'Ada Example' failed: exa HTTP 500"]
    assert tally.state == "partial"


def test_podcasts_never_dropped():
    caller, _ = wire(
        *script([apple_episode("No mention", "gardening", "2025-01-01T00:00:00Z", feed="f")], [])
    )
    leads, _ = find_podcasts(caller, KEYS, ["Ada Example"], exa_search=None)
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
    leads, _ = find_podcasts(caller, KEYS, ["Ada Example"], exa_search=None)
    assert leads[0].kind == "show" and leads[0].feed_url == "https://feeds.example/ada.xml"


def test_without_podcast_index_keys_apple_only_and_gap():
    caller, transport = wire(ok({"results": []}))
    leads, tally = find_podcasts(caller, MediaSourceKeys(), ["Ada Example"], exa_search=None)
    assert leads == [] and len(transport.requests) == 1
    assert tally.gaps == [
        "Podcast Index keys are not set: it was not searched.",
        "Exa's podcast transcripts are not available in this job: not searched.",
    ]


def test_a_failing_source_is_a_gap_not_an_error():
    caller, _ = wire(
        HttpResponse(500, {}, b"down"),
        HttpResponse(500, {}, b"down"),
        ok({"items": [pi_episode("Talk", "Ada Example", 1740787200)]}),
        ok({"feeds": []}),
    )
    leads, tally = find_podcasts(caller, KEYS, ["Ada Example"], exa_search=None)
    assert [lead.title for lead in leads] == ["Talk"]
    assert any(gap.startswith("Apple search [1] 'Ada Example' failed") for gap in tally.gaps)


# --- The overview: one short line per result (founder, 2026-11-11) -----------------------------

from clue_api.footprint.podcast_search import overview  # noqa: E402


def lead(**kw):
    base = {
        "show": "Show A",
        "title": "Zero trust at scale",
        "published_at": datetime(2025, 3, 1, tzinfo=UTC),
        "description": "a talk",
        "sources": ["apple"],
        "found_by": ['"Ada Example"'],
    }
    return EpisodeLead(**{**base, **kw})


def test_overview_is_one_line_per_result_in_the_order_found():
    searches = ['"Ada Example"', '"Ada Example" Acme']
    leads = [
        lead(duration_s=2700, sources=["apple", "podcast_index"], found_by=searches),
        lead(
            title="The SME cyber shield",
            show="Show B",
            sources=["exa_podcasts"],
            found_by=[searches[1]],
            heard_guests=["Bo Plain", "Ada Example"],
            duration_s=0,
        ),
        lead(
            kind="show", title="The Ada Example Show", show="The Ada Example Show", duration_s=None
        ),
    ]
    lines = overview(leads, searches)
    assert lines[0].startswith("3 results, in the order found (not ranked)")
    assert '[1] "Ada Example" — 2 results' in lines
    assert '[2] "Ada Example" Acme — 2 results' in lines
    rows = [line for line in lines if line[:4].strip().isdigit()]
    assert rows == [
        "  1 | 2025-03-01 | Show A — Zero trust at scale | 45 min | 1,2 | apple+pi",
        "  2 | 2025-03-01 | Show B — The SME cyber shield | - | 2 | exa"
        " | heard: Bo Plain, Ada Example",
        "  3 | 2025-03-01 | SHOW: The Ada Example Show | - | 1 | apple",
    ]


def test_overview_shortens_long_titles():
    rows = overview([lead(title="x" * 200)], ['"Ada Example"'])
    row = next(line for line in rows if line.startswith("  1 |"))
    assert "…" in row and len(row) < 140


def test_exa_passages_leave_out_the_episode_header():
    hit = exa_hit("The SME cyber shield")
    hit.highlights = (
        "- **Podcast:** [Show A](https://exa.ai/library/podcast/s1)\n- **Published:** 2026-06-15"
        "\n- **Guests:** [Ada Example](https://exa.ai/library/person/a)\n\n...\n\n"
        "Joining me today is Ada Exampel, Executive Director at Acme.",
        "Later she said zero trust starts with people.",
    )
    exa, _ = exa_returning([hit])
    caller, _ = wire(*script([], []))
    leads, _ = find_podcasts(caller, KEYS, ['"Ada Example"'], exa_search=exa)
    assert leads[0].passages == [
        "Joining me today is Ada Exampel, Executive Director at Acme.",
        "Later she said zero trust starts with people.",
    ]
