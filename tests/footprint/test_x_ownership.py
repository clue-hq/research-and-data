"""Whose tweet is it (review I6): decided by X's permanent account id, never the handle typed.

TikHub's timeline names the account (``data.user.rest_id``, ``data.user.profile``) and every
tweet's author (``author.rest_id``). A retweet is one only when X marks it (``retweeted_tweet``, or
X's "RT @" text); a tweet by another account that is not a retweet stays theirs, marked
``in_feed``. Shapes as in the r44a trial's saved pages.
"""

from __future__ import annotations

from clue_api.footprint.social import X_MAY_BE_CUT, x_posts
from tests.footprint.test_social import TOKEN, body, tweet, wire


def by(rest_id, screen, tid, text, **extra):
    return {
        **tweet(tid, text, screen),
        "author": {"rest_id": rest_id, "screen_name": screen, "name": screen.title()},
        **extra,
    }


def page(*items, user=("1", "ada")):
    return body(
        {
            "code": 200,
            "data": {
                "timeline": list(items),
                "next_cursor": None,
                "status": "ok",
                "user": {"rest_id": user[0], "profile": user[1], "status": "active"},
            },
        }
    )


def test_a_renamed_handle_still_reads_the_persons_own_tweets():
    caller, _ = wire(page(by("1", "ada_new", "10", "my own words"), user=("1", "ada_new")))
    post = x_posts(caller, TOKEN, "ada_old").posts[0]
    assert post.kind == "own" and post.text == "my own words"
    assert post.url == "https://x.com/ada_new/status/10"


def test_a_long_quote_in_an_own_tweet_is_read_in_full_after_a_rename(monkeypatch):
    from clue_api.footprint import short_links
    from tests.footprint.test_social import tweet_detail

    monkeypatch.setattr(short_links, "WORKERS", 1)
    preview = "x" * (X_MAY_BE_CUT + 20)
    quoted = by("2", "bob", "30", preview)
    own = by("1", "ada_new", "10", "So true", quoted=quoted)
    caller, transport = wire(
        page(own, user=("1", "ada_new")), tweet_detail(preview + " and the rest")
    )
    post = x_posts(caller, TOKEN, "ada_old").posts[0]
    assert post.kind == "own" and post.shared.text == preview + " and the rest"
    assert not post.shared.text_may_be_cut and len(transport.requests) == 2


def test_a_retweet_is_one_only_when_x_marks_it():
    original = by("2", "bob", "20", "Bob's words")
    retweet = by("1", "ada", "11", "RT @bob: Bob's wor…", retweeted_tweet=original)
    caller, _ = wire(page(retweet))
    post = x_posts(caller, TOKEN, "ada").posts[0]
    assert post.kind == "repost" and post.text == "" and post.shared.text == "Bob's words"


def test_another_accounts_tweet_in_the_timeline_keeps_its_author():
    caller, _ = wire(page(by("1", "ada", "10", "mine"), by("2", "bob", "12", "Bob's own post")))
    posts = x_posts(caller, TOKEN, "ada").posts
    assert [p.kind for p in posts] == ["own", "in_feed"]
    assert posts[1].text == "Bob's own post" and posts[1].author_name == "Bob"
    assert posts[1].url == "https://x.com/bob/status/12"


def test_without_ids_the_timelines_own_account_name_decides():
    no_ids = {**tweet("10", "mine", "ada_new"), "author": {"screen_name": "ada_new", "name": "Ada"}}
    caller, _ = wire(
        body(
            {
                "code": 200,
                "data": {"timeline": [no_ids], "next_cursor": None, "user": {"profile": "ada_new"}},
            }
        )
    )
    assert x_posts(caller, TOKEN, "ada_old").posts[0].kind == "own"
