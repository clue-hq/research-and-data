"""The Brand Ad Assets lane (spec ``docs/brand-ad-assets-v1-spec.md`` §4/§5 W2).

One flag-gated pipeline — harvest → filter/dedupe → custody → distill → pre-generate —
that turns a client's own published LinkedIn ads into three durable artifact kinds: the
harvested reference creatives (bytes in design custody, provenance stamped), the versioned
ad-DNA card, and the pre-generated imagery born from that card's named visual systems.

**The provider is swappable and nobody outside this package knows who it is.** ``provider``
declares the seam (:class:`~.provider.AdLibraryProvider`); ``adyntel`` is the one v1
implementation of it (ruling D3), reached only through :func:`~.provider.resolve_provider`.
Meta and Google fetchers are seam-ready and not built (spec §7).

Every module here is import-cheap: ``httpx`` is imported lazily on the one network path, so
importing this package from a route, a worker or a test drags in no transport.
"""

from __future__ import annotations

from .provider import (
    AdLibraryAd,
    AdLibraryCredentialsMissing,
    AdLibraryError,
    AdLibraryPage,
    AdLibraryProvider,
    resolve_provider,
)

__all__ = [
    "AdLibraryAd",
    "AdLibraryCredentialsMissing",
    "AdLibraryError",
    "AdLibraryPage",
    "AdLibraryProvider",
    "resolve_provider",
]
