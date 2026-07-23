"""M4.5 acceptance: the CRM import resolver (tier-1), exercised through the real M4.1 waterfall.

One test per acceptance criterion (ENG-126): a tier-1 ``crm_import`` claim against the resolved
entity (never minting ids); the ``account.crm_relationship_status`` "already a customer" flag; CRM
claims stamped **tenant-private** and isolated from another tenant while public claims stay shared;
swapping the ``CRMConnector`` (Salesforce → HubSpot double) yields the same claim contract; feeding
observations to M2 so two messy CRM names resolve to the *same* entity with no duplicate minted; and
existing customers exposed as lookalike seeds.

Every CRM record comes from a connector **double** (no live CRM, no credential) — the seam is what's
proven, not a vendor integration. CRM resolves pass the run ``workspace_id`` because ``crm_import``
claims classify tenant-private (decision #6) — the engine fails loud without one.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

import pytest

from clue_core import (
    AccountEntity,
    Entity,
    EntityId,
    EntityType,
    ExtractionMethod,
    FieldDef,
    IdentityBinding,
    PassKind,
    ResearchMode,
    Resolver,
    ReuseScope,
    UseClass,
    new_entity_id,
    new_run_id,
)
from clue_research.claimstore import (
    ALL_WORKSPACES,
    WorkspaceScope,
    claims_for,
    current_value,
)
from clue_research.identity import insert_account_entity
from clue_research.resolvers import (
    CRM_RELATIONSHIP_FIELD,
    CrmAccountRecord,
    CrmContactRecord,
    CrmRelationship,
    CrmResolver,
    lookalike_seeds,
    register_crm_resolver,
    resolve_crm_seeds,
    resolved_field,
)
from clue_research.resolvers.base import DeterministicResolver  # the public tier-1 enrichment seam
from clue_research.sources import StopReason, bind_resolver, resolve_field
from tests._workspace import seed_workspace

from .conftest import CountingBackend, rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_db")

_MODE = ResearchMode.ACCOUNT_PROFILING
_TENANT = "tenant-acme-client"


# --- doubles ----------------------------------------------------------------


class _Accounts:
    """An ``AccountLookup`` double: one resolved account, keyed by any id handed in."""

    def __init__(self, account: AccountEntity) -> None:
        self._account = account

    def key_for(self, entity_id: EntityId) -> AccountEntity | None:
        return self._account


class _Connector:
    """A ``CRMConnector`` double returning preset records (the vendor mapping is irrelevant here —
    the record is already vendor-agnostic, which is exactly the swap-invariant contract)."""

    def __init__(
        self,
        *,
        account: CrmAccountRecord | None = None,
        contact: CrmContactRecord | None = None,
        accounts: Iterable[CrmAccountRecord] = (),
    ) -> None:
        self._account = account
        self._contact = contact
        self._accounts = list(accounts)

    def fetch_account(self, account: AccountEntity) -> CrmAccountRecord | None:
        return self._account

    def fetch_contact(self, entity_id: EntityId) -> CrmContactRecord | None:
        return self._contact

    def iter_accounts(self) -> Iterable[CrmAccountRecord]:
        return list(self._accounts)


def _account_entity(domain: str = "acme.com") -> AccountEntity:
    return AccountEntity(id=new_entity_id(), canonical_name="Acme Corp", primary_domain=domain)


def _field(field_key: str, *, value_type: str = "str") -> FieldDef:
    return FieldDef(
        field_key=field_key, value_type=value_type, tier_plan=("crm",), pass_kind=PassKind.SCORING
    )


# --- AC: tier-1 crm_import + the "already a customer" relationship flag ----------------------


def test_crm_resolver_conforms_to_protocol_at_tier_1() -> None:
    resolver = CrmResolver(_Connector(), _Accounts(_account_entity()))
    assert isinstance(resolver, Resolver)  # structural: has tier + resolve
    assert resolver.tier == 1


def test_crm_relationship_status_flags_existing_customer() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = _account_entity()
            record = CrmAccountRecord(
                record_ref="https://crm.example/acct/42",
                name="Acme Corp",
                domain="acme.com",
                relationship=CrmRelationship.CUSTOMER,
            )
            register_crm_resolver(_Connector(account=record), accounts=_Accounts(account))
            entity = account.as_entity()
            result = await resolve_field(
                conn,
                entity,
                _field(CRM_RELATIONSHIP_FIELD),
                mode=_MODE,
                run_id=new_run_id(),
                workspace_id=_TENANT,
            )
            assert result.stop_reason is StopReason.CONFIDENT_HIT
            (claim,) = await claims_for(
                conn, entity.entity_id, CRM_RELATIONSHIP_FIELD, scope=ALL_WORKSPACES
            )
            assert claim.value_json == "customer"  # the already-a-customer flag, at Pass A
            assert claim.source_tier == 1
            assert claim.extraction_method is ExtractionMethod.CRM_IMPORT
            assert claim.source_key == "crm"  # engine-stamped
            assert claim.source_url == "https://crm.example/acct/42"  # the CRM record ref
            assert claim.evidence_span and claim.evidence_span.strip()

    run_async(_run())


def test_crm_maps_an_account_field_from_the_record() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = _account_entity()
            record = CrmAccountRecord(
                record_ref="crm://acct/42",
                name="Acme Corp",
                domain="acme.com",
                fields={"core.employee_count": 1200},
            )
            register_crm_resolver(_Connector(account=record), accounts=_Accounts(account))
            entity = account.as_entity()
            await resolve_field(
                conn,
                entity,
                _field("core.employee_count", value_type="int"),
                mode=_MODE,
                run_id=new_run_id(),
                workspace_id=_TENANT,
            )
            (claim,) = await claims_for(
                conn, entity.entity_id, "core.employee_count", scope=ALL_WORKSPACES
            )
            assert (
                claim.value_json == 1200 and claim.extraction_method is ExtractionMethod.CRM_IMPORT
            )

    run_async(_run())


def test_crm_miss_writes_nothing() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = _account_entity()
            register_crm_resolver(
                _Connector(account=None), accounts=_Accounts(account)
            )  # not in CRM
            entity = account.as_entity()
            result = await resolve_field(
                conn,
                entity,
                _field(CRM_RELATIONSHIP_FIELD),
                mode=_MODE,
                run_id=new_run_id(),
                workspace_id=_TENANT,
            )
            assert result.claim_refs == ()
            written = await claims_for(
                conn, entity.entity_id, CRM_RELATIONSHIP_FIELD, scope=ALL_WORKSPACES
            )
            assert written == []  # never fabricated

    run_async(_run())


# --- AC: tenant isolation — CRM claims private; a second tenant cannot see them ---------------


def test_crm_claims_are_tenant_private_and_excluded_from_cross_tenant_reuse() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = _account_entity()
            record = CrmAccountRecord(
                record_ref="crm://acct/42",
                name="Acme Corp",
                domain="acme.com",
                relationship=CrmRelationship.OPEN_OPPORTUNITY,
            )
            register_crm_resolver(_Connector(account=record), accounts=_Accounts(account))
            entity = account.as_entity()
            await resolve_field(
                conn,
                entity,
                _field(CRM_RELATIONSHIP_FIELD),
                mode=_MODE,
                run_id=new_run_id(),
                workspace_id=_TENANT,
            )
            # The owning tenant sees its CRM claim, stamped tenant-private + bound to the tenant.
            owner = WorkspaceScope.for_workspace(_TENANT)
            cv = await current_value(conn, entity.entity_id, CRM_RELATIONSHIP_FIELD, scope=owner)
            assert cv is not None and cv.value_json == "open_opportunity"
            (claim,) = await claims_for(conn, entity.entity_id, CRM_RELATIONSHIP_FIELD, scope=owner)
            assert claim.reuse_scope is ReuseScope.TENANT_PRIVATE
            assert claim.workspace_id == _TENANT
            # Another tenant touching the SAME public entity sees NONE of the first tenant's CRM.
            other = WorkspaceScope.for_workspace("tenant-other")
            assert (
                await current_value(conn, entity.entity_id, CRM_RELATIONSHIP_FIELD, scope=other)
                is None
            )
            assert list(await claims_for(conn, entity.entity_id, scope=other)) == []
            assert (
                list(await claims_for(conn, entity.entity_id, scope=WorkspaceScope.public_only()))
                == []
            )

    run_async(_run())


def test_public_footprint_claim_stays_reusable_across_tenants() -> None:
    # The other half of isolation: a public-footprint (non-CRM) claim about the same entity IS
    # visible to every tenant — the amortization the CRM boundary must not break.
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = _account_entity()
            backend = CountingBackend(
                [
                    resolved_field(
                        "core.employee_count", 900, source_url="https://api.x/1", confidence=0.9
                    )
                ]
            )
            bind_resolver("apollo", DeterministicResolver(backend, cost_cents=Decimal(3)))
            entity = account.as_entity()
            await resolve_field(
                conn,
                entity,
                FieldDef(
                    field_key="core.employee_count",
                    value_type="int",
                    tier_plan=("apollo",),
                    pass_kind=PassKind.SCORING,
                ),
                mode=_MODE,
                run_id=new_run_id(),
                workspace_id=_TENANT,  # supplied, but a public claim drops it
            )
            (claim,) = await claims_for(
                conn, entity.entity_id, "core.employee_count", scope=ALL_WORKSPACES
            )
            assert claim.reuse_scope is ReuseScope.PUBLIC_FOOTPRINT and claim.workspace_id is None
            for scope in (WorkspaceScope.for_workspace("t1"), WorkspaceScope.for_workspace("t2")):
                cv = await current_value(conn, entity.entity_id, "core.employee_count", scope=scope)
                assert cv is not None and cv.value_json == 900

    run_async(_run())


def test_same_entity_public_visible_both_tenants_private_only_owner() -> None:
    # The full isolation boundary on ONE entity: resolve it with BOTH a CRM field (→ tenant_private)
    # and a public field (→ public_footprint), then assert tenant-A sees both, tenant-B sees only
    # the public one, and public_only scope shows the public claim but not the CRM one.
    async def _run() -> None:
        async with rollback_conn() as conn:
            account = _account_entity()
            entity = account.as_entity()
            register_crm_resolver(
                _Connector(
                    account=CrmAccountRecord(
                        record_ref="crm://acct/42",
                        name="Acme Corp",
                        domain="acme.com",
                        relationship=CrmRelationship.CUSTOMER,
                    )
                ),
                accounts=_Accounts(account),
            )
            bind_resolver(
                "apollo",
                DeterministicResolver(
                    CountingBackend(
                        [
                            resolved_field(
                                "core.employee_count",
                                900,
                                source_url="https://api.x/1",
                                confidence=0.9,
                            )
                        ]
                    ),
                    cost_cents=Decimal(3),
                ),
            )
            run_id = new_run_id()
            await resolve_field(
                conn,
                entity,
                _field(CRM_RELATIONSHIP_FIELD),
                mode=_MODE,
                run_id=run_id,
                workspace_id=_TENANT,
            )
            await resolve_field(
                conn,
                entity,
                FieldDef(
                    field_key="core.employee_count",
                    value_type="int",
                    tier_plan=("apollo",),
                    pass_kind=PassKind.SCORING,
                ),
                mode=_MODE,
                run_id=run_id,
                workspace_id=_TENANT,
            )

            owner = WorkspaceScope.for_workspace(_TENANT)
            other = WorkspaceScope.for_workspace("tenant-other")
            public = WorkspaceScope.public_only()
            # Owner sees BOTH the private CRM relationship and the public headcount.
            assert (
                await current_value(conn, entity.entity_id, CRM_RELATIONSHIP_FIELD, scope=owner)
            ) is not None
            assert (
                await current_value(conn, entity.entity_id, "core.employee_count", scope=owner)
            ) is not None
            # Another tenant sees ONLY the public headcount — never the CRM relationship.
            assert (
                await current_value(conn, entity.entity_id, CRM_RELATIONSHIP_FIELD, scope=other)
            ) is None
            assert (
                await current_value(conn, entity.entity_id, "core.employee_count", scope=other)
            ) is not None
            # public_only: the headcount is shared; the CRM relationship is not.
            assert (
                await current_value(conn, entity.entity_id, CRM_RELATIONSHIP_FIELD, scope=public)
            ) is None
            assert (
                await current_value(conn, entity.entity_id, "core.employee_count", scope=public)
            ) is not None

    run_async(_run())


@pytest.mark.parametrize(
    ("raw", "produces_claim"),
    [(None, False), ("", False), ([], False), (0, True), (1200, True), ("ok", True)],
)
def test_crm_account_field_empty_vs_falsy_edge_cases(raw: object, produces_claim: bool) -> None:
    # missing/empty (None / "" / []) → miss, never fabricated; but a falsy-but-VALID value (0) is a
    # real value and must NOT be swallowed. Driven straight through the resolver (sync, no DB).
    record = CrmAccountRecord(
        record_ref="crm://acct/42",
        name="Acme Corp",
        domain="acme.com",
        fields={"core.employee_count": raw},  # type: ignore[dict-item]
    )
    account = _account_entity()
    resolver = CrmResolver(_Connector(account=record), _Accounts(account))
    claims = resolver.resolve(
        account.as_entity(),
        FieldDef(
            field_key="core.employee_count",
            value_type="int",
            tier_plan=("crm",),
            pass_kind=PassKind.SCORING,
        ),
    )
    assert (len(claims) == 1) is produces_claim
    if produces_claim:
        assert claims[0].value_json == raw


# --- AC: swapping the CRMConnector yields the same claim contract ---------------------------------


def test_swapping_connector_produces_the_same_claim_contract() -> None:
    async def _run() -> None:
        record = CrmAccountRecord(
            record_ref="crm://acct/42",
            name="Acme Corp",
            domain="acme.com",
            relationship=CrmRelationship.CUSTOMER,
        )

        # Two different "vendors" (Salesforce / HubSpot) both normalize to the SAME vendor-agnostic
        # record — so the resolver, oblivious to which is wired, emits the same claim.
        class _Salesforce(_Connector):
            pass

        class _HubSpot(_Connector):
            pass

        values: list[object] = []
        for connector_cls in (_Salesforce, _HubSpot):
            async with rollback_conn() as conn:
                account = _account_entity()
                register_crm_resolver(connector_cls(account=record), accounts=_Accounts(account))
                entity = account.as_entity()
                await resolve_field(
                    conn,
                    entity,
                    _field(CRM_RELATIONSHIP_FIELD),
                    mode=_MODE,
                    run_id=new_run_id(),
                    workspace_id=_TENANT,
                )
                (claim,) = await claims_for(
                    conn, entity.entity_id, CRM_RELATIONSHIP_FIELD, scope=ALL_WORKSPACES
                )
                values.append(
                    (claim.value_json, claim.source_tier, claim.extraction_method, claim.source_key)
                )
        assert values[0] == values[1]  # identical claim contract — the vendor never leaked

    run_async(_run())


# --- AC: feeds observations to M2; two messy names → same entity; no dup minted ---------------


def test_crm_seeds_feed_m2_without_minting_duplicate_entities() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            # One real account already exists; the CRM holds two messy rows for it (same domain).
            await seed_workspace(conn, _TENANT)
            resolved_id = await insert_account_entity(
                conn,
                canonical_name="Acme Corporation",
                primary_domain="acme.com",
                workspace_id=_TENANT,
            )
            before = await _account_count(conn)
            connector = _Connector(
                accounts=[
                    CrmAccountRecord(
                        record_ref="crm://1",
                        name="Acme Inc",
                        domain="acme.com",
                        relationship=CrmRelationship.CUSTOMER,
                    ),
                    CrmAccountRecord(
                        record_ref="crm://2",
                        name="ACME CORP.",
                        domain="acme.com",
                        relationship=CrmRelationship.CUSTOMER,
                    ),
                ]
            )
            seeds = await resolve_crm_seeds(conn, connector, workspace_id=_TENANT)
            assert len(seeds) == 2
            # Both messy names deterministically resolve (by domain) to the SAME existing entity.
            assert seeds[0].entity_id == resolved_id
            assert seeds[1].entity_id == resolved_id
            # No new entity was minted — M2 dedup honored (the resolver never mints ids).
            assert await _account_count(conn) == before

    run_async(_run())


def test_lookalike_seeds_exposes_only_resolved_customers() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await seed_workspace(conn, _TENANT)
            customer_id = await insert_account_entity(
                conn,
                canonical_name="Acme Corporation",
                primary_domain="acme.com",
                workspace_id=_TENANT,
            )
            await insert_account_entity(
                conn, canonical_name="Globex", primary_domain="globex.com", workspace_id=_TENANT
            )
            connector = _Connector(
                accounts=[
                    CrmAccountRecord(
                        record_ref="crm://1",
                        name="Acme",
                        domain="acme.com",
                        relationship=CrmRelationship.CUSTOMER,
                    ),
                    CrmAccountRecord(
                        record_ref="crm://2",
                        name="Globex",
                        domain="globex.com",
                        relationship=CrmRelationship.OPEN_OPPORTUNITY,  # not a customer
                    ),
                ]
            )
            seeds = await resolve_crm_seeds(conn, connector, workspace_id=_TENANT)
            assert lookalike_seeds(seeds) == [customer_id]  # only the existing customer is a seed

    run_async(_run())


def test_crm_seed_for_an_unresolved_record_is_none_and_mints_nothing() -> None:
    # A CRM row that does NOT resolve to an existing entity (no strong-key match) yields
    # entity_id=None — M4.5 never mints (M6's import flow disposes it), it is not a lookalike seed,
    # and no entity is created. (A resolved customer alongside it: only the resolved row seeds.)
    async def _run() -> None:
        async with rollback_conn() as conn:
            await seed_workspace(conn, _TENANT)
            customer_id = await insert_account_entity(
                conn,
                canonical_name="Acme Corporation",
                primary_domain="acme.com",
                workspace_id=_TENANT,
            )
            before = await _account_count(conn)
            connector = _Connector(
                accounts=[
                    CrmAccountRecord(
                        record_ref="crm://1",
                        name="Acme",
                        domain="acme.com",
                        relationship=CrmRelationship.CUSTOMER,
                    ),
                    CrmAccountRecord(
                        record_ref="crm://2",
                        name="Totally Unknown Co",
                        domain="unknown-co-xyz.example",  # no entity has this strong key
                        relationship=CrmRelationship.CUSTOMER,
                    ),
                ]
            )
            seeds = await resolve_crm_seeds(conn, connector, workspace_id=_TENANT)
            assert seeds[0].entity_id == customer_id  # the strong-key hit resolved
            assert (
                seeds[1].entity_id is None
            )  # the unknown row did NOT resolve (and was not minted)
            assert lookalike_seeds(seeds) == [customer_id]  # only the resolved customer is a seed
            assert await _account_count(conn) == before  # nothing minted

    run_async(_run())


# --- the contact path: crm_import contact claim → engine stamps STRONG + tenant-private -----------


def test_crm_contact_claim_is_strong_bound_and_tenant_private() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            contact = CrmContactRecord(
                record_ref="crm://contact/7",
                fields={"contact.facet.recent_post": "spoke at re:Invent"},
                use_class=UseClass.PROFESSIONAL_PUBLIC,
            )
            register_crm_resolver(
                _Connector(contact=contact), accounts=_Accounts(_account_entity())
            )
            entity = Entity(entity_id=new_entity_id(), entity_type=EntityType.CONTACT)
            field = FieldDef(
                field_key="contact.facet.recent_post",
                value_type="str",
                tier_plan=("crm",),
                pass_kind=PassKind.DEEP,
            )
            await resolve_field(
                conn,
                entity,
                field,
                mode=ResearchMode.CONTACT_PROFILING,
                run_id=new_run_id(),
                workspace_id=_TENANT,
            )
            (claim,) = await claims_for(
                conn, entity.entity_id, "contact.facet.recent_post", scope=ALL_WORKSPACES
            )
            assert claim.entity_type is EntityType.CONTACT
            assert (
                claim.identity_binding is IdentityBinding.STRONG
            )  # crm manifest, not the placeholder
            assert claim.use_class is UseClass.PROFESSIONAL_PUBLIC  # the connector classified it
            assert claim.reuse_scope is ReuseScope.TENANT_PRIVATE and claim.workspace_id == _TENANT

    run_async(_run())


async def _account_count(conn: object) -> int:
    from sqlalchemy import text

    result = await conn.execute(text("SELECT count(*) FROM account_entity"))  # type: ignore[attr-defined]
    return int(result.scalar_one())
