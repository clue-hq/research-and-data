"""The M9.3-backed implementation of the interview's ``ClaimEntailmentJudge`` port (PC-C8 §6c-b).

A claim's value must be supported by the exact span the client said. For a text value that is a
substring check and needs nobody's opinion. For a **typed** value — ``true``, ``["SOAP", "APSO",
"H&P"]``, ``12`` — no substring check can ever pass, because no rendering of a boolean or a list
appears in English prose; the 2026-08-01 acceptance run refused eight true, correctly-quoted facts
for exactly that reason and left the Client KB empty. Entailment is the right question there, and
the platform already ships an entailment judge: M9.3's :class:`~clue_research.verification.
FaithfulnessJudgeImpl`, cached, prompt-injection-hardened, and policy-as-data.

``clue_research.stage0`` may not import ``clue_research.verification`` (the milestone-independence
contract), so the interview declares the port and this composition-root module owns the wiring —
the same inversion :mod:`clue_api.statement_evidence` does for statement quotes. Nothing here forks
the judge's prompt, threshold, or persistence.

**The one honest deviation: what ``faithfulness_verdict.claim_id`` holds on this path.** The judge
caches on ``(claim_id, judge_model, prompt_version)``, and an interview claim's id is
``uuid5(onboarding_input_id, entity, field_key)`` — it does *not* include the value or the quote.
Keying the judgment on it would mean a model whose first attempt was refused could never repair it
inside the same turn: the corrected value asks the same cache key and is served the stale
``unsupported``, which is precisely the unrepairable loop this package exists to remove. So the
judgment is asked under a **content-addressed question id** instead —
:func:`~clue_research.claimstore.entailment_judgment_id`, which lives in the claim substrate rather
than here precisely because ``clue_research.compliance`` (DSAR redaction) and, later, M12
provenance must recompute the same id and may not import this module. That module's docstring owns
the full rationale, including why object keys are sorted.

Consequences, all deliberate:

* a different value or a different quote is a different question, so repair works;
* the same question is asked once, ever, across the precondition check and the engine's own check;
* the verdict row's ``claim_id`` is a question id, not a claim id. It is recomputable from any
  written claim (``field_key`` + ``value_json`` + ``evidence_span``), so "which verdict admitted
  this claim?" stays a deterministic lookup — and DSAR erasure depends on that recompute — while
  ``claim.source_key = 'client_interview_judged'`` is the per-claim flag that says to go looking.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import JsonValue

from clue_core import (
    Claim,
    EntityId,
    EntityType,
    ExtractionMethod,
    JudgeVerdict,
    ResearchMode,
    UnitInterval,
    new_run_id,
)
from clue_core.verification import FaithfulnessJudge
from clue_obs import get_logger
from clue_research.claimstore import entailment_judgment_id
from clue_research.stage0 import ClaimEntailment
from clue_research.verification import DEFAULT_JUDGE_POLICY

log = get_logger(__name__)

__all__ = ["FaithfulnessClaimEntailmentJudge"]

#: The judge is asked about a value and a span, never about an entity's wider record, so the probe
#: claim's non-evidential fields are fixed. Tier 1 is the honest one (the client is a tier-1 source)
#: and — because the M9.3 judge drives ``verification_status`` for tier 4 *only* — it also keeps the
#: judgment from writing status for a claim row that does not exist yet.
_PROBE_TIER = 1


class FaithfulnessClaimEntailmentJudge:
    """Ask the M9.3 faithfulness judge whether one quote entails one typed value."""

    def __init__(
        self,
        *,
        judge: FaithfulnessJudge,
        supported_threshold: UnitInterval = DEFAULT_JUDGE_POLICY.supported_threshold,
    ) -> None:
        self._judge = judge
        self._supported_threshold = supported_threshold

    async def entails(
        self, *, entity_id: EntityId, field_key: str, value: JsonValue, quote: str
    ) -> ClaimEntailment:
        probe = Claim(
            id=entailment_judgment_id(field_key=field_key, value=value, quote=quote),
            entity_id=entity_id,
            # The probe is a question about text, not a personal-data write: ACCOUNT keeps it clear
            # of the contact-facet governance validator, which asks for provenance this question
            # has no claim to. The real claim carries its own entity type and governance.
            entity_type=EntityType.ACCOUNT,
            field_key=field_key,
            value_json=value,
            source_tier=_PROBE_TIER,
            extraction_method=ExtractionMethod.HUMAN,
            evidence_span=quote,
            confidence=1.0,
            cost_cents=Decimal(0),
            run_id=new_run_id(),
            research_mode=ResearchMode.ACCOUNT_PROFILING,
        )
        try:
            result = await self._judge.judge(probe)
        except Exception as exc:  # noqa: BLE001 - a judge outage is not an unsupported value
            # Fail closed, but not *dishonestly* closed: "we could not ask" and "the words do not
            # support it" are different facts and the model gets told which one happened.
            log.warning(
                "stage0.interview.entailment_judge_unavailable",
                field_key=field_key,
                detail=str(exc),
            )
            return ClaimEntailment(supported=False, verdict="unavailable")
        supported = (
            result.verdict is JudgeVerdict.SUPPORTED and result.score >= self._supported_threshold
        )
        return ClaimEntailment(
            supported=supported, verdict=result.verdict.value, score=float(result.score)
        )
