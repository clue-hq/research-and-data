from datetime import UTC, datetime
from uuid import uuid4

import pytest

from clue_agents import ContextLayer
from clue_api.stage0_trial import (
    Stage0TrialPaths,
    Stage0TrialState,
    stage0_trial_context_policy,
)


def _state(slug: str = "quality-trial") -> Stage0TrialState:
    session_id = uuid4()
    return Stage0TrialState(
        session_id=session_id,
        session_slug=slug,
        workspace_id=f"s0-{slug}-12345678",
        brand_id="brand_trial",
        product_id="product_trial",
        project_id="project_trial",
        client_entity_id=uuid4(),
        client_kb_version=1,
        company_name="Example Company",
        website="https://example.invalid",
        product_name="Example Product",
        project_name="Example Stage 0 trial",
        thread_id=f"stage0-trial-{session_id.hex}",
        created_at=datetime.now(UTC),
    )


def test_trial_state_round_trips_through_private_report_handle(tmp_path) -> None:
    paths = Stage0TrialPaths.for_session(tmp_path, "quality-trial")
    expected = _state()

    paths.save_state(expected)

    assert paths.load_state() == expected
    assert paths.state.parent == tmp_path / "quality-trial"
    assert not (paths.state.parent / ".session.json.tmp").exists()


@pytest.mark.parametrize("slug", ("../escape", "Uppercase", "spaces are unsafe", ""))
def test_trial_paths_reject_unsafe_session_slugs(tmp_path, slug: str) -> None:
    with pytest.raises(ValueError, match="invalid Stage-0 trial session slug"):
        Stage0TrialPaths.for_session(tmp_path, slug)


def test_stage0_trial_context_budgets_every_layer_and_keeps_history_room() -> None:
    policy = stage0_trial_context_policy()

    assert tuple(item.layer for item in policy.budgets) == tuple(ContextLayer)
    assert policy.budget_for(ContextLayer.L4_MEMORY) > 0
    assert policy.budget_for(ContextLayer.L6_CONVERSATION) > policy.budget_for(ContextLayer.L7_TURN)
