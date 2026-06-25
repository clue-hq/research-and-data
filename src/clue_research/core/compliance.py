"""The appropriateness / use gate — the M10 contract other milestones call (phase-3 pre-flight).

The *second* of the two distinct gates (Doc D §3/§5). The accuracy / identity-binding gate
(``core.verification``) answers "is it true, and is it *this* person?"; this gate answers the
orthogonal "*may we use it* for outreach?" — ``use_class × jurisdiction × client_policy``. They live
in **separate modules on purpose** (Doc D §5: the two must be separately measurable, with separate
spans) — the same reason ``core.verification``'s own docstring says the use gate is "deliberately
not here". The *seam* lives in ``core`` (like every cross-package gate protocol — ``Resolver``,
``FaithfulnessJudge``, …) because M12 (``narrative``) and others must call it **without** importing
the ``compliance`` package (the import-linter independence contract); M10 supplies the
**implementation**, injected at the ``api`` composition root.

Ordering (Doc D §7): the use gate runs **after** identity-binding (M9.4) and the faithfulness judge
(M9.3). A data-subject objection (GDPR Art. 21) and retention age-out (``FreshnessState.EXPIRED``)
are **not** gate reasons here — they are handled at the merge/eligibility substrate (M10.5
tombstones the affected claims before the merge read), so ``evaluate(claim)`` stays a simple
per-claim appropriateness check and never needs widening.

Beat-0-style: this module ships only the seam (the protocol + the frozen value type + the composite
predicate). M10 builds the impl, the ``use_decision`` side table, and the jurisdiction/use-class
policy on its branch. Architecture sources: Doc D §2/§3/§5/§7,
docs/specs/M10-compliance-and-personal-data.md.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from clue_research.core.claim import Claim
from clue_research.core.enums import IdentityBinding, UseReason
from clue_research.core.primitives import ClaimId


class UseDecision(BaseModel):
    """The appropriateness/use gate's verdict on one personal claim (M10.3). ``usable_for_outreach``
    is the single bit downstream reads; ``reason`` is the typed justification (``UseReason``);
    ``policy_version`` pins the ``client_policy × jurisdiction`` config row that decided it
    (versioned config, mirroring ``judge_policy`` / ``pre_spend_policy``).

    Stored in M10's ``use_decision`` **side table** keyed on ``claim_id`` — a verdict settable
    *after* the claim is inserted, never a born ``claim`` column (so no ``claim`` ALTER and no touch
    of the append-only immutable guard; phase-3 pre-flight PF-2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: ClaimId
    usable_for_outreach: bool
    reason: UseReason
    policy_version: int


@runtime_checkable
class UseGate(Protocol):
    """The appropriateness/use gate (M10.3) — the use-axis sibling of the accuracy gates in
    ``core.verification``. Classifies whether a personal claim may drive outreach under
    ``use_class × jurisdiction × client_policy`` and emits its own ``compliance.use_gate`` span (Doc
    D §5 — separately measurable from the faithfulness judge). Per-claim **by design**: objection
    (Art. 21) and retention age-out are excluded at the merge substrate, so this signature never
    needs a ``contact_context``. M10 supplies the impl; injected at ``api``."""

    async def evaluate(self, claim: Claim) -> UseDecision: ...


def is_outreach_promotable(claim: Claim, decision: UseDecision) -> bool:
    """Whether a contact claim may drive outreach — the **use-axis** composite, distinct from the
    **accuracy-axis** :func:`~clue_research.core.claim.can_be_promoted` (and the
    ``Claim.is_promotable`` convenience that wraps it). The two predicates are deliberately named
    apart so a caller cannot bind the wrong one.

    Both axes must hold for a committee hook to be usable in 1:1 outreach (Doc D §3/§5):

    * accuracy / identity (``can_be_promoted`` / M9): a strong identity-binding, an evidence span;
    * appropriateness (this fn / M10): the use gate cleared ``usable_for_outreach``.

    Returns ``True`` only when the claim is **strongly** bound *and* the use gate cleared it. It
    does **not** re-check retention or objection — those are excluded at the merge substrate (M10.5
    tombstone-before-read), so a claim reaching this predicate has already survived merge
    eligibility.
    M12's handoff assembler calls this (never ``Claim.is_promotable``, which is accuracy-only) when
    deciding which committee hooks may carry a value-narrative angle.

    The ``decision`` is passed in (not read off the claim) because the use verdict lives in M10's
    ``use_decision`` side table, not on the ``claim`` row (PF-2)."""
    return claim.identity_binding is IdentityBinding.STRONG and decision.usable_for_outreach
