"""Durable-graph seam for the two turn harnesses.

Design session continuity (founder ruling 2026-09-18) replaces D5's resume-as-restart. The
thread is the document's SESSION, so a thread that already carries state is the normal case,
not a crash: a new run appends its user message and the graph continues with every earlier tool
call, result and critique still in the window; a retried run (same run id as the thread's last
user message) resumes from the last checkpoint with input ``None``. ``PatchToolCallsMiddleware``
(deepagents, installed on both graphs) repairs a dangling tool call left by an interrupted attempt.
The tool substrate is reconstructible now: the scene is reloaded from the document at turn start
and per-turn files live under the session folder's ``turns/<run_id>``.

The site harness (site-turn durability, 2026-10-16) never resumes the LATEST checkpoint: its
folder is rebuilt from the stored site, so a conversation that had already edited files would
continue over a folder that no longer holds those edits (finding K4-1). It resumes from the
checkpoint its working copy was stamped with (``resume_checkpoint_id``), whose files it has laid
back first, and otherwise refuses a thread that already carries this run (``resume_latest=False``).
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
    resume_checkpoint_id: str | None = None,
    resume_latest: bool = True,
    durability: str | None = None,
    control: Any = None,
) -> Any:
    """Invoke a compiled turn graph on its thread: fresh, continued, or resumed.

    ``checkpointer``/``thread_id`` are both optional and only take effect together — a turn run
    without a checkpointer (the CLI, the offline fixtures, every test that does not need
    durability) invokes exactly as it did before, so this function is a no-op on that path.

    Returns whatever ``agent.invoke`` returns. Never raises on the checkpoint bookkeeping itself:
    a checkpointer that cannot report its own state must not be able to fail a turn that would
    otherwise run, so the lookup is best-effort and logged, and an unreadable thread is treated
    as fresh.

    ``resume_checkpoint_id`` resumes the thread from that exact checkpoint with input ``None``
    (the site harness's working copy names it). ``resume_latest=False`` refuses, with a
    ``RuntimeError``, a thread whose newest user message already carries ``run_id``: resuming its
    latest checkpoint is only safe for a caller whose files do not depend on it. ``durability`` is
    passed to the graph (``"sync"``: each step's checkpoint is committed before the next starts).
    ``control`` (a LangGraph ``RunControl``) lets the caller ask the run to stop at its next step
    boundary; the graph then raises ``GraphDrained`` (the site harness's drain, 2026-10-16).
    """
    extra: dict[str, Any] = {} if durability is None else {"durability": durability}
    if control is not None:
        extra["control"] = control
    if checkpointer is None or thread_id is None:
        return agent.invoke(initial_state, config=invoke_config, **extra)

    if resume_checkpoint_id is not None:
        logger.info(
            "turn.checkpoint_resume_at", thread_id=thread_id, run_id=run_id, checkpoint_id=resume_checkpoint_id
        )
        config = {
            **invoke_config,
            "configurable": {**invoke_config.get("configurable", {}), "checkpoint_id": resume_checkpoint_id},
        }
        return agent.invoke(None, config=config, **extra)

    last_run = _last_user_run_id(agent, invoke_config, thread_id)
    if last_run is None:
        return agent.invoke(initial_state, config=invoke_config, **extra)
    if run_id is not None and last_run == run_id:
        if not resume_latest:
            raise RuntimeError(
                f"thread {thread_id} already carries run {run_id} but no checkpoint to resume from was named; "
                "resuming its latest checkpoint over a rebuilt folder would lose its file work"
            )
        logger.info("turn.checkpoint_resume", thread_id=thread_id, run_id=run_id)
        return agent.invoke(None, config=invoke_config, **extra)
    logger.info("turn.checkpoint_continue", thread_id=thread_id, run_id=run_id, after_run=last_run)
    return agent.invoke(initial_state, config=invoke_config, **extra)


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
