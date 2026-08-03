"""The identity of one *entailment question* — a content address over (field, value, span).

The M9.3 faithfulness judge caches and audits on ``faithfulness_verdict.claim_id``. For a tier-4
synthesized claim that column is genuinely the claim's id: the claim exists first and is judged
afterwards. PC-C8 §6c-b inverts the order — a typed interview value must be *vouched for before it
is written*, and its prospective claim id (``uuid5(onboarding_input, entity, field_key)``) carries
neither the value nor the quote, so caching under it would answer a corrected second attempt with
the refused first attempt's verdict and make repair impossible. The judgment therefore gets its own
identity, derived from exactly what the question is about.

**This lives in the claim substrate, not at a call site, because three packages must agree on it
and none of them may import the others** (conventions §2 / the milestone-independence contract):

* ``clue_api.claim_entailment`` asks the question, so the verdict row lands under this id;
* ``clue_research.compliance.dsar`` recomputes it from an erased claim to redact that verdict's
  free-text rationale — which quotes the client's own words, so a mismatch here is a silent
  erasure hole, not a cosmetic one (it was exactly that for one commit);
* ``claimstore.faithfulness_attribution`` uses it to report the verdict through M12 narrative and
  the review projector while continuing to label the public object with the real claim id.

The recompute is what makes the indirection honest: given any written claim, ``field_key`` +
``value_json`` + ``evidence_span`` reproduce the question id, so "which verdict admitted this
claim?" stays a deterministic lookup, and ``claim.source_key = 'client_interview_judged'`` is the
per-claim flag that says to go looking.

Two subtleties, both deliberate:

* **Object keys are sorted.** ``jsonb`` does not preserve key order, so a value read back out of
  ``claim`` is spelled differently from the one that was judged; an order-sensitive digest would
  miss its own verdict on every recompute (found live, 2026-08-01). List order is preserved — a
  list is a sequence, not a set.
* **Two subjects whose claims share a field, a value *and* a span share one question**, so erasing
  either redacts the shared rationale. That is the correct direction: the rationale quotes that
  exact text, which is the erased subject's words too.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from pydantic import JsonValue

from clue_core import Claim, ClaimId

__all__ = [
    "ENTAILMENT_JUDGMENT_NAMESPACE",
    "SOURCE_CLIENT_INTERVIEW_JUDGED",
    "FaithfulnessLookupPlan",
    "FaithfulnessSubjectIdentityError",
    "entailment_judgment_id",
    "faithfulness_lookup_plan",
]

#: The uuid5 name prefix for an entailment *question*. Distinct from the interview's claim prefix
#: (``stage0-interview-claim:``) so a question id can never collide with a claim id.
ENTAILMENT_JUDGMENT_NAMESPACE = "stage0-interview-entailment"

#: The single durable producer marker for claims admitted by the pre-write entailment judge.
#: It lives beside the A→(Q,A) mapping — not in Stage 0 — so every reader and DSAR use exactly the
#: same discriminator without importing the producing subsystem.
SOURCE_CLIENT_INTERVIEW_JUDGED = "client_interview_judged"


@dataclass(frozen=True, slots=True)
class FaithfulnessLookupPlan:
    """The ordered verdict subjects for one public/actual claim ``A``.

    ``subject_ids`` is priority-ordered. Ordinary claims have ``(A,)``; a judged interview claim
    has ``(Q, A)`` so the content-addressed pre-write judgment wins and ``A`` remains a legacy
    fallback. Consumers must key and label their result with ``actual_claim_id`` only.
    """

    actual_claim_id: ClaimId
    subject_ids: tuple[ClaimId, ...]


class FaithfulnessSubjectIdentityError(ValueError):
    """A marked judged claim lacks the immutable evidence needed to reconstruct ``Q``."""

    reason_code = "judged_interview_evidence_span_missing"

    def __init__(self, actual_claim_id: ClaimId) -> None:
        self.actual_claim_id = actual_claim_id
        super().__init__(
            f"cannot resolve faithfulness subject for claim {actual_claim_id}: {self.reason_code}"
        )


def entailment_judgment_id(*, field_key: str, value: JsonValue, quote: str) -> ClaimId:
    """The content-addressed id of "does this span entail this value for this field?".

    Key-sorted canonical JSON for the value, NUL-separated from the field and the quote so
    ``field="a", quote="bc"`` and ``field="ab", quote="c"`` stay two questions.
    """

    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    payload = "\x00".join((field_key, canonical, quote))
    digest = hashlib.sha256(payload.encode()).hexdigest()
    return ClaimId(uuid5(NAMESPACE_URL, f"{ENTAILMENT_JUDGMENT_NAMESPACE}:{digest}"))


def faithfulness_lookup_plan(claim: Claim) -> FaithfulnessLookupPlan:
    """Map a real claim ``A`` to its ordered faithfulness-verdict subjects.

    The source marker is authoritative. Merely having an evidence span never opts an ordinary claim
    into Q lookup. Conversely, a marked claim without a non-empty span is internally inconsistent:
    silently falling back to A could turn a missing attribution into a false verdict, so callers
    receive a typed, bounded identity error and may isolate that claim.
    """

    if claim.source_key != SOURCE_CLIENT_INTERVIEW_JUDGED:
        return FaithfulnessLookupPlan(actual_claim_id=claim.id, subject_ids=(claim.id,))
    if not claim.evidence_span:
        raise FaithfulnessSubjectIdentityError(claim.id)
    question_id = entailment_judgment_id(
        field_key=claim.field_key,
        value=claim.value_json,
        quote=claim.evidence_span,
    )
    return FaithfulnessLookupPlan(
        actual_claim_id=claim.id,
        subject_ids=(question_id, claim.id),
    )
