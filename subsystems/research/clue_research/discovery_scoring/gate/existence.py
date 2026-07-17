"""The existence check — the pluggable liveness seam of the gate (M6.2 / ENG-133).

Discovery admission requires real-world existence, not just a syntactically valid candidate
(staged-flow §3: "live-domain check + at least one corroborating record"). This is the swappable
seam for that check, analogous to ``Resolver`` / ``DiscoveryChannel``: production binds a real
live-domain / DNS / corroboration provider; the default is a cheap deterministic proxy.

The default treats a candidate as existing iff it carries a **resolvable identity** — a registrable
domain (the strong key) or a non-empty name — because such a candidate already came from a *grounded
channel record* (M6.1's structural invariant), so the record is its corroboration. A candidate with
neither a domain nor a name has *nothing to resolve to* (the prototype's fabricated-account shape)
and is rejected before any spend. A stricter live-domain check is a drop-in replacement here.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from clue_research.discovery_scoring.discovery import CandidateHypothesis
from clue_research.identity import registrable_domain


class ExistenceVerdict(BaseModel):
    """Whether a candidate is judged to exist, plus the reason (surfaced on a rejection)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    exists: bool
    reason: str = ""


@runtime_checkable
class ExistenceCheck(Protocol):
    """The pluggable existence/liveness check. Async because a real implementation does IO (DNS, a
    live-domain HEAD, a corroborating-record lookup); the default is pure."""

    async def check(self, candidate: CandidateHypothesis) -> ExistenceVerdict: ...


class DefaultExistenceCheck:
    """The deterministic default: a candidate exists iff it has a registrable domain or a non-empty
    name (a resolvable identity). Grounding (M6.1) already guarantees it came from a real record, so
    this is the cheap proxy for "live domain + corroborating record"; swap in a real DNS check by
    binding a different :class:`ExistenceCheck`."""

    async def check(self, candidate: CandidateHypothesis) -> ExistenceVerdict:
        if candidate.candidate_domain and registrable_domain(candidate.candidate_domain):
            return ExistenceVerdict(exists=True, reason="registrable domain")
        if candidate.raw_name and candidate.raw_name.strip():
            return ExistenceVerdict(exists=True, reason="resolvable name")
        return ExistenceVerdict(
            exists=False,
            reason="no registrable domain or resolvable name — nothing to resolve to",
        )


DEFAULT_EXISTENCE_CHECK = DefaultExistenceCheck()


__all__ = ["ExistenceVerdict", "ExistenceCheck", "DefaultExistenceCheck", "DEFAULT_EXISTENCE_CHECK"]
