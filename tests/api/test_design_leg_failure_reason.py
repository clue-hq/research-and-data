"""A failed design run's reason reaches the user and the strategy agent (production 2026-10-05).

Two design runs failed in 5–7 s with "Permission denied" on the design workspace; the user saw
only "Design stopped before completion", and the strategy agent, which sees a closed design
session only through its exit summary, guessed the page "was never generated".
"""

from __future__ import annotations

from clue_api.design_leg_wiring import design_run_failure_note, exit_summary

#: The exact shape of the 2026-10-05 production failures (design_agent_run.result_json).
RUNTIME_FAILED = {
    "status": "failed",
    "summary": "Agent runtime failed before returning a result.",
    "doc_kind": "web",
    "model_calls": [],
    "diagnostics": [
        {
            "code": "agent_runtime.failed",
            "hint": (
                "Failed to materialize agent workspace at /srv/clue/lumen-agent from "
                "/app/subsystems/clue-design/apps/agent_runtime/knowledge_docs: [Errno 13] "
                "Permission denied: '/srv/clue/lumen-agent/.materialize.lock'"
            ),
            "phase": "validation",
            "message": "Agent runtime failed before returning a result.",
            "severity": "error",
        }
    ],
}


def test_a_run_that_failed_before_any_model_call_is_described_as_such() -> None:
    note = design_run_failure_note(RUNTIME_FAILED)
    assert note is not None
    assert "before anything was generated" in note
    assert "agent_runtime.failed" in note
    # Server internals (paths, errno text) never reach the user or the agent's prose.
    assert "/srv" not in note and "Errno" not in note


def test_a_run_that_failed_while_designing_says_so() -> None:
    note = design_run_failure_note({**RUNTIME_FAILED, "model_calls": [{"model": "x"}]})
    assert note is not None and "while designing" in note


def test_a_successful_or_unknown_run_has_no_failure_note() -> None:
    assert design_run_failure_note({"status": "accepted"}) is None
    assert design_run_failure_note(None) is None
    assert design_run_failure_note({}) is None


def test_the_exit_summary_tells_the_strategy_agent_the_last_run_failed() -> None:
    base = exit_summary("out_of_scope", "Not design work.")
    note = design_run_failure_note(RUNTIME_FAILED)
    with_failure = exit_summary("out_of_scope", "Not design work.", last_failure=note)
    assert with_failure.startswith(base)
    assert note is not None and note in with_failure
    assert exit_summary("out_of_scope", "Not design work.", last_failure=None) == base
