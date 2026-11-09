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
    assert history.gap and "page 2" in history.gap


def test_first_page_failure_is_unavailable():
    caller, _ = wire(*[TransportFailure("connection reset")] * 4)
    history = linkedin_activity(caller, TOKEN, "ada", "posts")
    assert history.state == "unavailable" and history.posts == [] and history.gap


def test_private_instagram_is_private_not_error():
    caller, _ = wire(
        body({"success": False, "message": "Profile is restricted", "error": "not_found"}, 404, "0")
    )
    history = instagram_posts(caller, TOKEN, "ada")
    assert history.state == "private" and history.posts == [] and history.cost_usd == 0


def test_unknown_handle_is_not_found():
    caller, _ = wire(body({"success": False, "message": "User not found"}, 404, "0"))
    assert instagram_posts(caller, TOKEN, "nobody").state == "not_found"


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
