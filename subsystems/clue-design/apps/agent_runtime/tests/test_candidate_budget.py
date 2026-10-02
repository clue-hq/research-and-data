"""Candidate repair advice must distinguish a missed target from a hard stop."""

from dataclasses import replace

import pytest
from lumen_agent.budget import BudgetExhausted, RunBudget
from lumen_agent.tools.render import _render_preview_text
from test_render_preview_reuse import _authored_preview


def _budget(monkeypatch, *, elapsed=386.0, calls=29):
    clock = {"now": 0.0}
    monkeypatch.setattr("lumen_agent.budget.time.monotonic", lambda: clock["now"])
    budget = RunBudget(
        max_llm_calls=90, wall_clock_s=1800,
        target_llm_calls=20, target_wall_clock_s=240,
    )
    clock["now"] = elapsed
    for _ in range(calls):
        budget.check_and_count()
    return budget, clock


@pytest.mark.parametrize("elapsed,calls", [(10.0, 1), (386.0, 29), (1560.0, 78)])
def test_first_quality_repair_uses_hard_headroom_not_target(monkeypatch, elapsed, calls):
    """Even a 240s target leaves the first repair available after work begins."""
    budget, _ = _budget(monkeypatch, elapsed=elapsed, calls=calls)

    advice = budget.candidate_status_line(current_round=1)

    assert "If your current review identifies concrete defects" in advice
    assert "one focused repair round is available" in advice
    assert "round_2" in advice
    assert "headroom alone" in advice
    assert "budget_exhausted" not in advice
    assert budget.breach is None
    budget.check_and_count()  # Advice does not create a new hard cutoff.
    assert budget.calls == calls + 1


def test_target_overrun_remains_reported_without_becoming_exhaustion(monkeypatch):
    budget, _ = _budget(monkeypatch)
    before = budget.snapshot()

    advice = budget.candidate_status_line(current_round=1)

    assert "TARGET EXCEEDED" in advice
    assert "29 of 20 target model calls" in advice
    assert "386s of 240s used" in advice
    for private_limit in ("61 model calls", "1414s", "90", "1800"):
        assert private_limit not in advice
    assert before["max_llm_calls"] == 90
    assert before["wall_clock_s"] == 1800
    assert before["target_exceeded"]["kind"] == "wall_clock"
    assert before["exhausted"] is None
    assert budget.snapshot() == before


@pytest.mark.parametrize("current_round", [2, 3])
def test_a_second_quality_repair_is_not_advised(monkeypatch, current_round):
    budget, _ = _budget(monkeypatch)

    advice = budget.candidate_status_line(current_round=current_round)

    assert "Do not open another authoring round" in advice
    assert "one focused repair round is available" not in advice
    assert "accepted only if the current review passes" in advice
    assert "preserve an unaccepted draft" in advice


@pytest.mark.parametrize("elapsed,calls", [(1560.0, 79), (1560.1, 78)])
def test_repair_requires_both_hard_headroom_floors(monkeypatch, elapsed, calls):
    budget, _ = _budget(monkeypatch, elapsed=elapsed, calls=calls)

    advice = budget.candidate_status_line(current_round=1)

    assert "Do not open another authoring round" in advice
    assert "one focused repair round is available" not in advice
    assert "insufficient hard headroom" in advice


def test_round_zero_does_not_mistake_seed_inspection_for_finished_authoring(monkeypatch):
    budget, _ = _budget(monkeypatch, elapsed=10, calls=1)

    advice = budget.candidate_status_line(current_round=0)

    assert "Continue the initial authoring workflow" in advice
    assert "one focused repair round is available" not in advice
    assert "Finalize now" not in advice


def test_candidate_advice_does_not_change_either_hard_backstop(monkeypatch):
    budget, clock = _budget(monkeypatch, elapsed=386, calls=89)
    budget.candidate_status_line(current_round=1)
    budget.check_and_count()
    with pytest.raises(BudgetExhausted, match="90 calls made"):
        budget.check_and_count()

    budget, clock = _budget(monkeypatch, elapsed=1799, calls=1)
    budget.candidate_status_line(current_round=1)
    clock["now"] = 1800
    with pytest.raises(BudgetExhausted, match="1800.0s elapsed"):
        budget.check_and_count()


def test_legacy_status_line_is_unchanged(monkeypatch):
    budget, _ = _budget(monkeypatch)

    assert budget.status_line() == (
        "BUDGET LEFT: 29 of 20 model calls used, 0 left. "
        "6.4 of 4.0 minutes used, 0.0 left. "
        "You are PAST this turn's target. Nothing has stopped you and "
        "nothing is going to cut you off here. Do not open another "
        "authoring round. Keep the design that stands. record_gap what "
        "is still wrong. Finalize now."
    )


@pytest.mark.parametrize("bundle", ["legacy", "candidate"])
def test_director_render_routes_advice_without_changing_checkpoint(
    tmp_path, monkeypatch, bundle,
):
    """Catch either a lost candidate route or leaking it into the legacy view."""
    tools, persisted, round_one = _authored_preview(tmp_path, monkeypatch)
    tools.config = replace(tools.config, scene_skill_bundle=bundle)
    budget, _ = _budget(monkeypatch)

    result = _render_preview_text(tools, checkpoint=True, budget=budget)

    assert persisted.exists()
    assert (round_one / "preview.png").exists()
    if bundle == "candidate":
        assert "one focused repair round is available" in result
        # Resolve the real newest round directory, rather than assuming round 1.
        (round_one.parent / "round_2").mkdir()
        result = _render_preview_text(tools, checkpoint=True, budget=budget)
        assert "Do not open another authoring round" in result
        assert "one focused repair round is available" not in result
    else:
        assert result.endswith(budget.status_line())
        assert "one focused repair round is available" not in result


def test_author_renderer_still_has_no_budget_guidance(tmp_path, monkeypatch):
    tools, persisted, _ = _authored_preview(tmp_path, monkeypatch)
    tools.config = replace(tools.config, scene_skill_bundle="candidate")

    result = _render_preview_text(tools, checkpoint=False, budget=None)

    assert "BUDGET LEFT" not in result
    assert "one focused repair round is available" not in result
    assert not persisted.exists()


def test_candidate_advice_is_not_selected_for_a_noncheckpoint_renderer(tmp_path, monkeypatch):
    tools, persisted, _ = _authored_preview(tmp_path, monkeypatch)
    tools.config = replace(tools.config, scene_skill_bundle="candidate")
    budget, _ = _budget(monkeypatch)

    result = _render_preview_text(tools, checkpoint=False, budget=budget)

    assert result.endswith(budget.status_line())
    assert "one focused repair round is available" not in result
    assert not persisted.exists()
