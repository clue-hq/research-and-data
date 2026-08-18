"""`clue_research.profiling.committee` — Committee Discovery (mode M3 / M8.3).

Within a known explicitly selected account, find the relevant people and hypothesize each one's
committee role — producing the buying committee (Output 3) and the V1 contact graph (substrate §7).
The trunk is
:func:`discover_committee` (+ :class:`CommitteeAspectWorker` for the M7 graph); it existence-gates
candidates through M2, infers + plausibility-gates roles via the shared LLM gateway, and reports
committee coverage confidence. See ``docs/specs/M08-deep-profiling.md`` §M8.3.
"""

from __future__ import annotations

from clue_research.profiling.committee.admission import (
    AdmissionOutcome,
    AdmissionStatus,
    admit_candidate,
)
from clue_research.profiling.committee.coverage import (
    CommitteeCoverage,
    CommitteeCoverageConfidence,
    estimate_committee_coverage,
)
from clue_research.profiling.committee.fields import (
    COMMITTEE_FIELD_KEYS,
    COMMITTEE_PACK,
    CONTACT_CLASS,
    CURRENT_LOCATION,
    CURRENT_TITLE,
    JOB_FUNCTION,
    JOB_LEVEL,
    ORGANIZATION_RELATIONSHIP,
    PERSONA,
    ROLE_ON_COMMITTEE,
    TEAM_MEMBERSHIP,
    load_committee_pack,
)
from clue_research.profiling.committee.results import (
    DEFAULT_COMMITTEE_CONFIG,
    CommitteeConfig,
    CommitteeMemberRef,
    CommitteeResult,
)
from clue_research.profiling.committee.roles import (
    RoleInference,
    RoleSeniority,
    RoleVerdict,
    gate_role,
    infer_role,
    role_plausible,
    title_seniority,
)
from clue_research.profiling.committee.sources import (
    CandidateFactProvenance,
    CandidateProfessionalFact,
    CommitteePersonCandidate,
    CommitteeSource,
    order_committee_sources,
)
from clue_research.profiling.committee.stopping import (
    DEFAULT_COMMITTEE_STOPPING_CONFIG,
    CommitteeStoppingConfig,
    CommitteeStoppingRule,
    CommitteeStopReason,
)
from clue_research.profiling.committee.worker import (
    CommitteeAspectWorker,
    ProfessionalFactReplayConflict,
    discover_committee,
    write_committee_claim,
)

__all__ = [
    # worker entrypoint + M7 adapter
    "discover_committee",
    "CommitteeAspectWorker",
    "ProfessionalFactReplayConflict",
    "write_committee_claim",
    # result / config
    "CommitteeResult",
    "CommitteeMemberRef",
    "CommitteeConfig",
    "DEFAULT_COMMITTEE_CONFIG",
    # field-class pack (M8.3)
    "COMMITTEE_PACK",
    "COMMITTEE_FIELD_KEYS",
    "ROLE_ON_COMMITTEE",
    "PERSONA",
    "CONTACT_CLASS",
    "CURRENT_TITLE",
    "JOB_FUNCTION",
    "JOB_LEVEL",
    "TEAM_MEMBERSHIP",
    "CURRENT_LOCATION",
    "ORGANIZATION_RELATIONSHIP",
    "load_committee_pack",
    # people-source seam
    "CommitteeSource",
    "CommitteePersonCandidate",
    "CandidateFactProvenance",
    "CandidateProfessionalFact",
    "order_committee_sources",
    # existence gate
    "admit_candidate",
    "AdmissionOutcome",
    "AdmissionStatus",
    # role inference + plausibility gate
    "infer_role",
    "gate_role",
    "role_plausible",
    "title_seniority",
    "RoleInference",
    "RoleVerdict",
    "RoleSeniority",
    # stopping rule
    "CommitteeStoppingRule",
    "CommitteeStoppingConfig",
    "DEFAULT_COMMITTEE_STOPPING_CONFIG",
    "CommitteeStopReason",
    # coverage confidence
    "estimate_committee_coverage",
    "CommitteeCoverage",
    "CommitteeCoverageConfidence",
]
