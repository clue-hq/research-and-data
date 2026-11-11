"""What a social history reader reports when a page is not posts.

The agent takes the state at its word, so a failure must never read as an answer about the person:
``not_found`` / ``private`` come only from the provider's own reply about the account (the shapes
below were probed live on 2026-11-11); our credit, a rate limit, a provider fault or a reply that is
not data is ``unavailable`` on the first page and ``partial`` after it, with the reason in ``gaps``.
Every case runs against every reader.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from clue_api.footprint.social import (
    EMPTY_PAGES_IN_A_ROW,
    company_linkedin_posts,
    facebook_posts,
    instagram_posts,
    linkedin_activity,
    x_posts,
)
from clue_spend.transport import HttpResponse, TransportFailure
from tests.footprint.test_social import TOKEN, body, co_post, li_post, tweet, wire


@dataclass(frozen=True)
class Reader:
    name: str
    read: Any
    #: A page holding one post (number ``n``); ``more`` adds the provider's next-page marker.
    page: Any
    #: A reply with status 200 that carries an error instead of posts, in the provider's style.
    error_envelope: dict[str, Any]


def _li_reaction(n):
    return {"reactionType": "LIKE", "createdAt": "2026-10-29T13:29:56Z", "post": li_post(n, "2026")}


READERS = [
    Reader(
        "linkedin_posts",
        lambda c: linkedin_activity(c, TOKEN, "ada", "posts"),
        lambda n, more: {
            "posts": [li_post(n, f"2026-10-{n:02d}T10:00:00Z")],
            "paginationToken": f"p{n + 1}" if more else None,
            "hasMore": more,
        },
        {"error": "Upstream timeout, please retry"},
    ),
    Reader(
        "linkedin_reactions",
        lambda c: linkedin_activity(c, TOKEN, "ada", "reactions"),
        lambda n, more: {
            "reactions": [_li_reaction(n)],
            "paginationToken": f"p{n + 1}" if more else None,
            "hasMore": more,
        },
        {"error": "Upstream timeout, please retry"},
    ),
    Reader(
        "x",
        lambda c: x_posts(c, TOKEN, "ada"),
        lambda n, more: {
            "code": 200,
            "data": {"timeline": [tweet(str(n), f"post {n}")], "next_cursor": f"c{n + 1}"}
            if more
            else {"timeline": [tweet(str(n), f"post {n}")], "next_cursor": None},
        },
        {"code": 400, "message": "Request failed. Please retry.", "data": None},
    ),
    Reader(
        "instagram",
        lambda c: instagram_posts(c, TOKEN, "ada"),
        lambda n, more: {
            "items": [{"code": f"C{n}", "id": str(n), "taken_at": 1753361074, "caption": {}}],
            "more_available": more,
            "next_max_id": f"m{n + 1}" if more else None,
        },
        {"success": False, "message": "Something went wrong, please try again"},
    ),
    Reader(
        "facebook",
        lambda c: facebook_posts(c, TOKEN, "https://www.facebook.com/ada"),
        lambda n, more: {
            "posts": [{"id": str(n), "text": f"post {n}", "creation_time": "2026-11-09"}],
            "cursor": f"c{n + 1}" if more else None,
        },
        {"success": False, "message": "Something went wrong, please try again"},
    ),
    Reader(
        "company",
        lambda c: company_linkedin_posts(c, TOKEN, "https://www.linkedin.com/company/acme/"),
        # Company pages page back by date; a second page is asked whenever the first has posts.
        lambda n, more: {"code": 200, "data": {"data": [co_post(str(n), f"2026-10-{n:02d}")]}},
        {"code": 500, "message": "Internal error", "data": None},
    ),
]
by_name = pytest.mark.parametrize("reader", READERS, ids=lambda r: r.name)


def treg_refusal(status, detail):
    return HttpResponse(
        status,
        {"content-type": "application/json", "X-Treg-Error": "1"},
        json.dumps({"detail": detail}).encode(),
    )


def rate_limited():
    # A provider's 429 relayed through treg, in treg's wrapping.
    return body({"detail": {"code": 429, "message": "Too many requests"}}, 429, "0")


def not_data():
    return HttpResponse(200, {"content-type": "text/html"}, b"<html>502 Bad Gateway</html>")


def every_attempt(reply):
    """The spend wrapper retries a rate limit and a dropped connection (4 attempts in all)."""
    retried = isinstance(reply, TransportFailure) or getattr(reply, "status", 0) == 429
    return [reply] * 4 if retried else [reply]


# --- The first page fails: nothing was read, and nothing is known about the person -------------


@by_name
@pytest.mark.parametrize(
    ("reply", "says"),
    [
        (rate_limited, "HTTP 429: Too many requests"),
        (not_data, "was not data"),
        (lambda: treg_refusal(403, "capability_pinned"), "treg refused HTTP 403"),
    ],
    ids=["rate_limited", "not_data", "treg_refused"],
)
def test_first_page_failure_is_unavailable_with_the_reason(reader, reply, says):
    caller, _ = wire(*every_attempt(reply()))
    history = reader.read(caller)
    assert history.state == "unavailable" and history.posts == []
    assert len(history.gaps) == 1 and "page 1" in history.gaps[0] and says in history.gaps[0]
    assert history.halted is None


@by_name
def test_a_200_carrying_an_error_is_a_failure_not_zero_posts(reader):
    caller, _ = wire(body(reader.error_envelope))
    history = reader.read(caller)
    assert history.state == "unavailable" and history.posts == []
    assert "page 1" in history.gaps[0]


@by_name
def test_out_of_credit_is_unavailable_and_stops_treg(reader):
    caller, transport = wire(treg_refusal(402, "insufficient_balance"))
    history = reader.read(caller)
    assert history.state == "unavailable" and history.posts == []
    assert "out of credit" in history.gaps[0] and history.halted == "payment_required"
    assert len(transport.requests) == 1


@by_name
def test_refused_key_is_unavailable_and_stops_treg(reader):
    caller, _ = wire(treg_refusal(401, "invalid token"))
    history = reader.read(caller)
    assert history.state == "unavailable" and history.halted == "auth_invalid"
    assert "refused our key" in history.gaps[0]


@by_name
def test_provider_not_answering_is_unavailable(reader):
    caller, _ = wire(*[TransportFailure("connection reset")] * 4)
    history = reader.read(caller)
    assert history.state == "unavailable" and "did not answer" in history.gaps[0]


# --- A later page fails: what was read is kept, and the history says it is incomplete ----------


@by_name
@pytest.mark.parametrize(
    ("reply", "says"),
    [
        (rate_limited, "HTTP 429"),
        (not_data, "was not data"),
        (lambda: treg_refusal(402, "insufficient_balance"), "out of credit"),
        (lambda: TransportFailure("connection reset"), "did not answer"),
    ],
    ids=["rate_limited", "not_data", "out_of_credit", "no_answer"],
)
def test_later_page_failure_is_partial_and_keeps_the_posts(reader, reply, says):
    caller, _ = wire(body(reader.page(1, True)), *every_attempt(reply()))
    history = reader.read(caller)
    assert history.state == "partial" and len(history.posts) == 1
    assert "page 2" in history.gaps[0] and says in history.gaps[0]


@by_name
def test_a_later_200_carrying_an_error_is_partial(reader):
    caller, _ = wire(body(reader.page(1, True)), body(reader.error_envelope))
    history = reader.read(caller)
    assert history.state == "partial" and len(history.posts) == 1


def test_later_page_saying_not_found_is_partial_not_an_answer():
    """An answer about the account only counts on the first page: a not-found after posts were
    read (here fetchinio refusing a page token) means the reading stopped, not that the person is
    gone."""
    lost = body({"error": "Pagination token not found", "code": "PROFILE_NOT_FOUND"}, 404, "0")
    caller, _ = wire(body(READERS[0].page(1, True)), lost)
    history = linkedin_activity(caller, TOKEN, "ada", "posts")
    assert history.state == "partial" and len(history.posts) == 1
    assert "not found" in history.gaps[0]


# --- Real answers about the account (shapes probed 2026-11-11) ---------------------------------


def test_linkedin_unknown_profile_is_not_found():
    unknown = {"error": "LinkedIn profile not found", "code": "PROFILE_NOT_FOUND"}
    for kind in ("posts", "reactions"):
        caller, _ = wire(body(unknown, 404, "0"))
        history = linkedin_activity(caller, TOKEN, "nobody", kind)
        assert history.state == "not_found" and history.gaps == []
        assert history.provider_said == "LinkedIn profile not found"


def test_facebook_unknown_account_is_not_found():
    unknown = {
        "success": True,
        "credits_charged": 0,
        "url": "https://www.facebook.com/nobody",
        "accountDoesNotExist": True,
        "isPrivate": False,
        "message": "Account doesn't exist",
    }
    caller, _ = wire(body(unknown, 404, "0"))
    history = facebook_posts(caller, TOKEN, "https://www.facebook.com/nobody")
    assert history.state == "not_found" and history.provider_said == "Account doesn't exist"


def test_facebook_private_message_is_private():
    caller, _ = wire(body({"success": True, "message": "Profile is private"}, 404, "0"))
    assert facebook_posts(caller, TOKEN, "https://www.facebook.com/lisa").state == "private"


def test_company_unknown_page_is_not_found():
    unknown = {"code": 200, "message": "Request successful.", "data": {"data": None}}
    caller, _ = wire(body(unknown, micro="1000"))
    assert company_linkedin_posts(caller, TOKEN, "acme").state == "not_found"


def test_company_no_older_posts_ends_the_history():
    caller, _ = wire(
        body(READERS[5].page(1, True)), body({"code": 200, "data": {"data": None}}, micro="1000")
    )
    history = company_linkedin_posts(caller, TOKEN, "acme")
    assert history.state == "complete" and len(history.posts) == 1


def test_x_unknown_handle_is_not_claimed_as_not_found():
    """TikHub answers an unknown handle with the same generic 400 it gives a bad request, so it is
    reported as a failure in the provider's words, with both readings named."""
    unknown = {"detail": {"code": 400, "message": "Request failed. Please retry. Check the docs."}}
    caller, _ = wire(body(unknown, 400, "0"))
    history = x_posts(caller, TOKEN, "zq81xnosuchuser7")
    assert history.state == "unavailable"
    assert "Request failed" in history.gaps[0] and "handle does not exist" in history.gaps[0]


# --- The provider says "more" but stops making progress ----------------------------------------


def test_empty_pages_while_the_provider_says_more_keep_reading():
    caller, _ = wire(
        body({"posts": [], "paginationToken": "p2", "hasMore": True}),
        body({"posts": [li_post(2, "2026-10-02T10:00:00Z")], "hasMore": False}),
    )
    history = linkedin_activity(caller, TOKEN, "ada", "posts")
    assert history.state == "complete" and len(history.posts) == 1 and history.pages == 2


def test_endless_empty_pages_stop_as_partial():
    pages = [
        body({"posts": [], "paginationToken": f"p{n}", "hasMore": True})
        for n in range(2, EMPTY_PAGES_IN_A_ROW + 3)
    ]
    caller, transport = wire(*pages)
    history = linkedin_activity(caller, TOKEN, "ada", "posts")
    assert history.state == "partial" and "empty pages" in history.gaps[0]
    assert len(transport.requests) == EMPTY_PAGES_IN_A_ROW


def test_repeated_page_marker_stops_as_partial():
    page = body(
        {"posts": [li_post(1, "2026-10-01T10:00:00Z")], "paginationToken": "p", "hasMore": True}
    )
    again = body(
        {"posts": [li_post(2, "2026-10-02T10:00:00Z")], "paginationToken": "p", "hasMore": True}
    )
    caller, _ = wire(page, again)
    history = linkedin_activity(caller, TOKEN, "ada", "posts")
    assert history.state == "partial" and "repeated" in history.gaps[0]
    assert len(history.posts) == 2


# --- Items of the wrong shape are left out and counted, never the whole page -------------------


def test_unreadable_items_are_counted_not_fatal():
    odd = {**li_post(2, "2026-10-02T10:00:00Z"), "author": "Ada Example"}  # author as a string
    caller, _ = wire(
        body({"posts": ["junk", None, li_post(1, "2026-10-01T10:00:00Z"), odd], "hasMore": False})
    )
    history = linkedin_activity(caller, TOKEN, "ada", "posts")
    assert history.state == "complete" and [p.post_id[-1] for p in history.posts] == ["1", "2"]
    assert history.gaps == ["page 1: 2 item(s) could not be read"]


def test_x_unreadable_timeline_items_are_counted():
    page = {"code": 200, "data": {"timeline": [None, tweet("1", "mine")], "next_cursor": None}}
    caller, _ = wire(body(page))
    history = x_posts(caller, TOKEN, "ada")
    assert len(history.posts) == 1 and history.gaps == ["page 1: 1 item(s) could not be read"]


# --- treg stopping while long quoted posts are read in full ------------------------------------


def test_out_of_credit_while_reading_quotes_marks_them_cut_and_stops_treg(monkeypatch):
    from clue_api.footprint import short_links

    monkeypatch.setattr(short_links, "WORKERS", 1)
    long_preview = "x" * 270
    quote = {**tweet("3", "So true"), "quoted": {**tweet("30", long_preview, "bob")}}
    other = {**tweet("4", "Also"), "quoted": {**tweet("40", long_preview, "bob")}}
    timeline = {"code": 200, "data": {"timeline": [quote, other], "next_cursor": None}}
    caller, transport = wire(body(timeline), treg_refusal(402, "insufficient_balance"))
    history = x_posts(caller, TOKEN, "ada")
    assert history.state == "complete" and history.halted == "payment_required"
    assert all(p.shared.text_may_be_cut for p in history.posts)
    assert len(transport.requests) == 2  # the second quote is not asked for
    assert any("treg stopped" in g for g in history.gaps)
