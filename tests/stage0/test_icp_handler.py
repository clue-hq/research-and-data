"""DB-backed test for the ``ICP_CONFIRMED`` phase handler (M5.2).

The handler implements the frozen ``PhaseHandler`` protocol and opens its own (committing)
transaction, so this exercises it against a real DB. ``ICP_CONFIRMED`` is a checkpoint over an
*already-confirmed* spec: it reads the pinned ``(client_id, icp_key, icp_version)``, compiles it,
and emits the artifact (plan_hash + two-pass counts + pre-run estimate). A fresh tenant per run
gives a brand-new client + spec at version 1 (the claim/icp tables are append-only — no cleanup).
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from clue_research.claimstore import load_core_pack
from clue_research.core import (
    CampaignPhase,
    PhaseContext,
    PhaseHandler,
    PhaseStatus,
    new_campaign_run_id,
)
from clue_research.db import db_lifespan, transaction
from clue_research.icp import load_starter_packs
from clue_research.sources import seed_source_manifests
from clue_research.stage0 import (
    IcpConfirmedHandler,
    confirm_icp,
    load_client_knowledge_pack,
    load_icp_feedback_pack,
    synthesize_icps,
)
from clue_research.stage0.fields import (
    CLIENT_ICP_EVIDENCE,
    CLIENT_PRODUCT,
    CLIENT_VALUE_PROP,
)
from tests.stage0._fakes import build_client_kb
from tests.stage0.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_stage0_db", "resolver_bindings")

_ASSERTED: dict[str, object] = {
    CLIENT_VALUE_PROP: "We sell a data infrastructure platform",
    CLIENT_PRODUCT: "data infrastructure platform for analytics teams",
    CLIENT_ICP_EVIDENCE: {"industries": ["data_infra"], "sizes": ["mid-market"]},
}


def test_handler_conforms_to_protocol() -> None:
    handler = IcpConfirmedHandler()
    assert isinstance(handler, PhaseHandler)
    assert handler.phase is CampaignPhase.ICP_CONFIRMED


async def _seed_committed() -> None:
    """Commit the registry state the handler reads (idempotent — load is a no-op if present)."""
    async with transaction() as conn:
        await load_core_pack(conn)
        await load_client_knowledge_pack(conn)
        await load_starter_packs(conn)
        await load_icp_feedback_pack(conn)
        await seed_source_manifests(conn)


def _ctx(client_id: str, icp_key: str, icp_version: int) -> PhaseContext:
    return PhaseContext(
        campaign_run_id=new_campaign_run_id(),
        phase=CampaignPhase.ICP_CONFIRMED,
        client_id=client_id,
        icp_key=icp_key,
        icp_version=icp_version,
    )


def test_handler_emits_artifact_for_confirmed_spec() -> None:
    async def _run() -> None:
        async with db_lifespan():
            await _seed_committed()
            suffix = uuid4().hex[:12]
            client = f"tenant-icp-{suffix}"
            # build + confirm a spec in a committed transaction, then run the handler over it
            async with transaction() as conn:
                ref = await build_client_kb(
                    conn, client_id=client, suffix=suffix, asserted=_ASSERTED
                )
                (proposal,) = await synthesize_icps(conn, ref, client_id=client)
                confirmation = await confirm_icp(
                    conn, proposal, client_id=client, client_entity_id=ref.client_entity_id
                )

            spec_ref = confirmation.ref
            result = await IcpConfirmedHandler().run(
                _ctx(client, spec_ref.icp_key, spec_ref.icp_version)
            )

            assert result.status is PhaseStatus.COMPLETED
            assert result.payload["icp_key"] == spec_ref.icp_key
            assert result.payload["icp_version"] == 1
            assert isinstance(result.payload["plan_hash"], str) and result.payload["plan_hash"]
            assert result.payload["scoring_field_count"] >= 1
            assert isinstance(result.payload["estimate"], dict)
            assert result.payload["estimate"]["discovered_count"] == 500

    run_async(_run())


def test_handler_fails_when_no_confirmed_spec() -> None:
    async def _run() -> None:
        async with db_lifespan():
            await _seed_committed()
            # a campaign pointed at an ICP the client never confirmed → FAILED (a real
            # misconfiguration), not a budget PAUSE.
            result = await IcpConfirmedHandler().run(
                _ctx(f"tenant-missing-{uuid4().hex[:12]}", "never_confirmed", 1)
            )
            assert result.status is PhaseStatus.FAILED
            assert "reason" in result.payload

    run_async(_run())
