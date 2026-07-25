"""M11.3 acceptance — the tier-4 synthesis gating policy + the judge-gated merge (hermetic, no DB).

Covers the M11.3 ACs that are satisfiable on the import-isolated M11 branch: the synthesis field
rows exist with the right shape; the account-only personal-data firewall and Pass-B-only guards; the
``resonance.*`` open class; and — the judge-gate AC — that the merge view (M1.2) excludes an
unverified / judge-failed tier-4 synthesis claim from ``current_value`` and promotes a verified one.
The runtime judge pipeline (corroboration → faithfulness → promote) is composed at the api root and
its wiring is the deferred integration step; here we prove the *policy* and the *merge gate*.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from clue_core import (
    Claim,
    EntityType,
    ExtractionMethod,
    FieldDef,
    IdentityBinding,
    PassKind,
    ResearchMode,
    UseClass,
    VerificationStatus,
    account_claim,
    can_be_promoted,
    contact_claim,
    new_entity_id,
    new_run_id,
)
from clue_research.claimstore import CORE_PACK, DEFAULT_MERGE_POLICY, merge_claims
from clue_research.synthesis import (
    PASS_B_MODE,
    SynthesisGateError,
    assert_pass_b_claim,
    guard_account_only,
    guard_pass_b,
    guard_synthesis_resolution,
    is_account_synthesis_field,
    is_governed_synthesis_claim,
    is_synthesis_field,
    synthesis_claim_is_promotable,
)

_PAIN = "account.operational_pain"
_MOVES = "account.strategic_moves"
_CULTURE = "account.resonance.culture"
_NOW = datetime(2026, 6, 25, tzinfo=UTC)


# --- helpers -------------------------------------------------------------------------------------


def _field(
    key: str,
    *,
    tier_plan: tuple[str, ...] = ("exa_deep", "parallel_task"),
    pass_kind: PassKind = PassKind.DEEP,
) -> FieldDef:
    return FieldDef(field_key=key, value_type="str", tier_plan=tier_plan, pass_kind=pass_kind)


def _seed_field(key: str) -> FieldDef:
    """The registered ``FieldDef`` for ``key`` from the in-memory core pack (no DB)."""
    return next(s.field_def for s in CORE_PACK if s.field_def.field_key == key)


def _tier4_claim(
    *,
    key: str = _PAIN,
    status: VerificationStatus = VerificationStatus.VERIFIED,
    value: str = "Acme runs brittle legacy ETL",
    span: str | None = "brittle legacy ETL",
    mode: ResearchMode = ResearchMode.ACCOUNT_PROFILING,
) -> Claim:
    claim = account_claim(
        entity_id=new_entity_id(),
        field_key=key,
        value_json=value,
        source_tier=4,
        extraction_method=ExtractionMethod.LLM_SYNTHESIS,
        confidence=0.9,
        run_id=new_run_id(),
        research_mode=mode,
        source_url="https://acme.com/eng",
        evidence_span=span,
    )
    if status is not VerificationStatus.UNVERIFIED:
        claim = claim.model_copy(update={"verification_status": status})
    return claim


# --- the synthesis field rows exist with the right shape (AC) ------------------------------------


@pytest.mark.parametrize("key", [_PAIN, _MOVES, _CULTURE])
def test_synthesis_field_rows_are_deep_tier4_account_synthesis(key: str) -> None:
    field = _seed_field(key)
    assert field.pass_kind is PassKind.DEEP
    assert field.tier_plan == ("exa_deep", "parallel_task")  # tier-4-only (PF-6 alignment)
    assert field.gate == "deep-pass"  # the base value (spec's committee-gated/tier>=1 simplified)
    assert field.freshness_ttl is not None
    assert is_synthesis_field(field) and is_account_synthesis_field(field)


def test_resonance_is_an_open_class_no_code_change_for_a_new_subfield() -> None:
    # A brand-new resonance sub-field that is NOT enumerated anywhere classifies + qualifies purely
    # by its namespace — the registered-not-enumerated property (Doc C §2).
    new_resonance = _field("account.resonance.attrition")
    assert is_account_synthesis_field(new_resonance)


# --- predicates ----------------------------------------------------------------------------------


def test_is_synthesis_field_keys_on_tier4_provider_in_plan() -> None:
    assert is_synthesis_field(_field(_PAIN, tier_plan=("exa_deep", "parallel_task")))
    assert is_synthesis_field(_field(_MOVES, tier_plan=("parallel_task",)))
    # a deterministic tier-1 field is not synthesis
    assert not is_synthesis_field(_field("account.headcount", tier_plan=("clay", "apollo")))


def test_is_account_synthesis_field_excludes_contact_facet() -> None:
    assert not is_account_synthesis_field(_field("contact.facet.recent_post"))
    assert is_account_synthesis_field(_field(_CULTURE))


# --- account-only personal-data firewall (AC) ----------------------------------------------------


def test_guard_account_only_rejects_a_contact_class_synthesis_field() -> None:
    with pytest.raises(SynthesisGateError, match="personal-data firewall"):
        guard_account_only(_field("contact.facet.recent_post"))


def test_guard_account_only_allows_account_synthesis_and_ignores_non_synthesis() -> None:
    guard_account_only(_field(_PAIN))  # account synthesis — ok
    guard_account_only(_field("account.headcount", tier_plan=("clay",)))  # not synthesis — no-op


# --- Pass-B-only (AC) ----------------------------------------------------------------------------


def test_guard_pass_b_rejects_synthesis_outside_mode_m2() -> None:
    for mode in (ResearchMode.ACCOUNT_DISCOVERY, ResearchMode.CONTACT_PROFILING):
        with pytest.raises(SynthesisGateError, match="Pass-B-only"):
            guard_pass_b(_field(_PAIN), mode)


def test_guard_pass_b_allows_mode_m2() -> None:
    guard_pass_b(_field(_PAIN), PASS_B_MODE)  # ACCOUNT_PROFILING — ok
    assert PASS_B_MODE is ResearchMode.ACCOUNT_PROFILING


def test_guard_pass_b_noop_for_a_non_synthesis_field() -> None:
    # A cheap scoring field may be resolved in any mode — the guard only constrains synthesis.
    scoring = _field("account.headcount", tier_plan=("clay",), pass_kind=PassKind.SCORING)
    guard_pass_b(scoring, ResearchMode.ACCOUNT_DISCOVERY)


def test_guard_synthesis_resolution_combines_firewall_and_pass_b() -> None:
    guard_synthesis_resolution(_field(_PAIN), PASS_B_MODE)  # ok
    with pytest.raises(SynthesisGateError):
        guard_synthesis_resolution(_field("contact.facet.recent_post"), PASS_B_MODE)
    with pytest.raises(SynthesisGateError):
        guard_synthesis_resolution(_field(_PAIN), ResearchMode.ACCOUNT_DISCOVERY)


# --- claim-level invariants ----------------------------------------------------------------------


def test_is_governed_synthesis_claim_is_account_tier4_only() -> None:
    assert is_governed_synthesis_claim(_tier4_claim())
    # a contact tier-4 claim is M10's, not governed by this account firewall
    contact = contact_claim(
        entity_id=new_entity_id(),
        field_key="contact.facet.recent_post",
        value_json="posted about scaling",
        source_tier=4,
        extraction_method=ExtractionMethod.LLM_SYNTHESIS,
        confidence=0.8,
        run_id=new_run_id(),
        research_mode=ResearchMode.CONTACT_PROFILING,
        source_url="https://x.com/p",
        evidence_span="scaling",
        identity_binding=IdentityBinding.STRONG,
        use_class=UseClass.PROFESSIONAL_PUBLIC,
    )
    assert not is_governed_synthesis_claim(contact)


def test_assert_pass_b_claim_fires_only_on_a_mode_regression() -> None:
    assert_pass_b_claim(_tier4_claim(mode=ResearchMode.ACCOUNT_PROFILING))  # ok
    with pytest.raises(SynthesisGateError, match="Pass-B-only"):
        assert_pass_b_claim(_tier4_claim(mode=ResearchMode.ACCOUNT_DISCOVERY))


# --- judge-gate via the merge view (AC) — no value reaches current_value without a judge verdict --


def test_verified_tier4_synthesis_claim_is_promoted() -> None:
    verified = _tier4_claim(status=VerificationStatus.VERIFIED)
    cv = merge_claims([verified], None, DEFAULT_MERGE_POLICY, _NOW)
    assert cv is not None and cv.value_json == "Acme runs brittle legacy ETL"


@pytest.mark.parametrize("status", [VerificationStatus.UNVERIFIED, VerificationStatus.REJECTED])
def test_unverified_or_rejected_tier4_synthesis_is_excluded_from_current_value(
    status: VerificationStatus,
) -> None:
    # The judge-gate: a synthesized claim that has not cleared the faithfulness judge never surfaces
    # as current truth — the field reads empty (None), which is the correct output (substrate §6).
    assert merge_claims([_tier4_claim(status=status)], None, DEFAULT_MERGE_POLICY, _NOW) is None


def test_no_span_tier4_synthesis_claim_cannot_be_promoted() -> None:
    # Re-asserts the M1/M9 invariant at the synthesis-field level: a tier-4 claim with no evidence
    # span is structurally unpromotable, regardless of any verdict.
    assert not can_be_promoted(_tier4_claim(span=None))
    assert can_be_promoted(_tier4_claim(span="brittle legacy ETL"))


def test_promotability_restatement_agrees_with_the_merge_gate() -> None:
    # The restatement (synthesis_claim_is_promotable) must track the authoritative M1.2 merge gate
    # for EVERY verdict — asserted against the real merge here so the two cannot silently drift.
    for status in (
        VerificationStatus.VERIFIED,
        VerificationStatus.UNVERIFIED,
        VerificationStatus.REJECTED,
    ):
        claim = _tier4_claim(status=status)
        promoted_by_merge = merge_claims([claim], None, DEFAULT_MERGE_POLICY, _NOW) is not None
        assert synthesis_claim_is_promotable(claim) == promoted_by_merge, status
    assert _tier4_claim().entity_type is EntityType.ACCOUNT


def test_a_lower_tier_claim_is_not_a_governed_synthesis_claim() -> None:
    # The claim-level firewall read: a tier≤3 claim is not a governed account-synthesis claim.
    assert not is_governed_synthesis_claim(
        account_claim(
            entity_id=new_entity_id(),
            field_key="account.headcount",
            value_json=1000,
            source_tier=1,
            extraction_method=ExtractionMethod.API,
            confidence=0.99,
            run_id=new_run_id(),
            research_mode=ResearchMode.ACCOUNT_PROFILING,
            source_url="https://api.clay.com/acme",
        )
    )
