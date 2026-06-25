"""PF-6 guard: the tier-4 *synthesis* fields in the core pack route to the **registered** tier-4
source_keys (``exa_deep`` / ``parallel_task``), so M11's bound resolvers actually fire for them.

Regression: phase-3 pre-flight bug — ``account.operational_pain`` / ``account.strategic_moves``
carried ``tier_plan=("exa", "parallel")``, but only ``"exa_deep"`` / ``"parallel_task"`` are
registered source_keys (``provider`` is a *separate* column = ``exa`` / ``parallel``), so the
waterfall hit ``NoResolverBoundError`` (→ ``stop_reason=no_resolver`` → empty) and M11's synthesis
never ran. (Non-synthesis fields may legitimately name not-yet-built sources; this guard covers only
the tier-4 synthesis fields M11 owns.)
"""

from __future__ import annotations

from clue_research.claimstore.packs import CORE_PACK
from clue_research.sources.seeds import SEED_MANIFESTS

# The tier-4 synthesis fields M11 fills (account.* / account.resonance.*). contact.facet is
# M8.5/M10-governed and intentionally excluded from this account-synthesis guard.
_TIER4_SYNTHESIS_FIELDS = {
    "account.operational_pain",
    "account.strategic_moves",
    "account.resonance.culture",
}
_TIER4_SYNTHESIS_KEYS = {"exa_deep", "parallel_task"}


def _tier_plan(field_key: str) -> tuple[str, ...]:
    for seed in CORE_PACK:
        if seed.field_def.field_key == field_key:
            return seed.field_def.tier_plan
    raise AssertionError(f"{field_key} is not registered in CORE_PACK")


def test_synthesis_fields_route_to_registered_tier4_resolvers() -> None:
    registered = {entry.manifest.source_key for entry in SEED_MANIFESTS}
    for field_key in _TIER4_SYNTHESIS_FIELDS:
        plan = _tier_plan(field_key)
        unregistered = set(plan) - registered
        assert not unregistered, (
            f"{field_key} tier_plan {plan} names unregistered source_key(s) {unregistered}: "
            "the waterfall would NoResolverBound → empty and M11 would never fire"
        )
        assert _TIER4_SYNTHESIS_KEYS & set(plan), (
            f"{field_key} tier_plan {plan} has no registered tier-4 synthesis source "
            f"(expected one of {_TIER4_SYNTHESIS_KEYS})"
        )
