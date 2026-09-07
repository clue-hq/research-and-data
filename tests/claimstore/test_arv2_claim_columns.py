"""The three D1 claim columns round-trip through insert_claim / claims_by_ids."""

from __future__ import annotations

import pytest

from clue_core import (
    Claim,
    EntityType,
    ExtractionMethod,
    ResearchMode,
    ReuseScope,
    new_run_id,
)
from clue_research.claimstore import claims_by_ids, insert_claim
from clue_research.claimstore.tenancy import WorkspaceScope
from clue_research.identity import insert_account_entity
from tests._workspace import seed_workspace
from tests.claimstore.conftest import rollback_conn
from tests.db.conftest import run_async


@pytest.mark.usefixtures("require_claimstore_db")
def test_priority_outreach_and_markers_round_trip() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn, "ws_d1")
            account = await insert_account_entity(
                conn, canonical_name="Zafran", primary_domain="zafran.io", workspace_id=ws
            )
            claim = Claim(
                entity_id=account,
                entity_type=EntityType.ACCOUNT,
                field_key="core.account_name",
                value_json="Zafran Security",
                source_tier=1,
                extraction_method=ExtractionMethod.API,
                confidence=0.9,
                run_id=new_run_id(),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                reuse_scope=ReuseScope.TENANT_PRIVATE,
                workspace_id=ws,
                signal_priority=2,
                outreach_safe=False,
                write_markers={"source_missing": True},
            )
            claim_id = await insert_claim(conn, claim)
            stored = (
                await claims_by_ids(conn, [claim_id], scope=WorkspaceScope.for_workspace(ws))
            )[claim_id]
            assert stored.signal_priority == 2
            assert stored.outreach_safe is False
            assert stored.write_markers == {"source_missing": True}
            assert stored.source_url is None

    run_async(_run())


@pytest.mark.usefixtures("require_claimstore_db")
def test_unstamped_claim_reads_back_the_column_defaults() -> None:
    """A writer that never heard of D1 still round-trips: 3 / True / None."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn, "ws_d1")
            account = await insert_account_entity(
                conn, canonical_name="Acme D1", primary_domain="acme-d1.example", workspace_id=ws
            )
            claim = Claim(
                entity_id=account,
                entity_type=EntityType.ACCOUNT,
                field_key="core.account_name",
                value_json="Acme D1",
                source_url="https://acme-d1.example/about",
                source_tier=1,
                extraction_method=ExtractionMethod.API,
                confidence=0.9,
                run_id=new_run_id(),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                reuse_scope=ReuseScope.TENANT_PRIVATE,
                workspace_id=ws,
            )
            claim_id = await insert_claim(conn, claim)
            stored = (
                await claims_by_ids(conn, [claim_id], scope=WorkspaceScope.for_workspace(ws))
            )[claim_id]
            assert stored.signal_priority == 3
            assert stored.outreach_safe is True
            assert stored.write_markers is None

    run_async(_run())
