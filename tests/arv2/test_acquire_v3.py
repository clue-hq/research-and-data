"""acquire_research_evidence version 3: new footprint jobs; versions 1 and 2 stay as pinned."""

from __future__ import annotations

from pathlib import Path

import yaml

from clue_api.arv2.quality_provider_tools import (
    ACQUISITIONS,
    ACQUISITIONS_V3,
    AcquireResearchToolV2,
    AcquireResearchToolV3,
)
from clue_api.quality_research_wiring import CATALOG_ROOT, quality_tools

FOOTPRINT_JOBS = {
    "find_podcasts",
    "find_videos",
    "find_handles",
    "linkedin_activity",
    "x_posts",
    "instagram_posts",
    "facebook_posts",
    "company_linkedin_posts",
}


def test_v2_schema_fingerprint_unchanged():
    profile = yaml.safe_load(
        (
            Path(CATALOG_ROOT) / "profiles/quality-person-research/v30-person/profile.yaml"
        ).read_text()
    )
    pin = next(t for t in profile["tools"] if t["name"] == "acquire_research_evidence")
    descriptor = quality_tools(None, None, purge=False).descriptor("acquire_research_evidence", "2")
    assert pin["version"] == "2"
    assert descriptor.input_schema_sha256 == pin["input_schema_sha256"]
    assert descriptor.output_schema_sha256 == pin["output_schema_sha256"]


def test_v3_job_names():
    assert (ACQUISITIONS - {"discover_media"}) | FOOTPRINT_JOBS == ACQUISITIONS_V3
    assert AcquireResearchToolV3.version == "3" and AcquireResearchToolV2.version == "2"


def test_v3_registered_beside_v1_and_v2():
    registry = quality_tools(None, None, purge=False)
    assert {"1", "2", "3"} <= set(registry.versions("acquire_research_evidence"))


def test_preview_shows_the_original_of_a_repost():
    from datetime import UTC, datetime

    from clue_api.arv2.footprint_operations import _history
    from clue_api.footprint.social_types import Post, SharedPost, SocialHistory

    when = datetime(2026, 11, 6, tzinfo=UTC)
    original = SharedPost(
        post_id="20", url="https://x.com/bob/status/20", author_name="Bob", text="Bob's words"
    )
    reposted = Post(
        platform="x",
        post_id="2",
        url="u",
        published_at=when,
        text="",
        kind="repost",
        shared=original,
    )
    quoted = reposted.model_copy(update={"post_id": "3", "text": "Very nice", "kind": "own"})
    value = _history(SocialHistory.of([reposted, quoted], pages=1, cost_usd=0, state="complete"))
    titles = sorted(r["title"] for r in value["results"])
    assert titles == ["Reposted from Bob: Bob's words", "Very nice (quoting Bob: Bob's words)"]
    assert value["posts"][0]["shared"]["text"] == "Bob's words"


def test_podcast_and_video_jobs_take_the_agents_own_searches():
    import pytest
    from pydantic import ValidationError

    from clue_api.arv2.footprint_operations import FindPodcastsArgs, FindVideosArgs

    for model in (FindPodcastsArgs, FindVideosArgs):
        searches = ['"Mike McNeil" podcast', "Fleet Device Management CEO panel"]
        assert model(queries=searches).queries == searches
        with pytest.raises(ValidationError):
            model(name="Mike McNeil", company="Fleet")
        with pytest.raises(ValidationError):
            model(queries=[])


def test_exa_podcast_search_is_limited_to_the_podcast_index():
    from types import SimpleNamespace

    import pytest

    from clue_api.arv2.footprint_operations import _exa_podcasts

    asked = []

    class FakeExa:
        def search(self, query, **kw):
            asked.append((query, kw))
            return SimpleNamespace(status=asked[-1][0] == "down" and 500 or 200, results=("hit",))

    runtime = SimpleNamespace(clients=SimpleNamespace(exa=lambda caller: FakeExa()))
    search = _exa_podcasts(runtime, caller=None)
    assert search('"Ada Example"') == ("hit",)
    query, kw = asked[0]
    assert kw["include_domains"] == ["exa.ai/library/podcast"]
    assert kw["highlights"]["query"] == '"Ada Example"' and kw["num_results"] == 20
    with pytest.raises(ValueError, match="500"):
        search("down")
    assert _exa_podcasts(SimpleNamespace(clients=SimpleNamespace()), caller=None) is None
