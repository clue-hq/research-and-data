"""The footprint jobs of ``acquire_research_evidence`` version 3.

Each job runs one ``clue_api.footprint`` function inside ``runtime.call_provider`` (so every paid
call lands on the job's ledger and its raw pages become citable provider records) and returns the
result the wrapper saves at ``/research/operations/<id>/0.json``. A short ``results`` list feeds the
receipt preview; the full lists (``posts``, ``leads``, ``handles``) are in the saved file.

The descriptions below are short and functional. The wording the agent reads is agreed with the
founder first (plan Task 11) and replaces them.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from clue_api.footprint.handles import find_handles
from clue_api.footprint.media_sources import MediaSourceKeys, media_keys_of
from clue_api.footprint.podcast_search import EXA_PODCAST_DOMAIN, find_podcasts, overview
from clue_api.footprint.search_tally import SourceStopped, Tally
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
from clue_api.footprint.video_search import overview as video_overview
from clue_spend.errors import ProviderHalted, ProviderTransportError, RawParseError

#: The receipt previews this many items; the saved file holds them all.
PREVIEW_ITEMS = 20


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


#: One search the agent writes, e.g. ``"Mike McNeil" Fleet Device Management``.
Query = Annotated[str, Field(min_length=2, max_length=300)]

# What each argument expects, as the agent reads it in the job list (founder-approved 2026-11-11).
_PODCAST_SEARCHES = [
    '"Mike McNeil"',
    '"Mike McNeil" Fleet Device Management',
    "Fleet Device Management CEO panel",
]
_VIDEO_SEARCHES = ['"Ann Barron-DiCamillo"', '"Ann Barron-DiCamillo" Citi']
_QUERIES = (
    "Your searches, one or more, each written as you would type it into a search box. Put a "
    "name in double quotes to keep its words together."
)


class FindPodcastsArgs(_Args):
    queries: list[Query] = Field(
        min_length=1,
        description=_QUERIES,
        examples=[_PODCAST_SEARCHES],
    )


class FindVideosArgs(_Args):
    queries: list[Query] = Field(
        min_length=1,
        description="Same as for find_podcasts: " + _QUERIES[0].lower() + _QUERIES[1:],
        examples=[_VIDEO_SEARCHES],
    )


class FindHandlesArgs(_Args):
    name: str = Field(
        min_length=2,
        max_length=200,
        description="The person's full name as they use it.",
        examples=["Ann Barron-DiCamillo"],
    )
    company: str | None = Field(
        None,
        max_length=200,
        description="Their current employer; it helps tell them apart from namesakes.",
        examples=["U.S. Bank"],
    )
    linkedin_url: str | None = Field(
        None,
        max_length=500,
        description=(
            "Their LinkedIn profile link, the surest way to find their other accounts; give it "
            "whenever you have it."
        ),
        examples=["https://www.linkedin.com/in/annbarrondicamillo"],
    )


class LinkedInActivityArgs(_Args):
    profile: str = Field(
        min_length=2,
        max_length=500,
        description=(
            "Their LinkedIn profile link, such as https://www.linkedin.com/in/jane-doe (their "
            "profile URN also works)."
        ),
        examples=["https://www.linkedin.com/in/jane-doe"],
    )
    kind: Literal["posts", "reactions"] = Field(
        description=(
            '"posts" for what they wrote or shared, "reactions" for posts they reacted to; one '
            "kind per call, so call twice for both."
        ),
        examples=["posts"],
    )


class XPostsArgs(_Args):
    handle: str = Field(
        min_length=1,
        max_length=100,
        description="The X account name, with or without @. Not a link.",
        examples=["davegerhardt"],
    )


class InstagramPostsArgs(_Args):
    handle: str = Field(
        min_length=1,
        max_length=100,
        description="The Instagram account name, with or without @. Not a link.",
        examples=["davegerhardt"],
    )


class FacebookPostsArgs(_Args):
    profile: str = Field(
        min_length=2,
        max_length=500,
        description="The Facebook profile link.",
        examples=["https://www.facebook.com/jane.doe"],
    )


class CompanyLinkedInPostsArgs(_Args):
    company: str = Field(
        min_length=2,
        max_length=500,
        description="The company's LinkedIn page link.",
        examples=["https://www.linkedin.com/company/illumio/"],
    )


#: What the agent reads for each job (founder-approved 2026-11-11, Task 11).
_TEXT: Mapping[str, str] = {
    "find_podcasts": (
        "Podcast episodes for the searches you write (queries). Each search is run on Apple, "
        "Podcast Index and Exa's podcast transcripts, which match what was said in an episode, "
        "so an episode whose title never names the person can still be found. Each episode "
        "comes with its full description, links, feed and audio link, the searches that found "
        "it, and, from Exa, the transcript passages that matched and the hosts and guests Exa "
        "heard. Nothing is left out or ranked: decide yourself which are this person. The "
        "answer starts with an overview, one line per episode in the order found; scan it, then "
        "open the episodes you need by number in its podcasts list."
    ),
    "find_videos": (
        "YouTube videos for the searches you write (queries). Each comes with its full "
        "description, tags, channel, length and the searches that found it. Nothing is left out "
        "or ranked. The answer starts with an overview, one line per video in the order found; "
        "scan it, then open the videos you need by number in its videos list."
    ),
    "find_handles": (
        "Possible X, Facebook and Instagram accounts for the person. Each one is only a "
        "candidate: check its bio and posts before you read it."
    ),
    "linkedin_activity": (
        "Everything the person has posted on LinkedIn (kind=posts), or every post they reacted "
        "to (kind=reactions). Every post is saved with its own link, date and any video link. A "
        "reshare comes with the original post and its author."
    ),
    "x_posts": (
        "Every post on an X account, newest first. A repost comes with the original post and "
        "its author; a quote comes with the post it quotes. Video links are included."
    ),
    "instagram_posts": (
        "The public posts of an Instagram account. A private account comes back as private."
    ),
    "facebook_posts": (
        "The public posts of a Facebook profile. A private profile comes back as private."
    ),
    "company_linkedin_posts": (
        "Everything a company has posted on its LinkedIn page. A reshare comes with the "
        "original post and its author."
    ),
}

#: One example call per job, shown at the end of its description (and checked by the tests).
EXAMPLES: Mapping[str, dict[str, Any]] = {
    "find_podcasts": {"queries": _PODCAST_SEARCHES},
    "find_videos": {"queries": _VIDEO_SEARCHES},
    "find_handles": {
        "name": "Ann Barron-DiCamillo",
        "company": "U.S. Bank",
        "linkedin_url": "https://www.linkedin.com/in/annbarrondicamillo",
    },
    "linkedin_activity": {"profile": "https://www.linkedin.com/in/jane-doe", "kind": "posts"},
    "x_posts": {"handle": "davegerhardt"},
    "instagram_posts": {"handle": "davegerhardt"},
    "facebook_posts": {"profile": "https://www.facebook.com/jane.doe"},
    "company_linkedin_posts": {"company": "https://www.linkedin.com/company/illumio/"},
}

DESCRIPTIONS: Mapping[str, str] = {
    name: f"{text} Example arguments: {json.dumps(EXAMPLES[name])}" for name, text in _TEXT.items()
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


#: How each outcome of a social history is named on the receipt (``error_code``).
_OUTCOME_CODES: Mapping[str, str] = {
    "partial": "history_partial",
    "unavailable": "history_unavailable",
    "not_found": "account_not_found",
    "private": "account_private",
}


def _outcome(history: SocialHistory) -> dict[str, Any]:
    """The receipt's first preview line (``report``), its ``recovery`` and ``outcome_code``: what
    happened, said so the agent cannot take a failure for an answer about the person."""
    gaps = "; ".join(history.gaps)
    n, pages = len(history.posts), history.pages
    if history.state == "complete":
        return {"report": f"All {n} posts over {pages} page(s). Also: {gaps}"} if gaps else {}
    if history.state in ("not_found", "private"):
        said = f': "{history.provider_said}"' if history.provider_said else ""
        what = "does not exist" if history.state == "not_found" else "is private"
        return {
            "outcome_code": _OUTCOME_CODES[history.state],
            "report": f"The provider says this account {what}{said}.",
        }
    if history.halted:
        return {
            "outcome_code": "provider_halted",
            "report": f"Read {n} posts, then stopped: {gaps}. This is not about the person.",
            "recovery": "treg is stopped for the rest of this job, so no LinkedIn, X, "
            "Instagram, Facebook or company-page job will run again; note the gap.",
        }
    if history.state == "partial":
        report = (
            f"Read {n} posts over {pages} page(s), then the reading stopped: {gaps}. "
            "This is not the whole history."
        )
    else:
        report = f"Nothing was read: {gaps}. This says nothing about the person."
    return {
        "outcome_code": _OUTCOME_CODES[history.state],
        "report": report,
        "recovery": "Call again with the same arguments to read it again.",
    }


def _history(history: SocialHistory) -> dict[str, Any]:
    value = history.model_dump(mode="json", exclude={"halted"})
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
    value.update(_outcome(history))
    return value


async def _social(runtime: Any, call: Callable[[Any, Any, str], SocialHistory]) -> dict[str, Any]:
    token, base_url = _treg(runtime)
    if token is None:
        return dict(_NO_TREG)
    history = await runtime.call_provider("treg", lambda caller: call(caller, token, base_url))
    if history.halted:
        # treg stopped selling inside this call (the reader keeps what it read rather than
        # raising): latch it for the job as call_provider does for a provider that raises.
        reason = "out of credit" if history.halted == "payment_required" else history.halted
        runtime.halted.setdefault("treg", f"treg stopped selling: {reason}")
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


def _exa(runtime: Any, caller: Any, query: str, **kwargs: Any) -> Any:
    """One Exa search for a footprint job. A failure is a ``ValueError`` naming it (never zero
    hits); Exa refusing to sell, now or earlier in the job, is :class:`SourceStopped`, so the
    search stops asking Exa and only Exa."""
    if "exa" in runtime.halted:
        raise SourceStopped("exa", f"stopped earlier in this job: {runtime.halted['exa']}")
    try:
        found = runtime.clients.exa(caller).search(query, **kwargs)
    except ProviderHalted as halted:
        raise SourceStopped("exa", halted.reason_code.removeprefix("latched:")) from halted
    except (ProviderTransportError, RawParseError) as exc:
        raise ValueError(f"Exa did not answer ({str(exc)[:160]})") from exc
    if found.status >= 400:
        raise ValueError(f"Exa HTTP {found.status}")
    return found


def _exa_ready(runtime: Any) -> bool:
    return getattr(runtime.clients, "exa", None) is not None


def _exa_podcasts(runtime: Any, caller: Any) -> Callable[[str], Any] | None:
    """One search on Exa's podcast index, with the transcript passages that matched."""
    if not _exa_ready(runtime):
        return None

    def search(query: str) -> Any:
        return _exa(
            runtime,
            caller,
            query,
            include_domains=[EXA_PODCAST_DOMAIN],
            num_results=EXA_PODCAST_RESULTS,
            text_max_chars=1500,  # the episode page's header: show, date, hosts, guests
            highlights={"query": query, "maxCharacters": 1200},
            label="footprint.find_podcasts",
        ).results

    return search


def _exa_videos(runtime: Any, caller: Any) -> Callable[[str], list[str]] | None:
    """One Exa web search limited to YouTube, for searches YouTube itself could not run."""
    if not _exa_ready(runtime):
        return None

    def search(query: str) -> list[str]:
        found = _exa(
            runtime,
            caller,
            query,
            include_domains=["youtube.com"],
            num_results=10,
            label="footprint.find_videos",
        )
        return [h.url for h in found.results if h.url]

    return search


#: How a search job's state is named on the receipt (``error_code``).
_SEARCH_CODES: Mapping[str, str] = {
    "partial": "searches_partial",
    "unavailable": "searches_unavailable",
}


def _searched(
    runtime: Any, tally: Tally, what: str, n: int, queries: Sequence[str], listing: str
) -> dict[str, Any]:
    """The state, gaps and receipt line of a podcast or video search: the problems are on the
    line the agent reads, and a failure is never "nothing found"."""
    for provider, reason in tally.stopped.items():
        runtime.halted.setdefault(provider, f"{provider} stopped selling: {reason}")
    searches = len(dict.fromkeys(queries))
    problems = f" Problems: {'; '.join(tally.gaps)}" if tally.gaps else ""
    value: dict[str, Any] = {
        "state": tally.state,
        "gaps": tally.gaps,
        "n_results": n,
        "report": (
            f"{n} {what} results from {searches} searches.{problems} Read the overview at the "
            "top of result_path (one line per result), then open the entries you need by number "
            f"in its {listing} list (line N is {listing}[N-1])."
        ),
    }
    if tally.state != "complete":
        value["outcome_code"] = _SEARCH_CODES[tally.state]
        value["recovery"] = "Call again with the same arguments to run the searches again."
    return value


async def _find_podcasts(runtime: Any, args: FindPodcastsArgs) -> dict[str, Any]:
    """The saved file opens with ``overview`` (one short line per result) and holds the full
    entries under ``podcasts``. The wrapper saves keys in alphabetical order, so these two names
    keep the overview first; the receipt carries only the ``report`` line."""
    leads, tally = await runtime.call_provider(
        "podcast_index",
        lambda caller: find_podcasts(
            caller, _keys(runtime), args.queries, exa_search=_exa_podcasts(runtime, caller)
        ),
    )
    return {
        **_searched(runtime, tally, "podcast", len(leads), args.queries, "podcasts"),
        "overview": overview(leads, args.queries),
        "podcasts": [lead.model_dump(mode="json") for lead in leads],
    }


async def _find_videos(runtime: Any, args: FindVideosArgs) -> dict[str, Any]:
    leads, tally = await runtime.call_provider(
        "youtube_data",
        lambda caller: find_videos(
            caller, _keys(runtime), args.queries, exa_fallback=_exa_videos(runtime, caller)
        ),
    )
    # As for podcasts: the saved file opens with ``overview``, then the full entries under
    # ``videos`` (keys are saved alphabetically); the receipt carries only the ``report`` line.
    return {
        **_searched(runtime, tally, "video", len(leads), args.queries, "videos"),
        "overview": video_overview(leads, args.queries),
        "videos": [lead.model_dump(mode="json") for lead in leads],
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
