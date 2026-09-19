"""Durable-graph seam for the two turn harnesses.

Design session continuity (founder ruling 2026-09-18) replaces D5's resume-as-restart. The
thread is the document's SESSION, so a thread that already carries state is the normal case,
not a crash: a new run appends its user message and the graph continues with every earlier tool
call, result and critique still in the window; a retried run (same run id as the thread's last
user message) resumes from the last checkpoint with input ``None``. ``PatchToolCallsMiddleware``
(deepagents, installed on both graphs) repairs a dangling tool call left by an interrupted attempt.
The tool substrate is reconstructible now: the scene is reloaded from the document at turn start
and per-turn files live under the session folder's ``turns/<run_id>``.
"""

from __future__ import annotations

from typing import Any

from py_lumen_obs import get_logger

logger = get_logger("lumen_agent.checkpoint")

RUN_ID_KEY = "lumen_run_id"


def invoke_turn_graph(
    agent: Any,
    initial_state: dict,
    *,
    invoke_config: dict,
    checkpointer: Any = None,
    thread_id: str | None = None,
    run_id: str | None = None,
) -> Any:
    """Invoke a compiled turn graph on its thread: fresh, continued, or resumed.

    ``checkpointer``/``thread_id`` are both optional and only take effect together — a turn run
    without a checkpointer (the CLI, the offline fixtures, every test that does not need
    durability) invokes exactly as it did before, so this function is a no-op on that path.

    Returns whatever ``agent.invoke`` returns. Never raises on the checkpoint bookkeeping itself:
    a checkpointer that cannot report its own state must not be able to fail a turn that would
    otherwise run, so the lookup is best-effort and logged, and an unreadable thread is treated
    as fresh.
    """
    if checkpointer is None or thread_id is None:
        return agent.invoke(initial_state, config=invoke_config)

    last_run = _last_user_run_id(agent, invoke_config, thread_id)
    if last_run is None:
        return agent.invoke(initial_state, config=invoke_config)
    if run_id is not None and last_run == run_id:
        logger.info("turn.checkpoint_resume", thread_id=thread_id, run_id=run_id)
        return agent.invoke(None, config=invoke_config)
    logger.info("turn.checkpoint_continue", thread_id=thread_id, run_id=run_id, after_run=last_run)
    return agent.invoke(initial_state, config=invoke_config)


def _last_user_run_id(agent: Any, invoke_config: dict, thread_id: str) -> str | None:
    """The run id stamped on the thread's newest user message; ``None`` for a fresh thread."""
    try:
        snapshot = agent.get_state(invoke_config)
    except Exception:  # noqa: BLE001 - never let checkpoint bookkeeping fail a runnable turn
        logger.warning("turn.checkpoint_state_unreadable", thread_id=thread_id, exc_info=True)
        return None
    if getattr(snapshot, "created_at", None) is None:
        return None
    messages = (getattr(snapshot, "values", None) or {}).get("messages") or []
    for message in reversed(messages):
        if getattr(message, "type", None) == "human":
            return (getattr(message, "additional_kwargs", None) or {}).get(RUN_ID_KEY) or "unknown"
    return "unknown"


__all__ = ["RUN_ID_KEY", "invoke_turn_graph"]
