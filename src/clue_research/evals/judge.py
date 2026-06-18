"""The LLM-as-judge seam + deterministic offline stubs (M0.6).

The faithfulness judge (substrate §6 / conventions §6) is invoked behind the :class:`Judge` protocol
so the judge *model* is swappable without touching the harness — and so CI runs with a deterministic
stub (no LLM/provider call). The production judge lands with M9; M0.6 ships the seam + stubs and
the regression-on-swap path (two stubs that disagree, to prove a judge swap moves the metrics).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from clue_research.core import Claim


class JudgeVerdict(BaseModel):
    """Whether a claim's value is entailed by its evidence span (claim-level groundedness)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entailed: bool
    reason: str = ""


@runtime_checkable
class Judge(Protocol):
    """Swappable faithfulness judge. Production wires an LLM behind this; CI uses a stub."""

    name: str

    def judge(self, claim: Claim) -> JudgeVerdict: ...


class StubJudge:
    """Lenient deterministic judge (no LLM): entailed iff the claim has a non-empty span."""

    name = "stub"

    def judge(self, claim: Claim) -> JudgeVerdict:
        span = claim.evidence_span or ""
        return JudgeVerdict(entailed=bool(span), reason="has evidence span" if span else "no span")


class GroundedStubJudge:
    """Stricter deterministic judge: entailed iff the stringified value appears in the span.

    Disagrees with `StubJudge` on a span-present-but-value-absent claim — exactly what
    makes a judge swap visible as a metrics delta (the regression-on-swap demonstration)."""

    name = "grounded_stub"

    def judge(self, claim: Claim) -> JudgeVerdict:
        span = claim.evidence_span or ""
        entailed = bool(span) and str(claim.value_json) in span
        return JudgeVerdict(
            entailed=entailed, reason="value found in span" if entailed else "value not in span"
        )
