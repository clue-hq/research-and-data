"""The CRM import resolver — the client's own data as tier-1 grounding (M4.5 / ENG-126).

Substrate §4 calls the CRM out specifically: pulling the client's existing account/contact records
in as **tier-1 claims** both *grounds* research and lets the platform detect "already a customer /
already in pipeline" early — cheap, highest-trust, and something pure-web aggregators (Clay et al.)
miss. The CRM is *just a tier-1 resolver* (conventions §2): nothing downstream knows the vendor, so
swapping Salesforce → HubSpot is a :class:`CRMConnector` config change, never a caller edit.

Two surfaces share one connector seam and one normalized record shape:

* :class:`CrmResolver` — the ``Resolver`` (tier-1, ``extraction_method='crm_import'``) the M4.1
  waterfall dispatches through. Given an *already-resolved* entity, it pulls that entity's CRM
  record and maps the requested field — including :data:`CRM_RELATIONSHIP_FIELD` (the "already a
  customer" flag) — into a typed claim. It writes claims **only** against the resolved ``entity_id``
  it was handed; it never mints ids (identity is M2's). The waterfall stamps the claims
  ``tenant_private`` (``crm_import`` classifies private — decision #6), so CRM stays isolated.
* :func:`resolve_crm_seeds` — the bulk **observation-feeding** surface: it pulls the client's CRM
  accounts, feeds each as an :class:`~clue_research.identity.Observation` to the M2 identity
  service, and returns the resolved seeds (two messy CRM names with the same strong key → the *same*
  entity — M2 dedup honored, no duplicate entity minted). :func:`lookalike_seeds` exposes the
  existing-customer entities as the strongest lookalike seeds for mode-M1 discovery (the *expansion*
  is M6 — M4.5 only supplies the resolved seeds).

The connector reads tenant-scoped credentials via the manifest ``auth_ref`` (never a secret in code
or fixtures); the record shape is vendor-agnostic so the vendor mapping lives inside the connector.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.core import (
    AccountEntity,
    Claim,
    CostCents,
    Entity,
    EntityId,
    EntityType,
    ExtractionMethod,
    FieldDef,
    IdentityBinding,
    ResearchMode,
    ResolverError,
    UseClass,
    account_claim,
    contact_claim,
    new_run_id,
    to_value_json,
)
from clue_research.identity import (
    DEFAULT_DISPOSITION_POLICY,
    DEFAULT_EMBEDDER,
    DEFAULT_RESOLUTION_POLICY,
    DispositionPolicy,
    Embedder,
    Observation,
    ResolutionPolicy,
    ResolutionResult,
    resolve_many,
)
from clue_research.resolvers.live import AccountLookup
from clue_research.sources import SEED_MANIFESTS, bind_resolver

SOURCE_KEY = "crm"
AUTH_REF = "CLUE_CRM_API_KEY"
# The "already a customer / in pipeline" field the resolver emits so Pass A (M6) can flag existing
# relationships cheaply (substrate §4; Doc B §4). Registered in the core pack (M1.3); its closed
# value set mirrors :class:`CrmRelationship` (the drift is guarded by a test).
CRM_RELATIONSHIP_FIELD = "account.crm_relationship_status"


class CrmRelationship(StrEnum):
    """The client's relationship to an account, as the CRM asserts it (substrate §4 / Doc B §4).

    A closed taxonomy (conventions §3): the connector maps each vendor's stage/type vocabulary into
    one of these, so ``account.crm_relationship_status`` carries a uniform value regardless of CRM.
    """

    CUSTOMER = "customer"
    OPEN_OPPORTUNITY = "open_opportunity"
    PROSPECT = "prospect"
    FORMER_CUSTOMER = "former_customer"
    NONE = "none"


class CrmAccountRecord(BaseModel):
    """One client-CRM **account** record, normalized to a vendor-agnostic shape (M4.5).

    The vendor mapping (Salesforce ``NumberOfEmployees`` → ``core.employee_count``, ``StageName`` →
    a :class:`CrmRelationship`, …) lives inside the :class:`CRMConnector`, so a connector swap
    yields the *same* record — and the same claims. ``fields`` maps our registered ``field_key``s
    to the CRM's value for that field; the resolver reads the requested field straight out of it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_ref: (
        str  # the CRM record's URL/id — the claim ``source_url`` (the record, not the vendor)
    )
    name: str  # the account name as the CRM holds it (free-text; M2 resolves it to an entity)
    domain: str | None = None  # the strong key M2 dedups on
    registry_ids: dict[str, str] = {}  # NPI/DUNS/CIK/LEI as the CRM holds them (M2 strong keys)
    relationship: CrmRelationship = CrmRelationship.NONE
    fields: dict[str, JsonValue] = {}  # our field_key -> the CRM's value (e.g. core.employee_count)


class CrmContactRecord(BaseModel):
    """One client-CRM **contact** record, normalized (M4.5). Contacts resolve under accounts (M2);
    the connector keys its contacts by the resolved ``entity_id`` it ingested. ``use_class`` is the
    governance class the connector assigns the contact's personal data (Doc D §2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_ref: str
    fields: dict[str, JsonValue] = {}  # our contact field_key -> the CRM's value
    use_class: UseClass = UseClass.PROFESSIONAL_PUBLIC


class CRMConnector:
    """The pluggable CRM seam (Salesforce / HubSpot / … are config, not code).

    A connector turns the client's CRM into the vendor-agnostic records above. The resolver path
    uses :meth:`fetch_account` / :meth:`fetch_contact` (one resolved entity → its record); the seed
    uses :meth:`iter_accounts` (the whole book, fed to M2 for resolution). This is a structural
    ``Protocol`` (duck-typed): a Salesforce client and a HubSpot client both satisfy it, and nothing
    downstream knows which one is wired (conventions §2). It is **read-only** — CRM write-back is
    forbidden (Postgres is the only write path, conventions §6).
    """

    def fetch_account(self, account: AccountEntity) -> CrmAccountRecord | None:
        """The CRM record for an already-resolved account (by its domain/name/registry ids), or
        ``None`` for a hard miss (the account isn't in the CRM)."""
        raise NotImplementedError

    def fetch_contact(self, entity_id: EntityId) -> CrmContactRecord | None:
        """The CRM record for an already-resolved contact, or ``None`` (a hard miss)."""
        raise NotImplementedError

    def iter_accounts(self) -> Iterable[CrmAccountRecord]:
        """Every CRM account record (the seed/observation feed). Default: none (override in a real
        connector). The resolver path does not call this."""
        return ()


# Placeholder research mode per entity kind — the waterfall overwrites research_mode with the run's
# mode in ``_finalize`` (the resolver cannot know the campaign's mode), so this only has to be
# coherent with the claim model (mirrors ``resolvers.base._PLACEHOLDER_MODE``).
_PLACEHOLDER_MODE: dict[EntityType, ResearchMode] = {
    EntityType.ACCOUNT: ResearchMode.ACCOUNT_PROFILING,
    EntityType.CONTACT: ResearchMode.CONTACT_PROFILING,
}


def _account_value(record: CrmAccountRecord, field_key: str) -> tuple[JsonValue, str] | None:
    """The (value, evidence_span) for ``field_key`` from an account record, or ``None`` for a hard
    miss. ``CRM_RELATIONSHIP_FIELD`` is the derived relationship flag; any other field is a direct
    read of the connector-normalized ``fields`` map (missing/empty → miss, never fabricated)."""
    if field_key == CRM_RELATIONSHIP_FIELD:
        rel = record.relationship.value
        return rel, f"crm:relationship_status={rel}"
    raw = record.fields.get(field_key)
    if raw is None or raw == "" or raw == []:
        return None
    return raw, f"crm:{field_key}={raw!r}"


class CrmResolver:
    """A tier-1 ``Resolver`` (M0.2) over the client CRM: the resolved entity's CRM record → claims.

    ``extraction_method='crm_import'`` and ``source_tier=1`` — the client's own data is the highest
    trust. It writes claims **only** against the ``entity_id`` it is handed (the M2-resolved
    entity), never minting an id. The per-call ``cost_cents`` (≈0 — CRM is cheap) goes to the first
    claim, exactly as the M4.4 deterministic resolvers do; the waterfall sums per-claim cost. A
    contact claim is built with a placeholder ``WEAK`` binding the engine overwrites with the crm
    manifest's authoritative ``STRONG`` (a CRM record is a strong, client-asserted binding); the
    waterfall stamps the claims ``tenant_private`` (decision #6 — CRM data is tenant-isolated).
    """

    tier: int = 1

    def __init__(
        self,
        connector: CRMConnector,
        accounts: AccountLookup | None = None,
        *,
        cost_cents: CostCents = Decimal(0),
    ) -> None:
        self._connector = connector
        self._accounts = accounts
        self._cost_cents = cost_cents

    def resolve(self, entity: Entity, field: FieldDef) -> list[Claim]:
        if entity.entity_type is EntityType.ACCOUNT:
            return self._resolve_account(entity, field)
        return self._resolve_contact(entity, field)

    def _resolve_account(self, entity: Entity, field: FieldDef) -> list[Claim]:
        if self._accounts is None:
            # The orchestrator (M6/M7) supplies the AccountLookup; absence is a wiring error, not a
            # silent miss (mirrors the M4.4 live backend contract).
            raise ResolverError(
                f"{SOURCE_KEY!r} CRM resolver requires an AccountLookup (wired by the M6/M7 "
                "orchestrator) to key the CRM record by the resolved account"
            )
        account = self._accounts.key_for(entity.entity_id)
        if account is None:
            return []  # the account isn't loaded → hard miss
        record = self._connector.fetch_account(account)
        if record is None:
            return []  # not in the CRM → a correct empty (never fabricated)
        found = _account_value(record, field.field_key)
        if found is None:
            return []
        value, span = found
        return [
            account_claim(
                entity_id=entity.entity_id,
                field_key=field.field_key,
                value_json=to_value_json(value),
                source_tier=1,
                extraction_method=ExtractionMethod.CRM_IMPORT,
                confidence=1.0,  # the client's own assertion is maximally trusted at the source
                run_id=new_run_id(),
                research_mode=_PLACEHOLDER_MODE[EntityType.ACCOUNT],
                source_url=record.record_ref,
                evidence_span=span,
                cost_cents=self._cost_cents,
            )
        ]

    def _resolve_contact(self, entity: Entity, field: FieldDef) -> list[Claim]:
        record = self._connector.fetch_contact(entity.entity_id)
        if record is None:
            return []
        value = record.fields.get(field.field_key)
        if value is None or value == "" or value == []:
            return []
        return [
            contact_claim(
                entity_id=entity.entity_id,
                field_key=field.field_key,
                value_json=to_value_json(value),
                source_tier=1,
                extraction_method=ExtractionMethod.CRM_IMPORT,
                confidence=1.0,
                run_id=new_run_id(),
                research_mode=_PLACEHOLDER_MODE[EntityType.CONTACT],
                # WEAK placeholder — the engine overwrites it with the crm manifest's STRONG.
                identity_binding=IdentityBinding.WEAK,
                use_class=record.use_class,
                source_url=record.record_ref,
                evidence_span=f"crm:{field.field_key}={value!r}",
                cost_cents=self._cost_cents,
            )
        ]


# --- the observation-feeding / lookalike-seed surface (feeds M2; mints no ids) --------------------


class CrmSeed(BaseModel):
    """A client-CRM account resolved against the M2 identity service (M4.5).

    ``entity_id`` is the resolved entity **only** when the match clears the auto-merge band (a
    deterministic strong-key hit) — otherwise it is ``None`` (a mid-band/unresolved row M6's import
    flow disposes; M4.5 never mints an entity). Two messy CRM names sharing a strong key both
    resolve to the same ``entity_id`` (M2 dedup honored), so no duplicate entity is created.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    record: CrmAccountRecord
    resolution: ResolutionResult
    entity_id: EntityId | None
    relationship: CrmRelationship


async def resolve_crm_seeds(
    conn: AsyncConnection,
    connector: CRMConnector,
    *,
    policy: ResolutionPolicy = DEFAULT_RESOLUTION_POLICY,
    disposition: DispositionPolicy = DEFAULT_DISPOSITION_POLICY,
    embedder: Embedder = DEFAULT_EMBEDDER,
) -> list[CrmSeed]:
    """Feed every CRM account as an :class:`~clue_research.identity.Observation` to M2 and return
    the resolved seeds — the bulk identity surface (it never mints ids: the disposition/creation of
    a new entity is M2.3/M6). A row resolves to an existing entity only when its top candidate
    clears the auto-merge band (``disposition.auto_merge_threshold``) — a deterministic strong-key
    hit; anything softer is left ``entity_id=None`` for M6's import flow to dispose. Two CRM rows
    with the same strong key (domain/registry id) resolve to the *same* entity, so no dup."""
    records = list(connector.iter_accounts())
    observations = [
        Observation(
            name=r.name,
            entity_type=EntityType.ACCOUNT,
            domain=r.domain,
            registry_ids=r.registry_ids,
        )
        for r in records
    ]
    results = await resolve_many(conn, observations, policy=policy, embedder=embedder)
    seeds: list[CrmSeed] = []
    for record, result in zip(records, results, strict=True):
        top = result.top
        entity_id = (
            top.entity_id
            if top is not None and top.score >= disposition.auto_merge_threshold
            else None
        )
        seeds.append(
            CrmSeed(
                record=record,
                resolution=result,
                entity_id=entity_id,
                relationship=record.relationship,
            )
        )
    return seeds


def lookalike_seeds(seeds: Iterable[CrmSeed]) -> list[EntityId]:
    """The resolved **existing-customer** entities — the strongest lookalike seeds for mode-M1
    discovery (staged-flow §3; Doc B §4). Only resolved customers (an ``entity_id`` and a
    ``CUSTOMER`` relationship) qualify; the expansion itself is M6 (M4.5 supplies the seeds)."""
    return [
        s.entity_id
        for s in seeds
        if s.entity_id is not None and s.relationship is CrmRelationship.CUSTOMER
    ]


def make_resolver(
    connector: CRMConnector,
    *,
    accounts: AccountLookup | None = None,
    cost_cents: CostCents | None = None,
) -> CrmResolver:
    """Construct the CRM resolver; ``cost_cents`` defaults to the seed manifest's per-call cost (the
    single source of truth for a source's price), mirroring ``register_deterministic_resolvers``."""
    cost = cost_cents if cost_cents is not None else _seed_cost()
    return CrmResolver(connector, accounts, cost_cents=cost)


def register_crm_resolver(
    connector: CRMConnector,
    *,
    accounts: AccountLookup | None = None,
    cost_cents: CostCents | None = None,
) -> None:
    """Bind the CRM resolver to its ``source_key`` (``crm``) — the seam the M6/M7 orchestrator calls
    with the tenant's real connector (Salesforce/HubSpot) + the loaded ``AccountLookup``. Idempotent
    (last write wins, so a test/config can swap the connector behind the key)."""
    bind_resolver(SOURCE_KEY, make_resolver(connector, accounts=accounts, cost_cents=cost_cents))


def _seed_cost() -> CostCents:
    """The crm manifest's per-call cost from the in-memory seeds (the single source of truth)."""
    return next(m.cost_cents for m in SEED_MANIFESTS if m.source_key == SOURCE_KEY)
