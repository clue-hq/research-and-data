"""One run through the real store, lineage and artifact store, asserting the rows the page reads.

The provider is still doubled — the driver's job is the rows, not Exa's answers — but everything
below it is real: the O1 CHECKs, the step ↔ document cycle, the catalog synchronizer's minted
product, and the artifact the overview document cites.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2.onboarding_driver import OnboardingRunWorkHandler, onboarding_work_id
from clue_api.arv2.onboarding_store import create_run, list_documents, read_current_run
from clue_config import Settings
from clue_fleet.lease import LeaseGeneration
from clue_fleet.work_worker import WorkContext
from clue_storage import read_verified_artifact
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.api.test_stage0_setup_db import _MemoryStorage
from tests.arv2.test_onboarding_driver import OVERVIEW, PRODUCT, REVIEWS, FakeExa, _agent, _deep
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401
    require_profiling_db,  # noqa: F401
    rollback_conn,
)

pytestmark = pytest.mark.usefixtures("require_profiling_db")

USER = "usr_o3_driver"


def test_a_run_publishes_readable_documents_and_products_and_status() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-driver-db"
            project = await seed_project(conn, ws, name="O3 driver")
            await seed_principal(conn, workspace_id=ws, user_id=USER)
            run_id = uuid4()
            await create_run(
                conn,
                run_id=run_id,
                workspace_id=ws,
                brand_id=project.brand_id,
                company_domain="insighthealth.ai",
                requested_by_user_id=USER,
            )
            storage = _MemoryStorage()
            artifacts = DurableAgentArtifactStore(
                storage=storage,  # type: ignore[arg-type]
                conn_factory=conn_session_factory(conn),
            )
            exa = FakeExa(
                {
                    "overview": _agent(OVERVIEW, usd="0.5"),
                    "reviews": _agent(REVIEWS),
                    "product_research": _agent(PRODUCT),
                },
                _deep(
                    [
                        {
                            "name": "MagicFlow",
                            "short_description": "Orchestration.",
                            "offering_kind": "platform",
                        }
                    ]
                ),
            )
            handler = OnboardingRunWorkHandler(
                settings=Settings(_env_file=None),
                conn_factory=conn_session_factory(conn),
                artifacts=artifacts,
                exa=lambda *, run_id, step_label: exa,
            )
            context = WorkContext(
                task_id=uuid4(),
                work_id=onboarding_work_id(run_id),
                worker_id="t",
                lease_generation=LeaseGeneration(1),
                payload={
                    "run_id": str(run_id),
                    "workspace_id": ws,
                    "brand_id": project.brand_id,
                    "company_domain": "insighthealth.ai",
                    "company_name": "Insight Health",
                },
                stop_requested=asyncio.Event(),
                lease_lost=asyncio.Event(),
            )

            result = await handler.handle(context)

            assert result.outcome == "completed_with_gaps"  # synthesis is empty until O4
            status = await read_current_run(conn, workspace_id=ws)
            assert status is not None
            assert status.status == "completed_with_gaps"
            kinds = {(step.kind, step.subject_ref): step.status for step in status.steps}
            assert kinds[("overview", None)] == "completed"
            assert kinds[("lineup", None)] == "completed"
            assert kinds[("catalog_sync", None)] == "completed"
            assert kinds[("synthesis", None)] == "empty"
            assert any(
                key[0] == "product_research" and value == "completed"
                for key, value in kinds.items()
            )
            listed = await list_documents(conn, workspace_id=ws, brand_id=project.brand_id)
            documents = {document.path: document for document in listed}
            assert documents["company/overview.md"].status == "ready"
            assert documents["product/catalog.md"].status == "ready"
            assert documents["product/magicflow.md"].status == "ready"
            assert documents["proof/customer-reviews.md"].status == "ready"
            record, body = await read_verified_artifact(
                conn,
                storage,  # type: ignore[arg-type]
                storage_key=documents["company/overview.md"].artifact_key,
                workspace_id=ws,
            )
            assert record.workspace_id == ws
            assert body.startswith(b"---\nkind: company-overview")
            assert status.cost_usd >= 0.5

    run_async(scenario())
