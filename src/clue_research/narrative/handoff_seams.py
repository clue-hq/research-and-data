"""The injected committee seam the M12.2 handoff assembler consumes (M12 ↔ M8/M10).

The assembler is a *worker* (import-linter independence contract), so — exactly like the M12.1
positioner — it may not import the sibling packages that own the buying committee (``profiling`` /
M8) or the appropriateness/use gate (``compliance`` / M10). The committee, its governed
contact claims, and the M10 ``use_decision`` per personal hook therefore reach the assembler via an
**injected seam** whose production implementation is built at the ``api`` composition root (it may
import all of them) and injected.

This is a *richer* seam than M12.1's :class:`~clue_research.narrative.seams.CommitteeReader` (which
returns only the use-cleared facet hooks the positioner gates its *prompt* on): the handoff's
``committee[]`` carries each member's **full** ``profile_claims`` (role, persona, and facets) as
:class:`~clue_core.handoff.ProfileClaimView`\\s — each with ``identity_binding`` +
``use_class`` (Doc D §7), so the content layer can see why a hook is or isn't usable. So the seam
returns the handoff-shaped :class:`~clue_core.handoff.CommitteeMember`, paired with
the per-claim :class:`~clue_core.compliance.UseDecision` the assembler needs to mark the
outreach-eligible set (``is_outreach_promotable`` — Doc D / M10; PF-1).

The production reader can reuse the M8A.5 ``build_handoff_skeleton`` (which already JOINs M8.3's
committee with M8.4's contact ``profile_claims``) for ``member`` and call M10's ``UseGate`` / read
the ``use_decision`` side table per facet claim for ``use_decisions`` — but that wiring lands at
``api`` when M8/M10 integrate (deferred-injection, like the M9.4 binding classifier). The
in-memory fake here lets M12.2 build and test against fixtures with zero sibling imports.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from clue_core import ClaimId, CommitteeMember, EntityId, UseDecision


class HandoffCommitteeMember(BaseModel):
    """One buying-committee member as the handoff assembler consumes it: the handoff-shaped
    :class:`CommitteeMember` (identity + persona + role + the full ``profile_claims``) plus the M10
    appropriateness/use verdict for each **governed facet** claim among those profile claims.

    ``use_decisions`` is keyed by the facet claim's id and present **only** for ``contact.facet.*``
    claims the M10 use-gate evaluated; an identifying claim (``contact.role_on_committee`` /
    ``contact.persona``) has no entry (not an outreach hook, so it is never gate-filtered). The
    assembler keeps a governed facet in the outreach-eligible committee only if it clears
    ``is_outreach_promotable`` (strong identity-binding AND ``usable_for_outreach``); a weak-binding
    or use-disallowed facet is dropped before the handoff (M12.2 AC4)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    member: CommitteeMember
    use_decisions: dict[ClaimId, UseDecision] = {}


@runtime_checkable
class HandoffCommitteeReader(Protocol):
    """Read the buying committee for an account in the handoff shape (the M12.2 ↔ M8/M10 seam).

    Returns one :class:`HandoffCommitteeMember` per resolved committee member — its
    :class:`CommitteeMember` (with full ``profile_claims``) and the per-governed-facet
    :class:`UseDecision`. Tenant-scoped on ``tenant_id`` (a committee assessment and its personal
    hooks are ``TENANT_PRIVATE``). The production impl (``profiling`` committee/contact results ×
    ``compliance`` ``use_decision``) is injected at the ``api`` root."""

    async def committee_for_handoff(
        self, *, account_entity_id: EntityId, tenant_id: str
    ) -> tuple[HandoffCommitteeMember, ...]: ...


class InMemoryHandoffCommitteeReader:
    """A fixture :class:`HandoffCommitteeReader` backed by a plain ``{account_entity_id: (members,
    ...)}`` map — for M12.2 tests and local runs before the real reader is wired at ``api``."""

    def __init__(
        self, committees: dict[EntityId, tuple[HandoffCommitteeMember, ...]] | None = None
    ) -> None:
        self._committees = committees or {}

    async def committee_for_handoff(
        self, *, account_entity_id: EntityId, tenant_id: str
    ) -> tuple[HandoffCommitteeMember, ...]:
        return self._committees.get(account_entity_id, ())
