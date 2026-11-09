"""What a social history reader returns: every post it could fetch, and how far it got."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Platform = Literal["linkedin", "x", "instagram", "facebook"]
PostKind = Literal["own", "reaction", "repost", "company"]
HistoryState = Literal["complete", "partial", "private", "not_found", "unavailable"]


class Post(BaseModel):
    platform: Platform
    post_id: str
    url: str | None
    published_at: datetime | None
    text: str
    kind: PostKind
    author_name: str | None = None
    author_url: str | None = None
    video_urls: list[str] = Field(default_factory=list)
    #: Which provider page (0-based) this post came from, so it can be found in the saved pages.
    raw_ref: int = 0


class SocialHistory(BaseModel):
    """``complete``: every page the provider had. ``partial``: it stopped early and ``gap`` says
    where. ``private``/``not_found``: nothing to read, which is an answer, not an error."""

    state: HistoryState
    posts: list[Post]
    pages: int
    cost_usd: float
    earliest: datetime | None = None
    latest: datetime | None = None
    gap: str | None = None

    @classmethod
    def of(
        cls,
        posts: list[Post],
        *,
        pages: int,
        cost_usd: float,
        state: HistoryState,
        gap: str | None = None,
    ) -> SocialHistory:
        dates = [p.published_at for p in posts if p.published_at is not None]
        return cls(
            state=state,
            posts=posts,
            pages=pages,
            cost_usd=cost_usd,
            earliest=min(dates) if dates else None,
            latest=max(dates) if dates else None,
            gap=gap,
        )
