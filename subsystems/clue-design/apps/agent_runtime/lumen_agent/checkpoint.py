"""Durable-graph seam for the two turn harnesses (design-integration Part II, slice D5 Round B).

D5 puts design agent turns on the platform fleet, which means a turn can be *taken over*: the
worker driving it dies, its lease expires, a second worker claims the same run at a higher
generation and must do something sensible with the half-finished work. This module is the one
place that decides what "something sensible" is.

WHAT SHIPPED: **resume-as-restart**, not true mid-turn resume. That is a measured finding, not a
shortcut, and the reason is structural:

``LumenDesignTools`` / ``LumenWebTools`` mint a FRESH ``run_id`` in their constructor
(``tools/substrate.py``: ``self.run_id = new_run_id()``) and derive ``trace_dir`` from it. All of
the turn's real state — the scene under construction, the operations ledger, the round
directories, the preview images, and ``final.json``, which is the harness's sole authority for the
turn's outcome — lives in that per-construction directory and in the tool object's memory. None of
it is in the LangGraph checkpoint, which holds only the message list and graph position.

So a "true" resume would restore a message history whose tool results describe a workspace that no
longer exists, hand it to a tool substrate whose scene is empty, and let the orchestrator finalize
against files it never wrote. That is not resumption; it is a fabricated continuation, and the
design harness's whole discipline is that it never fabricates an outcome. Likewise a *completed*
checkpoint cannot be short-circuited: the outcome it produced lives in the dead attempt's
``final.json``, which the new tool substrate cannot name.

Therefore, when a thread already carries state, this module **deletes the thread and re-invokes
the frozen envelope from the top** — same run, same ``thread_id``, same immutable work
description, and the run's prior ``design_run_event`` rows are left untouched so the editor's SSE
stream keeps its history. Every restart is logged loudly (``turn.checkpoint_restart``).

WHY WIRE THE CHECKPOINTER AT ALL, THEN? Three reasons, all real today:
1. The graph state becomes durable and inspectable per run — an operator can see how far a dead
   turn actually got, which the trace dir alone cannot tell them once the process is gone.
2. ``thread_id`` becomes the design run id (the D5 ruling), so graph state, run row, event stream,
   and fleet work id all key on one identifier instead of the runtime's private ``tools.run_id``.
3. It is the seam true resume will land on. When the tool substrate is made reconstructible from a
   run id (a later round's work), the ``_RESTART`` branch below becomes the resume branch and
   nothing else moves.
"""

from __future__ import annotations

from typing import Any

from py_lumen_obs import get_logger

logger = get_logger("lumen_agent.checkpoint")


def invoke_turn_graph(
    agent: Any,
    initial_state: dict,
    *,
    invoke_config: dict,
    checkpointer: Any = None,
    thread_id: str | None = None,
) -> Any:
    """Invoke a compiled turn graph, restarting a thread that already carries state.

    ``checkpointer``/``thread_id`` are both optional and only take effect together — a turn run
    without a checkpointer (the CLI, the offline fixtures, every test that does not need
    durability) invokes exactly as it did before D5, so this function is a no-op on that path.

    Returns whatever ``agent.invoke`` returns. Never raises on the checkpoint bookkeeping itself:
    a checkpointer that cannot report or clear its own state must not be able to fail a turn that
    would otherwise run, so the lookup/delete are best-effort and logged.
    """
    if checkpointer is None or thread_id is None:
        return agent.invoke(initial_state, config=invoke_config)

    if _thread_has_state(agent, invoke_config, thread_id):
        logger.warning(
            "turn.checkpoint_restart",
            thread_id=thread_id,
            reason="tool_substrate_is_not_resumable",
            detail=(
                "a previous attempt left graph state on this thread; the turn is re-run from the "
                "top because the tool substrate (scene, trace dir, final.json) cannot be restored"
            ),
        )
        _clear_thread(checkpointer, thread_id)

    return agent.invoke(initial_state, config=invoke_config)


def _thread_has_state(agent: Any, invoke_config: dict, thread_id: str) -> bool:
    try:
        snapshot = agent.get_state(invoke_config)
    except Exception:  # noqa: BLE001 - never let checkpoint bookkeeping fail a runnable turn
        logger.warning("turn.checkpoint_state_unreadable", thread_id=thread_id, exc_info=True)
        return False
    # A never-seen thread yields a snapshot whose values are empty and whose config carries no
    # checkpoint id; `created_at` is the cheapest honest "this thread has been written" signal.
    return getattr(snapshot, "created_at", None) is not None


def _clear_thread(checkpointer: Any, thread_id: str) -> None:
    try:
        checkpointer.delete_thread(thread_id)
    except Exception:  # noqa: BLE001 - see above
        logger.warning("turn.checkpoint_clear_failed", thread_id=thread_id, exc_info=True)


__all__ = ["invoke_turn_graph"]
