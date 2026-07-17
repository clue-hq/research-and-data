"""M13 integration join, on a live Postgres: the joined review surface → M13.2 concrete emitter →
``disposition`` row path.

M13.1 tested the surface with a *fake* emitter and M13.2 tested ``capture_review_action`` directly;
this proves the two halves run together once ``build_reviewed_phase_handler`` wires the concrete
``ReviewDispositionEmitterImpl`` in — a reject through the surface is mirrored into exactly one
``claim_rejected`` disposition that preserves its reason_code. Skips without a DB (like the rest of
the DB suites)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    AccountStatus,
    Claim,
    EntityId,
    ExtractionMethod,
    ResearchMode,
    ReviewAction,
    ReviewRejectReason,
    account_claim,
    new_campaign_run_id,
    new_run_id,
)
from clue_research.api.review_feedback_wiring import build_reviewed_phase_handler
from clue_research.claimstore import insert_claim
from clue_research.durable.campaign_run import ensure_campaign_run
from clue_research.identity import insert_account_entity
from clue_research.review.disposition_store import ReviewDispositionEmitterImpl

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_review_db")

_CLIENT = "client-acme"
_ICP_KEY = "default"
_ICP_VERSION = 1
_PAIN = "account.operational_pain"  # a core-pack account field (string value)


def _factory(conn: AsyncConnection) -> Callable[[], AbstractAsyncContextManager[AsyncConnection]]:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncConnection]:
        yield conn

    return factory


def _orig(entity: EntityId) -> Claim:
    """An eligible (tier-2 scrape) account claim — the current value the reviewer approves."""
    return account_claim(
        entity_id=entity,
        field_key=_PAIN,
        value_json="original pain",
        source_tier=2,
        extraction_method=ExtractionMethod.SCRAPE,
        confidence=0.8,
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        source_url="https://news.example/acme",
    )


def test_review_action_through_production_binder_writes_a_disposition() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            factory = _factory(conn)
            acct = await insert_account_entity(
                conn, canonical_name="Acme", primary_domain="acme.com", status=AccountStatus.ACTIVE
            )
            orig = _orig(acct)
            await insert_claim(conn, orig)
            run_id = new_campaign_run_id()
            await ensure_campaign_run(
                conn,
                campaign_run_id=run_id,
                client_id=_CLIENT,
                icp_key=_ICP_KEY,
                icp_version=_ICP_VERSION,
            )

            # The production binder wires M13.2's concrete emitter into the surface (not the no-op).
            handler = build_reviewed_phase_handler(
                conn_factory=factory, session_factory=factory, emitter_conn_factory=factory
            )
            surface = handler._surface
            assert isinstance(surface._emit, ReviewDispositionEmitterImpl)

            session = await surface.open_session(
                account_entity_id=acct, campaign_run_id=run_id, client_id=_CLIENT
            )
            # A REJECT carries a reason_code; the mirrored disposition must preserve the REAL one —
            # proving the emitter read the committed ``review_action`` row, not the ``(None, now)``
            # fallback. NB: all factories share one connection (rollback isolation can't observe a
            # second connection); the production two-transaction path is correct because the surface
            # emits AFTER its write txn commits (see ``surface.apply_action``).
            await surface.apply_action(
                session_id=session.session_id,
                claim_id=orig.id,
                action=ReviewAction.REJECT,
                actor="reviewer",
                reason_code=ReviewRejectReason.INACCURATE,
            )

            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT disposition_type, reason_code FROM disposition "
                            "WHERE client_id = :c AND account_entity_id = :a"
                        ),
                        {"c": _CLIENT, "a": str(acct)},
                    )
                )
                .mappings()
                .one()
            )  # exactly one disposition row for this account
            assert row["disposition_type"] == "claim_rejected"  # the reject was mirrored
            assert (
                row["reason_code"] == ReviewRejectReason.INACCURATE.value
            )  # real reason preserved

    run_async(_run())
