"""Per-handoff **verification health** (M12.3 — the trust posture that travels with the output).

Doc C §6 requires the handoff to carry its own verification-health signal so the content-layer
consumer (and, via M13.4, the client) can *see* how trustworthy a served object is — the early
warning that a model/resolver swap regressed quality. The two headline numbers (substrate §6 / Doc
C §6) are:

* **tier-4 judge pass rate** — of the synthesized (tier-4) value-narrative lines, the share carrying
  a recorded faithfulness verdict. Every line in a served handoff is already ``VERIFIED`` (the
  assembler excludes ``rejected``/``unverified`` narratives), so a citation present ⟹ the line was
  judged faithful; a *served* line WITHOUT a citation is the anomaly this rate surfaces.
* **strong-binding share** — of the committee's identity-bound (contact) claims, the share at
  ``STRONG`` identity-binding. This is computed over the **unfiltered** committee the seam returns
  (NOT the outreach-eligible set the handoff carries) so the denominator is honest: the handoff's
  committee has already had weak-binding facets dropped, so a share computed over it would read
  ~100%
  by construction and tell the consumer nothing.

This is a **pure** function (no DB, no LLM) computed once at assembly time — where the unfiltered
committee + the narrative citations are both in hand — and stamped onto the M12-owned
:class:`~clue_research.narrative.handoff.AssembledHandoff` wrapper (never the frozen ``core``
contract). It is deterministic over the same inputs, so it keeps a re-assembly byte-stable (M12.2
AC5).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from clue_research.core import IdentityBinding, ProfileClaimView, UnitInterval, ValueNarrativeItem
from clue_research.narrative.handoff_seams import HandoffCommitteeMember
from clue_research.narrative.support import FaithfulnessCitation


class VerificationHealth(BaseModel):
    """The trust posture of one served handoff (Doc C §6) — the two headline shares plus the raw
    counts they are derived from (so a consumer can recompute / aggregate without losing the
    numerator and denominator). The ``*_share`` / ``*_rate`` are ``None`` when their denominator is
    zero (an account with no narrative, or a committee with no identity-bound claim) — an absent
    rate
    is honest where a ``0.0`` would be a false negative."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value_narrative_total: int = 0
    value_narrative_judged_faithful: int = 0
    tier4_judge_pass_rate: UnitInterval | None = None
    committee_contact_claims_total: int = 0
    committee_strong_binding: int = 0
    strong_binding_share: UnitInterval | None = None


def compute_verification_health(
    *,
    narrative: Sequence[ValueNarrativeItem],
    citations: Mapping[str, FaithfulnessCitation],
    committee_members: Sequence[HandoffCommitteeMember],
) -> VerificationHealth:
    """Summarise the trust posture of an assembled handoff (Doc C §6).

    ``narrative`` are the served (verified-only) value-narrative lines; ``citations`` is the
    ``str(claim_id) -> FaithfulnessCitation`` map the assembler already resolved;
    ``committee_members``
    are the **unfiltered** :class:`HandoffCommitteeMember`\\s from the seam (so the strong-binding
    denominator includes weak-binding claims dropped from the outreach-eligible set)."""
    n_narrative = len(narrative)
    judged = sum(1 for item in narrative if str(item.claim_id) in citations)
    pass_rate: UnitInterval | None = (judged / n_narrative) if n_narrative else None

    contact_claims: list[ProfileClaimView] = [
        pv
        for hm in committee_members
        for pv in hm.member.profile_claims
        if pv.identity_binding is not None
    ]
    n_contact = len(contact_claims)
    strong = sum(1 for pv in contact_claims if pv.identity_binding is IdentityBinding.STRONG)
    strong_share: UnitInterval | None = (strong / n_contact) if n_contact else None

    return VerificationHealth(
        value_narrative_total=n_narrative,
        value_narrative_judged_faithful=judged,
        tier4_judge_pass_rate=pass_rate,
        committee_contact_claims_total=n_contact,
        committee_strong_binding=strong,
        strong_binding_share=strong_share,
    )
