"""`clue_research.config` — Config, secrets & jurisdiction/policy skeleton (M0.4).

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

Layering: ``config`` may import :mod:`clue_research.core` (and stdlib / pydantic-settings) only —
**never** ``obs`` (obs sits above config) and **never** ``db`` (enforced by import-linter, M0.1).

Implements ENG-120 (docs/specs/M00-foundations-and-shared-contracts.md §M0.4).
"""

from __future__ import annotations

from clue_research.config.gateway import DEFAULT_GATEWAY_CONFIG, GatewayConfig, ModelPrice
from clue_research.config.loader import (
    ConfigError,
    OverlayStore,
    default_store,
    get_config,
    get_policy,
    overlay_from_mapping,
)
from clue_research.config.models import Config, ConfigOverlay, ConfigVersion
from clue_research.config.policy import (
    DEFAULT_JURISDICTION,
    DEFAULT_POSTURE,
    Jurisdiction,
    JurisdictionPolicy,
    LawfulBasisDefaults,
    Posture,
    RetentionTtls,
    SourceScope,
    UseDisposition,
)
from clue_research.config.schema import (
    BudgetCaps,
    FreshnessTtls,
    MergePolicy,
    ScoringRubric,
    SourceProfile,
)
from clue_research.config.secrets import (
    DB_DSN_ENV_VAR,
    Secrets,
    is_secret_name,
    redact,
    redact_mapping,
)

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
    "DEFAULT_JURISDICTION",
    "DEFAULT_POSTURE",
    # config-schema placeholders
    "MergePolicy",
    "ScoringRubric",
    "SourceProfile",
    "BudgetCaps",
    "FreshnessTtls",
    # llm-gateway config (the model-egress policy-as-data; client in clue_research.gateway)
    "GatewayConfig",
    "ModelPrice",
    "DEFAULT_GATEWAY_CONFIG",
    # secrets
    "Secrets",
    "redact",
    "redact_mapping",
    "is_secret_name",
    "DB_DSN_ENV_VAR",
]
