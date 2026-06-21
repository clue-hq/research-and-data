"""Test doubles for M5 (stage0) — fake resolvers/judge wired through the real seams.

`stage0` cannot import `resolvers`/`adapters` (the import-linter one-way worker seam), so the live
client-knowledge extractor + Firecrawl wiring is api-composition-root integration. The
reverse-profiling *orchestration* is exercised here by binding a fake
:class:`~clue_research.core.resolver.Resolver` to a real seeded ``source_key`` via
``sources.bind_resolver`` — the same dispatch the production waterfall uses — so M5.1's loop,
budget, versioning and coverage are tested end-to-end and deterministically.
Tests (unlike milestone packages) may import anything.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import JsonValue

from clue_research.core import (
    Claim,
    Entity,
    ExtractionMethod,
    FieldDef,
    JudgeResult,
    JudgeVerdict,
    ResearchMode,
    account_claim,
    new_claim_id,
    new_run_id,
)


class FakeResolver:
    """A :class:`~clue_research.core.resolver.Resolver` that returns a canned claim per field.

    ``values`` maps ``field_key -> value_json``; a field absent from it is a hard miss (``[]``). The
    claim's ``source_tier`` MUST equal the bound manifest's tier (the waterfall asserts it), so a
    fake bound to ``firecrawl_site`` (tier-2) uses ``tier=2``. ``run_id``/``research_mode`` are
    placeholders the waterfall overwrites."""

    def __init__(
        self,
        *,
        tier: int,
        values: dict[str, JsonValue],
        extraction_method: ExtractionMethod = ExtractionMethod.SCRAPE,
        source_url: str | None = "https://client.example",
        confidence: float = 0.9,
        cost_cents: Decimal = Decimal("1.0"),
    ) -> None:
        self.tier = tier
        self._values = values
        self._method = extraction_method
        self._source_url = source_url
        self._confidence = confidence
        self._cost = cost_cents

    def resolve(self, entity: Entity, field: FieldDef) -> list[Claim]:
        if field.field_key not in self._values:
            return []
        return [
            account_claim(
                entity_id=entity.entity_id,
                field_key=field.field_key,
                value_json=self._values[field.field_key],
                source_tier=self.tier,
                extraction_method=self._method,
                confidence=self._confidence,
                run_id=new_run_id(),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                source_url=self._source_url,
                evidence_span="reverse-profiled from the client surface",
                cost_cents=self._cost,
            )
        ]


class RecordingJudge:
    """A :class:`~clue_research.core.verification.FaithfulnessJudge` that records the claims it
    judged and returns a fixed verdict (default ``SUPPORTED``)."""

    def __init__(self, verdict: JudgeVerdict = JudgeVerdict.SUPPORTED) -> None:
        self.verdict = verdict
        self.judged: list[Claim] = []

    async def judge(self, claim: Claim) -> JudgeResult:
        self.judged.append(claim)
        return JudgeResult(
            claim_id=claim.id,
            verdict=self.verdict,
            score=0.9,
            rationale="fake",
        )


def make_tier4_claim(entity_id: object, field_key: str, *, with_span: bool) -> Claim:
    """A tier-4 LLM-synthesis claim (optionally span-less) for promotion/merge tests."""
    return Claim(
        id=new_claim_id(),
        entity_id=entity_id,  # type: ignore[arg-type]
        entity_type="account",  # type: ignore[arg-type]
        field_key=field_key,
        value_json="synthesized value",
        source_tier=4,
        extraction_method=ExtractionMethod.LLM_SYNTHESIS,
        evidence_span="grounded span" if with_span else None,
        confidence=0.7,
        source_url="https://synth.example",
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
    )
