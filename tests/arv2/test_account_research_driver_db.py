"""One account job driven end to end against the real rows: run, job, claims, receipt, activity.

The model is scripted (it finalizes at once) and no provider is reached, but everything below the
agent is real — the R2 store's CHECKs, the lenient claim gate, the ICP and persona documents read
through the verified-artifact path, and the derived run status.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from pydantic import PrivateAttr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2 import account_research_store as store
from clue_api.arv2.account_research_catalog import (
    ARV2_ACCOUNT_PROFILE_REF,
    arv2_account_profile_sha256,
    arv2_person_profile_sha256,
)
from clue_api.arv2.account_research_driver import (
    Arv2AccountResearchWorkHandler,
    arv2_account_work_id,
)
from clue_api.arv2.claim_writer import ClaimDraft, LenientClaimWriter
from clue_config import Settings
from clue_core import (
    EntityId,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    ResearchMode,
    RunId,
    UseClass,
    new_project_run_id,
)
from clue_fleet.lease import LeaseGeneration
from clue_fleet.work_worker import WorkContext
from clue_research.claimstore import WorkspaceScope, claims_for
from clue_research.durable.project_run import ensure_project_run
from clue_research.identity import insert_account_entity, insert_contact_entity
from clue_storage import artifact_key, content_address, record_artifact
from tests._workspace import seed_project
from tests.api.test_stage0_setup_db import _MemoryStorage
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401
    require_profiling_db,  # noqa: F401
    rollback_conn,
)

pytestmark = pytest.mark.usefixtures("require_profiling_db")

ICP_MARKDOWN = (
    "---\nkind: icp-definition\nicp_key: clue-abm-buyers\n---\n\n"
    "# ICP\nSeries A B2B SaaS with an outbound motion.\n"
)
PERSONA_MARKDOWN = (
    "---\nkind: audience-persona\nicp_key: clue-abm-buyers\n---\n\n"
    "# Personas\nchampion: VP Demand Generation.\n"
)


class _ScriptedModel(BaseChatModel):
    _respond: Callable[[list[BaseMessage]], AIMessage] = PrivateAttr()

    def __init__(self, respond: Callable[[list[BaseMessage]], AIMessage]) -> None:
        super().__init__()
        self._respond = respond

    @property
    def _llm_type(self) -> str:
        return "arv2-account-db-scripted"

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        **kwargs: Any,
    ) -> _ScriptedModel:
        del tools, kwargs
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        return ChatResult(generations=[ChatGeneration(message=self._respond(messages))])


class _Models:
    def __init__(self, model: BaseChatModel) -> None:
        self._model = model

    def build(self, **kwargs: Any) -> BaseChatModel:
        del kwargs
        return self._model


class _Clients:
    def exa(self, caller: Any) -> Any:
        raise AssertionError("no provider is reached in this test")

    def ai_ark(self, caller: Any) -> Any:
        raise AssertionError("no provider is reached in this test")

    def media(self, caller: Any, ledger: Any) -> Any:
        raise AssertionError("no provider is reached in this test")

    def structuring(self, caller: Any) -> Any:
        raise AssertionError("no provider is reached in this test")


def _finalizing_model() -> _ScriptedModel:
    def respond(messages: list[BaseMessage]) -> AIMessage:
        del messages
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "finalize_research",
                    "args": {
                        "summary": "Probook hires GTM roles and names its customers.",
                        "fit_verdicts": [
                            {
                                "gate": "series-a-saas",
                                "verdict": "likely",
                                "rationale": "Open demand-gen requisitions.",
                                "claim_ids": [],
                            }
                        ],
                        "gaps": ["revenue undisclosed"],
                        "committee_candidates": [],
                    },
                    "id": "call-finalize",
                    "type": "tool_call",
                }
            ],
            usage_metadata={"input_tokens": 1_000, "output_tokens": 200, "total_tokens": 1_200},
            response_metadata={
                "clue_cost_cents": "0.5",
                "clue_cost_source": "metered",
                "clue_answering_model": "x-ai/grok-4.6",
            },
        )

    return _ScriptedModel(respond)


async def _register_document(
    conn: AsyncConnection,
    storage: _MemoryStorage,
    *,
    workspace_id: str,
    brand_id: str,
    path: str,
    kind: str,
    status: str,
    body: str,
) -> tuple[str, str]:
    """Register one knowledge document the way the answer-key loader does: artifact then row."""
    payload = body.encode("utf-8")
    sha = content_address(payload)
    key = artifact_key(workspace_id, sha)
    await record_artifact(
        conn,
        storage_key=key,
        workspace_id=workspace_id,
        content_sha256=sha,
        media_type="text/markdown",
        size_bytes=len(payload),
        source_key="arv2_knowledge_document",
    )
    await storage.put(key, payload, media_type="text/markdown")
    await conn.execute(
        text(
            """
            INSERT INTO brand_knowledge_document
                (document_id, workspace_id, brand_id, folder, path, kind, version, status,
                 artifact_key, artifact_sha256)
            VALUES
                (:document_id, :workspace_id, :brand_id, :folder, :path, :kind, 1, :status,
                 :artifact_key, :artifact_sha256)
            """
        ),
        {
            "document_id": uuid4(),
            "workspace_id": workspace_id,
            "brand_id": brand_id,
            "folder": path.split("/", 1)[0],
            "path": path,
            "kind": kind,
            "status": status,
            "artifact_key": key,
            "artifact_sha256": sha,
        },
    )
    return key, sha


def test_one_job_runs_to_a_finalized_receipt_and_a_completed_run() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id = "ws-r2-driver-db"
            project = await seed_project(conn, workspace_id, name="R2 driver")
            project_run_id = new_project_run_id()
            await ensure_project_run(
                conn,
                project_run_id=project_run_id,
                project_id=project.project_id,
                workspace_id=workspace_id,
                icp_key="clue-abm-buyers",
                icp_version=1,
            )
            account_id = await insert_account_entity(
                conn,
                canonical_name="Probook",
                primary_domain="probook.ai",
                workspace_id=workspace_id,
            )
            storage = _MemoryStorage()
            icp_key_, icp_sha = await _register_document(
                conn,
                storage,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                path="audience/icp-clue-abm-buyers.md",
                kind="icp-definition",
                status="confirmed",
                body=ICP_MARKDOWN,
            )
            await _register_document(
                conn,
                storage,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                path="audience/persona-clue-abm-buyers.md",
                kind="audience-persona",
                status="ready",
                body=PERSONA_MARKDOWN,
            )

            run_id, job_id = uuid4(), uuid4()
            await store.create_run(
                conn,
                store.RunRow(
                    run_id=run_id,
                    workspace_id=workspace_id,
                    project_id=project.project_id,
                    brand_id=project.brand_id,
                    project_run_id=UUID(str(project_run_id)),
                    icp_artifact_key=icp_key_,
                    icp_artifact_sha256=icp_sha,
                    icp_key="clue-abm-buyers",
                    icp_version=1,
                    product_selection_version=1,
                    effort="full",
                    committee_cap=3,
                    directive_text="prioritise hiring evidence",
                    profile_ref=ARV2_ACCOUNT_PROFILE_REF,
                    profile_sha256=arv2_account_profile_sha256(),
                    requested_by_user_id="usr-r2",
                    request_sha256=hashlib.sha256(b"request").hexdigest(),
                ),
            )
            await store.create_job(
                conn,
                job_id=job_id,
                run_id=run_id,
                workspace_id=workspace_id,
                account_entity_id=UUID(str(account_id)),
            )

            handler = Arv2AccountResearchWorkHandler(
                settings=Settings(_env_file=None),
                conn_factory=conn_session_factory(conn),
                # The production sink, injected from outside the lane exactly as ``fleet_main``
                # will inject it. No provider hop runs here, so nothing is persisted through it —
                # what the test pins is that the composed handler takes the platform's own store.
                artifacts=DurableAgentArtifactStore(
                    storage=storage,  # type: ignore[arg-type]
                    conn_factory=conn_session_factory(conn),
                ),
                storage=storage,
                clients=_Clients(),
                model_provider=_Models(_finalizing_model()),
                model_id="x-ai/grok-4.6",
                writer=LenientClaimWriter(lenient=True),
                clock=lambda: datetime(2026, 9, 8, 12, 0, tzinfo=UTC),
            )
            context = WorkContext(
                task_id=uuid4(),
                work_id=arv2_account_work_id(job_id),
                worker_id="w1",
                lease_generation=LeaseGeneration(1),
                payload={
                    "job_id": str(job_id),
                    "run_id": str(run_id),
                    "workspace_id": workspace_id,
                },
                stop_requested=asyncio.Event(),
                lease_lost=asyncio.Event(),
            )

            result = await handler.handle(context)

            assert result.outcome == "completed"
            job = await store.read_job(conn, job_id=job_id)
            assert job is not None
            assert job.status == "completed"
            assert job.finalization is not None
            assert job.finalization["reason"] == "finalized"
            assert job.finalization["summary"].startswith("Probook hires")
            assert job.finalization["claims_written"] >= 1
            assert job.finalization["profile_sha256"] == arv2_account_profile_sha256()
            assert job.model_rounds == 1 and job.tool_calls == 1

            assert await store.refresh_run_status(conn, run_id=run_id) == "completed"

            claims = await claims_for(
                conn,
                EntityId(account_id),
                scope=WorkspaceScope.for_workspace(workspace_id),
            )
            verdicts = [claim for claim in claims if claim.field_key == "account.icp_fit_verdict"]
            assert len(verdicts) == 1
            assert verdicts[0].outreach_safe is False

            activity = (
                (
                    await conn.execute(
                        text(
                            "SELECT kind, actor_kind, text, project_id FROM "
                            "account_activity_event WHERE account_entity_id = :id"
                        ),
                        {"id": account_id},
                    )
                )
                .mappings()
                .all()
            )
            assert len(activity) == 1
            assert activity[0]["kind"] == "updated"
            assert activity[0]["actor_kind"] == "clue"
            assert activity[0]["project_id"] == project.project_id
            assert "Account research finalized" in activity[0]["text"]

    run_async(scenario())


def test_the_agent_model_rounds_are_ledger_rows_and_the_job_cost_is_their_sum() -> None:
    """R2-close task 2: the loop's own model calls are spend, on the same ledger the tools use.

    The live R2 run booked ``cost_usd = 0`` on every job because the twenty-nine Grok rounds it
    spent were never written down anywhere.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id = "ws-r2-model-spend"
            project = await seed_project(conn, workspace_id, name="R2 model spend")
            project_run_id = new_project_run_id()
            await ensure_project_run(
                conn,
                project_run_id=project_run_id,
                project_id=project.project_id,
                workspace_id=workspace_id,
                icp_key="clue-abm-buyers",
                icp_version=1,
            )
            account_id = await insert_account_entity(
                conn,
                canonical_name="Probook",
                primary_domain="probook.ai",
                workspace_id=workspace_id,
            )
            storage = _MemoryStorage()
            icp_key_, icp_sha = await _register_document(
                conn,
                storage,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                path="audience/icp-clue-abm-buyers.md",
                kind="icp-definition",
                status="confirmed",
                body=ICP_MARKDOWN,
            )
            await _register_document(
                conn,
                storage,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                path="audience/persona-clue-abm-buyers.md",
                kind="audience-persona",
                status="ready",
                body=PERSONA_MARKDOWN,
            )

            run_id, job_id = uuid4(), uuid4()
            await store.create_run(
                conn,
                store.RunRow(
                    run_id=run_id,
                    workspace_id=workspace_id,
                    project_id=project.project_id,
                    brand_id=project.brand_id,
                    project_run_id=UUID(str(project_run_id)),
                    icp_artifact_key=icp_key_,
                    icp_artifact_sha256=icp_sha,
                    icp_key="clue-abm-buyers",
                    icp_version=1,
                    product_selection_version=1,
                    effort="full",
                    committee_cap=3,
                    directive_text="prioritise hiring evidence",
                    profile_ref=ARV2_ACCOUNT_PROFILE_REF,
                    profile_sha256=arv2_account_profile_sha256(),
                    requested_by_user_id="usr-r2",
                    request_sha256=hashlib.sha256(b"request-model-spend").hexdigest(),
                ),
            )
            await store.create_job(
                conn,
                job_id=job_id,
                run_id=run_id,
                workspace_id=workspace_id,
                account_entity_id=UUID(str(account_id)),
            )

            handler = Arv2AccountResearchWorkHandler(
                settings=Settings(_env_file=None),
                conn_factory=conn_session_factory(conn),
                artifacts=DurableAgentArtifactStore(
                    storage=storage,  # type: ignore[arg-type]
                    conn_factory=conn_session_factory(conn),
                ),
                storage=storage,
                clients=_Clients(),
                model_provider=_Models(_finalizing_model()),
                model_id="x-ai/grok-4.6",
                writer=LenientClaimWriter(lenient=True),
                clock=lambda: datetime(2026, 9, 8, 12, 0, tzinfo=UTC),
            )
            context = WorkContext(
                task_id=uuid4(),
                work_id=arv2_account_work_id(job_id),
                worker_id="w1",
                lease_generation=LeaseGeneration(1),
                payload={
                    "job_id": str(job_id),
                    "run_id": str(run_id),
                    "workspace_id": workspace_id,
                },
                stop_requested=asyncio.Event(),
                lease_lost=asyncio.Event(),
            )

            assert (await handler.handle(context)).outcome == "completed"

            ledger = (
                (
                    await conn.execute(
                        text(
                            "SELECT provider, operation, label, phase, outcome, cost_usd, "
                            " extras_json FROM provider_call_ledger "
                            "WHERE entity_research_job_id = :job_id AND "
                            " operation = 'agent_completion' ORDER BY recorded_at"
                        ),
                        {"job_id": job_id},
                    )
                )
                .mappings()
                .all()
            )
            assert len(ledger) == 1
            assert ledger[0]["provider"] == "openrouter"
            assert ledger[0]["label"] == "round-1"
            assert ledger[0]["phase"] == "result"
            assert ledger[0]["outcome"] == "ok"
            assert ledger[0]["cost_usd"] == Decimal("0.005000")
            assert ledger[0]["extras_json"]["cost_source"] == "metered"

            total = (
                await conn.execute(
                    text(
                        "SELECT COALESCE(SUM(cost_usd), 0) FROM provider_call_ledger "
                        "WHERE entity_research_job_id = :job_id AND phase = 'result'"
                    ),
                    {"job_id": job_id},
                )
            ).scalar_one()

            job = await store.read_job(conn, job_id=job_id)
            assert job is not None
            assert job.cost_usd == total == Decimal("0.005000")
            assert job.finalization is not None
            assert job.finalization["model_spend"]["calls"] == 1
            assert job.finalization["model_spend"]["usd"] == "0.005"
            assert job.finalization["model_spend"]["prompt_tokens"] == 1_000

    run_async(scenario())


# -- the person job (R3 task 8) -------------------------------------------------------------------


def _finalizing_person_model(seen: dict[str, Any]) -> _ScriptedModel:
    def respond(messages: list[BaseMessage]) -> AIMessage:
        seen.setdefault("prompt", "\n".join(str(message.content) for message in messages))
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "finalize_research",
                    "args": {
                        "summary": "Dana Reyes runs demand generation and speaks about pipeline.",
                        "openers": [
                            {
                                "text": "Your DevOpsDays talk on pipeline hygiene stayed with me.",
                                "hook": "the DevOpsDays talk",
                                "quote": "pipeline hygiene is a marketing problem",
                                "url": "https://devopsdays.test/talk",
                            }
                        ],
                        "hooks": ["speaks at DevOpsDays"],
                        "not_found": [],
                        "same_name_log": [],
                        "gaps": ["no podcast appearances found"],
                    },
                    "id": "call-finalize",
                    "type": "tool_call",
                }
            ],
        )

    return _ScriptedModel(respond)


async def _seed_contact_claim(
    conn: AsyncConnection,
    *,
    contact_id: EntityId,
    workspace_id: str,
    run_id: UUID,
    field_key: str,
    value: Any,
) -> None:
    """One live contact claim, written through the same gate the lane writes every claim with."""
    await LenientClaimWriter(lenient=True).write(
        conn,
        ClaimDraft(
            entity_id=contact_id,
            entity_type=EntityType.CONTACT,
            field_key=field_key,
            value_json=value,
            extraction_method=ExtractionMethod.API,
            run_id=RunId(run_id),
            research_mode=ResearchMode.CONTACT_PROFILING,
            workspace_id=workspace_id,
            source_url="https://probook.ai/team",
            source_key="ai_ark:person",
            evidence_span="Dana Reyes, VP Demand Generation",
            confidence=0.9,
            identity_binding=IdentityBinding.STRONG,
            use_class=UseClass.PROFESSIONAL_PUBLIC,
        ),
    )


def test_a_person_job_composes_against_the_real_contact_rows_and_lands_a_person_receipt() -> None:
    """The committee member's own job: its pin, its lock, its belt, its receipt."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id = "ws-r3-person-driver"
            project = await seed_project(conn, workspace_id, name="R3 person driver")
            project_run_id = new_project_run_id()
            await ensure_project_run(
                conn,
                project_run_id=project_run_id,
                project_id=project.project_id,
                workspace_id=workspace_id,
                icp_key="clue-abm-buyers",
                icp_version=1,
            )
            account_id = await insert_account_entity(
                conn,
                canonical_name="Probook",
                primary_domain="probook.ai",
                workspace_id=workspace_id,
            )
            contact_id = await insert_contact_entity(
                conn,
                account_entity_id=account_id,
                full_name="Dana Reyes",
                linkedin_url="https://www.linkedin.com/in/dana-reyes",
            )
            storage = _MemoryStorage()
            icp_key_, icp_sha = await _register_document(
                conn,
                storage,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                path="audience/icp-clue-abm-buyers.md",
                kind="icp-definition",
                status="confirmed",
                body=ICP_MARKDOWN,
            )
            await _register_document(
                conn,
                storage,
                workspace_id=workspace_id,
                brand_id=project.brand_id,
                path="audience/persona-clue-abm-buyers.md",
                kind="audience-persona",
                status="ready",
                body=PERSONA_MARKDOWN,
            )

            seen: dict[str, Any] = {}
            run_id, job_id = uuid4(), uuid4()
            await store.create_run(
                conn,
                store.RunRow(
                    run_id=run_id,
                    workspace_id=workspace_id,
                    project_id=project.project_id,
                    brand_id=project.brand_id,
                    project_run_id=UUID(str(project_run_id)),
                    icp_artifact_key=icp_key_,
                    icp_artifact_sha256=icp_sha,
                    icp_key="clue-abm-buyers",
                    icp_version=1,
                    product_selection_version=1,
                    effort="full",
                    committee_cap=3,
                    directive_text="prioritise hiring evidence",
                    profile_ref=ARV2_ACCOUNT_PROFILE_REF,
                    profile_sha256=arv2_account_profile_sha256(),
                    requested_by_user_id="usr-r3",
                    request_sha256=hashlib.sha256(b"person-request").hexdigest(),
                ),
            )
            await _seed_contact_claim(
                conn,
                contact_id=contact_id,
                workspace_id=workspace_id,
                run_id=run_id,
                field_key="contact.current_title",
                value="VP Demand Generation",
            )
            await _seed_contact_claim(
                conn,
                contact_id=contact_id,
                workspace_id=workspace_id,
                run_id=run_id,
                field_key="contact.facet.career_history",
                value=[
                    {
                        "org": "Sysdig",
                        "role": "Director of Demand Gen",
                        "start": "2021",
                        "end": "2024",
                    },
                    {"org": "Probook", "role": "VP Demand Generation", "start": "2024-04"},
                ],
            )
            assert await store.create_job(
                conn,
                job_id=job_id,
                run_id=run_id,
                workspace_id=workspace_id,
                account_entity_id=UUID(str(account_id)),
                subject_type="person",
                subject_entity_id=UUID(str(contact_id)),
                profile_sha256=arv2_person_profile_sha256(),
            )

            handler = Arv2AccountResearchWorkHandler(
                settings=Settings(_env_file=None),
                conn_factory=conn_session_factory(conn),
                artifacts=DurableAgentArtifactStore(
                    storage=storage,  # type: ignore[arg-type]
                    conn_factory=conn_session_factory(conn),
                ),
                storage=storage,
                clients=_Clients(),
                model_provider=_Models(_finalizing_person_model(seen)),
                model_id="x-ai/grok-4.6",
                person_model_id="x-ai/grok-4.6-person",
                writer=LenientClaimWriter(lenient=True),
                clock=lambda: datetime(2026, 9, 8, 12, 0, tzinfo=UTC),
            )
            context = WorkContext(
                task_id=uuid4(),
                work_id=arv2_account_work_id(job_id),
                worker_id="w1",
                lease_generation=LeaseGeneration(1),
                payload={
                    "job_id": str(job_id),
                    "run_id": str(run_id),
                    "workspace_id": workspace_id,
                },
                stop_requested=asyncio.Event(),
                lease_lost=asyncio.Event(),
            )

            result = await handler.handle(context)

            assert result.outcome == "completed"
            # The lock is built from the real rows: the contact column, the title claim and the
            # career-history claim, rendered one line per role.
            prompt = seen["prompt"]
            assert "<person_research_context>" in prompt
            assert '"title": "VP Demand Generation"' in prompt
            assert '"linkedin_url": "https://www.linkedin.com/in/dana-reyes"' in prompt
            assert "Director of Demand Gen @ Sysdig (2021–2024)" in prompt
            assert "VP Demand Generation @ Probook (2024-04–)" in prompt
            assert "## the person's own claims" in prompt

            job = await store.read_job(conn, job_id=job_id)
            assert job is not None
            assert job.status == "completed"
            assert job.finalization is not None
            assert job.finalization["reason"] == "finalized"
            assert job.finalization["openers_written"] == 1
            assert job.finalization["hooks_written"] == 1
            assert job.finalization["gaps"] == ["no podcast appearances found"]
            assert job.finalization["profile_sha256"] == arv2_person_profile_sha256()
            assert job.finalization["model_id"] == "x-ai/grok-4.6-person"

            # The finalization's claims landed on the PERSON, never on the account.
            contact_claims = await claims_for(
                conn,
                contact_id,
                scope=WorkspaceScope.for_workspace(workspace_id),
            )
            written = {claim.field_key for claim in contact_claims}
            assert "contact.facet.openers" in written and "contact.facet.hooks" in written
            account_claims = await claims_for(
                conn,
                EntityId(account_id),
                scope=WorkspaceScope.for_workspace(workspace_id),
            )
            assert account_claims == []

            activity = (
                (
                    await conn.execute(
                        text(
                            "SELECT text FROM account_activity_event WHERE account_entity_id = :id"
                        ),
                        {"id": account_id},
                    )
                )
                .mappings()
                .all()
            )
            assert len(activity) == 1
            assert "Person research finalized" in activity[0]["text"]

    run_async(scenario())
