"""Account Discovery (mode M1) — grounded-only candidate generation (M6.1 / ENG-128).

The wide, recall-optimized front edge of the pipeline: turn a confirmed ICP spec's *discovery
strategy* into a stream of **candidate hypotheses** — companies that *might* fit, sourced **only**
from real records returned by grounded channels, never invented by an LLM (staged-flow §3/§8; the
exact failure mode the prototype shipped). The orchestrator fans queries across the planned channels
(the *expand* pattern), dedupes in-stream, and stops on a marginal-yield drop or a discovery budget
cap. Admission to the store is the existence/identity gate's job (M6.2); this module only proposes.

Public seam (the contract M6.2's gate consumes):
* :func:`discover` — ``(spec, run_id, channels, gateway, config) -> DiscoveryResult`` (the candidate
  stream + per-channel yield counters + a ``stopping_reason``).
* :class:`CandidateHypothesis` — a proposed account, explicitly **not** an ``account_entity`` until
  M6.2 admits it; cannot exist without a grounding ``source_record_ref``/``source_url``.
* :class:`DiscoveryChannel` — the swappable, grounded provider seam (source-keyed, config-selected);
  a channel returns real records only. M6 owns this seam (the M4 ``Resolver`` protocol is
  enrichment-shaped — ``resolve(entity, field)`` — and structurally cannot *produce* new entities).
* :class:`DiscoveryStrategy` — the typed view of the opaque ``ICPSpec.discovery_strategy`` slot.
"""

from __future__ import annotations

from clue_research.discovery_scoring.discovery.channels import (
    ChannelRegistry,
    DiscoveryChannel,
    DiscoveryQuery,
)
from clue_research.discovery_scoring.discovery.hypothesis import (
    CandidateHypothesis,
    CandidateRecord,
)
from clue_research.discovery_scoring.discovery.orchestrator import (
    ChannelYield,
    DiscoveryResult,
    discover,
)
from clue_research.discovery_scoring.discovery.stopping import StoppingReason
from clue_research.discovery_scoring.discovery.strategy import (
    DEFAULT_DISCOVERY_CONFIG,
    LOOKALIKE_CHANNEL,
    DiscoveryConfig,
    DiscoveryStrategy,
    DiscoveryStrategyError,
)

__all__ = [
    "discover",
    "DiscoveryResult",
    "ChannelYield",
    "CandidateHypothesis",
    "CandidateRecord",
    "DiscoveryChannel",
    "DiscoveryQuery",
    "ChannelRegistry",
    "DiscoveryStrategy",
    "DiscoveryStrategyError",
    "DiscoveryConfig",
    "DEFAULT_DISCOVERY_CONFIG",
    "StoppingReason",
    "LOOKALIKE_CHANNEL",
]
