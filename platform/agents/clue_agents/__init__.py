"""Doc A — platform deepagent, subagents, skills, and context contracts.

C6.0 freezes framework-neutral value types and injected ports.  Production runtime construction,
workspace materialization, durable records, and routing intentionally land in later C6 slices.
"""

from clue_agents.contracts import (
    AgentConstitution,
    AgentFinalizeEnvelope,
    AgentPlan,
    AgentProfile,
    AgentResourceManifest,
    AgentResourceRef,
    AgentRole,
    AgentTurnRequest,
    ArtifactRef,
    ContextBundleManifest,
    ContextLayer,
    ContextLayerManifest,
    DelegationRequest,
    DelegationResult,
    DomainObjectRef,
    FinalizeStatus,
    ModelPolicy,
    SkillBundle,
    ToolPin,
    ValidatedOperation,
    ValidatedPlan,
    WorkspacePolicy,
)
from clue_agents.ports import (
    AgentContextAssembler,
    AgentExecutionAdapter,
    AgentHistoryStore,
    AgentModelProvider,
    AgentWorkspaceBackend,
)
from clue_agents.skills import SkillDescriptor, discover_skills, load_skill
from clue_agents.state import ClueDeepAgentState

__all__ = [
    "AgentConstitution",
    "AgentContextAssembler",
    "AgentExecutionAdapter",
    "AgentFinalizeEnvelope",
    "AgentHistoryStore",
    "AgentModelProvider",
    "AgentPlan",
    "AgentProfile",
    "AgentResourceManifest",
    "AgentResourceRef",
    "AgentRole",
    "AgentTurnRequest",
    "AgentWorkspaceBackend",
    "ArtifactRef",
    "ClueDeepAgentState",
    "ContextBundleManifest",
    "ContextLayer",
    "ContextLayerManifest",
    "DelegationRequest",
    "DelegationResult",
    "DomainObjectRef",
    "FinalizeStatus",
    "ModelPolicy",
    "SkillBundle",
    "SkillDescriptor",
    "ToolPin",
    "ValidatedOperation",
    "ValidatedPlan",
    "WorkspacePolicy",
    "discover_skills",
    "load_skill",
]
