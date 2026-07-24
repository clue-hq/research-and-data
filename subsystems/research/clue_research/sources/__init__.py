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
from clue_research.sources.planner import (
    DEFAULT_SOURCE_PLANNER_CONFIG,
    OrderedSourcePlan,
    PlannedSource,
    SourcePlannerConfig,
    plan_sources,
)
from clue_research.sources.registry import (
    NoResolverBoundError,
    SourceManifestRedefinitionError,
    SourceYieldError,
    bind_resolver,
    clear_resolver_bindings,
    entity_scope_serves,
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
from clue_research.sources.source_profile import (
    AllowedSource,
    resolve_allowed_set,
)
from clue_research.sources.source_yield import (
    SourceYieldStat,
    get_source_yield,
    record_source_yield,
)
from clue_research.sources.thresholds import (
    DEFAULT_CONFIDENCE_THRESHOLDS,
    ConfidenceThresholds,
)
from clue_research.sources.waterfall import (
    AttemptRecorder,
    StepOutcome,
    StopReason,
    TierStep,
    WaterfallResult,
    resolve_field,
    resolve_fields,
)

__all__ = [
    # manifest type
    "RegistrySourceManifest",
    # DB registry
    "register_source",
    "get_source",
    "list_sources",
    "sources_for",
    "registered_source_keys",
    "entity_scope_serves",
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
    # waterfall engine (M4.1)
    "resolve_field",
    "resolve_fields",
    "AttemptRecorder",
    "WaterfallResult",
    "TierStep",
    "StopReason",
    "StepOutcome",
    # confidence thresholds (engine-side config, decision #1)
    "ConfidenceThresholds",
    "DEFAULT_CONFIDENCE_THRESHOLDS",
    # the registry-intersection allowed set (M4.6; profile serving lives in clue_research.icp)
    "AllowedSource",
    "resolve_allowed_set",
    # the config-bounded Source Planner (M4.6)
    "plan_sources",
    "OrderedSourcePlan",
    "PlannedSource",
    "SourcePlannerConfig",
    "DEFAULT_SOURCE_PLANNER_CONFIG",
    # per-source yield telemetry (the learning-loop substrate; M4.6)
    "record_source_yield",
    "get_source_yield",
    "SourceYieldStat",
]
