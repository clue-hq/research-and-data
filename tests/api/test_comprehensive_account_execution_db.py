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

import asyncio
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
    EntityResearchAgentDefinition,
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
from clue_api.entity_research_runtime_wiring import (
    DbEntityResearchAgentJournal,
    EntityResearchJournalConflict,
)
from clue_api.entity_research_tools import (
    EntityResearchGovernedRejection,
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
    FieldSourceAuthority,
    GovernedResearchToolRequest,
    ResearchClaimDelta,
    ResearchFieldOutcome,
    ResearchFieldResultProjection,
    ResearchFinalizationOutcome,
    ResearchOperationKind,
    ResearchRunKind,
    ResearchRunLifecycleContract,
    ResearchSubjectType,
)
from clue_fleet import (
    DbEntityResearchJobStore,
    EntityResearchExecutionFence,
    EntityResearchJobEnvelope,
    EntityResearchRunEnvelope,
    FleetTaskKind,
    FleetTaskStatus,
    LeaseGeneration,
    WorkContext,
    WorkId,
    acquire_work_lease,
    claim_next_task,
    release_work_lease,
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
    EXA_FIELD_ALIAS_CHARACTERS,
    EXA_OUTPUT_MAX_FIELDS,
    ExaDeepFieldSpec,
)
from clue_research.resolvers.sumble import ORGANIZATIONS_SOURCE_KEY
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


#: The longest structured-output property name the live provider actually reproduced. Operation
#: ``31b13c06-…`` of job ``04162ed5-…`` requested three v1 hex aliases of 52, 66 and 74 characters
#: and answered with keys of 48, 62 and 62 — so ~62 characters is the copy budget that cost that
#: account its whole resonance bundle. Every alias the compiler emits today is ten characters.
LIVE_ALIAS_CHAR_BUDGET = 62


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
            str(field_key)
            for request in self.requests
            for field_key in request.field_key_by_alias.values()
        )

    def search(self, request: Any) -> Mapping[str, Any]:
        self.requests.append(request)
        payload: dict[str, Any] = json.loads(_EXA_RESPONSE.read_text(encoding="utf-8"))
        payload["costDollars"]["total"] = 0.07
        template = payload["output"]["grounding"][0]
        properties = cast(Mapping[str, Mapping[str, Any]], request.output_schema["properties"])
        content: dict[str, Any] = {}
        grounding: list[Mapping[str, Any]] = []
        field_key_by_alias = cast(Mapping[str, str], request.field_key_by_alias)
        for alias, schema in properties.items():
            if str(field_key_by_alias[alias]) in self._empty:
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

    The corruption is modelled as an *alias copy budget*: the provider reproduces only the first
    ``alias_char_budget`` characters of each property name. The live budget was about 62 characters
    (see :data:`LIVE_ALIAS_CHAR_BUDGET`), which the v1 hex aliases blew straight through; the
    default here is below the current fixed alias length so this transport still corrupts.
    """

    def __init__(
        self,
        *,
        alias_char_budget: int = EXA_FIELD_ALIAS_CHARACTERS - 2,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._alias_char_budget = alias_char_budget
        self.corrupted_field_keys: frozenset[str] = frozenset()

    def search(self, request: Any) -> Mapping[str, Any]:
        payload = dict(super().search(request))
        if self.corrupted_field_keys:
            return payload
        output = dict(cast(Mapping[str, Any], payload["output"]))
        content = cast(Mapping[str, Any], output["content"])
        clipped = {alias[: self._alias_char_budget]: value for alias, value in content.items()}
        if clipped == content:
            # Every alias fitted the provider's copy budget, so the exchange settles normally.
            return payload
        output["content"] = clipped
        payload["output"] = output
        field_key_by_alias = cast(Mapping[str, str], request.field_key_by_alias)
        self.corrupted_field_keys = frozenset(str(field_key_by_alias[alias]) for alias in content)
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
    definition: EntityResearchAgentDefinition
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

    connection = _NestedConnFactory(conn)
    projection = await _launch(conn, fixture=fixture, connection=connection)
    return await _drive_launched_job(
        conn,
        fixture=fixture,
        tmp_path=tmp_path,
        job_id=projection.jobs[0].job_id,
        transport=transport,
        enrich_action=enrich_action,
        expect_error=expect_error,
    )


async def _drive_launched_job(
    conn: AsyncConnection,
    *,
    fixture: _Fixture,
    tmp_path: Path,
    job_id: UUID,
    worker_id: str = "b8-comprehensive",
    transport: _ScriptedExaTransport | None = None,
    enrich_action: Any | None = None,
    expect_error: type[BaseException] | None = None,
    assert_premature_close_refused: bool = True,
    model_id: str = "b8-comprehensive-model",
) -> _Drive:
    """Drive one already-launched job exactly once, as one worker claim would.

    Separate from :func:`_drive_comprehensive_run` so the same durable job can be driven more
    than once: a crashed drive followed by a resumed re-drive is a real fleet lifecycle, and each
    call claims the task, takes the lease, and composes a fresh runtime the way a fresh worker
    process does.
    """

    storage = FsStorage(tmp_path / f"b8-artifacts-{uuid4().hex[:8]}")
    connection = _NestedConnFactory(conn)
    task = await claim_next_task(
        conn,
        kind=FleetTaskKind.ENTITY_RESEARCH_JOB,
        worker_id=worker_id,
        project_run_id=ProjectRunId(job_id),
    )
    assert task is not None
    lease = await acquire_work_lease(
        conn,
        work_id=WorkId(job_id),
        worker_id=worker_id,
        ttl=timedelta(seconds=120),
    )
    assert lease is not None
    fence = EntityResearchExecutionFence(
        task_id=task.task_id,
        worker_id=worker_id,
        lease_generation=lease.generation,
        task_attempt=task.attempts,
    )
    jobs = DbEntityResearchJobStore(conn_factory=connection)
    begun = await jobs.begin(job_id, fence=fence)
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
        observation_window=f"b8-comprehensive:{job_id}",
        research_intent=(
            "Target-lock research to this canonical account and answer only the admitted "
            "structured fields with inspectable evidence."
        ),
        freshness_policy_ref="freshness:b8-comprehensive-v1",
        freshness_seconds=3_600,
        cost_cents_reserved_per_bundle=Decimal("8"),
        entity_research_job_id=job_id,
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
                job_id: {
                    "research_account_deep": ProviderActionBinding(action=exa_action, version=1),
                    "enrich_account": ProviderActionBinding(
                        action=enrich_action or providers, version=1
                    ),
                    "discover_buying_committee": ProviderActionBinding(action=providers, version=1),
                }
            }
        ),
        model_policy=ModelPolicy(
            model_id=model_id,
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
    if assert_premature_close_refused:
        with pytest.raises(
            AccountResearchAuthorityError,
            match="coverage cannot close before every authorized field/source",
        ):
            await state.assess(
                AssessAccountCoverageInput(
                    result_refs=(), assessment_note="premature no-work close"
                ),
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
        definition=definition,
        model=model,
        providers=providers,
        transport=transport,
        job_id=job_id,
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


def test_the_live_alias_truncation_budget_no_longer_corrupts_any_bundle(tmp_path: Path) -> None:
    """The same provider that lost the live resonance bundle now copies every alias intact.

    Operation ``31b13c06-…`` of job ``04162ed5-…`` asked for three v1 hex aliases of 52, 66 and 74
    characters and answered with keys of 48, 62 and 62, so ``validate_exa_deep_exchange`` refused a
    paid exchange and ``account.resonance.buying_culture|culture|employee_sentiment`` closed as
    gaps. This drives the *same* transport at the *same* ~62-character copy budget: under the short
    alias scheme every property name is ten characters, nothing is clipped, and the fields that the
    live run lost are researched and completed instead.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_discovered_account(
                conn, FsStorage(tmp_path / "b8-alias-budget-artifacts")
            )
            transport = _TruncatingExaTransport(
                empty_field_keys=(_HONEST_EMPTY,),
                alias_char_budget=LIVE_ALIAS_CHAR_BUDGET,
            )
            drive = await _drive_comprehensive_run(
                conn, fixture=fixture, tmp_path=tmp_path, transport=transport
            )

            assert transport.requests, "no Exa bundle was compiled"
            requested = {
                alias
                for request in transport.requests
                for alias in request.output_schema["properties"]
            }
            assert requested
            assert all(len(alias) == EXA_FIELD_ALIAS_CHARACTERS for alias in requested)
            assert max(len(alias) for alias in requested) < LIVE_ALIAS_CHAR_BUDGET
            assert not transport.corrupted_field_keys

            coverage = await _coverage_row(conn, job_id=drive.job_id)
            completed = {str(value) for value in coverage["completed_field_keys"]}
            unresolved = {str(value) for value in coverage["unresolved_field_keys"]}
            assert completed | unresolved == set(COMPREHENSIVE_ACCOUNT_FIELDS)
            live_casualties = {
                "account.resonance.buying_culture",
                "account.resonance.culture",
                "account.resonance.employee_sentiment",
            } & set(COMPREHENSIVE_ACCOUNT_FIELDS)
            assert live_casualties, "the live casualties are no longer comprehensive fields"
            assert live_casualties <= completed

            operations = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT EXISTS (
                                       SELECT 1 FROM entity_research_result result
                                       WHERE result.provider_operation_ref
                                             =operation.operation_ref
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
            assert operations
            assert all(row["produced"] for row in operations)

    run_async(scenario())


def test_an_over_long_research_intent_is_refused_recoverably(tmp_path: Path) -> None:
    """A follow-up whose planning sentence overflows the product cap must not kill the job.

    Live regression: the model's follow-up ``research_account_deep`` grew the Exa planning sentence
    past the 1000-character cap, the compiler raised a bare ``ValueError`` through the tool, and
    the account's whole execution failed. The overflow is an ordinary request-shape violation —
    nothing is reserved, nothing is dispatched — so it must come back as the repairable governed
    species the agent already knows how to act on.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path / "b8-intent-cap-artifacts")
            fixture = await _seed_discovered_account(conn, storage)
            connection = _NestedConnFactory(conn)
            action = ExaAccountSemanticResearchAction(
                workspace_id=fixture.workspace_id,
                project_id=fixture.project_id,
                project_run_id=ProjectRunId(fixture.project_run_id),
                account_id=EntityId(fixture.account_id),
                icp_key=fixture.icp_key,
                icp_version=fixture.icp_version,
                research_directive=fixture.research_directive,
                acquisition=ExaDeepAcquisitionCoordinator(
                    transport=_ScriptedExaTransport(), storage=storage, conn_factory=connection
                ),
                snapshots=ExaDeepSnapshotResolverProvider(storage=storage, conn_factory=connection),
                projector=ExaEntityResearchProjectionBuilder(
                    storage=storage, conn_factory=connection
                ),
                conn_factory=connection,
                observation_window="b8-intent-cap",
                # The live shape: a confirmed directive's questions, joined, already near the cap
                # and then extended by the follow-up augmentation inside ``execute``.
                research_intent="Answer the confirmed qualitative questions with evidence. " * 40,
                freshness_policy_ref="freshness:b8-intent-cap-v1",
                freshness_seconds=3_600,
                cost_cents_reserved_per_bundle=Decimal("8"),
                entity_research_job_id=uuid4(),
            )

            async def _unreachable(operation: Any) -> Any:
                raise AssertionError("a refused request must never reserve or settle an operation")

            with pytest.raises(EntityResearchGovernedRejection) as refused:
                await action.execute(
                    GovernedResearchToolRequest(
                        research_run_id=uuid4(),
                        job_id=uuid4(),
                        subject_type=ResearchSubjectType.ACCOUNT,
                        target_entity_id=fixture.account_id,
                        agent_turn_id=uuid4(),
                        agent_execution_id=uuid4(),
                        tool_call_id=uuid4(),
                        tool_name="research_account_deep",
                        tool_version=1,
                        tool_input_sha256="b" * 64,
                        field_plan_ref="field-plan:b8-intent-cap",
                        source_plan_ref="source-plan:b8-intent-cap",
                        field_keys=("account.operational_pain",),
                        source_keys=(EXA_DEEP_SOURCE_KEY,),
                        field_source_authority=(
                            FieldSourceAuthority(
                                field_key="account.operational_pain",
                                source_keys=(EXA_DEEP_SOURCE_KEY,),
                            ),
                        ),
                        budget_reservation_key="budget:b8-intent-cap",
                        idempotency_key="idem:b8-intent-cap",
                    ),
                    before_dispatch=_unreachable,
                    settle_terminal=_unreachable,
                )

            payload = json.loads(refused.value.render())
            assert payload["error"] == "governed_research_rejection"
            assert payload["code"] == "research_request_shape_rejected"
            assert payload["recoverable"] is True
            assert "1000-character product cap" in payload["detail"]
            # Nothing was bought: no operation row exists for the refused call.
            operations = await conn.execute(
                text("SELECT count(*) FROM external_research_operation")
            )
            assert operations.scalar_one() == 0

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


async def _replay_the_operation_under_a_second_job(
    conn: AsyncConnection, *, drive: _Drive, operation_ref: str
) -> EntityResearchJobAuthorization:
    """Launch a second run over the same account and journal its replay of one operation.

    The live shape (Millennium, 2026-08-19): a provider operation ref is content-keyed, so a later
    job over the same account re-derives *the same* ref, joins it and records a
    ``replay_observation``. It dispatches nothing, buys nothing and files no fold of its own — the
    anti-double-spend rule is exactly what makes the fold single and cross-job.

    The run/job pair is written through the fleet store rather than through the account launcher on
    purpose: a second launcher call can mint a second account run pinning the same directive, which
    ``pinned_account_research_directive`` refuses as ambiguous. The authority itself is the first
    job's, copied verbatim — both jobs execute the same confirmed directive over the same account,
    which is precisely why they meet on one operation.
    """

    connection = _NestedConnFactory(conn)
    selection = drive.authorization.selection.model_copy(update={"selection_id": uuid4()})
    research_run_id = uuid4()
    job_id = uuid4()
    authorization = drive.authorization.model_copy(
        update={
            "job_id": job_id,
            "research_run_id": research_run_id,
            "selection": selection,
            "checkpoint_thread_id": f"entity-research:{job_id}",
            "attempt_id": uuid4(),
            "lease_id": uuid4(),
        }
    )
    await DbEntityResearchJobStore(conn_factory=connection).launch(
        EntityResearchRunEnvelope(
            lifecycle=ResearchRunLifecycleContract(
                run_id=research_run_id,
                run_kind=ResearchRunKind.ACCOUNT_RESEARCH,
                selection=selection,
                user_confirmed_launch=True,
                operations=(ResearchOperationKind.ACCOUNT_PROFILE,),
            ),
            jobs=(
                EntityResearchJobEnvelope(
                    authorization=authorization,
                    priority=0,
                    budget_envelope_ref=selection.budget_envelope_ref,
                    budget_cap_cents=Decimal("300"),
                ),
            ),
            budget_cap_cents=Decimal("300"),
            concurrency_limit=1,
        )
    )
    # The replaying request repeats the first job's exact governed authority — same tool, fields,
    # sources and questions — because both jobs execute the same confirmed directive. Only the
    # journal identity and the budget/idempotency keys are the second job's own.
    source = (
        (
            await conn.execute(
                text(
                    """
                    SELECT request_row.subject_type, request_row.target_entity_id,
                           request_row.workspace_id, request_row.project_id,
                           request_row.product_id, request_row.project_run_id,
                           request_row.tool_name, request_row.tool_version,
                           request_row.tool_input_sha256, request_row.field_plan_ref,
                           request_row.source_plan_ref, request_row.field_keys,
                           request_row.source_keys, request_row.questions,
                           request_row.field_source_authority, turn_row.context_json
                    FROM entity_research_tool_request request_row
                    JOIN entity_research_provider_observation observation
                      ON observation.tool_request_id=request_row.tool_request_id
                    JOIN entity_research_agent_turn turn_row
                      ON turn_row.agent_turn_id=request_row.agent_turn_id
                     AND turn_row.agent_execution_id=request_row.agent_execution_id
                    WHERE observation.provider_operation_ref=:operation_ref
                    """
                ),
                {"operation_ref": operation_ref},
            )
        )
        .mappings()
        .one()
    )
    turn_id, execution_id, event_id, request_id = uuid4(), uuid4(), uuid4(), uuid4()
    call_id = f"replay-call:{job_id}"
    params = {
        **dict(source),
        "turn_id": turn_id,
        "execution_id": execution_id,
        "event_id": event_id,
        "request_id": request_id,
        "call_id": call_id,
        "job_id": job_id,
        "research_run_id": research_run_id,
        "checkpoint_thread_id": authorization.checkpoint_thread_id,
        "observation_id": uuid4(),
        "operation_ref": operation_ref,
        "sha": "a" * 64,
        "authority": json.dumps(source["field_source_authority"]),
        # The admitted half of the context (tool names, field/source authority, questions) is the
        # first job's real journal: both jobs run the same confirmed directive, and the request
        # trigger checks every requested tool/field/source/question against it. Only the turn's own
        # identity is the second job's.
        "context": json.dumps(
            {
                **dict(source["context_json"]),
                "agent_execution_id": str(execution_id),
                "agent_turn_id": str(turn_id),
                "role": "account",
                "subject_type": str(source["subject_type"]),
                "subject_entity_id": str(source["target_entity_id"]),
                "job_id": str(job_id),
                "research_run_id": str(research_run_id),
                "workspace_id": str(source["workspace_id"]),
                "project_id": str(source["project_id"]),
                "product_id": str(source["product_id"]),
                "project_run_id": str(source["project_run_id"]),
                "checkpoint_thread_id": authorization.checkpoint_thread_id,
            }
        ),
    }
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_agent_turn
                (agent_turn_id, agent_execution_id, job_id, research_run_id, role, subject_type,
                 target_entity_id, workspace_id, project_id, product_id, project_run_id,
                 checkpoint_thread_id, context_json, context_sha256, resource_manifest_json,
                 resource_manifest_sha256, tool_manifest_json, tool_manifest_sha256,
                 system_prompt_sha256)
            VALUES
                (:turn_id, :execution_id, :job_id, :research_run_id, 'account', :subject_type,
                 :target_entity_id, :workspace_id, :project_id, :product_id, :project_run_id,
                 :checkpoint_thread_id, CAST(:context AS jsonb), :sha, '{}'::jsonb, :sha,
                 '[]'::jsonb, :sha, :sha)
            """
        ),
        params,
    )
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_agent_event
                (event_id, agent_turn_id, agent_execution_id, event_kind, tool_call_id, tool_name,
                 tool_version, tool_input_sha256, payload_json)
            VALUES (:event_id, :turn_id, :execution_id, 'tool_started', :call_id, :tool_name,
                    :tool_version, :tool_input_sha256, '{}'::jsonb)
            """
        ),
        params,
    )
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_tool_request
                (tool_request_id, agent_turn_id, agent_execution_id, tool_event_id,
                 raw_tool_call_id, research_run_id, job_id, subject_type, target_entity_id,
                 workspace_id, project_id, product_id, project_run_id, tool_name, tool_version,
                 tool_input_sha256, field_plan_ref, source_plan_ref, field_keys, source_keys,
                 questions, budget_reservation_key, idempotency_key, field_source_authority)
            VALUES
                (:request_id, :turn_id, :execution_id, :event_id, :call_id, :research_run_id,
                 :job_id, :subject_type, :target_entity_id, :workspace_id, :project_id,
                 :product_id, :project_run_id, :tool_name, :tool_version, :tool_input_sha256,
                 :field_plan_ref, :source_plan_ref, :field_keys, :source_keys, :questions,
                 :call_id, :call_id, CAST(:authority AS jsonb))
            """
        ),
        params,
    )
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_provider_observation
                (observation_id, tool_request_id, external_workspace_id, disposition,
                 provider_operation_ref)
            VALUES (:observation_id, :request_id, :workspace_id, 'replay_observation',
                    :operation_ref)
            """
        ),
        params,
    )
    return authorization


def test_a_replaying_job_sees_the_settlement_another_job_folded(tmp_path: Path) -> None:
    """The live Millennium wedge: a fold is a property of the operation, not of the asker.

    ``entity_research_provider_settlement_fold`` is keyed on the operation and inserted ON CONFLICT
    DO NOTHING, so it is written once and carries the job id of whoever settled it first. While the
    pending predicate and the completeness derivation demanded a fold carrying *their own* job id,
    a job that merely replayed the operation could never see the settlement:
    ``sumble-account-operation:89f64be2`` (Sumble tech stack, HTTP 402, folded 2026-08-19 under job
    ``298f3dec``) held two later jobs' ``assess_account_coverage`` and ``finalize_account_research``
    at "dependent account decision has pending work" until the graph recursion cap killed them.
    Nothing repaired it: the gap-ledger replay hits the terminal rejection and ON CONFLICT DO
    NOTHING keeps the first job's fold. The provider is done with this operation, so every job that
    observed it is done waiting on it.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_discovered_account(
                conn, FsStorage(tmp_path / "b8-cross-job-fold-artifacts")
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
            rows = await _operation_states(conn, job_id=drive.job_id)
            assert rows and all(
                row["dispatched_at"] is not None and not row["folded"] for row in rows
            )
            settled = rows[0]
            operation_ref = str(settled["operation_ref"])
            replayed_pairs = {
                (field_key, str(settled["source_key"])) for field_key in settled["field_keys"]
            }
            assert replayed_pairs
            # The first job reaches the provider and settles the operation terminally. A non-zero
            # cost is deliberate: the release below must move the settlement's *visibility*, never
            # its money.
            await conn.execute(
                text(
                    """
                    INSERT INTO entity_research_provider_settlement_fold
                        (provider_operation_ref, research_run_id, job_id, settled_cost_cents)
                    VALUES (:operation_ref, :run_id, :job_id, 4.5)
                    """
                ),
                {
                    "operation_ref": operation_ref,
                    "run_id": drive.authorization.research_run_id,
                    "job_id": drive.job_id,
                },
            )

            replay = await _replay_the_operation_under_a_second_job(
                conn, drive=drive, operation_ref=operation_ref
            )
            pending = AccountResearchStateStore._pending_refs
            # The replaying job observed exactly this one operation, and the provider is done with
            # it, so it waits on nothing — assessment and finalization can both proceed.
            assert await pending(conn, replay.job_id) == ()
            assert operation_ref not in await pending(conn, drive.job_id)

            # And the settled work counts as this job's attempt: it observed a dispatched operation
            # that terminally settled, which is the whole of the §5.2 attempt test.
            completeness = await read_account_research_execution_completeness(
                conn, authorization=replay
            )
            assert replayed_pairs <= set(completeness.terminal_field_source_pairs)
            assert not replayed_pairs & set(completeness.outstanding_field_source_pairs)

            # Spend attribution is untouched and stays job-scoped: the replaying job spent nothing
            # on an operation it never dispatched.
            spend = (
                (
                    await conn.execute(
                        text(
                            "SELECT job.job_id, (SELECT COALESCE(sum(fold.settled_cost_cents), 0) "
                            "FROM entity_research_provider_settlement_fold fold "
                            "WHERE fold.job_id=job.job_id) AS folded_spend "
                            "FROM entity_research_job job WHERE job.job_id=ANY(:job_ids)"
                        ),
                        {"job_ids": [str(drive.job_id), str(replay.job_id)]},
                    )
                )
                .mappings()
                .all()
            )
            assert {UUID(str(row["job_id"])): row["folded_spend"] for row in spend} == {
                drive.job_id: Decimal("4.5"),
                replay.job_id: Decimal("0"),
            }

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


async def _crashed_job_task(conn: AsyncConnection, *, job_id: UUID) -> Mapping[str, Any]:
    row = (
        (
            await conn.execute(
                text(
                    "SELECT task_id, attempts, status, result_ref_json FROM fleet_task "
                    "WHERE work_id=:job_id AND kind='entity_research_job'"
                ),
                {"job_id": job_id},
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def _agent_turns(conn: AsyncConnection, *, job_id: UUID) -> Sequence[Mapping[str, Any]]:
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT agent_turn_id, context_sha256, tool_manifest_sha256 "
                    "FROM entity_research_agent_turn WHERE job_id=:job_id ORDER BY started_at"
                ),
                {"job_id": job_id},
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def test_a_crashed_account_job_re_drives_after_a_supervisor_suspension_and_resume(
    tmp_path: Path,
) -> None:
    """The live 2026-08-19 defect: a resumed job refused itself as a replayed agent turn.

    A drive that dies inside a provider tool leaves an immutable R3 turn row keyed on
    ``(job, lease_generation, current_state_sha256)``.  ``release_work_lease`` *deletes* the lease
    row, so the resumed drive's lease starts again at generation 1 and — with the durable state
    unchanged, because the crash bought nothing — every input to that key repeats.  The resumed
    drive therefore re-minted the crashed drive's turn id, and because the fleet had meanwhile
    moved (a provider reservation resized, a concurrency default raised), the journal saw the same
    turn id under a different exact construction and failed closed with
    ``EntityResearchJournalConflict``.  Every one of the five live jobs died that way on resume.

    The attempt ordinal is now part of the turn key, so a resume is its own turn and the R3 guard
    keeps its real meaning: one turn id, one immutable construction, still fail-closed.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_discovered_account(
                conn, FsStorage(tmp_path / "b8-resume-artifacts")
            )
            connection = _NestedConnFactory(conn)
            projection = await _launch(conn, fixture=fixture, connection=connection)
            job_id = projection.jobs[0].job_id

            crash = _ReserveOnlyEnrichAction(
                workspace_id=fixture.workspace_id,
                project_id=fixture.project_id,
                project_run_id=fixture.project_run_id,
                account_id=fixture.account_id,
            )
            crashed = await _drive_launched_job(
                conn,
                fixture=fixture,
                tmp_path=tmp_path,
                job_id=job_id,
                worker_id="b8-resume-crash",
                enrich_action=crash,
                expect_error=EntityResearchResultIntegrityError,
            )
            assert crash.reserved
            first_turns = await _agent_turns(conn, job_id=job_id)
            assert len(first_turns) == 1
            # The batch rows the production coordinator writes when a member dies before
            # dispatch (the R9 harness seeds no tool-request rows, so the test writes them, as
            # ``test_a_cancelled_members_pending_release_is_not_an_attempt`` does). Without them
            # the crash's reservation stays pending and no later drive could ever settle.
            await _fail_the_causing_member(conn, job_id=job_id)
            assert crashed.outcome is None
            crashed_state_sha = (
                await conn.execute(
                    text("SELECT current_state_sha256 FROM entity_research_job WHERE job_id=:j"),
                    {"j": job_id},
                )
            ).scalar_one()

            # The supervisor's own suspension path, then the human resume, then the re-offer.
            task = await _crashed_job_task(conn, job_id=job_id)
            fleets = AccountResearchFleetService(conn_factory=connection)
            await fleets.suspend_failure(
                WorkContext(
                    task_id=UUID(str(task["task_id"])),
                    work_id=WorkId(job_id),
                    worker_id="b8-resume-crash",
                    lease_generation=LeaseGeneration(1),
                    payload={"job_id": str(job_id)},
                    stop_requested=asyncio.Event(),
                    lease_lost=asyncio.Event(),
                    task_attempt=int(task["attempts"]),
                ),
                EntityResearchResultIntegrityError("provider worker died after reserving"),
            )
            # ``suspend_failure`` cancels the drive task itself, exactly as the live run recorded
            # it: ``supervisor_suspended`` with the worker error as its reason code.
            settled = await _crashed_job_task(conn, job_id=job_id)
            assert str(settled["status"]) == FleetTaskStatus.DONE.value
            assert settled["result_ref_json"] == {
                "outcome": "supervisor_suspended",
                "reason_code": "worker_error:EntityResearchResultIntegrityError",
            }
            await release_work_lease(
                conn,
                work_id=WorkId(job_id),
                worker_id="b8-resume-crash",
                generation=LeaseGeneration(1),
            )
            await fleets.resume_job(
                job_id,
                workspace_id=fixture.workspace_id,
                actor="human:account-owner",
            )

            # The crash bought nothing and the released lease restarts at generation 1, so the
            # old turn key repeats exactly. Only the attempt ordinal separates the two drives.
            resumed = await _drive_launched_job(
                conn,
                fixture=fixture,
                tmp_path=tmp_path,
                job_id=job_id,
                worker_id="b8-resume-redrive",
                assert_premature_close_refused=False,
                # Something that constructs the agent moved while the job sat paused — live it
                # was an Exa reservation resized and a provider-concurrency default raised;
                # here, one pinned model id. Any of them changes the exact-construction digests,
                # which is what turned a re-minted turn id into a hard refusal.
                model_id="b8-comprehensive-model-v2",
            )
            after = (
                await conn.execute(
                    text("SELECT current_state_sha256 FROM entity_research_job WHERE job_id=:j"),
                    {"j": job_id},
                )
            ).scalar_one()
            assert after != crashed_state_sha  # the re-drive is the one that did the work

            turns = await _agent_turns(conn, job_id=job_id)
            assert len(turns) == 2
            assert turns[0]["agent_turn_id"] != turns[1]["agent_turn_id"]
            assert isinstance(resumed.outcome, EntityResearchAgentResult)
            receipt = resumed.result.finalization_receipt
            assert receipt is not None
            # The resumed drive reached a real engine-accepted finalization — the same honest
            # ``needs_review`` (one deliberately empty Exa row) the uninterrupted run reaches.
            assert receipt.proposal.outcome is ResearchFinalizationOutcome.NEEDS_REVIEW
            assert receipt.proposal.review_flags == ("account_fields_unresolved",)

    run_async(scenario())


def test_the_journal_still_refuses_one_turn_id_under_two_constructions(tmp_path: Path) -> None:
    """The R3 guard the resume fix must not weaken: a turn id is one immutable construction."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_discovered_account(
                conn, FsStorage(tmp_path / "b8-guard-artifacts")
            )
            connection = _NestedConnFactory(conn)
            projection = await _launch(conn, fixture=fixture, connection=connection)
            job_id = projection.jobs[0].job_id
            drive = await _drive_launched_job(
                conn,
                fixture=fixture,
                tmp_path=tmp_path,
                job_id=job_id,
                worker_id="b8-guard",
            )
            turns = await _agent_turns(conn, job_id=drive.job_id)
            assert turns
            journal = DbEntityResearchAgentJournal(conn_factory=connection)
            with pytest.raises(EntityResearchJournalConflict, match="different exact"):
                await journal.start(
                    definition=drive.definition,
                    context_sha256="b" * 64,
                    resource_manifest_sha256="c" * 64,
                    tool_manifest_sha256="d" * 64,
                    system_prompt_sha256="e" * 64,
                )

    run_async(scenario())


def test_a_historical_unrequestable_pair_is_exhausted_not_outstanding(tmp_path: Path) -> None:
    """Live regression: an unbuyable obligation looped the agent until the recursion cap.

    A selection minted before the launcher intersected wire-requestability still names pairs whose
    pinned Sumble action structurally cannot ask for the field. ``enrich_account`` refuses such a
    request as ineligible and coverage refuses to close while it is outstanding, so the agent
    alternates between the two refusals until LangGraph's recursion limit kills the job. The
    completeness reader must apply the same requestability intersection the launcher does: the
    pair is exhausted by construction and reported as an honest gap, while every requestable
    source of the same field stays outstanding until it is really attempted.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_discovered_account(
                conn, FsStorage(tmp_path / "unrequestable-artifacts")
            )
            connection = _NestedConnFactory(conn)
            projection = await _launch(conn, fixture=fixture, connection=connection)
            jobs = DbEntityResearchJobStore(conn_factory=connection)
            stored = await jobs.get_job(projection.jobs[0].job_id)
            assert stored is not None
            authorization = stored.authorization
            unbuyable = "account.operational_pain"
            # The launcher already refuses to mint the pair (the F3 intersection).
            assert not any(
                item.field_key == unbuyable and ORGANIZATIONS_SOURCE_KEY in item.source_keys
                for item in authorization.effective_field_source_authority
            )

            widened = tuple(
                item.model_copy(
                    update={"source_keys": (ORGANIZATIONS_SOURCE_KEY, *item.source_keys)}
                )
                if item.field_key == unbuyable
                else item
                for item in authorization.selection.field_source_authority
            )
            historical = authorization.model_copy(
                update={
                    "selection": authorization.selection.model_copy(
                        update={"field_source_authority": widened}
                    )
                }
            )
            assert any(
                item.field_key == unbuyable and ORGANIZATIONS_SOURCE_KEY in item.source_keys
                for item in historical.effective_field_source_authority
            )

            completeness = await read_account_research_execution_completeness(
                conn, authorization=historical
            )
            outstanding = set(completeness.outstanding_field_source_pairs)
            assert (unbuyable, ORGANIZATIONS_SOURCE_KEY) not in outstanding
            assert (unbuyable, ORGANIZATIONS_SOURCE_KEY) not in set(
                completeness.terminal_field_source_pairs
            )
            # Nothing was researched, so the requestable half of the same field is still owed:
            # the intersection drops unbuyable pairs, never real obligations.
            assert (unbuyable, EXA_DEEP_SOURCE_KEY) in outstanding
            assert unbuyable not in completeness.satisfied_field_keys
            assert not completeness.complete

    run_async(scenario())


def test_a_replaying_jobs_settlement_fold_projection_tolerates_the_first_filers_identity(
    tmp_path: Path,
) -> None:
    """The fold-replay guard compares the money fact, never the asker's identity.

    ``_fold_settled_spend`` writes the fold once (ON CONFLICT DO NOTHING) and, on replay,
    re-reads and compares. Comparing ``research_run_id``/``job_id`` made every cross-job replay
    of a settled operation an "integrity violation": live, job ``3cc0a4f2`` died at 06:20:59 on
    2026-08-20 replaying job ``298f3dec``'s folded ``sumble_jobs`` operation — same disease as
    the fold-visibility readers, one layer deeper. The run/job columns record who FILED the fold
    (that job's spend attribution); the replayer legitimately differs on both. The one true
    integrity comparison survives: the same operation claiming a *different settled cost* on
    replay still raises.
    """

    async def scenario() -> None:
        from types import SimpleNamespace

        async with rollback_conn() as conn:
            fixture = await _seed_discovered_account(
                conn, FsStorage(tmp_path / "b8-fold-identity-artifacts")
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
            rows = await _operation_states(conn, job_id=drive.job_id)
            operation_ref = str(rows[0]["operation_ref"])
            await conn.execute(
                text(
                    """
                    INSERT INTO entity_research_provider_settlement_fold
                        (provider_operation_ref, research_run_id, job_id, settled_cost_cents)
                    VALUES (:operation_ref, :run_id, :job_id, 4.5)
                    """
                ),
                {
                    "operation_ref": operation_ref,
                    "run_id": drive.authorization.research_run_id,
                    "job_id": drive.job_id,
                },
            )
            replay = await _replay_the_operation_under_a_second_job(
                conn, drive=drive, operation_ref=operation_ref
            )
            store = EntityResearchResultStore(
                storage=FsStorage(tmp_path / "b8-fold-identity-store"),
                conn_factory=_NestedConnFactory(conn),
                enforce_budget=False,
            )
            # Only the two identity fields and the cost are read on the replay path, so the
            # request stand-in carries exactly the replaying job's identity.
            replaying_request = SimpleNamespace(
                research_run_id=replay.research_run_id, job_id=replay.job_id
            )
            # Same operation, same settled cost, different run and job: a legitimate replay.
            await store._fold_settled_spend(
                conn,
                request=replaying_request,  # type: ignore[arg-type]
                provider_operation_ref=operation_ref,
                settled_cost_cents=Decimal("4.5"),
            )
            # A different settled cost for the same operation is the real integrity violation.
            with pytest.raises(EntityResearchResultIntegrityError):
                await store._fold_settled_spend(
                    conn,
                    request=replaying_request,  # type: ignore[arg-type]
                    provider_operation_ref=operation_ref,
                    settled_cost_cents=Decimal("9.9"),
                )
            # The first filer's fold row is untouched: one row, original attribution, 4.5 cents.
            fold = (
                (
                    await conn.execute(
                        text(
                            "SELECT research_run_id, job_id, settled_cost_cents "
                            "FROM entity_research_provider_settlement_fold "
                            "WHERE provider_operation_ref=:operation_ref"
                        ),
                        {"operation_ref": operation_ref},
                    )
                )
                .mappings()
                .one()
            )
            assert fold["job_id"] == drive.job_id
            assert Decimal(fold["settled_cost_cents"]) == Decimal("4.5")

    run_async(scenario())
