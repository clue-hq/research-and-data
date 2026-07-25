"""C2 generic-web resolver contract through the existing governed waterfall."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from clue_core import (
    Claim,
    ClaimDraft,
    Entity,
    EntityId,
    EntityType,
    FieldDef,
    IdentityBinding,
    NormalizedText,
    PassKind,
    RawArtifact,
    ResearchMode,
    Resolver,
    SourceManifest,
    UseClass,
    new_entity_id,
    new_run_id,
    revalidate_with,
)
from clue_research.adapters import CallableClaimExtractor, span_for
from clue_research.claimstore import ALL_WORKSPACES, claims_for
from clue_research.resolvers.generic_web import (
    GenericWebPolicy,
    GenericWebResolver,
    GenericWebTarget,
    generic_web_manifest,
    register_generic_web_resolver,
)
from clue_research.sources import register_source, resolve_field
from clue_storage import FsStorage, SnapshotSink, get_artifact
from tests._workspace import seed_workspace

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_db")

_FACT = "Acme launched a partner ecosystem program in 2026"
_PAGE = f"# Industry registry\n\nVerified profile: {_FACT}."


class _Targets:
    def __init__(self, target: GenericWebTarget | None) -> None:
        self.target = target
        self.calls: list[tuple[EntityId, str]] = []

    def target_for(self, entity_id: EntityId, field_key: str) -> GenericWebTarget | None:
        self.calls.append((entity_id, field_key))
        return self.target


class _Scraper:
    def __init__(self, events: list[str] | None = None) -> None:
        self.calls: list[str] = []
        self.events = events

    def scrape(self, ref: str, ctx: object) -> RawArtifact:
        self.calls.append(ref)
        if self.events is not None:
            self.events.append("scrape")
        return RawArtifact(
            ref=ref,
            media_type="text/markdown",
            content=_PAGE.encode(),
            metadata={"backend": "test"},
        )


def _extractor(*, contact: bool = False) -> CallableClaimExtractor:
    def extract(normalized: NormalizedText, entity: Entity, field: FieldDef) -> list[ClaimDraft]:
        return [
            ClaimDraft(
                field_key=field.field_key,
                value=_FACT,
                evidence_span=span_for(normalized.text, _FACT),
                confidence=0.9,
                use_class=UseClass.PROFESSIONAL_PUBLIC if contact else None,
            )
        ]

    return CallableClaimExtractor(extract)


def _account_field() -> FieldDef:
    return FieldDef(
        field_key="account.strategic_moves",
        value_type="str",
        tier_plan=("generic_web",),
        pass_kind=PassKind.DEEP,
    )


def test_manifest_and_resolver_are_fixed_tier3_contracts() -> None:
    entity_id = new_entity_id()
    target = GenericWebTarget(
        entity_id=entity_id,
        field_key="account.strategic_moves",
        url="https://registry.example/acme",
        approved_domain="registry.example",
    )
    resolver = GenericWebResolver(
        generic_web_manifest(), targets=_Targets(target), extractor=_extractor()
    )
    assert isinstance(resolver, Resolver)
    assert resolver.tier == 3
    assert generic_web_manifest().tier == 3


def test_target_shape_and_exclusion_fail_before_scrape() -> None:
    with pytest.raises(ValidationError, match="approved domain"):
        GenericWebTarget(
            entity_id=new_entity_id(),
            field_key="account.strategic_moves",
            url="https://wrong.example/acme",
            approved_domain="registry.example",
        )

    entity = Entity(entity_id=new_entity_id(), entity_type=EntityType.ACCOUNT)
    target = GenericWebTarget(
        entity_id=entity.entity_id,
        field_key="account.strategic_moves",
        url="https://registry.example/acme",
        approved_domain="registry.example",
    )
    scraper = _Scraper()
    register_generic_web_resolver(
        targets=_Targets(target),
        extractor=_extractor(),
        scraper=scraper,
        policy=GenericWebPolicy(excluded_hosts=frozenset({"registry.example"})),
    )
    resolver = GenericWebResolver(
        generic_web_manifest(),
        targets=_Targets(target),
        extractor=_extractor(),
        policy=GenericWebPolicy(excluded_hosts=frozenset({"registry.example"})),
    )
    assert resolver.resolve(entity, _account_field()) == []
    assert scraper.calls == []


def test_waterfall_orders_gate_scrape_tagger_and_persists_snapshot(tmp_path: object) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            entity = Entity(entity_id=new_entity_id(), entity_type=EntityType.ACCOUNT)
            field = _account_field()
            target = GenericWebTarget(
                entity_id=entity.entity_id,
                field_key=field.field_key,
                url="https://registry.example/acme",
                approved_domain="registry.example",
            )
            events: list[str] = []
            scraper = _Scraper(events)
            manifest = register_generic_web_resolver(
                targets=_Targets(target),
                extractor=_extractor(),
                scraper=scraper,
            )
            await register_source(conn, manifest)
            sink = SnapshotSink()
            storage = FsStorage(str(tmp_path))

            async def gate(source: SourceManifest) -> bool:
                events.append("gate")
                return True

            def tagger(claim: Claim) -> Claim:
                events.append("tag")
                return claim

            run_id = new_run_id()
            result = await resolve_field(
                conn,
                entity,
                field,
                mode=ResearchMode.ACCOUNT_PROFILING,
                run_id=run_id,
                source_gate=gate,
                claim_tagger=tagger,
                snapshots=sink,
                storage=storage,
            )
            assert result.claim_refs
            assert events == ["gate", "scrape", "tag"]
            assert scraper.calls == ["https://registry.example/acme"]

            (claim,) = await claims_for(
                conn, entity.entity_id, field.field_key, scope=ALL_WORKSPACES
            )
            assert claim.source_tier == 3
            assert claim.source_key == "generic_web"
            assert claim.run_id == run_id
            assert claim.source_url == "https://registry.example/acme"
            assert claim.evidence_span == _FACT
            assert claim.artifact_key is not None
            assert await get_artifact(conn, claim.artifact_key) is not None
            assert await storage.get(claim.artifact_key) == _PAGE.encode()

    run_async(scenario())


def test_contact_claim_flows_through_injected_classifier() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_workspace(conn, "workspace-contact")
            entity = Entity(entity_id=new_entity_id(), entity_type=EntityType.CONTACT)
            field = FieldDef(
                field_key="contact.facet.recent_post",
                value_type="str",
                tier_plan=("generic_web",),
                pass_kind=PassKind.DEEP,
            )
            target = GenericWebTarget(
                entity_id=entity.entity_id,
                field_key=field.field_key,
                url="https://registry.example/person",
                approved_domain="registry.example",
            )
            manifest = register_generic_web_resolver(
                targets=_Targets(target),
                extractor=_extractor(contact=True),
                scraper=_Scraper(),
            )
            await register_source(conn, manifest)
            classifications: list[IdentityBinding | None] = []

            def classify(claim: Claim) -> Claim:
                classifications.append(claim.identity_binding)
                return revalidate_with(claim, identity_binding=IdentityBinding.STRONG)

            await resolve_field(
                conn,
                entity,
                field,
                mode=ResearchMode.CONTACT_PROFILING,
                run_id=new_run_id(),
                workspace_id="workspace-contact",
                claim_tagger=classify,
            )
            (written,) = await claims_for(
                conn, entity.entity_id, field.field_key, scope=ALL_WORKSPACES
            )
            assert classifications == [IdentityBinding.WEAK]
            assert written.identity_binding is IdentityBinding.STRONG
            assert written.use_class is UseClass.PROFESSIONAL_PUBLIC

    run_async(scenario())


def test_wrong_entity_target_never_scrapes() -> None:
    entity = Entity(entity_id=new_entity_id(), entity_type=EntityType.ACCOUNT)
    target = GenericWebTarget(
        entity_id=new_entity_id(),
        field_key="account.strategic_moves",
        url="https://registry.example/lookalike",
        approved_domain="registry.example",
    )
    scraper = _Scraper()
    register_generic_web_resolver(targets=_Targets(target), extractor=_extractor(), scraper=scraper)
    resolver = GenericWebResolver(
        generic_web_manifest(), targets=_Targets(target), extractor=_extractor()
    )
    assert resolver.resolve(entity, _account_field()) == []
    assert scraper.calls == []
