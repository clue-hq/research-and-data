"""`clue_research.stage0` — Stage 0 Front Edge (M5).

The front edge of the subsystem (Doc B): client reverse-profiling → a versioned Client Knowledge
Base (M5.1), ICP synthesis & proposal (M5.2), and the import + hybrid-lookalike entry scenarios
(M5.3/M5.4). Stage 0 is the *seed of research* — every downstream direction is determined here.

Beat-0 froze the cross-milestone seam in ``core`` (``docs/specs/_beat0-contract-freeze.md``): M5's
``REVERSE_PROFILING``/``ICP_CONFIRMED`` phases *implement* ``PhaseHandler`` from
:mod:`clue_research.core.execution`, and M5.1 calls the M9 ``FaithfulnessJudge`` (the
:mod:`clue_research.core.verification` protocol, injected) for tier-4 client claims. Imports and
lookalike seeds reach M6 through the **claim store** — M5 imports no sibling milestone package
(machine-enforced by the import-linter independence contract). The concrete handlers are wired into
the ``CampaignRun`` at the ``api`` composition root.

M5.1 (this milestone) lands: the ``client.*`` field set, the reverse-profiling orchestration, the
claim-native Client-KB version ledger, and the ``REVERSE_PROFILING`` phase handler.
"""

from __future__ import annotations

from clue_research.stage0.client_kb import (
    current_kb_version,
    read_client_kb,
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
from clue_research.stage0.reuse import CLIENT_KNOWLEDGE_REUSE_POLICY
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
    "current_kb_version",
    "ReverseProfilingHandler",
    "reverse_profiling_run_id",
    # input / output contracts
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
    # reuse policy (client-knowledge is tenant-private)
    "CLIENT_KNOWLEDGE_REUSE_POLICY",
]
