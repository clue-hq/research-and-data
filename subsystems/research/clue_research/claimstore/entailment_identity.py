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
* M12 provenance / the review projector will need the same recompute to report a judged claim as
  judged.

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
from uuid import NAMESPACE_URL, uuid5

from pydantic import JsonValue

from clue_core import ClaimId

__all__ = ["ENTAILMENT_JUDGMENT_NAMESPACE", "entailment_judgment_id"]

#: The uuid5 name prefix for an entailment *question*. Distinct from the interview's claim prefix
#: (``stage0-interview-claim:``) so a question id can never collide with a claim id.
ENTAILMENT_JUDGMENT_NAMESPACE = "stage0-interview-entailment"


def entailment_judgment_id(*, field_key: str, value: JsonValue, quote: str) -> ClaimId:
    """The content-addressed id of "does this span entail this value for this field?".

    Key-sorted canonical JSON for the value, NUL-separated from the field and the quote so
    ``field="a", quote="bc"`` and ``field="ab", quote="c"`` stay two questions.
    """

    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    payload = "\x00".join((field_key, canonical, quote))
    digest = hashlib.sha256(payload.encode()).hexdigest()
    return ClaimId(uuid5(NAMESPACE_URL, f"{ENTAILMENT_JUDGMENT_NAMESPACE}:{digest}"))
