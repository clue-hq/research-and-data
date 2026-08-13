"""Durable official-site crawl contracts (C0); implementations land in later slices."""

from clue_research.official_site.contracts import *  # noqa: F403
from clue_research.official_site.contracts import __all__ as _contract_exports
from clue_research.official_site.seams import (
    CrawlRepository,
    OfficialSiteCorpusMaterializer,
    PageFetcher,
)
from clue_research.official_site.transitions import (
    ATTEMPT_TRANSITIONS,
    PAGE_TRANSITIONS,
    RUN_TRANSITIONS,
    allows_transition,
    transition_manifest,
)

__all__ = [
    *_contract_exports,
    "ATTEMPT_TRANSITIONS",
    "CrawlRepository",
    "OfficialSiteCorpusMaterializer",
    "PAGE_TRANSITIONS",
    "PageFetcher",
    "RUN_TRANSITIONS",
    "allows_transition",
    "transition_manifest",
]
