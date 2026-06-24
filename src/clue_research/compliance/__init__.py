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

__all__ = [
    # M10.1 — jurisdiction resolution
    "JurisdictionResolver",
    "JurisdictionResolverImpl",
    "JurisdictionResolution",
    "DerivedFrom",
    "extract_region",
    "region_from_value",
    "region_to_regime",
    # field pack (M10.1 contact.jurisdiction; M10.5 will extend)
    "COMPLIANCE_PACK",
    "CONTACT_JURISDICTION",
    "load_compliance_pack",
]
