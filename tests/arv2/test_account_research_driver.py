"""The R2 fleet driver, offline: the containment law, the pins, and the receipt it lands.

Nothing here touches a database, a provider or a model over the wire. The store is doubled (it
records the transitions in order), the three composition reads are patched at the driver's own
module names, and the model is scripted to finalize at once — so what is asserted is the driver's
own contract: **``handle`` never raises**, every failure lands the job ``needs_review`` with a
named code, and a finished job carries the receipt and the spend.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from pydantic import PrivateAttr, SecretStr

from clue_api.arv2 import account_research_driver as driver
from clue_api.arv2 import account_research_tools as tools_module
from clue_api.arv2.account_research_catalog import arv2_account_profile_sha256
from clue_api.arv2.account_research_driver import (
    ARV2_ACCOUNT_DEDUP_PREFIX,
    ARV2_ACCOUNT_TASK_PRIORITY,
    Arv2AccountResearchWorkHandler,
    arv2_account_work_id,
    build_arv2_account_research_handler,
)
from clue_api.arv2.account_research_store import JobRow, JobSpend, RunRow
from clue_api.arv2.claim_writer import ClaimDraft, WriteReceipt
from clue_api.arv2.structuring_client import FieldCatalog, FieldSpec
from clue_config import Secrets, Settings
from clue_core import ClaimId
from clue_fleet import FleetTaskKind
from clue_fleet.lease import LeaseGeneration
from clue_fleet.work_worker import WorkContext

WORKSPACE = "ws-r2-driver"
ICP_SHA = "d" * 64
ICP_BODY = b"---\nkind: icp-definition\nicp_key: clue-abm-buyers\n---\n\n# ICP\nSeries A SaaS.\n"
PERSONA_BODY = (
    b"---\nkind: audience-persona\nicp_key: clue-abm-buyers\n---\n\n# Personas\nVP Marketing.\n"
)


def _run_row(*, profile_sha256: str | None = None) -> RunRow:
    return RunRow(
        run_id=uuid4(),
        workspace_id=WORKSPACE,
        project_id="prj-1",
        brand_id="brd-1",
        project_run_id=uuid4(),
        icp_artifact_key=f"{WORKSPACE}/icp",
        icp_artifact_sha256=ICP_SHA,
        icp_key="clue-abm-buyers",
        icp_version=1,
        product_selection_version=1,
        effort="full",
        committee_cap=4,
        directive_text="focus on hiring signals",
        profile_ref="agent-profile:arv2-account:v1",
        profile_sha256=profile_sha256 or arv2_account_profile_sha256(),
        requested_by_user_id="usr-1",
        request_sha256="c" * 64,
        status="in_progress",
    )


def _job_row(run: RunRow) -> JobRow:
    return JobRow(
        job_id=uuid4(),
        run_id=run.run_id,
        workspace_id=run.workspace_id,
        account_entity_id=uuid4(),
        status="in_progress",
        attempt=1,
        started_at=datetime(2026, 9, 8, tzinfo=UTC),
        finished_at=None,
        finalization=None,
        failure_code=None,
        failure_message=None,
        model_rounds=0,
        tool_calls=0,
        cost_usd=Decimal(0),
        credits=Decimal(0),
        media_seconds=0,
    )


class FakeStore:
    """The store's transitions, recorded in order, with no SQL behind them."""

    def __init__(self, run: RunRow, job: JobRow | None) -> None:
        self.run = run
        self.job = job
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def begin_job(self, conn: Any, *, job_id: UUID) -> JobRow | None:
        del conn
        self.events.append(("begin_job", {"job_id": job_id}))
        return self.job

    async def read_run(self, conn: Any, *, run_id: UUID) -> RunRow | None:
        del conn
        self.events.append(("read_run", {"run_id": run_id}))
        return self.run if run_id == self.run.run_id else None

    async def suspend_job(self, conn: Any, *, job_id: UUID) -> None:
        del conn
        self.events.append(("suspend_job", {"job_id": job_id}))

    async def finish_job(self, conn: Any, **kwargs: Any) -> None:
        del conn
        self.events.append(("finish_job", kwargs))

    async def refresh_run_status(self, conn: Any, *, run_id: UUID) -> str:
        del conn
        self.events.append(("refresh_run_status", {"run_id": run_id}))
        return "completed"

    async def read_persona_documents(
        self, conn: Any, *, workspace_id: str, brand_id: str
    ) -> tuple[Any, ...]:
        del conn
        self.events.append(("read_persona_documents", {"brand_id": brand_id}))
        return (
            SimpleNamespace(
                document_id=uuid4(),
                folder="audience",
                path="audience/persona-clue-abm-buyers.md",
                kind="audience-persona",
                version=1,
                status="ready",
                artifact_key=f"{workspace_id}/persona",
                artifact_sha256="e" * 64,
            ),
        )

    async def read_account_catalog(self, conn: Any) -> FieldCatalog:
        del conn
        self.events.append(("read_account_catalog", {}))
        return FieldCatalog(account=(FieldSpec("core.industry", "Industry."),))

    async def job_spend(self, conn: Any, *, job_id: UUID) -> JobSpend:
        del conn
        self.events.append(("job_spend", {"job_id": job_id}))
        return JobSpend(cost_usd=Decimal("2.50"), credits=Decimal("3.000"), media_seconds=120)

    async def job_link_audit(self, conn: Any, *, job_id: UUID) -> dict[str, int]:
        del conn
        self.events.append(("job_link_audit", {"job_id": job_id}))
        return {"EXACT": 3, "PARTIAL": 1, "NOT_FOUND": 0}

    def named(self, name: str) -> list[dict[str, Any]]:
        return [payload for event, payload in self.events if event == name]


class FakeConn:
    """A connection that records the one statement the driver writes itself."""

    def __init__(self) -> None:
        self.statements: list[tuple[str, Any]] = []

    async def execute(self, statement: Any, parameters: Any = None) -> Any:
        self.statements.append((str(statement), parameters))
        return SimpleNamespace(scalar_one=lambda: "completed")


class FakeConnFactory:
    def __init__(self) -> None:
        self.conn = FakeConn()
        self.opened = 0

    def __call__(self) -> Any:
        return self._open()

    @asynccontextmanager
    async def _open(self) -> AsyncIterator[Any]:
        self.opened += 1
        yield self.conn


class FakeWriter:
    def __init__(self) -> None:
        self.drafts: list[ClaimDraft] = []

    async def write(self, conn: Any, draft: ClaimDraft) -> WriteReceipt:
        del conn
        self.drafts.append(draft)
        return WriteReceipt(
            claim_id=ClaimId(uuid4()),
            field_key=draft.field_key,
            markers=dict(draft.markers),
            registered_field=False,
        )


class FakeArtifacts:
    async def persist_body(self, *, workspace_id: str, data: bytes, media_type: str) -> Any:
        raise AssertionError("no provider hop runs in the offline driver tests")


class FakeClients:
    def exa(self, caller: Any) -> Any:
        raise AssertionError("no provider is reached offline")

    def ai_ark(self, caller: Any) -> Any:
        raise AssertionError("no provider is reached offline")

    def media(self, caller: Any, ledger: Any) -> Any:
        raise AssertionError("no provider is reached offline")

    def structuring(self, caller: Any) -> Any:
        raise AssertionError("no provider is reached offline")


class _ScriptedModel(BaseChatModel):
    _respond: Callable[[list[BaseMessage]], AIMessage] = PrivateAttr()

    def __init__(self, respond: Callable[[list[BaseMessage]], AIMessage]) -> None:
        super().__init__()
        self._respond = respond

    @property
    def _llm_type(self) -> str:
        return "arv2-account-driver-scripted"

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


def _finalizes_at_once() -> _ScriptedModel:
    def respond(messages: list[BaseMessage]) -> AIMessage:
        del messages
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "finalize_research",
                    "args": {
                        "summary": "Probook is a strong fit on hiring and tooling evidence.",
                        "fit_verdicts": [
                            {
                                "gate": "series-a-saas",
                                "verdict": "likely",
                                "rationale": "Two GTM requisitions open.",
                                "claim_ids": [],
                            }
                        ],
                        "gaps": ["no revenue disclosure"],
                        "committee_candidates": [],
                    },
                    "id": "call-finalize",
                    "type": "tool_call",
                }
            ],
        )

    return _ScriptedModel(respond)


class FakeModels:
    def __init__(self, model: BaseChatModel) -> None:
        self.model = model
        self.builds: list[dict[str, Any]] = []

    def build(self, **kwargs: Any) -> BaseChatModel:
        self.builds.append(kwargs)
        return self.model


def _patch_reads(
    monkeypatch: pytest.MonkeyPatch, *, icp_sha: str = ICP_SHA, account: Any | None = None
) -> None:
    """Patch the three composition reads the driver makes through other packages."""

    async def fake_get_account(conn: Any, entity_id: Any) -> Any:
        del conn, entity_id
        return account

    async def fake_read_verified_artifact(
        conn: Any, storage: Any, *, storage_key: str, workspace_id: str
    ) -> tuple[Any, bytes]:
        del conn, storage, workspace_id
        if storage_key.endswith("persona"):
            return SimpleNamespace(content_sha256="e" * 64), PERSONA_BODY
        return SimpleNamespace(content_sha256=icp_sha), ICP_BODY

    async def fake_claims_for(conn: Any, entity_id: Any, *, scope: Any) -> Sequence[Any]:
        del conn, entity_id, scope
        return ()

    async def fake_claims_for_runs(conn: Any, run_ids: Any, *, scope: Any) -> Sequence[Any]:
        del conn, run_ids, scope
        return ()

    monkeypatch.setattr(driver, "get_account", fake_get_account)
    monkeypatch.setattr(driver, "read_verified_artifact", fake_read_verified_artifact)
    monkeypatch.setattr(driver, "claims_for", fake_claims_for)
    monkeypatch.setattr(tools_module, "claims_for_runs", fake_claims_for_runs)


def _handler(
    store: FakeStore, *, model: BaseChatModel | None = None
) -> tuple[Arv2AccountResearchWorkHandler, FakeConnFactory, FakeWriter, FakeModels]:
    conn_factory = FakeConnFactory()
    writer = FakeWriter()
    models = FakeModels(model or _finalizes_at_once())
    handler = Arv2AccountResearchWorkHandler(
        settings=Settings(_env_file=None),
        conn_factory=conn_factory,
        artifacts=FakeArtifacts(),
        storage=object(),
        clients=FakeClients(),
        model_provider=models,
        model_id="x-ai/grok-4.6",
        writer=writer,
        store=store,
        clock=lambda: datetime(2026, 9, 8, 12, 0, tzinfo=UTC),
    )
    return handler, conn_factory, writer, models


def _context(job: JobRow, *, work_id: UUID | None = None) -> WorkContext:
    return WorkContext(
        task_id=uuid4(),
        work_id=arv2_account_work_id(work_id or job.job_id),
        worker_id="w1",
        lease_generation=LeaseGeneration(1),
        payload={
            "job_id": str(job.job_id),
            "run_id": str(job.run_id),
            "workspace_id": job.workspace_id,
        },
        stop_requested=asyncio.Event(),
        lease_lost=asyncio.Event(),
    )


def test_handle_marks_job_completed_with_a_receipt_and_never_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row()
    job = _job_row(run)
    store = FakeStore(run, job)
    _patch_reads(
        monkeypatch, account=SimpleNamespace(canonical_name="Probook", primary_domain="probook.ai")
    )
    handler, conn_factory, writer, models = _handler(store)

    result = asyncio.run(handler.handle(_context(job)))

    assert handler.kind is FleetTaskKind.ARV2_ACCOUNT_RESEARCH
    assert result.outcome == "completed"
    assert result.references == {"job_id": str(job.job_id), "run_id": str(run.run_id)}
    assert result.requeue is False

    finished = store.named("finish_job")
    assert len(finished) == 1
    landed = finished[0]
    assert landed["status"] == "completed"
    assert landed["failure_code"] is None
    assert landed["cost_usd"] == Decimal("2.50")
    assert landed["credits"] == Decimal("3.000")
    assert landed["media_seconds"] == 120
    assert landed["model_rounds"] == 1
    assert landed["tool_calls"] == 1

    receipt = landed["finalization"]
    assert receipt["reason"] == "finalized"
    assert receipt["summary"].startswith("Probook is a strong fit")
    assert receipt["fit_verdicts"][0]["gate"] == "series-a-saas"
    assert receipt["gaps"] == ["no revenue disclosure"]
    assert receipt["claims_written"] == 0
    assert receipt["by_field"] == {}
    assert receipt["proposed_fields"] == []
    assert receipt["link_audit"] == {"EXACT": 3, "PARTIAL": 1, "NOT_FOUND": 0}
    assert receipt["halted_providers"] == {}
    assert receipt["profile_sha256"] == arv2_account_profile_sha256()
    assert len(receipt["manifest_sha256"]) == 64
    assert receipt["model_id"] == "x-ai/grok-4.6"

    assert store.named("refresh_run_status")
    # The model is built through the gateway boundary, with the ARV2 role so its effort env applies.
    assert models.builds[0]["role"] == "arv2_account"
    assert models.builds[0]["model_id"] == "x-ai/grok-4.6"
    # The fit verdict the model finalized on was written through the injected claim gate.
    assert [draft.field_key for draft in writer.drafts] == ["account.icp_fit_verdict"]
    # Exactly one activity row, authored by Clue, hung under the run's project.
    activity = [
        params
        for statement, params in conn_factory.conn.statements
        if "account_activity_event" in statement
    ]
    assert len(activity) == 1
    assert activity[0]["project_id"] == run.project_id
    assert activity[0]["text"] == "Account research finalized: 0 claims"


def test_handle_contains_a_composition_failure_as_needs_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row()
    job = _job_row(run)
    store = FakeStore(run, job)
    _patch_reads(
        monkeypatch,
        icp_sha="f" * 64,  # the artifact on disk is not the one the launch signed off on
        account=SimpleNamespace(canonical_name="Probook", primary_domain="probook.ai"),
    )
    handler, _, _, _ = _handler(store)

    result = asyncio.run(handler.handle(_context(job)))

    assert result.outcome == "needs_review"
    landed = store.named("finish_job")[0]
    assert landed["status"] == "needs_review"
    assert landed["failure_code"] == "ArtifactIntegrityError"
    assert "digest" in landed["failure_message"]
    assert store.named("refresh_run_status")


def test_a_missing_account_row_is_contained_as_needs_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row()
    job = _job_row(run)
    store = FakeStore(run, job)
    _patch_reads(monkeypatch, account=None)
    handler, _, _, _ = _handler(store)

    result = asyncio.run(handler.handle(_context(job)))

    assert result.outcome == "needs_review"
    assert store.named("finish_job")[0]["failure_code"] == "RuntimeError"


def test_a_profile_digest_that_moved_since_the_launch_refuses_the_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row(profile_sha256="a" * 64)
    job = _job_row(run)
    store = FakeStore(run, job)
    _patch_reads(
        monkeypatch, account=SimpleNamespace(canonical_name="Probook", primary_domain="probook.ai")
    )
    handler, _, _, _ = _handler(store)

    result = asyncio.run(handler.handle(_context(job)))

    assert result.outcome == "needs_review"
    landed = store.named("finish_job")[0]
    assert landed["failure_code"] == "profile_pin_mismatch"


def test_stop_requested_requeues_as_suspended(monkeypatch: pytest.MonkeyPatch) -> None:
    run = _run_row()
    job = _job_row(run)
    store = FakeStore(run, job)
    _patch_reads(
        monkeypatch, account=SimpleNamespace(canonical_name="Probook", primary_domain="probook.ai")
    )
    handler, _, _, _ = _handler(store)
    context = _context(job)
    context.stop_requested.set()

    result = asyncio.run(handler.handle(context))

    assert result.outcome == "stopped"
    assert result.requeue is True
    assert store.named("suspend_job") == [{"job_id": job.job_id}]
    assert not store.named("begin_job"), "a stopped task never starts the agent"


def test_payload_work_id_mismatch_is_a_needs_review_not_a_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row()
    job = _job_row(run)
    store = FakeStore(run, job)
    _patch_reads(
        monkeypatch, account=SimpleNamespace(canonical_name="Probook", primary_domain="probook.ai")
    )
    handler, _, _, _ = _handler(store)

    result = asyncio.run(handler.handle(_context(job, work_id=uuid4())))

    assert result.outcome == "needs_review"
    landed = store.named("finish_job")[0]
    assert landed["status"] == "needs_review"
    assert landed["failure_code"] == "invalid_task_payload"
    assert not store.named("begin_job")


def test_an_unreadable_payload_is_contained_without_a_raise() -> None:
    run = _run_row()
    job = _job_row(run)
    store = FakeStore(run, job)
    handler, _, _, _ = _handler(store)
    context = WorkContext(
        task_id=uuid4(),
        work_id=arv2_account_work_id(job.job_id),
        worker_id="w1",
        lease_generation=LeaseGeneration(1),
        payload={"job_id": "not-a-uuid"},
        stop_requested=asyncio.Event(),
        lease_lost=asyncio.Event(),
    )

    result = asyncio.run(handler.handle(context))

    assert result.outcome == "failed"
    assert store.events == []


def test_a_redelivered_terminal_job_completes_idempotently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row()
    job = _job_row(run)
    store = FakeStore(run, None)  # begin_job refuses: the job is not this worker's to run
    _patch_reads(
        monkeypatch, account=SimpleNamespace(canonical_name="Probook", primary_domain="probook.ai")
    )
    handler, _, _, _ = _handler(store)

    result = asyncio.run(handler.handle(_context(job)))

    assert result.outcome == "completed"
    assert not store.named("finish_job"), "a redelivery never re-finishes a job"


def test_the_model_error_outcome_lands_needs_review_with_its_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row()
    job = _job_row(run)
    store = FakeStore(run, job)
    _patch_reads(
        monkeypatch, account=SimpleNamespace(canonical_name="Probook", primary_domain="probook.ai")
    )

    def explode(messages: list[BaseMessage]) -> AIMessage:
        del messages
        raise RuntimeError("the provider hung up")

    handler, _, _, _ = _handler(store, model=_ScriptedModel(explode))

    result = asyncio.run(handler.handle(_context(job)))

    assert result.outcome == "needs_review"
    landed = store.named("finish_job")[0]
    assert landed["failure_code"] == "model_error"
    assert "RuntimeError" in landed["failure_message"]
    assert landed["finalization"]["reason"] == "model_error"


def test_the_enqueue_constants_are_the_ones_the_launcher_will_use() -> None:
    assert ARV2_ACCOUNT_DEDUP_PREFIX == "arv2-account-research:"
    assert ARV2_ACCOUNT_TASK_PRIORITY == -100
    job_id = uuid4()
    assert UUID(str(arv2_account_work_id(job_id))) == job_id


def test_the_system_prompt_carries_the_pinned_resources_and_the_job_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row()
    job = _job_row(run)
    store = FakeStore(run, job)
    _patch_reads(
        monkeypatch, account=SimpleNamespace(canonical_name="Probook", primary_domain="probook.ai")
    )
    seen: dict[str, Any] = {}

    def respond(messages: list[BaseMessage]) -> AIMessage:
        seen.setdefault("messages", list(messages))
        return AIMessage(content="nothing to do")

    handler, _, _, _ = _handler(store, model=_ScriptedModel(respond))

    asyncio.run(handler.handle(_context(job)))

    prompt = "\n".join(str(message.content) for message in seen["messages"])
    assert "agent-profile:arv2-account:v1" in prompt
    assert "Series A SaaS." in prompt, "the ICP body reaches the model"
    assert "VP Marketing." in prompt, "the persona document reaches the model"
    assert "core.industry" in prompt, "the field catalog menu reaches the model"
    assert "focus on hiring signals" in prompt, "the launch directive reaches the model"
    assert json.loads(json.dumps(store.named("read_account_catalog"))) == [{}]


def test_a_payload_naming_another_run_is_refused_before_any_model_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row()
    job = _job_row(run)
    store = FakeStore(run, job)
    _patch_reads(
        monkeypatch, account=SimpleNamespace(canonical_name="Probook", primary_domain="probook.ai")
    )
    handler, _, _, models = _handler(store)
    context = _context(job)
    context.payload["run_id"] = str(uuid4())

    result = asyncio.run(handler.handle(context))

    assert result.outcome == "needs_review"
    assert store.named("finish_job")[0]["failure_code"] == "invalid_task_payload"
    assert models.builds == [], "no model is built for a job whose run was not named"


def _live_secrets() -> Secrets:
    return Secrets(
        _env_file=None,
        exa_api_key=SecretStr("exa"),
        openrouter_api_key=SecretStr("or"),
        ai_ark_api_key=SecretStr("ark"),
        gemini_api_key=SecretStr("gem"),
    )


def test_the_builder_composes_nothing_while_the_lane_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARV2_ACCOUNT_AGENT_MODEL", "x-ai/grok-4.6")

    handler = build_arv2_account_research_handler(
        Settings(_env_file=None, arv2_account_research_enabled=False),
        _live_secrets(),
        storage=object(),  # type: ignore[arg-type]
        artifacts=FakeArtifacts(),
        model_provider=FakeModels(_finalizes_at_once()),
    )

    assert handler is None


@pytest.mark.parametrize(
    ("missing_key", "model_id"),
    [
        ("exa_api_key", "x-ai/grok-4.6"),
        ("openrouter_api_key", "x-ai/grok-4.6"),
        ("ai_ark_api_key", "x-ai/grok-4.6"),
        ("gemini_api_key", "x-ai/grok-4.6"),
        (None, ""),  # a blank env line is unset, never an empty model id
    ],
)
def test_the_builder_refuses_and_composes_nothing_when_configuration_is_missing(
    monkeypatch: pytest.MonkeyPatch, missing_key: str | None, model_id: str
) -> None:
    monkeypatch.setenv("ARV2_ACCOUNT_AGENT_MODEL", model_id)
    fields = {
        "exa_api_key": SecretStr("exa"),
        "openrouter_api_key": SecretStr("or"),
        "ai_ark_api_key": SecretStr("ark"),
        "gemini_api_key": SecretStr("gem"),
    }
    if missing_key is not None:
        fields[missing_key] = SecretStr("   ")  # blank is unset

    handler = build_arv2_account_research_handler(
        Settings(_env_file=None, arv2_account_research_enabled=True),
        Secrets(_env_file=None, **fields),
        storage=object(),  # type: ignore[arg-type]
        artifacts=FakeArtifacts(),
        model_provider=FakeModels(_finalizes_at_once()),
    )

    assert handler is None


def test_the_builder_composes_the_lane_when_everything_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARV2_ACCOUNT_AGENT_MODEL", "x-ai/grok-4.6")

    artifacts, models = FakeArtifacts(), FakeModels(_finalizes_at_once())

    handler = build_arv2_account_research_handler(
        Settings(_env_file=None, arv2_account_research_enabled=True),
        _live_secrets(),
        storage=object(),  # type: ignore[arg-type]
        artifacts=artifacts,
        model_provider=models,
    )

    assert handler is not None
    assert handler.kind is FleetTaskKind.ARV2_ACCOUNT_RESEARCH
    # The sink and the model provider are the caller's objects: the lane composes neither a second
    # artifact write path nor its own gateway client.
    assert handler._artifacts is artifacts  # noqa: SLF001 — the injection is the assertion
    assert handler._models is models  # noqa: SLF001
