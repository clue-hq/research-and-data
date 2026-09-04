"""The advisory memory store may not veto the primary directive flow (live blocker, 2026-08-20).

Live shape, twice at 16:26 and 16:29 IST: the deepagent drafted the first directive under the new
committee co-definition contract, so the human's instruction text legitimately named committee
personas and roles. ``draft_account_research_directive@5`` side-writes that instruction into
project-scoped memory, the memory seam's LLM reconciliation judge answered ``body_ok=false``
("the body must carry the learning, never quoted personal-claim content"), and
``clue_research.directives.draft_research_directive`` treated the resulting
:class:`~clue_core.MemoryRejected` as fatal::

    ResearchDirectiveInvalid: project research instruction was rejected by the memory seam:
    body_rule

The draft died. Nothing about the *directive* was wrong — an advisory subsystem's nondeterministic
hygiene opinion killed the platform's primary flow.

Doc M is unambiguous that this can never be right in *any* posture, not merely the pilot one
(`docs/architecture/clue-hq-scoped-memory-and-context-assembly.md` §2: "Memory is advisory; config
is binding … nothing authoritative lives in memory"; M8B's own contract line: "Preserve memory as
advisory and the confirmed directive as execution authority"). The seam already models the
degradation: :class:`~clue_core.MemoryDisabled` — the workspace kill-switch — lands the directive
with ``memory_refs=()`` and a truthful ``memory_outcome``. A rejection now degrades the same way,
loudly, and the memory row is still *not* written (store hygiene is preserved; only the veto dies).

Both directions are pinned: an accepted submission must still thread its ``memory_id`` into the
directive's ``memory_refs``, so a regression that degrades everything to "no memory" fails here.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.research_directive_tools import build_research_directive_tools
from clue_api.trial.account_deep_fixture import seed_insight_health_account_deep_fixture
from clue_api.trial.discovery_fixture import PRODUCT_ID, PROJECT_ID, WORKSPACE_ID
from clue_config import MemoryCaps
from clue_core import ReconcileJudgment, ReconcileVerdictKind, new_operation_id
from clue_memory import WriteSeam
from clue_obs.otel.metrics import InMemorySink, get_metric_sink, set_metric_sink
from clue_research.durable.spend_posture import (
    EVENT_POLICY_REFUSAL_RECORD_ONLY,
    METRIC_POLICY_REFUSAL_RECORD_ONLY,
)
from clue_storage import FsStorage
from clue_toolbelt import ToolContext, ToolRegistry, invoke_tool
from tests.api.test_account_deep_fixture_a1 import _pages
from tests.api.test_account_research_directive_a2 import TTL, _body
from tests.db.conftest import run_async
from tests.memory.conftest import ScriptedJudge, add_judge, make_settings
from tests.profiling.conftest import conn_session_factory
from tests.stage0.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

#: The live instruction species: the human's own direction names the four committee personas and
#: the roles that carry them, because the co-definition contract (founder ruling 2026-08-20)
#: requires the personas to be agreed before any account research launches.
COMMITTEE_INSTRUCTION = (
    "Build the buying committee as we agreed: the champion is the Divisional CIO, the economic "
    "buyer is the CFO, the technical evaluator sits in Information Technology, and treat the "
    "Compliance Director as the likely blocker."
)


@asynccontextmanager
async def _recorded() -> AsyncIterator[tuple[InMemorySink, list[dict[str, Any]]]]:
    """Install a fresh metric sink and capture structlog events for the duration."""

    previous = get_metric_sink()
    sink = InMemorySink()
    set_metric_sink(sink)
    try:
        with structlog.testing.capture_logs() as events:
            yield sink, events
    finally:
        set_metric_sink(previous)


def _record_only_reasons(sink: InMemorySink, events: list[dict[str, Any]]) -> set[str]:
    """The policy refusals this run skipped, proved from both surfaces at once."""

    logged = {
        str(event["reason"])
        for event in events
        if event.get("event") == EVENT_POLICY_REFUSAL_RECORD_ONLY and "reason" in event
    }
    metered = {
        dict(attributes)["reason"]
        for (name, attributes), value in sink.counters.items()
        if name == METRIC_POLICY_REFUSAL_RECORD_ONLY and value > 0
    }
    assert logged == metered, "every skipped policy refusal must both log and meter"
    return logged


def _body_rule_judge() -> ScriptedJudge:
    """The live judgment: a well-formed preference whose body the judge calls person-adjacent."""

    return ScriptedJudge(
        ReconcileJudgment(
            verdict=ReconcileVerdictKind.ADD,
            body_ok=False,
            rationale="the body names individual committee members' roles",
        )
    )


async def _draft(
    conn: AsyncConnection,
    *,
    judge: Any,
    tmp_path: Path,
    instruction: str,
) -> tuple[dict[str, Any], Any]:
    fixture = await seed_insight_health_account_deep_fixture(
        conn,
        pages=_pages(),
        storage=FsStorage(tmp_path / "artifacts"),
    )
    cf = conn_session_factory(conn)

    def memory_factory(write_conn: AsyncConnection) -> WriteSeam:
        return WriteSeam(write_conn, judge, settings=make_settings(), caps=MemoryCaps())

    registry = ToolRegistry()
    for tool in build_research_directive_tools(
        memory_write_factory=memory_factory,
        conn_factory=cf,
    ):
        registry.register(tool, make_default=tool.version == "2")

    result = await invoke_tool(
        registry,
        "draft_account_research_directive",
        {
            "project_id": PROJECT_ID,
            "product_id": PRODUCT_ID,
            "icp_key": fixture.deep_icp_key,
            "icp_version": fixture.deep_icp_version,
            "body": _body(fixture.selected_account_id).model_dump(mode="json"),
            "account_overrides": [],
            "user_instruction": instruction,
            "source_turn_ref": "agent-turn:committee-codefinition",
        },
        ToolContext(
            workspace_id=WORKSPACE_ID,
            actor="agent",
            conn_factory=cf,
            operation_id=new_operation_id(),
        ),
        idempotency_ttl_s=TTL,
    )
    return dict(result.references), fixture


def test_a_memory_body_rule_rejection_records_and_the_directive_still_drafts(
    tmp_path: Path,
) -> None:
    """The live blocker: the draft survives its instruction being refused by the memory seam."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            async with _recorded() as (sink, events):
                references, _ = await _draft(
                    conn,
                    judge=_body_rule_judge(),
                    tmp_path=tmp_path,
                    instruction=COMMITTEE_INSTRUCTION,
                )

            # The directive exists — the flow was not killed.
            assert references["status"] == "draft"
            assert references["memory_outcome"] == "memory_rejected:body_rule"
            assert references["memory_refs"] == []
            assert references["future_thread_memory_persisted"] is False

            # The skip is loud on both surfaces.
            assert _record_only_reasons(sink, events) == {"body_rule"}
            recorded = [
                event for event in events if event.get("event") == EVENT_POLICY_REFUSAL_RECORD_ONLY
            ]
            assert len(recorded) == 1
            assert recorded[0]["site"] == "research_directive_memory_seam"
            assert "learning" in str(recorded[0]["detail"])

            # Store hygiene is untouched: the rejected body was still never written.
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM memory WHERE workspace_id=:w"),
                    {"w": WORKSPACE_ID},
                )
            ).scalar_one() == 0

            # The durable directive really landed, with no memory refs.
            row = (
                await conn.execute(
                    text(
                        "SELECT status::text AS status, memory_refs "
                        "FROM account_research_directive WHERE directive_id=:d"
                    ),
                    {"d": UUID(str(references["directive_id"]))},
                )
            ).one()
            assert row.status == "draft"
            assert list(row.memory_refs or []) == []

    run_async(scenario())


def test_a_contactable_instruction_records_the_seams_precondition_and_still_drafts(
    tmp_path: Path,
) -> None:
    """The seam's *other* person-adjacent refusal, one layer above the judge.

    ``clue_memory.write`` fails closed on verbatim contact data in a body with no resolved
    subject — and this call site never has a subject by construction. So "…and cc me at
    ops@insighthealth.com" made a well-formed directive draft raise
    :class:`~clue_core.MemoryPreconditionFailed` straight through the tool. Same species, same
    degradation: recorded, no memory row, draft lands.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            async with _recorded() as (sink, events):
                references, _ = await _draft(
                    conn,
                    # The guard runs before the judge, so a clean judge proves which layer fired.
                    judge=add_judge(),
                    tmp_path=tmp_path,
                    instruction=(
                        "Research the shortlist and cc me at ops@insighthealth.example when the "
                        "committee is ready."
                    ),
                )

            assert references["status"] == "draft"
            assert references["memory_outcome"] == "memory_rejected:person_adjacent_precondition"
            assert references["memory_refs"] == []
            assert _record_only_reasons(sink, events) == {"person_adjacent_precondition"}
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM memory WHERE workspace_id=:w"),
                    {"w": WORKSPACE_ID},
                )
            ).scalar_one() == 0

    run_async(scenario())


def test_an_accepted_submission_still_threads_its_memory_ref(tmp_path: Path) -> None:
    """The other direction: degradation must not swallow a memory the seam actually accepted."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            async with _recorded() as (sink, events):
                references, _ = await _draft(
                    conn,
                    judge=add_judge(),
                    tmp_path=tmp_path,
                    instruction=COMMITTEE_INSTRUCTION,
                )

            assert references["status"] == "draft"
            assert references["memory_outcome"] == "persisted"
            assert len(references["memory_refs"]) == 1
            assert references["future_thread_memory_persisted"] is True
            # Nothing was skipped, so nothing is recorded.
            assert _record_only_reasons(sink, events) == set()

            memory_id = str(references["memory_refs"][0])
            assert (
                await conn.execute(
                    text("SELECT body FROM memory WHERE memory_id=:id"),
                    {"id": memory_id},
                )
            ).scalar_one() == COMMITTEE_INSTRUCTION

    run_async(scenario())
