"""M8.1 × M7 — the real aspect worker plugged into ``AccountResearchGraph`` (DB-gated).

The worker-level tests run ``AspectProfilingWorker`` directly; this proves it integrates with the
*production* path — M7's per-account orchestrator-worker graph dispatches it by the **field-class
aspect key** (``"account"``) that ``durable.planning.build_plan`` produces, and the references land
in the run's ``references_index``. Tests may import ``durable`` (the independence contract binds the
``src`` packages, not the test tree). A single-aspect plan keeps the fan-out to one worker, so the
worker runs sequentially on the test's rollback connection (no parallel-connection contention) and
nothing is committed to the shared DB.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from clue_core import (
    Claim,
    Entity,
    EntityScope,
    ExtractionMethod,
    FieldDef,
    Modality,
    PassKind,
    ResearchMode,
    SourceManifest,
    account_claim,
    new_entity_id,
    new_project_run_id,
    new_run_id,
)
from clue_research.claimstore import register_field
from clue_research.durable import (
    AccountResearchGraph,
    AccountRunStatus,
    AspectPlan,
    ResearchPlan,
    WorkerRegistry,
)
from clue_research.identity import insert_account_entity
from clue_research.profiling import AspectProfilingWorker
from clue_research.sources import RegistrySourceManifest, bind_resolver, register_source
from tests.durable.conftest import FakeAccountRunStore

from .conftest import conn_session_factory, rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_db")

_FIELD = "account.test_signal"


class _Fake:
    tier = 1

    def __init__(self, claims: list[Claim]) -> None:
        self._claims = claims

    def resolve(self, entity: Entity, field: FieldDef) -> list[Claim]:
        return [c.model_copy(update={"entity_id": entity.entity_id}) for c in self._claims]


def test_real_worker_runs_inside_account_research_graph() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await register_field(
                conn,
                FieldDef(
                    field_key=_FIELD,
                    value_type="object",
                    tier_plan=("fake1",),
                    pass_kind=PassKind.DEEP,
                ),
            )
            await register_source(
                conn,
                RegistrySourceManifest(
                    manifest=SourceManifest(
                        source_key="fake1",
                        modality=Modality.STRUCTURED,
                        entity_scope=EntityScope.ACCOUNT,
                        yields=("account",),
                        tier=1,
                        cost_cents=Decimal(0),
                    ),
                    active=True,
                ),
            )
            claim = account_claim(
                entity_id=new_entity_id(),
                field_key=_FIELD,
                value_json={"summary": "x"},
                source_tier=1,
                extraction_method=ExtractionMethod.API,
                confidence=0.95,
                run_id=new_run_id(),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                source_url="https://example.com/x",
                evidence_span="evidence",
            )
            bind_resolver("fake1", _Fake([claim]))
            acct = await insert_account_entity(
                conn, canonical_name="Acme Robotics", primary_domain="acme-robotics.com"
            )

            # The graph dispatches by the field-class aspect key "account" — the same key the real
            # M7 build_plan clusters an account.* gap into. A single-aspect plan = one worker.
            store = FakeAccountRunStore(
                ResearchPlan(
                    tier="top",
                    aspects=(AspectPlan(aspect="account", field_keys=(_FIELD,)),),
                )
            )
            registry = WorkerRegistry()
            registry.register(
                AspectProfilingWorker("account", session_factory=conn_session_factory(conn))
            )
            graph = AccountResearchGraph(store=store, workers=registry)

            result = await graph.run(
                acct,
                tier="top",
                project_run_id=new_project_run_id(),
                checkpointer=InMemorySaver(),
            )

            assert result.status is AccountRunStatus.DONE
            assert len(result.references_index["account"]) == 1  # the worker's ref, collected

    run_async(_run())
