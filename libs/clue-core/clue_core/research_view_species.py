"""C7 source-species and legacy-block ownership map.

The research-view composer aggregates independently-owned facts. This module is the executable
boundary that prevents it from authoring identity, score, committee, activity, execution, or
coverage data as if those values were research claims. It also freezes the nine-block compatibility
adapter without introducing a document-shaped dossier contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from clue_core.enums import (
    DossierBlockKind,
    ResearchDataSpecies,
    ResearchSectionKind,
)

_CLAIM = frozenset({ResearchDataSpecies.CLAIM_DERIVATION})

SECTION_SPECIES_POLICY: Final[Mapping[ResearchSectionKind, frozenset[ResearchDataSpecies]]] = (
    MappingProxyType(
        {
            ResearchSectionKind.IDENTITY: frozenset({ResearchDataSpecies.IDENTITY}),
            ResearchSectionKind.RESEARCH_STATUS: frozenset({ResearchDataSpecies.EXECUTION}),
            ResearchSectionKind.SUMMARY: _CLAIM,
            ResearchSectionKind.ABOUT: _CLAIM,
            ResearchSectionKind.FIT: frozenset({ResearchDataSpecies.SCORE}),
            ResearchSectionKind.INSIGHTS: _CLAIM,
            ResearchSectionKind.COMMITTEE: frozenset({ResearchDataSpecies.COMMITTEE}),
            ResearchSectionKind.ACTIVITY: frozenset({ResearchDataSpecies.ACTIVITY}),
            ResearchSectionKind.PROFESSIONAL_SIGNALS: _CLAIM,
            ResearchSectionKind.EVIDENCE: _CLAIM,
            ResearchSectionKind.QUOTES: _CLAIM,
            ResearchSectionKind.BACKGROUND: _CLAIM,
            ResearchSectionKind.CAREER: _CLAIM,
            ResearchSectionKind.EDUCATION: _CLAIM,
            ResearchSectionKind.PUBLICATIONS: _CLAIM,
            ResearchSectionKind.AWARDS: _CLAIM,
            ResearchSectionKind.PERSONALIZATION: _CLAIM,
            ResearchSectionKind.VALUE_NARRATIVE: _CLAIM,
            ResearchSectionKind.FEASIBILITY: _CLAIM,
            ResearchSectionKind.COVERAGE_GAPS: frozenset({ResearchDataSpecies.COVERAGE}),
        }
    )
)


BLOCK_KIND_BY_SECTION: Final[Mapping[ResearchSectionKind, DossierBlockKind | None]] = (
    MappingProxyType(
        {
            ResearchSectionKind.IDENTITY: None,
            ResearchSectionKind.RESEARCH_STATUS: None,
            ResearchSectionKind.SUMMARY: DossierBlockKind.EXECUTIVE_SUMMARY,
            ResearchSectionKind.ABOUT: DossierBlockKind.COMPANY_PROFILE,
            ResearchSectionKind.FIT: DossierBlockKind.FIT_ASSESSMENT,
            ResearchSectionKind.INSIGHTS: DossierBlockKind.SIGNAL,
            ResearchSectionKind.COMMITTEE: DossierBlockKind.COMMITTEE_MEMBER,
            ResearchSectionKind.ACTIVITY: None,
            ResearchSectionKind.PROFESSIONAL_SIGNALS: DossierBlockKind.SIGNAL,
            ResearchSectionKind.EVIDENCE: DossierBlockKind.SIGNAL,
            ResearchSectionKind.QUOTES: DossierBlockKind.SIGNAL,
            ResearchSectionKind.BACKGROUND: DossierBlockKind.SIGNAL,
            ResearchSectionKind.CAREER: DossierBlockKind.SIGNAL,
            ResearchSectionKind.EDUCATION: DossierBlockKind.SIGNAL,
            ResearchSectionKind.PUBLICATIONS: DossierBlockKind.SIGNAL,
            ResearchSectionKind.AWARDS: DossierBlockKind.SIGNAL,
            ResearchSectionKind.PERSONALIZATION: DossierBlockKind.PERSONALIZATION,
            ResearchSectionKind.VALUE_NARRATIVE: DossierBlockKind.VALUE_NARRATIVE,
            ResearchSectionKind.FEASIBILITY: DossierBlockKind.FEASIBILITY,
            ResearchSectionKind.COVERAGE_GAPS: DossierBlockKind.COVERAGE_GAP,
        }
    )
)


# Compatibility names delegate to the one research-view service when C7.7 exposes them. They do
# not authorize a second tool implementation, persistence path, or rendered-body contract.
LEGACY_DOSSIER_ALIASES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "compose_dossier@1": "research_view.compose",
        "dossier.updated": "research_view.updated",
        "dossier.section.stale": "research_view.section_stale",
    }
)


def allowed_species(section_kind: ResearchSectionKind) -> frozenset[ResearchDataSpecies]:
    """Return the authoritative data species allowed in ``section_kind``."""

    return SECTION_SPECIES_POLICY[section_kind]


def compatibility_block_kind(section_kind: ResearchSectionKind) -> DossierBlockKind | None:
    """Return the old nine-block adapter kind, if the semantic section participates in it."""

    return BLOCK_KIND_BY_SECTION[section_kind]


def species_is_allowed(
    section_kind: ResearchSectionKind,
    species: ResearchDataSpecies,
) -> bool:
    """Whether a C7 item preserves the section's existing authority boundary."""

    return species in allowed_species(section_kind)
