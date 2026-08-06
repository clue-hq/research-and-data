"""Fixture-backed proof that the Clue Trial uses the production run spine."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import SecretStr

from clue_api.entity_research_quarantine import EntityResearchAgentNotComposed
from clue_api.run_composition import ComposingRunDriver
from clue_api.stage0_trial import create_stage0_trial_session
from clue_api.storage_wiring import build_storage_backend
from clue_api.trial import ClueTrialSpine
from clue_config import GatewayConfig, load_settings
from clue_core import (
    Entity,
    EntityId,
    EntityType,
    FieldDef,
    ICPCreatedFrom,
    PassKind,
    ProjectPhase,
    WorkerStatus,
)
from clue_db import db_lifespan, transaction
from clue_gateway import build_gateway
from clue_research.claimstore import WorkspaceScope, claims_for
from clue_research.discovery_scoring.discovery import ChannelRegistry
from clue_research.durable import ProjectRunStatus
from clue_research.icp import (
    RubricEntry,
    ScoringRubric,
    ScoringTransform,
    SubRubric,
    create_icp_spec,
    rubric_to_slot,
)
from clue_research.icp.rubric import TierBand, TierCutoffs
from clue_research.profiling import AccountProfileResult
from clue_research.resolvers.sumble import (
    JOBS_SOURCE_KEY,
    MutableSumbleSnapshotLookup,
    SumbleClient,
    SumbleCreditBudget,
    build_sumble_resolvers,
)
from clue_spine import confirm_project_product
from tests.db.conftest import run_async

_FIXTURES = Path(__file__).parents[1] / "fixtures" / "clue_trial" / "sumble"


def _fixture(name: str) -> dict[str, Any]:
    value = json.loads((_FIXTURES / name).read_text())
    assert isinstance(value, dict)
    return value


class FixtureSumbleHttp:
    def __init__(self) -> None:
        self.calls: list[str] = []
        # Request bodies are retained so the test can prove the jobs call is keyed on the
        # organization id recovered from the organizations normalization, not on a default.
        self.bodies: list[dict[str, Any]] = []

    def __call__(self, url: str, **kwargs: Any) -> object:
        self.calls.append(url)
        body = kwargs.get("json_body")
        self.bodies.append(body if isinstance(body, dict) else {})
        if url.endswith("/organizations"):
            return _fixture("organizations_match.json")
        if url.endswith("/jobs"):
            return _fixture("jobs_engineering.json")
        if url.endswith("/techs"):
            return _fixture("tech_stack_confirmed.json")
        raise AssertionError(f"unexpected Sumble URL: {url}")


async def _fixture_account_profile(**kwargs: Any) -> AccountProfileResult:
    """Keep the phase/orchestrator/account-run path real with fixture-only provider output."""

    return AccountProfileResult(
        account_entity_id=kwargs["account_entity_id"],
        tier=kwargs["tier"],
        run_id=kwargs["run_id"],
        status=WorkerStatus.OK,
    )


def _rubric() -> ScoringRubric:
    return ScoringRubric(
        fit=SubRubric(
            entries=(
                RubricEntry(
                    field_key="core.employee_count",
                    transform=ScoringTransform.LINEAR,
                    params={"lo": 0, "hi": 500},
                ),
            )
        ),
        intent=SubRubric(),
        tier_cutoffs=TierCutoffs(
            bands=(TierBand(tier="high", min_fit=0.2, min_intent=0.0),),
            fallback_tier="low",
        ),
    )


@pytest.mark.usefixtures("require_profiling_db")
def test_sumble_fixture_reaches_real_tier_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        monkeypatch.setenv("CLUE_SUMBLE_API_KEY", "fixture-secret")
        session = f"spine-{uuid4().hex[:12]}"
        settings = load_settings(
            _env_file=None,
            gateway_allow_stub=True,
            storage_backend="fs",
            storage_fs_root=str(tmp_path / "artifacts"),
            c7_production_handoff_enabled=False,
            c7_research_view_read_enabled=True,
        )
        storage = build_storage_backend(settings)
        gateway = build_gateway(GatewayConfig(stub=True))
        driver = ComposingRunDriver(
            settings=settings,
            gateway=gateway,
            storage=storage,
            channels=ChannelRegistry(),
        )
        http = FixtureSumbleHttp()
        spine_snapshots = MutableSumbleSnapshotLookup()
        spine = ClueTrialSpine(
            settings=settings,
            gateway=gateway,
            storage=storage,
            snapshots=spine_snapshots,
            driver=driver,
            sumble_client_factory=lambda key, budget: SumbleClient(
                api_key=SecretStr(key.get_secret_value()),
                budget=SumbleCreditBudget(maximum=budget.maximum),
                http=http,
            ),
        )
        await spine.bootstrap()
        _, state = await create_stage0_trial_session(
            paths_root=tmp_path / "sessions",
            session_name=session,
            company_name="Trial Client",
            website="https://trial-client.example",
            product_name="Trial Product",
            project_name="Trial Project",
        )
        async with transaction() as conn:
            confirmed = await confirm_project_product(
                conn,
                workspace_id=state.workspace_id,
                project_id=state.project_id,
                product_id=state.product_id,
            )
            assert confirmed is not None
            spec = await create_icp_spec(
                conn,
                workspace_id=state.workspace_id,
                icp_key="sumble-trial",
                created_from=ICPCreatedFrom.CLIENT_EDIT,
                field_keys=(
                    "core.employee_count",
                    "core.primary_domain",
                    "account.hiring_velocity_eng",
                    "core.primary_tech_stack",
                ),
                scoring_rubric=rubric_to_slot(_rubric()),
                activate=True,
                client_entity_id=EntityId(state.client_entity_id),
                client_kb_version=state.client_kb_version,
                product_id=state.product_id,
            )
        run = await spine.prepare_project_run(
            state=state,
            icp_key=spec.icp_key,
            icp_version=spec.version,
            budget_cap_cents=Decimal(1000),
            readiness_override_reason="human approved a limited Sumble-only quality canary",
        )
        account_id = await spine.admit_direct_account(
            state=state,
            project_run=run,
            icp_key=spec.icp_key,
            icp_version=spec.version,
            domain="acme.example",
            name="Acme Health",
        )
        acquisition = await spine.acquire_sumble(
            state=state,
            project_run_id=run.project_run_id,
            account_entity_id=account_id,
            domain="acme.example",
            max_credits=3,
            allow_unbounded_tech=False,
        )
        assert acquisition.realized_credits == 3
        assert len(http.calls) == 2

        # The organizations select list must name every attribute the normalization keys on:
        # v9 returns only the selected attributes, so omitting id/url silently voids a paid
        # match (the live 2026-08-01 drift). Identity attributes are free, so the request stays
        # at its 1 base + 1 paid = 2 credit bound.
        organizations_select = http.bodies[0]["select"]["attributes"]
        assert set(organizations_select) >= {"id", "url", "sumble_url", "employee_count"}

        # The recovered id, not None, is what keys the dependent jobs call.
        assert acquisition.organization_id == 1726684
        assert http.bodies[1]["filter"]["organization_ids"] == [1726684]

        progress = await spine.drive_to_tier_checkpoint(
            project_run_id=run.project_run_id,
            account_entity_id=account_id,
        )
        assert progress.project_run.phase is ProjectPhase.TIER_CHECKPOINT
        assert progress.project_run.status is ProjectRunStatus.PAUSED
        assert progress.checkpoint is not None
        assert progress.checkpoint["scored_count"] == 1

        async with transaction() as conn:
            account_claims = await claims_for(
                conn,
                account_id,
                scope=WorkspaceScope.for_workspace(state.workspace_id),
            )
        by_field = {claim.field_key: claim for claim in account_claims}
        # The paid organization attribute is written as a real, evidence-backed value — not an
        # empty account produced by a silently discarded match.
        headcount = by_field["core.employee_count"]
        assert headcount.artifact_key is not None
        assert headcount.value_json == 120

        # Fit is scored over that real value, not over nothing: the rubric is LINEAR over
        # [0, 500], so 120 employees must score 0.24 and clear the 0.2 "high" band.
        fit = by_field["account.scoring.fit"]
        assert isinstance(fit.value_json, dict)
        fit_score = fit.value_json["value"]
        assert isinstance(fit_score, float)
        assert fit_score > 0.0
        assert fit_score == pytest.approx(0.24)

        assert "core.primary_domain" not in by_field
        assert "account.hiring_velocity_eng" not in by_field
        assert "core.primary_tech_stack" not in by_field

        # The jobs snapshot bound to this account normalizes its engineering-activity proxy from
        # the same recovered organization id. ``account.hiring_velocity_eng`` is a DEEP field
        # gated at tier>=3, so it is correctly absent at the tier checkpoint above; assert the
        # bound resolver's output directly rather than faking a deep-research write.
        jobs_resolver = build_sumble_resolvers(spine_snapshots)[JOBS_SOURCE_KEY]
        jobs_claims = jobs_resolver.resolve(
            Entity(entity_id=account_id, entity_type=EntityType.ACCOUNT),
            FieldDef(
                field_key="account.hiring_velocity_eng",
                value_type="number",
                pass_kind=PassKind.DEEP,
            ),
        )
        assert [claim.value_json for claim in jobs_claims] == [4]
        # The query contract is retained in the request artifact; claim evidence cites the exact
        # returned aggregate member from the immutable provider-response artifact.
        assert jobs_claims[0].evidence_span == '"total":4'

        # The S1 fixture proves discovery/scoring through the human tier checkpoint. R1 then
        # quarantines its retired pre-agent DEEP path: approval may not silently fall back to the
        # old account profiler while the replacement R5 agent composition is absent.
        with pytest.raises(EntityResearchAgentNotComposed):
            await spine.approve_direct_research(
                state=state,
                project_run_id=run.project_run_id,
                account_entity_id=account_id,
            )

    async def wrapped() -> None:
        async with db_lifespan():
            await scenario()

    run_async(wrapped())
