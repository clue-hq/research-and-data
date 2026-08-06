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


class TargetedEnrichmentOutput(ToolOutput):
    operation_id: str
    state: str
    outcome: str
    provider_units_reserved: str
    cost_cents_reserved: str


class AccountGapEnrichmentOutput(ToolOutput):
    operation_id: str
    account_entity_id: str
    state: str
    outcome: str
    provider_units_reserved: str
    provider_units_charged: str
    claim_ids: list[str]


class PhaseAccountsOutput(ToolOutput):
    status: str
    accounts_processed: int


class TierCheckpointOutput(ToolOutput):
    project_run_id: str
    phase: str


class AccountDeepLaunchOutput(ToolOutput):
    launch_id: str
    project_run_id: str
    research_directive_id: str
    selected_accounts: int
    estimated_cost_cents: str
    approved_budget_cap_cents: str
    replayed: bool
    enqueued: bool


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


class GovernedContactProfileOutput(ToolOutput):
    contact_entity_id: str
    project_run_id: str
    status: str
    selection_ref: str | None
    claim_refs: list[str]
    fields_filled: int


class HandoffOutput(ToolOutput):
    project_run_id: str
    handoffs: int
    narrative_emit_skipped: bool


class ContactContentHandoffOutput(ToolOutput):
    handoff: dict[str, object]


class ContactResearchSelectionApprovalOutput(ToolOutput):
    selection_id: str
    selection_sha256: str
    predecessor_selection_id: str
    approval_ref: str


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


class ResearchViewChangeReportOutput(ToolOutput):
    report_id: str
    operation_id: str
    old_snapshot_id: str
    new_snapshot_id: str
    old_source_state_sha256: str
    new_source_state_sha256: str
    old_composition_sha256: str
    new_composition_sha256: str
    unchanged_statement_ids: list[str]
    added_statement_ids: list[str]
    removed_statement_ids: list[str]
    stale_statement_ids: list[str]
    restricted_statement_ids: list[str]
    requested_operation_ids: list[str]
    reason_codes: list[str]
    fetch_ref: str


class ResearchViewReceiptOutput(ToolOutput):
    schema_version: str
    snapshot_id: str
    view_id: str
    workspace_id: str
    project_id: str
    project_run_id: str
    subject: dict[str, object]
    product_id: str | None
    source_state_sha256: str
    composition_sha256: str
    created_at: str
    fetch_ref: str


class ResearchViewRefOutput(ToolOutput):
    view_id: str
    snapshot_id: str | None
    workspace_id: str
    project_id: str
    subject_entity_id: str
    product_id: str | None
    source_state_sha256: str
    fetch_ref: str


class FieldProposalOutput(ToolOutput):
    field_proposal_id: str
    field_key: str
    status: str
    materialization_id: str | None = None
    materialization_status: str | None = None
    claim_ref: str | None = None
    client_kb_version: int | None = None
    refusal_code: str | None = None


class FieldProposalDecisionOutput(ToolOutput):
    field_proposal_id: str
    status: str
    applied_field_key: str | None
    materialization_id: str | None = None
    materialization_status: str | None = None
    claim_ref: str | None = None
    client_kb_version: int | None = None
    refusal_code: str | None = None


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


class StatementHistoryOutput(ToolOutput):
    """PC-C8 §7 — one bounded page of interview history.

    ``returned <= page_size`` always, and every reduction is named. A row whose words could not be
    read carries ``quote_excluded_reason`` and a null ``quoted_text``; the tool never substitutes
    text it did not verify.

    ``total_matching`` is how many rows the selector matched — and is **null for the
    ``excluded_statement_evidence`` view**, where the total is genuinely unknown without resolving
    evidence for the entire ledger (the scan that view is bounded to avoid). Reporting the
    candidate-pool size there would let a caller read a truncated page as a complete one, so the
    field abstains instead. ``has_more`` + ``next_cursor`` are the complete-traversal contract in
    every view; ``candidates_scanned`` is how many candidate rows this page examined, which is what
    the cursor advanced by.
    """

    project_id: str
    view: str
    statements: list[dict[str, object]]
    page_size: int
    returned: int
    total_matching: int | None
    candidates_scanned: int
    has_more: bool
    next_cursor: str | None


class ReadinessHistoryOutput(ToolOutput):
    """PC-C8 §7 — one bounded, override-annotated page of the readiness ledger."""

    project_id: str
    gate: str | None
    decisions: list[dict[str, object]]
    page_size: int
    returned: int
    total_matching: int
    ledger_length: int
    has_more: bool
    next_cursor: str | None


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
    "ReadinessHistoryOutput",
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
    "StatementHistoryOutput",
    "SynthesizeIcpsOutput",
    "TierCheckpointOutput",
    "ProjectPhaseAdvanceOutput",
]
