"""Fixture-backed proof that the Clue Trial uses the production run spine."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import SecretStr

from clue_api.run_composition import ComposingRunDriver
from clue_api.stage0_trial import create_stage0_trial_session
from clue_api.storage_wiring import build_storage_backend
from clue_api.trial import ClueTrialSpine
from clue_config import GatewayConfig, load_settings
from clue_core import EntityId, ICPCreatedFrom, ProjectPhase, WorkerStatus
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
from clue_research.resolvers.sumble import SumbleClient, SumbleCreditBudget
from clue_spine import confirm_project_product
from tests.db.conftest import run_async
from tests.lock_factory import ProcessLocalLockFactory

_FIXTURES = Path(__file__).parents[1] / "fixtures" / "clue_trial" / "sumble"


def _fixture(name: str) -> dict[str, Any]:
    value = json.loads((_FIXTURES / name).read_text())
    assert isinstance(value, dict)
    return value


class FixtureSumbleHttp:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, url: str, **kwargs: Any) -> object:
        del kwargs
        self.calls.append(url)
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
        )
        storage = build_storage_backend(settings)
        gateway = build_gateway(GatewayConfig(stub=True))
        driver = ComposingRunDriver(
            settings=settings,
            gateway=gateway,
            storage=storage,
            lock_factory=ProcessLocalLockFactory(),
            channels=ChannelRegistry(),
            committee_sources=(),
            profile_account_fn=_fixture_account_profile,
        )
        http = FixtureSumbleHttp()
        spine = ClueTrialSpine(
            settings=settings,
            gateway=gateway,
            storage=storage,
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
        assert by_field["core.employee_count"].artifact_key is not None
        assert "core.primary_domain" not in by_field
        assert "account.hiring_velocity_eng" not in by_field
        assert "core.primary_tech_stack" not in by_field

        completed = await spine.approve_direct_research(
            state=state,
            project_run_id=run.project_run_id,
            account_entity_id=account_id,
        )
        assert completed.project_run.status is not ProjectRunStatus.FAILED
        assert completed.project_run.phase in (ProjectPhase.REVIEW, ProjectPhase.HANDOFF)
        assert completed.research_view is not None
        subject = completed.research_view["subject"]
        assert isinstance(subject, dict)
        assert subject["entity_id"] == str(account_id)

    async def wrapped() -> None:
        async with db_lifespan():
            await scenario()

    run_async(wrapped())
