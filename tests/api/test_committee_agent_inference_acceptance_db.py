"""Slice D / D5 — the committee agent-inference acceptance flow, end to end on real Postgres.

One comprehensive account run, driven by the **real** M8D account agent runtime over the **real**
production ``SumbleCommitteeSemanticResearchAction`` with Sumble provider doubles, proving contract
§5.2's separation from discovery to a governed committee the frontend can actually render:

1. the account agent completes its confirmed account field;
2. its governed ``discover_buying_committee`` call reaches the production Sumble action, which
   acquires Teams/People, enforces the declared office, and discovers + identity-resolves the
   buying unit **in ``agent_deferred`` mode** — zero gateway calls, zero role/persona claims, every
   admitted member honestly roleless (D2);
3. the agent then judges the roles itself and writes them back through
   ``record_committee_role_inferences`` as governed, evidence-cited, agent-derived claims (D3) —
   never HUMAN-stamped (D1);
4. coverage closes ``committee_status='complete'`` with ``committee_needs_review=0``, the
   finalization engine accepts ``completed``, and the R11.5-bridged contacts read serves every
   member with its role.

**The D4 cross-assert (founder-requested).** The two honest ``needs_review`` counts are independent
by construction — the committee worker's job-local tally (how many admitted members it returned
roleless) and the tool/coverage claims-derived tally (how many members still lack a role/persona
pair) — and had never been asserted against each other. They are, here, at both stages: at
discovery every one of the N members is roleless in *both* views; after one inference the
claims-derived count is N-1; after the rest it is 0, while the worker's own tally is still N (it
described the moment discovery ended, and never changes retroactively).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.contracts import ModelPolicy
from clue_agents.entity_research_contracts import EntityResearchAgentResult
from clue_agents.entity_research_runtime import (
    EntityResearchAgentFactory,
    EntityResearchAgentRuntime,
)
from clue_api.account_entity_research import (
    AccountResearchExecutionGuard,
    AccountResearchFinalizationEngine,
    AccountResearchStateStore,
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
from clue_api.entity_research_runtime_wiring import DbEntityResearchAgentJournal
from clue_api.entity_research_tools import (
    EntityResearchProviderCausationStore,
    EntityResearchResultStore,
    EntityResearchToolRequestStore,
    ExternalResearchResultLineageReader,
    GovernedEntityResearchToolFactory,
    ProviderActionBinding,
)
from clue_api.frontend_read import FRONTEND_READ_PREFIX
from clue_api.frontend_read.v1_shared import persona_display, persona_influence
from clue_api.projections_app import create_projections_app
from clue_api.sumble_committee_acquisition import (
    SumbleCommitteeAcquisitionCoordinator,
    compile_sumble_committee_preflight,
)
from clue_api.sumble_entity_research_tools import (
    SumbleCommitteeSemanticResearchAction,
    SumbleEntityResearchLineageReader,
)
from clue_config import DEFAULT_STAGE0_POLICY, load_settings
from clue_core import (
    AccountStatus,
    ClaimProvenanceKind,
    EntityId,
    ExtractionMethod,
    IdentityBinding,
    Persona,
    ReadinessGate,
    UseClass,
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
from clue_research.claimstore import WorkspaceScope, claims_for
from clue_research.identity import insert_account_entity
from clue_research.membership import ensure_project_account
from clue_research.narrative import load_prose_pack
from clue_research.profiling.committee import PERSONA, ROLE_ON_COMMITTEE
from clue_research.profiling.committee.results import CommitteeResult
from clue_research.resolvers.sumble.committee_transport import SumbleRawPayload
from clue_research.resolvers.sumble.people import SumblePeopleResponse
from clue_research.stage0 import compile_product_context, evaluate_readiness
from clue_storage import FsStorage
from tests.agents.test_entity_research_runtime_r3 import Checkpointers
from tests.api.test_account_entity_research_r5_db import (
    _DecisionModel,
    _FixtureAccountProviders,
    _FixtureLineageReader,
    _Models,
    _NestedConnFactory,
)
from tests.api.test_sumble_committee_acquisition_s2b import _CommitteeTransport
from tests.api.test_sumble_committee_acquisition_s2b import _payload as _people_fixture
from tests.api.test_sumble_committee_acquisition_s2b import _setup as _committee_setup
from tests.db.conftest import run_async
from tests.durable.conftest import rollback_conn as durable_rollback_conn
from tests.fleet.entity_research_r2_helpers import run_envelope
from tests.profiling.conftest import FakeGateway, conn_session_factory, seed_packs

pytestmark = pytest.mark.usefixtures("require_profiling_db")

#: The one account field this run's M8D selection admits.
#:
#: RECORDED DIVERGENCE (for the reviewer, not a shortcut): the s2b fixture's confirmed directive
#: names ``core.employee_count``, and no M8D account selection can carry it — the frozen contract's
#: ``_assert_field_axis`` admits only ``account.*`` keys on the account axis while
#: ``admitted_field_keys`` has ``min_length=1``. Re-confirming an account-axis directive is not
#: available either: the account run pins its directive exactly once, and the M8D authority trigger
#: ``entity_research_validate_provider_observation`` requires the account job and the durable
#: committee acquisition to share one project run — so the pinned committee authority and the
#: durable committee request are the fixture's. The selection therefore admits the account-axis
#: field the agent actually researches, while the pinned directive it cites confirms the committee
#: plan; nothing in the engine cross-checks a selection's fields against its directive's.
_FIELD = "account.hiring_velocity_eng"
_STRUCTURED_QUESTION = "What is the current hiring velocity for operational roles?"
_COMMITTEE_QUESTION = "Who participates in this product buying decision at the same office?"
#: The declared buying unit: the provider doubles place both current employees here.
_LOCALITY = "New York"
_REGION = "New York"
_FUNCTION = "Operations"
#: Both members are current employees of the account's provider organization, so the office gate
#: admits both with zero excluded and zero ambiguous candidates (a non-zero ambiguous count is a
#: coverage ``needs_review`` flag in its own right, independent of any role).
_ORGANIZATION_ID = 1726684


# --- provider doubles ---------------------------------------------------------------------------


class _SettledCommitteeTransport(_CommitteeTransport):
    """The s2b Sumble double, with a People submission the provider settles synchronously.

    The recorded s2b fixture walks pending → running → succeeded, which is the asynchronous
    wait/wake path S2B itself owns.  This acceptance is about the *governed tool call*, so the
    double returns a settled People response to the submit — a shape the coordinator handles on its
    own ``_after_people_response`` branch — and the whole acquisition therefore reaches ``ready``
    inside the one agent tool call that caused it, with ``before_dispatch`` journaling the provider
    operation exactly as production does.

    The people payload is the recorded fixture with its second row promoted to a *current* employee
    of the same organization, office and function: two admitted members is what makes ``N-1`` a
    falsifiable partial-stage count rather than a tautological zero.
    """

    def __init__(self) -> None:
        super().__init__()
        self.people_payload = self._two_current_employees()

    @staticmethod
    def _two_current_employees() -> SumbleRawPayload:
        payload = _people_fixture("people_succeeded.json")
        second = payload["people"][1]
        second["attributes"] = {
            **second["attributes"],
            "name": "Riley Chen",
            "linkedin_url": "https://www.linkedin.com/in/riley-chen-ops",
            "job_title": "Director of Operations",
            "job_function": "Operations",
            "job_level": "Director",
            "location": "New York, New York, United States",
            "country": "United States",
            "current_employer": {
                "organization_id": _ORGANIZATION_ID,
                "name": "Insight Health",
                "start_date": "2023-05",
            },
        }
        return payload

    def submit_people(
        self, body: Mapping[str, Any], *, maximum_credits: int
    ) -> tuple[SumblePeopleResponse, SumbleRawPayload]:
        del body
        assert maximum_credits == 16
        self.calls.append("people_submit")
        payload = json.loads(json.dumps(self.people_payload))
        payload["request_id"] = self._people_request_id
        return SumblePeopleResponse.model_validate(payload), payload

    def poll_people(
        self, request_id: str, *, maximum_credits: int
    ) -> tuple[SumblePeopleResponse, SumbleRawPayload]:
        raise AssertionError(
            f"a synchronously settled People submission must never poll ({request_id})"
        )


class _ObservingCommitteeAction(SumbleCommitteeSemanticResearchAction):
    """The production committee action, with the worker's own honest tally recorded on the way out.

    ``execute`` is untouched: this only observes the :class:`CommitteeResult` the real
    ``_discover_committee_members`` returns, which is the *worker's* job-local roleless tally — the
    left-hand side of the D4 cross-assert. Nothing about the acquisition, office gate, claim writes
    or projection changes.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.discoveries: list[CommitteeResult] = []

    async def _discover_committee_members(self, *args: Any, **kwargs: Any) -> CommitteeResult:
        result = await super()._discover_committee_members(*args, **kwargs)
        self.discoveries.append(result)
        return result


# --- the scripted account mind ------------------------------------------------------------------


class _AcceptanceModel(_DecisionModel):
    """The D5 flow, decided one tool call at a time from the preceding persisted tool result.

    Reuses the R5 backbone's model mechanics (``bind_tools``, the persisted-payload decoder, the
    account/scope identity fields) and replaces only the decision sequence.
    """

    _observed_state: dict[str, Any] | None = PrivateAttr(default=None)
    _discovered_subjects: tuple[dict[str, Any], ...] = PrivateAttr(default=())
    _partial: dict[str, Any] | None = PrivateAttr(default=None)
    _complete: dict[str, Any] | None = PrivateAttr(default=None)
    _coverage: dict[str, Any] | None = PrivateAttr(default=None)
    _refs: list[str] = PrivateAttr(default_factory=list)
    _inferences_recorded: int = PrivateAttr(default=0)
    _tool_sequence: list[str] = PrivateAttr(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "slice-d-d5-committee-acceptance-account-agent"

    @property
    def observed_state(self) -> dict[str, Any] | None:
        return self._observed_state

    @property
    def discovered_subjects(self) -> tuple[dict[str, Any], ...]:
        return self._discovered_subjects

    @property
    def partial_stage(self) -> dict[str, Any] | None:
        return self._partial

    @property
    def complete_stage(self) -> dict[str, Any] | None:
        return self._complete

    @property
    def coverage(self) -> dict[str, Any] | None:
        return self._coverage

    @property
    def tool_sequence(self) -> tuple[str, ...]:
        return tuple(self._tool_sequence)

    @staticmethod
    def _member(subject: Mapping[str, Any]) -> tuple[UUID, UUID]:
        """A discovered member and one of its own professional claim ids (its role evidence)."""
        claim_ref = subject["fields"][0]["claim_refs"][0]
        return UUID(subject["target_entity_id"]), UUID(claim_ref.removeprefix("claim:"))

    def _inference(self, subject: Mapping[str, Any], *, role: Persona) -> dict[str, Any]:
        contact_id, evidence_id = self._member(subject)
        return {
            "contact_entity_id": str(contact_id),
            "role": role.value,
            "confidence": 0.84 if role is Persona.CHAMPION else 0.71,
            "reasoning": (
                "The operations leader owns the referral workflow this product replaces."
                if role is Persona.CHAMPION
                else "The operations director signs off on the budget for this workflow."
            ),
            "evidence_claim_ids": [str(evidence_id)],
        }

    @staticmethod
    def _call(name: str, args: Mapping[str, Any], call_id: str) -> ChatResult:
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="",
                        tool_calls=[{"name": name, "args": dict(args), "id": call_id}],
                    )
                )
            ]
        )

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        tools = [message for message in messages if isinstance(message, ToolMessage)]
        if not tools:
            return self._call("read_account_research_state", {}, "d5-read")
        last = tools[-1]
        payload = self._payload(last)
        self._tool_sequence.append(str(last.name))
        if last.name == "read_account_research_state":
            assert payload["result_refs"] == []
            self._observed_state = payload
            return self._call(
                "enrich_account",
                {
                    "field_keys": [_FIELD],
                    "source_keys": ["sumble_jobs"],
                    "questions": [_STRUCTURED_QUESTION],
                },
                "d5-enrich",
            )
        if last.name == "enrich_account":
            results = payload["results"]
            assert [item["field_key"] for item in results[0]["fields"]] == [_FIELD]
            self._refs.extend(item["result_ref"] for item in results)
            evidence_ref = results[0]["fields"][0]["evidence"][0]["evidence_ref"]
            return self._call(
                "discover_buying_committee",
                {
                    "field_keys": [],
                    "source_keys": ["sumble_people"],
                    "questions": [_COMMITTEE_QUESTION],
                    "buying_unit_scope": {
                        "scope_id": str(self.scope_id),
                        "account_entity_id": str(self.account_id),
                        "office_label": "Insight Health New York operations office",
                        "locality": _LOCALITY,
                        "region": _REGION,
                        "country": "United States",
                        "target_functions": [_FUNCTION],
                        "evidence_refs": [evidence_ref],
                        "match_policy": "same_office_strict",
                    },
                },
                "d5-committee",
            )
        if last.name == "discover_buying_committee":
            results = payload["results"]
            subjects = tuple(results[0]["discovered_subjects"])
            # Discovery/identity only (contract §5.2 steps 1-2): the provider action returns
            # professional facts, never a role or persona.
            assert len(subjects) == 2
            assert all(subject["fields"] for subject in subjects)
            assert not {
                field["field_key"] for subject in subjects for field in subject["fields"]
            } & {str(ROLE_ON_COMMITTEE), str(PERSONA)}
            self._discovered_subjects = subjects
            self._refs.extend(item["result_ref"] for item in results)
            return self._call(
                "record_committee_role_inferences",
                {"inferences": [self._inference(subjects[0], role=Persona.CHAMPION)]},
                "d5-role-first",
            )
        if last.name == "record_committee_role_inferences":
            if self._inferences_recorded == 0:
                # Partial stage: N members, one inferred, N-1 honestly still needing review.
                assert payload["committee_member_count"] == 2
                assert payload["inferred_member_count"] == 1
                assert payload["needs_review"] == 1
                assert payload["committee_status"] == "needs_review"
                self._partial = payload
                self._inferences_recorded += 1
                return self._call(
                    "record_committee_role_inferences",
                    {
                        "inferences": [
                            self._inference(subject, role=Persona.ECONOMIC_BUYER)
                            for subject in self._discovered_subjects[1:]
                        ]
                    },
                    "d5-role-rest",
                )
            assert payload["committee_member_count"] == 2
            assert payload["inferred_member_count"] == 2
            assert payload["needs_review"] == 0
            assert payload["committee_status"] == "complete"
            self._complete = payload
            self._inferences_recorded += 1
            return self._call(
                "assess_account_coverage",
                {
                    "result_refs": list(self._refs),
                    "assessment_note": (
                        "The confirmed account field is grounded and every discovered committee "
                        "member carries a cited role inference."
                    ),
                },
                "d5-coverage",
            )
        if last.name == "assess_account_coverage":
            assert payload["committee_status"] == "complete"
            assert payload["committee_needs_review"] == 0
            assert "committee_roles_uninferred" not in payload["review_flags"]
            assert payload["unresolved_field_keys"] == []
            self._coverage = payload
            return self._call(
                "finalize_account_research",
                {
                    "coverage_ledger_ref": payload["coverage_ledger_ref"],
                    "requested_outcome": "completed",
                },
                "d5-finalize",
            )
        # ``finalize_account_research`` is deliberately absent: the runtime arms deterministic
        # termination the moment the engine's finalize tool returns its admissible proposal
        # (``_note_finalization_result`` / ``_engine_proposal``) and echoes that proposal itself, so
        # the model is never asked to speak again. A tool result arriving here would mean the
        # runtime resumed a finished run.
        raise AssertionError(f"unexpected D5 tool result: {last.name}")


# --- harness ------------------------------------------------------------------------------------


def _envelope(
    *,
    account_id: UUID,
    workspace_id: str,
    project_id: str,
    product_id: str,
    project_run_id: UUID,
    directive_ref: str,
    directive_sha256: str,
) -> EntityResearchRunEnvelope:
    """One account-research launch envelope over the s2b account and its confirmed directive."""

    base = run_envelope(ResearchRunKind.ACCOUNT_RESEARCH)
    original = base.lifecycle.selection
    selection = EntityResearchSelection.model_validate(
        original.model_copy(
            update={
                "workspace_id": workspace_id,
                "project_id": project_id,
                "product_id": product_id,
                "project_run_id": project_run_id,
                "directive_ref": directive_ref,
                "directive_sha256": directive_sha256,
                "subjects": (
                    original.subjects[0].model_copy(update={"subject_entity_id": account_id}),
                ),
                "admitted_field_keys": (_FIELD,),
                "admitted_source_keys": ("sumble_jobs", "sumble_people"),
                "field_source_authority": (
                    FieldSourceAuthority(field_key=_FIELD, source_keys=("sumble_jobs",)),
                ),
                "committee_source_keys": ("sumble_people",),
                "research_questions": (_STRUCTURED_QUESTION, _COMMITTEE_QUESTION),
            }
        ).model_dump(mode="python")
    )
    lifecycle = ResearchRunLifecycleContract.model_validate(
        base.lifecycle.model_copy(update={"selection": selection}).model_dump(mode="python")
    )
    original_job = base.jobs[0]
    authorization = EntityResearchJobAuthorization.model_validate(
        original_job.authorization.model_copy(
            update={
                "subject_entity_id": account_id,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "product_id": product_id,
                "project_run_id": project_run_id,
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
                    original_job.model_copy(
                        update={
                            "authorization": authorization,
                            "budget_cap_cents": Decimal("60"),
                        }
                    ),
                ),
                "budget_cap_cents": Decimal("60"),
            }
        ).model_dump(mode="python")
    )


async def _confirm_stage0_pins(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    brand_id: str,
    product_id: str,
    project_run_id: UUID,
    icp_key: str,
    icp_version: int,
) -> None:
    """Complete this project run's Stage-0 execution pins, so product-pinned reads can serve it.

    ``project_run_stage0_pins_complete`` binds client entity / KB version / product / product
    context / readiness together, so a run either carries the whole confirmed chain or none of it —
    and every product-pinned read (the C7 lens and this flow's contacts committee read alike)
    compares a claim's ``product_id`` against the run's pin. The s2b committee fixture's run is
    created before its product is confirmed and so carries none of the chain; a run that carries it
    is the confirmed shape production reaches, not a test-only relaxation.

    The run cannot simply be replaced by a freshly pinned one: the M8D authority trigger
    ``entity_research_validate_provider_observation`` requires a governed tool request and the
    provider operation it causes to share one ``project_run_id``, so the account job and the durable
    committee acquisition are the same run by construction.
    """

    client_entity_id = await insert_account_entity(
        conn,
        canonical_name="D5 acceptance client",
        primary_domain=f"{uuid4().hex[:10]}.example",
        status=AccountStatus.ACTIVE,
        workspace_id=workspace_id,
    )
    context = await compile_product_context(
        conn,
        workspace_id=workspace_id,
        brand_id=brand_id,
        product_id=product_id,
        client_entity_id=client_entity_id,
        client_kb_version=1,
        claim_refs=(),
    )
    readiness = await evaluate_readiness(
        conn,
        workspace_id=workspace_id,
        brand_id=brand_id,
        product_id=product_id,
        project_id=project_id,
        client_entity_id=client_entity_id,
        client_kb_version=1,
        icp_key=icp_key,
        icp_version=icp_version,
        product_context_version_id=context.version_id,
        gate=ReadinessGate.DISCOVERY_SPEND,
        spec=DEFAULT_STAGE0_POLICY.readiness,
        metrics={"coverage_ratio": 1.0, "verified_claims": 1, "open_policy_blocks": 0},
        created_by_actor="agent",
    )
    await conn.execute(
        text(
            "UPDATE project_run SET client_entity_id=:client, client_kb_version=1, "
            "product_id=:product, product_context_version_id=:context, "
            "readiness_decision_id=:readiness WHERE id=:id AND workspace_id=:workspace_id"
        ),
        {
            "client": client_entity_id,
            "product": product_id,
            "context": context.version_id,
            "readiness": readiness.readiness_decision_id,
            "id": project_run_id,
            "workspace_id": workspace_id,
        },
    )


def _projections_client(conn: AsyncConnection) -> httpx.AsyncClient:
    app = create_projections_app(
        surface=None,  # type: ignore[arg-type]
        tool_invoker=None,  # type: ignore[arg-type]
        settings=load_settings(_env_file=None, frontend_read_enabled=True),
        conn_factory=conn_session_factory(conn),
        manage_db_lifespan=False,
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://d5")


# --- the acceptance -----------------------------------------------------------------------------


def test_d5_committee_discovery_defers_roles_and_the_account_agent_completes_the_committee(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    require_profiling_db: None,
) -> None:
    async def scenario() -> None:
        # The pilot posture: tier-4 agent-inferred role claims are born UNVERIFIED, and the
        # verified-tier-4 merge gate would withhold them from every governed read if verification
        # were enabled. Pinned explicitly rather than inherited from the product overlay.
        monkeypatch.setenv("CLUE_VERIFICATION_ENABLED", "false")
        storage = FsStorage(tmp_path / "d5-artifacts")
        workspace_id = "ws-d5-committee-acceptance"
        async with durable_rollback_conn(seed_pack=True) as conn:
            durable = await _committee_setup(conn, storage, workspace_id=workspace_id)
            await seed_packs(conn)
            await load_prose_pack(conn)

            project_id = durable.project_id
            account_id = UUID(str(durable.account_id))
            brand_id, product_id = (
                (
                    await conn.execute(
                        text(
                            "SELECT brand_id, product_id FROM project "
                            "WHERE project_id=:project_id AND workspace_id=:workspace_id"
                        ),
                        {"project_id": project_id, "workspace_id": workspace_id},
                    )
                )
                .tuples()
                .one()
            )
            project_run_id = UUID(str(durable.project_run_id))
            await _confirm_stage0_pins(
                conn,
                workspace_id=workspace_id,
                project_id=project_id,
                brand_id=str(brand_id),
                product_id=str(product_id),
                project_run_id=project_run_id,
                icp_key=durable.icp_key,
                icp_version=durable.icp_version,
            )
            await ensure_project_account(
                conn,
                workspace_id=workspace_id,
                project_id=project_id,
                account_entity_id=durable.account_id,
                added_via="discovered",
            )

            connection = _NestedConnFactory(conn)

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            # The confirmed direction this pass executes under: the fixture's own human-confirmed
            # directive, already pinned on this run's account run, which is what makes its committee
            # plan readable back to the agent as authority.
            directive = durable.research_directive
            assert directive is not None
            envelope = _envelope(
                account_id=account_id,
                workspace_id=workspace_id,
                project_id=project_id,
                product_id=str(product_id),
                project_run_id=project_run_id,
                directive_ref=directive.directive_ref,
                directive_sha256=directive.canonical_json_sha256,
            )
            authorization = envelope.jobs[0].authorization
            # The production launch: one human-confirmed fleet run, which is also what binds this
            # research run to the project run for the R11.5 committee bridge.
            await AccountResearchFleetService(conn_factory=connection).launch(
                envelope,
                policy=AccountResearchFleetPolicy(canary_size=1),
                actor="user:d5-acceptance",
                source_operation_id=envelope.lifecycle.run_id,
                source_action_ref=f"agent-action:launch-account-research:{uuid4()}",
            )
            jobs = DbEntityResearchJobStore(conn_factory=connection)
            stored_job = await jobs.get_job(authorization.job_id)
            assert stored_job is not None
            live_job = stored_job.model_copy(
                update={"active_worker_id": "d5-test-worker", "lease_generation": 1}
            )
            fence = EntityResearchExecutionFence(
                task_id=uuid4(),
                worker_id="d5-test-worker",
                lease_generation=1,
                task_attempt=1,
            )

            lineage = _FixtureLineageReader()
            fixture_providers = _FixtureAccountProviders(
                storage=storage,
                conn_factory=connection,
                contacts=(uuid4(), uuid4()),  # unused: the committee is the real Sumble action
                lineage=lineage,
                field_values={_FIELD: 42},
            )
            transport = _SettledCommitteeTransport()
            coordinator = SumbleCommitteeAcquisitionCoordinator(
                transport=transport,
                storage=storage,
                cents_per_credit=Decimal("0.5"),
                conn_factory=same_connection,
                poll_after_seconds=30,
            )
            gateway = FakeGateway()
            committee_action = _ObservingCommitteeAction(
                preflight=compile_sumble_committee_preflight(
                    durable, cents_per_credit=Decimal("0.5")
                ),
                coordinator=coordinator,
                storage=storage,
                conn_factory=same_connection,
                gateway=gateway,
                role_model="d5-role-model-must-not-be-called",
            )

            result_store = EntityResearchResultStore(
                storage=storage,
                conn_factory=connection,
                lineage_readers={
                    ExternalResearchResultLineageReader.provider_kind: (
                        ExternalResearchResultLineageReader(conn_factory=connection)
                    ),
                    lineage.provider_kind: lineage,
                    "sumble_committee": SumbleEntityResearchLineageReader(
                        provider_kind="sumble_committee",
                        conn_factory=connection,
                    ),
                },
            )
            tool_factory = GovernedEntityResearchToolFactory(
                requests=EntityResearchToolRequestStore(
                    conn_factory=connection,
                    storage=storage,
                ),
                causation=EntityResearchProviderCausationStore(conn_factory=connection),
                results=result_store,
            )
            state = AccountResearchStateStore(conn_factory=connection)
            resolver = AccountResearchDefinitionResolver(
                tools=tool_factory,
                state=state,
                provider_actions=StaticAccountResearchProviderActions(
                    {
                        authorization.job_id: {
                            "research_account_deep": ProviderActionBinding(
                                action=fixture_providers, version=1
                            ),
                            "enrich_account": ProviderActionBinding(
                                action=fixture_providers, version=1
                            ),
                            "discover_buying_committee": ProviderActionBinding(
                                action=committee_action, version=1
                            ),
                        }
                    }
                ),
                model_policy=ModelPolicy(
                    model_id="d5-test-model",
                    timeout_s=10,
                    max_retries=0,
                    max_output_tokens=4096,
                    temperature=0,
                ),
                conn_factory=connection,
            )
            definition = await resolver.resolve(job=live_job, fence=fence)
            # The confirmed committee plan reaches the agent before its first tool choice — the
            # authority its buying-unit scope narrows within.
            assert directive.directive_ref in definition.task_instruction
            assert "- functions: Operations, Administration" in definition.task_instruction
            assert "- levels: Director, VP" in definition.task_instruction
            assert "- personas: champion, economic_buyer" in definition.task_instruction
            assert "- candidate_cap: 2" in definition.task_instruction

            model = _AcceptanceModel(account_id=account_id, scope_id=uuid4())
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
            outcome = await runtime.run(definition=definition)

            # --- the run itself -----------------------------------------------------------------
            assert isinstance(outcome, EntityResearchAgentResult)
            assert outcome.finalization_receipt is not None
            assert (
                outcome.finalization_receipt.proposal.outcome
                is ResearchFinalizationOutcome.COMPLETED
            )
            assert outcome.finalization_receipt.verification.all_passed()
            # The exact governed decision sequence, one call per persisted result. It ends at
            # coverage because the runtime terminates deterministically once the engine's finalize
            # tool has returned its proposal — it echoes that proposal rather than asking the model
            # to repeat it (``EntityResearchAgentRuntime._note_finalization_result``).
            assert model.tool_sequence == (
                "read_account_research_state",
                "enrich_account",
                "discover_buying_committee",
                "record_committee_role_inferences",
                "record_committee_role_inferences",
                "assess_account_coverage",
            )
            assert transport.calls == ["teams", "people_submit"]
            # Its first read showed the agent the same confirmed committee plan the definition
            # carried — the state read is where a resumed turn would re-learn it.
            observed_state = model.observed_state
            assert observed_state is not None
            assert observed_state["committee_plan"] == {
                "directive_ref": directive.directive_ref,
                "functions": ["Operations", "Administration"],
                "levels": ["Director", "VP"],
                "teams": [],
                "personas": ["champion", "economic_buyer"],
                "candidate_cap": 2,
                "questions": [],
            }
            assert fixture_providers.calls == ["enrich_account"]

            # --- deferred discovery: no role work was bought at all -----------------------------
            assert gateway.complete_calls == 0
            assert len(committee_action.discoveries) == 1
            discovered = committee_action.discoveries[0]
            members = tuple(member.contact_entity_id for member in discovered.members)
            assert len(members) == 2
            assert all(
                member.persona is None
                and member.role_claim_id is None
                and member.persona_claim_id is None
                and member.professional_claim_ids
                for member in discovered.members
            )
            assert discovered.committee() == ()
            # What the agent was actually handed: professional facts about identified people, and
            # no judgment — the discovered-subject projection carries neither role nor persona.
            assert {UUID(subject["target_entity_id"]) for subject in model.discovered_subjects} == {
                UUID(str(value)) for value in members
            }
            assert not {
                field["field_key"]
                for subject in model.discovered_subjects
                for field in subject["fields"]
            } & {str(ROLE_ON_COMMITTEE), str(PERSONA)}

            # --- D4 cross-assert: two independent honest needs_review counts --------------------
            # At discovery the worker's job-local tally is every admitted member, and the
            # claims-derived view agrees: no member has a role/persona pair yet.
            assert discovered.needs_review == len(discovered.members) == 2
            partial = model.partial_stage
            complete = model.complete_stage
            assert partial is not None and complete is not None
            assert partial["committee_member_count"] == discovered.admitted == 2
            assert partial["needs_review"] == len(discovered.members) - 1 == 1
            assert partial["committee_status"] == "needs_review"
            assert complete["needs_review"] == 0
            assert complete["committee_status"] == "complete"
            # The worker's tally is a statement about the moment discovery ended and never moves.
            assert discovered.needs_review == 2

            # --- coverage row -------------------------------------------------------------------
            coverage = (
                (
                    await conn.execute(
                        text(
                            "SELECT committee_status, review_flags, committee_member_ids, "
                            "claim_refs, coverage_json FROM entity_research_account_coverage "
                            "WHERE job_id=:job_id ORDER BY created_at DESC LIMIT 1"
                        ),
                        {"job_id": authorization.job_id},
                    )
                )
                .mappings()
                .one()
            )
            assert coverage["committee_status"] == "complete"
            assert coverage["coverage_json"]["committee_needs_review"] == 0
            assert "committee_roles_uninferred" not in coverage["review_flags"]
            assert coverage["review_flags"] == []
            assert {UUID(str(value)) for value in coverage["committee_member_ids"]} == {
                UUID(str(value)) for value in members
            }
            # The ledger the agent saw is the ledger that persisted — no post-hoc recompute.
            assessed = model.coverage
            assert assessed is not None
            assert assessed["coverage_ledger_ref"] == (
                f"account-coverage:{coverage['coverage_json']['coverage_id']}"
            )
            assert assessed["completed_field_keys"] == [_FIELD]

            # --- the agent-derived role/persona claims ------------------------------------------
            scope = WorkspaceScope.for_workspace(workspace_id)
            expected_roles = {
                UUID(str(members[0])): Persona.CHAMPION,
                UUID(str(members[1])): Persona.ECONOMIC_BUYER,
            }
            role_claim_refs: set[str] = set()
            for member_id, persona in expected_roles.items():
                roles = await claims_for(conn, EntityId(member_id), ROLE_ON_COMMITTEE, scope=scope)
                personas = await claims_for(conn, EntityId(member_id), PERSONA, scope=scope)
                assert len(roles) == len(personas) == 1
                role_claim, persona_claim = roles[0], personas[0]
                assert role_claim.extraction_method is ExtractionMethod.LLM_SYNTHESIS
                assert persona_claim.extraction_method is ExtractionMethod.LLM_SYNTHESIS
                assert int(role_claim.source_tier) == int(persona_claim.source_tier) == 4
                assert role_claim.provenance_kind is ClaimProvenanceKind.PLATFORM_INFERRED
                assert persona_claim.provenance_kind is ClaimProvenanceKind.PLATFORM_INFERRED
                assert role_claim.identity_binding is IdentityBinding.STRONG
                assert persona_claim.identity_binding is IdentityBinding.STRONG
                assert role_claim.use_class is UseClass.PROFESSIONAL_PUBLIC
                assert set(role_claim.value_json) == {
                    "role",
                    "confidence",
                    "plausible",
                    "rationale",
                }
                assert role_claim.value_json["role"] == persona.value
                assert role_claim.value_json["plausible"] is True
                assert str(role_claim.value_json["rationale"]).strip()
                assert persona_claim.value_json == persona.value
                assert role_claim.source_url and role_claim.evidence_span
                assert role_claim.product_id == str(product_id)
                role_claim_refs |= {f"claim:{role_claim.id}", f"claim:{persona_claim.id}"}
            assert role_claim_refs <= set(coverage["claim_refs"])

            # --- zero HUMAN role provenance (D1) ------------------------------------------------
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM claim WHERE run_id=:run_id "
                        "AND extraction_method='human'"
                    ),
                    {"run_id": authorization.research_run_id},
                )
            ).scalar_one() == 0
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM claim WHERE entity_id=ANY(:members) "
                        "AND extraction_method='human'"
                    ),
                    {"members": [UUID(str(value)) for value in members]},
                )
            ).scalar_one() == 0

            # --- lineage ------------------------------------------------------------------------
            operation_lineage = (
                (
                    await conn.execute(
                        text(
                            "SELECT organization_identity_ref, account_id, workspace_id "
                            "FROM committee_acquisition_operation WHERE workspace_id=:workspace_id"
                        ),
                        {"workspace_id": workspace_id},
                    )
                )
                .mappings()
                .all()
            )
            assert len(operation_lineage) == 1
            assert (
                operation_lineage[0]["organization_identity_ref"]
                == "account-gap-snapshot:sumble_organizations:test"
            )
            assert UUID(str(operation_lineage[0]["account_id"])) == account_id
            role_run_ids = {
                UUID(str(value))
                for value in (
                    (
                        await conn.execute(
                            text(
                                "SELECT DISTINCT run_id FROM claim WHERE entity_id=ANY(:members) "
                                "AND field_key=ANY(:fields)"
                            ),
                            {
                                "members": [UUID(str(value)) for value in members],
                                "fields": [str(ROLE_ON_COMMITTEE), str(PERSONA)],
                            },
                        )
                    )
                    .scalars()
                    .all()
                )
            }
            assert role_run_ids  # an empty set would make the attribution query vacuous
            unattributed = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM unnest(CAST(:runs AS uuid[])) AS run(run_id) "
                        "WHERE NOT EXISTS (SELECT 1 FROM run_lineage lineage "
                        "WHERE lineage.run_id=run.run_id "
                        "AND lineage.workspace_id=:workspace_id "
                        "AND lineage.project_id=:project_id "
                        "AND lineage.project_run_id=:project_run_id "
                        "AND lineage.kind=:kind)"
                    ),
                    {
                        "runs": sorted(role_run_ids),
                        "workspace_id": workspace_id,
                        "project_id": project_id,
                        # The committee action registers its run against the project run the
                        # durable committee acquisition belongs to — the run whose observation
                        # window bought the People snapshot the role claims are grounded in. The
                        # role claims inherit that run from the evidence they cite, so this is the
                        # run the project lens back-joins them through.
                        "project_run_id": UUID(str(durable.project_run_id)),
                        # ``record_run_lineage`` is first-writer-wins on ``kind``: the project run
                        # was already registered by the launch path, so the committee action's
                        # re-registration is a harmless no-op and the durable kind stays
                        # ``entity_research``. The project attribution is identical either way.
                        "kind": "entity_research",
                    },
                )
            ).scalar_one()
            assert unattributed == 0

            # --- finalization intent ------------------------------------------------------------
            intent = (
                (
                    await conn.execute(
                        text(
                            "SELECT proposal_json->>'outcome' FROM "
                            "entity_research_account_finalization_intent WHERE job_id=:job_id"
                        ),
                        {"job_id": authorization.job_id},
                    )
                )
                .scalars()
                .all()
            )
            assert list(intent) == ["completed"]

            # --- the members and their roles reach the contacts read ----------------------------
            async with _projections_client(conn) as client:
                response = await client.get(
                    f"{FRONTEND_READ_PREFIX}/accounts/{account_id}/contacts",
                    headers={"X-Workspace-Id": workspace_id},
                )
            assert response.status_code == 200, response.text
            body = response.json()
            rows = {row["id"]: row for row in body["data"]}
            assert set(rows) == {str(value) for value in members}
            assert body["meta"]["total"] == 2
            for member_id, persona in expected_roles.items():
                row = rows[str(member_id)]
                # The agent's persona reaches the screen as the text a marketer reads, and the
                # influence column falls back to that persona's own default because these role
                # claims carry no ``influence`` key of their own (ruling S8). The claim-level
                # assertions above are where the role, its confidence and its rationale are
                # pinned; the row is the proof they are *rendered*, not a second copy of them.
                assert row["persona"] == persona_display(persona.value)
                assert row["influence"] == persona_influence(persona.value)
                # A member the read found claims for is linked, not a dead row.
                assert row["profileAction"] == "page"

    run_async(scenario())
