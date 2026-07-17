"""`clue_config` — Config, secrets & jurisdiction/policy skeleton (M0.4).

The ``config/`` seam (conventions §2 "policy is data, not code"). Exposes:

* **The layered config loader** — :func:`get_config` (merged ``defaults → client → ICP``,
  versioned, validated) and :func:`get_policy` (the jurisdiction/use-class/posture policy). Config
  is loaded once and injected, not read ad hoc.
* **Secrets handling** — :class:`Secrets` (provider keys + the ``CLUE_DATABASE_URL`` DSN read from
  the environment via ``pydantic-settings``, never committed/logged) and :func:`redact` /
  :func:`redact_mapping`, the redaction helpers the obs layer (M0.5) imports.
* **The jurisdiction/policy skeleton** — :class:`JurisdictionPolicy` and friends
  (:class:`Jurisdiction`, :class:`Posture`, the use-class allow-map, :class:`SourceScope`); shapes
  + conservative defaults only, **no enforcement** (the use-gate is M10).
* **Config-schema placeholders** — :class:`MergePolicy`, :class:`ScoringRubric`,
  :class:`SourceProfile`, :class:`BudgetCaps`, :class:`FreshnessTtls`; defaulted, validated, read
  by no engine yet (they reserve the seam for M1/M3/M4/M6/M7/M9).

Layering: ``config`` may import :mod:`clue_core` (and stdlib / pydantic-settings) only —
**never** ``obs`` (obs sits above config) and **never** ``db`` (enforced by import-linter, M0.1).

Implements ENG-120 (docs/specs/M00-foundations-and-shared-contracts.md §M0.4).
"""

from __future__ import annotations

from clue_config.gateway import (
    DEFAULT_GATEWAY_CONFIG,
    GatewayConfig,
    ModelPrice,
    default_gateway_config,
)
from clue_config.loader import (
    ConfigError,
    OverlayStore,
    default_store,
    get_config,
    get_policy,
    overlay_from_mapping,
)
from clue_config.models import Config, ConfigOverlay, ConfigVersion
from clue_config.policy import (
    DEFAULT_JURISDICTION,
    DEFAULT_POSTURE,
    DEFAULT_REGIME_MAPPING,
    DEFAULT_USE_CLASS_LEXICON,
    STRICT_DEFAULT_REGIME,
    Jurisdiction,
    JurisdictionPolicy,
    LawfulBasisDefaults,
    Posture,
    RegimeMapping,
    RetentionTtls,
    SourceScope,
    UseClassLexicon,
    UseDisposition,
)
from clue_config.schema import (
    DEFAULT_CONFIDENCE_THRESHOLDS,
    DEFAULT_SOURCE_PLAN_POLICY,
    BudgetCaps,
    ConfidenceThresholds,
    DeepPhaseConfig,
    FreshnessTtls,
    MergePolicy,
    RecursionPolicy,
    ScoringRubric,
    SourcePlanPolicy,
    SourceProfile,
    TierRecursionCaps,
    VerificationHealthThresholds,
)
from clue_config.secrets import (
    DB_DSN_ENV_VAR,
    Secrets,
    is_secret_name,
    redact,
    redact_mapping,
)
from clue_config.settings import DEFAULT_SYNTHESIS_MODEL, Settings, load_settings

__all__ = [
    # loader / seam
    "get_config",
    "get_policy",
    "overlay_from_mapping",
    "OverlayStore",
    "default_store",
    "ConfigError",
    # layered models
    "Config",
    "ConfigOverlay",
    "ConfigVersion",
    # jurisdiction / policy skeleton
    "JurisdictionPolicy",
    "Jurisdiction",
    "Posture",
    "SourceScope",
    "UseDisposition",
    "LawfulBasisDefaults",
    "RetentionTtls",
    "RegimeMapping",
    "UseClassLexicon",
    "DEFAULT_JURISDICTION",
    "DEFAULT_POSTURE",
    "DEFAULT_REGIME_MAPPING",
    "DEFAULT_USE_CLASS_LEXICON",
    "STRICT_DEFAULT_REGIME",
    # config-schema placeholders
    "MergePolicy",
    "VerificationHealthThresholds",
    "ScoringRubric",
    "SourceProfile",
    "BudgetCaps",
    "RecursionPolicy",
    "TierRecursionCaps",
    "DeepPhaseConfig",
    "FreshnessTtls",
    # live source knobs (read per-run by the M8 deep workers)
    "ConfidenceThresholds",
    "DEFAULT_CONFIDENCE_THRESHOLDS",
    "SourcePlanPolicy",
    "DEFAULT_SOURCE_PLAN_POLICY",
    # llm-gateway config (the model-egress policy-as-data; client in clue_research.gateway)
    "GatewayConfig",
    "ModelPrice",
    "DEFAULT_GATEWAY_CONFIG",
    "default_gateway_config",
    # deploy-time settings (non-secret env)
    "Settings",
    "load_settings",
    "DEFAULT_SYNTHESIS_MODEL",
    # secrets
    "Secrets",
    "redact",
    "redact_mapping",
    "is_secret_name",
    "DB_DSN_ENV_VAR",
]
