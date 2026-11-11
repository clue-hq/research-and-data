"""Social history readers, against bodies in each provider's real shape (content made up)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

from pydantic import SecretStr

from clue_api.footprint.social import (
    company_linkedin_posts,
    facebook_posts,
    instagram_posts,
    linkedin_activity,
    x_posts,
)
from clue_spend.calls import ProviderCaller
from clue_spend.sinks import MemoryLedger, MemoryRawSink
from clue_spend.transport import HttpResponse, ScriptedTransport, TransportFailure

TOKEN = SecretStr("t")


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


def body(value, status=200, micro="1500"):
    return HttpResponse(
        status,
        {"content-type": "application/json", "X-Treg-Cost-Micro": micro},
        json.dumps(value).encode(),
    )


def li_post(pid, date, *, video=None, author="Ada Example"):
    return {
        "id": f"urn:li:activity:{pid}",
        "content": f"post {pid}",
        "date": date,
        "shareUrl": f"https://www.linkedin.com/posts/ada_{pid}",
        "videoUrl": video,
        "postType": "text",
        "author": {"name": author, "url": "https://www.linkedin.com/in/ada"},
    }


def query(request):
    return {k: v[0] for k, v in parse_qs(urlsplit(request.url).query).items()}


def test_linkedin_pages_until_no_more():
    caller, transport = wire(
        body(
            {
                "posts": [li_post(1, "2026-10-01T10:00:00Z")],
                "paginationToken": "p2",
                "hasMore": True,
            }
        ),
        body(
            {
                "posts": [li_post(2, "2019-03-01T10:00:00Z")],
                "paginationToken": None,
                "hasMore": False,
            }
        ),
    )
    history = linkedin_activity(caller, TOKEN, "ada", "posts")
    assert history.state == "complete" and history.pages == 2
    assert [p.post_id for p in history.posts] == ["urn:li:activity:1", "urn:li:activity:2"]
    assert history.posts[0].kind == "own" and history.posts[0].url.endswith("ada_1")
    assert history.cost_usd == 0.003
    assert query(transport.requests[0]) == {"profileUrlOrUrn": "ada", "count": "50"}
    assert query(transport.requests[1])["paginationToken"] == "p2"
    assert "fetchinio.linkedin.user.posts" in transport.requests[0].url


def test_linkedin_reactions_carry_the_liked_post():
    reaction = {
        "reactionType": "LIKE",
        "createdAt": "2026-10-29T13:29:56Z",
        "activityUrn": "urn:li:activity:9",
        "post": li_post(9, "2026-10-27T18:10:16Z", author="Someone Else"),
    }
    caller, transport = wire(body({"reactions": [reaction], "hasMore": False}))
    history = linkedin_activity(caller, TOKEN, "ada", "reactions")
    post = history.posts[0]
    assert post.kind == "reaction" and post.author_name == "Someone Else"
    assert post.published_at == datetime(2026, 10, 29, 13, 29, 56, tzinfo=UTC)
    assert "fetchinio.linkedin.user.reactions" in transport.requests[0].url


def test_failure_mid_history_keeps_fetched_pages():
    caller, _ = wire(
        body(
            {
                "posts": [li_post(1, "2026-10-01T10:00:00Z")],
                "paginationToken": "p2",
                "hasMore": True,
            }
        ),
        *[TransportFailure("connection reset")] * 4,
    )
    history = linkedin_activity(caller, TOKEN, "ada", "posts")
    assert history.state == "partial" and len(history.posts) == 1
    assert "page 2" in history.gaps[0] and "did not answer" in history.gaps[0]


def test_first_page_failure_is_unavailable():
    caller, _ = wire(*[TransportFailure("connection reset")] * 4)
    history = linkedin_activity(caller, TOKEN, "ada", "posts")
    assert history.state == "unavailable" and history.posts == []
    assert "page 1" in history.gaps[0]


def test_private_instagram_is_private_not_error():
    caller, _ = wire(
        body({"success": False, "message": "Profile is restricted", "error": "not_found"}, 404, "0")
    )
    history = instagram_posts(caller, TOKEN, "ada")
    assert history.state == "private" and history.posts == [] and history.cost_usd == 0


def test_unknown_handle_is_not_found():
    # ScrapeCreators' real reply for an unknown Instagram handle (probed 2026-11-11).
    unknown = {
        "success": True,
        "credits_charged": 0,
        "error": "not_found",
        "errorStatus": 404,
        "message": "Profile is unavailable on Instagram",
    }
    caller, _ = wire(body(unknown, 404, "0"))
    history = instagram_posts(caller, TOKEN, "nobody")
    assert history.state == "not_found"
    assert history.provider_said == "Profile is unavailable on Instagram"


def test_instagram_posts_and_video():
    item = {
        "code": "ABC",
        "id": "1_2",
        "taken_at": 1753361074,
        "caption": {"text": "a reel"},
        "video_versions": [{"url": "https://cdn.example/v.mp4"}],
        "user": {"username": "ada", "full_name": "Ada Example"},
    }
    caller, _ = wire(body({"items": [item], "more_available": False, "next_max_id": None}))
    post = instagram_posts(caller, TOKEN, "ada").posts[0]
    assert post.url == "https://www.instagram.com/p/ABC/" and post.text == "a reel"
    assert post.video_urls == ["https://cdn.example/v.mp4"]


def test_private_facebook_is_private():
    caller, _ = wire(
        body({"success": True, "account_status": "private", "isPrivate": True}, micro="0")
    )
    assert facebook_posts(caller, TOKEN, "https://www.facebook.com/ada").state == "private"


def test_facebook_posts_page_by_cursor():
    first = {
        "id": "1",
        "text": "hello",
        "url": "https://www.facebook.com/ada/posts/1",
        "author": {"name": "Ada Example"},
        "videoDetails": {"hdUrl": "https://video.example/1.mp4"},
        "creation_time": "2026-11-09T08:02:52.000Z",
    }
    caller, transport = wire(
        body({"posts": [first], "cursor": "c2"}),
        body({"posts": [], "cursor": None}),
    )
    history = facebook_posts(caller, TOKEN, "https://www.facebook.com/ada")
    assert history.state == "complete" and history.posts[0].video_urls == [
        "https://video.example/1.mp4"
    ]
    assert query(transport.requests[1])["cursor"] == "c2"


def tweet(tid, text, screen_name="ada", video=None):
    media = {"video": [{"variants": video}]} if video else None
    return {
        "tweet_id": tid,
        "created_at": "Fri Nov 06 18:16:33 +0000 2026",
        "text": text,
        "media": media,
        "author": {"screen_name": screen_name, "name": "Ada Example"},
    }


def test_retweet_marked_repost():
    caller, _ = wire(
        body(
            {
                "data": {
                    "timeline": [tweet("1", "mine"), tweet("2", "RT @bob: theirs", "bob")],
                    "next_cursor": None,
                    "status": "ok",
                }
            }
        )
    )
    posts = x_posts(caller, TOKEN, "ada").posts
    assert [p.kind for p in posts] == ["own", "repost"]
    assert posts[0].url == "https://x.com/ada/status/1"


def test_x_pages_by_cursor_and_stops_on_repeat():
    caller, transport = wire(
        body({"data": {"timeline": [tweet("1", "a")], "next_cursor": "c2", "status": "ok"}}),
        body({"data": {"timeline": [tweet("1", "a")], "next_cursor": "c3", "status": "ok"}}),
    )
    history = x_posts(caller, TOKEN, "ada")
    assert history.pages == 2 and len(history.posts) == 1 and history.state == "complete"
    assert query(transport.requests[1])["cursor"] == "c2"


def test_x_video_takes_best_mp4():
    variants = [
        {"content_type": "application/x-mpegURL", "url": "https://v.example/a.m3u8"},
        {"content_type": "video/mp4", "bitrate": 432000, "url": "https://v.example/low.mp4"},
        {"content_type": "video/mp4", "bitrate": 2176000, "url": "https://v.example/high.mp4"},
    ]
    caller, _ = wire(
        body(
            {
                "data": {
                    "timeline": [tweet("1", "v", video=variants)],
                    "next_cursor": None,
                    "status": "ok",
                }
            }
        )
    )
    assert x_posts(caller, TOKEN, "ada").posts[0].video_urls == ["https://v.example/high.mp4"]


def test_video_links_kept():
    caller, _ = wire(
        body(
            {
                "posts": [li_post(1, "2026-10-01T10:00:00Z", video="https://dms.licdn.com/v.mp4")],
                "hasMore": False,
            }
        )
    )
    assert linkedin_activity(caller, TOKEN, "ada", "posts").posts[0].video_urls == [
        "https://dms.licdn.com/v.mp4"
    ]


def co_post(urn, posted):
    return {
        "urn": urn,
        "posted": posted,
        "text": f"company {urn}",
        "url": f"https://www.linkedin.com/posts/acme_{urn}",
        "poster": {"name": "Acme"},
    }


def test_company_posts_page_back_by_date_until_nothing_new():
    caller, transport = wire(
        body(
            {
                "code": 200,
                "data": {
                    "data": [
                        co_post("3", "2026-11-09 17:41:08"),
                        co_post("2", "2026-10-08 19:49:01"),
                    ]
                },
            },
            micro="1000",
        ),
        body(
            {
                "code": 200,
                "data": {
                    "data": [
                        co_post("2", "2026-10-08 19:49:01"),
                        co_post("1", "2026-07-02 20:22:15"),
                    ]
                },
            },
            micro="1000",
        ),
        body({"code": 200, "data": {"data": [co_post("1", "2026-07-02 20:22:15")]}}, micro="1000"),
    )
    history = company_linkedin_posts(caller, TOKEN, "https://www.linkedin.com/company/acme/")
    assert [p.post_id for p in history.posts] == ["3", "2", "1"]
    assert all(p.kind == "company" for p in history.posts) and history.pages == 3
    assert query(transport.requests[1])["end_date"] == "2026-10-08"
    assert "tikhub.x.linkedin-web-v2-get-company-posts" in transport.requests[0].url


def test_company_unknown_is_not_found():
    caller, _ = wire(body({"code": 200, "data": {"data": None}}, micro="1000"))
    assert company_linkedin_posts(caller, TOKEN, "acme").state == "not_found"


# --- Reposts, quotes, replies, reshares, link cards and mentions ------------------------------
# A post's ``text`` is only ever the person's own words. What they repost, quote or reshare is
# someone else's and lives in ``shared``, in full and with its author.

LONG = "A long original post by Bob. " * 40  # well past X's 140-character retweet form


def timeline(*items):
    return body({"data": {"timeline": list(items), "next_cursor": None, "status": "ok"}})


def bob_tweet(tid, text, *, video=None):
    return {**tweet(tid, text, "bob", video=video), "author": {"screen_name": "bob", "name": "Bob"}}


def test_retweet_keeps_the_full_original_not_the_clipped_rt_text():
    variants = [{"content_type": "video/mp4", "bitrate": 1, "url": "https://v.example/bob.mp4"}]
    rt = {
        **tweet("2", "RT @bob: " + LONG[:129] + "…"),
        "media": [],
        "retweeted": {"id": "20"},
        "retweeted_tweet": bob_tweet("20", LONG, video=variants),
    }
    caller, _ = wire(timeline(rt))
    post = x_posts(caller, TOKEN, "ada").posts[0]
    assert post.kind == "repost" and post.text == ""
    shared = post.shared
    assert shared is not None and shared.text == LONG and "…" not in shared.text
    assert shared.author_name == "Bob" and shared.author_url == "https://x.com/bob"
    assert shared.url == "https://x.com/bob/status/20" and shared.post_id == "20"
    assert shared.published_at == datetime(2026, 11, 6, 18, 16, 33, tzinfo=UTC)
    assert shared.video_urls == ["https://v.example/bob.mp4"]


def test_retweet_without_the_original_falls_back_to_the_rt_text():
    caller, _ = wire(timeline(tweet("2", "RT @bob: theirs")))
    post = x_posts(caller, TOKEN, "ada").posts[0]
    assert post.kind == "repost" and post.text == "RT @bob: theirs" and post.shared is None


def test_quote_tweet_keeps_own_words_and_the_quoted_post():
    quote = {**tweet("3", "Very nice"), "quoted": bob_tweet("30", "Bob's launch post")}
    caller, _ = wire(timeline(quote))
    post = x_posts(caller, TOKEN, "ada").posts[0]
    assert post.kind == "own" and post.text == "Very nice"
    assert post.shared is not None and post.shared.text == "Bob's launch post"
    assert post.shared.author_name == "Bob" and post.shared.url == "https://x.com/bob/status/30"


def test_reply_records_the_tweet_it_answers():
    reply = {**tweet("4", "and part two"), "reply_to": "3"}
    caller, _ = wire(timeline(reply))
    post = x_posts(caller, TOKEN, "ada").posts[0]
    assert post.reply_to_id == "3" and post.shared is None


def li_reshare(pid, own_text):
    original = {
        **li_post(90, "2026-10-01T20:28:29.388Z", author="Pat Original"),
        "content": LONG,
        "author": {
            "name": "Pat Original",
            "url": "https://www.linkedin.com/in/pat?miniProfileUrn=urn%3Ali%3Afsd_profile%3AX",
        },
    }
    return {
        **li_post(pid, "2026-10-02T10:00:00Z"),
        "content": own_text,
        "resharedPostUrn": "urn:li:activity:90",
        "resharedPost": original,
    }


def test_linkedin_reshare_keeps_the_full_original():
    caller, _ = wire(body({"posts": [li_reshare(5, "Great team, apply!")], "hasMore": False}))
    post = linkedin_activity(caller, TOKEN, "ada", "posts").posts[0]
    assert post.kind == "own" and post.text == "Great team, apply!"
    shared = post.shared
    assert shared is not None and shared.text == LONG
    assert shared.author_name == "Pat Original"
    assert shared.author_url == "https://www.linkedin.com/in/pat"
    assert shared.url == "https://www.linkedin.com/posts/ada_90"
    assert shared.post_id == "urn:li:activity:90"


def test_linkedin_reshare_without_comment_is_a_repost():
    caller, _ = wire(body({"posts": [li_reshare(6, "")], "hasMore": False}))
    post = linkedin_activity(caller, TOKEN, "ada", "posts").posts[0]
    assert post.kind == "repost" and post.text == "" and post.shared.text == LONG


def test_liked_reshare_keeps_the_original():
    reaction = {"createdAt": "2026-10-29T13:29:56Z", "post": li_reshare(7, "look at this")}
    caller, _ = wire(body({"reactions": [reaction], "hasMore": False}))
    post = linkedin_activity(caller, TOKEN, "ada", "reactions").posts[0]
    assert post.kind == "reaction" and post.shared is not None and post.shared.text == LONG


def test_linkedin_link_card_and_mentions():
    item = {
        **li_post(8, "2026-10-25T10:00:00Z"),
        "article": {
            "title": "Content Writer @ Example",
            "subtitle": "jobs.example.com",
            "link": "https://jobs.example.com/job/1",
        },
        "mentions": [
            {"type": "person", "name": "Dan Example", "url": "https://www.linkedin.com/in/dan"},
            {"type": "company", "name": "Acme", "url": "https://www.linkedin.com/company/acme/"},
            {"type": "person", "name": None, "url": None},
        ],
    }
    caller, _ = wire(body({"posts": [item], "hasMore": False}))
    post = linkedin_activity(caller, TOKEN, "ada", "posts").posts[0]
    assert post.link is not None and post.link.title == "Content Writer @ Example"
    assert post.link.url == "https://jobs.example.com/job/1"
    assert [(m.name, m.url) for m in post.mentions] == [
        ("Dan Example", "https://www.linkedin.com/in/dan"),
        ("Acme", "https://www.linkedin.com/company/acme/"),
    ]


def test_plain_post_has_no_extras():
    caller, _ = wire(body({"posts": [li_post(1, "2026-10-01T10:00:00Z")], "hasMore": False}))
    post = linkedin_activity(caller, TOKEN, "ada", "posts").posts[0]
    assert post.shared is None and post.link is None and post.mentions == []
    assert post.reply_to_id is None


# --- Long quoted posts, short links, company reshares (2026-11-11) ----------------------------

from clue_api.footprint import short_links  # noqa: E402
from tests.footprint._pages import lnkd_page, tco_page  # noqa: E402

QUOTED_PREVIEW = "x" * 270  # what TikHub's timeline sends for a long quoted post: its first ~280


def one_at_a_time(monkeypatch):
    # ScriptedTransport answers in order, so short links are opened one by one in tests.
    monkeypatch.setattr(short_links, "WORKERS", 1)


def tweet_detail(text, *, urls=()):
    return body(
        {
            "code": 200,
            "data": {
                "text": text,
                "entities": {"urls": [{"url": s, "expanded_url": u} for s, u in urls]},
            },
        },
        micro="1000",
    )


def test_long_quoted_post_is_read_in_full(monkeypatch):
    one_at_a_time(monkeypatch)
    quote = {**tweet("3", "So true"), "quoted": bob_tweet("30", QUOTED_PREVIEW)}
    caller, transport = wire(timeline(quote), tweet_detail(LONG))
    history = x_posts(caller, TOKEN, "ada")
    shared = history.posts[0].shared
    assert shared.text == LONG and not shared.text_may_be_cut
    assert "tikhub.x.twitter-web-fetch-tweet-detail" in transport.requests[1].url
    assert query(transport.requests[1]) == {"tweet_id": "30"}
    assert history.cost_usd == 0.0025


def test_short_quoted_post_is_not_looked_up():
    quote = {**tweet("3", "So true"), "quoted": bob_tweet("30", "short and complete")}
    caller, transport = wire(timeline(quote))
    post = x_posts(caller, TOKEN, "ada").posts[0]
    assert post.shared.text == "short and complete" and len(transport.requests) == 1


def test_wide_characters_count_double_toward_the_limit(monkeypatch):
    one_at_a_time(monkeypatch)
    preview = "地图" * 70  # 140 characters, 280 by X's count
    quote = {**tweet("3", "看看"), "quoted": bob_tweet("30", preview)}
    caller, transport = wire(timeline(quote), tweet_detail(preview + "，还有更多"))
    assert x_posts(caller, TOKEN, "ada").posts[0].shared.text == preview + "，还有更多"


def test_quoted_post_that_cannot_be_read_is_marked_possibly_cut(monkeypatch):
    one_at_a_time(monkeypatch)
    quote = {**tweet("3", "So true"), "quoted": bob_tweet("30", QUOTED_PREVIEW)}
    caller, _ = wire(timeline(quote), body({"code": 404, "detail": "gone"}, 404, "0"))
    shared = x_posts(caller, TOKEN, "ada").posts[0].shared
    assert shared.text == QUOTED_PREVIEW and shared.text_may_be_cut


def test_x_links_come_from_tikhub_and_the_rest_are_opened(monkeypatch):
    one_at_a_time(monkeypatch)
    item = {
        **tweet("5", "Read https://t.co/Known1 and https://t.co/Other2"),
        "entities": {
            "urls": [{"url": "https://t.co/Known1", "expanded_url": "https://a.example/1"}]
        },
    }
    rt = {
        **tweet("6", "RT @bob: see https://t.co/Bob3"),
        "retweeted_tweet": bob_tweet("60", "see https://t.co/Bob3"),
    }
    caller, transport = wire(
        timeline(item, rt), tco_page("https://bob.example/3"), tco_page("https://b.example/2")
    )
    posts = x_posts(caller, TOKEN, "ada").posts
    assert posts[0].links == {
        "https://t.co/Known1": "https://a.example/1",
        "https://t.co/Other2": "https://b.example/2",
    }
    assert posts[0].text == "Read https://t.co/Known1 and https://t.co/Other2"  # words unchanged
    assert posts[1].shared.links == {"https://t.co/Bob3": "https://bob.example/3"}
    assert len(transport.requests) == 3  # the known link is never opened


def test_linkedin_short_links_are_opened(monkeypatch):
    one_at_a_time(monkeypatch)
    item = {
        **li_reshare(9, "Apply: https://lnkd.in/gOwn"),
        "content": "Apply: https://lnkd.in/gOwn",
    }
    item["resharedPost"]["content"] = "Details https://lnkd.in/gOrig"
    caller, _ = wire(
        body({"posts": [item], "hasMore": False}),
        lnkd_page("https://jobs.example.com/1"),
        lnkd_page("https://events.example.com/2"),
    )
    post = linkedin_activity(caller, TOKEN, "ada", "posts").posts[0]
    assert post.links == {"https://lnkd.in/gOwn": "https://events.example.com/2"}
    assert post.shared.links == {"https://lnkd.in/gOrig": "https://jobs.example.com/1"}


def test_company_reshare_is_a_repost_of_the_original(monkeypatch):
    one_at_a_time(monkeypatch)
    reshare = {
        "urn": "75",
        "share_urn": "74",
        "posted": "2026-10-13 18:46:01",
        "reshared": True,
        "text": "A leader's own post https://lnkd.in/gL",
        "url": "https://www.linkedin.com/posts/lee_a-leaders-own-post-ugcPost-74-abcd",
        "poster": {"name": "Lee Leader", "linkedin_url": "https://www.linkedin.com/in/lee"},
    }
    caller, _ = wire(
        body({"code": 200, "data": {"data": [reshare]}}, micro="1000"),
        body({"code": 200, "data": {"data": [reshare]}}, micro="1000"),
        lnkd_page("https://podcast.example/ep"),
    )
    post = company_linkedin_posts(caller, TOKEN, "https://www.linkedin.com/company/acme/").posts[0]
    assert post.kind == "repost" and post.text == ""
    assert post.url == "https://www.linkedin.com/feed/update/urn:li:activity:75/"
    assert post.author_url == "https://www.linkedin.com/company/acme/"
    shared = post.shared
    assert (
        shared.author_name == "Lee Leader"
        and shared.author_url == "https://www.linkedin.com/in/lee"
    )
    assert shared.text == reshare["text"] and shared.url == reshare["url"]
    assert shared.links == {"https://lnkd.in/gL": "https://podcast.example/ep"}


def test_company_own_post_keeps_its_words(monkeypatch):
    one_at_a_time(monkeypatch)
    caller, _ = wire(
        body({"code": 200, "data": {"data": [co_post("1", "2026-07-02 20:22:15")]}}, micro="1000"),
        body({"code": 200, "data": {"data": [co_post("1", "2026-07-02 20:22:15")]}}, micro="1000"),
    )
    post = company_linkedin_posts(caller, TOKEN, "acme").posts[0]
    assert post.kind == "company" and post.text == "company 1" and post.shared is None
