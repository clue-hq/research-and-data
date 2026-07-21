"""The reconciliation eval golden set (Doc M §18: the one genuinely hard component ships with
its measuring stick beside it).

File-based fixtures (``fixtures/*.json``) scored over :func:`clue_memory.reconcile.decide` —
the SAME pure decision core the live write seam executes, so the golden set measures the real
path, offline, deterministically (the fixture's ``judgment`` field plays the LLM's part; a null
judgment exercises the fail-safe). Memory-local by design: Rule S1 forbids importing the
research subsystem's M9.6 harness, and the decision layer needs no DB.

Swapping the judge model/prompt re-runs this same set: score the new judge's real outputs into
the ``judgment`` slots and compare scoreboards.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from clue_core import (
    MemoryRejected,
    MemorySubmission,
    ReconcileCandidate,
    ReconcileJudgment,
)
from clue_memory.reconcile import Disposition, decide

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class GoldenFixture(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    submission: MemorySubmission
    candidates: tuple[ReconcileCandidate, ...] = ()
    judgment: ReconcileJudgment | None = None
    # Expected outcome: either a disposition {verdict, target_memory_id?, park_proposed?}
    # or a rejection {reason}.
    expected: dict[str, str | bool | None]


class GoldenReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    total: int
    passed: int
    failures: tuple[str, ...] = ()

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 1.0


def load_fixtures(directory: Path = FIXTURES_DIR) -> list[GoldenFixture]:
    fixtures = [
        GoldenFixture(**json.loads(path.read_text())) for path in sorted(directory.glob("*.json"))
    ]
    if not fixtures:
        raise FileNotFoundError(f"no golden fixtures under {directory}")
    return fixtures


def _check(fixture: GoldenFixture) -> str | None:
    """None = pass; otherwise the failure sentence."""
    actual = decide(fixture.submission, fixture.candidates, fixture.judgment)
    expected = fixture.expected
    if isinstance(actual, MemoryRejected):
        if expected.get("kind") != "rejected":
            return f"{fixture.name}: expected {expected}, got rejection {actual.reason.value}"
        if actual.reason.value != expected.get("reason"):
            return (
                f"{fixture.name}: expected rejection {expected.get('reason')}, "
                f"got {actual.reason.value}"
            )
        return None
    assert isinstance(actual, Disposition)
    if expected.get("kind") != "disposition":
        return f"{fixture.name}: expected {expected}, got disposition {actual.verdict.value}"
    if actual.verdict.value != expected.get("verdict"):
        return (
            f"{fixture.name}: expected verdict {expected.get('verdict')}, "
            f"got {actual.verdict.value}"
        )
    if actual.target_memory_id != expected.get("target_memory_id"):
        return (
            f"{fixture.name}: expected target {expected.get('target_memory_id')}, "
            f"got {actual.target_memory_id}"
        )
    if actual.park_proposed != bool(expected.get("park_proposed", False)):
        return f"{fixture.name}: park_proposed mismatch"
    return None


def run_golden(directory: Path = FIXTURES_DIR) -> GoldenReport:
    fixtures = load_fixtures(directory)
    failures = tuple(f for f in (_check(fx) for fx in fixtures) if f is not None)
    return GoldenReport(
        total=len(fixtures), passed=len(fixtures) - len(failures), failures=failures
    )
