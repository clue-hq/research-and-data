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
