"""``clue_spend.acall``: one async provider call through the spend layer, drained by itself.

The calls that skipped the spend layer (Exa deep, Exa Websets, Composio, Cloudflare, Clerk) are
async code with a connection factory in hand; ``acall`` is the one way they spend (design
2026-10-31 ruling 8).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

from sqlalchemy import text

from clue_spend import CallSpec, HttpRequest, HttpResponse, LedgerStamp, SpendEstimate
from clue_spend.acall import acall
from clue_spend.incidents import open_incidents
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async


class _Transport:
    def __init__(self, response: HttpResponse) -> None:
        self.response = response
        self.sent: list[HttpRequest] = []

    def send(self, request: HttpRequest) -> HttpResponse:
        self.sent.append(request)
        return self.response


def _spec(provider: str) -> CallSpec:
    return CallSpec(
        provider=provider,
        operation=f"test.{provider}",
        label=f"{provider}:test",
        request=HttpRequest(
            method="GET",
            url="https://provider.example/thing",
            headers={"Authorization": "Bearer secret-token-123"},
            body=None,
            timeout_s=5.0,
        ),
        estimate=SpendEstimate(credits=0),
        max_attempts=1,
        binary=False,
    )


def _stamp() -> LedgerStamp:
    return LedgerStamp(workspace_id=f"ws_acall_{uuid4().hex[:8]}")


def test_acall_returns_the_response_and_ledgers_it(require_claimstore_db: None) -> None:
    stamp = _stamp()

    async def scenario():
        async with rollback_conn(seed_pack=False) as conn:

            @asynccontextmanager
            async def same():
                yield conn

            response = await acall(
                _spec("composio"),
                conn_factory=same,
                stamp=stamp,
                transport=_Transport(HttpResponse(status=200, body=b"{}")),
            )
            rows = (
                await conn.execute(
                    text(
                        "SELECT provider, outcome FROM provider_call_ledger "
                        "WHERE workspace_id = :ws AND phase = 'result'"
                    ),
                    {"ws": stamp.workspace_id},
                )
            ).all()
            return response, rows

    response, rows = run_async(scenario())
    assert response.status == 200
    assert [(r.provider, r.outcome) for r in rows] == [("composio", "ok")]


def test_acall_ledgers_a_402_and_opens_an_incident(require_claimstore_db: None) -> None:
    async def scenario():
        async with rollback_conn(seed_pack=False) as conn:

            @asynccontextmanager
            async def same():
                yield conn

            response = await acall(
                _spec("cloudflare"),
                conn_factory=same,
                stamp=_stamp(),
                transport=_Transport(HttpResponse(status=402, body=b'{"error":"payment required"}')),
            )
            return response, await open_incidents(conn, providers=["cloudflare"])

    response, live = run_async(scenario())
    assert response.status == 402
    assert [(i.reason, i.kind) for i in live] == [("credits_exhausted", "refusal")]
    assert "secret-token-123" not in live[0].sample_message


def test_acall_returns_even_when_the_drain_fails() -> None:
    @asynccontextmanager
    async def broken():
        raise RuntimeError("database went away")
        yield  # pragma: no cover

    response = run_async(
        acall(
            _spec("clerk"),
            conn_factory=broken,
            stamp=_stamp(),
            transport=_Transport(HttpResponse(status=200, body=b"{}")),
        )
    )
    assert response.status == 200
