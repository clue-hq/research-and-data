"""`clue_research.stage0` — Stage 0 Front Edge (M5).

The front edge of the subsystem (Doc B): client reverse-profiling → a versioned Client Knowledge
Base (M5.1), ICP synthesis & proposal (M5.2), and the import + hybrid-lookalike entry scenarios
(M5.3/M5.4). Stage 0 is the *seed of research* — every downstream direction is determined here.

Beat-0 froze the cross-milestone seam in ``core`` (``docs/specs/_beat0-contract-freeze.md``): M5's
``REVERSE_PROFILING``/``ICP_CONFIRMED`` phases *implement* ``PhaseHandler`` from
:mod:`clue_core.execution`; M5.1 calls the M9 ``FaithfulnessJudge`` (injected) for tier-4
client claims, and M5.2's synthesis calls the M0.4 ``LLMGateway`` (injected). Imports and lookalike
seeds reach M6 through the **claim store** — M5 imports no sibling milestone package
(machine-enforced by the import-linter independence contract); it consumes the M1–M4 services
(claimstore/identity/icp/sources) directly. The concrete handlers/gateway are wired into the
``ProjectRun`` at the ``api`` composition root.

M5.1 lands: the ``client.*`` field set, the reverse-profiling orchestration, the claim-native
Client-KB version ledger, and the ``REVERSE_PROFILING`` phase handler. M5.2 lands: ICP synthesis
(``synthesize_icps``), the confirm→compile→diff flow (``confirm_icp``), the pre-run cost estimate,
and the ``ICP_CONFIRMED`` phase handler. M5.3 lands the import entry scenario (``import_accounts``):
bulk identity resolution through M2 (auto-merge / human-review / new-entity / unresolved), CRM
tier-1 enrichment with "already a customer" detection, ICP back-scoring via the importable M3.4
Pass-A scorer, D6 non-fit flagging, governed imported-contact tagging, and the claim-native
``import.batch`` marker — converging into the same account-set shape discovery emits. Import is an
entry scenario, not a campaign phase (no ``IMPORT`` phase); it runs before M6's ``SCORING`` phase,
store-mediated. M5.4 lands hybrid lookalike seeding (``assemble_lookalike_seeds``): it ranks +
packages resolved seed ``account_entity``s — the client's existing customers (M5.1) and high-fit
imports (M5.3) — into a per-ICP ``SeedSet``, the input contract M6 mode-M1 lookalike expansion
consumes. M5.4 produces the seeds, not the discovery run; seeds reach M6 store/spec-mediated through
the confirmed spec's ``discovery_strategy.seed_account_ids`` (so a SeedSet slots straight into an
``ICPProposal``'s ``seed_accounts``). Like import, seeding is an entry scenario, not a phase.
"""

from __future__ import annotations

from clue_config.settings import DEFAULT_SYNTHESIS_MODEL
from clue_research.stage0.client_kb import (
    client_kb_readiness_metrics,
    current_kb_version,
    read_client_kb,
    read_client_kb_claims,
    reverse_profile,
)
from clue_research.stage0.fields import (
    CLIENT_KB_VERSION,
    CLIENT_KNOWLEDGE_FIELDS,
    CLIENT_KNOWLEDGE_PACK,
    CLIENT_PACK,
    SURFACE_CLASS_FIELDS,
    SurfaceClass,
    load_client_knowledge_pack,
)
from clue_research.stage0.governed import (
    OnboardingInputRow,
    ReadinessDecisionRow,
    ReconLaneStatus,
    ReconRunRow,
    StatementCounts,
    StatementRoute,
    VolunteeredStatementRow,
    compile_product_context,
    count_statements_for_input,
    ensure_readiness_spec,
    evaluate_readiness,
    get_onboarding_input,
    get_onboarding_input_for_artifact,
    get_readiness_decision,
    get_recon,
    override_readiness,
    read_readiness_decisions,
    read_statements,
    recon_dedupe_hash,
    record_statement,
    start_recon,
    submit_onboarding_input,
    transition_recon_lane,
)
from clue_research.stage0.icp_confirm import confirm_icp
from clue_research.stage0.icp_estimate import EstimateInputs, estimate_campaign
from clue_research.stage0.icp_fields import (
    ICP_CONFIRM_DIFF,
    ICP_FEEDBACK_PACK,
    ICP_PACK,
    load_icp_feedback_pack,
)
from clue_research.stage0.icp_handler import IcpConfirmedHandler
from clue_research.stage0.icp_synthesis import (
    MAX_PROJECT_STATEMENTS,
    NO_CLIENT_KB_CLAIMS,
    NO_PROJECT_STATEMENTS,
    ICPSynthesisResult,
    ICPSynthesisStatus,
    ProjectStatement,
    synthesize_icps,
    synthesize_icps_with_proposals,
)
from clue_research.stage0.icp_types import (
    CandidateSignal,
    FirmographicDimensions,
    ICPConfirmation,
    ICPProposal,
    ICPProposalDiff,
    ICPProposalEdits,
    ICPSpecRef,
    ProposedRubric,
    RubricWeight,
    RubricWeightChange,
    SeedAccount,
    SourcePrior,
    StartingSourceProfile,
    TechnographicDimension,
)
from clue_research.stage0.import_accounts import import_accounts, import_batch_run_id
from clue_research.stage0.import_fields import (
    CONTACT_IMPORT_RECORD,
    DISCOVERY_PROVENANCE,
    IMPORT_BATCH,
    IMPORT_PACK,
    load_import_pack,
)
from clue_research.stage0.import_types import (
    FitFlag,
    ImportContactResult,
    ImportContactRow,
    ImportResult,
    ImportRow,
    NeedsReviewRow,
    ResolvedAccount,
    UnresolvedRow,
)
from clue_research.stage0.interview import (
    SOURCE_CLIENT_INTERVIEW,
    SOURCE_CLIENT_INTERVIEW_JUDGED,
    ClaimEntailment,
    ClaimEntailmentJudge,
    InterviewClaimEntityRefused,
    InterviewEvidenceRefused,
    InterviewRoute,
    InterviewRoutingResult,
    InterviewStatement,
    is_judged_value,
    judge_interview_values,
    locate_quote,
    prepare_interview_statements,
    register_client_interview_source,
    resolve_claim_entity,
    route_interview_answer,
)
from clue_research.stage0.reuse import (
    CLIENT_KNOWLEDGE_REUSE_POLICY,
    ICP_REUSE_POLICY,
    IMPORT_REUSE_POLICY,
    SEED_REUSE_POLICY,
)
from clue_research.stage0.reverse_profiling_handler import (
    ReverseProfilingHandler,
    reverse_profiling_run_id,
)
from clue_research.stage0.seeds import assemble_lookalike_seeds, seeds_run_id
from clue_research.stage0.seeds_types import (
    DEFAULT_SEED_POLICY,
    SeedPolicy,
    SeedReason,
    SeedSet,
    SkippedSeed,
)
from clue_research.stage0.types import (
    ClientInput,
    ClientKnowledgeBaseRef,
    CoverageReport,
    ReverseProfileResult,
    SurfaceCoverage,
    VolunteeredMaterial,
)

__all__ = [
    # M5.1 — reverse-profiling → versioned Client Knowledge Base
    "reverse_profile",
    "read_client_kb",
    "read_client_kb_claims",
    "client_kb_readiness_metrics",
    "current_kb_version",
    "ReverseProfilingHandler",
    "reverse_profiling_run_id",
    # M5.1 input / output contracts
    "ClientInput",
    "VolunteeredMaterial",
    "ClientKnowledgeBaseRef",
    "CoverageReport",
    "SurfaceCoverage",
    "ReverseProfileResult",
    # the client-knowledge field set + surface taxonomy
    "load_client_knowledge_pack",
    "CLIENT_KNOWLEDGE_PACK",
    "CLIENT_KNOWLEDGE_FIELDS",
    "CLIENT_KB_VERSION",
    "CLIENT_PACK",
    "SurfaceClass",
    "SURFACE_CLASS_FIELDS",
    # M5.2 — ICP synthesis & proposal
    "synthesize_icps",
    "synthesize_icps_with_proposals",
    "ICPSynthesisResult",
    "ICPSynthesisStatus",
    "ProjectStatement",
    "NO_CLIENT_KB_CLAIMS",
    "NO_PROJECT_STATEMENTS",
    "MAX_PROJECT_STATEMENTS",
    "DEFAULT_SYNTHESIS_MODEL",
    "confirm_icp",
    "estimate_campaign",
    "EstimateInputs",
    "IcpConfirmedHandler",
    # M5.2 proposal / confirm contracts
    "ICPProposal",
    "FirmographicDimensions",
    "TechnographicDimension",
    "CandidateSignal",
    "SeedAccount",
    "SourcePrior",
    "StartingSourceProfile",
    "RubricWeight",
    "ProposedRubric",
    "ICPProposalEdits",
    "ICPProposalDiff",
    "RubricWeightChange",
    "ICPSpecRef",
    "ICPConfirmation",
    # M5.2 icp.* feedback field set (claim-native confirm diff)
    "load_icp_feedback_pack",
    "ICP_FEEDBACK_PACK",
    "ICP_PACK",
    "ICP_CONFIRM_DIFF",
    # M5.3 — import entry scenario (bulk ID resolution + ICP back-scoring + non-fit flagging)
    "import_accounts",
    "import_batch_run_id",
    # M5.3 input / output contracts
    "ImportRow",
    "ImportContactRow",
    "ImportResult",
    "ResolvedAccount",
    "NeedsReviewRow",
    "UnresolvedRow",
    "ImportContactResult",
    "FitFlag",
    # M5.3 import field set (claim-native batch marker + governed contact record)
    "load_import_pack",
    "IMPORT_PACK",
    "IMPORT_BATCH",
    "CONTACT_IMPORT_RECORD",
    "DISCOVERY_PROVENANCE",
    # M5.4 — hybrid lookalike seeding (imports / existing customers → M6 seed set)
    "assemble_lookalike_seeds",
    "seeds_run_id",
    "SeedSet",
    "SkippedSeed",
    "SeedReason",
    "SeedPolicy",
    "DEFAULT_SEED_POLICY",
    # reuse policies (client-knowledge + icp + import + seed are tenant-private)
    "CLIENT_KNOWLEDGE_REUSE_POLICY",
    "ICP_REUSE_POLICY",
    "IMPORT_REUSE_POLICY",
    "SEED_REUSE_POLICY",
    # C4 governed Stage 0
    "OnboardingInputRow",
    "ReadinessDecisionRow",
    "ReconLaneStatus",
    "ReconRunRow",
    "StatementCounts",
    "StatementRoute",
    "compile_product_context",
    "count_statements_for_input",
    "ensure_readiness_spec",
    "evaluate_readiness",
    "get_onboarding_input",
    "get_onboarding_input_for_artifact",
    "get_readiness_decision",
    "get_recon",
    "override_readiness",
    "recon_dedupe_hash",
    "read_readiness_decisions",
    "read_statements",
    "record_statement",
    "VolunteeredStatementRow",
    "start_recon",
    "submit_onboarding_input",
    "transition_recon_lane",
    "SOURCE_CLIENT_INTERVIEW",
    "SOURCE_CLIENT_INTERVIEW_JUDGED",
    "ClaimEntailment",
    "ClaimEntailmentJudge",
    "InterviewClaimEntityRefused",
    "InterviewEvidenceRefused",
    "InterviewRoute",
    "InterviewRoutingResult",
    "InterviewStatement",
    "is_judged_value",
    "judge_interview_values",
    "locate_quote",
    "prepare_interview_statements",
    "register_client_interview_source",
    "resolve_claim_entity",
    "route_interview_answer",
]
