"""Existence/identity gate + discovery-provenance (M6.2 / ENG-133).

The anti-fabrication spine of the discovery axis (staged-flow §3/§8). A discovered candidate is a
*hypothesis, not an account*: before admission it must resolve to a real canonical
``account_entity`` through the M2 identity service. A hallucinated entity has nothing to resolve
to and **dies here,
before a cent of profiling spend**. Survivors become ``account_entity`` rows carrying a
*discovery-provenance* claim (where found, why it matched, how confident), so admission itself is
auditable. This is the one gate every candidate — discovered (Scenario A) or imported (Scenario B,
``matched_channel='import'``) — passes through; it is the convergence contract the Pass-A bridge
(M6.3) reads.

Public seam:
* :func:`admit` — ``(conn, candidate, run_id) -> AdmissionResult`` (admitted / needs_review /
  rejected); idempotent + lockable.
* :class:`AdmissionResult` / :class:`AdmissionStatus`.
* :class:`ExistenceCheck` — the pluggable liveness seam (default: a candidate exists iff it carries
  a resolvable identity; a real live-domain/DNS check is a future provider).
"""

from __future__ import annotations

from clue_research.discovery_scoring.gate.admission import (
    DISCOVERY_PROVENANCE_FIELD,
    admit,
    ensure_discovery_provenance,
    membership_channel,
)
from clue_research.discovery_scoring.gate.existence import (
    DEFAULT_EXISTENCE_CHECK,
    DefaultExistenceCheck,
    ExistenceCheck,
    ExistenceVerdict,
)
from clue_research.discovery_scoring.gate.results import AdmissionResult, AdmissionStatus

__all__ = [
    "admit",
    "ensure_discovery_provenance",
    "membership_channel",
    "AdmissionResult",
    "AdmissionStatus",
    "ExistenceCheck",
    "ExistenceVerdict",
    "DefaultExistenceCheck",
    "DEFAULT_EXISTENCE_CHECK",
    "DISCOVERY_PROVENANCE_FIELD",
]
