"""The registry-row source manifest — the wrapper over the core capability contract (M4.2).

Locked decision #2: *wrap, don't redefine.* :class:`clue_research.core.SourceManifest` is the
M0.2 capability contract (staged-flow §7a) and stays clean; :class:`RegistrySourceManifest` embeds
it and adds the operational metadata a registry row needs — ``active``, ``provider`` (vendor/human
name, for billing/ops ONLY, **never** branched on by callers), ``auth_ref`` (a reference into the
credential store, **never** the secret itself), ``rate_limit``, ``requires_adapter`` (the M4.3
modality-adapter key), ``version``, ``created_at``.

Ergonomic delegates (``source_key``/``tier``/``modality``/…) read through to the embedded manifest
so callers need not reach into ``.manifest`` for the common fields.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from clue_research.core import EntityScope, IdentityBinding, Modality, SourceManifest


class RegistrySourceManifest(BaseModel):
    """A ``source_manifest`` registry row: the core capability manifest + operational metadata."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest: SourceManifest
    active: bool = True
    # The vendor/human name — used ONLY for billing/observability, NEVER read by callers as control
    # flow (so "nothing downstream knows Clay specifically exists" stays a checkable invariant).
    provider: str | None = None
    # A reference into the credential store (e.g. an env-var name / secret id) — NEVER the secret.
    auth_ref: str | None = None
    rate_limit: dict[str, JsonValue] | None = None
    requires_adapter: str | None = None  # the M4.3 modality-adapter key, if this source needs one
    version: int = Field(default=1, ge=1)
    created_at: datetime | None = None  # set by the DB DEFAULT now(); populated on read

    @property
    def source_key(self) -> str:
        return self.manifest.source_key

    @property
    def tier(self) -> int:
        return self.manifest.tier

    @property
    def modality(self) -> Modality:
        return self.manifest.modality

    @property
    def entity_scope(self) -> EntityScope:
        return self.manifest.entity_scope

    @property
    def yields(self) -> tuple[str, ...]:
        return self.manifest.yields

    @property
    def identity_binding_strength(self) -> IdentityBinding | None:
        return self.manifest.identity_binding_strength
