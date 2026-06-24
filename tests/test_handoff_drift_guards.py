"""Drift guards for the M12.2 handoff assembler's mirrored constants (no DB).

``narrative`` may not import its sibling workers (``discovery_scoring`` / ``profiling``) nor apply
``core.is_outreach_promotable`` to a ``ProfileClaimView`` (it is not a ``Claim``), so the assembler
re-declares three things that *originate* elsewhere: the reserved score field-keys, the account-axis
field-class set, and the facet-eligibility predicate. These tests live at the top of ``tests/``
(which is under no import contract) so they CAN cross-import the sources of truth and fail loudly
the moment a rename / edit makes a copy drift from its origin — closing the audit's "silent drift"
gap.
"""

from __future__ import annotations

import pytest

from clue_research.core import (
    ExtractionMethod,
    IdentityBinding,
    ProfileClaimView,
    ResearchMode,
    UseClass,
    UseDecision,
    UseReason,
    contact_claim,
    is_outreach_promotable,
    new_entity_id,
    new_run_id,
)
from clue_research.discovery_scoring.scoring.engine import (
    FIT_FIELD as SCORING_FIT_FIELD,
)
from clue_research.discovery_scoring.scoring.engine import (
    INTENT_FIELD as SCORING_INTENT_FIELD,
)
from clue_research.narrative.handoff import (
    _ACCOUNT_AXIS_CLASSES,
    FIT_FIELD,
    INTENT_FIELD,
    _facet_outreach_eligible,
)
from clue_research.profiling.account import _ACCOUNT_AXIS_CLASSES as PROFILING_AXIS_CLASSES


def test_score_field_keys_match_the_scoring_engine() -> None:
    """The assembler's re-declared score keys must equal the M6.3 writer's (a rename there would
    otherwise make M12.2 silently read no score)."""
    assert FIT_FIELD == SCORING_FIT_FIELD
    assert INTENT_FIELD == SCORING_INTENT_FIELD


def test_account_axis_classes_match_profiling() -> None:
    """The assembler's account-profile field-class set must equal the profiler's (a class added to
    one but not the other would silently include/exclude a whole field-class from Output 2)."""
    assert _ACCOUNT_AXIS_CLASSES == PROFILING_AXIS_CLASSES


@pytest.mark.parametrize("binding", [IdentityBinding.STRONG, IdentityBinding.WEAK])
@pytest.mark.parametrize("usable", [True, False])
def test_facet_eligibility_mirrors_core_is_outreach_promotable(
    binding: IdentityBinding, usable: bool
) -> None:
    """``_facet_outreach_eligible`` (operates on a view) must agree with the canonical
    ``core.is_outreach_promotable`` (operates on a Claim + decision) across the full
    {strong/weak} × {usable/not} matrix — so a change to the use-axis predicate can't drift."""
    claim = contact_claim(
        entity_id=new_entity_id(),
        field_key="contact.facet.recent_post",
        value_json="ex-Stripe",
        source_tier=4,
        extraction_method=ExtractionMethod.LLM_SYNTHESIS,
        confidence=0.9,
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        identity_binding=binding,
        use_class=UseClass.PROFESSIONAL_PUBLIC,
        source_url="https://src.local/c",
        evidence_span="a span",
    )
    decision = UseDecision(
        claim_id=claim.id,
        usable_for_outreach=usable,
        reason=UseReason.ALLOWED if usable else UseReason.USE_CLASS_DISALLOWED_FOR_REGIME,
        policy_version=1,
    )
    view = ProfileClaimView(
        claim_id=claim.id,
        value_json=claim.value_json,
        source_tier=claim.source_tier,
        identity_binding=binding,
        use_class=UseClass.PROFESSIONAL_PUBLIC,
    )
    assert _facet_outreach_eligible(view, decision.usable_for_outreach) is is_outreach_promotable(
        claim, decision
    )
