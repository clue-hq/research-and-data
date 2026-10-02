"""Per-run summary metrics for a design deepagent turn (fast-loop v1 §7).

WHY THIS EXISTS. The 2026-08-24 forensics that produced
``docs/deepagent-fast-loop-v1-spec.md`` had to hand-aggregate ~6000 raw log lines
to learn that one scene-ad run spent 43m18s across 178 sequential LLM calls and
13.5M input tokens, reaching its first preview only at +15.4 min. Every one of
those numbers was already IN the trace — nobody could read it without a
spreadsheet. This module makes the same aggregation automatic, so the §1 gate
table (≤10 min wall, ≤45 calls, ≤4 min to first preview, ≤3M input tokens) can
be proven or refuted from one line of one file.

WHAT IT IS. A plain in-process counter object, one per run, fed by events the
runtime ALREADY produces:

* the per-role ``TraceCallbackHandler`` (``trace_callbacks.py``) calls
  :meth:`RunMetrics.record_llm_completed` / :meth:`record_llm_failed` from
  inside its own already-wrapped handler bodies — the same call that emits
  ``llm_call_completed``;
* ``LumenDesignTools.compile_dsl_block`` calls
  :meth:`mark_compile_iteration` next to its own iteration bump;
* ``LumenDesignTools._write_and_validate_preview_artifacts`` calls
  :meth:`mark_first_preview` the first time a preview artifact validates;
* ``LumenDesignTools.preflight_design`` calls :meth:`record_autofix` once per
  §5.4 deterministic-autofix attempt, accepted or rolled back.

COST. Integer arithmetic under one ``threading.Lock`` (the lock is required for
the same reason ``LumenDesignTools._record_lock`` is: batched read-only tool
calls run on langgraph's ToolNode thread pool, so callbacks arrive from
concurrent threads). It adds **no** LLM call, **no** tool call, and no I/O at
all on the hot loop — the single write happens once, at run end, in
:func:`emit_run_metrics`.

PURELY ADDITIVE. No existing event shape changes and no field is removed; the
``run_metrics`` event and ``metrics.json`` are new surfaces alongside them.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Optional

from py_lumen_obs import get_logger

#: The one summary event name. Emitted once per run, to the obs logger (so it
#: lands in the run's ``logs/run.jsonl`` next to the per-call trace) and to the
#: substrate's own trace/event sink (so it reaches the durable ``run_event``
#: stream the run view reads).
RUN_METRICS_EVENT = "run_metrics"

#: A model call slower than this is counted separately. 30s is the forensics
#: threshold: the baseline run's tail was 10–25s/call with a long 86–104s tail
#: that the SDK's socket-silence timeout let through (spec §5.6, and
#: ``docs/case-studies/deepagent-latency.md``). The count is the cheap signal
#: for "is the watchdog doing its job".
SLOW_CALL_MS = 30_000

#: The file written next to ``final.json`` in the run directory.
METRICS_FILENAME = "metrics.json"

_log = get_logger("lumen_agent.run_metrics")


class _RoleCounters:
    """One role's slice of the run. Plain mutable ints; never shared unlocked."""

    __slots__ = (
        "calls",
        "failed",
        "duration_ms_total",
        "duration_ms_max",
        "input_tokens",
        "output_tokens",
    )

    def __init__(self) -> None:
        self.calls = 0
        self.failed = 0
        self.duration_ms_total = 0
        self.duration_ms_max = 0
        self.input_tokens = 0
        self.output_tokens = 0

    def as_dict(self) -> dict:
        return {
            "calls": self.calls,
            "failed": self.failed,
            "duration_ms_total": self.duration_ms_total,
            "duration_ms_max": self.duration_ms_max,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }


def _int(value: Any) -> int:
    """Tokens/durations arrive from provider payloads and are routinely ``None``.

    A missing count is 0 here rather than a crash or a ``None`` that poisons the
    sum: the tracer already records the per-call ``None`` verbatim in
    ``llm_call_completed``, so the honest per-call fact survives; this summary
    only claims "what we could count".
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


class RunMetrics:
    """Per-run counters. Construct ONE at the start of a run and share it."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._lock = threading.Lock()
        self._started_monotonic = time.monotonic()
        self._roles: dict[str, _RoleCounters] = {}
        self._llm_calls_over_30s = 0
        self._compile_iterations = 0
        self._first_preview_monotonic: Optional[float] = None
        # Fast-loop v1 §5.6. `_budget` is the run's `budget.RunBudget` when the
        # flag is on (None otherwise), so the summary can report the thresholds
        # the run was actually held to and not just the numbers it hit.
        # `_budget_breach` is the BACKSTOP triple, recorded by the budget itself
        # at the moment it refuses a call — kept separately so it survives even
        # if the budget object is never handed over.
        #
        # `_budget_target_exceeded` is its D1 counterpart and a DIFFERENT FACT:
        # the run went past the guidance it was given, which is informational.
        # The two are separate fields, separate summary keys and separate words
        # on the human line precisely so nobody can read routine drift past a
        # 900s target as a run that hung (ruling D1, clause 4).
        self._budget: Any = None
        self._budget_breach: Optional[dict] = None
        self._budget_target_exceeded: Optional[dict] = None
        # §5.2: how many times the inner-iteration cap refused a compile. A
        # non-zero count is the honest signal that a round wanted more passes
        # than the cap allows — the number to tune the cap against.
        self._inner_iteration_refusals = 0
        self._autofix_applied = 0
        self._autofix_rolled_back = 0
        self._autofix_by_class: dict[str, int] = {}

    # -- registration ------------------------------------------------------- #
    def register_role(self, role: str) -> None:
        """Declare a role up front so a role that never spoke still reports zeros.

        Without this, a run in which the reviewer was never dispatched would
        simply omit ``reviewer`` — indistinguishable from a run where the
        reviewer role does not exist. "Zero calls" is the interesting fact once
        the spec's §5.3 reviewer retirement lands.
        """
        with self._lock:
            self._roles.setdefault(role, _RoleCounters())

    # -- fed by the tracer -------------------------------------------------- #
    def record_llm_completed(
        self,
        *,
        role: str,
        duration_ms: Any,
        input_tokens: Any,
        output_tokens: Any,
    ) -> None:
        ms = _int(duration_ms)
        with self._lock:
            counters = self._roles.setdefault(role, _RoleCounters())
            counters.calls += 1
            counters.duration_ms_total += ms
            counters.duration_ms_max = max(counters.duration_ms_max, ms)
            counters.input_tokens += _int(input_tokens)
            counters.output_tokens += _int(output_tokens)
            if ms > SLOW_CALL_MS:
                self._llm_calls_over_30s += 1

    def record_llm_failed(self, *, role: str, duration_ms: Any) -> None:
        """A failed call still burned wall clock — the 20m42s baseline run died
        on a quota 403, so a failed run's metrics are the ones that matter most."""
        ms = _int(duration_ms)
        with self._lock:
            counters = self._roles.setdefault(role, _RoleCounters())
            counters.calls += 1
            counters.failed += 1
            counters.duration_ms_total += ms
            counters.duration_ms_max = max(counters.duration_ms_max, ms)
            if ms > SLOW_CALL_MS:
                self._llm_calls_over_30s += 1

    # -- fed by the substrate ------------------------------------------------ #
    def mark_compile_iteration(self) -> None:
        with self._lock:
            self._compile_iterations += 1

    def mark_first_preview(self) -> None:
        """First VALIDATED preview artifact. Idempotent — only the first wins."""
        with self._lock:
            if self._first_preview_monotonic is None:
                self._first_preview_monotonic = time.monotonic()

    def mark_inner_iteration_refused(self) -> None:
        """§5.2: the per-round inner-iteration cap refused one more compile."""
        with self._lock:
            self._inner_iteration_refusals += 1

    # -- fed by the fast-loop budget (§5.6) ---------------------------------- #
    def attach_budget(self, budget: Any) -> None:
        """Register the run's `budget.RunBudget` so the summary reports it."""
        with self._lock:
            self._budget = budget

    def record_budget_breach(self, *, kind: str, limit: float, observed: float) -> None:
        """The FIRST BACKSTOP hit only — a sticky budget can only stop once.

        Abnormal by construction under D1: the target does not come through
        here, so a non-null `budget_exhausted` means a hung or runaway run.
        """
        with self._lock:
            if self._budget_breach is None:
                self._budget_breach = {
                    "kind": kind,
                    "limit": limit,
                    "observed": observed,
                }

    def record_budget_target_exceeded(
        self, *, kind: str, target: float, observed: float
    ) -> None:
        """The FIRST target crossing only. INFORMATIONAL — nothing stopped.

        Deliberately shaped with a `target` key rather than the breach's `limit`,
        so a consumer reading the two dicts cannot confuse them by shape either.

        READING THE ABSENCE OF THIS KEY. It is recorded at a call the budget
        ADMITTED, so a run that leaps from inside its target straight past the
        backstop (one very long call) reports `budget_exhausted` with no
        `budget_target_exceeded` beside it. That is not "stayed within
        guidance" — the config validator guarantees backstop >= target, so a
        backstop hit is past-target by construction. Count drift as
        `budget_target_exceeded OR budget_exhausted`, never the former alone.
        """
        with self._lock:
            if self._budget_target_exceeded is None:
                self._budget_target_exceeded = {
                    "kind": kind,
                    "target": target,
                    "observed": observed,
                }
    def record_autofix(self, klass: str, *, accepted: bool) -> None:
        """One §5.4 deterministic-autofix attempt.

        Both halves are counted, and they answer different questions.
        ``autofix_count`` is the payoff — repairs that landed WITHOUT a model
        call, which is the number the §1 call-count gate is trying to move.
        ``autofix_rolled_back`` is the honesty check: a class that keeps getting
        rejected is burning two engine calls to hand the author the same
        diagnostic it started with, and should be narrowed or retired rather
        than left running.
        """
        with self._lock:
            if accepted:
                self._autofix_applied += 1
                self._autofix_by_class[klass] = self._autofix_by_class.get(klass, 0) + 1
            else:
                self._autofix_rolled_back += 1

    # -- the summary --------------------------------------------------------- #
    def wall_time_ms(self) -> int:
        return int((time.monotonic() - self._started_monotonic) * 1000)

    def snapshot(
        self,
        *,
        outcome: Optional[str] = None,
        status: Optional[str] = None,
        stop_reason: Optional[str] = None,
        rounds_total: int = 0,
    ) -> dict:
        """The full summary dict. Safe to call at any time; called once at run end."""
        with self._lock:
            by_role = {role: counters.as_dict() for role, counters in sorted(self._roles.items())}
            first_preview = self._first_preview_monotonic
            budget = self._budget
            budget_breach = dict(self._budget_breach) if self._budget_breach else None
            budget_target_exceeded = (
                dict(self._budget_target_exceeded) if self._budget_target_exceeded else None
            )
            inner_iteration_refusals = self._inner_iteration_refusals
            summary = {
                "run_id": self.run_id,
                "outcome": outcome,
                "status": status,
                "stop_reason": stop_reason,
                "wall_time_ms": self.wall_time_ms(),
                "llm_calls_total": sum(r["calls"] for r in by_role.values()),
                "llm_calls_failed": sum(r["failed"] for r in by_role.values()),
                "llm_calls_over_30s": self._llm_calls_over_30s,
                "input_tokens_total": sum(r["input_tokens"] for r in by_role.values()),
                "output_tokens_total": sum(r["output_tokens"] for r in by_role.values()),
                "time_to_first_preview_ms": (
                    int((first_preview - self._started_monotonic) * 1000)
                    if first_preview is not None
                    else None
                ),
                "rounds_total": int(rounds_total),
                "compile_iterations_total": self._compile_iterations,
                "autofix_count": self._autofix_applied,
                "autofix_rolled_back": self._autofix_rolled_back,
                "autofix_by_class": dict(sorted(self._autofix_by_class.items())),
                "by_role": by_role,
            }
        # Fast-loop v1 §5.6/§5.2. Both keys are ADDITIVE and both are omitted on
        # a flag-off run, so a pre-fast-loop `metrics.json` is byte-identical:
        # no budget exists to report and the inner-iteration cap never fires.
        # `budget.snapshot()` is read outside the metrics lock on purpose — the
        # budget takes its own lock, and taking them in two orders across two
        # call paths is how deadlocks are written.
        if budget is not None:
            try:
                summary["budget"] = budget.snapshot()
            except Exception:  # noqa: BLE001 - never fail a turn on its own metrics
                summary["budget"] = None
        if budget_target_exceeded is not None:
            # D1: informational, and additive like every other fast-loop key —
            # absent on a run that stayed inside its guidance, and absent
            # entirely off the flag (no budget exists to have a target).
            summary["budget_target_exceeded"] = budget_target_exceeded
        if budget_breach is not None:
            summary["budget_exhausted"] = budget_breach
        if inner_iteration_refusals:
            summary["inner_iteration_refusals"] = inner_iteration_refusals
        return summary


# --------------------------------------------------------------------------- #
# run-end emission
# --------------------------------------------------------------------------- #
def count_round_dirs(rounds_dir: Path, *, above: int = 0) -> int:
    """How many ``rounds/round_N`` directories the turn produced.

    Rounds are a FILESYSTEM fact here: the orchestrator creates each round
    directory through its own file tools, so the harness never sees a "round
    started" call to count. One directory listing at run end is cheaper and more
    honest than inferring rounds from delegation counts, and it is deliberately
    NOT done in the hot loop.

    ``above`` is the round base this turn inherited from its design session (the
    workspace outlives the turn, so earlier turns' round directories are still
    there). Only rounds numbered above it belong to this turn; the default 0
    counts them all, which is every non-session run.
    """
    try:
        if not rounds_dir.is_dir():
            return 0
        return sum(
            1
            for child in rounds_dir.iterdir()
            if child.is_dir()
            and child.name.startswith("round_")
            and child.name[len("round_") :].isdigit()
            and int(child.name[len("round_") :]) > above
        )
    except OSError:
        return 0


def emit_run_metrics(
    tools: Any,
    *,
    outcome: Optional[str] = None,
    status: Optional[str] = None,
    stop_reason: Optional[str] = None,
    rounds_dir: Optional[Path] = None,
) -> Optional[dict]:
    """Emit the ONE summary event and write ``metrics.json``. Never raises.

    Called from the harness runner's ``finally``, so it runs on EVERY terminal
    outcome — accepted, clarification_requested, an honest ``failed`` finalize,
    a recursion-limit abort, and an outright exception. A failed run's metrics
    are the ones that matter most (spec §1: the 20m42s run that died on quota).

    Three sinks, deliberately, because three different readers need it:

    1. ``logs/run.jsonl`` via the obs logger — what ``python -m lumen_agent.trace``
       renders and what a human greps;
    2. ``metrics.json`` in the turn directory, next to ``final.json`` — a file
       artifact that outlives log rotation;
    3. the substrate's ``record`` (trace.jsonl + the optional event sink), whose
       sink lands the summary on the durable ``run_event`` stream so the run
       view can render it without touching the worker's filesystem.

    A failure in any of the three is logged and swallowed: metrics are
    observability, and observability must never be the thing that fails a turn.
    """
    metrics: Optional[RunMetrics] = getattr(tools, "metrics", None)
    if metrics is None:
        return None
    try:
        solo_rounds = getattr(tools, "solo_rounds_executed", None)
        summary = metrics.snapshot(
            outcome=outcome,
            status=status,
            stop_reason=stop_reason,
            rounds_total=(
                solo_rounds if solo_rounds is not None
                else count_round_dirs(
                    rounds_dir, above=getattr(tools, "round_base", 0)
                ) if rounds_dir is not None else 0
            ),
        )
    except Exception as error:  # noqa: BLE001 - never fail a turn on its own metrics
        _log.warning("run_metrics_snapshot_failed", error=f"{type(error).__name__}: {error}")
        return None

    try:
        _log.info(RUN_METRICS_EVENT, **summary)
    except Exception:  # noqa: BLE001
        pass

    try:
        # The turn's own folder — which is the run folder unless this run belongs
        # to a design session, where `turn_dir` is where its `final.json` lands.
        turn_dir = getattr(tools, "turn_dir", None) or getattr(tools, "trace_dir", None)
        if turn_dir is not None:
            (Path(turn_dir) / METRICS_FILENAME).write_text(
                json.dumps(summary, indent=2), encoding="utf-8"
            )
    except Exception as error:  # noqa: BLE001
        _log.warning("run_metrics_write_failed", error=f"{type(error).__name__}: {error}")

    try:
        record = getattr(tools, "record", None)
        if callable(record):
            record(
                "coordinator",
                RUN_METRICS_EVENT,
                output_summary=summarize_line(summary),
                payload=summary,
                # The sink push is otherwise a five-field lightweight subset, so
                # the summary rides the opt-in `sink_extra` channel — that is what
                # puts it on the durable run_event stream for the run view.
                sink_extra={"metrics": summary},
            )
    except Exception as error:  # noqa: BLE001
        _log.warning("run_metrics_record_failed", error=f"{type(error).__name__}: {error}")

    return summary


def summarize_line(summary: dict) -> str:
    """One human line: the §1 gate row, in the order the spec's table lists it."""
    ttfp = summary.get("time_to_first_preview_ms")
    line = (
        f"{_ms(summary.get('wall_time_ms'))} wall · "
        f"{summary.get('llm_calls_total', 0)} llm calls · "
        f"first preview {_ms(ttfp) if ttfp is not None else 'never'} · "
        f"in {summary.get('input_tokens_total', 0)} tok / "
        f"out {summary.get('output_tokens_total', 0)} tok · "
        f"{summary.get('rounds_total', 0)} rounds · "
        f"{summary.get('compile_iterations_total', 0)} compiles · "
        f"{summary.get('autofix_count', 0)} autofix"
    )
    # §5.6 / D1: the two budget outcomes must be readable at a glance and must
    # not read alike. "past target" is a run that cost more than guidance asked;
    # "BACKSTOP HIT" is a run the circuit breaker had to stop. Both are appended
    # only when they happened, so the flag-off line is unchanged.
    exceeded = summary.get("budget_target_exceeded")
    if isinstance(exceeded, dict) and exceeded.get("kind"):
        line += f" · past target ({exceeded['kind']})"
    breach = summary.get("budget_exhausted")
    if isinstance(breach, dict) and breach.get("kind"):
        line += f" · BUDGET BACKSTOP HIT ({breach['kind']})"
    return line


def _ms(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "?"
    ms = int(value)
    if ms >= 60_000:
        return f"{ms // 60_000}m{(ms % 60_000) // 1000:02d}s"
    if ms >= 1000:
        return f"{ms / 1000:.1f}s"
    return f"{ms}ms"
