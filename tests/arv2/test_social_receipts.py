"""What the agent is handed for a social history: the receipt never calls a failure an answer.

A history that stopped part-way is ``completed`` with ``error_code=history_partial``; one where
nothing could be read is ``refused`` with ``history_unavailable`` (or ``provider_halted`` when treg
stopped selling); a private or unknown account is the provider's answer, named as such. The reason
is in the receipt's first preview line and in ``recovery``, so the agent reads it without opening
the file. Built here exactly as the tool builds it: the job's value, then the wrapper's settlement.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

from clue_api.arv2 import footprint_operations as ops
from clue_api.arv2.quality_provider_tools import (
    RETRY_ON_REPEAT,
    AcquireResearchToolV3,
    settle_outcome,
)
from clue_api.footprint.social_types import Post, SocialHistory


def post(n: int) -> Post:
    return Post(
        platform="x",
        post_id=str(n),
        url=f"https://x.com/ada/status/{n}",
        published_at=None,
        text=f"post {n}",
        kind="own",
    )


def receipt(history: SocialHistory) -> tuple[dict, dict]:
    value = ops._history(history)
    unknown, refused, code = settle_outcome(value)
    out = AcquireResearchToolV3(None).settled_receipt(
        uuid4(), value, unknown=unknown, refused=refused, code=code
    )
    return value, out.references


def test_complete_history_reads_as_before():
    value, got = receipt(
        SocialHistory.of([post(1), post(2)], pages=1, cost_usd=0, state="complete")
    )
    assert got["status"] == "completed" and got["error_code"] is None
    assert got["result_count"] == 2 and "report" not in value
    assert [h["title"] for h in got["preview"]] == ["post 1", "post 2"]


def test_partial_history_says_so_in_the_receipt():
    gap = "tikhub.x.user.posts stopped at page 7: the provider answered HTTP 429: Too many requests"
    history = SocialHistory.of([post(1)], pages=6, cost_usd=0, state="partial", gaps=[gap])
    value, got = receipt(history)
    assert got["status"] == "completed" and got["error_code"] == "history_partial"
    first = got["preview"][0]
    assert (
        first["title"] == "Report"
        and "page 7" in first["snippet"]
        and "HTTP 429" in first["snippet"]
    )
    assert "not the whole history" in first["snippet"]
    assert "same arguments" in got["recovery"]
    assert value["gaps"] == [gap] and value["state"] == "partial"


def test_unavailable_history_is_refused_with_the_reason():
    gap = "fetchinio.linkedin.user.posts stopped at page 1: the reply (HTTP 200) was not data"
    history = SocialHistory.of([], pages=0, cost_usd=0, state="unavailable", gaps=[gap])
    _, got = receipt(history)
    assert got["status"] == "refused" and got["error_code"] == "history_unavailable"
    assert "was not data" in got["preview"][0]["snippet"]
    assert "says nothing about the person" in got["preview"][0]["snippet"]
    assert "same arguments" in got["recovery"]


def test_treg_stopping_is_named_and_not_offered_again():
    gap = "tikhub.x.user.posts stopped at page 1 (treg stopped): treg is out of credit (HTTP 402)"
    history = SocialHistory.of(
        [], pages=0, cost_usd=0, state="unavailable", gaps=[gap], halted="payment_required"
    )
    _, got = receipt(history)
    assert got["status"] == "refused" and got["error_code"] == "provider_halted"
    assert "out of credit" in got["preview"][0]["snippet"]
    assert "same arguments" not in got["recovery"]
    assert "provider_halted" not in RETRY_ON_REPEAT


def test_not_found_is_the_providers_answer():
    history = SocialHistory.of(
        [], pages=1, cost_usd=0, state="not_found", provider_said="LinkedIn profile not found"
    )
    _, got = receipt(history)
    assert got["status"] == "refused" and got["error_code"] == "account_not_found"
    assert "LinkedIn profile not found" in got["preview"][0]["snippet"]


def test_private_is_the_providers_answer():
    history = SocialHistory.of(
        [], pages=1, cost_usd=0, state="private", provider_said="Profile is restricted"
    )
    _, got = receipt(history)
    assert got["status"] == "empty" and got["error_code"] == "account_private"
    assert "Profile is restricted" in got["preview"][0]["snippet"]


def test_complete_history_with_unreadable_items_mentions_them():
    history = SocialHistory.of(
        [post(1)],
        pages=1,
        cost_usd=0,
        state="complete",
        gaps=["page 1: 2 item(s) could not be read"],
    )
    _, got = receipt(history)
    assert got["status"] == "completed" and got["error_code"] is None
    assert "2 item(s) could not be read" in got["preview"][0]["snippet"]


def test_only_failures_are_retried_on_repeat():
    assert {"history_partial", "history_unavailable"} <= RETRY_ON_REPEAT
    assert not {"account_not_found", "account_private", "provider_halted"} & RETRY_ON_REPEAT


def test_treg_stopping_stops_every_later_treg_job():
    """The job latches treg the way it latches any provider that stops selling."""
    stopped = SocialHistory.of(
        [], pages=0, cost_usd=0, state="unavailable", gaps=["x"], halted="payment_required"
    )

    async def call_provider(provider, fn):
        assert provider == "treg"
        return stopped

    runtime = SimpleNamespace(
        call_provider=call_provider,
        clients=SimpleNamespace(treg_token="t"),
        settings=SimpleNamespace(treg_base_url="https://treg.to"),
        halted={},
    )
    asyncio.run(ops._x_posts(runtime, ops.XPostsArgs(handle="ada")))
    assert "out of credit" in runtime.halted["treg"]


def test_partial_history_with_no_posts_is_not_empty():
    gap = "fetchinio.linkedin.user.posts stopped at page 2: the provider answered HTTP 429"
    history = SocialHistory.of([], pages=1, cost_usd=0, state="partial", gaps=[gap])
    _, got = receipt(history)
    assert got["status"] == "refused" and got["error_code"] == "history_partial"


def test_a_post_by_another_account_names_its_author_in_the_preview():
    theirs = Post(
        platform="x",
        post_id="12",
        url="https://x.com/bob/status/12",
        published_at=None,
        text="Bob's own post",
        kind="in_feed",
        author_name="Bob",
    )
    _, got = receipt(SocialHistory.of([theirs], pages=1, cost_usd=0, state="complete"))
    assert got["preview"][0]["title"] == "Not this account's post, by Bob: Bob's own post"
