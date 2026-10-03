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
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
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
from clue_api.arv2.account_research_catalog import (
    arv2_account_profile_sha256,
    arv2_person_profile_sha256,
)
from clue_api.arv2.account_research_driver import (
    ARV2_ACCOUNT_DEDUP_PREFIX,
    ARV2_ACCOUNT_TASK_PRIORITY,
    ARV2_PERSON_MODEL_ENV,
    Arv2AccountResearchWorkHandler,
    arv2_account_work_id,
    build_arv2_account_research_handler,
    employment_history_lines,
    format_established,
)
from clue_api.arv2.account_research_launch import QueuedJob
from clue_api.arv2.account_research_store import JobRow, JobSpend, RunRow
from clue_api.arv2.account_research_tools import PERSON_TOOL_NAMES
from clue_api.arv2.claim_writer import ClaimDraft, WriteReceipt
from clue_api.arv2.fleet_task import (
    ARV2_DISPLAY_DEDUP_PREFIX,
    ARV2_DISPLAY_TASK_PRIORITY,
    arv2_display_work_id,
)
from clue_api.arv2.provider_ledger import ledger_id_for
from clue_api.arv2.structuring_client import FieldCatalog, FieldSpec
from clue_config import Secrets, Settings
from clue_core import (
    Claim,
    ClaimId,
    EntityId,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    ResearchMode,
    ReuseScope,
    RunId,
    UseClass,
)
from clue_fleet import FleetTaskKind
from clue_fleet.lease import LeaseGeneration
from clue_fleet.work_worker import WorkContext

WORKSPACE = "ws-r2-driver"
ICP_SHA = "d" * 64
ICP_BODY = b"---\nkind: icp-definition\nicp_key: clue-abm-buyers\n---\n\n# ICP\nSeries A SaaS.\n"
#: The same ICP with the hard gates a real synthesized ICP carries — the keys every fit verdict is
#: keyed to.
GATED_ICP_BODY = (
    b"---\n"
    b"kind: icp-definition\n"
    b"icp_key: clue-abm-buyers\n"
    b"hard_gates:\n"
    b"  - {key: series-a-saas, rule: Series A or later SaaS, test: funding wire}\n"
    b"  - {key: us-hq, rule: US headquarters, test: the about page}\n"
    b"---\n\n# ICP\nSeries A SaaS.\n"
)
PERSONA_BODY = (
    b"---\nkind: audience-persona\nicp_key: clue-abm-buyers\n---\n\n# Personas\nVP Marketing.\n"
)


@pytest.fixture(autouse=True)
def measured_failure_spend(monkeypatch):
    """The driver double has no SQL; the real ledger join is covered by quality_driver_db."""
    from clue_api.arv2 import quality_meter

    async def usage(conn, *, workspace_id, job_id):
        return quality_meter.QualityUsage(Decimal("2.50"), Decimal("3"), 120, 1, 0, 2, 3, 100)

    monkeypatch.setattr(quality_meter, "usage", usage)


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


def _job_row(run: RunRow, *, attempt: int = 1) -> JobRow:
    return JobRow(
        job_id=uuid4(),
        run_id=run.run_id,
        workspace_id=run.workspace_id,
        account_entity_id=uuid4(),
        subject_type="account",
        subject_entity_id=None,
        profile_sha256=run.profile_sha256,
        status="in_progress",
        attempt=attempt,
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


#: "the row the driver would read back is the one ``begin_job`` was given" — the ordinary case.
_SAME_ROW = object()


class FakeStore:
    """The store's transitions, recorded in order, with no SQL behind them."""

    def __init__(self, run: RunRow, job: JobRow | None, row: Any = _SAME_ROW) -> None:
        self.run = run
        self.job = job
        #: What ``read_job`` answers. It is a separate fact from what ``begin_job`` claims: a job
        #: that exists but is not claimable is an ordinary redelivery, while a job with NO row is
        #: a task that outran its launch.
        self.row: JobRow | None = job if row is _SAME_ROW else row
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def begin_job(self, conn: Any, *, job_id: UUID) -> JobRow | None:
        del conn
        self.events.append(("begin_job", {"job_id": job_id}))
        return self.job

    async def read_job(self, conn: Any, *, job_id: UUID) -> JobRow | None:
        del conn
        self.events.append(("read_job", {"job_id": job_id}))
        return self.row

    async def read_run(self, conn: Any, *, run_id: UUID) -> RunRow | None:
        del conn
        self.events.append(("read_run", {"run_id": run_id}))
        return self.run if run_id == self.run.run_id else None

    async def suspend_job(self, conn: Any, *, job_id: UUID) -> None:
        del conn
        self.events.append(("suspend_job", {"job_id": job_id}))

    async def set_job_stage(self, conn: Any, *, job_id: UUID, stage: str) -> None:
        del conn
        self.events.append(("set_job_stage", {"job_id": job_id, "stage": stage}))

    async def finish_job(self, conn: Any, **kwargs: Any) -> None:
        del conn
        self.events.append(("finish_job", kwargs))

    async def refresh_run_status(self, conn: Any, *, run_id: UUID) -> str:
        del conn
        self.events.append(("refresh_run_status", {"run_id": run_id}))
        return "completed"

    async def read_persona_documents(
        self, conn: Any, *, workspace_id: str, brand_id: str, project_id: str
    ) -> tuple[Any, ...]:
        del conn
        self.events.append(
            ("read_persona_documents", {"brand_id": brand_id, "project_id": project_id})
        )
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

    async def read_account_catalog(self, conn: Any, *, workspace_id: str) -> FieldCatalog:
        del conn
        self.events.append(("read_account_catalog", {}))
        return FieldCatalog(account=(FieldSpec("core.industry", "Industry."),))

    async def read_person_catalog(self, conn: Any, *, workspace_id: str) -> FieldCatalog:
        del conn
        self.events.append(("read_person_catalog", {}))
        return FieldCatalog(
            contact=(FieldSpec("contact.current_title", "Current title."),),
            facet=(FieldSpec("contact.facet.personal_hook", "A personal hook."),),
        )

    async def job_spend(self, conn: Any, *, job_id: UUID) -> JobSpend:
        del conn
        self.events.append(("job_spend", {"job_id": job_id}))
        return JobSpend(cost_usd=Decimal("2.50"), credits=Decimal("3.000"), media_seconds=120)

    async def job_link_audit(self, conn: Any, *, job_id: UUID) -> dict[str, int]:
        del conn
        self.events.append(("job_link_audit", {"job_id": job_id}))
        return {"EXACT/on_page": 3, "PARTIAL/partial_on_page": 1, "NOT_FOUND/not_on_page": 2}

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
    monkeypatch: pytest.MonkeyPatch,
    *,
    icp_sha: str = ICP_SHA,
    account: Any | None = None,
    icp_body: bytes = ICP_BODY,
    contact: Any | None = None,
    claims: Mapping[str, Sequence[Any]] | None = None,
) -> None:
    """Patch the four composition reads the driver makes through other packages."""

    async def fake_get_account(conn: Any, entity_id: Any) -> Any:
        del conn, entity_id
        return account

    async def fake_get_contact(conn: Any, entity_id: Any) -> Any:
        del conn, entity_id
        return contact

    async def fake_read_verified_artifact(
        conn: Any, storage: Any, *, storage_key: str, workspace_id: str
    ) -> tuple[Any, bytes]:
        del conn, storage, workspace_id
        if storage_key.endswith("persona"):
            return SimpleNamespace(content_sha256="e" * 64), PERSONA_BODY
        return SimpleNamespace(content_sha256=icp_sha), icp_body

    async def fake_claims_for(conn: Any, entity_id: Any, *, scope: Any) -> Sequence[Any]:
        del conn, scope
        return (claims or {}).get(str(entity_id), ())

    async def fake_claims_for_runs(conn: Any, run_ids: Any, *, scope: Any) -> Sequence[Any]:
        del conn, run_ids, scope
        return ()

    monkeypatch.setattr(driver, "get_account", fake_get_account)
    monkeypatch.setattr(driver, "get_contact", fake_get_contact)
    monkeypatch.setattr(driver, "read_verified_artifact", fake_read_verified_artifact)
    monkeypatch.setattr(driver, "claims_for", fake_claims_for)
    monkeypatch.setattr(tools_module, "claims_for_runs", fake_claims_for_runs)


def _handler(
    store: FakeStore,
    *,
    model: BaseChatModel | None = None,
    queue: Any | None = None,
    person_model_id: str = "x-ai/grok-4.6-person",
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
        person_model_id=person_model_id,
        writer=writer,
        queue=queue,
        store=store,
        clock=lambda: datetime(2026, 9, 8, 12, 0, tzinfo=UTC),
    )
    return handler, conn_factory, writer, models


def _context(job: JobRow, *, work_id: UUID | None = None, task_attempt: int = 1) -> WorkContext:
    return WorkContext(
        task_id=uuid4(),
        work_id=arv2_account_work_id(work_id or job.job_id),
        worker_id="w1",
        task_attempt=task_attempt,
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
    # The audit reaches the receipt keyed by *reason*, so a reader of the terminal row learns
    # whether the job's misses were dead links, empty pages or quotes off the wrong page.
    assert receipt["link_audit"] == {
        "EXACT/on_page": 3,
        "NOT_FOUND/not_on_page": 2,
        "PARTIAL/partial_on_page": 1,
    }
    assert receipt["halted_providers"] == {}
    assert receipt["profile_sha256"] == arv2_account_profile_sha256()
    assert len(receipt["manifest_sha256"]) == 64
    assert receipt["model_id"] == "x-ai/grok-4.6"

    assert store.named("refresh_run_status")
    # The stage stamps: the claim opens ``deep_research``, the settle stamps ``committee`` before
    # the fan-out — and stops there, because this finalization named no candidates, so no person
    # job was ever born for ``member_research`` to describe.
    stamps = [payload["stage"] for event, payload in store.events if event == "set_job_stage"]
    assert stamps == ["deep_research", "committee"]
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
    assert landed["cost_usd"] == Decimal("2.50")
    assert landed["finalization"]["spend"]["unpriced_provider_calls"] == 1
    assert not landed["finalization"]["spend"]["cost_complete"]
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
    # begin_job refuses (the job is not this worker's to run), but the row is there.
    store = FakeStore(run, None, row=job)
    _patch_reads(
        monkeypatch, account=SimpleNamespace(canonical_name="Probook", primary_domain="probook.ai")
    )
    handler, _, _, _ = _handler(store)

    result = asyncio.run(handler.handle(_context(job)))

    assert result.outcome == "completed"
    assert not store.named("finish_job"), "a redelivery never re-finishes a job"


def test_a_task_whose_job_row_is_not_there_yet_is_requeued_rather_than_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The C1 defence: "no row" is NOT "already finished".

    A task that reached a worker before its launch committed would otherwise be finished as done
    while the job row lands ``not_started`` a moment later — no error, no ``needs_review``, and no
    second offer ever, because the dedup key is terminal. So the task waits instead.
    """
    run = _run_row()
    job = _job_row(run)
    store = FakeStore(run, None, row=None)  # nothing claimable, and nothing there at all
    _patch_reads(
        monkeypatch, account=SimpleNamespace(canonical_name="Probook", primary_domain="probook.ai")
    )
    handler, _, _, _ = _handler(store)

    result = asyncio.run(handler.handle(_context(job)))

    assert result.outcome == "job_row_not_visible"
    assert result.requeue is True
    assert result.requeue_after == timedelta(seconds=5)
    assert result.references["job_id"] == str(job.job_id)
    assert store.named("read_job") == [{"job_id": job.job_id}]
    assert not store.named("finish_job"), "there is no row to flag"


def test_a_job_row_that_never_appears_stops_waiting_and_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A genuinely rolled-back launch must not requeue forever."""
    run = _run_row()
    job = _job_row(run)
    store = FakeStore(run, None, row=None)
    _patch_reads(
        monkeypatch, account=SimpleNamespace(canonical_name="Probook", primary_domain="probook.ai")
    )
    handler, _, _, _ = _handler(store)

    result = asyncio.run(handler.handle(_context(job, task_attempt=13)))

    assert result.outcome == "failed" and result.requeue is False
    assert not store.named("finish_job")


def test_a_cancelled_handle_suspends_the_job_before_the_cancellation_propagates() -> None:
    """I1: the fleet CANCELS the handler on lease loss, and ``CancelledError`` is a BaseException.

    Without the explicit clause the job would stay ``in_progress`` forever: the redelivery cannot
    claim it, reads as a finished job, and the task is marked done.
    """
    run = _run_row()
    job = _job_row(run)
    store = FakeStore(run, job)
    handler, _, _, _ = _handler(store)
    started = asyncio.Event()

    async def hang(scope: Any, *, task_attempt: int) -> str:
        del scope, task_attempt
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    handler._run = hang  # type: ignore[method-assign]  # the agent is not what is under test

    async def scenario() -> None:
        task = asyncio.create_task(handler.handle(_context(job)))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    assert store.named("suspend_job") == [{"job_id": job.job_id}], (
        "a lease-lost job must be parked, or nothing can ever claim it again"
    )


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


class _Denied(Exception):
    """A refusal shaped the way the OpenAI-compatible SDKs raise one: a status and a repr body."""

    status_code = 403

    def __init__(self) -> None:
        super().__init__(
            "Error code: 403 - {'error': {'message': 'Key limit exceeded (weekly limit)',"
            " 'code': 403}}"
        )


def test_a_job_the_provider_refused_records_the_reason_rather_than_the_bare_model_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A key that hit its cap is not "the model errored" — the job row says which provider stopped
    serving and why, so the reviewer reads a cause instead of a shrug."""

    run = _run_row()
    job = _job_row(run)
    store = FakeStore(run, job)
    _patch_reads(
        monkeypatch, account=SimpleNamespace(canonical_name="Probook", primary_domain="probook.ai")
    )

    def refuse(messages: list[BaseMessage]) -> AIMessage:
        del messages
        raise _Denied()

    handler, _, _, _ = _handler(store, model=_ScriptedModel(refuse))

    result = asyncio.run(handler.handle(_context(job)))

    assert result.outcome == "needs_review"
    landed = store.named("finish_job")[0]
    assert landed["status"] == "needs_review"
    assert landed["failure_code"] == "provider_refused:openrouter:key_limit"


def test_the_icp_hard_gates_key_the_receipt_and_an_unassessed_gate_is_filled_unclear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The driver reads the pinned ICP's ``hard_gates`` keys and the tool keys the verdicts to them.

    The scripted model answers on ``series-a-saas`` only; ``us-hq`` is the ICP's other gate, so the
    receipt carries it as ``unclear`` rather than leaving a reviewer to wonder whether the gate was
    checked and passed or never looked at.
    """
    run = _run_row()
    job = _job_row(run)
    store = FakeStore(run, job)
    _patch_reads(
        monkeypatch,
        account=SimpleNamespace(canonical_name="Probook", primary_domain="probook.ai"),
        icp_body=GATED_ICP_BODY,
    )
    handler, _, writer, _ = _handler(store)

    result = asyncio.run(handler.handle(_context(job)))

    assert result.outcome == "completed"
    verdicts = store.named("finish_job")[0]["finalization"]["fit_verdicts"]
    assert [verdict["gate"] for verdict in verdicts] == ["series-a-saas", "us-hq"]
    assert verdicts[1]["verdict"] == "unclear" and verdicts[1]["rationale"] == "not assessed"
    assert [draft.markers.get("filled_by_tool") for draft in writer.drafts] == [None, True]


def test_the_enqueue_constants_are_the_ones_the_launcher_will_use() -> None:
    assert ARV2_ACCOUNT_DEDUP_PREFIX == "arv2-account-research:"
    assert ARV2_ACCOUNT_TASK_PRIORITY == -100
    job_id = uuid4()
    assert UUID(str(arv2_account_work_id(job_id))) == job_id


@pytest.mark.parametrize(
    ("account_name", "account_domain"),
    [("Probook", "probook.ai"), ("Zafran Security", "zafran.io")],
)
def test_the_system_prompt_carries_the_pinned_resources_and_the_job_context(
    monkeypatch: pytest.MonkeyPatch,
    account_name: str,
    account_domain: str,
) -> None:
    run = replace(
        _run_row(),
        directive_text="Research {{account_name}} at {{account_domain}}; focus on hiring signals",
    )
    job = _job_row(run)
    store = FakeStore(run, job)
    _patch_reads(
        monkeypatch,
        account=SimpleNamespace(canonical_name=account_name, primary_domain=account_domain),
        icp_body=GATED_ICP_BODY,
    )
    seen: dict[str, Any] = {}

    def respond(messages: list[BaseMessage]) -> AIMessage:
        seen.setdefault("messages", list(messages))
        return AIMessage(content="nothing to do")

    handler, _, _, _ = _handler(store, model=_ScriptedModel(respond))

    asyncio.run(handler.handle(_context(job)))

    prompt = "\n".join(str(message.content) for message in seen["messages"])
    assert f"Research {account_name} at {account_domain}; focus on hiring signals" in prompt
    assert "{{account_name}}" not in prompt and "{{account_domain}}" not in prompt
    assert "{{account_name}}" in run.directive_text, "the shared launch brief stays unchanged"
    assert "agent-profile:arv2-account:v1" in prompt
    assert "Series A SaaS." in prompt, "the ICP body reaches the model"
    assert "VP Marketing." in prompt, "the persona document reaches the model"
    assert "core.industry" in prompt, "the field catalog menu reaches the model"
    assert "focus on hiring signals" in prompt, "the launch directive reaches the model"
    assert '"icp_gate_keys": ["series-a-saas", "us-hq"]' in prompt, (
        "the gates the verdicts are keyed to reach the model, so it never guesses a label"
    )
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


# --- the agent's own model spend (R2-close task 2) ---------------------------------------------


def _metered_finalizing_model() -> _ScriptedModel:
    """The finalizing model, stamped the way the governed gateway stamps a real answer."""

    base = _finalizes_at_once()

    def respond(messages: list[BaseMessage]) -> AIMessage:
        message = base._respond(messages)
        return AIMessage(
            content=message.content,
            tool_calls=message.tool_calls,
            usage_metadata={"input_tokens": 1_000, "output_tokens": 200, "total_tokens": 1_200},
            response_metadata={
                "clue_cost_cents": "0.5",
                "clue_cost_source": "metered",
                "clue_answering_model": "x-ai/grok-4.6",
            },
        )

    return _ScriptedModel(respond)


def test_the_model_rounds_are_drained_onto_the_ledger_before_the_job_spend_is_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row()
    # Attempt 2: a job that was suspended once and re-driven. The row id the driver stamps must
    # carry the row's own attempt, or this run's rounds would collide with the first attempt's and
    # be dropped by the drain's ON CONFLICT.
    job = _job_row(run, attempt=2)
    store = FakeStore(run, job)
    _patch_reads(
        monkeypatch, account=SimpleNamespace(canonical_name="Probook", primary_domain="probook.ai")
    )
    handler, conn_factory, _, _ = _handler(store, model=_metered_finalizing_model())

    result = asyncio.run(handler.handle(_context(job)))

    assert result.outcome == "completed"
    ledger_rows = [
        params
        for statement, params in conn_factory.conn.statements
        if "provider_call_ledger" in statement
    ]
    assert len(ledger_rows) == 1, "one model round, one ledger row"
    landed = ledger_rows[0]
    assert landed["provider"] == "openrouter"
    assert landed["operation"] == "agent_completion"
    assert landed["phase"] == "result"
    assert landed["outcome"] == "ok"
    assert landed["cost_usd"] == Decimal("0.005")
    assert landed["job_id"] == job.job_id
    assert landed["ledger_id"] == ledger_id_for(f"model:{job.job_id}:2:1")
    assert json.loads(str(landed["extras_json"]))["prompt_tokens"] == 1_000

    receipt = store.named("finish_job")[0]["finalization"]
    assert receipt["model_spend"] == {
        "usd": "0.005",
        "calls": 1,
        "prompt_tokens": 1_000,
        "completion_tokens": 200,
        "cached_prompt_tokens": 0,
        "cost_source": "metered",
    }


# -- the "already established" block ---------------------------------------------------------------


def _established_claim(
    field_key: str,
    *,
    value: Any,
    url: str | None,
    source_key: str | None = None,
) -> Claim:
    """A live claim shaped the way ``claims_for`` hands them to ``_already_established``."""
    return Claim(
        entity_id=EntityId(uuid4()),
        entity_type=EntityType.ACCOUNT,
        field_key=field_key,
        value_json=value,
        source_tier=4,
        extraction_method=ExtractionMethod.LLM_SYNTHESIS,
        run_id=RunId(uuid4()),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        confidence=0.6,
        reuse_scope=ReuseScope.TENANT_PRIVATE,
        workspace_id=WORKSPACE,
        source_url=url,
        evidence_span="Probook was founded in 2022.",
        source_key=source_key,
    )


def test_format_established_writes_compact_json_values_capped_per_line() -> None:
    long_list = [{"title": f"Role {i}", "url": f"https://jobs.test/{i}"} for i in range(40)]
    claims = [
        _established_claim("account.open_requisitions", value=long_list, url="https://jobs.test"),
        _established_claim("core.founded_year", value=2022, url=None, source_key="ai_ark:company"),
    ]
    text = format_established(claims)
    lines = text.split("\n")
    assert len(lines) == 2
    assert lines[0].startswith('- account.open_requisitions: [{"title": "Role 0"')
    assert lines[0].endswith("… (https://jobs.test)")
    assert len(lines[0]) <= 240 + len("- account.open_requisitions: ") + len(
        "… (https://jobs.test)"
    )
    assert lines[1] == "- core.founded_year: 2022 (ai_ark:company)"


# -- the committee fan-out (R3 task 6) ------------------------------------------------------------


def _finalizes_with_a_committee() -> _ScriptedModel:
    """The same finalization, carrying one confirmed committee member."""

    def respond(messages: list[BaseMessage]) -> AIMessage:
        del messages
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "finalize_research",
                    "args": {
                        "summary": "Probook is a strong fit on hiring and tooling evidence.",
                        "fit_verdicts": [],
                        "gaps": [],
                        "committee_candidates": [
                            {
                                "name": "Dana Reyes",
                                "title": "VP Marketing",
                                "persona": "economic_buyer",
                                "linkedin_url": "https://www.linkedin.com/in/dana-reyes",
                                "confirmed_by": "https://probook.ai/team",
                                "vacant_seat": False,
                                "evidence_span": "Dana Reyes, VP Marketing",
                            }
                        ],
                    },
                    "id": "call-finalize",
                    "type": "tool_call",
                }
            ],
        )

    return _ScriptedModel(respond)


class _RecordingQueue:
    """A queue that records its offers into the store's own event log, to pin the ORDER."""

    def __init__(self, store: FakeStore) -> None:
        self._store = store

    async def enqueue(self, **kwargs: Any) -> bool:
        self._store.events.append(("enqueue", kwargs))
        return True


def _patch_committee_step(
    monkeypatch: pytest.MonkeyPatch, store: FakeStore, run: RunRow
) -> list[dict[str, Any]]:
    """Stand in for the step: record the call, and hand back one person job to offer."""
    calls: list[dict[str, Any]] = []
    person_job = uuid4()

    async def fake_step(conn: Any, **kwargs: Any) -> Any:
        del conn
        store.events.append(("committee_step", {"candidates": len(kwargs["candidates"])}))
        calls.append(kwargs)
        return driver.CommitteeStepResult(
            contacts_created=(),
            jobs=(QueuedJob(job_id=person_job, run_id=run.run_id, workspace_id=run.workspace_id),),
            skipped=(),
        )

    monkeypatch.setattr(driver, "run_committee_step", fake_step)
    return calls


def test_an_account_job_fans_its_committee_out_inside_the_settle_and_offers_after_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rows first, offer second: the step runs after ``finish_job``, the offer after the commit."""
    run = _run_row()
    job = _job_row(run)
    store = FakeStore(run, job)
    _patch_reads(
        monkeypatch, account=SimpleNamespace(canonical_name="Probook", primary_domain="probook.ai")
    )
    calls = _patch_committee_step(monkeypatch, store, run)
    handler, _conn_factory, _writer, _models = _handler(
        store, model=_finalizes_with_a_committee(), queue=_RecordingQueue(store)
    )

    result = asyncio.run(handler.handle(_context(job)))

    assert result.outcome == "completed"
    order = [name for name, _ in store.events]
    # The two stage stamps ride this same transaction, so the order now reads: the terminal row,
    # then ``committee`` before the step, then ``member_research`` once the step returned person
    # jobs, and only then the run's status and the offer.
    assert order[order.index("finish_job") :][:6] == [
        "finish_job",
        "set_job_stage",
        "committee_step",
        "set_job_stage",
        "refresh_run_status",
        "enqueue",
    ]
    stamps = [payload["stage"] for event, payload in store.events if event == "set_job_stage"]
    # Claim → (finalize stamps synthesis inside the tool; see the tools test) → committee →
    # member_research once the person jobs exist. The order is the driver's real order.
    assert stamps == ["deep_research", "committee", "member_research"]
    # The step is handed the finalization's own candidates, the job, the run and the job's scope.
    assert calls[0]["candidates"][0]["name"] == "Dana Reyes"
    assert calls[0]["job"] is job and calls[0]["run"] is run
    assert calls[0]["scope"].account_id == EntityId(job.account_entity_id)
    assert calls[0]["person_profile_sha256"] == arv2_person_profile_sha256()


def test_a_worker_with_no_queue_still_writes_the_committee_and_says_it_offered_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``queue=None`` composes a fan-out that creates rows and offers none — loudly."""
    run = _run_row()
    job = _job_row(run)
    store = FakeStore(run, job)
    _patch_reads(
        monkeypatch, account=SimpleNamespace(canonical_name="Probook", primary_domain="probook.ai")
    )
    _patch_committee_step(monkeypatch, store, run)
    handler, _conn_factory, _writer, _models = _handler(
        store, model=_finalizes_with_a_committee(), queue=None
    )

    result = asyncio.run(handler.handle(_context(job)))

    assert result.outcome == "completed"
    assert [name for name, _ in store.events].count("committee_step") == 1
    assert not store.named("enqueue")


def test_a_committee_step_that_explodes_never_costs_the_job_its_terminal_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure law at the driver's own boundary: the account job still lands completed."""
    run = _run_row()
    job = _job_row(run)
    store = FakeStore(run, job)
    _patch_reads(
        monkeypatch, account=SimpleNamespace(canonical_name="Probook", primary_domain="probook.ai")
    )

    async def explode(conn: Any, **kwargs: Any) -> Any:
        del conn, kwargs
        raise RuntimeError("the committee step is broken")

    monkeypatch.setattr(driver, "run_committee_step", explode)
    handler, _conn_factory, _writer, _models = _handler(
        store, model=_finalizes_with_a_committee(), queue=_RecordingQueue(store)
    )

    result = asyncio.run(handler.handle(_context(job)))

    assert result.outcome == "completed"
    assert store.named("finish_job")[0]["status"] == "completed"
    # No PERSON job is offered — the step that would have created their rows exploded. The
    # account's own overview page is still offered: the account job itself finished, and the
    # page is written from what it wrote.
    offers = store.named("enqueue")
    kinds = [offer["kind"] for offer in offers]
    assert FleetTaskKind.ARV2_ACCOUNT_RESEARCH not in kinds
    assert kinds == [FleetTaskKind.ARV2_DISPLAY_PAGE, FleetTaskKind.ARV2_DISPLAY_PAGE]
    assert [offer["payload"]["page"] for offer in offers] == ["overview", "insights"]


def test_an_account_job_offers_its_overview_page_after_the_committee(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec 2026-09-12 §2: the overview is written at settle — offered after the commit, after
    the committee's person jobs, stamped with the account job as the page's spend."""
    run = _run_row()
    job = _job_row(run)
    store = FakeStore(run, job)
    _patch_reads(
        monkeypatch, account=SimpleNamespace(canonical_name="Probook", primary_domain="probook.ai")
    )
    _patch_committee_step(monkeypatch, store, run)
    handler, _conn_factory, _writer, _models = _handler(
        store, model=_finalizes_with_a_committee(), queue=_RecordingQueue(store)
    )

    result = asyncio.run(handler.handle(_context(job)))

    assert result.outcome == "completed"
    offers = [payload for name, payload in store.events if name == "enqueue"]
    kinds = [offer["kind"] for offer in offers]
    # Founder ruling 2026-09-22: BOTH account pages are written at settle — the overview first,
    # then the insights page — each its own task, after every research offer.
    assert kinds[-2:] == [FleetTaskKind.ARV2_DISPLAY_PAGE, FleetTaskKind.ARV2_DISPLAY_PAGE]
    assert FleetTaskKind.ARV2_ACCOUNT_RESEARCH in kinds[:-2]
    for page, expected_page in zip(offers[-2:], ("overview", "insights"), strict=True):
        assert page["work_id"] == arv2_display_work_id(
            "account", str(job.account_entity_id), expected_page
        )
        assert (
            page["dedup_key"]
            == f"{ARV2_DISPLAY_DEDUP_PREFIX}account:{job.account_entity_id}:{expected_page}"
        )
        assert page["priority"] == ARV2_DISPLAY_TASK_PRIORITY
        assert page["reopen_terminal"] is True
        assert page["payload"] == {
            "workspace_id": job.workspace_id,
            "subject_kind": "account",
            "subject_id": str(job.account_entity_id),
            "page": expected_page,
            "job_id": str(job.job_id),
        }


def test_a_worker_with_no_queue_says_it_offered_no_overview_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row()
    job = _job_row(run)
    store = FakeStore(run, job)
    _patch_reads(
        monkeypatch, account=SimpleNamespace(canonical_name="Probook", primary_domain="probook.ai")
    )
    _patch_committee_step(monkeypatch, store, run)
    handler, _conn_factory, _writer, _models = _handler(
        store, model=_finalizes_with_a_committee(), queue=None
    )
    result = asyncio.run(handler.handle(_context(job)))
    assert result.outcome == "completed"
    assert not store.named("enqueue")


# -- the person job (R3 task 8) -------------------------------------------------------------------


def _person_job_row(run: RunRow, *, contact_id: UUID, profile_sha256: str | None = None) -> JobRow:
    """One committee member's job: the same run, the account it belongs to, its own pin."""
    return replace(
        _job_row(run),
        subject_type="person",
        subject_entity_id=contact_id,
        profile_sha256=profile_sha256 or arv2_person_profile_sha256(),
    )


def _contact_claim(field_key: str, *, value: Any, contact_id: UUID, url: str | None) -> Claim:
    """A live contact claim shaped the way ``claims_for`` hands the person composition them."""
    return Claim(
        entity_id=EntityId(contact_id),
        entity_type=EntityType.CONTACT,
        field_key=field_key,
        value_json=value,
        source_tier=2,
        extraction_method=ExtractionMethod.API,
        run_id=RunId(uuid4()),
        research_mode=ResearchMode.CONTACT_PROFILING,
        confidence=0.9,
        reuse_scope=ReuseScope.TENANT_PRIVATE,
        workspace_id=WORKSPACE,
        source_url=url,
        evidence_span="Dana Reyes, VP Product Marketing",
        source_key="ai_ark:person",
        identity_binding=IdentityBinding.STRONG,
        use_class=UseClass.PROFESSIONAL_PUBLIC,
    )


CAREER_HISTORY = [
    {"org": "Sysdig", "role": "VP Product Marketing", "start": "2021", "end": "2024"},
    {"org": "Probook", "role": "VP Marketing", "start": "2024-04-01"},
    {"org": "Datadog"},
]


def _person_reads(
    monkeypatch: pytest.MonkeyPatch, job: JobRow, *, contact: Any | None = None
) -> None:
    """The person composition's reads: the account, the contact, and each one's live claims."""
    account_id = str(job.account_entity_id)
    contact_id = job.subject_entity_id
    assert contact_id is not None
    _patch_reads(
        monkeypatch,
        account=SimpleNamespace(canonical_name="Probook", primary_domain="probook.ai"),
        contact=(
            contact
            if contact is not None
            else SimpleNamespace(
                id=EntityId(contact_id),
                full_name="Dana Reyes",
                linkedin_url="https://www.linkedin.com/in/dana-reyes",
            )
        ),
        claims={
            account_id: (
                _established_claim(
                    "core.industry", value="observability", url="https://probook.ai/about"
                ),
            ),
            str(contact_id): (
                _contact_claim(
                    "contact.current_title",
                    value="VP Product Marketing",
                    contact_id=contact_id,
                    url="https://probook.ai/team",
                ),
                _contact_claim(
                    "contact.facet.career_history",
                    value=CAREER_HISTORY,
                    contact_id=contact_id,
                    url=None,
                ),
            ),
        },
    )


def _finalizes_the_person() -> _ScriptedModel:
    def respond(messages: list[BaseMessage]) -> AIMessage:
        del messages
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "finalize_research",
                    "args": {
                        "summary": "Dana Reyes runs product marketing and speaks about pipeline.",
                        "openers": [
                            {
                                "text": "Your DevOpsDays talk on pipeline hygiene stayed with me.",
                                "hook": "the DevOpsDays talk",
                                "quote": "pipeline hygiene is a marketing problem",
                                "url": "https://devopsdays.test/talk",
                            }
                        ],
                        "hooks": ["speaks at DevOpsDays"],
                        "not_found": ["no personal blog"],
                        "same_name_log": [
                            {
                                "name_or_url": "https://www.linkedin.com/in/dana-reyes-md",
                                "why_excluded": "a physician in Ohio, never at Probook",
                            }
                        ],
                        "gaps": ["no podcast appearances found"],
                    },
                    "id": "call-finalize",
                    "type": "tool_call",
                }
            ],
        )

    return _ScriptedModel(respond)


def test_employment_history_lines_render_one_line_per_role_with_missing_parts_omitted() -> None:
    assert employment_history_lines(CAREER_HISTORY) == (
        "VP Product Marketing @ Sysdig (2021–2024)",
        "VP Marketing @ Probook (2024-04-01–)",
        "Datadog",
    )


def test_employment_history_lines_ignore_anything_that_is_not_a_career_row() -> None:
    assert employment_history_lines(None) == ()
    assert employment_history_lines("VP Marketing") == ()
    # A row naming neither a role nor an organisation is a date range about nobody.
    assert employment_history_lines([{"start": "2019", "end": "2020"}, "not a row"]) == ()
    # A role with no employer is still a role the model should not re-derive.
    assert employment_history_lines([{"role": "Advisor"}]) == ("Advisor",)


def test_a_person_job_composes_the_person_bundle_its_tools_and_the_identity_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row()
    contact_id = uuid4()
    job = _person_job_row(run, contact_id=contact_id)
    store = FakeStore(run, job)
    _person_reads(monkeypatch, job)
    built: list[str] = []
    real_person_tools = driver.build_person_tools

    def spy(runtime: Any) -> Any:
        tools = real_person_tools(runtime)
        built.extend(tool.name for tool in tools)
        return tools

    monkeypatch.setattr(driver, "build_person_tools", spy)
    seen: dict[str, Any] = {}
    model = _finalizes_the_person()
    real_respond = model._respond

    def respond(messages: list[BaseMessage]) -> AIMessage:
        seen.setdefault("messages", list(messages))
        return real_respond(messages)

    handler, _conn_factory, _writer, models = _handler(store, model=_ScriptedModel(respond))

    result = asyncio.run(handler.handle(_context(job)))

    assert result.outcome == "completed"
    # The person belt, not the account's.
    assert built == list(PERSON_TOOL_NAMES)
    assert store.named("read_person_catalog") == [{}]
    assert not store.named("read_account_catalog")
    # Its own model id and its own effort role.
    assert models.builds[0]["model_id"] == "x-ai/grok-4.6-person"
    assert models.builds[0]["role"] == "arv2_person"

    prompt = "\n".join(str(message.content) for message in seen["messages"])
    assert "<person_research_context>" in prompt
    assert "agent-profile:arv2-person:v1" in prompt
    assert '"name": "Dana Reyes"' in prompt
    assert '"title": "VP Product Marketing"' in prompt
    assert '"linkedin_url": "https://www.linkedin.com/in/dana-reyes"' in prompt
    assert "VP Product Marketing @ Sysdig (2021–2024)" in prompt, "the lock reaches the model"
    # Account first, then a heading, then the person's own claims.
    account_line = prompt.index("- core.industry: ")
    heading = prompt.index("## the person's own claims")
    person_line = prompt.index("- contact.current_title: ")
    assert account_line < heading < person_line


def test_a_person_job_lands_the_person_receipt_and_never_runs_the_committee_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row()
    contact_id = uuid4()
    job = _person_job_row(run, contact_id=contact_id)
    store = FakeStore(run, job)
    _person_reads(monkeypatch, job)

    async def explode(conn: Any, **kwargs: Any) -> Any:
        del conn, kwargs
        raise AssertionError("a person job resolves no committee")

    monkeypatch.setattr(driver, "run_committee_step", explode)
    handler, conn_factory, writer, _models = _handler(
        store, model=_finalizes_the_person(), queue=_RecordingQueue(store)
    )

    result = asyncio.run(handler.handle(_context(job)))

    assert result.outcome == "completed"
    assert not store.named("enqueue")
    # A person job has no committee, so the driver stamps only the claim's ``deep_research``; its
    # ``synthesis`` stamp belongs to the finalize tool, which this test's model double stands in
    # for (and is asserted in the tools suite).
    stamps = [payload["stage"] for event, payload in store.events if event == "set_job_stage"]
    assert stamps == ["deep_research"]
    receipt = store.named("finish_job")[0]["finalization"]
    assert receipt["reason"] == "finalized"
    assert receipt["summary"].startswith("Dana Reyes runs product marketing")
    assert receipt["openers_written"] == 1
    assert receipt["openers_dropped"] == []
    assert receipt["hooks_written"] == 1
    assert receipt["not_found"] == ["no personal blog"]
    assert receipt["same_name_log"][0]["why_excluded"].startswith("a physician")
    assert receipt["insight_found"] is False
    assert receipt["reports_to_written"] is False
    assert receipt["reports_to_skipped"] is None
    # The coded compliance pass ran over the finalization's own writes, and its actions ride the
    # receipt: here the same-name log row cites nothing, and is marked, not hidden. The hooks claim
    # cites nothing either and produces no row at all — rule 6 exempts it, because a claim that
    # carries neither quote nor URL *by design* is not an evidence gap.
    assert [row["rule"] for row in receipt["compliance_log"]] == ["unevidenced"]
    assert [row["field_key"] for row in receipt["compliance_log"]] == [
        "contact.facet.excluded_lookalike"
    ]
    assert receipt["gaps"] == ["no podcast appearances found"]
    # Derived from the ROWS, not from the drafts: nothing is read back through the fake connection.
    assert receipt["claims_written"] == 0
    assert receipt["link_audit"] == {
        "EXACT/on_page": 3,
        "NOT_FOUND/not_on_page": 2,
        "PARTIAL/partial_on_page": 1,
    }
    assert receipt["model_spend"]["calls"] == 1
    assert receipt["model_id"] == "x-ai/grok-4.6-person"
    assert receipt["profile_sha256"] == arv2_person_profile_sha256()
    # No account-shaped key rides along: this job decided nothing about the account.
    assert "fit_verdicts" not in receipt and "committee_candidates" not in receipt
    # Every claim it wrote is the person's.
    assert {draft.entity_id for draft in writer.drafts} == {EntityId(contact_id)}
    activity = [
        params
        for statement, params in conn_factory.conn.statements
        if "account_activity_event" in statement
    ]
    assert activity[0]["text"].startswith("Person research finalized")


def test_a_person_job_whose_profile_digest_moved_refuses_on_its_own_pin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The JOB's pin, not the run's: a person job is queued long after the launch."""
    run = _run_row()
    contact_id = uuid4()
    job = _person_job_row(run, contact_id=contact_id, profile_sha256="a" * 64)
    store = FakeStore(run, job)
    _person_reads(monkeypatch, job)
    handler, _conn_factory, _writer, models = _handler(store)

    result = asyncio.run(handler.handle(_context(job)))

    assert result.outcome == "needs_review"
    assert store.named("finish_job")[0]["failure_code"] == "profile_pin_mismatch"
    assert models.builds == [], "a refused pin costs no model round"


def test_a_person_job_with_no_contact_row_is_contained_as_contact_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row()
    contact_id = uuid4()
    job = _person_job_row(run, contact_id=contact_id)
    store = FakeStore(run, job)
    _person_reads(monkeypatch, job, contact=None)
    monkeypatch.setattr(driver, "get_contact", _missing_contact)
    handler, _conn_factory, _writer, models = _handler(store)

    result = asyncio.run(handler.handle(_context(job)))

    assert result.outcome == "needs_review"
    landed = store.named("finish_job")[0]
    assert landed["failure_code"] == "contact_missing"
    assert str(contact_id) in landed["failure_message"]
    assert models.builds == []


async def _missing_contact(conn: Any, entity_id: Any) -> Any:
    del conn, entity_id
    return None


class _RecordingLog:
    """The driver's logger, as a list of the lines it wrote."""

    def __init__(self) -> None:
        self.lines: list[tuple[str, dict[str, Any]]] = []

    def _record(self, event: str, **fields: Any) -> None:
        self.lines.append((event, fields))

    info = warning = error = exception = _record

    def named(self, event: str) -> list[dict[str, Any]]:
        return [fields for name, fields in self.lines if name == event]


def test_an_unset_person_model_falls_back_to_the_account_model_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded = _RecordingLog()
    monkeypatch.setattr(driver, "log", recorded)
    store = FakeStore(_run_row(), None)

    handler, _conn_factory, _writer, _models = _handler(store, person_model_id="")

    assert handler._person_model_id == "x-ai/grok-4.6"  # noqa: SLF001 — the fallback IS the point
    fallback = recorded.named("arv2.person_model_fallback")
    assert len(fallback) == 1
    assert fallback[0]["model_id"] == "x-ai/grok-4.6"
    assert fallback[0]["env"] == ARV2_PERSON_MODEL_ENV


def test_the_builder_reads_the_person_model_from_its_own_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARV2_ACCOUNT_AGENT_MODEL", "x-ai/grok-4.6")
    monkeypatch.setenv(ARV2_PERSON_MODEL_ENV, "x-ai/grok-4.6-fast")

    handler = build_arv2_account_research_handler(
        Settings(_env_file=None, arv2_account_research_enabled=True),
        _live_secrets(),
        storage=object(),  # type: ignore[arg-type]
        artifacts=FakeArtifacts(),
        model_provider=FakeModels(_finalizes_at_once()),
    )

    assert handler is not None
    assert handler._person_model_id == "x-ai/grok-4.6-fast"  # noqa: SLF001


def test_the_builder_falls_the_person_model_back_to_the_account_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing person model is NOT a missing credential: the lane still composes."""
    monkeypatch.setenv("ARV2_ACCOUNT_AGENT_MODEL", "x-ai/grok-4.6")
    monkeypatch.setenv(ARV2_PERSON_MODEL_ENV, "  ")

    handler = build_arv2_account_research_handler(
        Settings(_env_file=None, arv2_account_research_enabled=True),
        _live_secrets(),
        storage=object(),  # type: ignore[arg-type]
        artifacts=FakeArtifacts(),
        model_provider=FakeModels(_finalizes_at_once()),
    )

    assert handler is not None
    assert handler._person_model_id == "x-ai/grok-4.6"  # noqa: SLF001


def test_a_person_job_that_never_finalized_still_lands_its_compliance_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A job that stops on a model error wrote claims all the same, and the floor may have redacted
    or dropped several. Reading the log off the finalization alone threw that audit trail away for
    exactly the jobs most likely to have gone wrong; it comes off the runtime instead."""
    run = _run_row()
    contact_id = uuid4()
    job = _person_job_row(run, contact_id=contact_id)
    store = FakeStore(run, job)
    _person_reads(monkeypatch, job)
    rounds: list[int] = []

    def respond(messages: list[BaseMessage]) -> AIMessage:
        del messages
        rounds.append(1)
        if len(rounds) > 1:
            raise RuntimeError("the provider hung up")
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "write_claims",
                    "args": {
                        "claims": [
                            {
                                "field_key": "contact.facet.self_summary",
                                "value": "She was diagnosed with cancer in 2019. She runs GTM.",
                                "evidence_span": "She runs GTM",
                                "source_url": "https://probook.ai/team",
                                "priority": 2,
                            }
                        ]
                    },
                    "id": "call-write",
                    "type": "tool_call",
                }
            ],
        )

    handler, _conn_factory, _writer, _models = _handler(store, model=_ScriptedModel(respond))

    result = asyncio.run(handler.handle(_context(job)))

    assert result.outcome == "needs_review"
    receipt = store.named("finish_job")[0]["finalization"]
    assert receipt["reason"] == "model_error"
    assert [(row["action"], row["rule"]) for row in receipt["compliance_log"]] == [
        ("redacted", "health")
    ]


def test_a_reporting_line_the_code_refused_reaches_the_durable_person_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refusal the model was told about must survive into the row a human reviews."""
    run = _run_row()
    contact_id = uuid4()
    job = _person_job_row(run, contact_id=contact_id)
    store = FakeStore(run, job)
    _person_reads(monkeypatch, job)

    def respond(messages: list[BaseMessage]) -> AIMessage:
        del messages
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "finalize_research",
                    "args": {
                        "summary": "Dana Reyes runs product marketing and speaks about pipeline.",
                        "reports_to": {
                            "name": "Sam Okafor",
                            "contact_id": str(uuid4()),
                            "url": "https://probook.ai/team",
                        },
                    },
                    "id": "call-finalize",
                    "type": "tool_call",
                }
            ],
        )

    handler, _conn_factory, writer, _models = _handler(store, model=_ScriptedModel(respond))

    assert asyncio.run(handler.handle(_context(job))).outcome == "completed"
    receipt = store.named("finish_job")[0]["finalization"]
    assert receipt["reports_to_written"] is False
    assert "quote" in receipt["reports_to_skipped"]
    assert [draft for draft in writer.drafts if draft.field_key == "contact.reports_to"] == []


def test_account_brief_binding_preserves_plain_text_and_does_not_expand_values() -> None:
    unchanged = 'Research the account; retain {"evidence": true} and {{unknown}}.'
    assert driver._account_directive(unchanged, name="Acme", domain="acme.test") == unchanged
    assert (
        driver._account_directive(
            "{{account_name}} / {{account_domain}} / {{account_name}}",
            name="Acme {{account_domain}}",
            domain="acme.test",
        )
        == "Acme {{account_domain}} / acme.test / Acme {{account_domain}}"
    )


def test_the_research_handler_declares_its_per_process_limit() -> None:
    """The worker claims at most this many research tasks per process (research slowness fix
    2026-10-03), the same number as the handler's own job semaphore."""
    from clue_fleet import InFlightLimited

    run = _run_row()
    handler = Arv2AccountResearchWorkHandler(
        settings=Settings(_env_file=None, arv2_account_max_parallel_jobs=3),
        conn_factory=FakeConnFactory(),
        artifacts=FakeArtifacts(),
        storage=object(),
        clients=FakeClients(),
        model_provider=FakeModels(_finalizes_at_once()),
        model_id="x-ai/grok-4.6",
        writer=FakeWriter(),
        store=FakeStore(run, _job_row(run)),
    )
    assert isinstance(handler, InFlightLimited)
    assert handler.max_in_flight == 3
