"""The committee people-source seam (M8.3) — enumerate candidate people for one account.

Committee discovery (mode M3) is *bounded discovery*: it must **enumerate** the people at a known
account, then resolve each through the M2 identity gate (staged-flow §6). The M4
:class:`~clue_core.resolver.Resolver` is the wrong shape for this — it *fills a field for a
known entity* (``resolve(entity, field) -> claims``); it structurally cannot produce new entities.
M6 owns a `DiscoveryChannel` for the account axis, but that lives in ``discovery_scoring`` and M8
may not import a sibling milestone (the independence contract). So M8.3 defines its own minimal,
M8-owned candidate-enumeration seam here — the contact-axis analogue of M6's channel, one level
down — and keeps the core ``Resolver`` protocol untouched (it is frozen during the parallel build).

A :class:`CommitteeSource` is a thin provider (Apollo/ZoomInfo people, the account's own
team/leadership page, public-activity signals) bound at the ``api`` composition root and selected /
ordered via the M4 Source Planner there. Until those providers exist, no source is bound and
:func:`discover_committee` returns an empty committee — a *correct* output, never a fabricated one.

**Anti-fabrication is structural** (the M3 existence-gate discipline, staged-flow §8): a
:class:`CommitteePersonCandidate` cannot be constructed without being grounded in *something real* —
a strong key (LinkedIn URL / verified email) or a source URL. The LLM may *plan* which sources to
query; it never *mints* a candidate. A candidate with a strong key is admissible; one without is
dropped at the gate (it has nothing to resolve to).
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, JsonValue, model_validator

from clue_core import AccountEntity, Confidence, CostCents


class CommitteePersonCandidate(BaseModel):
    """One candidate person found at an account — the input the existence gate resolves.

    Grounded by construction: at least one of ``linkedin_url`` / ``verified_email`` / ``source_url``
    must be present, so a record cannot be a pure fabrication (mirrors M6's ``CandidateRecord``).
    Only a candidate carrying a **strong key** survives the existence gate; the rest are dropped.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_key: str  # the producing committee source (provider stays behind this key)
    linkedin_url: str | None = None  # contact strong key
    verified_email: str | None = None  # contact strong key
    full_name: str | None = None
    title: str | None = None  # job title — the role-inference + plausibility input
    geo: dict[str, JsonValue] | None = None
    source_url: str | None = None  # where the person was found (the grounding / discovery channel)
    matched_signal: str = ""  # why this person is relevant (e.g. "VP Eng on the leadership page")
    source_person_id: str | None = None  # provider provenance key; never a strong identity key
    job_function: str | None = None
    job_level: str | None = None
    team_names: tuple[str, ...] = ()
    relationship_labels: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    discovery_confidence: Confidence = 0.5
    cost_cents: CostCents = Decimal(0)

    @model_validator(mode="after")
    def _check_grounded(self) -> CommitteePersonCandidate:
        if not (self.linkedin_url or self.verified_email or self.source_url):
            raise ValueError(
                "a committee candidate must be grounded in a strong key (linkedin_url / "
                "verified_email) or a source_url — the LLM plans queries, it never mints a person "
                "(M3 existence-gate discipline, staged-flow §8)"
            )
        return self

    @property
    def has_strong_key(self) -> bool:
        """Whether the candidate carries a resolvable strong key (the existence-gate precondition).

        A normalized non-empty LinkedIn URL or verified email — the only keys the M2 contact
        resolver matches deterministically. No strong key ⇒ nothing to resolve to ⇒ dropped.
        """
        return bool((self.linkedin_url or "").strip() or (self.verified_email or "").strip())


@runtime_checkable
class CommitteeSource(Protocol):
    """A bound provider that enumerates candidate people for one account (M8.3).

    The committee-axis analogue of M6's ``DiscoveryChannel``: ``source_key`` keys the provider in
    the registry (the provider's name stays hidden, like a resolver), ``tier`` is its trust tier,
    and ``find_candidates`` returns grounded candidates for the account. Swapping Apollo→ZoomInfo is
    a binding change behind this seam — invisible to :func:`discover_committee`."""

    source_key: str
    tier: int

    async def find_candidates(
        self, account: AccountEntity, *, limit: int
    ) -> Sequence[CommitteePersonCandidate]: ...


def order_committee_sources(
    sources: Sequence[CommitteeSource], plan: Sequence[str] | None = None
) -> list[CommitteeSource]:
    """Order the bound sources for consultation.

    When ``plan`` (the M4 Source Planner's ordered ``source_key``s, computed at the ``api`` root)
    is given, sources are consulted in that order — planner-chosen sources first, in plan order,
    then any remaining bound source in trust-tier order. With no plan, sources are ordered by
    trust tier (lowest/most-trusted first), matching the waterfall discipline. This is the one
    place consultation order is decided, so the worker never re-derives it."""
    by_key = {s.source_key: s for s in sources}
    ordered: list[CommitteeSource] = []
    seen: set[str] = set()
    for key in plan or ():
        source = by_key.get(key)
        if source is not None and key not in seen:
            ordered.append(source)
            seen.add(key)
    for source in sorted(sources, key=lambda s: s.tier):
        if source.source_key not in seen:
            ordered.append(source)
            seen.add(source.source_key)
    return ordered
