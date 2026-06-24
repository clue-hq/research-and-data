"""`clue_research.narrative` — Value Narrative & Handoff (M12).

The output edge of the research subsystem (overview §3): the per-``(account, persona)`` **value
narrative** (Output 4) and — later in M12.2/M12.3 — the ``account_handoff`` contract object and
the boundary API to the content layer. Scope and the modular-boundary rules live in this package's
``README.md``.

Shipped so far:

* **M12.1 — the positioning step** (:mod:`clue_research.narrative.positioner`): the
  :class:`Positioner` graph node that joins *verified account claims × client knowledge* into a
  per-persona :data:`~clue_research.narrative.fields.VALUE_NARRATIVE` claim-with-provenance,
  behind the M9.3 faithfulness judge. Its config-as-data (:class:`PositioningPolicy`, the
  versioned prompts + per-persona angle templates), the injected committee/retrieval seams, and
  the ``claim_support`` two-sided provenance side table.

This package imports only the shared base (``core`` / ``config`` / ``obs``) and the M1–M4 services
(``claimstore`` / ``identity``); it communicates with sibling milestones (M8/M9/M10/M5) through
``core`` seams + the claim store, never by importing them (the import-linter independence
contract).
"""

from __future__ import annotations

from clue_research.narrative.fields import (
    NARRATIVE_FIELD_KEYS,
    NARRATIVE_PACK,
    VALUE_NARRATIVE,
    load_narrative_pack,
)
from clue_research.narrative.handoff import (
    FIT_FIELD,
    INTENT_FIELD,
    METRIC_HANDOFFS_ASSEMBLED,
    SPAN_HANDOFF_ASSEMBLE,
    AssembledHandoff,
    HandoffAssembler,
    HandoffAssemblyError,
)
from clue_research.narrative.handoff_seams import (
    HandoffCommitteeMember,
    HandoffCommitteeReader,
    InMemoryHandoffCommitteeReader,
)
from clue_research.narrative.handoff_store import read_handoff, write_handoff
from clue_research.narrative.policy import (
    ACCOUNT_OPERATIONAL_PAIN,
    ACCOUNT_RESONANCE_CULTURE,
    ACCOUNT_STRATEGIC_MOVES,
    DEFAULT_FIELD_RELEVANCE,
    DEFAULT_POSITIONING_POLICY,
    NARRATIVE_ACCOUNT_FIELDS,
    PositioningPolicy,
    load_positioning_policy,
)
from clue_research.narrative.positioner import (
    METRIC_NARRATIVE_COVERAGE_GAP,
    METRIC_NARRATIVES_PRODUCED,
    SPAN_NARRATIVE_POSITION,
    CoverageGap,
    Positioner,
    PositioningResult,
    ValueNarrativeRef,
    assemble_evidence_span,
)
from clue_research.narrative.prompts import (
    ANGLE_TEMPLATES,
    PROMPT_VERSION,
    PROMPTS,
    AccountFact,
    AngleTemplate,
    ParsedArgument,
    angle_for,
    build_positioning_messages,
    fact_to_text,
    parse_positioning_response,
)
from clue_research.narrative.reuse import NARRATIVE_REUSE_POLICY
from clue_research.narrative.seams import (
    CommitteeContact,
    CommitteeReader,
    FacetHook,
    InMemoryClientKnowledgeRetriever,
    InMemoryCommitteeReader,
    rank_by_query_overlap,
)
from clue_research.narrative.support import (
    ClaimSupport,
    FaithfulnessCitation,
    read_claim_support,
    read_faithfulness_citation,
    write_claim_support,
)

__all__ = [
    # field registration (M1.3 row)
    "VALUE_NARRATIVE",
    "NARRATIVE_PACK",
    "NARRATIVE_FIELD_KEYS",
    "load_narrative_pack",
    # reuse stamping
    "NARRATIVE_REUSE_POLICY",
    # policy-as-data (M12.1 AC8)
    "PositioningPolicy",
    "DEFAULT_POSITIONING_POLICY",
    "DEFAULT_FIELD_RELEVANCE",
    "NARRATIVE_ACCOUNT_FIELDS",
    "ACCOUNT_OPERATIONAL_PAIN",
    "ACCOUNT_STRATEGIC_MOVES",
    "ACCOUNT_RESONANCE_CULTURE",
    "load_positioning_policy",
    # prompts (prompt-as-data)
    "PROMPT_VERSION",
    "PROMPTS",
    "ANGLE_TEMPLATES",
    "AngleTemplate",
    "AccountFact",
    "ParsedArgument",
    "angle_for",
    "build_positioning_messages",
    "parse_positioning_response",
    "fact_to_text",
    # injected seams + fixtures
    "CommitteeReader",
    "CommitteeContact",
    "FacetHook",
    "InMemoryCommitteeReader",
    "InMemoryClientKnowledgeRetriever",
    "rank_by_query_overlap",
    # claim_support side table
    "ClaimSupport",
    "write_claim_support",
    "read_claim_support",
    # faithfulness citation (M12.2 provenance — the answering judge model)
    "FaithfulnessCitation",
    "read_faithfulness_citation",
    # the positioning step
    "Positioner",
    "PositioningResult",
    "ValueNarrativeRef",
    "CoverageGap",
    "assemble_evidence_span",
    "SPAN_NARRATIVE_POSITION",
    "METRIC_NARRATIVES_PRODUCED",
    "METRIC_NARRATIVE_COVERAGE_GAP",
    # the handoff assembler (M12.2)
    "HandoffAssembler",
    "AssembledHandoff",
    "HandoffAssemblyError",
    "FIT_FIELD",
    "INTENT_FIELD",
    "SPAN_HANDOFF_ASSEMBLE",
    "METRIC_HANDOFFS_ASSEMBLED",
    # the handoff committee seam (M12.2)
    "HandoffCommitteeReader",
    "HandoffCommitteeMember",
    "InMemoryHandoffCommitteeReader",
    # the account_handoff materialization (M12.2)
    "write_handoff",
    "read_handoff",
]
