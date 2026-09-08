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

from clue_api.arv2 import account_research_store as store
from clue_api.arv2.account_research_catalog import (
    ARV2_ACCOUNT_PROFILE_REF,
    arv2_account_profile_sha256,
)
from clue_api.arv2.account_research_driver import (
    Arv2AccountResearchWorkHandler,
    arv2_account_work_id,
)
from clue_api.arv2.claim_writer import LenientClaimWriter
from clue_config import Settings
from clue_core import EntityId, new_project_run_id
from clue_fleet.lease import LeaseGeneration
from clue_fleet.work_worker import WorkContext
from clue_research.claimstore import WorkspaceScope, claims_for
from clue_research.durable.project_run import ensure_project_run
from clue_research.identity import insert_account_entity
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


class _Artifacts:
    async def persist_body(self, *, workspace_id: str, data: bytes, media_type: str) -> Any:
        raise AssertionError("no raw body is buffered in this test")


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
                artifacts=_Artifacts(),
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
