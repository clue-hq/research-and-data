"""Read a person's or a company's whole public social history through treg.

Each reader pages until the provider says it has no further page and keeps every page it fetched.
What happened is reported plainly (``SocialHistory``), because the agent takes the state at its
word:

- ``complete`` only when the provider said there were no more pages.
- ``private`` / ``not_found`` only when the provider said so about this account, on the first page,
  in a reply recognised below from its real shape (probed 2026-11-11). X has no such reply: an
  unknown handle gets TikHub's generic "Request failed" 400, which is reported as a failure.
- Anything else that is not posts — our credit or key refused by treg, a rate limit, a provider
  fault, a 200 carrying an error, a reply that is not data — is a failure: ``unavailable`` on the
  first page, ``partial`` (posts so far kept) on a later one, with the reason in ``gaps``.
- treg out of credit, or our key refused, also sets ``halted`` so the job stops calling treg.

There is no page limit (founder rule: no pre-emptive caps); paging stops when the provider says
there is no more. A provider that repeats its next-page marker, or that keeps saying "more" while
sending empty pages, has stopped making progress: that is reported as ``partial``, not complete.

Providers (ledger section 0a, tested 2026-11-09/10):
LinkedIn posts and reactions — fetchinio; X timeline — TikHub; Instagram and Facebook posts —
ScrapeCreators; company LinkedIn posts — TikHub (cheaper and five times denser than ScrapeCreators).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import SecretStr

from clue_api.footprint import short_links
from clue_api.footprint.social_types import (
    HistoryState,
    LinkCard,
    Mention,
    Post,
    PostKind,
    SharedPost,
    SocialHistory,
)
from clue_api.footprint.treg_client import TREG_BASE_URL, TregReply, treg_call
from clue_spend.calls import ProviderCaller
from clue_spend.errors import ProviderHalted, ProviderTransportError

LINKEDIN_POSTS = "fetchinio.linkedin.user.posts"
LINKEDIN_REACTIONS = "fetchinio.linkedin.user.reactions"
X_TIMELINE = "tikhub.x.user.posts"
INSTAGRAM_POSTS = "scrapecreators.instagram.user.posts"
FACEBOOK_POSTS = "scrapecreators.x.v1-facebook-profile-posts"
COMPANY_LINKEDIN_POSTS = "tikhub.x.linkedin-web-v2-get-company-posts"
X_TWEET = "tikhub.x.twitter-web-fetch-tweet-detail"
#: TikHub's copy of a quoted post holds only its first ~280 characters by X's count (checked
#: 2026-11-10). A quoted post this long or longer may be cut, so it is read in full on its own.
X_MAY_BE_CUT = 250

#: A provider that says "more" but sends this many empty pages in a row has stopped making
#: progress; the reading stops and says so (loop detection, not a limit on the history).
EMPTY_PAGES_IN_A_ROW = 3


@dataclass(frozen=True)
class PageRead:
    """What one provider page turned out to be. Exactly one of: posts (with ``following``, the
    query for the next page, or ``None`` when the provider has no more), ``closed`` (the provider
    said the account is private or unknown, in ``said``), or ``failure`` (why it is not an
    answer)."""

    posts: list[Post] = field(default_factory=list)
    following: dict[str, str | int] | None = None
    closed: Literal["private", "not_found"] | None = None
    said: str | None = None
    failure: str | None = None
    #: Items on the page that could not be read (wrong shape) and were left out.
    unreadable: int = 0


Parse = Callable[[TregReply, int], PageRead]


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


def _id(value: Any) -> str | None:
    return _str(str(value)) if isinstance(value, (str, int)) and value != "" else None


def _bare(url: str | None) -> str | None:
    """A profile link without its tracking query (``?miniProfileUrn=…``)."""
    return url.split("?", 1)[0] if url else None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _message(body: Any) -> str | None:
    """The provider's own words in a reply, wherever it put them, cut to a readable length."""
    if isinstance(body, str):
        text = " ".join(body.split())
        return text[:200] or None
    if not isinstance(body, dict):
        return None
    detail = body.get("detail")
    for value in (
        detail.get("message") if isinstance(detail, dict) else detail,
        body.get("message"),
        body.get("error"),
    ):
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())[:200]
    return None


def _refusal(reply: TregReply) -> str:
    """Why a reply that is not posts is not an answer, in plain words."""
    said = _message(reply.body)
    who = "treg refused" if reply.treg_error else "the provider answered"
    return f"{who} HTTP {reply.status}" + (f": {said}" if said else "")


def _not_data(reply: TregReply) -> str | None:
    """The shared failures: a refusal (any 4xx not recognised as an answer about the account)
    or a reply that is not data at all."""
    if reply.status >= 400:
        return _refusal(reply)
    if not isinstance(reply.body, dict):
        said = _message(reply.body)
        return f"the reply (HTTP {reply.status}) was not data" + (f": {said}" if said else "")
    return None


def _items(rows: Any, read: Callable[[dict[str, Any]], Post | None]) -> tuple[list[Post], int]:
    """Read each item; one of the wrong shape is left out and counted, never the whole page."""
    posts: list[Post] = []
    unreadable = 0
    for item in rows if isinstance(rows, list) else []:
        if not isinstance(item, dict):
            unreadable += 1
            continue
        try:
            post = read(item)
        except (AttributeError, KeyError, TypeError, ValueError):
            unreadable += 1
            continue
        if post is not None:
            posts.append(post)
    return posts, unreadable


def _history(
    caller: ProviderCaller,
    token: SecretStr,
    tool_id: str,
    first: dict[str, str | int],
    parse: Parse,
    base_url: str,
    *,
    ends_on_empty: bool,
) -> SocialHistory:
    """Page through one provider. ``ends_on_empty``: a page with nothing new means the history
    has run out (X, company pages); otherwise only the provider's own "no more" ends it."""
    posts: list[Post] = []
    seen: set[str] = set()
    gaps: list[str] = []
    cost = 0.0
    pages = 0
    empty_run = 0
    query: dict[str, str | int] | None = first

    def stopped(reason: str, *, halted: str | None = None) -> SocialHistory:
        state: HistoryState = "partial" if pages else "unavailable"
        where = f"page {pages + 1}" if not halted else f"page {pages + 1} (treg stopped)"
        gaps.insert(0, f"{tool_id} stopped at {where}: {reason}")
        return SocialHistory.of(
            posts, pages=pages, cost_usd=round(cost, 6), state=state, gaps=gaps, halted=halted
        )

    while query is not None:
        try:
            reply: TregReply = treg_call(caller, token, tool_id, query, base_url=base_url)
        except ProviderHalted as halted:
            reason = (
                "treg is out of credit (HTTP 402)"
                if halted.reason_code.endswith("payment_required")
                else f"treg refused our key ({halted.reason_code})"
            )
            return stopped(reason, halted=halted.reason_code.removeprefix("latched:"))
        except ProviderTransportError as exc:
            return stopped(f"the provider did not answer ({exc})")
        cost += reply.cost_usd
        try:
            read = parse(reply, pages)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            read = PageRead(failure=f"the reply could not be read ({type(exc).__name__})")
        if read.closed is not None:
            if pages == 0:
                return SocialHistory.of(
                    [],
                    pages=1,
                    cost_usd=round(cost, 6),
                    state=read.closed,
                    provider_said=read.said,
                )
            read = PageRead(
                failure=f"the provider said the account is {read.closed.replace('_', ' ')}"
                + (f" ({read.said})" if read.said else "")
            )
        if read.failure is not None:
            return stopped(read.failure)
        pages += 1
        if read.unreadable:
            gaps.append(f"page {pages}: {read.unreadable} item(s) could not be read")
        fresh = [p for p in read.posts if p.post_id not in seen]
        seen.update(p.post_id for p in fresh)
        posts.extend(fresh)
        following = read.following
        if following is None or (ends_on_empty and not fresh):
            break
        if following == query:
            return stopped("the provider repeated the previous page's next-page marker")
        empty_run = 0 if fresh else empty_run + 1
        if empty_run >= EMPTY_PAGES_IN_A_ROW:
            return stopped(
                f"the provider said there was more but sent {empty_run} empty pages in a row"
            )
        query = following
    return SocialHistory.of(
        posts, pages=pages, cost_usd=round(cost, 6), state="complete", gaps=gaps
    )


def _with_links(history: SocialHistory, known: dict[str, str] | None = None) -> SocialHistory:
    """Name the address behind every short link in the posts and what they share. ``known``
    holds addresses the provider already sent; only the rest are opened (free, not a provider
    call). Links that could not be opened stay as written and are counted in ``gaps``."""
    known = dict(known or {})
    texts = [p.text for p in history.posts] + [p.shared.text for p in history.posts if p.shared]
    wanted = {link for text in texts for link in short_links.short_links(text)} - known.keys()
    opened = short_links.expand(wanted)
    known.update(opened.addresses)

    def found(text: str) -> dict[str, str]:
        return {s: known[s] for s in short_links.short_links(text) if s in known}

    posts = []
    for post in history.posts:
        shared = post.shared
        if shared is not None:
            shared = shared.model_copy(update={"links": found(shared.text)})
        posts.append(post.model_copy(update={"links": found(post.text), "shared": shared}))
    gaps = list(history.gaps)
    if opened.failed:
        gaps.append(
            f"{opened.failed} of {len(wanted)} short link(s) could not be opened; "
            "they are left as written"
        )
    return history.model_copy(update={"posts": posts, "gaps": gaps})


# --- LinkedIn (fetchinio) ----------------------------------------------------------------------


def _li_shared(item: Any) -> SharedPost | None:
    if not isinstance(item, dict):
        return None
    pid = _str(item.get("id")) or _str(item.get("shareUrn"))
    text = _str(item.get("content"))
    if pid is None and text is None:
        return None
    author = _dict(item.get("author")) or _dict(item.get("profile"))
    video = _str(item.get("videoUrl"))
    return SharedPost(
        post_id=pid,
        url=_str(item.get("shareUrl")),
        author_name=_str(author.get("name")),
        author_url=_bare(_str(author.get("url"))),
        published_at=_date(item.get("date")),
        text=text or "",
        video_urls=[video] if video else [],
    )


def _li_link(item: dict[str, Any]) -> LinkCard | None:
    article = item.get("article")
    if not isinstance(article, dict) or _str(article.get("link")) is None:
        return None
    return LinkCard(title=_str(article.get("title")), url=article["link"])


def _li_mentions(item: dict[str, Any]) -> list[Mention]:
    return [
        Mention(name=m["name"], url=_str(m.get("url")))
        for m in item.get("mentions") or []
        if isinstance(m, dict) and _str(m.get("name"))
    ]


def _li_post(item: dict[str, Any], *, kind: Literal["own", "reaction"], page: int) -> Post | None:
    author = _dict(item.get("author")) or _dict(item.get("profile"))
    pid = _str(item.get("id")) or _str(item.get("shareUrn"))
    if pid is None:
        return None
    video = _str(item.get("videoUrl"))
    text = _str(item.get("content")) or ""
    shared = _li_shared(item.get("resharedPost"))
    return Post(
        platform="linkedin",
        post_id=pid,
        url=_str(item.get("shareUrl")),
        published_at=_date(item.get("date")),
        text=text,
        # A reshare with no words of their own is a repost; with words, it is their post.
        kind="repost" if kind == "own" and shared and not text else kind,
        author_name=_str(author.get("name")),
        author_url=_bare(_str(author.get("url"))),
        video_urls=[video] if video else [],
        shared=shared,
        link=_li_link(item),
        mentions=_li_mentions(item),
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
    key = "posts" if kind == "posts" else "reactions"

    def liked(item: dict[str, Any], page: int) -> Post | None:
        post = _li_post(_dict(item.get("post")), kind="reaction", page=page)
        if post is None:
            return None
        reacted = _date(item.get("createdAt"))
        return post.model_copy(update={"published_at": reacted or post.published_at})

    def parse(reply: TregReply, page: int) -> PageRead:
        body = reply.body
        # fetchinio's answer for a profile that does not exist (probed 2026-11-11).
        if reply.status == 404 and _dict(body).get("code") == "PROFILE_NOT_FOUND":
            return PageRead(closed="not_found", said=_message(body))
        if failure := _not_data(reply):
            return PageRead(failure=failure)
        body = _dict(body)
        if body.get("error"):
            return PageRead(failure=f"HTTP {reply.status} carrying an error: {_message(body)}")
        if body.get(key) is not None and not isinstance(body.get(key), list):
            return PageRead(failure=f"the reply's {key} were not a list")
        posts, unreadable = _items(
            body.get(key),
            (lambda item: _li_post(item, kind="own", page=page))
            if kind == "posts"
            else (lambda item: liked(item, page)),
        )
        token_ = _str(body.get("paginationToken"))
        following = {**first, "paginationToken": token_} if body.get("hasMore") and token_ else None
        return PageRead(posts=posts, following=following, unreadable=unreadable)

    tool = LINKEDIN_POSTS if kind == "posts" else LINKEDIN_REACTIONS
    history = _history(caller, token, tool, first, parse, base_url, ends_on_empty=False)
    return _with_links(history)


# --- X (TikHub) --------------------------------------------------------------------------------


def _best_mp4(media: Any) -> list[str]:
    urls: list[str] = []
    for video in _dict(media).get("video") or []:
        mp4s = [
            v
            for v in (_dict(video).get("variants") or [])
            if isinstance(v, dict) and v.get("content_type") == "video/mp4" and _str(v.get("url"))
        ]
        if mp4s:
            urls.append(max(mp4s, key=lambda v: v.get("bitrate") or 0)["url"])
    return urls


def _x_entity_links(item: Any) -> dict[str, str]:
    """The addresses TikHub already sent for a tweet's short links."""
    entities = item.get("entities") if isinstance(item, dict) else None
    if not isinstance(entities, dict):
        return {}
    return {
        e["url"]: e["expanded_url"]
        for key in ("urls", "media")
        for e in entities.get(key) or []
        if isinstance(e, dict) and _str(e.get("url")) and _str(e.get("expanded_url"))
    }


def _x_length(text: str) -> int:
    """Length by X's count: Latin and common punctuation count one, other characters two."""
    return sum(
        1 if o <= 4351 or 8192 <= o <= 8205 or 8208 <= o <= 8223 or 8242 <= o <= 8247 else 2
        for o in map(ord, text)
    )


def _x_full_quotes(
    caller: ProviderCaller,
    token: SecretStr,
    history: SocialHistory,
    known: dict[str, str],
    base_url: str,
) -> SocialHistory:
    """Read in full each quoted post long enough to have been cut. A post that cannot be read
    keeps the provider's copy, marked ``text_may_be_cut``. If treg stops selling on the way, the
    rest are marked too, without asking again, and the history says treg stopped."""
    cost = 0.0
    halted = history.halted
    gaps = list(history.gaps)
    posts = []
    for post in history.posts:
        shared = post.shared
        if (
            post.kind == "repost"  # a retweet's original comes in full
            or shared is None
            or shared.post_id is None
            or _x_length(shared.text) < X_MAY_BE_CUT
        ):
            posts.append(post)
            continue
        full: str | None = None
        if halted is None:
            try:
                reply = treg_call(
                    caller, token, X_TWEET, {"tweet_id": shared.post_id}, base_url=base_url
                )
                cost += reply.cost_usd
                data = reply.body.get("data") if isinstance(reply.body, dict) else None
                if reply.status < 400 and isinstance(data, dict):
                    full = _str(data.get("text"))
                    known.update(_x_entity_links(data))
            except ProviderHalted as stop:
                halted = stop.reason_code.removeprefix("latched:")
                gaps.append(
                    f"{X_TWEET}: treg stopped ({halted}) while long quoted posts were read in "
                    "full; the rest keep the timeline's copy, marked text_may_be_cut"
                )
            except ProviderTransportError:
                full = None
        if full is not None and len(full) >= len(shared.text):
            shared = shared.model_copy(update={"text": full, "text_may_be_cut": False})
        else:
            shared = shared.model_copy(update={"text_may_be_cut": True})
        posts.append(post.model_copy(update={"shared": shared}))
    return history.model_copy(
        update={
            "posts": posts,
            "cost_usd": round(history.cost_usd + cost, 6),
            "gaps": gaps,
            "halted": halted,
        }
    )


def _x_shared(item: Any) -> SharedPost | None:
    """The original of a retweet or the post a quote tweet quotes, as TikHub sends it."""
    if not isinstance(item, dict):
        return None
    tid = _id(item.get("tweet_id"))
    text = _str(item.get("text"))
    if tid is None and text is None:
        return None
    author = _dict(item.get("author"))
    screen = _str(author.get("screen_name"))
    return SharedPost(
        post_id=tid,
        url=f"https://x.com/{screen}/status/{tid}" if screen and tid else None,
        author_name=_str(author.get("name")),
        author_url=f"https://x.com/{screen}" if screen else None,
        published_at=_date(item.get("created_at")),
        text=text or "",
        video_urls=_best_mp4(item.get("media")),
    )


def x_posts(
    caller: ProviderCaller, token: SecretStr, handle: str, *, base_url: str = TREG_BASE_URL
) -> SocialHistory:
    """A retweet's ``text`` from TikHub is X's 140-character ``RT @…: …`` form, cut short; the
    full original comes in ``retweeted_tweet`` and is kept in ``shared``, so a retweet's own text
    is empty. A quote tweet keeps its own words and the quoted post in ``shared``.

    Whose tweet it is never depends on the handle typed, which may be an old one (review I6): a
    tweet is the account's own when its author's permanent id is the timeline account's id
    (``data.user.rest_id``), or, without ids, when its author's name is the timeline account's
    current name (``data.user.profile``). A retweet is one only when X marks it. A tweet by
    another account that is not a retweet keeps its author and is marked ``in_feed``."""
    handle = handle.lstrip("@").strip()
    first: dict[str, str | int] = {"screen_name": handle}
    known: dict[str, str] = {}

    def tweet(item: dict[str, Any], page: int, account: dict[str, Any]) -> Post | None:
        tid = _id(item.get("tweet_id"))
        if tid is None:
            return None
        author = _dict(item.get("author"))
        screen = _str(author.get("screen_name")) or handle
        text = _str(item.get("text")) or ""
        for part in (item, item.get("retweeted_tweet"), item.get("quoted")):
            known.update(_x_entity_links(part))
        original = _x_shared(item.get("retweeted_tweet"))
        account_id, author_id = _id(account.get("rest_id")), _id(author.get("rest_id"))
        account_name = _str(account.get("profile")) or handle
        if account_id and author_id:
            mine = author_id == account_id
        else:
            mine = screen.lower() == account_name.lower()
        kind: PostKind
        if original is not None or text.startswith("RT @"):
            kind = "repost"
        else:
            kind = "own" if mine else "in_feed"
        # A retweet's own text is X's clipped "RT @…" form: keep the full original instead.
        own = "" if original is not None else text
        return Post(
            platform="x",
            post_id=tid,
            url=f"https://x.com/{screen}/status/{tid}",
            published_at=_date(item.get("created_at")),
            text=own,
            kind=kind,
            author_name=_str(author.get("name")),
            author_url=f"https://x.com/{screen}",
            video_urls=_best_mp4(item.get("media")),
            shared=original or _x_shared(item.get("quoted")),
            reply_to_id=_id(item.get("reply_to")),
            raw_ref=page,
        )

    def parse(reply: TregReply, page: int) -> PageRead:
        if failure := _not_data(reply):
            if reply.status == 400 and not reply.treg_error:
                # Probed 2026-11-11: TikHub sends this same reply for a handle that does not
                # exist, so it is not an answer either way; the agent is told both readings.
                failure += " (TikHub gives this same reply when the handle does not exist)"
            return PageRead(failure=failure)
        body = _dict(reply.body)
        if body.get("code") not in (None, 200):
            return PageRead(failure=f"HTTP {reply.status} carrying an error: {_message(body)}")
        data = body.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("timeline"), list):
            return PageRead(failure=f"HTTP {reply.status} without a timeline: {_message(body)}")
        account = _dict(data.get("user"))
        posts, unreadable = _items(data["timeline"], lambda item: tweet(item, page, account))
        cursor = _str(data.get("next_cursor"))
        return PageRead(
            posts=posts,
            following={**first, "cursor": cursor} if cursor else None,
            unreadable=unreadable,
        )

    # TikHub keeps handing out a cursor after the last tweet: a page with nothing new is the end.
    history = _history(caller, token, X_TIMELINE, first, parse, base_url, ends_on_empty=True)
    history = _x_full_quotes(caller, token, history, known, base_url)
    return _with_links(history, known)


# --- Instagram and Facebook (ScrapeCreators) ---------------------------------------------------


def _scrapecreators_closed(reply: TregReply) -> PageRead | None:
    """ScrapeCreators' answers about the account itself (probed 2026-11-11 and in the ledger):
    unknown Instagram — 404 ``error: not_found``, "Profile is unavailable on Instagram"; private
    Instagram — "Profile is restricted"; unknown Facebook — ``accountDoesNotExist: true``; private
    Facebook — ``isPrivate: true`` / ``account_status: private`` / "Profile is private"."""
    body = _dict(reply.body)
    said = _message(body)
    lowered = (said or "").lower()
    if body.get("isPrivate") is True or body.get("account_status") == "private":
        return PageRead(closed="private", said=said)
    if "profile is restricted" in lowered or "profile is private" in lowered:
        return PageRead(closed="private", said=said)
    if body.get("accountDoesNotExist") is True:
        return PageRead(closed="not_found", said=said)
    if reply.status == 404 and body.get("error") == "not_found":
        return PageRead(closed="not_found", said=said)
    return None


def _scrapecreators_failure(reply: TregReply, key: str) -> str | None:
    if failure := _not_data(reply):
        return failure
    body = _dict(reply.body)
    if body.get("success") is False or body.get("error"):
        return f"HTTP {reply.status} carrying an error: {_message(body)}"
    if body.get(key) is not None and not isinstance(body.get(key), list):
        return f"the reply's {key} were not a list"
    return None


def instagram_posts(
    caller: ProviderCaller, token: SecretStr, handle: str, *, base_url: str = TREG_BASE_URL
) -> SocialHistory:
    handle = handle.lstrip("@")
    first: dict[str, str | int] = {"handle": handle}

    def read(item: dict[str, Any], page: int) -> Post | None:
        code = _str(item.get("code"))
        pid = _str(str(item.get("id") or "")) or code
        if pid is None:
            return None
        caption = _dict(item.get("caption"))
        versions = item.get("video_versions") or []
        first_version = _dict(versions[0]) if isinstance(versions, list) and versions else {}
        video = _str(first_version.get("url")) or _str(item.get("video_url"))
        user = _dict(item.get("user"))
        return Post(
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

    def parse(reply: TregReply, page: int) -> PageRead:
        if closed := _scrapecreators_closed(reply):
            return closed
        if failure := _scrapecreators_failure(reply, "items"):
            return PageRead(failure=failure)
        body = _dict(reply.body)
        posts, unreadable = _items(body.get("items"), lambda item: read(item, page))
        cursor = _str(body.get("next_max_id"))
        following = (
            {**first, "next_max_id": cursor} if body.get("more_available") and cursor else None
        )
        return PageRead(posts=posts, following=following, unreadable=unreadable)

    return _history(caller, token, INSTAGRAM_POSTS, first, parse, base_url, ends_on_empty=False)


def facebook_posts(
    caller: ProviderCaller, token: SecretStr, profile: str, *, base_url: str = TREG_BASE_URL
) -> SocialHistory:
    first: dict[str, str | int] = {"url": profile}

    def read(item: dict[str, Any], page: int) -> Post | None:
        pid = _str(str(item.get("id") or ""))
        if pid is None:
            return None
        details = _dict(item.get("videoDetails"))
        video = _str(details.get("hdUrl")) or _str(details.get("sdUrl"))
        author = _dict(item.get("author"))
        return Post(
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

    def parse(reply: TregReply, page: int) -> PageRead:
        if closed := _scrapecreators_closed(reply):
            return closed
        if failure := _scrapecreators_failure(reply, "posts"):
            return PageRead(failure=failure)
        body = _dict(reply.body)
        posts, unreadable = _items(body.get("posts"), lambda item: read(item, page))
        cursor = _str(body.get("cursor"))
        return PageRead(
            posts=posts,
            following={**first, "cursor": cursor} if cursor else None,
            unreadable=unreadable,
        )

    return _history(caller, token, FACEBOOK_POSTS, first, parse, base_url, ends_on_empty=False)


# --- Company LinkedIn page (TikHub) -------------------------------------------------------------


def company_linkedin_posts(
    caller: ProviderCaller, token: SecretStr, company: str, *, base_url: str = TREG_BASE_URL
) -> SocialHistory:
    """TikHub returns about 50 posts newest first and takes no cursor; the next page asks for
    posts up to the oldest date seen, and paging stops when a page brings nothing new.

    A successful reply with no data (``{"code": 200, "data": {"data": null}}``) is TikHub's answer
    for a company page it does not know (probed 2026-11-11): on the first page that is
    ``not_found``; on a later page it means nothing older is left."""
    first: dict[str, str | int] = {"url": company}

    def read(item: dict[str, Any], page: int) -> Post | None:
        urn = _str(str(item.get("urn") or item.get("share_urn") or ""))
        if urn is None:
            return None
        poster = _dict(item.get("poster"))
        if item.get("reshared") is True:
            # TikHub lists a company's reshare as the original post: its author is the
            # poster, its text and link are the original's. The company adds nothing
            # (37 of 37 checked 2026-11-11 had no words of the company's own).
            return Post(
                platform="linkedin",
                post_id=urn,
                url=f"https://www.linkedin.com/feed/update/urn:li:activity:{urn}/",
                published_at=_date(item.get("posted")),
                text="",
                kind="repost",
                author_url=company,
                shared=SharedPost(
                    post_id=_id(item.get("share_urn")),
                    url=_str(item.get("url")),
                    author_name=_str(poster.get("name")),
                    author_url=_bare(_str(poster.get("linkedin_url"))),
                    text=_str(item.get("text")) or "",
                ),
                raw_ref=page,
            )
        return Post(
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

    def parse(reply: TregReply, page: int) -> PageRead:
        if failure := _not_data(reply):
            return PageRead(failure=failure)
        body = _dict(reply.body)
        if body.get("code") not in (None, 200):
            return PageRead(failure=f"HTTP {reply.status} carrying an error: {_message(body)}")
        outer = body.get("data")
        if not isinstance(outer, dict) or "data" not in outer:
            return PageRead(failure=f"HTTP {reply.status} without company data: {_message(body)}")
        rows = outer["data"]
        if rows is None:
            if page == 0:
                return PageRead(closed="not_found", said="TikHub found no posts for this page")
            return PageRead()
        if not isinstance(rows, list):
            return PageRead(failure="the reply's posts were not a list")
        posts, unreadable = _items(rows, lambda item: read(item, page))
        dates = [p.published_at for p in posts if p.published_at]
        following = {**first, "end_date": min(dates).strftime("%Y-%m-%d")} if dates else None
        return PageRead(posts=posts, following=following, unreadable=unreadable)

    history = _history(
        caller, token, COMPANY_LINKEDIN_POSTS, first, parse, base_url, ends_on_empty=True
    )
    return _with_links(history)
