"""`clue_research.icp` — ICP & Research-Schema Compiler (M3).

Package scaffolded by M0.1 (ENG-101); scope and the modular-boundary rules live in this package's
``README.md``. Implemented by M3:

* **M3.1 — ICP spec data model** (``spec.py``): durable, append-only storage + read/write API for
  the versioned ``ICPSpec`` contract (keyed ``(client_id, icp_key, version)``), validating
  field-keys against the M1.3 registry and packs against the M3.3 catalog.
* **M3.2 — research-schema compiler** (``compiler.py``): pure ``compile_field_plan(icp_spec)`` →
  typed ``FieldPlan`` (scoring/deep partition, signal-class links, gates, per-ICP overrides).
* **M3.3 — industry packs framework** (``catalog`` / ``source_profile`` / ``packs``): the pack
  catalog + the two prior sets of a pack (field set in M1.3; source profile as versioned config).
* M3.4 (scoring rubric) — to follow.

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
from clue_research.icp.compiler import (
    CompileError,
    FieldOverride,
    FieldPlan,
    FieldPlanEntry,
    SignalClassLink,
    compile_active_icp,
    compile_field_plan,
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
from clue_research.icp.spec import (
    ICPSpecDiff,
    ICPSpecValidationError,
    UnknownICPSpecError,
    activate_icp_version,
    create_icp_spec,
    diff_icp,
    get_active_icp,
    get_icp_version,
    list_icp_keys,
    list_icp_versions,
    validate_icp_references,
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
    # ICP spec data model (M3.1)
    "create_icp_spec",
    "activate_icp_version",
    "get_active_icp",
    "get_icp_version",
    "list_icp_versions",
    "list_icp_keys",
    "diff_icp",
    "validate_icp_references",
    "ICPSpecDiff",
    "ICPSpecValidationError",
    "UnknownICPSpecError",
    # research-schema compiler (M3.2)
    "compile_field_plan",
    "compile_active_icp",
    "FieldPlan",
    "FieldPlanEntry",
    "SignalClassLink",
    "FieldOverride",
    "CompileError",
]
