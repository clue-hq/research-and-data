"""What the agent is handed for a podcast or video search (review findings I2, I3).

Problems are on the receipt's first preview line; a search where some calls failed is
``completed`` with ``searches_partial``; one where none answered is ``refused`` with
``searches_unavailable``, never "empty"; "empty" means every search ran and found nothing. Exa out
of credit is latched for the job as Exa only, and an Exa already stopped is not asked.
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
from clue_api.footprint.search_tally import SourceStopped, Tally
from clue_api.footprint.video_search import VideoLead
from clue_spend.errors import ProviderHalted


def lead(n: int) -> VideoLead:
    return VideoLead(
        video_id=f"v{n:010d}", url=f"https://www.youtube.com/watch?v=v{n:010d}", source="youtube"
    )


def runtime(found, *, halted=None, exa=None):
    async def call_provider(provider, fn):
        return fn(None) if callable(found) else found

    return SimpleNamespace(
        call_provider=call_provider,
        clients=SimpleNamespace(exa=exa),
        settings=SimpleNamespace(),
        halted=dict(halted or {}),
    )


def receipt(value):
    unknown, refused, code = settle_outcome(value)
    return (
        AcquireResearchToolV3(None)
        .settled_receipt(uuid4(), value, unknown=unknown, refused=refused, code=code)
        .references
    )


def videos(rt):
    return asyncio.run(ops._find_videos(rt, ops.FindVideosArgs(queries=["one", "two"])))


def test_partial_search_is_completed_with_the_problems_shown():
    tally = Tally(answered=1)
    tally.fail("YouTube search [2] 'two' failed (YouTube HTTP 500); tried on Exa.")
    value = videos(runtime(([lead(1)], tally)))
    got = receipt(value)
    assert got["status"] == "completed" and got["error_code"] == "searches_partial"
    assert "HTTP 500" in got["preview"][0]["snippet"]
    assert "same arguments" in got["recovery"]


def test_no_search_answering_is_refused_not_empty():
    tally = Tally()
    tally.fail("YouTube search [1] 'one' failed (YouTube did not answer); tried on Exa.")
    value = videos(runtime(([], tally)))
    got = receipt(value)
    assert got["status"] == "refused" and got["error_code"] == "searches_unavailable"
    assert "did not answer" in got["preview"][0]["snippet"]


def test_searches_that_found_nothing_are_empty():
    value = videos(runtime(([], Tally(answered=2))))
    got = receipt(value)
    assert got["status"] == "empty" and got["error_code"] is None


def test_search_failures_are_retried_on_repeat():
    assert {"searches_partial", "searches_unavailable"} <= RETRY_ON_REPEAT


def test_exa_stopping_is_latched_for_the_job_as_exa_only():
    tally = Tally(answered=1)
    tally.stop("exa", "payment_required", "Exa stopped selling at search [1].")
    rt = runtime(([lead(1)], tally))
    videos(rt)
    assert set(rt.halted) == {"exa"} and "payment_required" in rt.halted["exa"]


class _Exa:
    """Exa's client as the jobs use it: ``exa(caller).search(...)`` returns hits and a status."""

    def __init__(self, status=200, raises=None):
        self.status, self.raises, self.asked = status, raises, []

    def __call__(self, caller):
        return self

    def search(self, query, **kwargs):
        self.asked.append(query)
        if self.raises:
            raise self.raises
        return SimpleNamespace(
            status=self.status, results=[SimpleNamespace(url="https://youtu.be/aaaaaaaaaaa")]
        )


def test_video_exa_fallback_checks_the_status():
    exa = _Exa(status=429)
    search = ops._exa_videos(SimpleNamespace(clients=SimpleNamespace(exa=exa), halted={}), None)
    try:
        search("one")
    except ValueError as exc:
        assert "429" in str(exc)
    else:
        raise AssertionError("an Exa 429 must not read as zero results")


def test_exa_out_of_credit_becomes_source_stopped():
    halted = ProviderHalted("exa", "payment_required", ledger_row_id=None)
    exa = _Exa(raises=halted)
    rt = SimpleNamespace(clients=SimpleNamespace(exa=exa), halted={})
    for make in (ops._exa_videos, ops._exa_podcasts):
        try:
            make(rt, None)("one")
        except SourceStopped as stop:
            assert stop.provider == "exa" and "payment_required" in stop.reason
        else:
            raise AssertionError("Exa out of credit must stop Exa")


def test_exa_stopped_earlier_in_the_job_is_not_asked():
    exa = _Exa()
    rt = SimpleNamespace(clients=SimpleNamespace(exa=exa), halted={"exa": "out of credit"})
    for make in (ops._exa_videos, ops._exa_podcasts):
        try:
            make(rt, None)("one")
        except SourceStopped as stop:
            assert "earlier in this job" in stop.reason
        else:
            raise AssertionError("an Exa stopped earlier must not be asked")
    assert exa.asked == []
