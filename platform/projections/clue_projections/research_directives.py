"""Read-only, human-reviewable projection of an account-research directive draft."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from clue_core import ResearchDirective, ResearchDirectiveAccountOverride


class ResearchDirectivePreview(BaseModel):
    """Bounded review payload; questions remain explicitly labeled as hypotheses."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    directive_ref: str
    version: int
    status: str
    account_ids: tuple[str, ...]
    sealed_selection_ref: str | None
    field_keys: tuple[str, ...]
    hypotheses: tuple[str, ...]
    allowed_source_keys: tuple[str, ...]
    preferred_source_keys: tuple[str, ...]
    excluded_source_keys: tuple[str, ...]
    committee_functions: tuple[str, ...]
    committee_levels: tuple[str, ...]
    committee_teams: tuple[str, ...]
    committee_personas: tuple[str, ...]
    exclusions: tuple[str, ...]
    tier: str
    max_depth: int
    max_fanout: int
    budget_cap_cents: Decimal
    account_override_refs: tuple[str, ...]
    unresolved_prerequisites: tuple[str, ...]

    def render(self) -> str:
        accounts = str(len(self.account_ids)) if self.account_ids else self.sealed_selection_ref
        return (
            f"Research directive {self.directive_ref} covers {accounts} account selection; "
            f"{len(self.field_keys)} registered fields and {len(self.hypotheses)} user-guided "
            f"hypotheses; committee functions {', '.join(self.committee_functions) or 'none'}; "
            f"tier {self.tier}, depth {self.max_depth}, fan-out {self.max_fanout}, "
            f"budget cap {self.budget_cap_cents} cents."
        )


def project_research_directive_preview(
    directive: ResearchDirective,
    overrides: tuple[ResearchDirectiveAccountOverride, ...] = (),
) -> ResearchDirectivePreview:
    body = directive.body
    unresolved: list[str] = []
    if not body.privacy_policy.account_research_allowed:
        unresolved.append("account_research_not_authorized")
    if not body.privacy_policy.committee_discovery_allowed:
        unresolved.append("committee_discovery_not_authorized")
    return ResearchDirectivePreview(
        directive_ref=directive.directive_ref,
        version=directive.version,
        status=directive.status.value,
        account_ids=tuple(str(item) for item in body.account_scope.explicit_account_ids),
        sealed_selection_ref=body.account_scope.sealed_selection_ref,
        field_keys=body.field_keys,
        hypotheses=tuple(question.text for question in body.questions),
        allowed_source_keys=body.source_policy.allowed_source_keys,
        preferred_source_keys=body.source_policy.preferred_source_keys,
        excluded_source_keys=body.source_policy.excluded_source_keys,
        committee_functions=body.committee_plan.functions,
        committee_levels=body.committee_plan.levels,
        committee_teams=body.committee_plan.teams,
        committee_personas=body.committee_plan.personas,
        exclusions=body.exclusions,
        tier=body.effort_policy.tier,
        max_depth=body.effort_policy.max_depth,
        max_fanout=body.effort_policy.max_fanout,
        budget_cap_cents=body.effort_policy.budget_cap_cents,
        account_override_refs=tuple(item.override_ref for item in overrides),
        unresolved_prerequisites=tuple(unresolved),
    )


__all__ = ["ResearchDirectivePreview", "project_research_directive_preview"]
