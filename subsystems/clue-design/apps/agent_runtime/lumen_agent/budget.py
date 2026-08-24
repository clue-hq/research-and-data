"""Fast-loop v1 §5.6 — harness-enforced run budgets.

WHY A HARNESS BUDGET AND NOT A PROMPT RULE. The 2026-08-24 baseline runs were
both prompt-bounded ("there is no fixed number of rounds — you decide when the
request is satisfied") and both blew straight past every number anyone would
have written into a prompt: 178 model calls / 43m18s on one, 68 calls / 20m42s
and a quota 403 on the other. A ceiling the model is *asked* to respect is not a
ceiling. This module is the ceiling: a shared counter consulted immediately
before every model call, on every role, that raises when the run is out of
budget.

THE MECHANISM. :class:`BudgetCallbackHandler` is a langchain callback appended
to each role model's own ``.callbacks`` list — the same in-place attach
``trace_callbacks.attach_trace_callback`` uses, for the same reason (a
``.with_config`` wrapper breaks deepagents' ``resolve_model``). It sets
``raise_error = True``, which is langchain-core's documented opt-in for "an
exception from this handler propagates instead of being logged and swallowed"
(``callbacks/manager.py::handle_event``). So a breach surfaces as a
:class:`BudgetExhausted` out of ``agent.invoke`` — one exception, at a
well-defined point, before the over-budget call is paid for.

WHAT HAPPENS NEXT is deliberately NOT this module's business. The runner
(``harness.run_deepagent_turn``) catches :class:`BudgetExhausted` and finalizes
the run honestly: a gap per §5.6 ("finalize the best accepted checkpoint with
gaps recorded — never discard work, never grind past the ceiling"), then a
`completed_with_warnings` finalize when a draft actually stands and a `failed`
one when nothing was ever authored. P0.4 checkpoint commits are what make that
honest rather than lossy: every accepted round is already durable in the
document, so stopping mid-run costs the current round, not the run.

WALL CLOCK. Checked at the same seam. Every model call is the run's unit of
time (~99% of wall clock, measured), so refusing to *start* another one is a
real watchdog even though nothing interrupts a call already in flight — the
per-call ``agent_llm_timeout_s`` (L3) still owns that.

FLAG-GATED. Nothing here is constructed unless ``config.fast_loop`` is on.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Optional

from py_lumen_obs import get_logger

_log = get_logger("lumen_agent.budget")

#: Breach kinds, stamped on the exception, the run event, and the metrics
#: snapshot so all three name the same thing.
BUDGET_LLM_CALLS = "llm_calls"
BUDGET_WALL_CLOCK = "wall_clock"

#: The one run event announcing a breach.
BUDGET_EXHAUSTED_EVENT = "run_budget_exhausted"


class BudgetExhausted(RuntimeError):
    """Raised at the seam of the model call that would have gone over budget.

    Carries the machine-readable triple so the runner can record it verbatim
    rather than re-deriving it from a message string.
    """

    def __init__(self, kind: str, limit: float, observed: float) -> None:
        self.kind = kind
        self.limit = limit
        self.observed = observed
        if kind == BUDGET_WALL_CLOCK:
            detail = (
                f"wall-clock budget exhausted: {observed:.1f}s elapsed of "
                f"{limit:.0f}s allowed"
            )
        else:
            detail = (
                f"model-call budget exhausted: {int(observed)} calls made of "
                f"{int(limit)} allowed"
            )
        super().__init__(
            f"{detail}. Stopping cleanly and finalizing the best state "
            "(fast-loop v1 §5.6)."
        )

    def as_dict(self) -> dict:
        return {"kind": self.kind, "limit": self.limit, "observed": self.observed}


class RunBudget:
    """The shared per-run ceiling. Construct ONE and hand it to every role."""

    def __init__(
        self,
        *,
        max_llm_calls: int,
        wall_clock_s: float,
        metrics: Any = None,
    ) -> None:
        self.max_llm_calls = int(max_llm_calls)
        self.wall_clock_s = float(wall_clock_s)
        # The run_metrics accumulator, so a breach lands in the §7 summary next
        # to the numbers that explain it. Optional and best-effort: metrics are
        # observability and must never be the thing that fails a turn.
        self._metrics = metrics
        self._lock = threading.Lock()
        self._started_monotonic = time.monotonic()
        self._calls = 0
        self._breach: Optional[BudgetExhausted] = None

    # -- state ---------------------------------------------------------------
    @property
    def calls(self) -> int:
        with self._lock:
            return self._calls

    def elapsed_s(self) -> float:
        return time.monotonic() - self._started_monotonic

    @property
    def breach(self) -> Optional[BudgetExhausted]:
        """The FIRST breach, if any. Sticky: once out of budget, always out."""
        with self._lock:
            return self._breach

    # -- the gate ------------------------------------------------------------
    def check_and_count(self) -> None:
        """Admit one model call, or raise :class:`BudgetExhausted`.

        Checked BEFORE counting so the configured budget is the number of calls
        actually *made*: with ``max_llm_calls=45`` the 45th call runs and the
        46th raises. The same ordering makes the counter readable as "calls
        admitted", which is what the metrics snapshot reports.
        """
        with self._lock:
            if self._breach is not None:
                raise self._breach
            elapsed = self.elapsed_s()
            if self._calls >= self.max_llm_calls:
                self._breach = BudgetExhausted(
                    BUDGET_LLM_CALLS, float(self.max_llm_calls), float(self._calls)
                )
            elif elapsed >= self.wall_clock_s:
                self._breach = BudgetExhausted(
                    BUDGET_WALL_CLOCK, self.wall_clock_s, elapsed
                )
            if self._breach is None:
                self._calls += 1
                return
            breach = self._breach

        # Announced OUTSIDE the lock: the logger and the metrics accumulator take
        # their own locks, and a lock-order inversion here would deadlock the very
        # path that exists to stop a run cleanly.
        _log.warning(
            BUDGET_EXHAUSTED_EVENT,
            kind=breach.kind,
            limit=breach.limit,
            observed=breach.observed,
        )
        if self._metrics is not None:
            try:
                self._metrics.record_budget_breach(
                    kind=breach.kind, limit=breach.limit, observed=breach.observed
                )
            except Exception:  # noqa: BLE001 - metrics never break the stop path
                pass
        raise breach

    def snapshot(self) -> dict:
        """The budget's own line in the §7 metrics summary."""
        breach = self.breach
        return {
            "max_llm_calls": self.max_llm_calls,
            "wall_clock_s": self.wall_clock_s,
            "llm_calls_admitted": self.calls,
            "exhausted": breach.as_dict() if breach is not None else None,
        }


class BudgetCallbackHandler:
    """Consults the budget immediately before each model call, on one role.

    Deliberately NOT a subclass of ``BaseCallbackHandler``: langchain-core only
    needs the duck-typed hooks plus ``raise_error``/``ignore_*`` attributes, and
    importing the base class at module scope would make this module unimportable
    in the offline unit tests that stub the model layer out entirely. The class
    is tiny and its contract is the four attributes below.
    """

    #: langchain-core's opt-in: without it, ``handle_event`` logs our exception
    #: and carries on — which would turn the ceiling back into a suggestion.
    raise_error = True
    ignore_llm = False
    ignore_chain = True
    ignore_agent = True
    ignore_retriever = True
    ignore_chat_model = False
    ignore_retry = True
    ignore_custom_event = True

    def __init__(self, budget: RunBudget, role: str) -> None:
        self._budget = budget
        self._role = role

    def __getattr__(self, name: str):
        """Every callback hook we do not implement is an inert no-op.

        langchain probes handlers for a wide and version-dependent set of
        ``on_*`` methods; a missing one is fine, but ``ignore_*`` flags and
        internal attributes are read positionally in places. Answering "no-op
        callable" for any unknown ``on_*`` and raising ``AttributeError``
        otherwise keeps this handler forward-compatible without pretending to
        implement hooks it does not.
        """
        if name.startswith("on_"):
            return lambda *args, **kwargs: None
        raise AttributeError(name)

    # Both entry points, because chat models fire on_chat_model_start and the
    # text-completion path fires on_llm_start (mirrors TraceCallbackHandler).
    def on_chat_model_start(self, serialized, messages, **kwargs) -> None:
        self._budget.check_and_count()

    def on_llm_start(self, serialized, prompts, **kwargs) -> None:
        self._budget.check_and_count()


def attach_budget_callback(model: Any, budget: RunBudget, role: str) -> Any:
    """Append a :class:`BudgetCallbackHandler` to ``model.callbacks`` IN PLACE.

    Identical mechanism and constraints to ``attach_trace_callback`` — see that
    function for the full rationale. A test sentinel with no writable
    ``callbacks`` field is left untouched, which is why the budget's graceful
    finalize is proven against the runner directly rather than through a stub
    model.
    """
    handler = BudgetCallbackHandler(budget, role)
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
