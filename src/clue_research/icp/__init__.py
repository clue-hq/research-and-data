"""`clue_research.icp` — ICP & Research-Schema Compiler (M3).

Package scaffolded by M0.1 (ENG-101); scope and the modular-boundary rules live in this package's
``README.md``. Implemented by M3:

* **M3.3 — industry packs framework** (this module set): the pack catalog + the two prior sets of a
  pack (field set via the M1.3 registry; source profile as versioned config). Public seam below.
* M3.1 (ICP spec), M3.2 (research-schema compiler), M3.4 (scoring rubric) — to follow.

M3.3 reuses the claim-store substrate (M1) to author field rows and stores source profiles as its
own config tables; it references M4's ``source_key`` namespace by string only and imports no
resolver, manifest, Source Planner, or provider SDK (conventions §2; M0.1 import rules).
"""

from __future__ import annotations

from clue_research.icp.catalog import (
    Pack,
    PackRecord,
    PackRedefinitionError,
    PackSourceSlot,
    PackValidationError,
    UnknownPackError,
    get_pack,
    get_pack_field_set,
    get_pack_source_profile,
    list_packs,
    register_pack_catalog,
    validate_pack,
)
from clue_research.icp.packs import (
    DATA_INFRA,
    FRONTIER_AI,
    HEALTHCARE_PRACTICE,
    STARTER_PACKS,
    load_starter_packs,
)
from clue_research.icp.source_profile import (
    ResolvedSourceProfile,
    SourceProfileRedefinitionError,
    SourceWeight,
    WeightedSource,
    get_source_profile,
    is_valid_source_key,
    register_source_profile,
    register_source_profile_override,
)

__all__ = [
    # pack catalog (M3.3)
    "Pack",
    "PackSourceSlot",
    "PackRecord",
    "register_pack_catalog",
    "list_packs",
    "get_pack",
    "get_pack_field_set",
    "get_pack_source_profile",
    "validate_pack",
    "UnknownPackError",
    "PackRedefinitionError",
    "PackValidationError",
    # source-profile half (M3.3)
    "SourceWeight",
    "WeightedSource",
    "ResolvedSourceProfile",
    "register_source_profile",
    "register_source_profile_override",
    "get_source_profile",
    "is_valid_source_key",
    "SourceProfileRedefinitionError",
    # worked starter packs (M3.3)
    "STARTER_PACKS",
    "FRONTIER_AI",
    "HEALTHCARE_PRACTICE",
    "DATA_INFRA",
    "load_starter_packs",
]
