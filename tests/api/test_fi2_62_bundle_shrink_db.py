"""FI-2 §6.2 — the provider bundle shrinks to what the workspace does not already know.

§6.1 (Task 2) made the account runtime *report* born-complete fields; on its own that only saves
the agent a turn. The money is saved here: the Exa Deep bundle is compiled straight from the
directive's admitted account-axis fields, so unless the compiler subtracts the borrowed set, a
second project pays Exa to re-derive a fact the first project already put on file.

Three behaviours are pinned:

* a borrowed field never enters the bundle (and its directional question goes with it);
* an account-axis bundle that shrinks to nothing reserves **nothing** — no operation row, no HTTP,
  and a reason code that says *why* it is empty rather than reporting an authorization that is not
  actually missing;
* the borrowed set is exactly ``born_complete`` — a **stale** claim (or one with no evidence span)
  is not "already known" and its field stays in the bundle.

The borrowed set comes from ``born_complete_account_field_keys``, the same derivation the §6.1
state read and the R5 first-call guard use, so the guard's "first Exa call must include every
primary Exa field" rule and the bundle's contents cannot disagree.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.account_research_wiring import AccountResolverBindingAvailability
from clue_api.exa_deep_acquisition import ExaDeepAcquisitionCoordinator
from clue_api.exa_deep_preparation import ExaDeepAccountResolverProvider
from clue_api.trial.account_deep_fixture import (
    ACCOUNT_NAME,
    DEEP_FIELD_KEYS,
    seed_insight_health_account_deep_fixture,
)
from clue_api.trial.discovery_fixture import PRODUCT_ID, PROJECT_ID, WORKSPACE_ID
from clue_config import Settings
from clue_core import (
    Claim,
    EntityId,
    EntityType,
    ExtractionMethod,
    ResearchMode,
    ResearchQuestion,
    ReuseScope,
    RunId,
    new_operation_id,
)
from clue_research.claimstore import insert_claim
from clue_research.durable import create_account_deep_launch
from clue_research.resolvers.exa import ExaDeepSearchRequest, exa_field_alias
from clue_research.verification import PreSpendGateImpl
from clue_storage import FsStorage
from tests.api.account_deep_test_support import confirmed_account_research_direction
from tests.api.test_account_deep_fixture_a1 import _pages, _TaskReentrantConnectionFactory
from tests.db.conftest import run_async
from tests.stage0.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_EXA_RESPONSE = (
    Path(__file__).parents[1] / "fixtures" / "providers" / "exa" / "search" / "deep_response.json"
)

#: The four admitted account-axis fields whose effective source plan selects Exa Deep. (The fifth
#: shipped deep field, ``core.primary_tech_stack``, is a structured-source field and is left out of
#: the direction exactly as the O2 acceptance test leaves it out.)
_EXA_FIELDS = (DEEP_FIELD_KEYS[0], *DEEP_FIELD_KEYS[2:])
_PAIN = DEEP_FIELD_KEYS[2]  # account.operational_pain — neutral, 90d TTL

#: Schema-valid values per admitted field (``account.hiring_velocity_eng`` is a number).
_KNOWN_VALUES: Mapping[str, Any] = {
    DEEP_FIELD_KEYS[0]: 7,
    DEEP_FIELD_KEYS[2]: "Referral intake is still fax-driven across three offices.",
    DEEP_FIELD_KEYS[3]: "Opening a fourth office and consolidating intake.",
    DEEP_FIELD_KEYS[4]: "Small, tenured, referral-relationship-driven culture.",
}


class _ExaTransport:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self._payload = payload
        self.calls: list[object] = []

    def search(self, request: object) -> Mapping[str, Any]:
        self.calls.append(request)
        return self._payload


def _payload_for(field_keys: Sequence[str]) -> dict[str, Any]:
    """The recorded E1 response, narrowed to exactly the requested closed output contract.

    Grounding is narrowed with it: the provider contract refuses a response whose grounding names
    a field the content does not carry, which is precisely what a shrunk bundle produces.
    """

    payload = json.loads(_EXA_RESPONSE.read_text(encoding="utf-8"))
    payload["costDollars"]["total"] = 0.07
    recorded = dict(payload["output"]["content"])
    aliases = [exa_field_alias(field_key) for field_key in field_keys]
    payload["output"]["content"] = {alias: recorded.get(alias) for alias in aliases}
    payload["output"]["grounding"] = [
        item
        for item in payload["output"]["grounding"]
        if item["field"] in aliases and recorded.get(item["field"]) is not None
    ]
    return payload


async def _known_claim(
    conn: AsyncConnection,
    *,
    account_id: EntityId,
    field_key: str,
    run_id: RunId,
    age: timedelta,
    evidence_span: str | None = "The first project's own sourced evidence.",
) -> UUID:
    """One claim an earlier project already wrote about this account."""

    collected_at = datetime.now(UTC) - age
    claim = Claim(
        entity_id=account_id,
        entity_type=EntityType.ACCOUNT,
        field_key=field_key,
        value_json=_KNOWN_VALUES[field_key],
        source_url="https://insighthealth.ai/about",
        # A structured, already-settled source: an ``exa_deep`` claim would need full
        # operation/snapshot/artifact lineage, which is not what this test is about.
        source_key="sumble_jobs",
        source_tier=cast(Any, 2),
        extraction_method=ExtractionMethod.API,
        evidence_span=evidence_span,
        confidence=cast(Any, 0.9),
        observed_at=collected_at,
        collected_at=collected_at,
        run_id=run_id,
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        reuse_scope=ReuseScope.TENANT_PRIVATE,
        workspace_id=WORKSPACE_ID,
    )
    return UUID(str(await insert_claim(conn, claim)))


async def _confirmed_direction(conn: AsyncConnection, account_id: EntityId, *, icp: Any) -> Any:
    _, account_spec = await confirmed_account_research_direction(
        conn,
        workspace_id=WORKSPACE_ID,
        project_id=PROJECT_ID,
        product_id=PRODUCT_ID,
        account_id=account_id,
        icp_key=icp[0],
        icp_version=icp[1],
        field_keys=_EXA_FIELDS,
        questions=(
            ResearchQuestion(
                question_id="account-workflow",
                text="Find exact-account workflow friction.",
                target_field_key=_PAIN,
            ),
            ResearchQuestion(
                question_id="account-strategy",
                text="Find exact-account strategic moves.",
                target_field_key=DEEP_FIELD_KEYS[3],
            ),
        ),
    )
    return account_spec


def _provider(
    *, storage: FsStorage, conn_factory: Any, transport: _ExaTransport
) -> ExaDeepAccountResolverProvider:
    return ExaDeepAccountResolverProvider(
        settings=Settings(_env_file=None, exa_account_deep_acquisition_enabled=True),
        storage=storage,
        pre_spend_gate=PreSpendGateImpl(conn_factory=conn_factory),
        coordinator=ExaDeepAcquisitionCoordinator(
            transport=transport,
            storage=storage,
            conn_factory=conn_factory,
        ),
        conn_factory=conn_factory,
    )


async def _launch(conn: AsyncConnection, fixture: Any, pin: Any) -> None:
    await create_account_deep_launch(
        conn,
        workspace_id=WORKSPACE_ID,
        project_run_id=fixture.project_run_id,
        directive_id=pin.directive_id,
        account_entity_ids=(fixture.selected_account_id,),
        approved_budget_cap_cents=Decimal("300"),
        expected_estimated_cost_cents=Decimal("300"),
        created_by="human:fi2-62",
        source_operation_id=new_operation_id(),
        source_action_ref="turn:fi2-62-launch",
    )


async def _operations(conn: AsyncConnection) -> int:
    return int(
        (
            await conn.execute(
                text(
                    "SELECT count(*) FROM external_research_operation "
                    "WHERE workspace_id=:workspace_id"
                ),
                {"workspace_id": WORKSPACE_ID},
            )
        ).scalar_one()
    )


def test_fi2_62_a_born_complete_field_never_enters_the_exa_bundle(tmp_path: Path) -> None:
    """One borrowed field: its schema property and its directional question both disappear."""

    async def scenario() -> None:
        async with rollback_conn(seed=False) as conn:
            storage = FsStorage(tmp_path / "artifacts")
            fixture = await seed_insight_health_account_deep_fixture(
                conn, pages=_pages(), storage=storage
            )
            account_spec = await _confirmed_direction(
                conn,
                fixture.selected_account_id,
                icp=(fixture.deep_icp_key, fixture.deep_icp_version),
            )
            pin = account_spec.research_directive
            assert pin is not None
            await _launch(conn, fixture, pin)
            await _known_claim(
                conn,
                account_id=fixture.selected_account_id,
                field_key=_PAIN,
                run_id=RunId(fixture.project_run_id),
                age=timedelta(days=1),
            )

            expected = tuple(field_key for field_key in _EXA_FIELDS if field_key != _PAIN)
            transport = _ExaTransport(_payload_for(expected))
            conn_factory = _TaskReentrantConnectionFactory(conn)
            acquired = await _provider(
                storage=storage, conn_factory=conn_factory, transport=transport
            ).resolver_bindings(
                workspace_id=WORKSPACE_ID,
                project_run_id=fixture.project_run_id,
                account_entity_id=fixture.selected_account_id,
                research_directive=pin,
            )

            assert acquired.availability is AccountResolverBindingAvailability.READY
            assert len(transport.calls) == 1
            request = transport.calls[0]
            assert isinstance(request, ExaDeepSearchRequest)
            assert set(request.output_schema["properties"]) == {
                exa_field_alias(field_key) for field_key in expected
            }
            # The question that only existed to answer the borrowed field goes with it.
            assert request.additional_queries == (
                f"{ACCOUNT_NAME} Find exact-account strategic moves.",
            )
            # The skip is audited on the binding, so the ledger can explain the smaller bill.
            assert f"{_PAIN}:existing_claim_fresh" in acquired.audit_refs

    run_async(scenario())


def test_fi2_62_an_all_borrowed_account_axis_reserves_nothing(tmp_path: Path) -> None:
    """The §6.2 win: no bundle, no operation row, no HTTP — and an honest reason code."""

    async def scenario() -> None:
        async with rollback_conn(seed=False) as conn:
            storage = FsStorage(tmp_path / "artifacts")
            fixture = await seed_insight_health_account_deep_fixture(
                conn, pages=_pages(), storage=storage
            )
            account_spec = await _confirmed_direction(
                conn,
                fixture.selected_account_id,
                icp=(fixture.deep_icp_key, fixture.deep_icp_version),
            )
            pin = account_spec.research_directive
            assert pin is not None
            await _launch(conn, fixture, pin)
            for field_key in _EXA_FIELDS:
                await _known_claim(
                    conn,
                    account_id=fixture.selected_account_id,
                    field_key=field_key,
                    run_id=RunId(fixture.project_run_id),
                    age=timedelta(days=1),
                )
            before = await _operations(conn)

            transport = _ExaTransport(_payload_for(()))
            conn_factory = _TaskReentrantConnectionFactory(conn)
            bindings = await _provider(
                storage=storage, conn_factory=conn_factory, transport=transport
            ).resolver_bindings(
                workspace_id=WORKSPACE_ID,
                project_run_id=fixture.project_run_id,
                account_entity_id=fixture.selected_account_id,
                research_directive=pin,
            )

            assert bindings.availability is AccountResolverBindingAvailability.NOT_APPLICABLE
            assert bindings.reason_code == "exa_deep_all_fields_already_known"
            assert transport.calls == []
            assert await _operations(conn) == before
            assert set(bindings.audit_refs) == {
                f"{field_key}:existing_claim_fresh" for field_key in _EXA_FIELDS
            }

    run_async(scenario())


@pytest.mark.parametrize(
    ("age", "evidence_span", "why"),
    [
        (timedelta(days=200), "The first project's own sourced evidence.", "stale"),
        (timedelta(days=1), None, "no evidence span"),
    ],
)
def test_fi2_62_only_a_born_complete_claim_shrinks_the_bundle(
    tmp_path: Path, age: timedelta, evidence_span: str | None, why: str
) -> None:
    """Not-born-complete is not "already known": the field stays in the bundle and gets bought."""

    async def scenario() -> None:
        async with rollback_conn(seed=False) as conn:
            storage = FsStorage(tmp_path / "artifacts")
            fixture = await seed_insight_health_account_deep_fixture(
                conn, pages=_pages(), storage=storage
            )
            account_spec = await _confirmed_direction(
                conn,
                fixture.selected_account_id,
                icp=(fixture.deep_icp_key, fixture.deep_icp_version),
            )
            pin = account_spec.research_directive
            assert pin is not None
            await _launch(conn, fixture, pin)
            await _known_claim(
                conn,
                account_id=fixture.selected_account_id,
                field_key=_PAIN,
                run_id=RunId(fixture.project_run_id),
                age=age,
                evidence_span=evidence_span,
            )

            transport = _ExaTransport(_payload_for(_EXA_FIELDS))
            conn_factory = _TaskReentrantConnectionFactory(conn)
            acquired = await _provider(
                storage=storage, conn_factory=conn_factory, transport=transport
            ).resolver_bindings(
                workspace_id=WORKSPACE_ID,
                project_run_id=fixture.project_run_id,
                account_entity_id=fixture.selected_account_id,
                research_directive=pin,
            )

            assert acquired.availability is AccountResolverBindingAvailability.READY, why
            request = transport.calls[0]
            assert isinstance(request, ExaDeepSearchRequest)
            assert exa_field_alias(_PAIN) in request.output_schema["properties"], why
            assert not any("existing_claim_fresh" in ref for ref in acquired.audit_refs), why

    run_async(scenario())
