"""Lane 3 slice 1b: the persona-evidence tool lands its call on ``provider_call_ledger`` under
the tool context's own connection factory, workspace-stamped (the context carries no project)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.arv2.sinks import LedgerRow
from clue_api.onboarding_evidence_tools import (
    EXA_SEARCH_EVIDENCE_TOOL_NAME,
    ExaSearchEvidenceInput,
    ExaSearchEvidenceTool,
)
from clue_core import operation_id_from_key
from clue_toolbelt import ToolContext
from tests.api.test_onboarding_evidence_tools import FakeExa, _deep
from tests.arv2.test_provider_ledger_db import FakeArtifacts
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")


def test_an_invocation_lands_its_row_under_the_contexts_connection_with_the_workspace_stamp() -> (
    None
):
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            ws = f"ws_evidence_{uuid4().hex[:8]}"
            fake = FakeExa(_deep([], []))
            artifacts = FakeArtifacts()

            def factory(label: str, raw: Any, ledger: Any) -> FakeExa:
                ledger.record(
                    LedgerRow(
                        row_id=f"evidence:{label}",
                        call_id=str(uuid4()),
                        phase="result",
                        provider="exa",
                        operation="deep-reasoning",
                        label=label,
                        recorded_at=datetime(2026, 9, 14, tzinfo=UTC),
                        http_status=200,
                        latency_ms=7,
                        attempts=1,
                        cost_usd=Decimal("0.015"),
                        outcome="ok",
                        extras={"cost_source": "metered"},
                    )
                )
                return fake

            tool = ExaSearchEvidenceTool(enabled=True, client_factory=factory, artifacts=artifacts)
            ctx = ToolContext(
                workspace_id=ws,
                actor="agent",
                conn_factory=conn_session_factory(conn),
                operation_id=operation_id_from_key("o4-evidence", "db"),
            )
            await tool.invoke(ExaSearchEvidenceInput(query="pain of practice managers"), ctx)
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT workspace_id, project_id, project_run_id, "
                            " entity_research_job_id, cost_usd, label FROM provider_call_ledger "
                            "WHERE workspace_id = :ws AND phase = 'result'"
                        ),
                        {"ws": ws},
                    )
                )
                .mappings()
                .one()
            )
            assert (row["project_id"], row["project_run_id"], row["entity_research_job_id"]) == (
                None,
                None,
                None,
            )
            assert row["cost_usd"] == Decimal("0.015000")
            assert row["label"].startswith(f"{EXA_SEARCH_EVIDENCE_TOOL_NAME}:")

    run_async(scenario())
