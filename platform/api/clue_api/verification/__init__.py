"""``clue_api.verification`` — the ``ProjectPhase.VERIFICATION`` composition root.

The live call site that drives the frozen ``VERIFICATION_GATE_ORDER`` (corroboration →
faithfulness → use-gate last) over the deep-produced claims, then records per-field
verification-health. See
:mod:`clue_api.verification.handler`. Wired + registered at the api root, mirroring
:mod:`clue_api.deep`.
"""

from __future__ import annotations

from clue_api.verification.composition import (
    build_verification_phase_handler,
    register_verification_phase_handler,
)
from clue_api.verification.handler import (
    ClaimCorroborator,
    ClaimLoader,
    ContactResolver,
    UseGateProvider,
    VerificationAccountResolver,
    VerificationPhaseHandler,
)

__all__ = [
    "VerificationPhaseHandler",
    "VerificationAccountResolver",
    "ClaimLoader",
    "ClaimCorroborator",
    "ContactResolver",
    "UseGateProvider",
    "build_verification_phase_handler",
    "register_verification_phase_handler",
]
