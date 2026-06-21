"""`clue_research.discovery_scoring` — Discovery (mode M1) + Pass A Scoring (M6).

Package scaffolded by M0.1 (ENG-101); scope and the modular-boundary rules live
in this package's ``README.md``. Implemented by M6.

Beat-0 froze the cross-milestone seam in ``core`` (see ``docs/specs/_beat0-contract-freeze.md``):
M6's ``DISCOVERY``/``SCORING``/``TIER_CHECKPOINT`` phases *implement* ``PhaseHandler`` from
:mod:`clue_research.core.execution` (the checkpoint pauses via ``PhaseResult(status=PAUSED)``), the
Pass-A scorer returns ``core.Score``, and budget checks call the injected ``BudgetEngine``. Imported
accounts (M5) converge here through the claim store, not an import — M6 imports no sibling package.

Implemented so far:
* **M6.1 (ENG-128)** — Account Discovery (mode M1): :func:`discover` + the grounded
  :class:`DiscoveryChannel` seam, the *expand* orchestration, in-stream dedup, and the stopping
  rule. See :mod:`clue_research.discovery_scoring.discovery`.
* **M6.2 (ENG-133)** — Existence/identity gate + discovery-provenance: :func:`admit` (resolve →
  M2 disposition → discovery-provenance claim) and the integrated :class:`DiscoveryPhaseHandler`.
  See :mod:`clue_research.discovery_scoring.gate`.
"""

from __future__ import annotations

from clue_research.discovery_scoring.discovery import (
    DEFAULT_DISCOVERY_CONFIG,
    LOOKALIKE_CHANNEL,
    CandidateHypothesis,
    CandidateRecord,
    ChannelRegistry,
    ChannelYield,
    DiscoveryChannel,
    DiscoveryConfig,
    DiscoveryQuery,
    DiscoveryResult,
    DiscoveryStrategy,
    StoppingReason,
    discover,
)
from clue_research.discovery_scoring.gate import (
    AdmissionResult,
    AdmissionStatus,
    DefaultExistenceCheck,
    ExistenceCheck,
    ExistenceVerdict,
    admit,
)
from clue_research.discovery_scoring.phases import DiscoveryPhaseHandler

__all__ = [
    # M6.1 — discovery
    "discover",
    "DiscoveryResult",
    "ChannelYield",
    "CandidateHypothesis",
    "CandidateRecord",
    "DiscoveryChannel",
    "DiscoveryQuery",
    "ChannelRegistry",
    "DiscoveryStrategy",
    "DiscoveryConfig",
    "DEFAULT_DISCOVERY_CONFIG",
    "StoppingReason",
    "LOOKALIKE_CHANNEL",
    # M6.2 — existence/identity gate
    "admit",
    "AdmissionResult",
    "AdmissionStatus",
    "ExistenceCheck",
    "ExistenceVerdict",
    "DefaultExistenceCheck",
    # M6 phase handlers
    "DiscoveryPhaseHandler",
]
