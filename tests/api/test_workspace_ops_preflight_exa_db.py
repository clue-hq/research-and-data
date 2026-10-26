"""The real Exa pre-flight probe (spec 2026-10-25 §3.3): a refusal reads as no credit, and the
probe's one call lands on the provider ledger, charged to the workspace."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from clue_api.arv2.calls import ProviderCaller
from clue_api.arv2.transport import HttpResponse, ScriptedTransport
from clue_api.workspace_ops.preflight import build_exa_probe
from clue_config import Secrets
from tests.auth.conftest import rollback_conn, run_async
from tests.profiling.conftest import conn_session_factory

pytestmark = pytest.mark.usefixtures("require_profiling_db")


def test_exa_out_of_credit_is_no_credit_and_ledgered_to_the_workspace() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = f"ws-ops-exa-{uuid4().hex[:8]}"
            await conn.execute(
                text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"), {"w": ws}
            )

            def caller(*, raw, ledger) -> ProviderCaller:
                return ProviderCaller(
                    transport=ScriptedTransport([HttpResponse(status=402, body=b"{}")]),
                    raw_sink=raw,
                    ledger=ledger,
                    now=lambda: datetime(2026, 10, 25, tzinfo=UTC),
                )

            probe = build_exa_probe(
                Secrets(exa_api_key=SecretStr("exa-key")),
                conn_session_factory(conn),
                caller_factory=caller,
            )
            result = await probe(ws)
            assert (result.outcome, result.required) == ("no_credit", True)
            assert "payment_required" in result.detail
            rows = (
                (
                    await conn.execute(
                        text("SELECT label FROM provider_call_ledger WHERE workspace_id = :w"),
                        {"w": ws},
                    )
                )
                .scalars()
                .all()
            )
            assert rows and set(rows) == {"onboarding-preflight"}

    run_async(scenario())


@pytest.mark.parametrize(
    ("status", "outcome"),
    [(401, "key_invalid"), (500, "unreachable")],
)
def test_an_exa_answer_that_is_not_a_success_is_never_ok(status: int, outcome: str) -> None:
    """Found by the live proof (2026-10-26): Exa answers a bad key with HTTP 401, which the client
    RETURNS (``result.status == 401``) rather than raising — the probe read it as ``ok``."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = f"ws-ops-exa-{uuid4().hex[:8]}"
            await conn.execute(
                text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"), {"w": ws}
            )

            def caller(*, raw, ledger) -> ProviderCaller:
                return ProviderCaller(
                    transport=ScriptedTransport(
                        [HttpResponse(status=status, body=b'{"error":"no"}')] * 4
                    ),
                    raw_sink=raw,
                    ledger=ledger,
                    now=lambda: datetime(2026, 10, 26, tzinfo=UTC),
                    sleep=lambda _: None,
                )

            probe = build_exa_probe(
                Secrets(exa_api_key=SecretStr("bad")),
                conn_session_factory(conn),
                caller_factory=caller,
            )
            result = await probe(ws)
            assert result.outcome == outcome, result

    run_async(scenario())
