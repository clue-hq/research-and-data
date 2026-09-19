"""The exit-judgment golden set (master plan §3-III-6; PD-part3 P3.6).

File-based fixtures (``fixtures/*.json``) scored over the SAME pure core the live exit path
executes (:func:`clue_design.exit_judgment.decide_exit`) — offline, deterministic, design-local
(the independence contract forbids importing the research subsystem's M9.6 harness; the
pattern is ``clue_memory.evals.golden``'s, deliberately).

Two scoring modes over one fixture set:

* :func:`run_decision_golden` — each fixture's ``judgment`` field plays the LLM's part;
  scores the fail-safe envelope and keeps the fixtures' expected labels internally coherent.
  This is the ``make check`` regression gate: it must pass 100%, always.
* :func:`score_judge` — runs a REAL judge (live model + prompt, or a scripted stand-in) over
  the fixtures and scores its verdicts through the same envelope. Swapping the judge model or
  bumping :data:`~clue_design.exit_judgment.EXIT_JUDGMENT_PROMPT_VERSION` re-runs this set;
  :func:`check_exit_regressions` compares the scoreboards and names every kind that got
  worse. The scoreboard is **namespaced by fixture kind** (the M9.6 lesson): an ambiguous
  regression cannot hide behind clearly-design passes.

The fixture kinds are the master plan's own taxonomy — clearly-design turns, clearly-strategy
turns, the ambiguous middle ("will this ad resonate with CFOs?") — plus the lock-in/abandon
exits and the fail-safe negatives (malformed judgments that must never close the leg). Each
ambiguous fixture documents its ratified expected answer in ``why``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from clue_design.exit_judgment import ExitJudgment, ExitReason, decide_exit

FIXTURES_DIR = Path(__file__).parent / "fixtures"

FixtureKind = Literal[
    "clearly_design",
    "clearly_strategy",
    "ambiguous",
    "lock_in",
    "abandon",
    "new_artifact",
    "fail_safe",
]

#: A judge maps a fixture's inputs to the model's verdict (or ``None`` for unparseable
#: output). The live judge renders the prompt from the same fields and parses the completion
#: with :func:`clue_design.exit_judgment.parse_exit_judgment`.
ExitJudge = Callable[["ExitGoldenFixture"], ExitJudgment | None]


class ExpectedDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action: Literal["continue", "finish"]
    reason: ExitReason | None = None
    fail_safe: bool = False


class ExitGoldenFixture(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    kind: FixtureKind
    #: v2 judge inputs: the artifact this session is bound to and the message's resolved
    #: tags, as the runner renders them. Absent on fixtures written before v2.
    artifact: str | None = None
    tags: tuple[str, ...] = ()
    brief: str
    history: tuple[dict[str, str], ...] = ()
    message: str
    #: The canned verdict playing the LLM's part in :func:`run_decision_golden`. ``None``
    #: models unparseable output (the fail-safe negatives).
    judgment: ExitJudgment | None = None
    expected: ExpectedDecision
    #: The ratified ruling's one-line rationale — required reading on ambiguous fixtures.
    why: str | None = None


class GoldenReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    total: int
    passed: int
    failures: tuple[str, ...] = ()
    #: ``kind -> (passed, total)`` — the namespaced scoreboard regressions are checked on.
    by_kind: dict[str, tuple[int, int]] = {}

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 1.0


def load_fixtures(directory: Path = FIXTURES_DIR) -> list[ExitGoldenFixture]:
    fixtures = [
        ExitGoldenFixture(**json.loads(path.read_text()))
        for path in sorted(directory.glob("*.json"))
    ]
    if not fixtures:
        raise FileNotFoundError(f"no exit-judgment golden fixtures under {directory}")
    return fixtures


def _score(
    fixtures: list[ExitGoldenFixture],
    verdict_for: ExitJudge,
) -> GoldenReport:
    failures: list[str] = []
    by_kind: dict[str, list[int]] = {}
    for fixture in fixtures:
        tally = by_kind.setdefault(fixture.kind, [0, 0])
        tally[1] += 1
        actual = decide_exit(verdict_for(fixture))
        expected = fixture.expected
        if (
            actual.action == expected.action
            and actual.reason == expected.reason
            and actual.fail_safe == expected.fail_safe
        ):
            tally[0] += 1
            continue
        failures.append(
            f"{fixture.name} [{fixture.kind}]: expected "
            f"{expected.action}/{expected.reason} (fail_safe={expected.fail_safe}), got "
            f"{actual.action}/{actual.reason} (fail_safe={actual.fail_safe})"
        )
    return GoldenReport(
        total=len(fixtures),
        passed=len(fixtures) - len(failures),
        failures=tuple(failures),
        by_kind={kind: (passed, total) for kind, (passed, total) in by_kind.items()},
    )


def run_decision_golden(directory: Path = FIXTURES_DIR) -> GoldenReport:
    """Score the fail-safe envelope with each fixture's canned ``judgment`` as the LLM."""

    return _score(load_fixtures(directory), lambda fixture: fixture.judgment)


def score_judge(judge: ExitJudge, directory: Path = FIXTURES_DIR) -> GoldenReport:
    """Score a real judge's verdicts over the golden set, through the same envelope.

    Fail-safe fixtures are scored on the ENVELOPE's behavior, not the judge's telepathy:
    their ``judgment`` (malformed by construction) stands in regardless of the judge, so a
    live-model scoreboard is comparable to the decision baseline kind-for-kind.
    """

    fixtures = load_fixtures(directory)
    return _score(
        fixtures,
        lambda fixture: fixture.judgment if fixture.kind == "fail_safe" else judge(fixture),
    )


def check_exit_regressions(baseline: GoldenReport, current: GoldenReport) -> tuple[str, ...]:
    """Every kind whose pass count dropped, as loud sentences. Empty = no regression."""

    regressions: list[str] = []
    for kind, (passed, total) in sorted(baseline.by_kind.items()):
        current_passed, current_total = current.by_kind.get(kind, (0, 0))
        if current_total != total:
            regressions.append(
                f"{kind}: fixture count changed ({total} -> {current_total}) — "
                "re-baseline before comparing"
            )
        elif current_passed < passed:
            regressions.append(f"{kind}: {passed}/{total} -> {current_passed}/{current_total}")
    return tuple(regressions)


def regression_exit_code(regressions: tuple[str, ...]) -> int:
    return 1 if regressions else 0
