"""API-root wiring for C7 deterministic research-view composition.

Concrete owner adapters are deliberately assembled here, the one package allowed to import every
subsystem. C7.3 exposes this factory so later API/tool/snapshot slices share one composer rather
than creating parallel dossier implementations.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from clue_research.narrative import (
    ActivityReferenceReader,
    CanonicalSubjectReader,
    CommitteeViewReader,
    CoverageViewReader,
    DerivedClaimReader,
    DeterministicResearchViewComposer,
    DirectClaimReader,
    FitResultReader,
    StatementGovernanceReader,
)


def build_research_view_composer(
    *,
    subjects: CanonicalSubjectReader,
    direct_claims: DirectClaimReader,
    derived_claims: DerivedClaimReader,
    fit: FitResultReader,
    committee: CommitteeViewReader,
    coverage: CoverageViewReader,
    activity: ActivityReferenceReader,
    governance: StatementGovernanceReader,
    clock: Callable[[], datetime] | None = None,
) -> DeterministicResearchViewComposer:
    """Construct the sole C7 live composer from concrete/injected owner readers."""

    return DeterministicResearchViewComposer(
        subjects=subjects,
        direct_claims=direct_claims,
        derived_claims=derived_claims,
        fit=fit,
        committee=committee,
        coverage=coverage,
        activity=activity,
        governance=governance,
        clock=clock,
    )
