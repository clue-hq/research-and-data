"""Central faithfulness-verdict attribution from internal subjects back to real claims.

The judge table stores two legitimate subject species: a normal claim id ``A`` and, for the
Stage-0 pre-write entailment path, a content-addressed question id ``Q``. Product consumers must
never know which one supplied the verdict. They pass already-scoped :class:`~clue_core.Claim`
objects here, this module performs one batch read over the union of candidate subjects, and the
result is always keyed and labelled by ``A``.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import Claim, ClaimId, Confidence, JudgeVerdict
from clue_obs.otel import MetricSink, get_logger, get_metric_sink
from clue_research.claimstore.entailment_identity import (
    FaithfulnessLookupPlan,
    FaithfulnessSubjectIdentityError,
    faithfulness_lookup_plan,
    faithfulness_redaction_subject_ids,
)

__all__ = [
    "METRIC_FAITHFULNESS_SUBJECT_IDENTITY_ERRORS",
    "FaithfulnessAttribution",
    "read_faithfulness_attributions",
    "redact_faithfulness_rationale",
]

METRIC_FAITHFULNESS_SUBJECT_IDENTITY_ERRORS = (
    "research.claimstore.faithfulness_subject_identity.errors"
)

_log = get_logger(__name__)


class FaithfulnessAttribution(BaseModel):
    """The latest selected verdict, publicly attributed to the real claim ``A`` only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    actual_claim_id: ClaimId
    verdict: JudgeVerdict
    score: Confidence
    judge_model: str
    answering_model: str
    prompt_version: str


async def redact_faithfulness_rationale(
    conn: AsyncConnection,
    claim: Claim,
    *,
    reason_code: str,
) -> FaithfulnessSubjectIdentityError | None:
    """One-way redact every rationale attributable to ``claim`` through the shared A/Q plan.

    A malformed judged-source claim still redacts its actual-claim fallback and returns the typed
    identity error so the caller can emit its domain-specific bounded metric. Keeping the subject
    lookup and SQL here gives DSAR and workspace erasure one owner for this privacy-critical edge.
    """

    identity_error: FaithfulnessSubjectIdentityError | None = None
    try:
        subject_ids = [str(item) for item in faithfulness_redaction_subject_ids(claim)]
    except FaithfulnessSubjectIdentityError as exc:
        subject_ids = [str(claim.id)]
        identity_error = exc
    await conn.execute(
        text(
            """
            UPDATE faithfulness_verdict
            SET rationale = NULL,
                rationale_redacted_at = COALESCE(rationale_redacted_at, now()),
                rationale_redaction_reason =
                    COALESCE(rationale_redaction_reason, :reason_code)
            WHERE claim_id = ANY(CAST(:claim_ids AS uuid[]))
              AND rationale IS NOT NULL
            """
        ),
        {"claim_ids": subject_ids, "reason_code": reason_code},
    )
    return identity_error


async def read_faithfulness_attributions(
    conn: AsyncConnection,
    claims: Sequence[Claim],
    *,
    sink: MetricSink | None = None,
) -> dict[ClaimId, FaithfulnessAttribution]:
    """Read the selected verdict for each already-authorized claim in one SQL round trip.

    Invalid judged-source claims are isolated rather than failing the batch or being labelled
    unsupported. The only emitted dimension is a closed reason code; no field value, evidence, or
    tenant data enters observability.
    """

    plans: list[FaithfulnessLookupPlan] = []
    seen_actual: set[ClaimId] = set()
    metric_sink = sink or get_metric_sink()
    for claim in claims:
        if claim.id in seen_actual:
            continue
        seen_actual.add(claim.id)
        try:
            plans.append(faithfulness_lookup_plan(claim))
        except FaithfulnessSubjectIdentityError as exc:
            metric_sink.add(
                METRIC_FAITHFULNESS_SUBJECT_IDENTITY_ERRORS,
                1,
                {"reason": exc.reason_code},
            )
            _log.warning(
                "claimstore.faithfulness_subject_identity_error reason=%s claim_id=%s",
                exc.reason_code,
                exc.actual_claim_id,
            )

    if not plans:
        return {}

    subject_ids = sorted({str(subject_id) for plan in plans for subject_id in plan.subject_ids})
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT DISTINCT ON (claim_id) claim_id, verdict, score, judge_model, "
                    "answering_model, prompt_version FROM faithfulness_verdict "
                    "WHERE claim_id IN :subject_ids "
                    "ORDER BY claim_id, judged_at DESC, judge_model DESC, prompt_version DESC"
                ).bindparams(bindparam("subject_ids", expanding=True)),
                {"subject_ids": subject_ids},
            )
        )
        .mappings()
        .all()
    )
    by_subject = {ClaimId(row["claim_id"]): row for row in rows}

    out: dict[ClaimId, FaithfulnessAttribution] = {}
    for plan in plans:
        selected = next(
            (by_subject[subject_id] for subject_id in plan.subject_ids if subject_id in by_subject),
            None,
        )
        if selected is None:
            continue
        judge_model = str(selected["judge_model"])
        answering_model = (
            str(selected["answering_model"])
            if selected["answering_model"] is not None
            else judge_model
        )
        out[plan.actual_claim_id] = FaithfulnessAttribution(
            actual_claim_id=plan.actual_claim_id,
            verdict=JudgeVerdict(selected["verdict"]),
            score=float(selected["score"]),
            judge_model=judge_model,
            answering_model=answering_model,
            prompt_version=str(selected["prompt_version"]),
        )
    return out
