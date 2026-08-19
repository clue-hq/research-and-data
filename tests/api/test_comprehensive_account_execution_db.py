"""Contract §11-B exit: all 21 account fields reach a settled attempted/satisfied state.

One composed account-research run over the fixed comprehensive profile
(:data:`~clue_api.comprehensive_research_contract.COMPREHENSIVE_ACCOUNT_FIELDS`), driven end to
end on real Postgres through the real launcher (Task B1), the real directive validator (Task B4),
the real R5 runtime/guard/engine, and provider doubles standing in for Exa Deep and Sumble. What it
proves is the *closure* property Slice B exists for: after finalization every one of the 21 rows is
accounted for — satisfied, honestly empty, or reused — and none has silently vanished between the
directive, the launch selection, and the coverage ledger.

The 21 rows settle through four distinct dispositions, and the test names each one:

* **Reused from discovery** — the seven §3.1 rows the Websets discovery vocabulary writes
  (``exa_websets_materialization._base_field_values``, the source of truth this file calls rather
  than restates). A fresh, evidence-backed, conflict-free neutral claim makes them born-complete:
  they are completed *and* carry an ``existing_claim_fresh`` skip, and no provider is asked for
  them.
* **Acquired** — the remaining admitted rows, bought once each through the governed tools.
* **Honestly empty** — a deliberately empty provider double leaves its row in
  ``unresolved_field_keys`` with the result's own reason, never a fabricated value.
* **Derived** — ``core.employee_range`` / ``core.revenue_band`` (§3.1 rows 5 and 8) settle at
  assessment from the governed employee-count / annual-revenue evidence (Task B7).

The coverage axis is the launch selection's paid fields plus all three zero-acquisition rows.
``core.account_name`` is evidence-backed canonical identity truth reused from discovery;
``core.employee_range`` and ``core.revenue_band`` are reused or derived. All 21 therefore appear
in one mechanically closed coverage ledger without authorizing a fake provider call.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.account_entity_research import AssessAccountCoverageInput
from clue_agents.contracts import ModelPolicy
from clue_agents.entity_research_contracts import (
    EntityResearchAgentResult,
    EntityResearchAgentSuspension,
    EntityResearchToolCall,
    canonical_sha256,
)
from clue_agents.entity_research_runtime import (
    ActiveEntityResearchToolExecution,
    EntityResearchAgentFactory,
    EntityResearchAgentRuntime,
)
from clue_api.account_entity_research import (
    AccountResearchAuthorityError,
    AccountResearchExecutionGuard,
    AccountResearchFinalizationEngine,
    AccountResearchStateStore,
    born_complete_account_field_keys,
    read_account_research_execution_completeness,
)
from clue_api.account_entity_research_composition import (
    AccountResearchDefinitionResolver,
    StaticAccountResearchProviderActions,
)
from clue_api.account_field_derivation import (
    DERIVED,
    DERIVED_ACCOUNT_FIELD_SOURCES,
    EXISTING_CLAIM_FRESH,
    employee_range_value,
    revenue_band_value,
)
from clue_api.account_research_fleet import (
    AccountResearchFleetPolicy,
    AccountResearchFleetService,
)
from clue_api.account_research_fleet_launch import (
    AccountResearchFleetLauncher,
    AccountResearchFleetLaunchRequest,
)
from clue_api.comprehensive_research_contract import (
    COMPREHENSIVE_ACCOUNT_FIELD_SOURCES,
    COMPREHENSIVE_ACCOUNT_FIELDS,
)
from clue_api.entity_research_runtime_wiring import DbEntityResearchAgentJournal
from clue_api.entity_research_tools import (
    EntityResearchProviderCausationStore,
    EntityResearchResultIntegrityError,
    EntityResearchResultStore,
    EntityResearchToolRequestStore,
    ExternalResearchResultLineageReader,
    GovernedEntityResearchToolFactory,
    ProviderActionBinding,
    ProviderObservationDisposition,
    ProviderOperationReservation,
    ProviderResearchProjectionDraft,
)
from clue_api.exa_deep_acquisition import (
    ExaDeepAcquisitionCoordinator,
    compile_exa_deep_acquisition_plan,
)
from clue_api.exa_deep_materialization import ExaDeepSnapshotResolverProvider
from clue_api.exa_entity_research_tools import (
    ExaAccountSemanticResearchAction,
    ExaEntityResearchProjectionBuilder,
)
from clue_api.exa_websets_materialization import _base_field_values
from clue_api.trial.account_deep_fixture import seed_insight_health_account_deep_fixture
from clue_core import (
    ClaimProvenanceKind,
    EntityId,
    ExtractionMethod,
    ProjectRunId,
    ResearchMode,
    ResearchQuestion,
    account_claim,
    new_run_id,
    revalidate_with,
)
from clue_core.entity_research import (
    EntityResearchJobAuthorization,
    EntityResearchSelection,
    ResearchClaimDelta,
    ResearchFieldOutcome,
    ResearchFieldResultProjection,
    ResearchFinalizationOutcome,
    ResearchSubjectType,
)
from clue_fleet import (
    DbEntityResearchJobStore,
    EntityResearchExecutionFence,
    FleetTaskKind,
    WorkId,
    acquire_work_lease,
    claim_next_task,
)
from clue_research.adapters.exa_websets import ExaDiscoveryCompanyItem
from clue_research.claimstore import (
    FieldRegistryScope,
    WorkspaceScope,
    current_value,
    current_values,
    get_effective_field,
    insert_claim,
    record_run_lineage,
)
from clue_research.durable.discovery import capture_discovery_artifact
from clue_research.identity import get_account, stamp_reuse
from clue_research.narrative.prose import PROSE_ACCOUNT_FIELDS
from clue_research.resolvers.exa import SOURCE_KEY as EXA_DEEP_SOURCE_KEY
from clue_research.resolvers.exa.deep_contract import (
    EXA_OUTPUT_MAX_FIELDS,
    ExaDeepFieldSpec,
    field_key_from_exa_alias,
)
from clue_storage import FsStorage
from tests.agents.test_entity_research_runtime_r3 import Checkpointers
from tests.api.account_deep_test_support import confirmed_account_research_direction
from tests.api.test_account_deep_fixture_a1 import _pages
from tests.api.test_account_entity_research_fresh_skip_db import _ScriptedModel
from tests.api.test_account_entity_research_r5_db import (
    _FixtureAccountProviders,
    _FixtureLineageReader,
    _Models,
    _NestedConnFactory,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_EXA_WEBSETS_SOURCE_KEY = "exa_websets"
#: §3.1 row 1 — canonical identity truth. It owns no acquisition source and is reused with
#: evidence inside the same 21-field coverage axis.
_IDENTITY_ROW = "core.account_name"
#: The Exa-owned row whose scripted provider response deliberately leaves absent.
_HONEST_EMPTY = "account.operational_pain"
_QUESTION = "Where is administrative work creating avoidable burden?"
#: The retained passage every scripted provider answer restates, so the Exa normalizer's
#: lexical support check selects the citation instead of refusing it as unsupported.
_GROUNDED_PASSAGE = (
    "The Referral Coordinator indexes incoming fax documents and routes patient calls."
)
#: The recorded E1 Exa envelope (documents, costs, provider ids) the scripted transport reuses.
_EXA_RESPONSE = (
    Path(__file__).parents[1] / "fixtures" / "providers" / "exa" / "search" / "deep_response.json"
)
#: The fixture's deep ICP must author the qualitative + structured shapes the launch plans over.
_DEEP_ICP_FIELDS = (
    "account.hiring_velocity_eng",
    "core.primary_tech_stack",
    "account.operational_pain",
    "account.strategic_moves",
    "core.industry",
)


@asynccontextmanager
async def _same_connection(conn: AsyncConnection) -> AsyncIterator[AsyncConnection]:
    async with conn.begin_nested():
        yield conn


def _schema_example(schema: Mapping[str, Any], *, passage: str = _GROUNDED_PASSAGE) -> Any:
    """One deterministic, schema-valid value for a registered field schema.

    Registry-driven on purpose: the profile's rows are strings, objects and arrays of objects with
    closed label enumerations, and a provider double that hand-wrote values per field would drift
    from the registry the claim writer validates against.

    Free-text leaves restate ``passage`` — the retained document the answer is grounded in. That is
    not decoration: the Exa normalizer only *selects* a citation whose retrieved passage lexically
    supports the asserted value, so a value invented independently of its evidence is correctly
    refused as unsupported.
    """

    declared = schema.get("type")
    # The Exa-compiled property schema declares nullable rows as ``["<type>", "null"]``; the
    # registry declares a bare string. Both are the same admitted type.
    kind = (
        next((item for item in declared if item != "null"), None)
        if isinstance(declared, list)
        else declared
    )
    if kind == "object":
        properties = cast(Mapping[str, Mapping[str, Any]], schema.get("properties", {}))
        return {name: _schema_example(value, passage=passage) for name, value in properties.items()}
    if kind == "array":
        return [
            _schema_example(
                cast(Mapping[str, Any], schema.get("items", {"type": "string"})), passage=passage
            )
        ]
    if kind in {"integer", "number"}:
        return 4 if kind == "integer" else 0.4
    if kind == "boolean":
        return True
    options = schema.get("enum")
    if isinstance(options, list) and options:
        return options[0]
    return passage


def _discovery_company() -> ExaDiscoveryCompanyItem:
    """One Websets company item carrying every base field the D4 vocabulary can materialize.

    The discovery-written field set is *read off the production mapping*
    (``exa_websets_materialization._base_field_values``) rather than restated here, so a change to
    the discovery vocabulary moves this test instead of silently diverging from it.
    """

    return ExaDiscoveryCompanyItem(
        provider_item_id="webset-item-comprehensive",
        provider_webset_id="webset-comprehensive",
        provider_source_id="exa-source-comprehensive",
        company_url="https://cascade-gastro.test",
        company_name="Cascade Gastroenterology Associates",
        base_fields={
            "industry": "Specialty gastroenterology practice",
            "employees": 1_200,
            "about": "A multi-site specialty gastroenterology practice serving New England.",
            "location": "Boston, Massachusetts, United States",
            "revenueAnnual": 42_000_000,
            "fundingTotal": 18_000_000,
            "fundingLatestRound": {
                "amount": 9_000_000,
                "name": "Series B",
                "date": "2026-02-01",
            },
        },
        evaluations=(),
        enrichments=(),
        observed_at=datetime.now(UTC) - timedelta(days=2),
    )


def _discovery_values() -> Mapping[str, Any]:
    """The §3.1 profile rows a Websets discovery already answers, with their materialized values."""

    company = _discovery_company()
    return {
        field_key: value
        for field_key, value in _base_field_values(company).items()
        if field_key in set(COMPREHENSIVE_ACCOUNT_FIELDS)
    }


async def _seed_websets_baseline(
    conn: AsyncConnection, *, workspace_id: str, project_id: str, account_id: UUID
) -> Mapping[str, UUID]:
    """Refresh every discovery-written profile row as a fresh, conflict-free Websets claim.

    The account-deep fixture already put a Websets discovery envelope on this account. A second
    observation of the same fact is *corroboration*, not disagreement, so where the account already
    holds a value this seeds that exact value again rather than manufacturing a conflict that would
    make the row un-borrowable for reasons that have nothing to do with §11-B.
    """

    vocabulary = _discovery_values()
    scope = WorkspaceScope.for_workspace(workspace_id)
    subject = EntityId(account_id)
    existing = await current_values(conn, [subject], list(vocabulary), scope=scope)
    discovery_run = new_run_id()
    await record_run_lineage(
        conn,
        run_id=UUID(str(discovery_run)),
        workspace_id=workspace_id,
        kind="discovery",
        project_id=project_id,
    )
    claim_ids: dict[str, UUID] = {}
    for field_key, generated in vocabulary.items():
        current = existing.get((subject, field_key))
        value = generated if current is None else current.value_json
        claim = revalidate_with(
            stamp_reuse(
                account_claim(
                    entity_id=subject,
                    field_key=field_key,
                    value_json=value,
                    source_tier=cast(Any, 2),
                    extraction_method=ExtractionMethod.API,
                    confidence=cast(Any, 0.85),
                    run_id=discovery_run,
                    research_mode=ResearchMode.ACCOUNT_DISCOVERY,
                    source_url="https://cascade-gastro.test/about",
                    evidence_span=f"Discovery evidence for {field_key}: {json.dumps(value)}",
                    observed_at=datetime.now(UTC) - timedelta(days=2),
                ),
                workspace_id=workspace_id,
            ),
            source_key=_EXA_WEBSETS_SOURCE_KEY,
        )
        claim_ids[field_key] = UUID(str(await insert_claim(conn, claim)))
    return claim_ids


@dataclass(frozen=True, slots=True)
class _Fixture:
    """One discovered, comprehensively directed account, ready to launch."""

    workspace_id: str
    project_id: str
    product_id: str
    project_run_id: UUID
    account_id: UUID
    icp_key: str
    icp_version: int
    directive_id: UUID
    research_directive: Any
    discovery_claim_ids: Mapping[str, UUID]


async def _seed_discovered_account(conn: AsyncConnection, storage: FsStorage) -> _Fixture:
    """A discovered account with fresh Websets claims and its confirmed comprehensive directive."""

    seeded = await seed_insight_health_account_deep_fixture(
        conn,
        pages=_pages(),
        storage=storage,
        deep_field_keys=_DEEP_ICP_FIELDS,
    )
    workspace_id = seeded.discovery_fixture.workspace_id
    account_id = UUID(str(seeded.selected_account_id))
    claim_ids = await _seed_websets_baseline(
        conn,
        workspace_id=workspace_id,
        project_id=seeded.discovery_fixture.project_id,
        account_id=account_id,
    )

    _, account_spec = await confirmed_account_research_direction(
        conn,
        workspace_id=workspace_id,
        project_id=seeded.discovery_fixture.project_id,
        product_id=seeded.discovery_fixture.product_id,
        account_id=seeded.selected_account_id,
        icp_key=seeded.deep_icp_key,
        icp_version=seeded.deep_icp_version,
        # Task B4's comprehensive profile: the whole fixed 21-field contract, never a subset.
        field_keys=PROSE_ACCOUNT_FIELDS,
        # Deliberately no ``sumble_people``: this is the Task B5 account-only shape, so the run
        # selects no committee discovery and composes without committee configuration.
        allowed_source_keys=(
            "exa_deep",
            "sumble_jobs",
            "sumble_organizations",
            "sumble_tech_stack",
        ),
        questions=(
            ResearchQuestion(
                question_id="qualitative-burden",
                text=_QUESTION,
                target_field_key="account.operational_pain",
            ),
        ),
    )
    pin = account_spec.research_directive
    assert pin is not None
    # The launcher is action-scoped: it must not require the outer project state machine to be
    # sitting in its DEEP phase (the r6 suite's ruling, mirrored here).
    await conn.execute(
        text("UPDATE project_run SET phase='scoring' WHERE id=:project_run_id"),
        {"project_run_id": seeded.project_run_id},
    )
    return _Fixture(
        workspace_id=workspace_id,
        project_id=seeded.discovery_fixture.project_id,
        product_id=seeded.discovery_fixture.product_id,
        project_run_id=UUID(str(seeded.project_run_id)),
        account_id=account_id,
        icp_key=seeded.deep_icp_key,
        icp_version=seeded.deep_icp_version,
        directive_id=UUID(str(pin.directive_id)),
        research_directive=pin,
        discovery_claim_ids=claim_ids,
    )


class _ScriptedExaTransport:
    """A scripted Exa Deep response shaped by the *compiled bundle's own* output schema.

    No network and no hand-written wire fixture beyond the recorded E1 envelope: for every alias
    the bundler asked for, the transport answers with a deterministic value generated from that
    alias's schema, grounded in the recorded result documents. Aliases in ``empty_field_keys`` are
    left out entirely — the production shape of "asked, nothing found", which the real Exa
    projection builder turns into a ``null`` outcome with ``explicit_null`` verification.
    """

    def __init__(self, *, empty_field_keys: Sequence[str] = ()) -> None:
        self.requests: list[Any] = []
        self._empty = frozenset(empty_field_keys)

    @property
    def requested_field_keys(self) -> frozenset[str]:
        return frozenset(
            str(field_key_from_exa_alias(alias))
            for request in self.requests
            for alias in request.output_schema["properties"]
        )

    def search(self, request: Any) -> Mapping[str, Any]:
        self.requests.append(request)
        payload: dict[str, Any] = json.loads(_EXA_RESPONSE.read_text(encoding="utf-8"))
        payload["costDollars"]["total"] = 0.07
        template = payload["output"]["grounding"][0]
        properties = cast(Mapping[str, Mapping[str, Any]], request.output_schema["properties"])
        content: dict[str, Any] = {}
        grounding: list[Mapping[str, Any]] = []
        for alias, schema in properties.items():
            if str(field_key_from_exa_alias(alias)) in self._empty:
                content[alias] = None
                continue
            content[alias] = _schema_example(schema)
            grounding.append({**template, "field": alias})
        payload["output"]["content"] = content
        payload["output"]["grounding"] = grounding
        return payload


class _TruncatingExaTransport(_ScriptedExaTransport):
    """Exa answers one bundle with corrupted alias keys, exactly as it did live.

    A real comprehensive run returned a 200 whose structured-output keys were truncated copies of
    the requested aliases, so ``validate_exa_deep_exchange`` refused the exchange and the operation
    settled ``spend_outcome_unknown``. Only the first bundle is corrupted, so the batch is the live
    shape: some bundles ready, one dispatched bundle that can never yield a snapshot.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.corrupted_field_keys: frozenset[str] = frozenset()

    def search(self, request: Any) -> Mapping[str, Any]:
        payload = dict(super().search(request))
        if self.corrupted_field_keys:
            return payload
        output = dict(cast(Mapping[str, Any], payload["output"]))
        content = cast(Mapping[str, Any], output["content"])
        output["content"] = {alias[:-4]: value for alias, value in content.items()}
        payload["output"] = output
        self.corrupted_field_keys = frozenset(
            str(field_key_from_exa_alias(alias)) for alias in content
        )
        return payload


class _PartialAccountProviders(_FixtureAccountProviders):
    """The Sumble double, with a deliberate honest empty on the nominated field keys.

    An empty structured answer is a ``null`` field outcome carrying no value, no claim and no
    evidence — the shape :class:`ResearchFieldResultProjection` reserves for "asked, nothing found".
    Everything else about the call (operation reservation, artifacts, lineage, spend) is the shared
    R5 fixture's real plumbing, so the empty row costs exactly what a hit would have cost.
    """

    def __init__(self, *, empty_field_keys: Sequence[str], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._empty = frozenset(empty_field_keys)

    async def _account_fields(
        self,
        *,
        request: Any,
        operation: ProviderOperationReservation,
        snapshot_ref: str,
        provider_request_id: str,
    ) -> tuple[ProviderResearchProjectionDraft, str, str]:
        empty = tuple(key for key in request.field_keys if key in self._empty)
        kept = tuple(key for key in request.field_keys if key not in self._empty)
        answered: tuple[ResearchFieldResultProjection, ...] = ()
        if kept:
            draft, raw_key, normalized_key = await super()._account_fields(
                request=request.model_copy(update={"field_keys": kept}),
                operation=operation,
                snapshot_ref=snapshot_ref,
                provider_request_id=provider_request_id,
            )
            answered = draft.fields
        else:
            raw_key, normalized_key = await self._empty_artifacts(operation)
        return (
            ProviderResearchProjectionDraft(
                operation=operation,
                snapshot_ref=snapshot_ref,
                requested_field_keys=tuple(request.field_keys),
                fields=(
                    *answered,
                    *(
                        ResearchFieldResultProjection(
                            field_key=field_key,
                            outcome=ResearchFieldOutcome.NULL,
                            claim_delta=ResearchClaimDelta.NONE,
                            verification_status="unverified",
                        )
                        for field_key in empty
                    ),
                ),
            ),
            raw_key,
            normalized_key,
        )

    async def _empty_artifacts(self, operation: ProviderOperationReservation) -> tuple[str, str]:
        """The retained bytes of a call that found nothing — an empty answer is still a receipt."""

        payloads: tuple[dict[str, Any], ...] = ({"evidence": {}}, {"fields": {}})
        async with self._conn_factory() as conn:
            keys = [
                await capture_discovery_artifact(
                    conn,
                    self._storage,
                    workspace_id=operation.workspace_id,
                    content=json.dumps(payload, sort_keys=True).encode(),
                    media_type="application/json",
                    source_key=operation.source_key,
                )
                for payload in payloads
            ]
        return keys[0], keys[1]


def _acquisition_plan(
    *, selection: EntityResearchSelection, borrowed: frozenset[str]
) -> list[dict[str, Any]]:
    """The tool calls one governed agent would make, derived from the launched authority.

    The R5 guard states the rules this satisfies: ``research_account_deep`` uses Exa Deep alone and
    its first call must carry *every* Exa-primary field net of the borrowed set; ``enrich_account``
    is independent of Exa Deep; and a field's requested source must be one its launched authority
    already carries. Nothing here is a hardcoded field list — the partition is read off
    ``selection.field_source_authority``.
    """

    authority = {
        item.field_key: tuple(item.source_keys) for item in selection.field_source_authority
    }
    outstanding = [key for key in selection.admitted_field_keys if key not in borrowed]
    structured: dict[str, list[str]] = {}
    exa_primary: list[str] = []
    for field_key in outstanding:
        first = authority[field_key][0]
        if first == EXA_DEEP_SOURCE_KEY:
            exa_primary.append(field_key)
        else:
            structured.setdefault(first, []).append(field_key)
    calls: list[dict[str, Any]] = [
        {
            "name": "enrich_account",
            "args": {
                "field_keys": field_keys,
                "source_keys": [source_key],
                "questions": [_QUESTION],
            },
        }
        for source_key, field_keys in sorted(structured.items())
    ]
    if exa_primary:
        calls.append(
            {
                "name": "research_account_deep",
                "args": {
                    "field_keys": exa_primary,
                    "source_keys": [EXA_DEEP_SOURCE_KEY],
                    "questions": [_QUESTION],
                },
            }
        )
    return calls


async def _launch(
    conn: AsyncConnection,
    *,
    fixture: _Fixture,
    connection: _NestedConnFactory,
) -> Any:
    launcher = AccountResearchFleetLauncher(
        fleets=AccountResearchFleetService(conn_factory=connection),
        conn_factory=connection,
    )
    return await launcher.launch(
        AccountResearchFleetLaunchRequest(
            workspace_id=fixture.workspace_id,
            project_run_id=fixture.project_run_id,
            research_directive_id=fixture.directive_id,
            account_entity_ids=(fixture.account_id,),
            approved_budget_cap_cents=Decimal("300"),
            expected_estimated_cost_cents=Decimal("300"),
            concurrency_limit=4,
            supervisor_policy=AccountResearchFleetPolicy(canary_size=1),
        ),
        actor="human:account-owner",
        source_action_ref="turn:b8-comprehensive-launch",
        source_operation_id=uuid4(),
    )


@dataclass(frozen=True, slots=True)
class _Drive:
    """Everything the assertions need about one finalized comprehensive run."""

    outcome: EntityResearchAgentResult | EntityResearchAgentSuspension | None
    model: _ScriptedModel
    providers: _PartialAccountProviders
    transport: _ScriptedExaTransport
    job_id: UUID
    selection: EntityResearchSelection
    borrowed: frozenset[str]
    authorization: EntityResearchJobAuthorization

    @property
    def result(self) -> EntityResearchAgentResult:
        assert isinstance(self.outcome, EntityResearchAgentResult)
        return self.outcome


async def _drive_comprehensive_run(
    conn: AsyncConnection,
    *,
    fixture: _Fixture,
    tmp_path: Path,
    transport: _ScriptedExaTransport | None = None,
    enrich_action: Any | None = None,
    expect_error: type[BaseException] | None = None,
) -> _Drive:
    """Launch through the real launcher, then run the composed job to finalization."""

    storage = FsStorage(tmp_path / f"b8-artifacts-{uuid4().hex[:8]}")
    connection = _NestedConnFactory(conn)
    projection = await _launch(conn, fixture=fixture, connection=connection)
    launched = projection.jobs[0]
    task = await claim_next_task(
        conn,
        kind=FleetTaskKind.ENTITY_RESEARCH_JOB,
        worker_id="b8-comprehensive",
        project_run_id=ProjectRunId(launched.job_id),
    )
    assert task is not None
    lease = await acquire_work_lease(
        conn,
        work_id=WorkId(launched.job_id),
        worker_id="b8-comprehensive",
        ttl=timedelta(seconds=120),
    )
    assert lease is not None
    fence = EntityResearchExecutionFence(
        task_id=task.task_id,
        worker_id="b8-comprehensive",
        lease_generation=lease.generation,
    )
    jobs = DbEntityResearchJobStore(conn_factory=connection)
    begun = await jobs.begin(launched.job_id, fence=fence)
    assert begun.admitted
    selection = begun.job.authorization.selection
    assert selection.committee_source_keys == ()

    # The borrowed set is read from the engine's own derivation, never re-derived here: the R5
    # guard refuses an Exa call that omits a primary field which is *not* borrowed, so the scripted
    # plan and the guard must agree by construction.
    borrowed = await born_complete_account_field_keys(
        conn,
        workspace_id=fixture.workspace_id,
        account_entity_id=fixture.account_id,
        field_keys=selection.admitted_field_keys,
    )
    plan = _acquisition_plan(selection=selection, borrowed=borrowed)
    field_schemas: dict[str, Mapping[str, Any]] = {}
    for field_key in selection.admitted_field_keys:
        registered = await get_effective_field(
            conn,
            scope=FieldRegistryScope.for_workspace(fixture.workspace_id),
            field_key=field_key,
        )
        assert registered is not None and registered.value_schema is not None
        field_schemas[field_key] = registered.value_schema
    lineage = _FixtureLineageReader()
    # The Sumble side: the shared R5 double's real reservation/artifact/claim plumbing, answering
    # each structured field with a value shaped by that field's registered schema.
    providers = _PartialAccountProviders(
        empty_field_keys=(),
        storage=storage,
        conn_factory=connection,
        contacts=(uuid4(), uuid4()),
        lineage=lineage,
        field_values={
            field_key: _schema_example(schema) for field_key, schema in field_schemas.items()
        },
    )
    # The Exa side: the *production* account action over a scripted transport, so the honest empty
    # and every Exa claim carry real external-research lineage rather than fixture provenance.
    transport = transport or _ScriptedExaTransport(empty_field_keys=(_HONEST_EMPTY,))
    exa_action = ExaAccountSemanticResearchAction(
        workspace_id=fixture.workspace_id,
        project_id=fixture.project_id,
        project_run_id=ProjectRunId(fixture.project_run_id),
        account_id=EntityId(fixture.account_id),
        icp_key=fixture.icp_key,
        icp_version=fixture.icp_version,
        research_directive=fixture.research_directive,
        acquisition=ExaDeepAcquisitionCoordinator(
            transport=transport, storage=storage, conn_factory=connection
        ),
        snapshots=ExaDeepSnapshotResolverProvider(storage=storage, conn_factory=connection),
        projector=ExaEntityResearchProjectionBuilder(storage=storage, conn_factory=connection),
        conn_factory=connection,
        observation_window=f"b8-comprehensive:{launched.job_id}",
        research_intent=(
            "Target-lock research to this canonical account and answer only the admitted "
            "structured fields with inspectable evidence."
        ),
        freshness_policy_ref="freshness:b8-comprehensive-v1",
        freshness_seconds=3_600,
        cost_cents_reserved_per_bundle=Decimal("8"),
        entity_research_job_id=launched.job_id,
    )
    result_store = EntityResearchResultStore(
        storage=storage,
        conn_factory=connection,
        lineage_readers={
            ExternalResearchResultLineageReader.provider_kind: (
                ExternalResearchResultLineageReader(conn_factory=connection)
            ),
            lineage.provider_kind: lineage,
        },
    )
    state = AccountResearchStateStore(conn_factory=connection)
    resolver = AccountResearchDefinitionResolver(
        tools=GovernedEntityResearchToolFactory(
            requests=EntityResearchToolRequestStore(conn_factory=connection, storage=storage),
            causation=EntityResearchProviderCausationStore(conn_factory=connection),
            results=result_store,
        ),
        state=state,
        provider_actions=StaticAccountResearchProviderActions(
            {
                launched.job_id: {
                    "research_account_deep": ProviderActionBinding(action=exa_action, version=1),
                    "enrich_account": ProviderActionBinding(
                        action=enrich_action or providers, version=1
                    ),
                    "discover_buying_committee": ProviderActionBinding(action=providers, version=1),
                }
            }
        ),
        model_policy=ModelPolicy(
            model_id="b8-comprehensive-model",
            timeout_s=30,
            max_retries=0,
            max_output_tokens=4096,
            temperature=0,
        ),
        conn_factory=connection,
    )
    definition = await resolver.resolve(job=begun.job, fence=fence)
    premature = ActiveEntityResearchToolExecution(
        context=definition.context,
        call=EntityResearchToolCall(
            tool_call_id="b8-premature-assessment",
            tool_name="assess_account_coverage",
            tool_version=1,
            tool_input_sha256="a" * 64,
            arguments={"result_refs": [], "assessment_note": "premature no-work close"},
        ),
        journal_event_ref="entity-agent-journal:b8-premature-assessment",
    )
    with pytest.raises(
        AccountResearchAuthorityError,
        match="coverage cannot close before every authorized field/source",
    ):
        await state.assess(
            AssessAccountCoverageInput(result_refs=(), assessment_note="premature no-work close"),
            premature,
        )
    async with connection() as execution_conn:
        incomplete = await read_account_research_execution_completeness(
            execution_conn, authorization=begun.job.authorization
        )
    assert not incomplete.complete
    assert incomplete.outstanding_field_source_pairs
    assert not incomplete.terminal_field_source_pairs
    model = _ScriptedModel(plan=plan)
    journal = DbEntityResearchAgentJournal(conn_factory=connection)
    runtime = EntityResearchAgentRuntime(
        factory=EntityResearchAgentFactory(
            models=_Models(model),
            journal=journal,
            guard=AccountResearchExecutionGuard(conn_factory=connection),
        ),
        checkpointers=Checkpointers(),
        journal=journal,
        finalizer=AccountResearchFinalizationEngine(conn_factory=connection),
    )
    outcome: EntityResearchAgentResult | EntityResearchAgentSuspension | None
    if expect_error is not None:
        with pytest.raises(expect_error):
            await runtime.run(definition=definition)
        outcome = None
    else:
        outcome = await runtime.run(definition=definition)
    return _Drive(
        outcome=outcome,
        model=model,
        providers=providers,
        transport=transport,
        job_id=launched.job_id,
        selection=selection,
        borrowed=borrowed,
        authorization=begun.job.authorization,
    )


async def _coverage_row(conn: AsyncConnection, *, job_id: UUID) -> Mapping[str, Any]:
    row = (
        (
            await conn.execute(
                text(
                    "SELECT completed_field_keys, unresolved_field_keys, unresolved_reasons, "
                    "coverage_json FROM entity_research_account_coverage WHERE job_id=:job_id"
                ),
                {"job_id": job_id},
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def _claim_row(conn: AsyncConnection, claim_id: Any) -> Mapping[str, Any]:
    """The durable provenance columns ``CurrentValue`` does not project."""

    row = (
        (
            await conn.execute(
                text(
                    "SELECT source_key, provenance_kind::text AS provenance_kind, evidence_span "
                    "FROM claim WHERE id=:claim_id"
                ),
                {"claim_id": claim_id},
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def _requested_field_keys(conn: AsyncConnection, *, job_id: UUID) -> frozenset[str]:
    """Every field key this job actually asked a provider for (the durable spend trail)."""

    return frozenset(
        str(value)
        for value in (
            (
                await conn.execute(
                    text(
                        "SELECT DISTINCT unnest(field_keys) FROM entity_research_tool_request "
                        "WHERE job_id=:job_id"
                    ),
                    {"job_id": job_id},
                )
            )
            .scalars()
            .all()
        )
    )


def test_every_comprehensive_account_field_reaches_a_settled_state(tmp_path: Path) -> None:
    """§11-B: no profile row silently vanishes between the directive and the coverage ledger."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_discovered_account(
                conn, FsStorage(tmp_path / "b8-fixture-artifacts")
            )
            drive = await _drive_comprehensive_run(conn, fixture=fixture, tmp_path=tmp_path)
            receipt = drive.result.finalization_receipt
            assert receipt is not None
            assert receipt.verification.all_passed()
            # One row is honestly empty, so the honest close is NEEDS_REVIEW, not COMPLETED.
            assert receipt.proposal.outcome is ResearchFinalizationOutcome.NEEDS_REVIEW

            row = await _coverage_row(conn, job_id=drive.job_id)
            completed = {str(value) for value in row["completed_field_keys"]}
            unresolved = {str(value) for value in row["unresolved_field_keys"]}
            skipped = {str(value) for value in row["coverage_json"]["skipped_field_reasons"]}
            skipped_fields = {reason.rsplit(":", 1)[0] for reason in skipped}

            # (1) Closure. The coverage axis is the exact full 21-field contract. Every row is
            # either completed or unresolved — nothing vanished.
            axis = completed | unresolved
            assert axis == set(COMPREHENSIVE_ACCOUNT_FIELDS)
            assert completed | unresolved | skipped_fields == axis
            assert not completed & unresolved
            assert (
                set(drive.selection.admitted_field_keys)
                | set(DERIVED_ACCOUNT_FIELD_SOURCES)
                | {_IDENTITY_ROW}
                == axis
            )

            requested = await _requested_field_keys(conn, job_id=drive.job_id)
            scope = WorkspaceScope.for_workspace(fixture.workspace_id)

            # Canonical identity truth is live, reused into coverage, and never bought.
            identity = await current_value(
                conn, EntityId(fixture.account_id), _IDENTITY_ROW, scope=scope
            )
            assert identity is not None
            assert identity.freshness_state.value == "fresh"
            assert identity.provenance.evidence_span
            assert not identity.conflict
            identity_row = await _claim_row(conn, identity.provenance.claim_id)
            assert identity_row["source_key"] == _EXA_WEBSETS_SOURCE_KEY
            assert _IDENTITY_ROW not in drive.selection.admitted_field_keys
            assert _IDENTITY_ROW not in requested
            assert _IDENTITY_ROW in completed
            assert f"{_IDENTITY_ROW}:existing_claim_fresh" in skipped

            # (2) Reuse, not re-buy. Every borrowed row is completed, carries the
            # ``existing_claim_fresh`` skip, cites the discovery claim that answered it, and was
            # asked of no provider. The borrowed set covers at least the whole D4 base vocabulary.
            assert set(_discovery_values()) & set(drive.selection.admitted_field_keys) <= (
                drive.borrowed
            )
            assert drive.borrowed <= completed
            assert {f"{key}:existing_claim_fresh" for key in drive.borrowed} <= skipped
            assert not drive.borrowed & requested
            assert not drive.borrowed & drive.transport.requested_field_keys
            claim_refs = set(row["coverage_json"]["claim_refs"])
            for field_key in drive.borrowed:
                borrowed_value = await current_value(
                    conn, EntityId(fixture.account_id), field_key, scope=scope
                )
                assert borrowed_value is not None
                # Reuse is *discovery* truth, never a paid provider's answer smuggled in as free.
                borrowed_row = await _claim_row(conn, borrowed_value.provenance.claim_id)
                assert borrowed_row["source_key"] == _EXA_WEBSETS_SOURCE_KEY
                assert f"claim:{borrowed_value.provenance.claim_id}" in claim_refs

            # (3) Honest empty: asked for, answered with nothing, recorded as such — never a value.
            assert _HONEST_EMPTY in requested
            assert unresolved == {_HONEST_EMPTY}
            reasons = {str(value) for value in row["unresolved_reasons"]}
            assert reasons == {f"{_HONEST_EMPTY}:null:explicit_null"}
            assert _HONEST_EMPTY in drive.transport.requested_field_keys
            assert (
                await current_value(conn, EntityId(fixture.account_id), _HONEST_EMPTY, scope=scope)
                is None
            )

            # (4) The derive-only §3.1 rows settle without spending, through whichever of the two
            # dispositions the row's evidence supports — "reuse **or** derive". Neither is ever
            # asked of a provider: they own no acquisition source at all.
            skip_reasons = {reason.rsplit(":", 1)[0]: reason for reason in skipped}
            for field_key, source_field in DERIVED_ACCOUNT_FIELD_SOURCES.items():
                assert field_key in completed
                assert field_key not in requested
                disposition = skip_reasons[field_key].removeprefix(f"{field_key}:")
                assert disposition in {DERIVED, EXISTING_CLAIM_FRESH}
                settled = await current_value(
                    conn, EntityId(fixture.account_id), field_key, scope=scope
                )
                assert settled is not None
                if disposition == EXISTING_CLAIM_FRESH:
                    continue
                # A derived band restates governed evidence: the exact band of the live source
                # claim, carrying platform-inferred provenance over that claim's own evidence.
                source = await current_value(
                    conn, EntityId(fixture.account_id), source_field, scope=scope
                )
                assert source is not None
                expected = (
                    employee_range_value(cast(int, source.value_json))
                    if field_key == "core.employee_range"
                    else revenue_band_value(
                        Decimal(str(cast(Mapping[str, Any], source.value_json)["amount"]))
                    )
                )
                assert settled.value_json == expected
                settled_row = await _claim_row(conn, settled.provenance.claim_id)
                assert settled_row["provenance_kind"] == ClaimProvenanceKind.PLATFORM_INFERRED.value
                assert settled.provenance.evidence_span == source.provenance.evidence_span

            # (5) Everything else was acquired exactly once, through a governed tool, and every
            # acquisition that found something completed its row.
            acquired = axis - drive.borrowed - set(DERIVED_ACCOUNT_FIELD_SOURCES) - {_IDENTITY_ROW}
            assert acquired == requested
            assert acquired - {_HONEST_EMPTY} <= completed
            assert drive.transport.requested_field_keys <= acquired
            assert drive.providers.calls and "research_account_deep" not in drive.providers.calls

    run_async(scenario())


def test_the_exa_owned_profile_rows_need_more_than_one_acquisition_bundle(
    tmp_path: Path,
) -> None:
    """§3.1 gives Exa Deep more rows than one Exa output schema can carry, so the plan splits.

    Compiled over the *real* §3.1 Exa-owned field set with the *real* registered value schemas and
    the real bundler — not a synthetic field list — so the split is a property of the contract, not
    of the fixture.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_discovered_account(
                conn, FsStorage(tmp_path / "b8-bundle-artifacts")
            )
            exa_owned = tuple(
                field_key
                for field_key, sources in COMPREHENSIVE_ACCOUNT_FIELD_SOURCES.items()
                if EXA_DEEP_SOURCE_KEY in sources
            )
            assert len(exa_owned) > EXA_OUTPUT_MAX_FIELDS
            specs: list[ExaDeepFieldSpec] = []
            for field_key in exa_owned:
                definition = await get_effective_field(
                    conn,
                    scope=FieldRegistryScope.for_workspace(fixture.workspace_id),
                    field_key=field_key,
                )
                assert definition is not None
                assert definition.value_schema is not None
                specs.append(
                    ExaDeepFieldSpec(field_key=field_key, value_schema=definition.value_schema)
                )
            account = await get_account(conn, EntityId(fixture.account_id))
            assert account is not None

            plan = compile_exa_deep_acquisition_plan(
                workspace_id=fixture.workspace_id,
                project_id=fixture.project_id,
                project_run_id=ProjectRunId(fixture.project_run_id),
                account=account,
                icp_key=fixture.icp_key,
                icp_version=fixture.icp_version,
                research_directive=fixture.research_directive,
                fields=specs,
                research_intent="Answer only the admitted structured fields with evidence.",
                additional_queries=(_QUESTION,),
                observation_window=f"b8-bundles:{fixture.account_id}",
                freshness_policy_ref="freshness:b8-comprehensive-v1",
                freshness_seconds=3_600,
                cost_cents_reserved_per_bundle=Decimal("8"),
            )

            assert len(plan.bundles) >= 2
            assert plan.field_count == len(exa_owned)
            packed = [
                len(cast(Mapping[str, Any], bundle.exa_request.output_schema["properties"]))
                for bundle in plan.bundles
            ]
            assert all(count <= EXA_OUTPUT_MAX_FIELDS for count in packed)
            assert sum(packed) == len(exa_owned)

    run_async(scenario())


def test_an_unsettleable_exa_bundle_settles_terminally_instead_of_stranding_the_account(
    tmp_path: Path,
) -> None:
    """A dispatched bundle that can never yield a snapshot must still close its fields.

    Live regression: Exa answered one of four dispatched bundles with corrupted structured-output
    keys, so the whole tool call raised and no bundle was ever stamped dispatched or settled. Under
    execution closure a reservation is not an attempt, so those fields stayed outstanding on every
    replay and the account could never settle. The dispatched-but-unproductive bundle now carries
    its real dispatch time plus an append-only settlement fold, the ready bundles still persist,
    and the run closes honestly.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_discovered_account(
                conn, FsStorage(tmp_path / "b8-unsettleable-artifacts")
            )
            transport = _TruncatingExaTransport(empty_field_keys=(_HONEST_EMPTY,))
            drive = await _drive_comprehensive_run(
                conn, fixture=fixture, tmp_path=tmp_path, transport=transport
            )
            assert transport.corrupted_field_keys
            receipt = drive.result.finalization_receipt
            assert receipt is not None
            assert receipt.proposal.outcome is ResearchFinalizationOutcome.NEEDS_REVIEW

            operations = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT operation.operation_ref, operation.field_keys,
                                   operation.dispatched_at,
                                   EXISTS (
                                       SELECT 1 FROM entity_research_provider_settlement_fold fold
                                       WHERE fold.provider_operation_ref=operation.operation_ref
                                   ) AS folded,
                                   EXISTS (
                                       SELECT 1 FROM entity_research_result result
                                       WHERE result.provider_operation_ref=operation.operation_ref
                                   ) AS produced
                            FROM entity_research_provider_operation operation
                            JOIN entity_research_provider_observation observation
                              ON observation.provider_operation_ref=operation.operation_ref
                            JOIN entity_research_tool_request request_row
                              ON request_row.tool_request_id=observation.tool_request_id
                            WHERE request_row.job_id=:job_id
                              AND operation.source_key=:source_key
                            """
                        ),
                        {"job_id": drive.job_id, "source_key": EXA_DEEP_SOURCE_KEY},
                    )
                )
                .mappings()
                .all()
            )
            assert len(operations) > 1
            # No operation is left reserved-but-never-dispatched: that is the state execution
            # closure refuses to count, and the state the live account was stranded in.
            assert all(row["dispatched_at"] is not None for row in operations)
            unproductive = [row for row in operations if not row["produced"]]
            assert len(unproductive) == 1
            assert unproductive[0]["folded"]
            assert set(unproductive[0]["field_keys"]) == transport.corrupted_field_keys
            assert all(row["folded"] or row["produced"] for row in operations)

            jobs = DbEntityResearchJobStore(conn_factory=_NestedConnFactory(conn))
            stored = await jobs.get_job(drive.job_id)
            assert stored is not None
            completeness = await read_account_research_execution_completeness(
                conn, authorization=stored.authorization
            )
            assert completeness.complete
            assert not completeness.outstanding_field_source_pairs
            terminal = set(completeness.terminal_field_source_pairs)
            assert {
                (field_key, EXA_DEEP_SOURCE_KEY) for field_key in transport.corrupted_field_keys
            } <= terminal
            # The corrupted bundle bought no evidence, so its rows close as honest gaps — the
            # positive settlement disposition: NEEDS_REVIEW *after* every authorized source is
            # terminal, with the unattributable rows named in the ledger rather than fabricated.
            assert not transport.corrupted_field_keys & set(completeness.satisfied_field_keys)
            coverage = await _coverage_row(conn, job_id=drive.job_id)
            unresolved = {str(value) for value in coverage["unresolved_field_keys"]}
            completed = {str(value) for value in coverage["completed_field_keys"]}
            assert transport.corrupted_field_keys <= unresolved
            assert not transport.corrupted_field_keys & completed
            assert completed | unresolved == set(COMPREHENSIVE_ACCOUNT_FIELDS)

    run_async(scenario())


class _ReserveOnlyEnrichAction:
    """Reserve one provider operation, then die before dispatch — the crash-window shape."""

    provider_kind = "sumble_account_gaps"

    def __init__(
        self, *, workspace_id: str, project_id: str, project_run_id: UUID, account_id: UUID
    ) -> None:
        self._workspace_id = workspace_id
        self._project_id = project_id
        self._project_run_id = project_run_id
        self._account_id = account_id
        self.reserved: list[str] = []

    def _reservation(
        self,
        request: Any,
        *,
        dispatched_at: datetime | None,
    ) -> ProviderOperationReservation:
        return ProviderOperationReservation(
            provider_kind=self.provider_kind,
            operation_ref=f"sumble-account-gap-operation:{request.tool_call_id}",
            workspace_id=self._workspace_id,
            project_id=self._project_id,
            project_run_id=self._project_run_id,
            subject_type=ResearchSubjectType.ACCOUNT,
            target_entity_id=self._account_id,
            source_key=request.source_keys[0],
            field_keys=request.field_keys,
            request_artifact_ref=f"artifact:reserve-only-{request.tool_call_id}",
            reserved_at=datetime.now(UTC),
            dispatched_at=dispatched_at,
            observation_disposition=ProviderObservationDisposition.CAUSED,
        )

    async def execute(
        self,
        request: Any,
        *,
        before_dispatch: Any,
        settle_terminal: Any,
    ) -> Sequence[ProviderResearchProjectionDraft]:
        del settle_terminal
        reservation = self._reservation(request, dispatched_at=None)
        await before_dispatch(reservation)
        self.reserved.append(reservation.operation_ref)
        raise EntityResearchResultIntegrityError("provider worker died after reserving")


class _PendingEnrichAction(_ReserveOnlyEnrichAction):
    """Reserve, dispatch, then die with the provider call still in flight."""

    def __init__(self, *, conn_factory: _NestedConnFactory, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._conn_factory = conn_factory

    async def execute(
        self,
        request: Any,
        *,
        before_dispatch: Any,
        settle_terminal: Any,
    ) -> Sequence[ProviderResearchProjectionDraft]:
        del settle_terminal
        reservation = self._reservation(request, dispatched_at=None)
        await before_dispatch(reservation)
        self.reserved.append(reservation.operation_ref)
        async with self._conn_factory() as conn:
            await conn.execute(
                text(
                    "UPDATE entity_research_provider_operation SET dispatched_at=reserved_at "
                    "WHERE operation_ref=:operation_ref"
                ),
                {"operation_ref": reservation.operation_ref},
            )
        raise EntityResearchResultIntegrityError("provider worker died with the call in flight")


async def _operation_states(conn: AsyncConnection, *, job_id: UUID) -> Sequence[Mapping[str, Any]]:
    return (
        (
            await conn.execute(
                text(
                    """
                    SELECT operation.operation_ref, operation.source_key, operation.field_keys,
                           operation.dispatched_at,
                           EXISTS (
                               SELECT 1 FROM entity_research_provider_settlement_fold fold
                               WHERE fold.provider_operation_ref=operation.operation_ref
                           ) AS folded
                    FROM entity_research_provider_operation operation
                    JOIN entity_research_provider_observation observation
                      ON observation.provider_operation_ref=operation.operation_ref
                    JOIN entity_research_tool_request request_row
                      ON request_row.tool_request_id=observation.tool_request_id
                    WHERE request_row.job_id=:job_id
                      AND request_row.tool_name='enrich_account'
                    """
                ),
                {"job_id": job_id},
            )
        )
        .mappings()
        .all()
    )


def test_a_reserved_but_undispatched_operation_is_not_a_terminal_attempt(
    tmp_path: Path,
) -> None:
    """Slice-5 case 8: a reservation is journalled causation, never evidence of provider work."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_discovered_account(
                conn, FsStorage(tmp_path / "b8-reserve-only-artifacts")
            )
            action = _ReserveOnlyEnrichAction(
                workspace_id=fixture.workspace_id,
                project_id=fixture.project_id,
                project_run_id=fixture.project_run_id,
                account_id=fixture.account_id,
            )
            drive = await _drive_comprehensive_run(
                conn,
                fixture=fixture,
                tmp_path=tmp_path,
                enrich_action=action,
                expect_error=EntityResearchResultIntegrityError,
            )
            assert action.reserved
            rows = await _operation_states(conn, job_id=drive.job_id)
            assert rows and all(row["dispatched_at"] is None and not row["folded"] for row in rows)
            completeness = await read_account_research_execution_completeness(
                conn, authorization=drive.authorization
            )
            reserved_pairs = {
                (field_key, str(row["source_key"]))
                for row in rows
                for field_key in row["field_keys"]
            }
            assert reserved_pairs
            assert not reserved_pairs & set(completeness.terminal_field_source_pairs)
            assert reserved_pairs <= set(completeness.outstanding_field_source_pairs)
            assert not completeness.complete
            # One member's death marks nothing attempted — neither its own fields nor any
            # sibling's. Before the pending-release fold there is no settlement at all.
            assert not completeness.terminal_field_source_pairs
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM entity_research_provider_settlement_fold")
                )
            ).scalar_one() == 0

    run_async(scenario())


def test_a_dispatched_but_pending_operation_is_not_a_terminal_attempt(
    tmp_path: Path,
) -> None:
    """Slice-5 case 9: in-flight provider work is not a settled attempt either."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_discovered_account(
                conn, FsStorage(tmp_path / "b8-pending-artifacts")
            )
            action = _PendingEnrichAction(
                conn_factory=_NestedConnFactory(conn),
                workspace_id=fixture.workspace_id,
                project_id=fixture.project_id,
                project_run_id=fixture.project_run_id,
                account_id=fixture.account_id,
            )
            drive = await _drive_comprehensive_run(
                conn,
                fixture=fixture,
                tmp_path=tmp_path,
                enrich_action=action,
                expect_error=EntityResearchResultIntegrityError,
            )
            assert action.reserved
            rows = await _operation_states(conn, job_id=drive.job_id)
            assert rows and all(
                row["dispatched_at"] is not None and not row["folded"] for row in rows
            )
            completeness = await read_account_research_execution_completeness(
                conn, authorization=drive.authorization
            )
            pending_pairs = {
                (field_key, str(row["source_key"]))
                for row in rows
                for field_key in row["field_keys"]
            }
            assert pending_pairs
            assert not pending_pairs & set(completeness.terminal_field_source_pairs)
            assert pending_pairs <= set(completeness.outstanding_field_source_pairs)
            assert not completeness.complete

    run_async(scenario())


async def _fail_the_causing_member(conn: AsyncConnection, *, job_id: UUID) -> tuple[UUID, ...]:
    """Record the durable batch rows a member killed before dispatch leaves behind.

    ``EntityResearchParallelAdmission`` writes these itself in production; the R9 harness that
    drives it seeds no tool-request or provider-operation rows, so the rows are written here
    against the real tool request the run already produced.
    """

    requests = (
        (
            await conn.execute(
                text(
                    """
                    SELECT DISTINCT request_row.tool_request_id, request_row.agent_turn_id,
                           request_row.agent_execution_id, request_row.raw_tool_call_id,
                           request_row.research_run_id, request_row.job_id,
                           request_row.subject_type, request_row.target_entity_id,
                           request_row.workspace_id, request_row.tool_name,
                           request_row.tool_version, request_row.tool_input_sha256
                    FROM entity_research_tool_request request_row
                    JOIN entity_research_provider_observation observation
                      ON observation.tool_request_id=request_row.tool_request_id
                    JOIN entity_research_provider_operation operation
                      ON operation.operation_ref=observation.provider_operation_ref
                    WHERE request_row.job_id=:job_id
                      AND request_row.tool_name='enrich_account'
                      AND operation.dispatched_at IS NULL
                    """
                ),
                {"job_id": job_id},
            )
        )
        .mappings()
        .all()
    )
    assert requests
    for row in requests:
        batch_id = uuid4()
        await conn.execute(
            text(
                """
                INSERT INTO entity_research_tool_batch
                    (batch_id, agent_turn_id, agent_execution_id, research_run_id, job_id,
                     subject_type, target_entity_id, workspace_id, concurrency_cap,
                     call_count, batch_json, batch_sha256)
                VALUES (:batch_id, :turn_id, :execution_id, :run_id, :job_id, :subject_type,
                        :target_id, :workspace_id, 2, 1, CAST(:payload AS jsonb), :sha)
                """
            ),
            {
                "batch_id": batch_id,
                "turn_id": row["agent_turn_id"],
                "execution_id": row["agent_execution_id"],
                "run_id": row["research_run_id"],
                "job_id": row["job_id"],
                "subject_type": row["subject_type"],
                "target_id": row["target_entity_id"],
                "workspace_id": row["workspace_id"],
                "payload": json.dumps({"calls": [str(row["raw_tool_call_id"])]}),
                "sha": canonical_sha256({"calls": [str(row["raw_tool_call_id"])]}),
            },
        )
        await conn.execute(
            text(
                """
                INSERT INTO entity_research_tool_batch_member
                    (batch_id, raw_tool_call_id, tool_name, tool_version, tool_input_sha256,
                     field_keys, source_keys)
                VALUES (:batch_id, :call_id, :tool_name, :version, :input_sha, '{}', '{}')
                """
            ),
            {
                "batch_id": batch_id,
                "call_id": row["raw_tool_call_id"],
                "tool_name": row["tool_name"],
                "version": row["tool_version"],
                "input_sha": row["tool_input_sha256"],
            },
        )
        await conn.execute(
            text(
                """
                INSERT INTO entity_research_tool_batch_event
                    (event_id, batch_id, raw_tool_call_id, event_kind, disposition, error_json)
                VALUES (:event_id, :batch_id, :call_id, 'failed', 'handler_failed',
                        CAST(:error AS jsonb))
                """
            ),
            {
                "event_id": uuid4(),
                "batch_id": batch_id,
                "call_id": row["raw_tool_call_id"],
                "error": json.dumps({"error_type": "CancelledError", "message": "sibling failed"}),
            },
        )
    return tuple(UUID(str(row["tool_request_id"])) for row in requests)


def test_a_cancelled_members_pending_release_is_not_an_attempt(tmp_path: Path) -> None:
    """Slice-5 case 15: a failed member's undispatched work stops pending, never settles.

    The release is a *read*: no durable row claims the operation was settled, because nothing was
    sent. So assessment stops waiting on work that will never arrive, while execution closure
    still refuses to count it — the pairs go back to outstanding and only a real dispatch that
    produces a result settles them.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_discovered_account(
                conn, FsStorage(tmp_path / "b8-pending-release-artifacts")
            )
            action = _ReserveOnlyEnrichAction(
                workspace_id=fixture.workspace_id,
                project_id=fixture.project_id,
                project_run_id=fixture.project_run_id,
                account_id=fixture.account_id,
            )
            drive = await _drive_comprehensive_run(
                conn,
                fixture=fixture,
                tmp_path=tmp_path,
                enrich_action=action,
                expect_error=EntityResearchResultIntegrityError,
            )
            rows = await _operation_states(conn, job_id=drive.job_id)
            assert rows and all(row["dispatched_at"] is None and not row["folded"] for row in rows)
            cancelled_pairs = {
                (field_key, str(row["source_key"]))
                for row in rows
                for field_key in row["field_keys"]
            }
            pending = AccountResearchStateStore._pending_refs
            assert len(await pending(conn, drive.job_id)) == len(rows)

            await _fail_the_causing_member(conn, job_id=drive.job_id)

            # Pending-ness is released, and no settlement row was invented to do it.
            assert await pending(conn, drive.job_id) == ()
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM entity_research_provider_settlement_fold")
                )
            ).scalar_one() == 0
            # An undispatched, fold-less operation is still not a terminal attempt, so the fields
            # go back to outstanding and the agent must research them again.
            released = await read_account_research_execution_completeness(
                conn, authorization=drive.authorization
            )
            assert not cancelled_pairs & set(released.terminal_field_source_pairs)
            assert cancelled_pairs <= set(released.outstanding_field_source_pairs)
            assert not released.complete

            # A retry that really reaches the provider supersedes the release. Exa's request
            # fingerprint is job-scoped, so the retry re-dispatches this very operation; its
            # settlement is therefore the operation's *first* fold and the real spend lands.
            # The bare INSERT below is the regression guard: reintroduce a zero-cost
            # pending-release fold and it raises a unique violation here, which is exactly how
            # ``_fold_settled_spend`` used to break the production retry path.
            await conn.execute(
                text(
                    "UPDATE entity_research_provider_operation SET dispatched_at=reserved_at "
                    "WHERE operation_ref=ANY(:refs)"
                ),
                {"refs": [str(row["operation_ref"]) for row in rows]},
            )
            # A dispatch stamp alone is still not terminal: something has to come back.
            mid_flight = await read_account_research_execution_completeness(
                conn, authorization=drive.authorization
            )
            assert not cancelled_pairs & set(mid_flight.terminal_field_source_pairs)
            await conn.execute(
                text(
                    """
                    INSERT INTO entity_research_provider_settlement_fold
                        (provider_operation_ref, research_run_id, job_id, settled_cost_cents)
                    VALUES (:operation_ref, :run_id, :job_id, 4.5)
                    """
                ),
                {
                    "operation_ref": str(rows[0]["operation_ref"]),
                    "run_id": drive.authorization.research_run_id,
                    "job_id": drive.job_id,
                },
            )
            settled = await read_account_research_execution_completeness(
                conn, authorization=drive.authorization
            )
            retried_pairs = {
                (field_key, str(rows[0]["source_key"])) for field_key in rows[0]["field_keys"]
            }
            assert retried_pairs <= set(settled.terminal_field_source_pairs)
            assert not retried_pairs & set(settled.outstanding_field_source_pairs)

    run_async(scenario())
