"""M8A.5 — the references-only deep handoff skeleton, driven entirely by in-memory results (no DB).

These prove the *join* M12.2 consumes: each committee member keyed ``(contact_entity_id, persona)``
with ``role_on_committee`` and its facet ``profile_claims`` joined on by ``contact_entity_id``; a
member with no contact result kept partial (``profile_claims=()``); the coverage band carried so a
budget-capped account reads partial, not failed; and — the load-bearing regression — that the two
ids-only surfaces (``references_index`` and the ``manifest()`` payload) never leak a ``value_json``
even though the in-memory ``committee`` join carries the value-bearing views M12.2 reads.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from clue_api.deep import (
    AccountDeepResult,
    AccountHandoffSkeleton,
    DeepCompleteManifest,
    build_handoff_skeleton,
)
from clue_core import (
    EntityId,
    Persona,
    RunId,
    WorkerStatus,
    new_claim_id,
    new_entity_id,
    new_run_id,
)
from clue_core.enums import IdentityBinding, UseClass
from clue_core.handoff import ProfileClaimView
from clue_research.durable import AccountRunSubPhase
from clue_research.profiling import (
    AccountProfileResult,
    CommitteeResult,
    ContactProfileResult,
)
from clue_research.profiling.committee.coverage import (
    CommitteeCoverage,
    estimate_committee_coverage,
)
from clue_research.profiling.committee.results import CommitteeMemberRef
from clue_research.profiling.committee.stopping import CommitteeStopReason

# A distinctive marker planted in every contact claim body — if it appears in the ids-only
# ``references_index`` or the ``manifest()`` payload, a blob leaked (the regression these guard).
_LEAK_MARKER = "LEAKY_SECRET_VALUE_DO_NOT_SURFACE"

# --- fixtures ----------------------------------------------------------------


def _coverage(
    *,
    stopping: CommitteeStopReason = CommitteeStopReason.BUDGET_CAP,
    admitted: int = 2,
    candidates_seen: int = 4,
) -> CommitteeCoverage:
    """A coverage estimate that leaves ``linkedin`` unsearched (a partial, named-channel band)."""
    return estimate_committee_coverage(
        channels_searched=("crm",),
        all_channels=("crm", "linkedin"),
        stopping_reason=stopping,
        candidates_seen=candidates_seen,
        admitted=admitted,
    )


def _member(contact_id: EntityId, *, persona: Persona = Persona.CHAMPION) -> CommitteeMemberRef:
    return CommitteeMemberRef(
        contact_entity_id=contact_id,
        persona=persona,
        role_on_committee=persona.value,
        role_confidence=0.8,
        role_plausible=True,
        discovery_claim_id=new_claim_id(),
        role_claim_id=new_claim_id(),
        persona_claim_id=new_claim_id(),
    )


def _view(value: str) -> ProfileClaimView:
    return ProfileClaimView(
        claim_id=new_claim_id(),
        value_json=value,
        evidence_span=f"{_LEAK_MARKER}: {value}",
        source_tier=2,
        identity_binding=IdentityBinding.STRONG,
        use_class=UseClass.PROFESSIONAL_PUBLIC,
    )


def _contact(
    contact_id: EntityId, account_id: EntityId, *, n_claims: int = 2
) -> ContactProfileResult:
    return ContactProfileResult(
        contact_entity_id=contact_id,
        account_entity_id=account_id,
        profile_claims=tuple(_view(f"{_LEAK_MARKER}-{contact_id}-{i}") for i in range(n_claims)),
        cost_cents=Decimal("2"),
    )


def _account(account_id: EntityId, run_id: RunId, *, n_refs: int = 2) -> AccountProfileResult:
    return AccountProfileResult(
        account_entity_id=account_id,
        tier="top",
        run_id=run_id,
        status=WorkerStatus.OK,
        claim_refs=tuple(new_claim_id() for _ in range(n_refs)),
        cost_cents=Decimal("5"),
    )


def _committee(
    account_id: EntityId,
    members: tuple[CommitteeMemberRef, ...],
    coverage: CommitteeCoverage,
) -> CommitteeResult:
    return CommitteeResult(
        account_entity_id=account_id,
        members=members,
        coverage=coverage,
        cost_cents=Decimal("3"),
        admitted=len(members),
    )


def _result(
    *,
    entity_id: EntityId,
    run_id: RunId,
    account: AccountProfileResult | None = None,
    committee: CommitteeResult | None = None,
    contacts: tuple[ContactProfileResult, ...] = (),
    cost: Decimal = Decimal("10"),
) -> AccountDeepResult:
    return AccountDeepResult(
        account_run_id=run_id,
        entity_id=entity_id,
        tier="top",
        account=account,
        committee=committee,
        contacts=contacts,
        cost_cents=cost,
        sub_phase=AccountRunSubPhase.CONTACTS_COMPLETE,
    )


def _full_result() -> tuple[AccountDeepResult, tuple[EntityId, EntityId]]:
    """A fresh, complete two-member result: both members profiled. Returns the two contact ids."""
    account_id = new_entity_id()
    run_id = new_run_id()
    c1, c2 = new_entity_id(), new_entity_id()
    members = (_member(c1, persona=Persona.CHAMPION), _member(c2, persona=Persona.BLOCKER))
    committee = _committee(account_id, members, _coverage(admitted=2))
    contacts = (_contact(c1, account_id), _contact(c2, account_id))
    result = _result(
        entity_id=account_id,
        run_id=run_id,
        account=_account(account_id, run_id),
        committee=committee,
        contacts=contacts,
    )
    return result, (c1, c2)


# --- tests -------------------------------------------------------------------


def test_members_keyed_account_persona_with_joined_profile_claims() -> None:
    result, (c1, c2) = _full_result()
    skeleton = build_handoff_skeleton(result)

    assert skeleton.account_entity_id == result.entity_id
    assert skeleton.tier == "top"
    assert skeleton.account_run_id == result.account_run_id
    assert len(skeleton.committee) == 2

    by_id = {m.contact_entity_id: m for m in skeleton.committee}
    # each member keyed (contact_entity_id, persona) + role_on_committee
    assert by_id[c1].persona is Persona.CHAMPION
    assert by_id[c1].role_on_committee == Persona.CHAMPION.value
    assert by_id[c2].persona is Persona.BLOCKER
    # the JOIN: each contact's ProfileClaimViews land on its own member (by contact_entity_id)
    c1_views = result.contacts[0].profile_claims
    assert by_id[c1].profile_claims == c1_views
    assert by_id[c2].profile_claims == result.contacts[1].profile_claims
    # and they did not cross-contaminate
    assert by_id[c1].profile_claims != by_id[c2].profile_claims


def test_member_without_contact_result_keeps_empty_profile_claims() -> None:
    # three admitted members, but only the first two were contact-profiled (e.g. size cap).
    account_id = new_entity_id()
    run_id = new_run_id()
    c1, c2, c3 = new_entity_id(), new_entity_id(), new_entity_id()
    members = (_member(c1), _member(c2), _member(c3))
    committee = _committee(account_id, members, _coverage(admitted=3))
    contacts = (_contact(c1, account_id), _contact(c2, account_id))  # c3 NOT profiled
    result = _result(entity_id=account_id, run_id=run_id, committee=committee, contacts=contacts)

    skeleton = build_handoff_skeleton(result)
    by_id = {m.contact_entity_id: m for m in skeleton.committee}
    assert len(skeleton.committee) == 3  # all members present (the keyed shells)
    assert by_id[c1].profile_claims  # joined
    assert by_id[c2].profile_claims  # joined
    assert by_id[c3].profile_claims == ()  # partial — no contact result, a valid empty shell


def test_references_index_and_manifest_carry_no_value_json() -> None:
    result, _ = _full_result()
    skeleton = build_handoff_skeleton(result)

    # every references_index value is a tuple of claim ids (UUIDs) — never a body
    for section, ids in skeleton.references_index.items():
        assert all(isinstance(cid, UUID) for cid in ids), section

    # the ids-only surfaces must not contain the planted claim-body marker anywhere
    assert _LEAK_MARKER not in skeleton.references_index.__repr__()
    manifest = skeleton.manifest()
    assert _LEAK_MARKER not in manifest.model_dump_json()
    # the manifest is the references-only payload surface — no committee join with views on it
    assert isinstance(manifest, DeepCompleteManifest)
    assert manifest.committee_member_ids == tuple(m.contact_entity_id for m in skeleton.committee)


def test_committee_join_carries_value_json_m12_ready() -> None:
    # the positive counterpart: the in-memory committee join DOES carry the value-bearing views, so
    # M12.2 can JOIN profile_claims by contact_entity_id with no further M8A input.
    result, (c1, _) = _full_result()
    skeleton = build_handoff_skeleton(result)
    by_id = {m.contact_entity_id: m for m in skeleton.committee}
    joined_values = [v.value_json for v in by_id[c1].profile_claims]
    assert any(_LEAK_MARKER in str(v) for v in joined_values)
    # M12.2's JOIN key is recoverable without re-reading M8A: contact_entity_id on every member
    assert all(m.contact_entity_id is not None for m in skeleton.committee)


def test_references_index_sections_and_claim_refs() -> None:
    result, (c1, c2) = _full_result()
    skeleton = build_handoff_skeleton(result)

    assert skeleton.references_index["account"] == tuple(result.account.claim_refs)  # type: ignore[union-attr]
    assert skeleton.references_index["committee"] == tuple(result.committee.claim_refs)  # type: ignore[union-attr]
    assert skeleton.references_index[f"contact:{c1}"] == result.contacts[0].claim_refs
    assert skeleton.references_index[f"contact:{c2}"] == result.contacts[1].claim_refs

    # claim_refs flattens every section's ids (the union M12.2 reads bodies for)
    expected = (
        tuple(result.account.claim_refs)  # type: ignore[union-attr]
        + tuple(result.committee.claim_refs)  # type: ignore[union-attr]
        + result.contacts[0].claim_refs
        + result.contacts[1].claim_refs
    )
    assert set(skeleton.claim_refs) == set(expected)
    assert len(skeleton.claim_refs) == len(expected)  # no dupes lost/added


def test_coverage_carried_through_partial_not_failed() -> None:
    result, _ = _full_result()  # built with BUDGET_CAP stopping → a capped, partial committee
    skeleton = build_handoff_skeleton(result)

    assert skeleton.coverage is not None
    assert "linkedin" in skeleton.coverage.channels_not_searched  # the named unsearched channel
    assert skeleton.coverage.stopping_reason is CommitteeStopReason.BUDGET_CAP
    # carried onto the references-only manifest too
    assert skeleton.manifest().coverage is skeleton.coverage
    # cost carried through (a partial is still costed, never an error)
    assert skeleton.cost_cents == result.cost_cents


def test_empty_committee_is_partial_not_failed() -> None:
    account_id = new_entity_id()
    run_id = new_run_id()
    committee = _committee(
        account_id, (), _coverage(stopping=CommitteeStopReason.EXHAUSTED, admitted=0)
    )
    result = _result(
        entity_id=account_id,
        run_id=run_id,
        account=_account(account_id, run_id),
        committee=committee,
    )

    skeleton = build_handoff_skeleton(result)
    assert skeleton.committee == ()  # no members — a valid empty committee
    assert skeleton.coverage is not None  # still a coverage band, never a failure
    assert "account" in skeleton.references_index  # the account axis still folded
    assert skeleton.manifest().committee_member_ids == ()


def test_resumed_result_yields_a_partial_in_memory_skeleton() -> None:
    # a resumed run: account + committee were done in a PRIOR run (None in this result), only the
    # contacts ran now. The in-memory join reflects this run; the durable cross-run picture is the
    # persisted account_run.references_index + the claim store (M12.2's read).
    account_id = new_entity_id()
    run_id = new_run_id()
    c1 = new_entity_id()
    result = _result(
        entity_id=account_id,
        run_id=run_id,
        account=None,
        committee=None,
        contacts=(_contact(c1, account_id),),
    )

    skeleton = build_handoff_skeleton(result)
    assert skeleton.committee == ()  # no in-memory committee this run
    assert skeleton.coverage is None
    assert "account" not in skeleton.references_index
    assert "committee" not in skeleton.references_index
    assert skeleton.references_index[f"contact:{c1}"]  # this run's contact section is present
    # still no leak on the ids-only surfaces
    assert _LEAK_MARKER not in skeleton.manifest().model_dump_json()


def test_skeleton_computes_no_scores_narrative_or_provenance() -> None:
    # M8A.5 builds the keyed join only — fit/intent scores, the value narrative, and the provenance
    # index are M6/M12. The skeleton's shape must not carry them.
    result, _ = _full_result()
    skeleton = build_handoff_skeleton(result)
    fields = set(AccountHandoffSkeleton.model_fields)
    assert "fit_score" not in fields
    assert "intent_score" not in fields
    assert "value_narrative" not in fields
    assert "provenance_index" not in fields
    # sanity: the model is exactly the references-oriented shape
    assert fields == {
        "account_entity_id",
        "tier",
        "account_run_id",
        "committee",
        "committee_member_ids",
        "coverage",
        "cost_cents",
        "references_index",
    }
    _ = skeleton  # built without error
