"""`clue_research.stage0` — Stage 0 Front Edge (M5).

The front edge of the subsystem (Doc B): client reverse-profiling → a versioned Client Knowledge
Base (M5.1), ICP synthesis & proposal (M5.2), and the import + hybrid-lookalike entry scenarios
(M5.3/M5.4). Stage 0 is the *seed of research* — every downstream direction is determined here.

Beat-0 froze the cross-milestone seam in ``core`` (``docs/specs/_beat0-contract-freeze.md``): M5's
``REVERSE_PROFILING``/``ICP_CONFIRMED`` phases *implement* ``PhaseHandler`` from
:mod:`clue_research.core.execution`; M5.1 calls the M9 ``FaithfulnessJudge`` (injected) for tier-4
client claims, and M5.2's synthesis calls the M0.4 ``LLMGateway`` (injected). Imports and lookalike
seeds reach M6 through the **claim store** — M5 imports no sibling milestone package
(machine-enforced by the import-linter independence contract); it consumes the M1–M4 services
(claimstore/identity/icp/sources) directly. The concrete handlers/gateway are wired into the
``CampaignRun`` at the ``api`` composition root.

M5.1 lands: the ``client.*`` field set, the reverse-profiling orchestration, the claim-native
Client-KB version ledger, and the ``REVERSE_PROFILING`` phase handler. M5.2 lands: ICP synthesis
(``synthesize_icps``), the confirm→compile→diff flow (``confirm_icp``), the pre-run cost estimate,
and the ``ICP_CONFIRMED`` phase handler.
"""

from __future__ import annotations

from clue_research.stage0.client_kb import (
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
from clue_research.stage0.icp_confirm import confirm_icp
from clue_research.stage0.icp_estimate import EstimateInputs, estimate_campaign
from clue_research.stage0.icp_fields import (
    ICP_CONFIRM_DIFF,
    ICP_FEEDBACK_PACK,
    ICP_PACK,
    load_icp_feedback_pack,
)
from clue_research.stage0.icp_handler import IcpConfirmedHandler
from clue_research.stage0.icp_synthesis import DEFAULT_SYNTHESIS_MODEL, synthesize_icps
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
from clue_research.stage0.reuse import (
    CLIENT_KNOWLEDGE_REUSE_POLICY,
    ICP_REUSE_POLICY,
)
from clue_research.stage0.reverse_profiling_handler import (
    ReverseProfilingHandler,
    reverse_profiling_run_id,
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
    # reuse policies (client-knowledge + icp are tenant-private)
    "CLIENT_KNOWLEDGE_REUSE_POLICY",
    "ICP_REUSE_POLICY",
]
