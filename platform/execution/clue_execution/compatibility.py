"""Exact compatibility-pin resolution for immutable recipe revisions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from clue_execution.models import Incompatibility, PinRequest, ResolvedPin


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class CompatibilityManifest(_FrozenModel):
    execution: tuple[PinRequest, ...] = ()
    nodes: dict[str, tuple[PinRequest, ...]] = Field(default_factory=dict)


class CompatibilityContext(_FrozenModel):
    workspace_id: str = Field(min_length=1)
    project_id: str | None = None
    attributes: dict[str, JsonValue] = Field(default_factory=dict)


class ResourceObservation(_FrozenModel):
    version: str | None
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: str = Field(min_length=1)
    metadata: dict[str, str | int | bool | None] = Field(default_factory=dict)


class PinResolver(Protocol):
    @property
    def kind(self) -> str: ...

    async def observe(
        self,
        request: PinRequest,
        context: CompatibilityContext,
    ) -> ResourceObservation | None: ...


ObservationLoader = Callable[
    [PinRequest, CompatibilityContext],
    Awaitable[ResourceObservation | None],
]


@dataclass(frozen=True, slots=True)
class CallablePinResolver:
    kind: str
    loader: ObservationLoader

    async def observe(
        self,
        request: PinRequest,
        context: CompatibilityContext,
    ) -> ResourceObservation | None:
        return await self.loader(request, context)


class PinResolverRegistry:
    """Open-by-registration resolver catalog; duplicate kinds are wiring errors."""

    def __init__(self) -> None:
        self._resolvers: dict[str, PinResolver] = {}

    def register(self, resolver: PinResolver) -> None:
        kind = resolver.kind.strip()
        if not kind:
            raise ValueError("pin resolver kind must be non-empty")
        if kind in self._resolvers:
            raise ValueError(f"pin resolver kind {kind!r} is already registered")
        self._resolvers[kind] = resolver

    def get(self, kind: str) -> PinResolver | None:
        return self._resolvers.get(kind)

    def kinds(self) -> tuple[str, ...]:
        return tuple(sorted(self._resolvers))


class CompatibilityReport(_FrozenModel):
    pins: tuple[ResolvedPin, ...] = ()
    incompatibilities: tuple[Incompatibility, ...] = ()
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @property
    def compatible(self) -> bool:
        return not self.incompatibilities


def canonical_payload_digest(payload: object) -> str:
    """The same digest for the same payload in every process.

    A set has no order, and Python iterates one in a per-process order (hash randomization), so
    a set is hashed as its items sorted. Without this, two workers pinned the same policy under
    different digests and a turn retried on another worker failed as a conflicting replay. A
    payload with no set inside hashes exactly as it always did.
    """
    if isinstance(payload, BaseModel):
        value: object = _sort_sets(
            payload.model_dump(mode="json", exclude_none=False),
            payload.model_dump(mode="python", exclude_none=False),
        )
    else:
        value = _sort_sets(payload, payload)
    return hashlib.sha256(_dumps(value).encode()).hexdigest()


def _dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sort_sets(value: object, shape: object) -> object:
    """``value`` with every set in ``shape`` (its Python-mode twin) turned into a sorted list."""

    if isinstance(shape, BaseModel):
        if value is shape:  # a model inside a plain payload: hash its JSON, not its repr
            value = shape.model_dump(mode="json", exclude_none=False)
        return _sort_sets(value, shape.model_dump(mode="python", exclude_none=False))
    if isinstance(shape, (set, frozenset)):
        # The JSON dump lists a set's items in the same order the set iterates in this process.
        items = value if isinstance(value, (list, tuple)) else list(shape)
        twins = list(shape)
        return sorted(
            (_sort_sets(item, twin) for item, twin in zip(items, twins, strict=True)), key=_dumps
        )
    if isinstance(value, dict) and isinstance(shape, dict):
        return {key: _sort_sets(item, shape.get(key)) for key, item in value.items()}
    if isinstance(value, (list, tuple)) and isinstance(shape, (list, tuple)):
        return [_sort_sets(item, twin) for item, twin in zip(value, shape, strict=True)]
    return value


def _sort_key(request: PinRequest) -> tuple[str, str, str, str]:
    return (request.kind, request.key, request.version or "", request.digest or "")


def _pin_sort_key(pin: ResolvedPin) -> tuple[str, str, str, str]:
    return (pin.kind, pin.key, pin.version or "", pin.digest)


def _incompatibility_sort_key(
    item: Incompatibility,
) -> tuple[str, str, str, str, str]:
    return (
        item.kind,
        item.key,
        item.requested_version or "",
        item.requested_digest or "",
        item.reason,
    )


class CompatibilityLoader:
    """Resolve every requirement and return a complete, deterministic report."""

    def __init__(self, registry: PinResolverRegistry) -> None:
        self._registry = registry

    async def load(
        self,
        manifest: CompatibilityManifest,
        *,
        context: CompatibilityContext,
    ) -> CompatibilityReport:
        requirements = list(manifest.execution)
        for node_key in sorted(manifest.nodes):
            requirements.extend(manifest.nodes[node_key])
        return await self._resolve(requirements, context=context)

    async def recheck_node(
        self,
        manifest: CompatibilityManifest,
        *,
        node_key: str,
        context: CompatibilityContext,
    ) -> CompatibilityReport:
        """Re-resolve execution and node-local pins immediately before dispatch."""
        return await self._resolve(
            (*manifest.execution, *manifest.nodes.get(node_key, ())),
            context=context,
        )

    async def resolve_requirements(
        self,
        requirements: Sequence[PinRequest],
        *,
        context: CompatibilityContext,
    ) -> CompatibilityReport:
        """Resolve an execution-time exact requirement set.

        Immutable recipes use :meth:`load` at promotion/start. Dynamic children declared by a
        bounded recipe slot do not exist at promotion time, so they carry their own exact
        requests and use this same resolver immediately before materialization and dispatch.
        """
        return await self._resolve(requirements, context=context)

    async def observe_current(
        self,
        *,
        kind: str,
        key: str,
        context: CompatibilityContext,
    ) -> ResourceObservation | None:
        """Observe a resource so an API-root pin builder can freeze its exact version/digest."""
        resolver = self._registry.get(kind)
        if resolver is None:
            return None
        probe = PinRequest(kind=kind, key=key, version="__observe_current__", required=False)
        return await resolver.observe(probe, context)

    async def _resolve(
        self,
        requirements: Sequence[PinRequest],
        *,
        context: CompatibilityContext,
    ) -> CompatibilityReport:
        pins: list[ResolvedPin] = []
        incompatibilities: list[Incompatibility] = []
        seen: dict[tuple[str, str], PinRequest] = {}
        for request in sorted(requirements, key=_sort_key):
            identity = (request.kind, request.key)
            prior = seen.get(identity)
            if prior is not None:
                if (
                    prior.version is not None
                    and request.version is not None
                    and prior.version != request.version
                ) or (
                    prior.digest is not None
                    and request.digest is not None
                    and prior.digest != request.digest
                ):
                    incompatibilities.append(
                        Incompatibility(
                            kind=request.kind,
                            key=request.key,
                            requested_version=request.version,
                            requested_digest=request.digest,
                            reason="conflicting_requirement",
                        )
                    )
                    continue
                # A dynamic node may refine a recipe's version-only pin with its exact digest.
                # Combine constraints before observing the resource so neither the content hash
                # nor a required=True declaration can be lost behind a weaker duplicate.
                request = request.model_copy(
                    update={
                        "version": prior.version or request.version,
                        "digest": prior.digest or request.digest,
                        "required": prior.required or request.required,
                    }
                )
            seen[identity] = request
        for request in seen.values():
            resolver = self._registry.get(request.kind)
            if resolver is None:
                incompatibilities.append(
                    Incompatibility(
                        kind=request.kind,
                        key=request.key,
                        requested_version=request.version,
                        requested_digest=request.digest,
                        reason="unsupported_kind",
                    )
                )
                continue
            try:
                observation = await resolver.observe(request, context)
            except Exception as exc:
                incompatibilities.append(
                    Incompatibility(
                        kind=request.kind,
                        key=request.key,
                        requested_version=request.version,
                        requested_digest=request.digest,
                        reason=f"resolver_error:{type(exc).__name__}",
                    )
                )
                continue
            if observation is None:
                if request.required:
                    incompatibilities.append(
                        Incompatibility(
                            kind=request.kind,
                            key=request.key,
                            requested_version=request.version,
                            requested_digest=request.digest,
                            observed_status="missing",
                            reason="missing",
                        )
                    )
                else:
                    pins.append(
                        ResolvedPin(
                            kind=request.kind,
                            key=request.key,
                            version=None,
                            digest=canonical_payload_digest(
                                {"kind": request.kind, "key": request.key, "status": "missing"}
                            ),
                            status="missing",
                        )
                    )
                continue
            if observation.status != "active" and request.required:
                incompatibilities.append(
                    Incompatibility(
                        kind=request.kind,
                        key=request.key,
                        requested_version=request.version,
                        requested_digest=request.digest,
                        observed_status=observation.status,
                        observed_version=observation.version,
                        reason=(
                            "memory_disabled"
                            if request.kind == "memory_switch" and observation.status == "disabled"
                            else observation.status
                        ),
                    )
                )
                continue
            if request.version is not None and observation.version != request.version:
                incompatibilities.append(
                    Incompatibility(
                        kind=request.kind,
                        key=request.key,
                        requested_version=request.version,
                        requested_digest=request.digest,
                        observed_status=observation.status,
                        observed_version=observation.version,
                        reason="version_mismatch",
                    )
                )
                continue
            if request.digest is not None and observation.digest != request.digest:
                incompatibilities.append(
                    Incompatibility(
                        kind=request.kind,
                        key=request.key,
                        requested_version=request.version,
                        requested_digest=request.digest,
                        observed_status=observation.status,
                        observed_version=observation.version,
                        reason="digest_mismatch",
                    )
                )
                continue
            pins.append(
                ResolvedPin(
                    kind=request.kind,
                    key=request.key,
                    version=observation.version,
                    digest=observation.digest,
                    status=observation.status,
                    metadata=observation.metadata,
                )
            )
        ordered_pins = tuple(sorted(pins, key=_pin_sort_key))
        ordered_incompatibilities = tuple(sorted(incompatibilities, key=_incompatibility_sort_key))
        report_sha256 = canonical_payload_digest(
            {
                "pins": [pin.model_dump(mode="json") for pin in ordered_pins],
                "incompatibilities": [
                    item.model_dump(mode="json") for item in ordered_incompatibilities
                ],
            }
        )
        return CompatibilityReport(
            pins=ordered_pins,
            incompatibilities=ordered_incompatibilities,
            report_sha256=report_sha256,
        )


__all__ = [
    "CallablePinResolver",
    "CompatibilityContext",
    "CompatibilityLoader",
    "CompatibilityManifest",
    "CompatibilityReport",
    "ObservationLoader",
    "PinResolver",
    "PinResolverRegistry",
    "ResourceObservation",
    "canonical_payload_digest",
]
