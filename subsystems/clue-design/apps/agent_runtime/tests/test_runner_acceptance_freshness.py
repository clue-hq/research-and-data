"""The runner must not return old acceptance for the live scene handed to the API."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from agent_fixtures import prepare_acceptance_evidence, runtime_config
from lumen_agent import harness
from lumen_agent.budget import BUDGET_LLM_CALLS, BudgetExhausted
from lumen_agent.cancellation import TurnCancelled
from lumen_agent.tools import substrate
from lumen_api import core as core_module


ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / "target" / "release" / "lumen-api-helper"
pytestmark = pytest.mark.skipif(not HELPER.exists(), reason="release helper not built")


def _run(tmp_path, monkeypatch, *, after_final=None, final_status="accepted"):
    monkeypatch.setattr(core_module.settings, "lumen_core_helper", str(HELPER))
    core = core_module.CoreClient(repo_root=ROOT)
    monkeypatch.setattr(substrate, "CoreClient", lambda **_: core)
    tools = substrate.LumenDesignTools(runtime_config(tmp_path), "Color panel")
    finalized = {}

    def invoke(*_args, **_kwargs):
        assert json.loads(tools.compile_dsl_block("""page square size(1080,1080,px)
  hero fr p(100,100) s(800,800) fill(#ff0000)
"""))["compile"]["status"] == "ok"
        prepare_acceptance_evidence(tools)
        finalized.update(json.loads(tools.finalize_run(final_status, "accepted", "Reviewed red panel.")))
        assert finalized["status"] == final_status
        if after_final is not None:
            after_final(tools)
        return {"messages": []}

    monkeypatch.setattr(
        harness, "create_design_deepagent",
        lambda *_args, **_kwargs: (SimpleNamespace(invoke=invoke), tools),
    )
    result, returned_tools = harness.run_deepagent_turn("Color panel", tools.config)
    assert returned_tools is tools
    return result, tools, finalized


@pytest.mark.parametrize("change", ["scene", "preview_bytes", "new_review_without_finalize"])
def test_runner_downgrades_acceptance_if_finalized_evidence_changed(tmp_path, monkeypatch, change):
    def after_final(tools):
        if change == "preview_bytes":
            path = Path(tools.latest_export_summary["artifacts"][0]["path"])
            path.write_bytes(path.read_bytes() + b"\n<!-- changed after review -->")
            return
        assert json.loads(tools.compile_dsl_block("#hero fill(#0000ff)"))["compile"]["status"] == "ok"
        if change == "new_review_without_finalize":
            # The same critique prose may be reused for genuinely new evidence.
            # The old final payload must still be bound to its original receipt.
            prepare_acceptance_evidence(tools)

    result, tools, original = _run(tmp_path, monkeypatch, after_final=after_final)
    assert original["status"] == "accepted"
    assert result["status"] == "completed_with_warnings"
    assert result["stop_reason"] == "acceptance_stale_at_return"
    assert result.get("acceptance_receipt") is None
    assert tools.scene["nodes"] and tools.operations_ledger
    assert json.loads((tools.trace_dir / "final.json").read_text()) == result
    assert json.loads((tools.trace_dir / "final_scene.json").read_text()) == tools.scene


@pytest.mark.parametrize("late_stop", [None, "budget", "cancel"])
def test_runner_preserves_fresh_acceptance_after_graph_exit(tmp_path, monkeypatch, late_stop):
    def after_final(_tools):
        if late_stop == "budget":
            raise BudgetExhausted(BUDGET_LLM_CALLS, 45, 45)
        if late_stop == "cancel":
            raise TurnCancelled()

    result, _tools, original = _run(tmp_path, monkeypatch, after_final=after_final)
    assert result == original
    assert result["status"] == "accepted"


def test_runner_preserves_nonaccepted_draft_result(tmp_path, monkeypatch):
    result, _tools, original = _run(tmp_path, monkeypatch, final_status="completed_with_warnings")
    assert result == original


@pytest.mark.parametrize("late_stop", ["budget", "cancel"])
def test_runner_downgrades_mutated_acceptance_despite_late_interrupt(tmp_path, monkeypatch, late_stop):
    def after_final(tools):
        assert json.loads(tools.compile_dsl_block("#hero fill(#0000ff)"))["compile"]["status"] == "ok"
        if late_stop == "budget":
            raise BudgetExhausted(BUDGET_LLM_CALLS, 45, 45)
        raise TurnCancelled()

    result, tools, _original = _run(tmp_path, monkeypatch, after_final=after_final)
    assert result["status"] == "completed_with_warnings"
    assert result["stop_reason"] == "acceptance_stale_at_return"
    assert result.get("acceptance_receipt") is None
    assert tools.scene["nodes"]


@pytest.fixture
def live_core_tools(tmp_path, monkeypatch):
    monkeypatch.setattr(core_module.settings, "lumen_core_helper", str(HELPER))
    core = core_module.CoreClient(repo_root=ROOT)
    monkeypatch.setattr(substrate, "CoreClient", lambda **_: core)
    return substrate.LumenDesignTools(runtime_config(tmp_path), "Color panel")


def _compile_panel(tools, *, blocked=False):
    radius = "$radius.pill" if blocked else "100"
    result = json.loads(tools.compile_dsl_block(
        f"page square size(1080,1080,px)\n  hero fr p(100,100) s(800,800) fill(#ff0000) rd({radius})\n"
    ))
    assert result["compile"]["status"] == "ok"


def _interrupt(tools, stop):
    if stop == "budget":
        return harness._finalize_on_budget_exhausted(
            tools, BudgetExhausted(BUDGET_LLM_CALLS, 45, 45)
        )
    return harness._finalize_on_cancelled(tools, TurnCancelled())


@pytest.mark.parametrize("stop", ["budget", "cancel"])
def test_interrupted_repaired_draft_keeps_old_failure_only_as_history(live_core_tools, stop):
    """Google control: rejected token failure, repair/render, then unverified geometry."""
    tools = live_core_tools
    _compile_panel(tools, blocked=True)
    failed = json.loads(tools.preflight_design())
    assert failed["preflight"]["has_errors"]
    assert any(d["code"] == "LUMB0301" for d in failed["preflight"]["diagnostics"])
    # The bare helper can render numeric-token fallback pixels; the failed
    # preflight still forbids acceptance. The saved control had an export
    # failure too, but this fixture does not pretend to reproduce that detail.
    assert json.loads(tools.export_preview("svg"))["export"]["status"] == "ok"
    review = {
        "accepted": False,
        "summary": "Current scene cannot export: radius.pill is unresolved.",
        "issues": [{"severity": "error", "category": "brand_fit",
                    "message": "radius.pill is unresolved.",
                    "suggested_repair": "Use a numeric corner radius."}],
    }
    assert json.loads(tools.submit_visual_critique(json.dumps(review)))["status"] == "ok"
    reviewed_iteration = tools.iteration
    assert json.loads(tools.compile_dsl_block("#hero rd(100)"))["compile"]["status"] == "ok"
    assert not json.loads(tools.preflight_design())["preflight"]["has_errors"]
    assert json.loads(tools.export_preview("svg"))["export"]["status"] == "ok"
    assert json.loads(tools.compile_dsl_block("#hero p(100,120)"))["compile"]["status"] == "ok"

    result = _interrupt(tools, stop)

    assert result["critique"] == {}
    assert result["historical_critique"]["critique"]["summary"] == review["summary"]
    assert result["historical_critique"]["iteration"] == reviewed_iteration
    assert result["historical_critique"]["status"] == "stale"
    verification = result["draft_verification"]
    assert [verification[name]["status"] for name in ("preflight", "preview", "review")] == [
        "stale", "stale", "stale"
    ]
    assert verification["preflight"]["has_blocking_errors"] is None
    assert verification["preflight"]["diagnostics"] == []
    assert "awaits review" in result["summary"]
    assert "cannot export" not in result["summary"]
    assert result["status"] == "completed_with_warnings"
    assert result["acceptance_receipt"] is None
    assert tools.scene["nodes"]["hero"]["corner"] == {
        "top_left": 100, "top_right": 100, "bottom_left": 100, "bottom_right": 100,
    }
    assert tools.operations_ledger


@pytest.mark.parametrize("stop", ["budget", "cancel"])
@pytest.mark.parametrize("checked", [False, True])
def test_interrupted_newborn_blocked_draft_never_claims_clean(live_core_tools, stop, checked):
    tools = live_core_tools
    _compile_panel(tools, blocked=True)
    if checked:
        assert json.loads(tools.preflight_design())["preflight"]["has_errors"]

    result = _interrupt(tools, stop)

    verification = result["draft_verification"]
    assert verification["preflight"]["status"] == ("current" if checked else "missing")
    assert verification["preflight"]["has_blocking_errors"] is (True if checked else None)
    assert verification["preview"]["status"] == "missing"
    assert verification["review"]["status"] == "missing"
    assert result["status"] == "completed_with_warnings"
    assert result["acceptance_receipt"] is None
    assert tools.scene["nodes"]


def test_current_rejected_draft_reports_clean_preflight_without_acceptance(live_core_tools):
    tools = live_core_tools
    _compile_panel(tools)
    prepare_acceptance_evidence(tools, {"accepted": False, "summary": "Spacing needs work.", "issues": []})

    result = json.loads(tools.finalize_run(
        "completed_with_warnings", "target_exceeded", "Old compile error still blocks export."
    ))

    verification = result["draft_verification"]
    assert [verification[name]["status"] for name in ("preflight", "preview", "review")] == [
        "current", "current", "current"
    ]
    assert verification["preflight"]["has_blocking_errors"] is False
    assert result["critique"]["summary"] == "Spacing needs work."
    assert "Spacing needs work." in result["summary"]
    assert "Old compile error" not in result["summary"]
    assert result["historical_critique"] is None
    assert result["acceptance_receipt"] is None


@pytest.mark.parametrize("change", ["scene", "preview_bytes"])
def test_runner_refreshes_warning_verification_after_finalize(tmp_path, monkeypatch, change):
    def after_final(tools):
        if change == "scene":
            assert json.loads(tools.compile_dsl_block("#hero p(100,140)"))["compile"]["status"] == "ok"
        else:
            path = Path(tools.latest_export_summary["artifacts"][0]["path"])
            path.write_bytes(path.read_bytes() + b"\n<!-- changed after warning finalize -->")

    result, tools, original = _run(
        tmp_path, monkeypatch, final_status="completed_with_warnings", after_final=after_final,
    )

    assert original["draft_verification"]["review"]["status"] == "current"
    assert result["draft_verification"]["review"]["status"] == "stale"
    assert result["critique"] == {}
    assert result["historical_critique"]["critique"] == original["critique"]
    assert result["status"] == "completed_with_warnings"
    assert result["acceptance_receipt"] is None
    assert json.loads((tools.trace_dir / "final.json").read_text()) == result
    assert json.loads((tools.trace_dir / "final_scene.json").read_text()) == tools.scene


def test_unreviewed_warning_summary_cannot_assert_a_current_export_failure(live_core_tools):
    tools = live_core_tools
    _compile_panel(tools)

    result = json.loads(tools.finalize_run(
        "completed_with_warnings", "target_exceeded", "Current scene cannot export: radius.pill is unresolved."
    ))

    assert result["critique"] == {}
    assert "cannot export" not in result["summary"]
    assert "preflight is unverified" in result["summary"]
    assert "awaits review" in result["summary"]


def test_warning_after_rereview_still_discloses_pages_pruned_on_first_finalize(live_core_tools):
    tools = live_core_tools
    _compile_panel(tools)
    assert json.loads(tools.compile_dsl_block("page spare size(1080,1080,px)"))["compile"]["status"] == "ok"
    prepare_acceptance_evidence(tools)
    assert tools.finalize_run("accepted", "accepted", "Done.").startswith("REFUSED")
    assert "spare" not in tools.scene["pages"]
    prepare_acceptance_evidence(tools, {"accepted": False, "summary": "Spacing needs work.", "issues": []})

    result = json.loads(tools.finalize_run("completed_with_warnings", "target_exceeded", "Draft."))

    assert result["draft_verification"]["review"]["status"] == "current"
    assert "Pruned 1 empty page" in result["summary"]
    assert "spare" in result["summary"]
    assert "Spacing needs work." in result["summary"]
