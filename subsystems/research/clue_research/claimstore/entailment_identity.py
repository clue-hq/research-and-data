"""The identity of one *entailment question* — a scoped content address.

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
* **Tenant-private questions also include the workspace.** ``client.*`` field meaning is local to
  the workspace, so equal field/value/span bytes in two workspaces are not the same semantic
  question and must never share a cached verdict. Within one workspace, two claims with the same
  field, value and span still share one question; erasing either redacts the shared rationale.
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
    "faithfulness_redaction_subject_ids",
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
    has ``(Q_workspace, A)`` so the scoped pre-write judgment wins and ``A`` remains a legacy
    fallback. The former unscoped Q is deliberately not a fallback: it cannot prove which tenant's
    field semantics were judged. Consumers must key and label their result with
    ``actual_claim_id`` only.
    """

    actual_claim_id: ClaimId
    subject_ids: tuple[ClaimId, ...]


class FaithfulnessSubjectIdentityError(ValueError):
    """A marked judged claim lacks the immutable evidence needed to reconstruct ``Q``."""

    def __init__(self, actual_claim_id: ClaimId, *, reason_code: str) -> None:
        self.actual_claim_id = actual_claim_id
        self.reason_code = reason_code
        super().__init__(
            f"cannot resolve faithfulness subject for claim {actual_claim_id}: {self.reason_code}"
        )


def entailment_judgment_id(
    *, workspace_id: str, field_key: str, value: JsonValue, quote: str
) -> ClaimId:
    """The content-addressed id of "does this span entail this value for this field?".

    Key-sorted canonical JSON for the value, NUL-separated from the field and the quote so
    ``field="a", quote="bc"`` and ``field="ab", quote="c"`` stay two questions. Supplying a
    workspace is mandatory: allowing an omitted scope here would make cross-tenant cache reuse an
    easy regression for any new caller.
    """

    if not workspace_id:
        raise ValueError("workspace-scoped entailment identity requires a non-empty workspace_id")
    return _entailment_judgment_id(("workspace", workspace_id, field_key, _canonical(value), quote))


def _canonical(value: JsonValue) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _entailment_judgment_id(parts: tuple[str, ...]) -> ClaimId:
    payload = "\x00".join(parts)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    return ClaimId(uuid5(NAMESPACE_URL, f"{ENTAILMENT_JUDGMENT_NAMESPACE}:{digest}"))


def _legacy_entailment_judgment_id(*, field_key: str, value: JsonValue, quote: str) -> ClaimId:
    """Reconstruct the pre-workspace Q only for privacy cleanup of already-written rows."""

    return _entailment_judgment_id((field_key, _canonical(value), quote))


def faithfulness_redaction_subject_ids(claim: Claim) -> tuple[ClaimId, ...]:
    """Return every current or legacy verdict subject whose rationale quotes ``claim``.

    Legacy Q is never exposed to attribution readers because it cannot prove tenant-local field
    semantics. It remains reachable here so a DSAR/workspace erasure also removes rationale written
    by the pre-workspace implementation.
    """

    plan = faithfulness_lookup_plan(claim)
    if claim.source_key != SOURCE_CLIENT_INTERVIEW_JUDGED:
        return plan.subject_ids
    assert claim.evidence_span is not None
    legacy = _legacy_entailment_judgment_id(
        field_key=claim.field_key,
        value=claim.value_json,
        quote=claim.evidence_span,
    )
    return tuple(dict.fromkeys((*plan.subject_ids, legacy)))


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
        raise FaithfulnessSubjectIdentityError(
            claim.id, reason_code="judged_interview_evidence_span_missing"
        )
    if not claim.workspace_id:
        raise FaithfulnessSubjectIdentityError(
            claim.id, reason_code="judged_interview_workspace_missing"
        )
    question_id = entailment_judgment_id(
        field_key=claim.field_key,
        value=claim.value_json,
        quote=claim.evidence_span,
        workspace_id=claim.workspace_id,
    )
    return FaithfulnessLookupPlan(
        actual_claim_id=claim.id,
        subject_ids=(question_id, claim.id),
    )
