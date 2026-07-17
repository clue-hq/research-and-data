"""`clue_research.compliance` — Compliance & Personal-Data Governance (M10).

Package scaffolded by M0.1 (ENG-101); scope and the modular-boundary rules live in this package's
``README.md``. Implemented by M10: jurisdiction resolution (M10.1), use-class tagging (M10.2), the
appropriateness/use gate (M10.3 — impl of the frozen ``core.compliance.UseGate`` seam), the three
postures as config (M10.4), and lawful basis + retention + DSAR/erasure (M10.5).

Compliance reads/writes through the claim store and reads config + obs; it imports no sibling worker
package (the import-linter independence contract). The cross-package use-gate seam lives in
``core.compliance``; this package supplies the implementations, injected at the ``api`` root.
"""

from __future__ import annotations

from clue_research.compliance.dsar import (
    ERASE_ALL,
    DataSubjectExport,
    DataSubjectRights,
    DataSubjectRightsImpl,
    ErasureResult,
    ErasureScope,
    ObjectionResult,
    RetentionSweep,
    SweepResult,
    TombstoneReason,
    build_tombstone,
)
from clue_research.compliance.fields import (
    COMPLIANCE_PACK,
    CONTACT_JURISDICTION,
    load_compliance_pack,
)
from clue_research.compliance.jurisdiction import (
    DerivedFrom,
    JurisdictionResolution,
    JurisdictionResolver,
    JurisdictionResolverImpl,
    extract_region,
    region_from_value,
    region_to_regime,
)
from clue_research.compliance.lawful_basis import (
    LawfulBasis,
    LawfulBasisRecord,
    NoticeReport,
    derive_lawful_basis,
    is_third_party_collected,
    load_lawful_basis,
    record_lawful_basis,
    retention_horizon_for,
    third_party_notice_report,
)
from clue_research.compliance.posture import (
    DEFAULT_POSTURE_POLICY,
    POSTURE_PRESETS,
    PosturePreset,
    workspace_policy_for_posture,
)
from clue_research.compliance.use_gate import (
    DEFAULT_WORKSPACE_POLICY,
    SensitiveOverride,
    UseGateImpl,
    WorkspacePolicy,
    decide_use,
    load_workspace_policy,
)

__all__ = [
    # M10.1 — jurisdiction resolution
    "JurisdictionResolver",
    "JurisdictionResolverImpl",
    "JurisdictionResolution",
    "DerivedFrom",
    "extract_region",
    "region_from_value",
    "region_to_regime",
    # M10.3 — appropriateness/use gate (impl of core.compliance.UseGate)
    "UseGateImpl",
    "WorkspacePolicy",
    "SensitiveOverride",
    "DEFAULT_WORKSPACE_POLICY",
    "decide_use",
    "load_workspace_policy",
    # M10.4 — the three postures as per-client config
    "POSTURE_PRESETS",
    "PosturePreset",
    "workspace_policy_for_posture",
    "DEFAULT_POSTURE_POLICY",
    # M10.5 — lawful basis + retention
    "LawfulBasis",
    "LawfulBasisRecord",
    "NoticeReport",
    "derive_lawful_basis",
    "retention_horizon_for",
    "is_third_party_collected",
    "record_lawful_basis",
    "load_lawful_basis",
    "third_party_notice_report",
    # M10.5 — DSAR / erasure (tombstone) + retention sweep
    "DataSubjectRights",
    "DataSubjectRightsImpl",
    "RetentionSweep",
    "DataSubjectExport",
    "ErasureScope",
    "ERASE_ALL",
    "ErasureResult",
    "ObjectionResult",
    "SweepResult",
    "TombstoneReason",
    "build_tombstone",
    # field pack (M10.1 contact.jurisdiction; M10.5 retention semantics live in lawful_basis/dsar)
    "COMPLIANCE_PACK",
    "CONTACT_JURISDICTION",
    "load_compliance_pack",
]
