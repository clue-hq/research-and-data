"""Reference-only output schemas for API-root tool implementations."""

from __future__ import annotations

from clue_toolbelt import ToolOutput


class ReverseProfileOutput(ToolOutput):
    client_entity_id: str
    client_kb_version: int
    fields_resolved: int


class SynthesizeIcpsOutput(ToolOutput):
    proposal_count: int
    client_kb_version: int


class ConfirmIcpOutput(ToolOutput):
    icp_key: str
    icp_version: int


class ImportAccountsOutput(ToolOutput):
    import_batch_id: str
    resolved: int
    needs_review: int
    unresolved: int


class DiscoverAccountsOutput(ToolOutput):
    status: str
    discovery_run_id: str | None
    admitted: int
    candidates: int | None
    needs_review: int | None
    rejected: int | None
    stopping_reason: str | None


class PhaseAccountsOutput(ToolOutput):
    status: str
    accounts_processed: int


class TierCheckpointOutput(ToolOutput):
    project_run_id: str
    phase: str


class DeepAccountOutput(ToolOutput):
    account_entity_id: str
    run_id: str
    status: str
    claim_refs: list[str]


class CommitteeOutput(ToolOutput):
    account_entity_id: str
    members: int
    admitted: int


class ContactProfileOutput(ToolOutput):
    contact_entity_id: str
    fields_filled: int
    profile_claims: int


class HandoffOutput(ToolOutput):
    project_run_id: str
    handoffs: int
    narrative_emit_skipped: bool


class ProjectEstimateOutput(ToolOutput):
    discovered_count: int
    projected_deep_count: int
    estimated_cost_cents: str
    cost_per_account_cents: str


class ProjectRunStartOutput(ToolOutput):
    project_run_id: str


class ProjectRunStatusOutput(ToolOutput):
    project_run_id: str
    status: str


class ProjectRunResumeOutput(ProjectRunStatusOutput):
    enqueued: bool


class ProjectRunBudgetOutput(ToolOutput):
    project_run_id: str
    budget_cap_cents: str


class ResearchAccountGapsOutput(ToolOutput):
    project_run_id: str
    account_entity_id: str
    round: int
    coverage_decision_ids: list[str]
    attempt_ids: list[str]
    claim_refs: list[str]
    remaining_gap_count: int
    terminal: bool


class EvaluatorAdviceOutput(ToolOutput):
    evaluator_advice_id: str
    valid: bool
    proposal_kind: str
    sufficient_for_goal: bool | None
    recommendations: list[str]
    warning_codes: list[str]


class ResearchAccountGapsV2Output(ResearchAccountGapsOutput):
    evaluator_advice: EvaluatorAdviceOutput
    stop_proposal: bool


class FieldProposalOutput(ToolOutput):
    field_proposal_id: str
    field_key: str
    status: str


class FieldProposalDecisionOutput(ToolOutput):
    field_proposal_id: str
    status: str
    applied_field_key: str | None


class SourceProposalOutput(ToolOutput):
    source_proposal_id: str
    source_key: str
    status: str


class SourceProposalDecisionOutput(ToolOutput):
    source_proposal_id: str
    status: str
    applied_source_key: str | None


class IngestionSubmitOutput(ToolOutput):
    ingestion_job_id: str
    artifact_key: str
    status: str


class IngestionRetryOutput(ToolOutput):
    ingestion_job_id: str
    status: str
    retry_count: int


class OnboardingInputOutput(ToolOutput):
    onboarding_input_id: str
    artifact_key: str
    kind: str


class ReconOutput(ToolOutput):
    recon_run_id: str
    client_entity_id: str | None
    fast_client_kb_version: int | None
    fast_status: str
    background_status: str
    background_run_id: str


class InterviewAnswerOutput(ToolOutput):
    statement_ids: list[str]
    claim_refs: list[str]
    memory_refs: list[str]
    project_state_refs: list[str]
    proposal_refs: list[str]
    unmapped_statement_ids: list[str]


class ProjectProductOutput(ToolOutput):
    project_id: str
    product_id: str


class Stage0ReadinessOutput(ToolOutput):
    readiness_decision_id: str
    gate: str
    verdict: str
    spec_version: int
    product_context_version_id: str | None


class Stage0OverrideOutput(ToolOutput):
    readiness_override_id: str
    readiness_decision_id: str


class ConfirmedProjectRunOutput(ToolOutput):
    project_run_id: str
    phase: str
    product_context_version_id: str
    readiness_decision_id: str


class RecipeExecutionStartOutput(ToolOutput):
    execution_id: str
    status: str
    enqueued: bool


class RecipeExecutionStatusOutput(ToolOutput):
    execution_id: str
    status: str
    enqueued: bool


class RecipeGateDecisionOutput(ToolOutput):
    execution_id: str
    node_key: str
    decision: str
    enqueued: bool


class RecipeProposalOutput(ToolOutput):
    recipe_revision_id: str
    recipe_key: str
    version: int
    status: str


class ProjectPhaseAdvanceOutput(ToolOutput):
    project_run_id: str
    phase: str
    status: str


class RunControlOutput(ToolOutput):
    execution_id: str
    control_kind: str
    subject_ref: str
    action: str
    active: bool
    reoffered: bool = False


__all__ = [
    "CommitteeOutput",
    "ConfirmedProjectRunOutput",
    "ConfirmIcpOutput",
    "ContactProfileOutput",
    "DeepAccountOutput",
    "DiscoverAccountsOutput",
    "FieldProposalDecisionOutput",
    "FieldProposalOutput",
    "HandoffOutput",
    "ImportAccountsOutput",
    "IngestionRetryOutput",
    "IngestionSubmitOutput",
    "InterviewAnswerOutput",
    "OnboardingInputOutput",
    "PhaseAccountsOutput",
    "ProjectEstimateOutput",
    "ProjectProductOutput",
    "ProjectRunBudgetOutput",
    "ProjectRunResumeOutput",
    "ProjectRunStartOutput",
    "ProjectRunStatusOutput",
    "RunControlOutput",
    "ReconOutput",
    "RecipeExecutionStartOutput",
    "RecipeExecutionStatusOutput",
    "RecipeGateDecisionOutput",
    "RecipeProposalOutput",
    "ResearchAccountGapsOutput",
    "ReverseProfileOutput",
    "SourceProposalDecisionOutput",
    "SourceProposalOutput",
    "Stage0OverrideOutput",
    "Stage0ReadinessOutput",
    "SynthesizeIcpsOutput",
    "TierCheckpointOutput",
    "ProjectPhaseAdvanceOutput",
]
