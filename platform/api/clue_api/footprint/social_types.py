"""What a social history reader returns: every post it could fetch, and how far it got."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Platform = Literal["linkedin", "x", "instagram", "facebook"]
PostKind = Literal["own", "reaction", "repost", "company"]
HistoryState = Literal["complete", "partial", "private", "not_found", "unavailable"]


class SharedPost(BaseModel):
    """Someone else's post that this one reposts, quotes or reshares, in full and with its author.
    Its words are that author's, never the person's."""

    post_id: str | None = None
    url: str | None = None
    author_name: str | None = None
    author_url: str | None = None
    published_at: datetime | None = None
    text: str
    video_urls: list[str] = Field(default_factory=list)
    #: Each short link in ``text`` (``t.co``, ``lnkd.in``) and the address it leads to.
    links: dict[str, str] = Field(default_factory=dict)
    #: The provider's copy may stop short and the full post could not be read: read it at ``url``.
    text_may_be_cut: bool = False


class LinkCard(BaseModel):
    """The link preview a post carries (title and address of the linked page)."""

    title: str | None = None
    url: str


class Mention(BaseModel):
    """A person or company tagged in the post."""

    name: str
    url: str | None = None


class Post(BaseModel):
    platform: Platform
    post_id: str
    url: str | None
    published_at: datetime | None
    #: Only the words of this post's author (for a reaction, the author of the liked post). A plain
    #: repost has none (``""``); what was reposted, quoted or reshared is in ``shared``.
    text: str
    kind: PostKind
    author_name: str | None = None
    author_url: str | None = None
    video_urls: list[str] = Field(default_factory=list)
    shared: SharedPost | None = None
    #: The id of the post this one replies to (X).
    reply_to_id: str | None = None
    link: LinkCard | None = None
    mentions: list[Mention] = Field(default_factory=list)
    #: Each short link in ``text`` (``t.co``, ``lnkd.in``) and the address it leads to. ``text``
    #: itself is never changed.
    links: dict[str, str] = Field(default_factory=dict)
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
