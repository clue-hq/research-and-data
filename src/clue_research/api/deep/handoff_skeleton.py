"""The per-account handoff skeleton (M8A.5) — the references-only ``(account, persona)``-keyed join.

After the trunk (M8A.1) has profiled the account (M8.1/M8.2), discovered the committee (M8.3), and
contact-profiled each admitted member (M8.4), this folds that one run's :class:`AccountDeepResult`
into the references-only join M12.2 consumes: each committee :class:`~clue_research.core.handoff.
CommitteeMember` shell keyed ``(contact_entity_id, persona)`` with its facet ``profile_claims``
joined on by ``contact_entity_id``, plus a per-section claim-id index and the coverage band.

It is **not** the final :class:`~clue_research.core.handoff.AccountHandoff` — the fit/intent scores,
the value narrative, and the provenance index are M6/M12. M8A.5 only proves "this account is
M12-ready": the inputs exist and are correctly keyed (overview §3). It builds **no new table**
(D-D — the materialised handoff row, if any, is M12.2's call; the Postgres claim store is the sole
source of truth), and it surfaces **references, never blobs** (substrate §5b) on the two ids-only
surfaces — the :attr:`AccountHandoffSkeleton.references_index` and the
:meth:`AccountHandoffSkeleton.manifest` payload — so a budget-capped or marginal-yield-stopped
account reads as *partial, with a coverage band*, never as a FAILED handoff.

The one place ``value_json`` legitimately appears is the in-memory ``committee`` join — the
``core.handoff.CommitteeMember.profile_claims`` views M8.4 already produced and M12.2 reads. That is
the M12-ready structure, not a persisted/emitted surface: the ids-only ``references_index`` and the
``manifest()`` payload (what the M8A.2 ``DeepPhaseHandler`` returns in ``PhaseResult.payload``)
carry claim ids only, and the regression test asserts neither leaks a ``value_json``.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from clue_research.api.deep.orchestrator import AccountDeepResult
from clue_research.core import ClaimId, CommitteeMember, CostCents, EntityId, RunId
from clue_research.profiling.committee.coverage import CommitteeCoverage

# The ``references_index`` section keys (ids only). Account + resonance claims are folded together
# under ``account`` — ``AccountProfileResult.claim_refs`` does not separate the two axes (the M8A.1
# orchestrator persists them under one ``account`` key as well), so this view matches the trunk.
_ACCOUNT_SECTION = "account"
_COMMITTEE_SECTION = "committee"


def _contact_section(contact_entity_id: EntityId) -> str:
    return f"contact:{contact_entity_id}"


class DeepCompleteManifest(BaseModel):
    """The references-only per-account "deep-complete" manifest for the ``PhaseResult.payload``.

    What the M8A.2 ``DeepPhaseHandler`` emits per account: the run header, the admitted member
    contact-ids, the coverage band (named unsearched channels included), the run cost, and the
    per-section claim-id index — **claim ids only, never a ``value_json``** (the regression test
    asserts it). The full ``(account, persona)`` join with ``profile_claims`` stays on the in-memory
    :class:`AccountHandoffSkeleton`; M12.2 recomputes it on read from this index + the store."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_entity_id: EntityId
    account_run_id: RunId
    tier: str
    committee_member_ids: tuple[EntityId, ...] = ()
    coverage: CommitteeCoverage | None = None
    cost_cents: CostCents = Decimal(0)
    references_index: dict[str, tuple[ClaimId, ...]] = {}


class AccountHandoffSkeleton(BaseModel):
    """A references-oriented, ``(account, persona)``-keyed deep handoff skeleton (M8A.5).

    The upstream shell M12.2 fills: each :attr:`committee` member is keyed ``(contact_entity_id,
    persona)``, carries ``role_on_committee``, and has its facet ``profile_claims`` joined on by
    ``contact_entity_id`` — so M12.2 can JOIN ``profile_claims`` with no further M8A input. A member
    with no matching contact result (capped beyond ``committee_size_cap``, or not profiled this run)
    keeps ``profile_claims=()`` — a valid *partial*, never an error.

    :attr:`references_index` and the :meth:`manifest` payload are the **ids-only** surfaces (the
    references-not-blobs contract); only the in-memory :attr:`committee` join carries the
    ``value_json``-bearing views M12.2 consumes. :attr:`coverage` carries the band + the named
    unsearched channels, so a budget-/yield-stopped account reads partial, not failed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_entity_id: EntityId
    tier: str
    account_run_id: RunId
    committee: tuple[CommitteeMember, ...] = ()
    coverage: CommitteeCoverage | None = None
    cost_cents: CostCents = Decimal(0)
    # section -> claim ids: ``account`` (+ resonance), ``committee``, ``contact:<entity_id>``.
    references_index: dict[str, tuple[ClaimId, ...]] = {}

    @property
    def claim_refs(self) -> tuple[ClaimId, ...]:
        """Every section's claim ids, flattened (references only) — the union M12.2 reads."""
        return tuple(cid for ids in self.references_index.values() for cid in ids)

    def manifest(self) -> DeepCompleteManifest:
        """The references-only payload surface for the M8A.2 ``PhaseResult.payload`` (no body).

        Drops the in-memory ``committee`` join (its views carry ``value_json``) down to the admitted
        member contact-ids, keeping the coverage band, cost, and ids-only index — so the handler can
        fold it into the payload without leaking a claim body."""
        return DeepCompleteManifest(
            account_entity_id=self.account_entity_id,
            account_run_id=self.account_run_id,
            tier=self.tier,
            committee_member_ids=tuple(m.contact_entity_id for m in self.committee),
            coverage=self.coverage,
            cost_cents=self.cost_cents,
            references_index=self.references_index,
        )


def build_handoff_skeleton(result: AccountDeepResult) -> AccountHandoffSkeleton:
    """Fold one account's :class:`AccountDeepResult` into the references-only skeleton (M8A.5).

    Projects ``result.committee.committee()`` to ``(contact_entity_id, persona)``-keyed
    :class:`~clue_research.core.handoff.CommitteeMember` shells and JOINs each admitted member's
    ``ProfileClaimView``s onto its shell by ``contact_entity_id`` (a member with no contact result
    keeps ``profile_claims=()`` — a valid partial). Every written claim id is folded into
    ``references_index`` under the ``account`` / ``committee`` / ``contact:<id>`` sections (ids
    only), and the committee coverage band is carried so the account reads partial, not failed.

    Built from **this run's** in-memory result — on a fresh complete run that is the whole picture;
    on a resumed run (where a prior run's stages are ``None`` in the result) the join reflects only
    what this run produced, and the durable, cross-run source M12.2 reads is the persisted
    ``account_run.references_index`` + the claim store. It writes nothing, reads no DB, and computes
    no fit/intent score, ``value_narrative``, or ``provenance_index`` (those remain M6/M12)."""
    by_contact = {c.contact_entity_id: c for c in result.contacts}

    committee: tuple[CommitteeMember, ...] = ()
    coverage: CommitteeCoverage | None = None
    if result.committee is not None:
        coverage = result.committee.coverage
        committee = tuple(
            shell.model_copy(
                update={"profile_claims": by_contact[shell.contact_entity_id].profile_claims}
            )
            if shell.contact_entity_id in by_contact
            else shell
            for shell in result.committee.committee()
        )

    references_index: dict[str, tuple[ClaimId, ...]] = {}
    if result.account is not None and result.account.claim_refs:
        references_index[_ACCOUNT_SECTION] = tuple(result.account.claim_refs)
    if result.committee is not None and result.committee.claim_refs:
        references_index[_COMMITTEE_SECTION] = tuple(result.committee.claim_refs)
    # Iterate the de-duplicated ``by_contact`` view (one entry per ``contact_entity_id``) — the same
    # source the committee JOIN above uses — so the ``contact:<id>`` index and the committee
    # ``profile_claims`` can never disagree. ``discover_committee`` already guarantees unique member
    # ids upstream, so under normal orchestration this is exactly ``result.contacts``.
    for contact in by_contact.values():
        if contact.claim_refs:
            references_index[_contact_section(contact.contact_entity_id)] = tuple(
                contact.claim_refs
            )

    return AccountHandoffSkeleton(
        account_entity_id=result.entity_id,
        tier=result.tier,
        account_run_id=result.account_run_id,
        committee=committee,
        coverage=coverage,
        cost_cents=result.cost_cents,
        references_index=references_index,
    )
