"""The typed, layered config loader (M0.4) — the ``config/`` seam.

Exposes the two accessors the rest of the subsystem consumes:

* :func:`get_config(client_id, icp_id=None)` — the merged, validated :class:`Config`.
* :func:`get_policy(client_id)` — the jurisdiction/use-class/posture
  :class:`~clue_research.config.policy.JurisdictionPolicy`.

**Layering.** Three layers merge in precedence order — *defaults → per-client → per-ICP/campaign*
(staged-flow §2). Each layer is a sparse :class:`~clue_research.config.models.ConfigOverlay`; a
present sub-tree wins, an absent one inherits from beneath. Config is loaded once and *injected*,
not read ad hoc: callers hold the returned object.

**Overlay source is a swappable seam.** M0 ships an in-memory :class:`OverlayStore` (overlays
registered by ``client_id`` / ``(client_id, icp_id)``). A later milestone can back the same
protocol with versioned DB rows without touching any caller (conventions §2 "policy is data").

**Validation fails fast on load.** Building an overlay from untrusted data
(:func:`overlay_from_mapping`) raises on an unknown posture, an unknown jurisdiction key, or an
out-of-range cap/weight — the pydantic enum/constraint machinery is the enforcement, surfaced as
:class:`ConfigError`.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from clue_research.config.models import Config, ConfigOverlay, ConfigVersion
from clue_research.config.policy import JurisdictionPolicy

# The base layer: the conservative, GDPR-grade, full-sweep defaults (Doc D §6 Option 1). Its
# version is layer "defaults"@1. Frozen models => safe to share this single instance.
_DEFAULTS_VERSION = ConfigVersion(layer="defaults", version=1, label="conservative-default")


class ConfigError(ValueError):
    """Raised when config fails to load or validate (unknown posture/jurisdiction/out-of-range cap).

    A subclass of :class:`ValueError` so callers can catch either; carries the underlying
    :class:`pydantic.ValidationError` (if any) for diagnostics.
    """

    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.__cause__ = cause


class OverlayStore:
    """In-memory store of config overlays keyed by client / (client, icp) — a swappable seam.

    M0 implementation. A client overlay applies to every ICP of that client; an ICP overlay
    applies on top of it. Registration is explicit (tests and Stage 0 set overlays); production
    later swaps this for a DB-backed store behind the same surface — no caller changes.
    """

    def __init__(self) -> None:
        self._client: dict[str, ConfigOverlay] = {}
        self._icp: dict[tuple[str, str], ConfigOverlay] = {}

    def set_client_overlay(self, client_id: str, overlay: ConfigOverlay) -> None:
        self._client[client_id] = overlay

    def set_icp_overlay(self, client_id: str, icp_id: str, overlay: ConfigOverlay) -> None:
        self._icp[(client_id, icp_id)] = overlay

    def client_overlay(self, client_id: str) -> ConfigOverlay | None:
        return self._client.get(client_id)

    def icp_overlay(self, client_id: str, icp_id: str) -> ConfigOverlay | None:
        return self._icp.get((client_id, icp_id))

    def clear(self) -> None:
        self._client.clear()
        self._icp.clear()


# Process-wide default store. Injected explicitly in tests/Stage 0; never read as global mutable
# state by the engine (callers receive the merged Config from get_config and hold it).
_DEFAULT_STORE = OverlayStore()


def default_store() -> OverlayStore:
    """The process default :class:`OverlayStore` (used when ``get_config`` gets no store arg)."""
    return _DEFAULT_STORE


def overlay_from_mapping(data: dict[str, Any]) -> ConfigOverlay:
    """Build a :class:`ConfigOverlay` from untrusted/raw config data, failing fast on bad values.

    This is the load boundary: an unknown ``posture``/``jurisdiction`` enum value, an out-of-range
    budget cap, or an out-of-range scoring weight raises :class:`ConfigError` here (acceptance
    criterion: reject on load), rather than surfacing deep inside an engine later.
    """
    try:
        return ConfigOverlay.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"invalid config overlay: {exc}", cause=exc) from exc


def _merge(base: Config, overlay: ConfigOverlay, version: ConfigVersion) -> Config:
    """Apply a sparse overlay onto a dense base, recording the layer version.

    Sub-tree semantics: a present sub-tree on the overlay replaces the base's; an absent one is
    inherited. (No partial sub-tree merge — see :class:`ConfigOverlay`.)
    """
    updates: dict[str, Any] = {}
    if overlay.policy is not None:
        updates["policy"] = overlay.policy
    if overlay.merge_policy is not None:
        updates["merge_policy"] = overlay.merge_policy
    if overlay.scoring_rubric is not None:
        updates["scoring_rubric"] = overlay.scoring_rubric
    if overlay.source_profiles is not None:
        updates["source_profiles"] = overlay.source_profiles
    if overlay.confidence_thresholds is not None:
        updates["confidence_thresholds"] = overlay.confidence_thresholds
    if overlay.source_plan_policy is not None:
        updates["source_plan_policy"] = overlay.source_plan_policy
    if overlay.budget_caps is not None:
        updates["budget_caps"] = overlay.budget_caps
    if overlay.recursion_policy is not None:
        updates["recursion_policy"] = overlay.recursion_policy
    if overlay.freshness_ttls is not None:
        updates["freshness_ttls"] = overlay.freshness_ttls
    if overlay.gateway is not None:
        updates["gateway"] = overlay.gateway
    if overlay.verification_health_thresholds is not None:
        updates["verification_health_thresholds"] = overlay.verification_health_thresholds
    # `is not None` (not truthiness) so an explicit `False` overrides the default `True`.
    if overlay.observability_client_facing is not None:
        updates["observability_client_facing"] = overlay.observability_client_facing
    applied = (*base.applied_versions, version)
    return base.model_copy(update={**updates, "applied_versions": applied})


def get_config(
    client_id: str,
    icp_id: str | None = None,
    *,
    store: OverlayStore | None = None,
) -> Config:
    """Return the merged, validated config for a client (and optionally an ICP).

    Precedence: **defaults → per-client → per-ICP**. Each contributing layer's version is recorded
    on ``Config.applied_versions`` (base-first). The returned object is dense and immutable; the
    caller holds it (config is injected, not re-read).
    """
    overlay_store = store if store is not None else _DEFAULT_STORE

    # Layer 0 — defaults (the dense base; every "policy is data" surface present + conservative).
    config = Config(
        client_id=client_id,
        icp_id=icp_id,
        applied_versions=(_DEFAULTS_VERSION,),
    )

    # Layer 1 — per-client overlay.
    client_overlay = overlay_store.client_overlay(client_id)
    if client_overlay is not None:
        version = client_overlay.version or ConfigVersion(layer="client")
        config = _merge(config, client_overlay, version)

    # Layer 2 — per-ICP / per-campaign overlay.
    if icp_id is not None:
        icp_overlay = overlay_store.icp_overlay(client_id, icp_id)
        if icp_overlay is not None:
            version = icp_overlay.version or ConfigVersion(layer="icp")
            config = _merge(config, icp_overlay, version)

    # Re-validate the fully-merged object so a cap/weight made out-of-range by an overlay
    # combination is caught on load (defense in depth; each layer was already validated).
    try:
        return Config.model_validate(config.model_dump())
    except ValidationError as exc:  # pragma: no cover - frozen sub-models already validated
        raise ConfigError(f"merged config failed validation: {exc}", cause=exc) from exc


def get_policy(client_id: str, *, store: OverlayStore | None = None) -> JurisdictionPolicy:
    """Return the jurisdiction/use-class/posture policy for a client.

    The use-gate (M10) and the source-scope decision (M4) read this. A client with no overrides
    gets the conservative default: posture = Option 1, jurisdiction = GDPR-grade, source-scope =
    full sweep, ``sensitive`` ⇒ not usable for outreach (Doc D §6 Option 1).
    """
    return get_config(client_id, store=store).policy
