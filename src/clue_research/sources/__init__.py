"""`clue_research.sources` — the Source Registry (M4.2 / ENG-111).

The swappability spine of the Source Intelligence Layer (staged-flow §7a): a source is a
``source_manifest`` row referenced only by ``source_key``, the sibling of the M1.3 field registry.
Exposes the DB registry (``register_source`` / ``get_source`` / ``list_sources`` / ``sources_for`` /
``registered_source_keys``) and the resolver binding (``bind_resolver`` / ``get_resolver``) the M4.1
waterfall dispatches through. Nothing downstream learns a provider's name — everything is a
``source_key``; ``provider`` is billing/ops-only. It never imports a resolver or a provider
SDK (resolvers register themselves via ``bind_resolver``).
"""

from __future__ import annotations

from clue_research.sources.manifest import RegistrySourceManifest
from clue_research.sources.registry import (
    NoResolverBoundError,
    SourceManifestRedefinitionError,
    SourceYieldError,
    bind_resolver,
    clear_resolver_bindings,
    get_resolver,
    get_source,
    is_resolver_bound,
    list_sources,
    register_source,
    registered_source_keys,
    sources_for,
    unbind_resolver,
)
from clue_research.sources.seeds import SEED_MANIFESTS, seed_source_manifests

__all__ = [
    # manifest type
    "RegistrySourceManifest",
    # DB registry
    "register_source",
    "get_source",
    "list_sources",
    "sources_for",
    "registered_source_keys",
    # resolver binding (in-process source_key -> Resolver dispatch)
    "bind_resolver",
    "unbind_resolver",
    "is_resolver_bound",
    "get_resolver",
    "clear_resolver_bindings",
    # errors
    "NoResolverBoundError",
    "SourceManifestRedefinitionError",
    "SourceYieldError",
    # seeds
    "SEED_MANIFESTS",
    "seed_source_manifests",
]
