"""Governed generic tier-3 web resolver for approved one-off public-source investigation.

The resolver is deliberately less authoritative than the official-site scraper. It can fetch only
the URL/domain target supplied for the exact resolved entity and field, uses the existing scrape
adapter/snapshot pipeline, and emits ordinary tier-3 claims. Pre-spend and contact classification
remain the waterfall's injected ``SourceGate``/``ClaimTagger`` responsibilities.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel, ConfigDict, model_validator

from clue_core import (
    Claim,
    Entity,
    EntityId,
    EntityScope,
    EntityType,
    FieldDef,
    IdentityBinding,
    Modality,
    ResearchMode,
    SourceManifest,
    new_run_id,
    normalize_host,
)
from clue_research.adapters import (
    ClaimExtractor,
    FirecrawlHtmlAdapter,
    ScrapeBackend,
    default_scrape_backend,
    register_adapter,
    run_chain,
)
from clue_research.sources import RegistrySourceManifest, bind_resolver
from clue_storage import SnapshotSink, current_snapshot_sink

GENERIC_WEB_SOURCE_KEY = "generic_web"
GENERIC_WEB_ADAPTER_KEY = "generic_web_html"


class GenericWebTarget(BaseModel):
    """An externally approved target, pinned to one resolved entity and field."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: EntityId
    field_key: str
    url: str
    approved_domain: str

    @model_validator(mode="after")
    def _target_lock_shape(self) -> GenericWebTarget:
        url_host = normalize_host(self.url)
        approved_host = normalize_host(self.approved_domain)
        if not url_host or not approved_host or url_host != approved_host:
            raise ValueError("generic-web URL must match its approved domain")
        return self


class GenericWebTargetLookup(Protocol):
    def target_for(self, entity_id: EntityId, field_key: str) -> GenericWebTarget | None: ...


class GenericWebPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    excluded_hosts: frozenset[str] = frozenset()

    def allows(self, target: GenericWebTarget) -> bool:
        return normalize_host(target.url) not in self.excluded_hosts


def generic_web_manifest() -> RegistrySourceManifest:
    """The registry entry integration registers before binding this resolver."""
    return RegistrySourceManifest(
        manifest=SourceManifest(
            source_key=GENERIC_WEB_SOURCE_KEY,
            modality=Modality.TEXT,
            entity_scope=EntityScope.BOTH,
            yields=("core", "account", "account.resonance", "contact", "contact.facet"),
            tier=3,
            cost_cents=Decimal(1),
            freshness_profile="snapshot",
            # Open public pages are never strong personal identity evidence by source prior alone.
            identity_binding_strength=IdentityBinding.WEAK,
        ),
        active=True,
        provider="generic_web",
        requires_adapter=GENERIC_WEB_ADAPTER_KEY,
        version=1,
    )


class GenericWebResolver:
    tier: int = 3

    def __init__(
        self,
        manifest: RegistrySourceManifest,
        *,
        targets: GenericWebTargetLookup,
        extractor: ClaimExtractor,
        policy: GenericWebPolicy | None = None,
        snapshots: SnapshotSink | None = None,
    ) -> None:
        if manifest.tier != 3:
            raise ValueError("generic web resolver must be bound to a tier-3 manifest")
        self._manifest = manifest
        self._targets = targets
        self._extractor = extractor
        self._policy = policy or GenericWebPolicy()
        self._snapshots = snapshots

    def resolve(self, entity: Entity, field: FieldDef) -> list[Claim]:
        target = self._targets.target_for(entity.entity_id, field.field_key)
        if (
            target is None
            or target.entity_id != entity.entity_id
            or target.field_key != field.field_key
            or normalize_host(target.url) != normalize_host(target.approved_domain)
            or not self._policy.allows(target)
        ):
            return []
        mode = (
            ResearchMode.CONTACT_PROFILING
            if entity.entity_type is EntityType.CONTACT
            else ResearchMode.ACCOUNT_PROFILING
        )
        return run_chain(
            self._manifest,
            target.url,
            entity,
            field,
            run_id=new_run_id(),
            research_mode=mode,
            extractor=self._extractor,
            params={
                "approved_domain": normalize_host(target.approved_domain),
                "target_entity_id": str(entity.entity_id),
            },
            snapshots=(self._snapshots if self._snapshots is not None else current_snapshot_sink()),
        )


def register_generic_web_resolver(
    *,
    targets: GenericWebTargetLookup,
    extractor: ClaimExtractor,
    scraper: ScrapeBackend | None = None,
    policy: GenericWebPolicy | None = None,
    snapshots: SnapshotSink | None = None,
    manifest: RegistrySourceManifest | None = None,
) -> RegistrySourceManifest:
    """Bind the generic resolver and its existing HTML→markdown adapter.

    Database registration remains an API-root integration concern. Returning the exact manifest
    gives that composition root the value it must register.
    """
    entry = manifest or generic_web_manifest()
    backend = scraper if scraper is not None else default_scrape_backend()
    register_adapter(
        entry.requires_adapter or GENERIC_WEB_ADAPTER_KEY,
        FirecrawlHtmlAdapter(scraper=backend),
    )
    bind_resolver(
        entry.source_key,
        GenericWebResolver(
            entry,
            targets=targets,
            extractor=extractor,
            policy=policy,
            snapshots=snapshots,
        ),
    )
    return entry


__all__ = [
    "GENERIC_WEB_ADAPTER_KEY",
    "GENERIC_WEB_SOURCE_KEY",
    "GenericWebPolicy",
    "GenericWebResolver",
    "GenericWebTarget",
    "GenericWebTargetLookup",
    "generic_web_manifest",
    "register_generic_web_resolver",
]
