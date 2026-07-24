"""Test doubles + DB harness for M8 deep profiling (Track A account + Track B committee/contact).

Mirrors the M4 source-registry / claim-store harness (DRY: reuses the M0.3 reachable-DB probe +
``run_async``): the schema is migrated to head once per session and every test runs inside an
always-rolled-back transaction, so tests never see or leave each other's ``claim`` /
``field_definition`` / ``account_entity`` / ``source_manifest`` rows. Pure (no-DB) tests cover the
target-lock / resonance-firewall / role / use-class / binding logic, the stopping rule and
coverage; the worker / admission / field-pack tests use the migrated DB and ``pytest.skip`` without
a reachable ``CLUE_DATABASE_URL`` so ``make check`` stays green. The in-process resolver binding is
cleared around every test (it is module-global). The doubles model the seams a real
committee/contact run depends on: a grounded :class:`CommitteeSource`, the :class:`LLMGateway`, and
a facet :class:`~clue_core.resolver.Resolver`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    AccountEntity,
    Claim,
    Completion,
    Confidence,
    ContactEntity,
    CostCents,
    EmbeddingResult,
    Entity,
    EntityId,
    EntityScope,
    ExtractionMethod,
    FieldDef,
    ICPCreatedFrom,
    ICPSpec,
    IdentityBinding,
    Message,
    Modality,
    ResearchMode,
    SourceManifest,
    UseClass,
    contact_claim,
    new_run_id,
)
from clue_db import db_lifespan
from clue_research.claimstore import load_core_pack
from clue_research.identity import (
    get_account,
    get_contact,
    insert_account_entity,
    insert_contact_entity,
)
from clue_research.profiling.committee import load_committee_pack
from clue_research.profiling.committee.sources import CommitteePersonCandidate
from clue_research.profiling.fields import load_deep_profiling_pack
from clue_research.sources import RegistrySourceManifest, register_source

# Accounts are workspace-local ([B3×research]): every account needs a seeded ``workspace`` row.
from tests._workspace import DEFAULT_TEST_WORKSPACE, seed_workspace

# Reuse the M0.3 helpers (DRY): the single-loop coroutine runner + the reachable-DB gate.
from tests.db.conftest import _db_available
from tests.db.conftest import run_async as run_async

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config() -> Config:
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    return cfg


@pytest.fixture(scope="session")
def migrated_db() -> bool:
    """Migrate to head once per session when a DB is reachable; return whether it is."""
    if not _db_available():
        return False
    command.upgrade(_alembic_config(), "head")
    return True


@pytest.fixture
def require_profiling_db(migrated_db: bool) -> None:
    """Skip unless a migrated, reachable DB is available (so ``make check`` stays green w/o one)."""
    if not migrated_db:
        pytest.skip(
            "CLUE_DATABASE_URL unset or database unreachable; "
            "set it and run `make db-up` to exercise the M8 profiling DB tests"
        )


@pytest.fixture
def require_db(migrated_db: bool) -> None:
    """Skip unless a migrated, reachable DB is available.

    Track A's account-axis tests declare ``pytestmark = usefixtures("require_db")``; this is the
    same gate as :func:`require_profiling_db` under the name those tests use.
    """
    if not migrated_db:
        pytest.skip(
            "CLUE_DATABASE_URL unset or database unreachable; "
            "set it and run a per-branch DB container to exercise the deep-profiling DB tests"
        )


@pytest.fixture(autouse=True)
def _clear_resolver_bindings() -> Iterator[None]:
    """Reset the process-global resolver registry around every test (M8.4 fill tests bind fake
    facet resolvers via ``sources.bind_resolver``; without it a binding leaks into later tests)."""
    from clue_research.sources import clear_resolver_bindings

    clear_resolver_bindings()
    yield
    clear_resolver_bindings()


@asynccontextmanager
async def rollback_conn(*, seed_pack: bool = True) -> AsyncIterator[AsyncConnection]:
    """Yield a pooled connection inside an always-rolled-back transaction (per-test isolation).

    Defaults to seeding the M1 core pack **and** the M8 deep-profiling pack (so the
    ``account.resonance.*`` / ``contact.facet.*`` field-classes + the account-axis gap fields
    resolve); pass ``seed_pack=False`` for a bare connection. The committee pack is intentionally
    **not** auto-seeded here — the contact/committee tests load it explicitly via :func:`seed_packs`
    (or ``load_committee_pack``), so ``committee/test_committee_fields.py``'s direct
    ``load_committee_pack`` stays a genuine first-insert. Re-seeding is safe: the pack loaders are
    idempotent (``register_field`` is a read-then-conditional-insert on the open transaction), so a
    test that auto-seeds here and also calls ``seed_packs`` is a no-op re-register, never an error.
    """
    async with db_lifespan() as engine:
        conn = await engine.connect()
        trans = await conn.begin()
        try:
            if seed_pack:
                await load_core_pack(conn)
                await load_deep_profiling_pack(conn)
            yield conn
        finally:
            await trans.rollback()
            await conn.close()


def conn_session_factory(conn: AsyncConnection):
    """A ``ConnFactory`` that hands the worker the *test's* rolled-back connection.

    The deep workers (and ``profile_account``) open their own session via an injected
    ``session_factory``; in tests we inject this so the worker reads/writes the same rolled-back
    transaction the test seeded on — never committing, never opening a second connection. The
    ``__aexit__`` is a no-op: the outer :func:`rollback_conn` owns the transaction lifecycle.
    """

    @asynccontextmanager
    async def _factory() -> AsyncIterator[AsyncConnection]:
        yield conn

    return _factory


async def seed_packs(conn: AsyncConnection) -> None:
    """Register the field packs the profiling tests need (idempotent): the core pack + the M8 seed
    (resonance/facet) + the M8.3 committee pack."""
    await load_core_pack(conn)
    await load_deep_profiling_pack(conn)
    await load_committee_pack(conn)


async def register_facet_source(
    conn: AsyncConnection, source_key: str = "exa_deep", *, tier: int = 4
) -> None:
    """Register the facet ``tier_plan`` source a test binds its fake resolver to.

    M8.4's fill now runs through the shared waterfall engine, which (correctly) SKIPS an
    unregistered source instead of resolving it — so a bound fake must sit behind a real manifest.
    ``exa_deep`` is also a committed production seed (v1: BOTH scope, cost 10) on a persistent
    schema, so the test variant registers at **version 2** — a versioned update inside the test's
    rolled-back transaction (the rerun-idempotency pattern, cf. the AC-6 gate test) — which also
    makes the manifest deterministic regardless of suite order. ``tier`` lets the sanctioned
    lower-tier fixtures bind a genuine tier-3 manifest (the engine enforces claim tier == manifest
    tier)."""
    await register_source(
        conn,
        RegistrySourceManifest(
            manifest=SourceManifest(
                source_key=source_key,
                modality=Modality.TEXT,
                entity_scope=EntityScope.CONTACT,
                yields=("contact.facet",),
                tier=tier,
                cost_cents=Decimal(0),
            ),
            active=True,
            version=2,
        ),
    )


async def insert_test_account(
    conn: AsyncConnection,
    *,
    name: str = "Acme Robotics",
    domain: str | None = "acme.example",
    workspace_id: str = DEFAULT_TEST_WORKSPACE,
) -> AccountEntity:
    """Insert a resolved, workspace-stamped account entity and return its full record.

    Accounts are workspace-local ([B3×research]); this seeds the ``workspace`` row (idempotent) so
    the account-entity workspace FK is satisfiable, then stamps ``workspace_id`` on the account —
    so every committee/profiling suite that creates its account through this helper is fixed
    centrally (and the admitted contact inherits this workspace)."""
    await seed_workspace(conn, workspace_id)
    account_id = await insert_account_entity(
        conn, canonical_name=name, primary_domain=domain, workspace_id=workspace_id
    )
    account = await get_account(conn, account_id)
    assert account is not None
    return account


async def insert_test_contact(
    conn: AsyncConnection,
    account: AccountEntity,
    *,
    full_name: str = "Jane CFO",
    linkedin_url: str | None = "https://linkedin.com/in/jane-cfo",
    verified_email: str | None = None,
) -> ContactEntity:
    """Insert a resolved contact under an account and return its full record (M8.4's input)."""
    contact_id = await insert_contact_entity(
        conn,
        account_entity_id=account.id,
        full_name=full_name,
        linkedin_url=linkedin_url,
        verified_email=verified_email,
    )
    contact = await get_contact(conn, contact_id)
    assert contact is not None
    return contact


def icp_spec() -> ICPSpec:
    """A minimal in-memory ICP spec (committee discovery reads org context, not the rubric)."""
    return ICPSpec(
        workspace_id="acme",
        icp_key="default",
        created_from=ICPCreatedFrom.SYNTHESIS,
    )


def make_candidate(
    *,
    source_key: str = "apollo_people",
    linkedin_url: str | None = None,
    verified_email: str | None = None,
    full_name: str | None = None,
    title: str | None = None,
    source_url: str | None = None,
    matched_signal: str = "leadership page",
    discovery_confidence: Confidence = 0.8,
    cost_cents: CostCents = Decimal(0),
) -> CommitteePersonCandidate:
    """Build a grounded committee candidate (the shape a real source returns)."""
    return CommitteePersonCandidate(
        source_key=source_key,
        linkedin_url=linkedin_url,
        verified_email=verified_email,
        full_name=full_name,
        title=title,
        source_url=source_url,
        matched_signal=matched_signal,
        discovery_confidence=discovery_confidence,
        cost_cents=cost_cents,
    )


@dataclass
class FakeCommitteeSource:
    """A :class:`CommitteeSource` double: returns its canned candidates and counts calls (so a test
    can assert bounded querying / provider-swap behaviour)."""

    source_key: str
    tier: int
    candidates: list[CommitteePersonCandidate] = field(default_factory=list)
    calls: int = 0

    async def find_candidates(
        self, account: AccountEntity, *, limit: int
    ) -> Sequence[CommitteePersonCandidate]:
        self.calls += 1
        return list(self.candidates[:limit])


@dataclass
class FakeGateway:
    """An :class:`LLMGateway` double: ``complete`` returns a canned (configurable) reply so the role
    parser's success path is exercised; ``embed`` is unused. ``complete_calls`` lets a test assert
    role inference ran. The real ``StubGateway`` (non-JSON output) covers the fail-safe path."""

    reply: str = '{"role": "economic_buyer", "confidence": 0.9, "rationale": "CFO has budget"}'
    cost_cents: CostCents = Decimal(0)
    complete_calls: int = 0

    def complete(self, *, model: str, messages: list[Message], **opts: object) -> Completion:
        self.complete_calls += 1
        return Completion(model=model, text=self.reply, cost_cents=self.cost_cents)

    def embed(self, *, model: str, inputs: list[str]) -> EmbeddingResult:
        return EmbeddingResult(model=model, vectors=())


@dataclass
class FakeFacetResolver:
    """A :class:`~clue_core.resolver.Resolver` double for M8.4's facet fill: returns tier-4
    facet claims with *placeholder* tags (binding=WEAK, use_class=professional-public) — what a real
    resolver must set just to construct a facet claim — so the test can assert M8.4 *re-tags* them
    with the authoritative per-claim binding + use-class. Bind it via ``sources.bind_resolver`` and
    clear with ``sources.clear_resolver_bindings``."""

    tier: int = 4
    # Each extraction: {"value_json", "evidence_span", "source_url", "confidence"}.
    extractions: list[dict[str, object]] = field(default_factory=list)

    def resolve(self, entity: Entity, field_def: FieldDef) -> list[Claim]:
        method = ExtractionMethod.LLM_SYNTHESIS if self.tier == 4 else ExtractionMethod.SCRAPE
        claims: list[Claim] = []
        for ext in self.extractions:
            claims.append(
                contact_claim(
                    entity_id=entity.entity_id,
                    field_key=field_def.field_key,
                    value_json=ext["value_json"],  # type: ignore[arg-type]
                    source_tier=self.tier,
                    extraction_method=method,
                    confidence=float(ext.get("confidence", 0.9)),  # type: ignore[arg-type]
                    run_id=new_run_id(),  # placeholder — M8.4 overrides via revalidate_with
                    research_mode=ResearchMode.CONTACT_PROFILING,
                    identity_binding=IdentityBinding.WEAK,  # placeholder — M8.4 re-tags
                    use_class=UseClass.PROFESSIONAL_PUBLIC,  # placeholder — M8.4 re-tags
                    source_url=ext.get("source_url"),  # type: ignore[arg-type]
                    evidence_span=ext.get("evidence_span"),  # type: ignore[arg-type]
                )
            )
        return claims


__all__ = [
    "run_async",
    "rollback_conn",
    "conn_session_factory",
    "migrated_db",
    "require_profiling_db",
    "require_db",
    "seed_packs",
    "register_facet_source",
    "insert_test_account",
    "insert_test_contact",
    "icp_spec",
    "make_candidate",
    "FakeCommitteeSource",
    "FakeGateway",
    "FakeFacetResolver",
    "EntityId",
]
