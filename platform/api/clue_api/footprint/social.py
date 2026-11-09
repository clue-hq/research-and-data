"""Read a person's or a company's whole public social history through treg.

Each reader pages until the provider has no further page and keeps every page it fetched. A
provider failing part-way returns what was read so far as ``partial`` with a gap naming the page;
a private or unknown account is an answer (``private`` / ``not_found``), not an error. There is no
page limit (founder rule: no pre-emptive caps); paging stops when the provider says there is no
more, or repeats itself.

Providers (ledger section 0a, tested 2026-11-09/10):
LinkedIn posts and reactions — fetchinio; X timeline — TikHub; Instagram and Facebook posts —
ScrapeCreators; company LinkedIn posts — TikHub (cheaper and five times denser than ScrapeCreators).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import SecretStr

from clue_api.footprint.social_types import Post, SocialHistory
from clue_api.footprint.treg_client import TREG_BASE_URL, TregReply, treg_call
from clue_spend.calls import ProviderCaller
from clue_spend.errors import ProviderTransportError

LINKEDIN_POSTS = "fetchinio.linkedin.user.posts"
LINKEDIN_REACTIONS = "fetchinio.linkedin.user.reactions"
X_TIMELINE = "tikhub.x.user.posts"
INSTAGRAM_POSTS = "scrapecreators.instagram.user.posts"
FACEBOOK_POSTS = "scrapecreators.x.v1-facebook-profile-posts"
COMPANY_LINKEDIN_POSTS = "tikhub.x.linkedin-web-v2-get-company-posts"

#: One page: the posts on it, the query for the next page (``None``: no more), and whether the
#: account turned out private or unknown.
Page = tuple[list[Post], dict[str, str | int] | None, Literal["private", "not_found"] | None]
Parse = Callable[[Any, int, int], Page]


def _date(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=UTC)
        text = str(value)
        for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%d %H:%M:%S"):
            try:
                parsed = datetime.strptime(text, fmt)
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            except ValueError:
                continue
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (ValueError, OverflowError, OSError):
        return None


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _history(
    caller: ProviderCaller,
    token: SecretStr,
    tool_id: str,
    first: dict[str, str | int],
    parse: Parse,
    base_url: str,
) -> SocialHistory:
    posts: list[Post] = []
    seen: set[str] = set()
    cost = 0.0
    pages = 0
    query: dict[str, str | int] | None = first
    while query is not None:
        try:
            reply: TregReply = treg_call(caller, token, tool_id, query, base_url=base_url)
        except ProviderTransportError as exc:
            gap = f"{tool_id} failed on page {pages + 1}: {exc}"
            state = "partial" if pages else "unavailable"
            return SocialHistory.of(posts, pages=pages, cost_usd=cost, state=state, gap=gap)
        cost += reply.cost_usd
        page_posts, following, closed = parse(reply.body, reply.status, pages)
        pages += 1
        if closed and not posts:
            return SocialHistory.of([], pages=pages, cost_usd=cost, state=closed)
        if reply.status >= 400 and not closed:
            gap = f"{tool_id} refused page {pages}: HTTP {reply.status}"
            state = "partial" if posts else "unavailable"
            return SocialHistory.of(posts, pages=pages, cost_usd=cost, state=state, gap=gap)
        fresh = [p for p in page_posts if p.post_id not in seen]
        seen.update(p.post_id for p in fresh)
        posts.extend(fresh)
        # A provider that hands back nothing new, or the same cursor again, has run out.
        query = following if fresh and following != query else None
    return SocialHistory.of(posts, pages=pages, cost_usd=cost, state="complete")


def _closed(body: Any, status: int) -> Literal["private", "not_found"] | None:
    if not isinstance(body, dict):
        return "not_found" if status == 404 else None
    message = str(body.get("message") or "").lower()
    if body.get("isPrivate") is True or body.get("account_status") == "private":
        return "private"
    if "restricted" in message or "private" in message:
        return "private"
    if status == 404 or body.get("error") == "not_found" or "not found" in message:
        return "not_found"
    return None


# --- LinkedIn (fetchinio) ----------------------------------------------------------------------


def _li_post(item: dict[str, Any], *, kind: Literal["own", "reaction"], page: int) -> Post | None:
    author = item.get("author") or item.get("profile") or {}
    pid = _str(item.get("id")) or _str(item.get("shareUrn"))
    if pid is None:
        return None
    video = _str(item.get("videoUrl"))
    return Post(
        platform="linkedin",
        post_id=pid,
        url=_str(item.get("shareUrl")),
        published_at=_date(item.get("date")),
        text=_str(item.get("content")) or "",
        kind=kind,
        author_name=_str(author.get("name")),
        author_url=_str(author.get("url")),
        video_urls=[video] if video else [],
        raw_ref=page,
    )


def linkedin_activity(
    caller: ProviderCaller,
    token: SecretStr,
    profile: str,
    kind: Literal["posts", "reactions"],
    *,
    base_url: str = TREG_BASE_URL,
) -> SocialHistory:
    first: dict[str, str | int] = {"profileUrlOrUrn": profile, "count": 50}

    def parse(body: Any, status: int, page: int) -> Page:
        if not isinstance(body, dict) or status >= 400:
            return [], None, _closed(body, status)
        posts: list[Post] = []
        if kind == "posts":
            for item in body.get("posts") or []:
                post = _li_post(item, kind="own", page=page)
                if post:
                    posts.append(post)
        else:
            for item in body.get("reactions") or []:
                liked = item.get("post") or {}
                post = _li_post(liked, kind="reaction", page=page)
                if post:
                    reacted = _date(item.get("createdAt"))
                    posts.append(
                        post.model_copy(update={"published_at": reacted or post.published_at})
                    )
        token_ = _str(body.get("paginationToken"))
        following = {**first, "paginationToken": token_} if body.get("hasMore") and token_ else None
        return posts, following, None

    tool = LINKEDIN_POSTS if kind == "posts" else LINKEDIN_REACTIONS
    return _history(caller, token, tool, first, parse, base_url)


# --- X (TikHub) --------------------------------------------------------------------------------


def _best_mp4(media: Any) -> list[str]:
    urls: list[str] = []
    for video in (media or {}).get("video") or [] if isinstance(media, dict) else []:
        mp4s = [
            v
            for v in (video.get("variants") or [])
            if v.get("content_type") == "video/mp4" and _str(v.get("url"))
        ]
        if mp4s:
            urls.append(max(mp4s, key=lambda v: v.get("bitrate") or 0)["url"])
    return urls


def x_posts(
    caller: ProviderCaller, token: SecretStr, handle: str, *, base_url: str = TREG_BASE_URL
) -> SocialHistory:
    handle = handle.lstrip("@")
    first: dict[str, str | int] = {"screen_name": handle}

    def parse(body: Any, status: int, page: int) -> Page:
        data = body.get("data") if isinstance(body, dict) else None
        if status >= 400 or not isinstance(data, dict):
            return [], None, _closed(body, status) or "not_found"
        posts: list[Post] = []
        for item in data.get("timeline") or []:
            tid = _str(str(item.get("tweet_id") or "")) or None
            if tid is None:
                continue
            author = item.get("author") or {}
            screen = _str(author.get("screen_name")) or handle
            text = _str(item.get("text")) or ""
            repost = text.startswith("RT @") or screen.lower() != handle.lower()
            posts.append(
                Post(
                    platform="x",
                    post_id=tid,
                    url=f"https://x.com/{screen}/status/{tid}",
                    published_at=_date(item.get("created_at")),
                    text=text,
                    kind="repost" if repost else "own",
                    author_name=_str(author.get("name")),
                    author_url=f"https://x.com/{screen}",
                    video_urls=_best_mp4(item.get("media")),
                    raw_ref=page,
                )
            )
        cursor = _str(data.get("next_cursor"))
        return posts, ({**first, "cursor": cursor} if cursor else None), None

    return _history(caller, token, X_TIMELINE, first, parse, base_url)


# --- Instagram and Facebook (ScrapeCreators) ---------------------------------------------------


def instagram_posts(
    caller: ProviderCaller, token: SecretStr, handle: str, *, base_url: str = TREG_BASE_URL
) -> SocialHistory:
    handle = handle.lstrip("@")
    first: dict[str, str | int] = {"handle": handle}

    def parse(body: Any, status: int, page: int) -> Page:
        closed = _closed(body, status)
        if closed or not isinstance(body, dict) or status >= 400:
            return [], None, closed
        posts: list[Post] = []
        for item in body.get("items") or []:
            code = _str(item.get("code"))
            pid = _str(str(item.get("id") or "")) or code
            if pid is None:
                continue
            caption = item.get("caption") if isinstance(item.get("caption"), dict) else {}
            versions = item.get("video_versions") or []
            video = _str(versions[0].get("url")) if versions else _str(item.get("video_url"))
            user = item.get("user") or {}
            posts.append(
                Post(
                    platform="instagram",
                    post_id=pid,
                    url=f"https://www.instagram.com/p/{code}/" if code else None,
                    published_at=_date(item.get("taken_at")),
                    text=_str(caption.get("text")) or "",
                    kind="own",
                    author_name=_str(user.get("full_name")) or _str(user.get("username")),
                    author_url=f"https://www.instagram.com/{handle}/",
                    video_urls=[video] if video else [],
                    raw_ref=page,
                )
            )
        cursor = _str(body.get("next_max_id"))
        following = (
            {**first, "next_max_id": cursor} if body.get("more_available") and cursor else None
        )
        return posts, following, None

    return _history(caller, token, INSTAGRAM_POSTS, first, parse, base_url)


def facebook_posts(
    caller: ProviderCaller, token: SecretStr, profile: str, *, base_url: str = TREG_BASE_URL
) -> SocialHistory:
    first: dict[str, str | int] = {"url": profile}

    def parse(body: Any, status: int, page: int) -> Page:
        closed = _closed(body, status)
        if closed or not isinstance(body, dict) or status >= 400:
            return [], None, closed
        posts: list[Post] = []
        for item in body.get("posts") or []:
            pid = _str(str(item.get("id") or ""))
            if pid is None:
                continue
            details = item.get("videoDetails") or {}
            video = _str(details.get("hdUrl")) or _str(details.get("sdUrl"))
            author = item.get("author") or {}
            posts.append(
                Post(
                    platform="facebook",
                    post_id=pid,
                    url=_str(item.get("url")),
                    published_at=_date(item.get("creation_time") or item.get("publishTime")),
                    text=_str(item.get("text")) or "",
                    kind="own",
                    author_name=_str(author.get("name")),
                    author_url=profile,
                    video_urls=[video] if video else [],
                    raw_ref=page,
                )
            )
        cursor = _str(body.get("cursor"))
        return posts, ({**first, "cursor": cursor} if cursor else None), None

    return _history(caller, token, FACEBOOK_POSTS, first, parse, base_url)


# --- Company LinkedIn page (TikHub) -------------------------------------------------------------


def company_linkedin_posts(
    caller: ProviderCaller, token: SecretStr, company: str, *, base_url: str = TREG_BASE_URL
) -> SocialHistory:
    """TikHub returns about 50 posts newest first and takes no cursor; the next page asks for
    posts up to the oldest date seen, and paging stops when a page brings nothing new."""
    first: dict[str, str | int] = {"url": company}

    def parse(body: Any, status: int, page: int) -> Page:
        outer = body.get("data") if isinstance(body, dict) else None
        rows = outer.get("data") if isinstance(outer, dict) else None
        if status >= 400 or not isinstance(rows, list):
            return [], None, _closed(body, status) or "not_found"
        posts: list[Post] = []
        for item in rows:
            urn = _str(str(item.get("urn") or item.get("share_urn") or ""))
            if urn is None:
                continue
            poster = item.get("poster") or {}
            posts.append(
                Post(
                    platform="linkedin",
                    post_id=urn,
                    url=_str(item.get("url")),
                    published_at=_date(item.get("posted")),
                    text=_str(item.get("text")) or "",
                    kind="company",
                    author_name=_str(poster.get("name")),
                    author_url=company,
                    raw_ref=page,
                )
            )
        dates = [p.published_at for p in posts if p.published_at]
        following = {**first, "end_date": min(dates).strftime("%Y-%m-%d")} if dates else None
        return posts, following, None

    return _history(caller, token, COMPANY_LINKEDIN_POSTS, first, parse, base_url)
