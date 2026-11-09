from datetime import UTC, datetime

from clue_api.footprint.social_types import Post, SocialHistory


def post(pid: str, when: datetime | None) -> Post:
    return Post(platform="linkedin", post_id=pid, url=None, published_at=when, text="t", kind="own")


def test_history_dates_follow_posts():
    early, late = datetime(2020, 1, 1, tzinfo=UTC), datetime(2026, 5, 1, tzinfo=UTC)
    history = SocialHistory.of(
        [post("a", late), post("b", None), post("c", early)],
        pages=2,
        cost_usd=0.003,
        state="complete",
    )
    assert history.earliest == early and history.latest == late
    assert history.pages == 2 and history.cost_usd == 0.003 and history.gap is None
    assert [p.post_id for p in history.posts] == ["a", "b", "c"]


def test_empty_history_has_no_dates():
    history = SocialHistory.of([], pages=1, cost_usd=0.0, state="private")
    assert history.earliest is None and history.latest is None and history.posts == []
