"""Read-only, human-reviewable projection of an account-research directive draft."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from clue_core import (
    EntityId,
    ResearchCommitteePlan,
    ResearchDirective,
    ResearchDirectiveAccountOverride,
    ResearchEffortPolicy,
    ResearchPrivacyPolicy,
    ResearchQuestion,
    ResearchSourcePolicy,
)


class ResearchDirectiveAccountPreview(BaseModel):
    """The effective differences a human is approving for one overridden account."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: str
    override_ref: str
    effective_field_keys: tuple[str, ...]
    effective_hypotheses: tuple[ResearchQuestion, ...]
    effective_source_policy: ResearchSourcePolicy
    effective_committee_plan: ResearchCommitteePlan
    effective_effort_policy: ResearchEffortPolicy
    added_exclusions: tuple[str, ...]


class ResearchDirectivePreview(BaseModel):
    """Bounded complete review payload; questions remain explicitly labeled as hypotheses."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    directive_ref: str
    version: int
    status: str
    account_ids: tuple[str, ...]
    sealed_selection_ref: str | None
    field_keys: tuple[str, ...]
    hypotheses: tuple[ResearchQuestion, ...]
    source_policy: ResearchSourcePolicy
    committee_plan: ResearchCommitteePlan
    privacy_policy: ResearchPrivacyPolicy
    effort_policy: ResearchEffortPolicy
    exclusions: tuple[str, ...]
    account_overrides: tuple[ResearchDirectiveAccountPreview, ...]
    memory_outcome: str
    future_thread_memory_persisted: bool
    unresolved_prerequisites: tuple[str, ...]
    rendered_summary: str

    @property
    def budget_cap_cents(self) -> Decimal:
        return self.effort_policy.budget_cap_cents


def _account_preview(
    directive: ResearchDirective,
    override: ResearchDirectiveAccountOverride,
) -> ResearchDirectiveAccountPreview:
    body = directive.body
    changes = override.body
    excluded_fields = set(changes.exclude_field_keys)
    fields = tuple(
        dict.fromkeys(
            field
            for field in (*body.field_keys, *changes.include_field_keys)
            if field not in excluded_fields
        )
    )
    excluded_questions = set(changes.exclude_question_ids)
    questions = tuple(
        item
        for item in (*body.questions, *changes.additional_questions)
        if item.question_id not in excluded_questions
    )
    return ResearchDirectiveAccountPreview(
        account_id=str(override.account_id),
        override_ref=override.override_ref,
        effective_field_keys=fields,
        effective_hypotheses=questions,
        effective_source_policy=changes.source_policy or body.source_policy,
        effective_committee_plan=changes.committee_plan or body.committee_plan,
        effective_effort_policy=changes.effort_policy or body.effort_policy,
        added_exclusions=changes.exclusions,
    )


def project_research_directive_preview(
    directive: ResearchDirective,
    overrides: tuple[ResearchDirectiveAccountOverride, ...] = (),
    *,
    resolved_account_ids: tuple[EntityId, ...] | None = None,
    memory_outcome: str = "unknown",
) -> ResearchDirectivePreview:
    body = directive.body
    account_ids = resolved_account_ids or body.account_scope.explicit_account_ids
    unresolved: list[str] = []
    if not body.privacy_policy.account_research_allowed:
        unresolved.append("account_research_not_authorized")
    if not body.privacy_policy.committee_discovery_allowed:
        unresolved.append("committee_discovery_not_authorized")
    memory_persisted = bool(directive.memory_refs)
    if not memory_persisted:
        unresolved.append("project_memory_disabled")
    rendered = (
        f"Research directive {directive.directive_ref} covers {len(account_ids)} account(s), "
        f"{len(body.field_keys)} registered fields and {len(body.questions)} user-guided "
        f"hypotheses. It may enumerate up to {body.committee_plan.candidate_cap} committee "
        f"candidates across {', '.join(body.committee_plan.functions) or 'no named functions'}, "
        f"with depth {body.effort_policy.max_depth}, fan-out {body.effort_policy.max_fanout}, "
        f"and a {body.effort_policy.budget_cap_cents}-cent cap. "
        "Contact profiling is "
        f"{'allowed' if body.privacy_policy.contact_profiling_allowed else 'excluded'}; "
        "contact reveals are "
        f"{'allowed' if body.privacy_policy.contact_reveals_allowed else 'excluded'}."
    )
    return ResearchDirectivePreview(
        directive_ref=directive.directive_ref,
        version=directive.version,
        status=directive.status.value,
        account_ids=tuple(str(item) for item in account_ids),
        sealed_selection_ref=body.account_scope.sealed_selection_ref,
        field_keys=body.field_keys,
        hypotheses=body.questions,
        source_policy=body.source_policy,
        committee_plan=body.committee_plan,
        privacy_policy=body.privacy_policy,
        effort_policy=body.effort_policy,
        exclusions=body.exclusions,
        account_overrides=tuple(_account_preview(directive, item) for item in overrides),
        memory_outcome=memory_outcome,
        future_thread_memory_persisted=memory_persisted,
        unresolved_prerequisites=tuple(unresolved),
        rendered_summary=rendered,
    )


__all__ = [
    "ResearchDirectiveAccountPreview",
    "ResearchDirectivePreview",
    "project_research_directive_preview",
]
