"""A3 (defect R3-D) — cooperative cancellation of an in-flight design turn.

THE DEFECT. During the W5 Apollo walk a doomed manual-reference run had to be watched to
completion because nothing could stop it (`.context/w5-apollo-e2e-report.md` §R3.7). The turn was
wrong within its first minute and kept spending paid model calls for many more.

THE MECHANISM IS THE BUDGET'S, DELIBERATELY. This module is the budget backstop's twin, and that
is not laziness — it is the only place in the process where a design turn can be stopped at all.
The drive loop is a LangGraph ReAct graph entered exactly once (`harness.run_deepagent_turn`
calls `invoke_turn_graph` and does not regain control until the graph returns), so there is no
Python round loop to test a flag in. What there IS, on every single model call, is the langchain
callback seam: `raise_error = True` makes an exception from `on_chat_model_start` propagate out
of `agent.invoke` instead of being logged and swallowed. `budget.BudgetCallbackHandler` uses that
seam to refuse an over-budget call; this handler uses it to refuse a call the human no longer
wants. One seam, two reasons, identical blast radius — and the runner's honest-finalize path is
shared rather than copied.

CANCELLATION BOUNDARIES. Check freshly before a model call and immediately after its return;
streaming calls also check while receiving tokens. A non-streaming synchronous request may run
until it returns or its configured timeout fires. Its caller retains the lease while unwinding;
no chat acknowledgement implies that a Python thread was forcibly killed. The governed tool
write seam also checks the same durable run signal before admitting a write.

WHAT SURVIVES. Everything that was already durable. P0.4 commits each accepted authoring round to
the document as it happens, so a cancelled run keeps every round it finished and loses only the
round in flight — the same guarantee the budget stop has, for the same reason.

FAIL-OPEN, NOT FAIL-CLOSED. :class:`CancellationProbe` swallows every error from the underlying
read and answers "not cancelled". A database blip must not become the run's cause of death: this
mechanism exists to stop runs a human asked to stop, and stopping one nobody asked about would be
a worse failure than missing a cancel for one more call. The next call re-reads.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from py_lumen_obs import get_logger

_log = get_logger("lumen_agent.cancellation")

#: The one run event announcing that a human's cancel request was honoured.
CANCELLED_EVENT = "run_cancelled"

#: The ``stop_reason`` a cancelled turn finalizes with. One literal, so the durable
#: ``result_json.stop_reason``, the trace record and any operator query all name the same fact.
CANCELLED_STOP_REASON = "cancelled_by_request"

#: How long a negative probe answer is trusted before the source is read again. The probe is
#: consulted once per model call and a model call is seconds long at best, so this only collapses
#: bursts (a retry storm, a role handing straight off to another); it can never delay a cancel by
#: more than this. Set to 0 to read the source on every single call.
PROBE_MIN_INTERVAL_S = 1.0


class TurnCancelled(RuntimeError):
    """Raised at the seam of the model call a cancelled run would otherwise have paid for.

    A sibling of :class:`~lumen_agent.budget.BudgetExhausted` in every way that matters to the
    runner: not a crash, not a failure of the design, but a deliberate stop with an honest name.
    """

    def __init__(self, requested_at: Optional[str] = None) -> None:
        self.requested_at = requested_at
        when = f" (requested at {requested_at})" if requested_at else ""
        super().__init__(
            f"cancelled by request{when}. A human asked this turn to stop, so it was stopped at "
            "the next model-call boundary rather than run to completion. Every authoring round "
            "already accepted was checkpointed to the document and stands; the round in flight "
            "did not complete."
        )


class CancellationProbe:
    """A cheap, sticky, fail-open view of "has this run been asked to stop?".

    STICKY. Once the source says yes, this says yes forever and stops reading. A cancellation is
    write-once at rest, so re-reading it could only ever cost another round trip, and a probe that
    could flip back to False would let a run resume itself after being stopped.

    THROTTLED, on the negative answer only. Reading Postgres once per model call is negligible
    against the call itself, but a burst of cheap calls should not become a burst of queries.
    A positive answer is never throttled — it is already terminal.

    FAIL-OPEN. Any exception from the source is logged once per occurrence and read as "not
    cancelled"; see the module docstring for why that direction is the safe one.
    """

    def __init__(
        self,
        source: Callable[[], bool],
        *,
        min_interval_s: float = PROBE_MIN_INTERVAL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._source = source
        self._min_interval_s = float(min_interval_s)
        self._clock = clock
        self._cancelled = False
        self._last_read: Optional[float] = None

    def __call__(self, *, fresh: bool = False) -> bool:
        if self._cancelled:
            return True
        now = self._clock()
        if (
            not fresh
            and self._last_read is not None
            and self._min_interval_s > 0
            and (now - self._last_read) < self._min_interval_s
        ):
            return False
        self._last_read = now
        try:
            answer = bool(self._source())
        except Exception as error:  # noqa: BLE001 - a read fault must never stop a live run
            _log.warning(
                "cancellation_probe_failed",
                error=f"{type(error).__name__}: {error}",
                detail="read as NOT cancelled; the next model call re-reads",
            )
            return False
        if answer:
            self._cancelled = True
        return answer


class CancellationCallbackHandler:
    """Consults the probe immediately before each model call, on one role.

    Shape and every attribute below are the budget handler's, for the reasons stated there:
    duck-typed rather than a ``BaseCallbackHandler`` subclass so this module stays importable in
    offline tests that stub the model layer out, and ``raise_error`` because without it
    langchain-core logs our exception and carries on — which would turn a cancel into a wish.
    """

    raise_error = True
    run_inline = False
    ignore_llm = False
    ignore_chain = True
    ignore_agent = True
    ignore_retriever = True
    ignore_chat_model = False
    ignore_retry = True
    ignore_custom_event = True

    def __init__(self, probe: Callable[[], bool], role: str) -> None:
        self._probe = probe
        self._role = role

    def __getattr__(self, name: str):
        """Every hook we do not implement is an inert no-op — see the budget handler's twin."""
        if name.startswith("on_"):
            return lambda *args, **kwargs: None
        raise AttributeError(name)

    def _check(self, *, fresh: bool = False) -> None:
        cancelled = self._probe(fresh=fresh) if isinstance(self._probe, CancellationProbe) else self._probe()
        if cancelled:
            _log.warning("run_cancelled_at_call_boundary", role=self._role)
            raise TurnCancelled()

    # Chat models fire on_chat_model_start; the text-completion path fires on_llm_start.
    def on_chat_model_start(self, serialized, messages, **kwargs) -> None:
        self._check(fresh=True)

    def on_llm_start(self, serialized, prompts, **kwargs) -> None:
        self._check(fresh=True)

    def on_llm_new_token(self, token, **kwargs) -> None:
        self._check()

    def on_llm_end(self, response, **kwargs) -> None:
        # A cached negative must not hand fresh tool calls to the graph after Stop.
        self._check(fresh=True)


def attach_cancellation_callback(model: Any, probe: Callable[[], bool], role: str) -> Any:
    """Append a :class:`CancellationCallbackHandler` to ``model.callbacks`` IN PLACE.

    Identical mechanism and constraints to ``budget.attach_budget_callback`` — a ``.with_config``
    wrapper returns a ``RunnableBinding`` that deepagents' ``resolve_model`` mishandles, so the
    handler is appended to the instance's own callback list. A test sentinel with no writable
    ``callbacks`` field is left untouched, which is why the cancel finalize is proven against the
    runner directly as well as through the handler.
    """
    handler = CancellationCallbackHandler(probe, role)
    if not hasattr(model, "callbacks"):
        return model
    try:
        existing = model.callbacks
        if existing is None:
            model.callbacks = [handler]
        elif isinstance(existing, list):
            existing.append(handler)
        else:
            add_handler = getattr(existing, "add_handler", None)
            if callable(add_handler):
                add_handler(handler)
            else:
                model.callbacks = [existing, handler]
    except Exception:  # noqa: BLE001 - never block assembly on wiring
        return model
    return model


__all__ = [
    "CANCELLED_EVENT",
    "CANCELLED_STOP_REASON",
    "CancellationCallbackHandler",
    "CancellationProbe",
    "TurnCancelled",
    "attach_cancellation_callback",
]
