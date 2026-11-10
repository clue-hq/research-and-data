"""The footprint jobs of ``acquire_research_evidence`` version 3.

Each job runs one ``clue_api.footprint`` function inside ``runtime.call_provider`` (so every paid
call lands on the job's ledger and its raw pages become citable provider records) and returns the
result the wrapper saves at ``/research/operations/<id>/0.json``. A short ``results`` list feeds the
receipt preview; the full lists (``posts``, ``leads``, ``handles``) are in the saved file.

The descriptions below are short and functional. The wording the agent reads is agreed with the
founder first (plan Task 11) and replaces them.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from clue_api.footprint.handles import find_handles
from clue_api.footprint.media_sources import MediaSourceKeys, media_keys_of
from clue_api.footprint.podcast_search import EXA_PODCAST_DOMAIN, find_podcasts, overview
from clue_api.footprint.social import (
    company_linkedin_posts,
    facebook_posts,
    instagram_posts,
    linkedin_activity,
    x_posts,
)
from clue_api.footprint.social_types import SocialHistory
from clue_api.footprint.treg_client import TREG_BASE_URL
from clue_api.footprint.video_search import find_videos
from clue_spend.errors import ProviderTransportError, RawParseError

#: The receipt previews this many items; the saved file holds them all.
PREVIEW_ITEMS = 20


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


#: One search the agent writes, e.g. ``"Mike McNeil" Fleet Device Management``.
Query = Annotated[str, Field(min_length=2, max_length=300)]


class FindPodcastsArgs(_Args):
    queries: list[Query] = Field(min_length=1)


class FindVideosArgs(_Args):
    queries: list[Query] = Field(min_length=1)


class FindHandlesArgs(_Args):
    name: str = Field(min_length=2, max_length=200)
    company: str | None = Field(None, max_length=200)
    linkedin_url: str | None = Field(None, max_length=500)


class LinkedInActivityArgs(_Args):
    profile: str = Field(min_length=2, max_length=500)
    kind: Literal["posts", "reactions"]


class XPostsArgs(_Args):
    handle: str = Field(min_length=1, max_length=100)


class InstagramPostsArgs(_Args):
    handle: str = Field(min_length=1, max_length=100)


class FacebookPostsArgs(_Args):
    profile: str = Field(min_length=2, max_length=500)


class CompanyLinkedInPostsArgs(_Args):
    company: str = Field(min_length=2, max_length=500)


DESCRIPTIONS: Mapping[str, str] = {
    "find_podcasts": (
        "Podcast episodes the person may appear on, from Apple and Podcast Index, with each "
        "episode's full description, links, feed and audio link. Nothing is filtered."
    ),
    "find_videos": (
        "YouTube videos found by the person's quoted name (and with the company), each with its "
        "full description, tags, channel and length. Nothing is filtered."
    ),
    "find_handles": (
        "Candidate X, Facebook and Instagram accounts for the person (PDL and a same-handle "
        "Instagram check). Each is a candidate to confirm from its bio and posts."
    ),
    "linkedin_activity": (
        "The person's whole LinkedIn history: their own posts (kind=posts) or the posts they "
        "reacted to (kind=reactions). Every post is saved; video links are included."
    ),
    "x_posts": "The whole X timeline of a handle; reposts are marked. Video links are included.",
    "instagram_posts": "The public Instagram posts of a handle; a private account says so.",
    "facebook_posts": "The public Facebook posts of a profile link; a private profile says so.",
    "company_linkedin_posts": "The whole post history of a company's LinkedIn page.",
}


def _treg(runtime: Any) -> tuple[Any, str]:
    return getattr(runtime.clients, "treg_token", None), getattr(
        runtime.settings, "treg_base_url", TREG_BASE_URL
    )


_NO_TREG = {"state": "unavailable", "gap": "treg_key_missing"}


def _title(post: Mapping[str, Any]) -> str:
    """A repost's own text is empty and a quote's is only half the story: name the original."""
    own = post.get("text") or ""
    shared = post.get("shared")
    if not shared:
        return own[:200]
    original = f"{shared.get('author_name') or 'someone'}: {shared.get('text') or ''}"
    return (f"{own} (quoting {original})" if own else f"Reposted from {original}")[:200]


def _history(history: SocialHistory) -> dict[str, Any]:
    value = history.model_dump(mode="json")
    newest = sorted(value["posts"], key=lambda p: p.get("published_at") or "", reverse=True)[
        :PREVIEW_ITEMS
    ]
    value["n_results"] = len(value["posts"])
    value["results"] = [
        {
            "title": _title(p),
            "url": p.get("url"),
            "published": p.get("published_at"),
        }
        for p in newest
    ]
    return value


async def _social(runtime: Any, call: Callable[[Any, Any, str], SocialHistory]) -> dict[str, Any]:
    token, base_url = _treg(runtime)
    if token is None:
        return dict(_NO_TREG)
    history = await runtime.call_provider("treg", lambda caller: call(caller, token, base_url))
    return _history(history)


async def _linkedin_activity(runtime: Any, args: LinkedInActivityArgs) -> dict[str, Any]:
    return await _social(
        runtime, lambda c, t, b: linkedin_activity(c, t, args.profile, args.kind, base_url=b)
    )


async def _x_posts(runtime: Any, args: XPostsArgs) -> dict[str, Any]:
    return await _social(runtime, lambda c, t, b: x_posts(c, t, args.handle, base_url=b))


async def _instagram_posts(runtime: Any, args: InstagramPostsArgs) -> dict[str, Any]:
    return await _social(runtime, lambda c, t, b: instagram_posts(c, t, args.handle, base_url=b))


async def _facebook_posts(runtime: Any, args: FacebookPostsArgs) -> dict[str, Any]:
    return await _social(runtime, lambda c, t, b: facebook_posts(c, t, args.profile, base_url=b))


async def _company_linkedin_posts(runtime: Any, args: CompanyLinkedInPostsArgs) -> dict[str, Any]:
    return await _social(
        runtime, lambda c, t, b: company_linkedin_posts(c, t, args.company, base_url=b)
    )


def _keys(runtime: Any) -> MediaSourceKeys:
    return media_keys_of(runtime)


#: Hits per search from Exa's podcast transcripts; each search costs about 1.7 cents at 20.
EXA_PODCAST_RESULTS = 20


def _exa_podcasts(runtime: Any, caller: Any) -> Callable[[str], Any] | None:
    """One search on Exa's podcast index, with the transcript passages that matched."""
    exa = getattr(runtime.clients, "exa", None)
    if exa is None:
        return None

    def search(query: str) -> Any:
        try:
            found = exa(caller).search(
                query,
                include_domains=[EXA_PODCAST_DOMAIN],
                num_results=EXA_PODCAST_RESULTS,
                text_max_chars=1500,  # the episode page's header: show, date, hosts, guests
                highlights={"query": query, "maxCharacters": 1200},
                label="footprint.find_podcasts",
            )
        except (ProviderTransportError, RawParseError) as exc:
            raise ValueError(str(exc)[:200]) from exc
        if found.status >= 400:
            raise ValueError(f"exa HTTP {found.status}")
        return found.results

    return search


async def _find_podcasts(runtime: Any, args: FindPodcastsArgs) -> dict[str, Any]:
    """The saved file opens with ``overview`` (one short line per result) and holds the full
    entries under ``podcasts``. The wrapper saves keys in alphabetical order, so these two names
    keep the overview first; the receipt carries only the ``report`` line."""
    leads, gaps = await runtime.call_provider(
        "podcast_index",
        lambda caller: find_podcasts(
            caller, _keys(runtime), args.queries, exa_search=_exa_podcasts(runtime, caller)
        ),
    )
    lines = overview(leads, args.queries)
    return {
        "state": "complete",
        "gaps": gaps,
        "n_results": len(leads),
        "report": (
            f"{len(leads)} podcast results from {len(dict.fromkeys(args.queries))} searches. "
            "Read the overview at the top of result_path (one line per result), then open the "
            "entries you need by number in its podcasts list (line N is podcasts[N-1])."
        ),
        "overview": lines,
        "podcasts": [lead.model_dump(mode="json") for lead in leads],
    }


async def _find_videos(runtime: Any, args: FindVideosArgs) -> dict[str, Any]:
    def run(caller: Any) -> Any:
        def exa(query: str) -> list[str]:
            hits = runtime.clients.exa(caller).search(
                query,
                include_domains=["youtube.com"],
                num_results=10,
                label="footprint.find_videos",
            )
            return [h.url for h in hits.results if h.url]

        return find_videos(caller, _keys(runtime), args.queries, exa_fallback=exa)

    leads, gaps = await runtime.call_provider("youtube_data", run)
    found = [lead.model_dump(mode="json") for lead in leads]
    return {
        "state": "complete",
        "gaps": gaps,
        "n_results": len(found),
        "leads": found,
        "results": [
            {
                "title": f"{lead.get('channel') or ''} — {lead.get('title') or ''}".strip(" —"),
                "url": lead["url"],
                "published": lead.get("published_at"),
                "text": lead.get("description"),
            }
            for lead in found
        ],
    }


async def _find_handles(runtime: Any, args: FindHandlesArgs) -> dict[str, Any]:
    token, base_url = _treg(runtime)
    if token is None:
        return dict(_NO_TREG)
    pdl = getattr(runtime.clients, "pdl_key", None)
    handles = await runtime.call_provider(
        "treg",
        lambda caller: find_handles(
            caller,
            token,
            pdl,
            name=args.name,
            company=args.company,
            linkedin_url=args.linkedin_url,
            base_url=base_url,
        ),
    )
    found = [h.model_dump(mode="json") for h in handles]
    return {
        "state": "complete",
        "gaps": [] if pdl else ["pdl_key_missing"],
        "n_results": len(found),
        "handles": found,
        "results": [
            {"title": f"{h['platform']} @{h['handle']}", "url": h["url"], "text": h.get("bio")}
            for h in found
        ],
    }


JOBS: tuple[tuple[str, type[BaseModel], Callable[[Any, Any], Any]], ...] = (
    ("find_podcasts", FindPodcastsArgs, _find_podcasts),
    ("find_videos", FindVideosArgs, _find_videos),
    ("find_handles", FindHandlesArgs, _find_handles),
    ("linkedin_activity", LinkedInActivityArgs, _linkedin_activity),
    ("x_posts", XPostsArgs, _x_posts),
    ("instagram_posts", InstagramPostsArgs, _instagram_posts),
    ("facebook_posts", FacebookPostsArgs, _facebook_posts),
    ("company_linkedin_posts", CompanyLinkedInPostsArgs, _company_linkedin_posts),
)


def footprint_tools(runtime: Any) -> list[Any]:
    from clue_api.arv2.account_research_tools import _tool

    return [
        _tool(runtime, name=name, model=model, body=body, description=DESCRIPTIONS[name])
        for name, model, body in JOBS
    ]
