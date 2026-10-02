"""FI-2 slice 3 — the canonical economics fixture (spec §9 slice-3 acceptance criteria).

Two projects, one account. **P1** researched ``Cascade Gastroenterology Associates`` first and put
its world-facts on file; **P2** now targets the same account and launches its own composed M8D
account-research job. Slice 3's whole claim is what that second run costs, and what it is allowed
to destroy:

* **§6.1/§6.2 — P2 buys nothing it already owns.** A fresh, evidence-backed, conflict-free
  *project-neutral* claim is borrowed: the coverage ledger carries ``<field>:existing_claim_fresh``
  and cites P1's claim id as the evidence, no provider operation is reserved, and the job settles
  at zero account-axis spend.
* **§6.1/R3 — a project-relative field is never borrowed.** P1's angle on this account is P1's
  answer to P1's question; P2 researches its own, however fresh P1's is.
* **§6.4 — P2's writes do not destroy P1's lens.** P1's tier and value narrative stay live and
  byte-identical after P2 has researched, re-tiered and re-positioned the same account, and each
  lens still serves exactly its own — asserted through the ``run_lineage`` predicate *and* through
  the shipped read layer.
* **§6.1 — a stale neutral fact is refreshed once, for everyone.** One Exa bundle, one operation,
  one new claim; both lenses then serve the refreshed value, because a neutral fact is workspace
  truth rather than either project's property.
* **§6.2 — the R5 guard is the live enforcement point.** On the composed route it refuses a
  ``research_account_deep`` that names a borrowed field, and refuses an empty bundle repairably.
* **§6.2/§11 item 3 — the launch estimate stays gross.** The saving is read off per-job spend and
  the coverage ledger, never off a netted estimate (the ratified deviation).

**What this fixture asserts through, and what it deliberately does not.** All of Task 3's
bundle-shrink code lives in ``ExaDeepAccountResolverProvider``, whose only builder is on the M8D R1
quarantine list and has no production caller — so ``exa_deep_all_fields_already_known`` and
``AccountResolverBindings.audit_refs`` never appear in a composed run and are **not** asserted
here (``tests/api/test_fi2_62_bundle_shrink_db.py`` unit-tests that provider directly). The live
route's three surfaces are: the **R5 guard**, the **coverage ledger**, and the **operation
ledgers**. Two operation ledgers exist and both are checked — ``external_research_operation`` (the
``ExaDeepAcquisitionCoordinator``'s, which the *real* Exa action wired into this fixture writes)
and ``entity_research_provider_operation`` (the composed provider reservation every action writes,
the fixture committee/enrichment double included). The Exa action here is the production
:class:`ExaAccountSemanticResearchAction` over a recorded response, so the Exa ledger is a real
composed-run assertion, not a vacuous one.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.contracts import ModelPolicy
from clue_agents.entity_research_contracts import (
    EntityResearchAgentResult,
    EntityResearchToolCall,
)
from clue_agents.entity_research_runtime import (
    EntityResearchAgentFactory,
    EntityResearchAgentRuntime,
)
from clue_api.account_entity_research import (
    AccountResearchAuthorityError,
    AccountResearchExecutionGuard,
    AccountResearchFinalizationEngine,
    AccountResearchStateStore,
    born_complete_account_field_keys,
)
from clue_api.account_entity_research_composition import (
    AccountResearchDefinitionResolver,
    StaticAccountResearchProviderActions,
    account_research_profile_sha256,
)
from clue_api.account_research_fleet import (
    AccountResearchFleetPolicy,
    AccountResearchFleetService,
)
from clue_api.account_research_fleet_launch import (
    AccountResearchFleetLauncher,
    AccountResearchFleetLaunchError,
    AccountResearchFleetLaunchRequest,
)
from clue_api.entity_research_runtime_wiring import DbEntityResearchAgentJournal
from clue_api.entity_research_tools import (
    EntityResearchProviderCausationStore,
    EntityResearchResultStore,
    EntityResearchToolRequestStore,
    ExternalResearchResultLineageReader,
    GovernedEntityResearchToolFactory,
    ProviderActionBinding,
)
from clue_api.exa_deep_acquisition import ExaDeepAcquisitionCoordinator
from clue_api.exa_deep_materialization import ExaDeepSnapshotResolverProvider
from clue_api.exa_entity_research_tools import (
    ExaAccountSemanticResearchAction,
    ExaEntityResearchProjectionBuilder,
)
from clue_api.trial.account_deep_fixture import (
    DEEP_FIELD_KEYS,
    InsightHealthAccountDeepFixtureResult,
    seed_insight_health_account_deep_fixture,
)
from clue_api.trial.discovery_fixture import PRODUCT_ID, PROJECT_ID, WORKSPACE_ID
from clue_core import (
    Claim,
    ClaimId,
    EntityId,
    EntityType,
    ExtractionMethod,
    FieldDef,
    FieldKey,
    PassKind,
    Persona,
    ProjectRunId,
    ResearchMode,
    ResearchQuestion,
    ResearchScope,
    ReuseScope,
    RunId,
    new_entity_id,
    new_operation_id,
    new_run_id,
    resolve_research_scope,
)
from clue_core.entity_research import (
    EntityResearchJobAuthorization,
    EntityResearchSelection,
    FieldSourceAuthority,
    ResearchFinalizationOutcome,
    ResearchRunKind,
    ResearchRunLifecycleContract,
)
from clue_fleet import DbEntityResearchJobStore, EntityResearchRunEnvelope
from clue_fleet.entity_research import EntityResearchExecutionFence
from clue_research.claimstore import (
    FieldRegistryScope,
    WorkspaceScope,
    claims_for,
    current_values,
    get_effective_field,
    insert_claim,
    load_core_pack,
    project_run_ids,
    record_run_lineage,
    register_field,
)
from clue_research.discovery_scoring.tiering import AccountScoreView, persist_tier
from clue_research.durable import insert_account_run, pin_account_run_research_directive
from clue_research.identity import insert_contact_entity
from clue_research.membership import ensure_project_account
from clue_research.narrative import (
    VALUE_NARRATIVE,
    CommitteeContact,
    InMemoryClientKnowledgeRetriever,
    InMemoryCommitteeReader,
    Positioner,
    load_narrative_pack,
)
from clue_research.profiling.committee import load_committee_pack
from clue_research.resolvers.exa import exa_field_alias
from clue_research.sources import seed_source_manifests
from clue_research.stage0 import load_client_knowledge_pack
from clue_research.verification import FaithfulnessJudgeImpl
from clue_spine import Project
from clue_storage import FsStorage
from tests._workspace import seed_project
from tests.agents.test_entity_research_runtime_r3 import Checkpointers
from tests.api.account_deep_test_support import confirmed_account_research_direction
from tests.api.test_account_deep_fixture_a1 import _pages
from tests.api.test_account_entity_research_fresh_skip_db import (
    _EmptyCommitteeProviders,
    _ScriptedModel,
)
from tests.api.test_account_entity_research_r5_db import (
    _FixtureLineageReader,
    _Models,
    _NestedConnFactory,
)
from tests.profiling.conftest import rollback_conn

from .conftest import run_async

pytestmark = pytest.mark.usefixtures("require_integration_db")

# --- the account's fields, with their §5.2 species and TTLs ------------------
_HIRING = DEEP_FIELD_KEYS[0]  # account.hiring_velocity_eng — neutral, 30d
_PAIN = DEEP_FIELD_KEYS[2]  # account.operational_pain      — neutral, 90d
_MOVES = DEEP_FIELD_KEYS[3]  # account.strategic_moves      — neutral, 90d
_CULTURE = DEEP_FIELD_KEYS[4]  # account.resonance.culture  — neutral, 60d
#: A **declared** project-relative deep field (registry data, not a key rule), so the relative
#: species is exercised through ``research_scope`` and not only through the ``account.scoring.*``
#: prefix default the fresh-skip suite already covers. It is threaded into the fixture's deep ICP,
#: so P2's confirmed directive may legitimately ask for it.
_ANGLE = "account.project_angle"
_FIT = "account.scoring.fit"  # P1's *score* — relative by the ratified key rule
_TIER_FIELD = "account.scoring.tier"
#: The account-axis neutral fields P1 answered and P2 must not re-buy.
_NEUTRAL = (_HIRING, _PAIN, _MOVES, _CULTURE)

_QUALITATIVE_QUESTION = "Where is administrative work creating avoidable burden?"
_STRUCTURED_QUESTION = "What is this account's own fit against this project's ICP?"
_COMMITTEE_QUESTION = "Who participates in this product buying decision at the same office?"

#: Schema-valid values for P1's already-on-file research (``hiring_velocity_eng`` is a number).
_P1_VALUES: Mapping[str, Any] = {
    _HIRING: 7,
    _PAIN: "Referral intake is still fax-driven across three offices.",
    _MOVES: "Opening a fourth office and consolidating intake.",
    _CULTURE: "Small, tenured, referral-relationship-driven culture.",
    _ANGLE: "P1 leads with referral turnaround time.",
    _FIT: {"value": 0.82},
}
#: What P2's own research answers with, where it researches at all.
_P2_VALUES: Mapping[str, Any] = {_ANGLE: "P2 leads with intake staffing cost."}

_EXA_RESPONSE = (
    Path(__file__).parents[1] / "fixtures" / "providers" / "exa" / "search" / "deep_response.json"
)
#: The whole directive estimate for a one-account fleet: ``effort_policy.budget_cap_cents``.
_GROSS = Decimal("300")


# --- doubles ----------------------------------------------------------------
class _RecordingExaTransport:
    """The recorded E1 Exa response, narrowed to whatever the *compiled bundle* asked for.

    Narrowing is not cosmetic: the provider contract refuses a response whose grounding names a
    field the content does not carry, which is exactly the shape a shrunk bundle produces. Keeping
    the transport honest about the request is also what makes "one refresh bought one field"
    assertable — ``requested`` is the wire truth, not the test's intention.
    """

    def __init__(self) -> None:
        self.requests: list[Any] = []

    @property
    def calls(self) -> int:
        return len(self.requests)

    @property
    def requested_aliases(self) -> tuple[frozenset[str], ...]:
        return tuple(frozenset(request.output_schema["properties"]) for request in self.requests)

    def search(self, request: Any) -> Mapping[str, Any]:
        self.requests.append(request)
        aliases = set(request.output_schema["properties"])
        payload: dict[str, Any] = json.loads(_EXA_RESPONSE.read_text(encoding="utf-8"))
        payload["costDollars"]["total"] = 0.07
        recorded = dict(payload["output"]["content"])
        payload["output"]["content"] = {
            alias: recorded.get(alias) for alias in aliases if recorded.get(alias) is not None
        }
        payload["output"]["grounding"] = [
            item
            for item in payload["output"]["grounding"]
            if item["field"] in aliases and recorded.get(item["field"]) is not None
        ]
        return payload


class _FakeGateway:
    """A deterministic ``LLMGateway``: one canned answer, no network (the narrative's two calls)."""

    def __init__(self, response_text: str) -> None:
        self._response = response_text

    def complete(self, *, model: str, messages: list[Any], **opts: object) -> Any:
        from clue_core import Completion

        del messages, opts
        return Completion(
            model=model,
            text=self._response,
            cost_cents=Decimal("0.3"),
            finish_reason="stop",
        )

    def embed(self, *, model: str, inputs: list[str]) -> object:  # pragma: no cover - unused
        raise NotImplementedError("the positioner never embeds")


# --- the fixture ------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class TwoProjects:
    """One workspace, one account, two projects — the ids every assertion below is written on."""

    workspace_id: str
    account_id: EntityId
    product_id: str
    #: The earlier project, whose research and lens must survive P2.
    p1: Project
    p1_run: RunId
    p1_claims: dict[str, UUID]
    #: The project launching now (the A1 trial fixture's project run + confirmed directive).
    p2_project_id: str
    seeded: InsightHealthAccountDeepFixtureResult
    client_entity_id: EntityId


def _session(conn: AsyncConnection) -> Callable[[], AbstractAsyncContextManager[AsyncConnection]]:
    @asynccontextmanager
    async def _factory() -> AsyncIterator[AsyncConnection]:
        yield conn

    return _factory


async def _p1_claim(
    conn: AsyncConnection,
    *,
    account_id: EntityId,
    field_key: str,
    run_id: RunId,
    age: timedelta,
) -> UUID:
    """One claim P1's research already put on file about this account.

    Sourced ``sumble_jobs`` rather than ``exa_deep`` deliberately: an ``exa_deep`` claim needs full
    operation/snapshot/artifact lineage (a DB trigger enforces it), and P1's *provenance* is not
    what this fixture is about — its freshness and its species are.
    """

    collected_at = datetime.now(UTC) - age
    return UUID(
        str(
            await insert_claim(
                conn,
                Claim(
                    entity_id=account_id,
                    entity_type=EntityType.ACCOUNT,
                    field_key=field_key,
                    value_json=_P1_VALUES[field_key],
                    source_url="https://insighthealth.ai/about",
                    source_key="sumble_jobs",
                    source_tier=cast(Any, 2),
                    extraction_method=ExtractionMethod.API,
                    evidence_span="P1's own sourced evidence for this account.",
                    confidence=cast(Any, 0.9),
                    observed_at=collected_at,
                    collected_at=collected_at,
                    run_id=run_id,
                    research_mode=ResearchMode.ACCOUNT_PROFILING,
                    reuse_scope=ReuseScope.TENANT_PRIVATE,
                    workspace_id=WORKSPACE_ID,
                ),
            )
        )
    )


def _positioner(conn: AsyncConnection, *, client_entity_id: EntityId, account: EntityId) -> Any:
    """The real M12.1 positioner with deterministic gateways (no network, real claim writes)."""

    return Positioner(
        gateway=_FakeGateway(
            '{"argument": "Cascade can cut referral turnaround with the product."}'
        ),
        retriever=InMemoryClientKnowledgeRetriever(
            {
                client_entity_id: (
                    __import__(
                        "clue_core.retrieval", fromlist=["ClientKnowledgeChunk"]
                    ).ClientKnowledgeChunk(
                        client_knowledge_id="ck0",
                        chunk="the product automates referral intake reconciliation",
                    ),
                )
            }
        ),
        committee_reader=InMemoryCommitteeReader(
            {
                account: (
                    CommitteeContact(
                        contact_entity_id=new_entity_id(),
                        persona=Persona.ECONOMIC_BUYER,
                        role_on_committee="economic_buyer",
                    ),
                )
            }
        ),
        judge=FaithfulnessJudgeImpl(
            gateway=_FakeGateway(
                '{"verdict": "supported", "score": 0.92, "rationale": "the span supports it"}'
            ),
            conn_factory=_session(conn),
        ),
        conn_factory=_session(conn),
    )


async def _seed_two_projects(
    conn: AsyncConnection,
    *,
    storage: FsStorage,
    stale: Sequence[str] = (),
    with_lens: bool = False,
) -> TwoProjects:
    """P1 researched this account; P2's project run + confirmed directive are ready to launch.

    ``stale`` ages P1's claim for those fields past their TTL (200 days clears every account TTL in
    the shipped packs); ``with_lens`` additionally gives P1 a tier and a value narrative, the two
    project-relative artifacts §6.4 protects.
    """

    await load_core_pack(conn)
    await load_committee_pack(conn)
    await load_narrative_pack(conn)
    await load_client_knowledge_pack(conn)
    await seed_source_manifests(conn)
    # The declared-relative field is registry data and rides the fixture's deep ICP, so P2's
    # human-confirmed directive can legitimately ask for it (a directive field must be a
    # registered deep field that the pinned ICP activates).
    await register_field(
        conn,
        FieldDef(
            field_key=FieldKey(_ANGLE),
            value_type="str",
            pass_kind=PassKind.DEEP,
            tier_plan=("sumble_jobs", "exa_deep"),
            freshness_ttl=timedelta(days=90),
            research_scope=ResearchScope.PROJECT_RELATIVE,
        ),
        value_schema={"type": "string"},
        description="Each project's own angle on this account (declared project-relative).",
    )
    seeded = await seed_insight_health_account_deep_fixture(
        conn,
        pages=_pages(),
        storage=storage,
        deep_field_keys=(*DEEP_FIELD_KEYS, _ANGLE),
    )
    account_id = seeded.selected_account_id
    p1 = await seed_project(conn, WORKSPACE_ID, name="Project One (the earlier project)")
    await ensure_project_account(
        conn,
        workspace_id=WORKSPACE_ID,
        project_id=p1.project_id,
        account_entity_id=UUID(str(account_id)),
        added_via="discovered",
    )
    await ensure_project_account(
        conn,
        workspace_id=WORKSPACE_ID,
        project_id=PROJECT_ID,
        account_entity_id=UUID(str(account_id)),
        added_via="discovered",
    )

    p1_run = new_run_id()
    await record_run_lineage(
        conn,
        run_id=UUID(str(p1_run)),
        workspace_id=WORKSPACE_ID,
        project_id=p1.project_id,
        kind="entity_research",
    )
    claims = {
        field_key: await _p1_claim(
            conn,
            account_id=account_id,
            field_key=field_key,
            run_id=p1_run,
            age=timedelta(days=200 if field_key in stale else 2),
        )
        for field_key in (*_NEUTRAL, _ANGLE)
    }

    client_entity_id = new_entity_id()
    if with_lens:
        # P1's *score* — relative by the ratified ``account.scoring.*`` key rule, and the third
        # artifact (with the tier and the narrative) that a second project must not destroy.
        claims[_FIT] = await _p1_claim(
            conn, account_id=account_id, field_key=_FIT, run_id=p1_run, age=timedelta(days=2)
        )
        tier_run = new_run_id()
        await record_run_lineage(
            conn,
            run_id=UUID(str(tier_run)),
            workspace_id=WORKSPACE_ID,
            project_id=p1.project_id,
            kind="tiering",
        )
        await persist_tier(
            conn,
            view=AccountScoreView(account_id=account_id, fit=0.82, intent=0.4),
            tier="high",
            cutoff_version="v-p1",
            run_id=tier_run,
            workspace_id=WORKSPACE_ID,
            icp_key=seeded.deep_icp_key,
            icp_version=seeded.deep_icp_version,
            project_id=p1.project_id,
        )
        narrative_run = new_run_id()
        await record_run_lineage(
            conn,
            run_id=UUID(str(narrative_run)),
            workspace_id=WORKSPACE_ID,
            project_id=p1.project_id,
            kind="narrative",
        )
        await _positioner(conn, client_entity_id=client_entity_id, account=account_id).position(
            account_id,
            icp_spec_version=seeded.deep_icp_version,
            icp_key=seeded.deep_icp_key,
            workspace_id=WORKSPACE_ID,
            client_entity_id=client_entity_id,
            run_id=narrative_run,
            project_id=p1.project_id,
        )

    return TwoProjects(
        workspace_id=WORKSPACE_ID,
        account_id=account_id,
        product_id=PRODUCT_ID,
        p1=p1,
        p1_run=p1_run,
        p1_claims=claims,
        p2_project_id=PROJECT_ID,
        seeded=seeded,
        client_entity_id=client_entity_id,
    )


async def _confirm_p2_directive(fixture: TwoProjects, conn: AsyncConnection) -> Any:
    """P2's human-confirmed research directive, pinned onto its account run (the composed seam)."""

    _, account_spec = await confirmed_account_research_direction(
        conn,
        workspace_id=fixture.workspace_id,
        project_id=fixture.p2_project_id,
        product_id=fixture.product_id,
        account_id=fixture.account_id,
        icp_key=fixture.seeded.deep_icp_key,
        icp_version=fixture.seeded.deep_icp_version,
        field_keys=(*_NEUTRAL, _ANGLE),
        allowed_source_keys=("exa_deep", "sumble_jobs", "sumble_people"),
        questions=(
            ResearchQuestion(
                question_id="qualitative-burden",
                text=_QUALITATIVE_QUESTION,
                target_field_key=_PAIN,
            ),
            ResearchQuestion(
                question_id="project-fit",
                text=_STRUCTURED_QUESTION,
                target_field_key=_ANGLE,
            ),
        ),
    )
    directive = account_spec.research_directive
    assert directive is not None
    await insert_account_run(
        conn,
        account_run_id=fixture.seeded.expected_account_run_id,
        project_run_id=fixture.seeded.project_run_id,
        entity_id=fixture.account_id,
        tier="high",
    )
    await pin_account_run_research_directive(
        conn, account_run_id=fixture.seeded.expected_account_run_id, pin=directive
    )
    return directive


def _p2_envelope(
    fixture: TwoProjects,
    *,
    directive: Any,
    admitted: Sequence[str],
    exa_primary: Sequence[str],
) -> EntityResearchRunEnvelope:
    """P2's account-research job over the account P1 already researched.

    ``exa_primary`` decides which fields Exa is the *first* authorized source for — the input to
    the R5 first-call rule. Everything else is answered by the structured double, which is how a
    project-relative field gets bought without inventing an Exa response for it.
    """

    from tests.fleet.entity_research_r2_helpers import run_envelope

    base = run_envelope(ResearchRunKind.ACCOUNT_RESEARCH)
    original = base.lifecycle.selection
    authorities = tuple(
        FieldSourceAuthority(
            field_key=key,
            source_keys=(("exa_deep",) if key in exa_primary else ("sumble_jobs", "exa_deep")),
        )
        for key in admitted
    )
    # The selection contract requires the admitted source set to be exactly the union of the
    # per-field authority plus the committee source — no idle authority.
    admitted_sources = (
        *dict.fromkeys(source for item in authorities for source in item.source_keys),
        "sumble_people",
    )
    selection = EntityResearchSelection.model_validate(
        original.model_copy(
            update={
                "workspace_id": fixture.workspace_id,
                "project_id": fixture.p2_project_id,
                "product_id": fixture.product_id,
                "project_run_id": UUID(str(fixture.seeded.project_run_id)),
                "directive_ref": directive.directive_ref,
                "directive_sha256": directive.canonical_json_sha256,
                "subjects": (
                    original.subjects[0].model_copy(
                        update={"subject_entity_id": UUID(str(fixture.account_id))}
                    ),
                ),
                "admitted_field_keys": tuple(admitted),
                "admitted_source_keys": admitted_sources,
                "field_source_authority": authorities,
                "committee_source_keys": ("sumble_people",),
                "research_questions": (
                    _QUALITATIVE_QUESTION,
                    _STRUCTURED_QUESTION,
                    _COMMITTEE_QUESTION,
                ),
            }
        ).model_dump(mode="python")
    )
    lifecycle = ResearchRunLifecycleContract.model_validate(
        base.lifecycle.model_copy(update={"selection": selection}).model_dump(mode="python")
    )
    job = base.jobs[0]
    authorization = EntityResearchJobAuthorization.model_validate(
        job.authorization.model_copy(
            update={
                "subject_entity_id": UUID(str(fixture.account_id)),
                "workspace_id": selection.workspace_id,
                "project_id": selection.project_id,
                "product_id": selection.product_id,
                "project_run_id": selection.project_run_id,
                "selection": selection,
                "agent_profile_ref": "agent-profile:account-research:v2",
                "agent_profile_sha256": account_research_profile_sha256(),
            }
        ).model_dump(mode="python")
    )
    return EntityResearchRunEnvelope.model_validate(
        base.model_copy(
            update={
                "lifecycle": lifecycle,
                "jobs": (
                    job.model_copy(
                        update={
                            "authorization": authorization,
                            "budget_cap_cents": Decimal("30"),
                        }
                    ),
                ),
                "budget_cap_cents": Decimal("30"),
            }
        ).model_dump(mode="python")
    )


@dataclass(frozen=True, slots=True)
class _Run:
    """Everything an assertion needs about one composed P2 run."""

    outcome: Any
    model: _ScriptedModel
    providers: _EmptyCommitteeProviders
    transport: _RecordingExaTransport
    authorization: EntityResearchJobAuthorization
    definition: Any
    guard: AccountResearchExecutionGuard


async def _run_p2(
    conn: AsyncConnection,
    *,
    fixture: TwoProjects,
    directive: Any,
    admitted: Sequence[str],
    exa_primary: Sequence[str] = _NEUTRAL,
    plan: list[dict[str, Any]],
    tmp_path: Path,
) -> _Run:
    """Drive P2's job through the real composed M8D runtime (guard + engine + providers)."""

    storage = FsStorage(tmp_path / f"fi2-s3-economics-{uuid4().hex[:8]}")
    connection = _NestedConnFactory(conn)
    envelope = _p2_envelope(
        fixture, directive=directive, admitted=admitted, exa_primary=exa_primary
    )
    jobs = DbEntityResearchJobStore(conn_factory=connection)
    await jobs.launch(envelope)
    authorization = envelope.jobs[0].authorization
    # What ``AccountResearchFleetLauncher`` does inside its own launch transaction (FI-2 P2): the
    # research run is attributed to its project. This suite launches the envelope directly (as
    # every M8D runtime suite does), so it stands in for that one production mint site — without
    # it the lens predicate below would have nothing to join P2's own claims on.
    await record_run_lineage(
        conn,
        run_id=UUID(str(authorization.research_run_id)),
        workspace_id=fixture.workspace_id,
        kind="entity_research",
        project_id=fixture.p2_project_id,
        project_run_id=UUID(str(fixture.seeded.project_run_id)),
    )
    stored = await jobs.get_job(authorization.job_id)
    assert stored is not None
    live_job = stored.model_copy(
        update={"active_worker_id": "fi2-s3-economics", "lease_generation": 1}
    )
    fence = EntityResearchExecutionFence(
        task_id=uuid4(),
        worker_id="fi2-s3-economics",
        lease_generation=1,
        task_attempt=1,
    )
    contacts = (
        UUID(
            str(
                await insert_contact_entity(
                    conn,
                    account_entity_id=fixture.account_id,
                    full_name="Jordan Lee",
                    linkedin_url=f"https://linkedin.com/in/jordan-{uuid4().hex[:8]}",
                )
            )
        ),
        UUID(
            str(
                await insert_contact_entity(
                    conn,
                    account_entity_id=fixture.account_id,
                    full_name="Morgan Patel",
                    linkedin_url=f"https://linkedin.com/in/morgan-{uuid4().hex[:8]}",
                )
            )
        ),
    )
    lineage = _FixtureLineageReader()
    providers = _EmptyCommitteeProviders(
        storage=storage,
        conn_factory=connection,
        contacts=contacts,
        lineage=lineage,
        field_values=_P2_VALUES,
    )
    transport = _RecordingExaTransport()
    exa_action = ExaAccountSemanticResearchAction(
        workspace_id=fixture.workspace_id,
        project_id=fixture.p2_project_id,
        project_run_id=ProjectRunId(fixture.seeded.project_run_id),
        account_id=fixture.account_id,
        icp_key=fixture.seeded.deep_icp_key,
        icp_version=fixture.seeded.deep_icp_version,
        research_directive=directive,
        acquisition=ExaDeepAcquisitionCoordinator(
            transport=transport, storage=storage, conn_factory=connection
        ),
        snapshots=ExaDeepSnapshotResolverProvider(storage=storage, conn_factory=connection),
        projector=ExaEntityResearchProjectionBuilder(storage=storage, conn_factory=connection),
        conn_factory=connection,
        observation_window=f"fi2-s3-economics:{authorization.research_run_id}:account",
        research_intent=_QUALITATIVE_QUESTION,
        freshness_policy_ref="freshness:fi2-s3-economics-v1",
        freshness_seconds=3600,
        cost_cents_reserved_per_bundle=Decimal("8"),
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
    resolver = AccountResearchDefinitionResolver(
        tools=GovernedEntityResearchToolFactory(
            requests=EntityResearchToolRequestStore(conn_factory=connection, storage=storage),
            causation=EntityResearchProviderCausationStore(conn_factory=connection),
            results=result_store,
        ),
        state=AccountResearchStateStore(conn_factory=connection),
        provider_actions=StaticAccountResearchProviderActions(
            {
                authorization.job_id: {
                    "research_account_deep": ProviderActionBinding(action=exa_action, version=1),
                    "enrich_account": ProviderActionBinding(action=providers, version=1),
                    "discover_buying_committee": ProviderActionBinding(action=providers, version=1),
                }
            }
        ),
        model_policy=ModelPolicy(
            model_id="fi2-s3-economics-model",
            timeout_s=10,
            max_retries=0,
            max_output_tokens=4096,
            temperature=0,
        ),
        conn_factory=connection,
    )
    definition = await resolver.resolve(job=live_job, fence=fence)
    guard = AccountResearchExecutionGuard(conn_factory=connection)
    model = _ScriptedModel(plan=plan)
    journal = DbEntityResearchAgentJournal(conn_factory=connection)
    runtime = EntityResearchAgentRuntime(
        factory=EntityResearchAgentFactory(models=_Models(model), journal=journal, guard=guard),
        checkpointers=Checkpointers(),
        journal=journal,
        finalizer=AccountResearchFinalizationEngine(conn_factory=connection),
    )
    outcome = await runtime.run(definition=definition)
    return _Run(
        outcome=outcome,
        model=model,
        providers=providers,
        transport=transport,
        authorization=authorization,
        definition=definition,
        guard=guard,
    )


def _committee_call(*, account_id: EntityId, evidence_claim_id: UUID) -> dict[str, Any]:
    return {
        "name": "discover_buying_committee",
        "args": {
            "field_keys": [],
            "source_keys": ["sumble_people"],
            "questions": [_COMMITTEE_QUESTION],
            "buying_unit_scope": {
                "scope_id": str(uuid4()),
                "account_entity_id": str(account_id),
                "office_label": "Cascade gastroenterology practice",
                "locality": "Bellevue",
                "region": "Washington",
                "target_functions": ["Operations"],
                "evidence_refs": [f"claim:{evidence_claim_id}"],
                "match_policy": "same_office_strict",
            },
        },
    }


# --- ledger readers (workspace-scoped; this suite shares a database) ---------
async def _exa_operations(conn: AsyncConnection, *, account_id: EntityId) -> int:
    """``external_research_operation`` rows — the *real* Exa acquisition coordinator's ledger."""

    return int(
        (
            await conn.execute(
                text(
                    "SELECT count(*) FROM external_research_operation "
                    "WHERE workspace_id=:workspace_id AND account_id=:account_id"
                ),
                {"workspace_id": WORKSPACE_ID, "account_id": UUID(str(account_id))},
            )
        ).scalar_one()
    )


async def _account_axis_operations(
    conn: AsyncConnection, *, account_id: EntityId
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """``(source_key, field_keys)`` for every composed account-axis provider reservation.

    The committee source is excluded: it buys people, not account fields, and §6.2's claim is
    about the account axis only. Sorted by source rather than by reservation time: what §6.2
    asserts is *what was bought*, and pinning the order two providers happen to reserve in would
    make these tests fail for a reason that is not the economics.
    """

    rows = (
        await conn.execute(
            text(
                "SELECT source_key, field_keys FROM entity_research_provider_operation "
                "WHERE workspace_id=:workspace_id AND target_entity_id=:account_id "
                "AND subject_type='account' AND source_key <> 'sumble_people' "
                "ORDER BY source_key, field_keys"
            ),
            {"workspace_id": WORKSPACE_ID, "account_id": UUID(str(account_id))},
        )
    ).all()
    return tuple((str(source_key), tuple(field_keys)) for source_key, field_keys in rows)


async def _job_spend(conn: AsyncConnection, *, job_id: UUID) -> Decimal:
    return Decimal(
        (
            await conn.execute(
                text("SELECT spent_cents FROM entity_research_job WHERE job_id=:job_id"),
                {"job_id": job_id},
            )
        ).scalar_one()
    )


async def _live_claims(
    conn: AsyncConnection, *, account_id: EntityId, field_key: str
) -> tuple[Any, ...]:
    return tuple(
        await claims_for(
            conn, account_id, field_key, scope=WorkspaceScope.for_workspace(WORKSPACE_ID)
        )
    )


async def _lens(conn: AsyncConnection, *, project_id: str) -> frozenset[RunId]:
    """The project's ``run_lineage`` predicate — which claims this project's lens serves."""

    return frozenset(await project_run_ids(conn, workspace_id=WORKSPACE_ID, project_id=project_id))


# --- (1) P2 spends nothing on the facts P1 already bought --------------------
def test_fi2_slice3_p2_spends_zero_on_the_fresh_neutral_facts_p1_already_bought(
    tmp_path: Path,
) -> None:
    """§9 AC clause 1: a wholly borrowed account axis reserves nothing, anywhere, and says why."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path / "fixture-artifacts")
            fixture = await _seed_two_projects(conn, storage=storage)
            directive = await _confirm_p2_directive(fixture, conn)

            # Premise, through the one shared derivation — not a second definition of "known".
            assert await born_complete_account_field_keys(
                conn,
                workspace_id=fixture.workspace_id,
                account_entity_id=UUID(str(fixture.account_id)),
                field_keys=_NEUTRAL,
            ) == frozenset(_NEUTRAL)

            run = await _run_p2(
                conn,
                fixture=fixture,
                directive=directive,
                admitted=_NEUTRAL,
                plan=[
                    _committee_call(
                        account_id=fixture.account_id,
                        evidence_claim_id=fixture.p1_claims[_PAIN],
                    )
                ],
                tmp_path=tmp_path,
            )

            assert isinstance(run.outcome, EntityResearchAgentResult)
            receipt = run.outcome.finalization_receipt
            assert receipt is not None
            assert receipt.proposal.outcome is ResearchFinalizationOutcome.COMPLETED
            assert receipt.verification.all_passed()
            assert set(receipt.proposal.completed_field_keys) == set(_NEUTRAL)
            assert receipt.proposal.unresolved_field_keys == ()

            coverage = run.model.observed_coverage
            # The ledger says *why* nothing was bought, per field, and cites P1's own claims.
            assert set(coverage["skipped_field_reasons"]) == {
                f"{key}:existing_claim_fresh" for key in _NEUTRAL
            }
            assert set(coverage["claim_refs"]) == {
                f"claim:{fixture.p1_claims[key]}" for key in _NEUTRAL
            }
            # No provider was asked, in either operation ledger, and no HTTP was performed.
            assert run.transport.calls == 0
            assert await _exa_operations(conn, account_id=fixture.account_id) == 0
            assert await _account_axis_operations(conn, account_id=fixture.account_id) == ()
            assert run.providers.calls == ["discover_buying_committee"]
            # The only spend is the committee call: the account axis cost nothing.
            assert await _job_spend(conn, job_id=run.authorization.job_id) == Decimal("1.25")

    run_async(scenario())


# --- (2) a project-relative field is never borrowed --------------------------
def test_fi2_slice3_p2_researches_the_project_relative_field_p1_already_answered(
    tmp_path: Path,
) -> None:
    """§9 AC clause 2: species, not freshness, decides — P1's fit score is not P2's to borrow."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path / "fixture-artifacts")
            fixture = await _seed_two_projects(conn, storage=storage)
            directive = await _confirm_p2_directive(fixture, conn)

            # The species comes from the registry, never from this test's opinion of the key.
            declared = await get_effective_field(
                conn,
                scope=FieldRegistryScope.for_workspace(fixture.workspace_id),
                field_key=_ANGLE,
            )
            assert declared is not None
            assert resolve_research_scope(declared.field_def) is ResearchScope.PROJECT_RELATIVE
            # P1's angle claim is *fresh*, and still not borrowable.
            assert _ANGLE not in await born_complete_account_field_keys(
                conn,
                workspace_id=fixture.workspace_id,
                account_entity_id=UUID(str(fixture.account_id)),
                field_keys=(*_NEUTRAL, _ANGLE),
            )

            run = await _run_p2(
                conn,
                fixture=fixture,
                directive=directive,
                admitted=(*_NEUTRAL, _ANGLE),
                plan=[
                    {
                        "name": "enrich_account",
                        "args": {
                            "field_keys": [_ANGLE],
                            "source_keys": ["sumble_jobs"],
                            "questions": [_STRUCTURED_QUESTION],
                        },
                    },
                    _committee_call(
                        account_id=fixture.account_id,
                        evidence_claim_id=fixture.p1_claims[_PAIN],
                    ),
                ],
                tmp_path=tmp_path,
            )

            assert isinstance(run.outcome, EntityResearchAgentResult)
            receipt = run.outcome.finalization_receipt
            assert receipt is not None
            assert receipt.verification.all_passed()
            state = run.model.observed_state
            assert set(state["completed_field_keys"]) == set(_NEUTRAL)
            assert set(state["unresolved_field_keys"]) == {_ANGLE}
            coverage = run.model.observed_coverage
            assert set(coverage["skipped_field_reasons"]) == {
                f"{key}:existing_claim_fresh" for key in _NEUTRAL
            }
            # The relative field cost exactly one structured call; the neutral axis cost nothing.
            assert await _account_axis_operations(conn, account_id=fixture.account_id) == (
                ("sumble_jobs", (_ANGLE,)),
            )
            assert await _exa_operations(conn, account_id=fixture.account_id) == 0
            assert run.providers.calls == ["enrich_account", "discover_buying_committee"]

            # Two live angle claims, one per lens: P1's survives and P2 got its own answer.
            live = await _live_claims(conn, account_id=fixture.account_id, field_key=_ANGLE)
            p1_lens = await _lens(conn, project_id=fixture.p1.project_id)
            p2_lens = await _lens(conn, project_id=fixture.p2_project_id)
            mine = {claim.id for claim in live if claim.run_id in p2_lens}
            theirs = {claim.id for claim in live if claim.run_id in p1_lens}
            assert theirs == {ClaimId(fixture.p1_claims[_ANGLE])}
            assert len(mine) == 1 and mine.isdisjoint(theirs)

    run_async(scenario())


# --- (3) P1's lens survives P2's run -----------------------------------------
def test_fi2_slice3_p1s_lens_is_untouched_by_p2s_research_tier_and_narrative(
    tmp_path: Path,
) -> None:
    """§9 AC clause 3: P1's tier, narrative and score stay live and unchanged.

    The interesting half is not that research leaves them alone — it is that P2 then *writes its
    own* tier and narrative for the same account, ICP and persona. Before §6.4 that write chose
    P1's claim as its predecessor and superseded it. Asserted both ways: through the
    ``run_lineage`` predicate at the substrate, and through the shipped account-detail read layer,
    so a BFF bug cannot mask a substrate bug (spec §10).
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path / "fixture-artifacts")
            fixture = await _seed_two_projects(conn, storage=storage, with_lens=True)
            directive = await _confirm_p2_directive(fixture, conn)
            before = {
                field_key: {
                    claim.id: claim.value_json
                    for claim in await _live_claims(
                        conn, account_id=fixture.account_id, field_key=field_key
                    )
                }
                for field_key in (_TIER_FIELD, VALUE_NARRATIVE, _FIT)
            }
            p1_lens = await _lens(conn, project_id=fixture.p1.project_id)
            p1_before = {
                field_key: {
                    claim.id: claim.value_json
                    for claim in await _live_claims(
                        conn, account_id=fixture.account_id, field_key=field_key
                    )
                    if claim.run_id in p1_lens
                }
                for field_key in (_TIER_FIELD, VALUE_NARRATIVE, _FIT)
            }
            assert all(p1_before[field_key] for field_key in p1_before), p1_before

            await _run_p2(
                conn,
                fixture=fixture,
                directive=directive,
                admitted=(*_NEUTRAL, _ANGLE),
                plan=[
                    {
                        "name": "enrich_account",
                        "args": {
                            "field_keys": [_ANGLE],
                            "source_keys": ["sumble_jobs"],
                            "questions": [_STRUCTURED_QUESTION],
                        },
                    },
                    _committee_call(
                        account_id=fixture.account_id,
                        evidence_claim_id=fixture.p1_claims[_PAIN],
                    ),
                ],
                tmp_path=tmp_path,
            )

            # P2 now re-tiers and re-positions the same account under the same ICP and persona —
            # the write that used to destroy P1's lens.
            p2_tier_run, p2_narrative_run = new_run_id(), new_run_id()
            for run_id, kind in ((p2_tier_run, "tiering"), (p2_narrative_run, "narrative")):
                await record_run_lineage(
                    conn,
                    run_id=UUID(str(run_id)),
                    workspace_id=fixture.workspace_id,
                    project_id=fixture.p2_project_id,
                    kind=kind,
                    project_run_id=UUID(str(fixture.seeded.project_run_id)),
                )
            await persist_tier(
                conn,
                view=AccountScoreView(account_id=fixture.account_id, fit=0.55, intent=0.2),
                tier="medium",
                cutoff_version="v-p2",
                run_id=p2_tier_run,
                workspace_id=fixture.workspace_id,
                icp_key=fixture.seeded.deep_icp_key,
                icp_version=fixture.seeded.deep_icp_version,
                project_id=fixture.p2_project_id,
            )
            await _positioner(
                conn, client_entity_id=fixture.client_entity_id, account=fixture.account_id
            ).position(
                fixture.account_id,
                icp_spec_version=fixture.seeded.deep_icp_version,
                icp_key=fixture.seeded.deep_icp_key,
                workspace_id=fixture.workspace_id,
                client_entity_id=fixture.client_entity_id,
                run_id=p2_narrative_run,
                project_id=fixture.p2_project_id,
            )

            # (a) the substrate: every P1 claim is still live and byte-identical.
            for field_key, expected in p1_before.items():
                live = {
                    claim.id: claim.value_json
                    for claim in await _live_claims(
                        conn, account_id=fixture.account_id, field_key=field_key
                    )
                    if claim.run_id in p1_lens
                }
                assert live == expected, field_key
            # …and P2's own writes are additions, not replacements.
            p2_lens = await _lens(conn, project_id=fixture.p2_project_id)
            for field_key in (_TIER_FIELD, VALUE_NARRATIVE):
                live = {
                    claim.id: claim.value_json
                    for claim in await _live_claims(
                        conn, account_id=fixture.account_id, field_key=field_key
                    )
                }
                assert set(before[field_key]) < set(live), field_key
                mine = {
                    claim.id
                    for claim in await _live_claims(
                        conn, account_id=fixture.account_id, field_key=field_key
                    )
                    if claim.run_id in p2_lens
                }
                assert mine and mine.isdisjoint(p1_before[field_key])

            # (b) the read layer's half of this assertion is gone with the FI-2 payloads
            # (2026-09-09): ``projectSections[]`` was the only surface that showed one account's
            # work partitioned per project, and contract v1 has no such slot. The lens guarantee
            # itself is the ``run_lineage`` predicate above, which is where it always lived.

    run_async(scenario())


# --- (4) a stale neutral fact is refreshed once, for both lenses -------------
def test_fi2_slice3_a_stale_neutral_fact_is_refreshed_once_and_serves_both_lenses(
    tmp_path: Path,
) -> None:
    """§9 AC clause 4: one spend per expired fact — and one shared refreshed truth afterwards.

    Two of P1's facts are 200 days old against their 90-day TTLs: its strategic moves and its
    operational pain. Everything else it put on file is fresh, so P2 pays for exactly the two that
    expired — one structured call and one Exa bundle, never a re-buy of the rest. The workspace
    then reads the refreshed strategic moves from the canonical merge, which is what makes it
    *both* lenses' fact: the one account-detail view serves neutral facts unpartitioned, so P1 sees
    the refresh it did not pay for.

    The Exa half pins a second, less comfortable truth. A tier-4 synthesized claim is born
    ``unverified``, and the merge withholds an unverified tier-4 claim by design (a claim with no
    faithfulness verdict cannot be promoted). The M8D research job does not run verification —
    that is the separate VERIFICATION phase, which no composed run currently reaches (the M8D R11
    DEEP-phase bridge). So the Exa refresh is *bought and durably written* but not yet *served*;
    the structured refresh is both. That is asserted rather than hidden, so the day the bridge
    lands this test says so.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path / "fixture-artifacts")
            fixture = await _seed_two_projects(conn, storage=storage, stale=(_PAIN, _MOVES))
            directive = await _confirm_p2_directive(fixture, conn)
            stale_claim = fixture.p1_claims[_MOVES]
            still_fresh = frozenset(set(_NEUTRAL) - {_PAIN, _MOVES})
            assert (
                await born_complete_account_field_keys(
                    conn,
                    workspace_id=fixture.workspace_id,
                    account_entity_id=UUID(str(fixture.account_id)),
                    field_keys=_NEUTRAL,
                )
                == still_fresh
            )

            run = await _run_p2(
                conn,
                fixture=fixture,
                directive=directive,
                admitted=_NEUTRAL,
                # Only the pain field is Exa-primary, so the R5 first-call rule asks for exactly
                # the one expired Exa field and the structured refresh stays independent.
                exa_primary=(_PAIN,),
                plan=[
                    {
                        "name": "enrich_account",
                        "args": {
                            "field_keys": [_MOVES],
                            "source_keys": ["sumble_jobs"],
                            "questions": [_QUALITATIVE_QUESTION],
                        },
                    },
                    {
                        "name": "research_account_deep",
                        "args": {
                            "field_keys": [_PAIN],
                            "source_keys": ["exa_deep"],
                            "questions": [_QUALITATIVE_QUESTION],
                        },
                    },
                    _committee_call(
                        account_id=fixture.account_id,
                        evidence_claim_id=fixture.p1_claims[_HIRING],
                    ),
                ],
                tmp_path=tmp_path,
            )

            assert isinstance(run.outcome, EntityResearchAgentResult)
            assert run.outcome.finalization_receipt is not None
            assert run.outcome.finalization_receipt.verification.all_passed()
            # One spend per expired field, and none for the rest — in both operation ledgers.
            assert await _account_axis_operations(conn, account_id=fixture.account_id) == (
                ("exa_deep", (_PAIN,)),
                ("sumble_jobs", (_MOVES,)),
            )
            assert await _exa_operations(conn, account_id=fixture.account_id) == 1
            assert run.transport.requested_aliases == (frozenset({exa_field_alias(_PAIN)}),)
            coverage = run.model.observed_coverage
            assert set(coverage["skipped_field_reasons"]) == {
                f"{key}:existing_claim_fresh" for key in still_fresh
            }

            # The structured refresh is the workspace's current truth…
            merged = await current_values(
                conn,
                [fixture.account_id],
                [_MOVES],
                scope=WorkspaceScope.for_workspace(fixture.workspace_id),
            )
            current = merged[(fixture.account_id, _MOVES)]
            assert current.freshness_state.value == "fresh"
            assert current.provenance.claim_id != ClaimId(stale_claim)
            assert current.value_json != _P1_VALUES[_MOVES]
            # …exactly once: P1's expired claim was replaced, not duplicated into a second winner.
            live = await _live_claims(conn, account_id=fixture.account_id, field_key=_MOVES)
            assert len(live) == 2  # the expired claim is retained (append-only), not the winner
            p2_lens = await _lens(conn, project_id=fixture.p2_project_id)
            assert [claim.id for claim in live if claim.run_id in p2_lens] == [
                current.provenance.claim_id
            ]

            # …and to *both* lenses: a neutral fact is served from the canonical merge above, not
            # from either project's lineage, so the one merged winner is what every reader gets.
            # (The read-layer half of this assertion went with the FI-2 payloads on 2026-09-09.)

            # The Exa refresh: bought and durably written, and *withheld* from the merge until a
            # faithfulness verdict exists. Both halves pinned (see the docstring).
            exa_written = (
                (
                    await conn.execute(
                        text(
                            "SELECT verification_status FROM claim WHERE entity_id=:account "
                            "AND field_key=:field AND source_key='exa_deep'"
                        ),
                        {"account": UUID(str(fixture.account_id)), "field": _PAIN},
                    )
                )
                .scalars()
                .all()
            )
            assert [str(value) for value in exa_written] == ["unverified"]
            # Withheld: the merge still serves P1's own stale value, not the unverified refresh.
            pain = (
                await current_values(
                    conn,
                    [fixture.account_id],
                    [_PAIN],
                    scope=WorkspaceScope.for_workspace(fixture.workspace_id),
                )
            )[(fixture.account_id, _PAIN)]
            assert pain.value_json == _P1_VALUES[_PAIN]
            assert pain.freshness_state.value == "stale"

    run_async(scenario())


# --- (5) the R5 guard is the live enforcement point --------------------------
def test_fi2_slice3_the_live_guard_refuses_a_re_buy_and_an_empty_bundle(tmp_path: Path) -> None:
    """§9 AC clause 5: both refusals, taken against the *composed* run's own context.

    This is the surface that actually keeps §6.2's invariant on the live route — the bundle
    compiler that also implements it sits behind the M8D R1 quarantine. Both refusals are
    ``AccountResearchAuthorityError``, i.e. model-repairable turns rather than job suspensions;
    the empty-bundle one exists because ``primary - borrowed`` on a wholly borrowed account is
    empty, so the first-call rule no longer catches a zero-field call on its way to the Exa
    action's *suspending* integrity error.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path / "fixture-artifacts")
            fixture = await _seed_two_projects(conn, storage=storage)
            directive = await _confirm_p2_directive(fixture, conn)
            run = await _run_p2(
                conn,
                fixture=fixture,
                directive=directive,
                admitted=_NEUTRAL,
                plan=[
                    _committee_call(
                        account_id=fixture.account_id,
                        evidence_claim_id=fixture.p1_claims[_PAIN],
                    )
                ],
                tmp_path=tmp_path,
            )

            async def _authorize(field_keys: Sequence[str]) -> None:
                await run.guard.authorize_tool(
                    context=run.definition.context,
                    call=EntityResearchToolCall(
                        tool_call_id=f"fi2-s3-{'-'.join(field_keys) or 'empty'}",
                        tool_name="research_account_deep",
                        tool_version=1,
                        tool_input_sha256="a" * 64,
                        arguments={
                            "field_keys": list(field_keys),
                            "source_keys": ["exa_deep"],
                            "questions": [_QUALITATIVE_QUESTION],
                        },
                    ),
                    journal_event_ref="entity-agent-journal:fi2-s3-economics",
                )

            with pytest.raises(
                AccountResearchAuthorityError,
                match=f"cannot re-buy a field an existing fresh claim already answers: {_PAIN}",
            ):
                await _authorize((_PAIN,))
            with pytest.raises(
                AccountResearchAuthorityError,
                match="Exa account research needs at least one field to buy",
            ):
                await _authorize(())
            # Neither refusal bought anything, and neither wedged the job: the run had already
            # finalized cleanly with zero account-axis spend.
            assert await _account_axis_operations(conn, account_id=fixture.account_id) == ()
            assert run.transport.calls == 0

    run_async(scenario())


# --- (6) the launch estimate stays gross -------------------------------------
def test_fi2_slice3_the_launch_estimate_stays_gross_on_an_already_answered_account(
    tmp_path: Path,
) -> None:
    """§9 AC clause 6 (the ratified deviation from §6.2's should-have / §11 item 3).

    The estimate is a **ceiling**, not a forecast: ``effort_policy.budget_cap_cents`` is a
    per-account cap with no per-field decomposition, it is also each job's own spend authority, and
    ``expected_estimated_cost_cents`` is a caller-supplied number with no server-side proposal
    surface to move in step. So P2 launches at the full figure even though every admitted neutral
    field is already answered, and a caller who "helpfully" nets it is refused. Where the money
    went is answered by the *other* two surfaces this file asserts — per-job spend and the coverage
    ledger's per-field skip reasons — never by a shrunken estimate.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path / "fixture-artifacts")
            fixture = await _seed_two_projects(conn, storage=storage)
            directive = await _confirm_p2_directive(fixture, conn)
            assert await born_complete_account_field_keys(
                conn,
                workspace_id=fixture.workspace_id,
                account_entity_id=UUID(str(fixture.account_id)),
                field_keys=_NEUTRAL,
            ) == frozenset(_NEUTRAL)

            connection = _NestedConnFactory(conn)
            launcher = AccountResearchFleetLauncher(
                fleets=AccountResearchFleetService(conn_factory=connection),
                conn_factory=connection,
            )

            def _request(expected: Decimal) -> AccountResearchFleetLaunchRequest:
                return AccountResearchFleetLaunchRequest(
                    workspace_id=fixture.workspace_id,
                    project_run_id=UUID(str(fixture.seeded.project_run_id)),
                    research_directive_id=UUID(str(directive.directive_id)),
                    account_entity_ids=(UUID(str(fixture.account_id)),),
                    approved_budget_cap_cents=_GROSS,
                    expected_estimated_cost_cents=expected,
                    concurrency_limit=4,
                    supervisor_policy=AccountResearchFleetPolicy(canary_size=1),
                )

            with pytest.raises(
                AccountResearchFleetLaunchError,
                match="approved estimate differs from the current effective directives",
            ):
                await launcher.launch(
                    _request(Decimal(0)),
                    actor="human:fi2-s3-economics",
                    source_action_ref="turn:fi2-s3-netted",
                    source_operation_id=new_operation_id(),
                )

            projection = await launcher.launch(
                _request(_GROSS),
                actor="human:fi2-s3-economics",
                source_action_ref="turn:fi2-s3-gross",
                source_operation_id=new_operation_id(),
            )
            assert projection.selected_accounts == 1
            assert projection.budget_cap_cents == _GROSS
            # The skip is under-spend, not a smaller ceiling: nothing has been spent by launching.
            assert projection.spent_cents == Decimal(0)

    run_async(scenario())
