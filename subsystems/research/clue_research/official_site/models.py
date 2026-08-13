"""Persistence-facing errors for the C1 official-site crawl repository.

The frozen public payloads live in :mod:`clue_research.official_site.contracts`. These errors keep
database absence, replay disagreement, and capacity exhaustion explicit without exposing another
set of domain models.
"""

from __future__ import annotations


class CrawlRepositoryError(RuntimeError):
    """Base class for durable crawl repository failures."""


class CrawlRunNotFoundError(CrawlRepositoryError):
    """The requested run does not exist in the supplied workspace scope."""


class CrawlReplayConflictError(CrawlRepositoryError):
    """An idempotency identity was replayed with different immutable inputs."""


class CrawlCapacityExceededError(CrawlRepositoryError):
    """A discovery batch would exceed the run-pinned durable page ceiling."""


class CrawlStateConflictError(CrawlRepositoryError):
    """The requested mutation is not valid from the currently committed state."""


__all__ = [
    "CrawlCapacityExceededError",
    "CrawlReplayConflictError",
    "CrawlRepositoryError",
    "CrawlRunNotFoundError",
    "CrawlStateConflictError",
]
