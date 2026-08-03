from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from clue_agents import ContextLayer
from clue_api.account_research_turn_wiring import (
    DbCompiledContextCardReader,
    _effective_budget_limit,
    account_research_context_policy,
)
from clue_api.agent_platform_wiring import (
    AgentCanarySample,
    AgentOwner,
    AgentRuntimeSurface,
    DbAgentOwnershipRouter,
    evaluate_agent_canary,
    run_owned_agent_surface,
)
from clue_api.fleet_main import _account_agent_runtime_required
from clue_config import Settings
from clue_research.durable import AspectPlan, ResearchPlan
from clue_research.identity import insert_account_entity
from tests._workspace import seed_project, seed_workspace
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)


@pytest.fixture
def require_c68_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_agent_rollout_defaults_are_off_and_validated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    assert not settings.agent_runtime_routing_enabled
    assert not settings.agent_stage0_routing_enabled
    assert not settings.agent_account_routing_enabled
    assert settings.agent_workspace_allowlist == ()
    assert settings.agent_canary_percent == 0
    assert settings.agent_account_plan_budget_limit_millicents == 1_000_000

    with pytest.raises(ValueError):
        _settings(agent_canary_percent=101)
    with pytest.raises(ValueError):
        _settings(agent_workspace_retention_s=-1)
    with pytest.raises(ValueError):
        _settings(agent_account_plan_budget_limit_millicents=-1)

    monkeypatch.setenv("CLUE_AGENT_WORKSPACE_ALLOWLIST", '["ws-a","ws-b"]')
    assert _settings().agent_workspace_allowlist == ("ws-a", "ws-b")


def test_account_context_policy_freezes_all_seven_layers_and_fresh_wake() -> None:
    policy = account_research_context_policy()
    assert tuple(item.layer for item in policy.budgets) == tuple(ContextLayer)
    assert policy.budget_for(ContextLayer.L4_MEMORY) == 8_000
    assert policy.budget_for(ContextLayer.L6_CONVERSATION) == 0


def test_account_agent_plan_budget_uses_the_strictest_durable_ceiling() -> None:
    plan = ResearchPlan(
        tier="high",
        aspects=(
            AspectPlan(
                aspect="account",
                field_keys=("account.name",),
                budget_envelope_cents=Decimal("5"),
            ),
        ),
    )
    assert (
        _effective_budget_limit(
            _settings(agent_account_plan_budget_limit_millicents=20_000),
            budget_cap_cents=Decimal("10"),
            plan=plan,
        )
        == 5_000
    )


def test_durable_owner_is_sticky_across_configuration_changes(
    require_c68_db: None,
) -> None:
    del require_c68_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id = "ws-c68-routing"
            await seed_workspace(conn, workspace_id)
            factory = conn_session_factory(conn)
            assert not await _account_agent_runtime_required(
                _settings(),
                conn_factory=factory,
            )
            enabled = DbAgentOwnershipRouter(
                settings=_settings(
                    agent_runtime_routing_enabled=True,
                    agent_account_routing_enabled=True,
                    agent_workspace_allowlist=(workspace_id,),
                ),
                conn_factory=factory,
            )
            first = await enabled.claim(
                workspace_id=workspace_id,
                surface=AgentRuntimeSurface.ACCOUNT_RESEARCH,
                subject_id="account-run-1",
            )
            assert first.owner is AgentOwner.DEEPAGENT
            assert first.selection_source == "allowlist"
            assert await _account_agent_runtime_required(
                _settings(),
                conn_factory=factory,
            )

            disabled = DbAgentOwnershipRouter(settings=_settings(), conn_factory=factory)
            replay = await disabled.claim(
                workspace_id=workspace_id,
                surface=AgentRuntimeSurface.ACCOUNT_RESEARCH,
                subject_id="account-run-1",
            )
            assert replay == first

            savepoint = await conn.begin_nested()
            try:
                with pytest.raises(DBAPIError):
                    await conn.execute(
                        text("UPDATE agent_runtime_route SET owner='legacy' WHERE id=:route_id"),
                        {"route_id": first.route_id},
                    )
            finally:
                await savepoint.rollback()

    run_async(scenario())


def test_compiled_context_cards_are_typed_and_workspace_scoped(
    require_c68_db: None,
) -> None:
    del require_c68_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id = "ws-c68-cards"
            project = await seed_project(conn, workspace_id)
            account_id = await insert_account_entity(
                conn,
                workspace_id=workspace_id,
                canonical_name="C68 Account",
                primary_domain="c68.example",
            )
            reader = DbCompiledContextCardReader(conn_factory=conn_session_factory(conn))
            project_card = await reader.read(
                workspace_id=workspace_id,
                object_type="project",
                object_id=project.project_id,
            )
            account_card = await reader.read(
                workspace_id=workspace_id,
                object_type="account",
                object_id=str(account_id),
            )
            assert project_card is not None
            assert project_card.ref.object_type == "project"
            assert account_card is not None
            assert "C68 Account" in account_card.body
            assert (
                await reader.read(
                    workspace_id="another-workspace",
                    object_type="account",
                    object_id=str(account_id),
                )
                is None
            )
            assert (
                await reader.read(
                    workspace_id=workspace_id,
                    object_type="unsupported",
                    object_id="anything",
                )
                is None
            )

    run_async(scenario())


class _ClaimingRouter:
    def __init__(self, owner: AgentOwner) -> None:
        self.owner = owner

    async def claim(
        self,
        *,
        workspace_id: str,
        surface: AgentRuntimeSurface,
        subject_id: str,
    ):
        del workspace_id, subject_id
        from clue_api.agent_platform_wiring import AgentRouteDecision

        return AgentRouteDecision(
            route_id=UUID("00000000-0000-0000-0000-000000000680"),
            workspace_id="ws",
            surface=surface,
            subject_id="subject",
            owner=self.owner,
            selection_source=(
                "allowlist" if self.owner is AgentOwner.DEEPAGENT else "not_selected"
            ),
            cohort_bucket=None if self.owner is AgentOwner.DEEPAGENT else 99,
            configured_percent=1,
            config_sha256="a" * 64,
        )


def test_routed_surface_executes_one_owner_and_never_falls_back() -> None:
    async def scenario() -> None:
        calls: list[str] = []

        async def agent() -> str:
            calls.append("agent")
            raise RuntimeError("visible agent failure")

        async def legacy() -> str:
            calls.append("legacy")
            return "legacy"

        with pytest.raises(RuntimeError, match="visible agent failure"):
            await run_owned_agent_surface(
                router=_ClaimingRouter(AgentOwner.DEEPAGENT),
                workspace_id="ws",
                surface=AgentRuntimeSurface.STAGE0,
                subject_id="thread-1",
                deepagent=agent,
                legacy=legacy,
            )
        assert calls == ["agent"]

        calls.clear()
        result = await run_owned_agent_surface(
            router=_ClaimingRouter(AgentOwner.LEGACY),
            workspace_id="ws",
            surface=AgentRuntimeSurface.ACCOUNT_RESEARCH,
            subject_id="run-1",
            deepagent=agent,
            legacy=legacy,
        )
        assert result == "legacy"
        assert calls == ["legacy"]

    run_async(scenario())


@pytest.mark.parametrize(
    ("candidate", "passed", "reason"),
    [
        (
            AgentCanarySample(
                completed=True,
                failure_visible=True,
                terminal_items=10,
                promotable_refs=8,
                verified_refs=7,
                cost_millicredits=110,
                rounds=3,
                duplicate_effects=0,
            ),
            True,
            None,
        ),
        (
            AgentCanarySample(
                completed=False,
                failure_visible=False,
                terminal_items=10,
                promotable_refs=8,
                verified_refs=7,
                cost_millicredits=110,
                rounds=3,
                duplicate_effects=0,
            ),
            False,
            "failed_turn_not_visible",
        ),
        (
            AgentCanarySample(
                completed=True,
                failure_visible=True,
                terminal_items=10,
                promotable_refs=8,
                verified_refs=7,
                cost_millicredits=110,
                rounds=3,
                duplicate_effects=1,
            ),
            False,
            "duplicate_effects",
        ),
    ],
)
def test_canary_comparison_fails_closed(
    candidate: AgentCanarySample,
    passed: bool,
    reason: str | None,
) -> None:
    baseline = AgentCanarySample(
        completed=True,
        failure_visible=True,
        terminal_items=10,
        promotable_refs=8,
        verified_refs=7,
        cost_millicredits=100,
        rounds=2,
        duplicate_effects=0,
    )
    result = evaluate_agent_canary(baseline=baseline, candidate=candidate)
    assert result.passed is passed
    if reason is not None:
        assert reason in result.reason_codes
