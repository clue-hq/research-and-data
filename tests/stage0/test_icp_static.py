"""Pure (no-DB) tests for M5.2 — the icp.* feedback field, reuse policy, estimate math, and the
pure proposal⊕edits→selection / diff logic. These run in the default ``make check`` (no database).
"""

from __future__ import annotations

from decimal import Decimal

from clue_core import ExtractionMethod, ReuseScope
from clue_core.field import classify_field_key, is_valid_field_key, resolve_reuse_scope
from clue_research.identity import DEFAULT_REUSE_POLICY, classify_reuse_scope
from clue_research.stage0 import (
    ICP_CONFIRM_DIFF,
    ICP_FEEDBACK_PACK,
    EstimateInputs,
    estimate_campaign,
)
from clue_research.stage0.icp_confirm import _diff, _select
from clue_research.stage0.icp_synthesis import _bounded, _parse_json, _synthesis_messages
from clue_research.stage0.icp_types import (
    CandidateSignal,
    FirmographicDimensions,
    ICPProposal,
    ICPProposalEdits,
    ProposedRubric,
    RubricWeight,
)
from clue_research.stage0.reuse import ICP_REUSE_POLICY


def test_icp_confirm_diff_field_is_wellformed_pack_and_private() -> None:
    (seed,) = ICP_FEEDBACK_PACK
    assert seed.field_def.field_key == ICP_CONFIRM_DIFF
    assert is_valid_field_key(ICP_CONFIRM_DIFF)
    # `icp` is not a canonical namespace → a vertical pack; a <pack>.* field MUST declare its scope.
    assert classify_field_key(ICP_CONFIRM_DIFF).value == "pack"
    assert seed.pack == "icp"
    assert seed.field_def.reuse_scope is ReuseScope.TENANT_PRIVATE
    assert resolve_reuse_scope(seed.field_def) is ReuseScope.TENANT_PRIVATE


def test_icp_reuse_policy_makes_icp_namespace_private() -> None:
    # ICP confirm-diff claims are client-tuned → tenant-private under the stage0 icp policy, whereas
    # the M2 default would mis-classify them public.
    assert (
        classify_reuse_scope(ICP_CONFIRM_DIFF, ExtractionMethod.HUMAN, 1, policy=ICP_REUSE_POLICY)
        is ReuseScope.TENANT_PRIVATE
    )
    assert (
        classify_reuse_scope(
            ICP_CONFIRM_DIFF, ExtractionMethod.HUMAN, 1, policy=DEFAULT_REUSE_POLICY
        )
        is ReuseScope.PUBLIC_FOOTPRINT
    )


def test_estimate_default_priors() -> None:
    est = estimate_campaign()
    assert est.discovered_count == 500
    assert est.projected_deep_count == 100  # round(500 * 0.2)
    assert est.estimated_cost_cents == Decimal("53000")  # 500*(5+1) + 100*500
    assert est.cost_per_account_cents == Decimal("106")  # 53000 / 500
    assert est.confidence == 0.3  # a pre-discovery prior, flagged low


def test_estimate_custom_inputs_and_zero_guard() -> None:
    est = estimate_campaign(
        EstimateInputs(
            projected_account_count=100,
            deep_fraction=0.5,
            discovery_cents_per_account=Decimal("2"),
            scoring_cents_per_account=Decimal("1"),
            deep_cents_per_account=Decimal("100"),
        )
    )
    assert est.projected_deep_count == 50
    assert est.estimated_cost_cents == Decimal("5300")  # 100*(2+1) + 50*100

    zero = estimate_campaign(EstimateInputs(projected_account_count=0))
    assert zero.estimated_cost_cents == Decimal(0)
    assert zero.cost_per_account_cents == Decimal(0)  # no division by zero


def test_parse_json_tolerates_fences_and_rejects_garbage() -> None:
    assert _parse_json('{"icps": []}') == {"icps": []}
    assert _parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _parse_json("not json") is None


def test_bounded_drops_offset_keys_and_dedupes() -> None:
    allowed = frozenset({"a", "b"})
    assert _bounded(("a", "x", "b", "a"), allowed) == ("a", "b")


def _proposal() -> ICPProposal:
    return ICPProposal(
        icp_key="primary",
        firmographic=FirmographicDimensions(
            field_keys=("core.employee_count", "core.primary_domain")
        ),
        candidate_signals=(
            CandidateSignal(
                signal_class="growth",
                proxy_field_keys=("account.recent_funding",),
                narrative_field_keys=("account.hiring_velocity_eng",),
            ),
        ),
        rubric=ProposedRubric(
            weights=(
                RubricWeight(field_key="core.employee_count", dimension="fit"),
                RubricWeight(field_key="core.primary_domain", dimension="fit"),
                RubricWeight(field_key="account.recent_funding", dimension="intent"),
            ),
            fit_threshold=0.5,
            intent_threshold=0.3,
        ),
    )


def test_select_and_diff_round_trip_edits() -> None:
    proposal = _proposal()
    edits = ICPProposalEdits(
        removed_signal_classes=("growth",),
        removed_field_keys=("core.primary_domain",),
        added_field_keys=("core.work_email",),
    )
    base = _select(proposal, ICPProposalEdits())
    confirmed = _select(proposal, edits)

    assert "core.work_email" in confirmed.field_keys
    assert "core.primary_domain" not in confirmed.field_keys
    # the growth signal's UNIQUE narrative field leaves with it; the proxy stays (rubric uses it)
    assert "account.hiring_velocity_eng" not in confirmed.field_keys
    assert "account.recent_funding" in confirmed.field_keys
    assert confirmed.signal_classes == ()

    diff = _diff(base, confirmed, notes=None)
    assert not diff.is_empty
    assert diff.added_field_keys == ("core.work_email",)
    assert "core.primary_domain" in diff.removed_field_keys
    assert "account.hiring_velocity_eng" in diff.removed_field_keys
    assert diff.removed_signal_classes == ("growth",)
    # core.primary_domain was a fit rubric entry → its removal shows as a reweight-to-None
    assert any(c.field_key == "core.primary_domain" and c.after is None for c in diff.reweighted)


def test_diff_is_empty_when_confirmed_as_proposed() -> None:
    proposal = _proposal()
    base = _select(proposal, ICPProposalEdits())
    confirmed = _select(proposal, ICPProposalEdits())
    assert _diff(base, confirmed, notes=None).is_empty


def test_the_synthesis_prompt_asks_for_both_field_scopes() -> None:
    """FI-2 P3: the species must-declare guard is only *reachable* if the model is told to declare
    one — a prompt that asks for ``reuse_scope`` alone would make every vertical concept the
    synthesizer drafts auto-reject at payload validation."""

    messages = _synthesis_messages(
        kb_claims={},
        project_statements=(),
        scoring_keys=frozenset(),
        deep_keys=frozenset(),
        pack_field_keys={},
    )
    system = messages[0].content
    assert '"reuse_scope"' in system
    assert '"research_scope"' in system
    assert "project_neutral" in system
    assert "project_relative" in system
