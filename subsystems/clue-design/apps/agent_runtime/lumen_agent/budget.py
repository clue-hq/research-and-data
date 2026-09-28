"""Fast-loop v1 §5.6 — run budgets, as GUIDANCE over a distant BACKSTOP.

RULING D1 (founder, 2026-08-26) RE-SHAPED THIS MODULE. It used to hold exactly
one number per axis and stop the run dead on it. It now holds two, and they do
different jobs:

* **The target** (``target_llm_calls`` / ``target_wall_clock_s``, shipped at 45
  calls / 900s) is what the agent is *told about*. It rides the orchestrator
  prompt as a plain obligation and the round-boundary ``BUDGET LEFT`` line.
  Crossing it stops nothing. It is recorded — once, stickily — so drift is
  visible in ``run_metrics`` instead of invisible.
* **The backstop** (``max_llm_calls`` / ``wall_clock_s``, shipped at ~2x the
  target: 90 calls / 1800s) is the circuit breaker for a hung or runaway run.
  It is the only hard stop, and the agent's prompt never mentions it, because a
  healthy run never reaches it.

WHY THE OLD HARD CEILING HAD TO MOVE. The original rationale still stands as
far as it goes: the 2026-08-24 baseline runs were purely prompt-bounded and blew
past every number anyone would have written down (178 calls / 43m18s on one; 68
calls / 20m42s and a quota 403 on the other). But the fix over-corrected. Live
A/B on 2026-08-26 (Apollo POC, `.context/ref-ads-pilot-apollo-report.md`) showed
the 600s hard wall cutting the run right after its first look — it shipped at
reference_fidelity 1 — while the same brief at 900s reacted to its own critique
and reached fidelity 2. The ceiling was not saving the run from waste. It was
amputating the repair round the loop exists to run. So the number the agent
steers by became advice, and the number that fires became distant.

THE MECHANISM (backstop only). :class:`BudgetCallbackHandler` is a langchain
callback appended to each role model's own ``.callbacks`` list — the same
in-place attach ``trace_callbacks.attach_trace_callback`` uses, for the same
reason (a ``.with_config`` wrapper breaks deepagents' ``resolve_model``). It
sets ``raise_error = True``, which is langchain-core's documented opt-in for "an
exception from this handler propagates instead of being logged and swallowed"
(``callbacks/manager.py::handle_event``). So a backstop hit surfaces as a
:class:`BudgetExhausted` out of ``agent.invoke`` — one exception, at a
well-defined point, before the over-budget call is paid for. Crossing a *target*
takes none of that path: it logs, it counts, and the call is admitted.

WHAT HAPPENS NEXT is deliberately NOT this module's business. The runner
(``harness.run_deepagent_turn``) catches :class:`BudgetExhausted` and finalizes
the run honestly: a gap per §5.6 ("finalize the best accepted checkpoint with
gaps recorded — never discard work, never grind past the ceiling"), then a
`completed_with_warnings` finalize when a draft actually stands and a `failed`
one when nothing was ever authored. P0.4 checkpoint commits are what make that
honest rather than lossy: every accepted round is already durable in the
document, so stopping mid-run costs the current round, not the run. D1 did not
weaken that path by one line — it only made reaching it abnormal.

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

#: Axis names, stamped on the exception, the run events, and the metrics
#: snapshot so all of them name the same thing.
BUDGET_LLM_CALLS = "llm_calls"
BUDGET_WALL_CLOCK = "wall_clock"

#: The one run event announcing a BACKSTOP hit. Abnormal: a run that reaches
#: this was hung or runaway (D1).
BUDGET_EXHAUSTED_EVENT = "run_budget_exhausted"

#: The one run event announcing that the run went past its TARGET.
#: INFORMATIONAL: nothing stopped, nothing failed, the run simply cost more
#: than the guidance asked for. Kept a distinct name from the backstop event so
#: "we drift past 900s a lot" and "a run hung" can never be read as the same
#: fact (D1 clause 4).
BUDGET_TARGET_EXCEEDED_EVENT = "run_budget_target_exceeded"

# ---------------------------------------------------------------------------
# What one more authoring round costs. Measured, not guessed: acceptance run #1
# (`run_4b5dd17f9e944269b94ca45d3bd6d9f2`, 2026-08-24) shows a repair round's
# irreducible shape as the author's delegation + one batched read + compile +
# preflight + render + view + one fix compile + the four round files + the report
# — about a dozen author calls — plus the orchestrator's own step-5 verification
# (read, preflight, render, view: four more). Sixteen calls. That run's mean call
# took ~17s across both roles, so sixteen calls is ~4.5 minutes; the floors below
# round that to a defensible 12 calls and 4 minutes.
#
# WHY THESE ARE FLOORS AND NOT A FORECAST. They are not a promise that a round
# fits in twelve calls. They are the point below which one demonstrably does NOT
# fit, which is the only question the orchestrator has to answer at a round
# boundary. Being wrong upward costs one unspent repair round; being wrong
# downward costs exactly what acceptance run #1 paid — a design left mid-repair
# when the wall clock fired at 604.6s of 600s.
REPAIR_ROUND_MIN_CALLS = 12
REPAIR_ROUND_MIN_SECONDS = 240.0


class BudgetExhausted(RuntimeError):
    """Raised at the seam of the model call that would have crossed the BACKSTOP.

    Carries the machine-readable triple so the runner can record it verbatim
    rather than re-deriving it from a message string. Under D1 this exception is
    an ABNORMAL event — the target is guidance and never raises anything.
    """

    def __init__(self, kind: str, limit: float, observed: float) -> None:
        self.kind = kind
        self.limit = limit
        self.observed = observed
        if kind == BUDGET_WALL_CLOCK:
            detail = (
                f"wall-clock BACKSTOP hit: {observed:.1f}s elapsed of the "
                f"{limit:.0f}s circuit breaker"
            )
        else:
            detail = (
                f"model-call BACKSTOP hit: {int(observed)} calls made of the "
                f"{int(limit)}-call circuit breaker"
            )
        super().__init__(
            f"{detail}. This is the runaway-run circuit breaker, not the turn "
            "target — a healthy run never reaches it. Stopping cleanly and "
            "finalizing the best state (fast-loop v1 §5.6, ruling D1)."
        )

    def as_dict(self) -> dict:
        return {"kind": self.kind, "limit": self.limit, "observed": self.observed}


class RunBudget:
    """The shared per-run budget. Construct ONE and hand it to every role.

    Two axes (model calls, wall clock) x two thresholds (target, backstop).
    ``target_*`` default to the backstop when a caller supplies only the
    backstop, which keeps a single-number construction meaning exactly what it
    used to mean.
    """

    def __init__(
        self,
        *,
        max_llm_calls: int,
        wall_clock_s: float,
        target_llm_calls: int | None = None,
        target_wall_clock_s: float | None = None,
        metrics: Any = None,
    ) -> None:
        # The BACKSTOP — the only hard stop (D1).
        self.max_llm_calls = int(max_llm_calls)
        self.wall_clock_s = float(wall_clock_s)
        # The TARGET — guidance, reported to the agent, enforced by nothing.
        self.target_llm_calls = int(
            target_llm_calls if target_llm_calls is not None else max_llm_calls
        )
        self.target_wall_clock_s = float(
            target_wall_clock_s if target_wall_clock_s is not None else wall_clock_s
        )
        # The run_metrics accumulator, so both a target crossing and a backstop
        # hit land in the §7 summary next to the numbers that explain them.
        # Optional and best-effort: metrics are observability and must never be
        # the thing that fails a turn.
        self._metrics = metrics
        self._lock = threading.Lock()
        self._started_monotonic = time.monotonic()
        self._calls = 0
        self._breach: Optional[BudgetExhausted] = None
        self._target_exceeded: Optional[dict] = None

    # -- state ---------------------------------------------------------------
    @property
    def calls(self) -> int:
        with self._lock:
            return self._calls

    def elapsed_s(self) -> float:
        return time.monotonic() - self._started_monotonic

    @property
    def breach(self) -> Optional[BudgetExhausted]:
        """The FIRST backstop hit, if any. Sticky: once stopped, always stopped."""
        with self._lock:
            return self._breach

    @property
    def target_exceeded(self) -> Optional[dict]:
        """The FIRST target crossing, if any — ``{kind, target, observed}``.

        Sticky and informational. A run that crosses the wall-clock target and
        later also crosses the call target reports the first crossing only; the
        question this answers is "did this run go past guidance, and on which
        axis first", not "how many times".
        """
        with self._lock:
            return dict(self._target_exceeded) if self._target_exceeded else None

    def past_target(self) -> bool:
        """Whether the run is over either target RIGHT NOW.

        Read live rather than off the sticky record, because the status line the
        orchestrator reads must be true at the moment it is read — the wall
        clock crosses the target between calls, not at one.
        """
        with self._lock:
            calls = self._calls
        return calls >= self.target_llm_calls or self.elapsed_s() >= self.target_wall_clock_s

    # -- the gate ------------------------------------------------------------
    def check_and_count(self) -> None:
        """Admit one model call, or raise :class:`BudgetExhausted` at the BACKSTOP.

        D1 in one method. Crossing a TARGET is noticed and recorded, and then
        the call is admitted anyway — the whole point of the ruling is that no
        hard cut fires at the number the agent was asked to steer by. Only the
        backstop raises, and only for a run that has become pathological.

        Checked BEFORE counting so the configured backstop is the number of
        calls actually *made*: with ``max_llm_calls=90`` the 90th call runs and
        the 91st raises. The same ordering makes the counter readable as "calls
        admitted", which is what the metrics snapshot reports.
        """
        crossing: Optional[dict] = None
        with self._lock:
            if self._breach is not None:
                raise self._breach
            elapsed = self.elapsed_s()

            # --- the backstop: the only thing that stops a run ---------------
            if self._calls >= self.max_llm_calls:
                self._breach = BudgetExhausted(
                    BUDGET_LLM_CALLS, float(self.max_llm_calls), float(self._calls)
                )
            elif elapsed >= self.wall_clock_s:
                self._breach = BudgetExhausted(
                    BUDGET_WALL_CLOCK, self.wall_clock_s, elapsed
                )

            if self._breach is None:
                # --- the target: noticed once, never enforced ----------------
                if self._target_exceeded is None:
                    if self._calls >= self.target_llm_calls:
                        crossing = {
                            "kind": BUDGET_LLM_CALLS,
                            "target": float(self.target_llm_calls),
                            "observed": float(self._calls),
                        }
                    elif elapsed >= self.target_wall_clock_s:
                        crossing = {
                            "kind": BUDGET_WALL_CLOCK,
                            "target": self.target_wall_clock_s,
                            "observed": elapsed,
                        }
                    if crossing is not None:
                        self._target_exceeded = crossing
                self._calls += 1
                breach = None
            else:
                breach = self._breach

        # Everything below is announced OUTSIDE the lock: the logger and the
        # metrics accumulator take their own locks, and a lock-order inversion
        # here would deadlock the very path that exists to stop a run cleanly.
        if breach is None:
            if crossing is not None:
                _log.info(
                    BUDGET_TARGET_EXCEEDED_EVENT,
                    kind=crossing["kind"],
                    target=crossing["target"],
                    observed=crossing["observed"],
                    backstop=(
                        float(self.max_llm_calls)
                        if crossing["kind"] == BUDGET_LLM_CALLS
                        else self.wall_clock_s
                    ),
                )
                if self._metrics is not None:
                    try:
                        self._metrics.record_budget_target_exceeded(
                            kind=crossing["kind"],
                            target=crossing["target"],
                            observed=crossing["observed"],
                        )
                    except Exception:  # noqa: BLE001 - metrics never break a run
                        pass
            return

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

    # -- headroom, for the model rather than the metrics -----------------------
    def remaining(self) -> dict:
        """What is left AGAINST THE TARGET, computed by the harness not the model.

        The 2026-08-24 acceptance run died mid-repair because nothing ever told
        the loop how much budget remained: the orchestrator opened round 2 with
        56 seconds of wall clock left, delegated, and the ceiling fired before
        the author's first compile. Every number needed to avoid that was already
        in this object — it was simply never shown to anyone who could act on it.

        MEASURED AGAINST THE TARGET, NOT THE BACKSTOP (D1). This is the number
        the agent steers by, and the agent is meant to steer by guidance; quoting
        it the backstop instead would both hide the target it was asked to hit
        and invite it to spend up to a circuit breaker. The backstop rides along
        under its own keys for anything that needs to reason about both.

        `room_for_another_round` is the whole point. The orchestrator should not
        be doing arithmetic against a pair of numbers in prose; it should be told
        yes or no. Both floors must clear, because a round starved of either
        resource stops in the same half-finished place.
        """
        calls_used = self.calls
        calls_left = max(0, self.target_llm_calls - calls_used)
        elapsed = self.elapsed_s()
        seconds_left = max(0.0, self.target_wall_clock_s - elapsed)
        return {
            "calls_used": calls_used,
            "calls_left": calls_left,
            "target_llm_calls": self.target_llm_calls,
            "elapsed_s": elapsed,
            "seconds_left": seconds_left,
            "target_wall_clock_s": self.target_wall_clock_s,
            "past_target": (
                calls_used >= self.target_llm_calls or elapsed >= self.target_wall_clock_s
            ),
            "backstop_llm_calls": self.max_llm_calls,
            "backstop_wall_clock_s": self.wall_clock_s,
            "room_for_another_round": (
                calls_left >= REPAIR_ROUND_MIN_CALLS
                and seconds_left >= REPAIR_ROUND_MIN_SECONDS
            ),
        }

    def status_line(self) -> str:
        """The headroom as one block of prose, for a tool result a model reads.

        Deliberately finished sentences rather than a data dump: the consumer is
        a language model at a decision point, and "there is not room" is acted on
        where "calls_left: 9" invites it to argue. The raw numbers ride along so
        the judgement is auditable rather than mysterious.

        THE BACKSTOP IS NEVER NAMED HERE (D1). The agent is told what it is
        aiming at and what to do about it. Telling it about the circuit breaker
        would only teach it that the target is negotiable.
        """
        state = self.remaining()
        if state["past_target"]:
            verdict = (
                "You are PAST this turn's target. Nothing has stopped you and "
                "nothing is going to cut you off here. Do not open another "
                "authoring round. Keep the design that stands. record_gap what "
                "is still wrong. Finalize now."
            )
        elif state["room_for_another_round"]:
            verdict = "There is room for another authoring round."
        else:
            verdict = (
                "There is NOT room for another authoring round — do not delegate "
                "again. Keep the design that stands, record_gap what is still "
                "wrong, and finalize."
            )
        return (
            "BUDGET LEFT: "
            f"{state['calls_used']} of {state['target_llm_calls']} model calls used, "
            f"{state['calls_left']} left. "
            f"{state['elapsed_s'] / 60.0:.1f} of "
            f"{state['target_wall_clock_s'] / 60.0:.1f} minutes used, "
            f"{state['seconds_left'] / 60.0:.1f} left. "
            f"{verdict}"
        )

    def candidate_status_line(self, *, current_round: int, runtime_owned_rounds: bool = False) -> str:
        """Scene-candidate advice for one quality repair, not a new hard gate.

        The candidate's four-minute target equals the existing minimum repair
        allowance. Comparing repair headroom to that target therefore forbids
        every repair once work starts. Keep reporting the target, but assess
        this single repair against the unchanged hard limits. The director
        judges defects after viewing the current pixels; an author's accepted
        self-audit must not suppress a legitimate director disagreement. Hard
        headroom stays in metrics; advice exposes eligibility, not an allowance
        inviting the model to spend up to the backstop.
        """
        state = self.remaining()
        calls_left = max(0, self.max_llm_calls - state["calls_used"])
        seconds_left = max(0.0, self.wall_clock_s - state["elapsed_s"])
        enough_headroom = (
            calls_left >= REPAIR_ROUND_MIN_CALLS
            and seconds_left >= REPAIR_ROUND_MIN_SECONDS
        )
        finish = (
            "Do not open another authoring round. Finalize accepted only if the current "
            "review passes all acceptance checks; otherwise preserve an unaccepted draft "
            "and record the remaining defects."
        )
        if not enough_headroom:
            verdict = f"There is insufficient hard headroom for a repair. {finish}"
        elif current_round == 0:
            verdict = (
                "No authoring round has finished yet. Continue the initial authoring "
                "workflow; this is not a repair-round decision."
            )
        elif current_round == 1:
            repair = (
                "after a registered rejected critique, the next construction tool "
                "starts round_2 automatically. Round notes are optional; batch the repair. "
                if runtime_owned_rounds else
                "open round_2 with those defects and a single batched repair. "
            )
            verdict = (
                "If your current review identifies concrete defects, one focused repair "
                f"round is available: {repair}"
                "Do not open a round because headroom alone exists. If the current "
                "review passes all acceptance checks, finalize now."
            )
        else:
            verdict = f"The one repair round is already used. {finish}"
        target = "TARGET EXCEEDED" if state["past_target"] else "WITHIN TARGET"
        return (
            f"BUDGET LEFT: {target}: {state['calls_used']} of "
            f"{self.target_llm_calls} target model calls and {state['elapsed_s']:.0f}s of "
            f"{self.target_wall_clock_s:.0f}s used. A target overrun is not a hard budget stop. "
            f"{verdict}"
        )

    def snapshot(self) -> dict:
        """The budget's own line in the §7 metrics summary.

        Both thresholds are reported, and the two outcomes are separate keys, so
        "this run drifted past guidance" can never be read off the same field as
        "this run hit the circuit breaker" (D1 clause 4). ``max_llm_calls`` and
        ``wall_clock_s`` keep their names and now carry the BACKSTOP values,
        which is what those knobs configure.
        """
        breach = self.breach
        return {
            "max_llm_calls": self.max_llm_calls,
            "wall_clock_s": self.wall_clock_s,
            "target_llm_calls": self.target_llm_calls,
            "target_wall_clock_s": self.target_wall_clock_s,
            "llm_calls_admitted": self.calls,
            "target_exceeded": self.target_exceeded,
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
    run_inline = False
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
