"""``clue_research.synthesis`` — Tier-4 LLM Synthesis (M11).

M11.1 / M11.2 ship the tier-4 resolvers (Exa Deep / Parallel Task) under ``resolvers/`` (provider
SDKs live behind the forbidden-SDK contract, not here). **M11.3** ships *this* package: the gating
policy + per-field verification-health surface that make those resolvers safe to ship — the
governed, judge-gated layer (substrate §11 step 6).

This package is a milestone worker under the independence contract: it imports only
``core``/``config``/``obs`` + the M1–M4 services (``claimstore``/``sources``/``icp``/``identity``),
never ``verification/`` or ``resolvers/``. So it owns the *policy* (what is a synthesis field,
Pass-B-only, the account-only firewall) and the *metric*, while the runtime judge-gating pipeline
(resolve → corroboration → faithfulness → promote) is composed at the ``api`` root. See the
``README.md`` for the modular-boundary rules.
"""

from __future__ import annotations

from clue_research.synthesis.gating import (
    ACCOUNT_SYNTHESIS_CLASSES,
    PASS_B_MODE,
    SYNTHESIS_SOURCE_KEYS,
    SynthesisGateError,
    assert_pass_b_claim,
    guard_account_only,
    guard_pass_b,
    guard_synthesis_resolution,
    is_account_synthesis_field,
    is_governed_synthesis_claim,
    is_synthesis_field,
    synthesis_claim_is_promotable,
)
from clue_research.synthesis.health import record_synthesis_health

__all__ = [
    # gating policy (the M11 synthesis invariants, as testable code)
    "SYNTHESIS_SOURCE_KEYS",
    "ACCOUNT_SYNTHESIS_CLASSES",
    "PASS_B_MODE",
    "SynthesisGateError",
    "is_synthesis_field",
    "is_account_synthesis_field",
    "is_governed_synthesis_claim",
    "synthesis_claim_is_promotable",
    "guard_account_only",
    "guard_pass_b",
    "guard_synthesis_resolution",
    "assert_pass_b_claim",
    # per-field verification-health surface (Doc C §6)
    "record_synthesis_health",
]
