"""M8D R11.5 — the governed committee, bridged to M8D fleet coverage.

The gap (``[LaneE×R11/C7]`` HB-1): ``ContactEligibilityResolver`` read its claim references from
``account_run.references_index``, whose only production writer is the R1-quarantined M8A/C
orchestrator.  Every real M8D run therefore resolved an *empty* committee — C7/FI-2 served ``[]``,
Lane E's value narrative refused ``committee_unavailable``, and HANDOFF assembled nobody — while the
M8D fleet had durably recorded that same committee in ``entity_research_account_coverage``
(``claim_refs`` + ``committee_member_ids``) all along.

These tests pin the bridge at the **claim-reference source**, which is the only place it exists:

* the M8D fixture writes **zero** ``account_run`` rows, so a passing committee read here can only
  have come from coverage (each scenario asserts that explicitly);
* everything below the source is the shared, untouched governance — product-exact filtering, the
  strong-binding membership rule, contact liveness, survivor redirects, ``latest_use_decisions``,
  and the deterministic sort — so the M8D scenarios below assert *governed* results, not raw joins;
* the legacy shape (references index, no fleet run) keeps resolving exactly as it did, which is what
  lets the pre-existing C7.6 suite (``tests/api/test_c7_handoff_cutover.py``) pass unchanged.

The fleet/launch fixtures are F1's (``tests.api.test_r11_deep_phase_bridge``) and the claim/
use-decision mechanics mirror the C7.6 suite, so nothing here invents a second fixture vocabulary.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.account_research_fleet import AccountResearchFleetPolicy
from clue_api.contact_eligibility import (
    AccountRunReferenceIndexSource,
    Arv2CommitteeReferenceSource,
    ChainedClaimReferenceSource,
    ContactEligibilityResolver,
    EntityResearchCoverageReferenceSource,
    build_contact_eligibility_resolver,
    build_governed_committee_view_reader,
    build_production_handoff_committee_reader,
)
from clue_core import (
    AccountStatus,
    Claim,
    ClaimId,
    EntityId,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    Persona,
    ProjectRunId,
    ResearchMode,
    ResearchSubjectRef,
    ResearchViewReadRequest,
    RunId,
    SourceTier,
    UseClass,
    VerificationStatus,
    contact_claim,
    new_run_id,
)
from clue_fleet import EntityResearchRunEnvelope
from clue_research.claimstore import WorkspaceScope, claims_by_ids, insert_claim
from clue_research.durable import AccountRunStatus, insert_account_run, save_references
from clue_research.identity import (
    insert_account_entity,
    insert_contact_entity,
    mark_merged,
    stamp_reuse,
)
from clue_research.profiling.committee import (
    CURRENT_TITLE,
    PERSONA,
    ROLE_ON_COMMITTEE,
    load_committee_pack,
    write_committee_claim,
)
from clue_research.profiling.fields import FACET_NICKNAME
from clue_spine import create_product, get_project
from tests.api.test_r11_deep_phase_bridge import (
    _age,
    _envelope,
    _Scope,
    _seed_scope,
    _service,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")


# --- harness ------------------------------------------------------------------------------------


def _factory(conn: AsyncConnection) -> Callable[[], AbstractAsyncContextManager[AsyncConnection]]:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncConnection]:
        yield conn

    return factory


async def _scope(conn: AsyncConnection) -> _Scope:
    """F1's seeded project run, plus the real ``product`` row a product-stamped claim needs.

    ``claim_product_workspace_fk`` pins ``(product_id, workspace_id)`` to a product, so the fleet's
    product id has to exist as a row before any committee claim can carry it. Materializing it
    under the project's own brand keeps one product across the fleet run, the claims, and the
    resolver — the same identity production has.
    """

    scope = await _seed_scope(conn)
    project = await get_project(conn, scope.project_id)
    assert project is not None
    await create_product(
        conn,
        workspace_id=scope.workspace_id,
        brand_id=project.brand_id,
        product_id=scope.product_id,
        name=f"R11 product {uuid4().hex[:6]}",
    )
    return scope


async def _launch_for(
    conn: AsyncConnection,
    scope: _Scope,
    accounts: Sequence[EntityId],
) -> EntityResearchRunEnvelope:
    """F1's launch with the fleet's job subjects pinned to real account entities.

    The bridge itself joins coverage to an account by ``account_entity_id`` and never looks at a
    job's subject, but a fixture whose fleet researched accounts that do not exist would be a
    fiction — and one that could hide a future join.  ``insert_account_entity`` mints its own id, so
    the pinning goes the other way: build F1's envelope, then substitute the real ids into the
    selection and every job authorization before launching.
    """

    base = _envelope(scope, accounts=len(accounts))
    subjects = tuple(
        subject.model_copy(update={"subject_entity_id": UUID(str(entity_id))})
        for subject, entity_id in zip(base.lifecycle.selection.subjects, accounts, strict=True)
    )
    selection = base.lifecycle.selection.model_copy(update={"subjects": subjects})
    envelope = base.model_copy(
        update={
            "lifecycle": base.lifecycle.model_copy(update={"selection": selection}),
            "jobs": tuple(
                job.model_copy(
                    update={
                        "authorization": job.authorization.model_copy(
                            update={
                                "subject_entity_id": UUID(str(entity_id)),
                                "selection": selection,
                            }
                        )
                    }
                )
                for job, entity_id in zip(base.jobs, accounts, strict=True)
            ),
        }
    )
    await _service(conn).launch(
        envelope,
        # Every job is a canary, so nothing is held and the canary health gate never colours a
        # scenario that is about reading output, not about admission.
        policy=AccountResearchFleetPolicy(canary_size=len(accounts)),
        actor="user:owner",
        source_operation_id=envelope.lifecycle.run_id,
        source_action_ref=f"agent-action:launch-account-research:{uuid4()}",
    )
    return envelope


async def _coverage(
    conn: AsyncConnection,
    envelope: EntityResearchRunEnvelope,
    *,
    job_index: int = 0,
    account_entity_id: EntityId,
    workspace_id: str,
    claims: Sequence[Claim] = (),
    members: Sequence[EntityId] = (),
    committee_status: str = "complete",
    sequence: int = 0,
) -> UUID:
    """Write the coverage row the R5 finalization compiler writes for one account job.

    Inserted as SQL rather than driven through ``AccountEntityResearchService`` deliberately: the
    production writer only runs at the end of a full agent-driven job, and this suite is about what
    a *reader* does with the row.  The column list, the ``claim:<uuid>`` reference shape, and the
    account-axis field keys are copied from that writer
    (``account_entity_research.py``) so the fixture cannot drift into a shape production never
    produces.

    ``sequence`` stamps ``created_at`` minutes apart.  Postgres freezes ``now()`` inside the test
    transaction and the coverage table is append-only (its trigger refuses the backdating UPDATE
    F1 uses on fleet rows), so a test that writes a *second* row for one account has to say at
    insert time which one is later — otherwise the reader's latest-wins tiebreak falls to a random
    ``coverage_id``.
    """

    coverage_id = uuid4()
    payload: dict[str, JsonValue] = {
        "coverage_id": str(coverage_id),
        "committee_status": committee_status,
        "committee_member_ids": [str(member) for member in members],
        "claim_refs": [f"claim:{claim.id}" for claim in claims],
    }
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_account_coverage
                (coverage_id, research_run_id, job_id, workspace_id, account_entity_id,
                 result_refs, completed_field_keys, unresolved_field_keys, unresolved_reasons,
                 committee_result_refs, committee_member_ids, committee_status, review_flags,
                 claim_refs, evidence_refs, coverage_json, coverage_sha256, created_at)
            VALUES
                (:coverage_id, :run_id, :job_id, :workspace_id, :account_id,
                 :result_refs, :completed, :unresolved, :reasons,
                 :committee_refs, :member_ids, :committee_status, :review_flags,
                 :claim_refs, :evidence_refs, CAST(:coverage_json AS jsonb), :sha,
                 now() + make_interval(mins => :sequence))
            """
        ),
        {
            "coverage_id": coverage_id,
            "run_id": envelope.lifecycle.run_id,
            "job_id": envelope.jobs[job_index].authorization.job_id,
            "workspace_id": workspace_id,
            "account_id": UUID(str(account_entity_id)),
            "result_refs": [],
            "completed": ["account.operational_pain"],
            "unresolved": [],
            "reasons": [],
            "committee_refs": [],
            "member_ids": [UUID(str(member)) for member in members],
            "committee_status": committee_status,
            "review_flags": [],
            "claim_refs": [f"claim:{claim.id}" for claim in claims],
            "evidence_refs": [],
            "coverage_json": json.dumps(payload, sort_keys=True),
            "sequence": sequence,
            "sha": hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        },
    )
    return coverage_id


async def _contact(
    conn: AsyncConnection,
    account: EntityId,
    *,
    name: str,
) -> EntityId:
    return await insert_contact_entity(
        conn,
        account_entity_id=account,
        full_name=name,
        linkedin_url=f"https://linkedin.com/in/{uuid4().hex[:12]}",
        status=AccountStatus.ACTIVE,
    )


async def _claim(
    conn: AsyncConnection,
    *,
    contact: EntityId,
    field_key: str,
    value: JsonValue,
    workspace_id: str,
    product_id: str,
    run_id: RunId,
    binding: IdentityBinding = IdentityBinding.STRONG,
    use_class: UseClass = UseClass.PROFESSIONAL_PUBLIC,
) -> Claim:
    """One product-stamped contact claim — the C7.6 suite's mechanics, verbatim."""

    claim = stamp_reuse(
        contact_claim(
            entity_id=contact,
            field_key=field_key,
            value_json=value,
            source_tier=1,
            extraction_method=ExtractionMethod.HUMAN,
            confidence=1.0,
            run_id=run_id,
            research_mode=ResearchMode.COMMITTEE_DISCOVERY,
            identity_binding=binding,
            use_class=use_class,
            evidence_span=f"evidence for {field_key}",
        ),
        workspace_id=workspace_id,
    ).model_copy(
        update={
            "product_id": product_id,
            "verification_status": (
                VerificationStatus.VERIFIED
                if binding is IdentityBinding.STRONG
                else VerificationStatus.UNVERIFIED
            ),
        }
    )
    await insert_claim(conn, claim)
    return claim


async def _member_claims(
    conn: AsyncConnection,
    *,
    contact: EntityId,
    workspace_id: str,
    product_id: str,
    run_id: RunId,
    persona: Persona = Persona.ECONOMIC_BUYER,
    binding: IdentityBinding = IdentityBinding.STRONG,
    facet_allowed: bool | None = True,
) -> tuple[Claim, ...]:
    """A member's role + persona + title + nickname facet, and the facet's use decision."""

    role = await _claim(
        conn,
        contact=contact,
        field_key=ROLE_ON_COMMITTEE,
        value={
            "role": persona.value,
            "confidence": 1.0,
            "plausible": True,
            "rationale": "named on the buying committee",
        },
        workspace_id=workspace_id,
        product_id=product_id,
        run_id=run_id,
        binding=binding,
    )
    persona_claim = await _claim(
        conn,
        contact=contact,
        field_key=PERSONA,
        value=persona.value,
        workspace_id=workspace_id,
        product_id=product_id,
        run_id=run_id,
        binding=binding,
    )
    title = await _claim(
        conn,
        contact=contact,
        field_key=CURRENT_TITLE,
        value="VP of Operations",
        workspace_id=workspace_id,
        product_id=product_id,
        run_id=run_id,
        binding=binding,
    )
    facet = await _claim(
        conn,
        contact=contact,
        field_key=FACET_NICKNAME,
        value="Jay",
        workspace_id=workspace_id,
        product_id=product_id,
        run_id=run_id,
        binding=binding,
        use_class=UseClass.PERSONAL_PUBLIC_NON_SENSITIVE,
    )
    if facet_allowed is not None:
        await conn.execute(
            text(
                """
                INSERT INTO use_decision
                    (claim_id, usable_for_outreach, reason, regime, policy_version)
                VALUES (:claim_id, :allowed, CAST(:reason AS use_reason), 'gdpr', 1)
                """
            ),
            {
                "claim_id": str(facet.id),
                "allowed": facet_allowed,
                "reason": ("allowed" if facet_allowed else "use_class_disallowed_for_regime"),
            },
        )
    return role, persona_claim, title, facet


@dataclass(frozen=True)
class _M8D:
    """One project run whose committee exists only in M8D coverage."""

    scope: _Scope
    envelope: EntityResearchRunEnvelope
    account: EntityId
    run_id: RunId
    members: tuple[EntityId, ...]
    claims: tuple[Claim, ...]


async def _account_runs(conn: AsyncConnection) -> int:
    return int((await conn.execute(text("SELECT count(*) FROM account_run"))).scalar_one())


async def _seed_m8d(
    conn: AsyncConnection,
    *,
    personas: tuple[Persona, ...] = (Persona.ECONOMIC_BUYER, Persona.TECHNICAL_EVALUATOR),
    facet_allowed: bool | None = True,
) -> _M8D:
    """A project run + fleet run + account + one contact per persona, joined only by coverage."""

    await load_committee_pack(conn)
    scope = await _scope(conn)
    account = await insert_account_entity(
        conn,
        canonical_name=f"R11 Target {uuid4().hex[:6]}",
        primary_domain=f"{uuid4().hex[:10]}.example",
        status=AccountStatus.ACTIVE,
        workspace_id=scope.workspace_id,
    )
    envelope = await _launch_for(conn, scope, (account,))
    run_id = new_run_id()
    members: list[EntityId] = []
    claims: list[Claim] = []
    for persona in personas:
        contact = await _contact(conn, account, name=f"{persona.value.title()} Person")
        members.append(contact)
        claims.extend(
            await _member_claims(
                conn,
                contact=contact,
                workspace_id=scope.workspace_id,
                product_id=scope.product_id,
                run_id=run_id,
                persona=persona,
                facet_allowed=facet_allowed,
            )
        )
    await _coverage(
        conn,
        envelope,
        account_entity_id=account,
        workspace_id=scope.workspace_id,
        claims=claims,
        members=members,
    )
    return _M8D(
        scope=scope,
        envelope=envelope,
        account=account,
        run_id=run_id,
        members=tuple(members),
        claims=tuple(claims),
    )


def _resolver(
    conn: AsyncConnection, fixture: _M8D, *, product_id: str | None = None
) -> ContactEligibilityResolver:
    """This suite's subject is the M8D **coverage** source, so it is injected explicitly.

    2026-09-09 — until ARV2 R3 Task 7 this was the *default* chain, and reading it through the
    default was the same thing. It no longer is: ``Arv2CommitteeReferenceSource`` now leads the
    default chain and would answer for every account below (their members hold live
    ``contact.persona`` claims), which would leave the coverage source — the thing these scenarios
    exist to prove — untested. The chain order itself is proven by
    ``test_the_default_chain_answers_from_arv2_before_the_coverage_row``.
    """

    return _legacy_resolver(
        conn,
        project_run_id=fixture.scope.project_run_id,
        product_id=fixture.scope.product_id if product_id is None else product_id,
    )


def _legacy_resolver(
    conn: AsyncConnection, *, project_run_id: ProjectRunId, product_id: str | None
) -> ContactEligibilityResolver:
    """The pre-ARV2 chain — M8D coverage, then the references index — and nothing in front of it."""

    return ContactEligibilityResolver(
        project_run_id=project_run_id,
        product_id=product_id,
        conn_factory=_factory(conn),
        claim_reference_source=ChainedClaimReferenceSource(
            (EntityResearchCoverageReferenceSource(), AccountRunReferenceIndexSource())
        ),
    )


# --- AC9: the headline ---------------------------------------------------------------------------


def test_the_governed_committee_resolves_out_of_m8d_coverage() -> None:
    """AC9: coverage-sourced references produce the governed committee, with zero references index.

    Both readers Lane E and M12 build over the resolver are asserted at the level Lane E's probe
    actually uses (``committee_for``), because that probe — not the resolver — is what refused
    ``committee_unavailable`` on every live run.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_m8d(conn, facet_allowed=False)
            # The fixture's only membership record is the coverage row: no account run exists, so
            # the legacy source has nothing to answer with even if it were consulted.
            assert await _account_runs(conn) == 0

            resolver = _resolver(conn, fixture)
            governed = await resolver.resolve_account(
                account_entity_id=fixture.account,
                workspace_id=fixture.scope.workspace_id,
            )
            # Sorted by persona then contact id, so the fixture's seeding order is the read order.
            assert [item.contact_entity_id for item in governed] == list(fixture.members)
            assert [item.persona for item in governed] == [
                Persona.ECONOMIC_BUYER,
                Persona.TECHNICAL_EVALUATOR,
            ]
            # Governance is exercised, not bypassed: the denied hook still displays but can never
            # personalize, exactly as it does on the legacy source.
            for member in governed:
                facets = [
                    item
                    for item in member.claims
                    if str(item.claim.field_key).startswith("contact.facet.")
                ]
                assert [item.display_eligible for item in facets] == [True]
                assert [item.personalization_eligible for item in facets] == [False]
                assert CURRENT_TITLE in {str(item.claim.field_key) for item in member.claims}

            # Lane E's probe shape: a non-empty committee here is the whole point of R11.5.
            reader = build_production_handoff_committee_reader(resolver)
            committee = await reader.committee_for(
                account_entity_id=fixture.account,
                workspace_id=fixture.scope.workspace_id,
            )
            assert {item.contact_entity_id for item in committee} == set(fixture.members)
            handoff = await reader.committee_for_handoff(
                account_entity_id=fixture.account,
                workspace_id=fixture.scope.workspace_id,
            )
            assert {item.member.contact_entity_id for item in handoff} == set(fixture.members)
            assert all(item.member.profile_claims for item in handoff)

    run_async(scenario())


@pytest.mark.parametrize("verification_enabled", ["true", "false"])
def test_the_bridged_committee_is_identical_in_both_verification_toggle_states(
    verification_enabled: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R11 §1a: the bridge is a pure reference read — no gateway, no judge, no toggle branch.

    The toggle only relaxes the merge's verified-tier-4 gate, and committee membership is
    deterministic tier-1 evidence, so flipping it must not move a single member or claim.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            monkeypatch.setenv("CLUE_VERIFICATION_ENABLED", verification_enabled)
            fixture = await _seed_m8d(conn)
            governed = await _resolver(conn, fixture).resolve_account(
                account_entity_id=fixture.account,
                workspace_id=fixture.scope.workspace_id,
            )
            assert [item.contact_entity_id for item in governed] == list(fixture.members)
            assert [
                sorted(str(claim.claim.field_key) for claim in item.claims) for item in governed
            ] == [sorted({str(claim.field_key) for claim in fixture.claims})] * len(fixture.members)

    run_async(scenario())


def test_the_contact_detail_read_follows_the_same_bridged_decision() -> None:
    """``resolve_contact`` delegates to ``resolve_account``, so it is bridged by construction — the
    contact detail surface cannot disagree with the committee list about who is on it."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_m8d(conn)
            resolver = _resolver(conn, fixture)
            resolved = await resolver.resolve_contact(
                contact_entity_id=fixture.members[0],
                account_entity_id=fixture.account,
                workspace_id=fixture.scope.workspace_id,
            )
            assert resolved is not None
            assert resolved.contact_entity_id == fixture.members[0]

    run_async(scenario())


# --- member scoping ------------------------------------------------------------------------------


def test_a_referenced_contact_who_is_not_a_committee_member_is_excluded() -> None:
    """``claim_refs`` is the run's whole claim bag; ``committee_member_ids`` is the committee.

    A contact the run profiled without seating on the committee must not become a member just
    because their claims are in the same reference bag.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_m8d(conn, personas=(Persona.ECONOMIC_BUYER,))
            bystander = await _contact(conn, fixture.account, name="Bystander Person")
            extra = await _member_claims(
                conn,
                contact=bystander,
                workspace_id=fixture.scope.workspace_id,
                product_id=fixture.scope.product_id,
                run_id=fixture.run_id,
                persona=Persona.CHAMPION,
            )
            # A second coverage row (latest wins) carrying BOTH contacts' claims but only the
            # original member — the exact shape the scoping rule exists for.
            await _coverage(
                conn,
                fixture.envelope,
                account_entity_id=fixture.account,
                workspace_id=fixture.scope.workspace_id,
                claims=(*fixture.claims, *extra),
                members=fixture.members,
                sequence=1,
            )

            governed = await _resolver(conn, fixture).resolve_account(
                account_entity_id=fixture.account,
                workspace_id=fixture.scope.workspace_id,
            )
            assert [item.contact_entity_id for item in governed] == list(fixture.members)
            assert bystander not in {item.contact_entity_id for item in governed}

    run_async(scenario())


def test_a_committee_member_merged_into_a_survivor_still_resolves() -> None:
    """Identity canonicalization re-keys claims; the member list is re-keyed the same way.

    The member id the run recorded is the loser, so scoping on the raw id would drop a member the
    resolver otherwise resolves perfectly — which is why the member ids go through the same
    ``surviving_ids`` redirect as the claims.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_m8d(conn, personas=(Persona.ECONOMIC_BUYER,))
            loser = fixture.members[0]
            survivor = await _contact(conn, fixture.account, name="Canonical Person")
            await mark_merged(conn, EntityType.CONTACT, loser, survivor)

            governed = await _resolver(conn, fixture).resolve_account(
                account_entity_id=fixture.account,
                workspace_id=fixture.scope.workspace_id,
            )
            assert [item.contact_entity_id for item in governed] == [survivor]

    run_async(scenario())


# --- the honest empty committee -------------------------------------------------------------------


def test_an_account_the_producing_fleet_run_never_covered_resolves_empty() -> None:
    """A run that published coverage is the authority for every account in its selection.

    The second account here has a fully populated legacy ``references_index``, so the assertion is
    specifically that the bridge does NOT fall through to a source the M8D run supersedes: an
    account this run did not research has an empty committee, not last era's one.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_m8d(conn, personas=(Persona.ECONOMIC_BUYER,))
            other = await insert_account_entity(
                conn,
                canonical_name=f"Uncovered {uuid4().hex[:6]}",
                primary_domain=f"{uuid4().hex[:10]}.example",
                status=AccountStatus.ACTIVE,
                workspace_id=fixture.scope.workspace_id,
            )
            contact = await _contact(conn, other, name="Legacy Member")
            legacy = await _member_claims(
                conn,
                contact=contact,
                workspace_id=fixture.scope.workspace_id,
                product_id=fixture.scope.product_id,
                run_id=fixture.run_id,
            )
            account_run = new_run_id()
            await insert_account_run(
                conn,
                account_run_id=account_run,
                project_run_id=fixture.scope.project_run_id,
                entity_id=other,
                tier="top",
            )
            await save_references(
                conn,
                account_run,
                references_index={"committee": [str(claim.id) for claim in legacy]},
                cost_cents=Decimal(0),
                status=AccountRunStatus.DONE,
            )

            resolver = _resolver(conn, fixture)
            assert (
                await resolver.resolve_account(
                    account_entity_id=other,
                    workspace_id=fixture.scope.workspace_id,
                )
                == ()
            )
            # The covered account in the same run still resolves, so the emptiness above is about
            # this account's coverage, not about the source being broken.
            assert (
                await resolver.resolve_account(
                    account_entity_id=fixture.account,
                    workspace_id=fixture.scope.workspace_id,
                )
                != ()
            )

    run_async(scenario())


def test_a_covered_account_with_no_resolved_members_resolves_empty() -> None:
    """Lane E's honest refusal survives: research that seated nobody still starves the narrative."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_m8d(conn, personas=(Persona.ECONOMIC_BUYER,))
            await _coverage(
                conn,
                fixture.envelope,
                account_entity_id=fixture.account,
                workspace_id=fixture.scope.workspace_id,
                claims=fixture.claims,
                members=(),
                committee_status="needs_review",
                sequence=1,
            )
            resolver = _resolver(conn, fixture)
            assert (
                await resolver.resolve_account(
                    account_entity_id=fixture.account,
                    workspace_id=fixture.scope.workspace_id,
                )
                == ()
            )
            assert (
                await build_production_handoff_committee_reader(resolver).committee_for(
                    account_entity_id=fixture.account,
                    workspace_id=fixture.scope.workspace_id,
                )
                == ()
            )

    run_async(scenario())


def test_only_the_latest_fleet_run_describes_the_committee() -> None:
    """R11 §6c latest-wins, applied to the committee: a relaunch supersedes the earlier run's
    coverage rather than unioning with it."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_m8d(conn, personas=(Persona.ECONOMIC_BUYER,))
            # Postgres freezes ``now()`` inside the test transaction, so age the first launch to
            # reproduce two launches made minutes apart in production.
            await _age(conn, fixture.envelope)
            relaunch = await _launch_for(conn, fixture.scope, (fixture.account,))
            second = await _contact(conn, fixture.account, name="Second Pass Person")
            second_claims = await _member_claims(
                conn,
                contact=second,
                workspace_id=fixture.scope.workspace_id,
                product_id=fixture.scope.product_id,
                run_id=fixture.run_id,
                persona=Persona.CHAMPION,
            )
            await _coverage(
                conn,
                relaunch,
                account_entity_id=fixture.account,
                workspace_id=fixture.scope.workspace_id,
                claims=second_claims,
                members=(second,),
            )

            governed = await _resolver(conn, fixture).resolve_account(
                account_entity_id=fixture.account,
                workspace_id=fixture.scope.workspace_id,
            )
            assert [item.contact_entity_id for item in governed] == [second]

    run_async(scenario())


# --- governance on the bridged source ---------------------------------------------------------


def test_a_product_mismatched_claim_never_enters_another_products_committee() -> None:
    """The product-exact filter is shared, so the bridge cannot widen it: coverage references are
    still only admitted for the product the reader asked for."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_m8d(conn, personas=(Persona.ECONOMIC_BUYER,))
            assert (
                await _resolver(conn, fixture, product_id="prd-somewhere-else").resolve_account(
                    account_entity_id=fixture.account,
                    workspace_id=fixture.scope.workspace_id,
                )
                == ()
            )

    run_async(scenario())


def test_a_weakly_bound_member_is_excluded_from_the_bridged_committee() -> None:
    """Membership is identity-bearing on both sources: a weak role/persona binding cannot establish
    that this canonical person holds the product's committee seat."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_m8d(conn, personas=(Persona.ECONOMIC_BUYER,))
            weak = await _contact(conn, fixture.account, name="Weak Person")
            weak_claims = await _member_claims(
                conn,
                contact=weak,
                workspace_id=fixture.scope.workspace_id,
                product_id=fixture.scope.product_id,
                run_id=fixture.run_id,
                persona=Persona.CHAMPION,
                binding=IdentityBinding.WEAK,
            )
            await _coverage(
                conn,
                fixture.envelope,
                account_entity_id=fixture.account,
                workspace_id=fixture.scope.workspace_id,
                claims=(*fixture.claims, *weak_claims),
                members=(*fixture.members, weak),
                sequence=1,
            )

            governed = await _resolver(conn, fixture).resolve_account(
                account_entity_id=fixture.account,
                workspace_id=fixture.scope.workspace_id,
            )
            assert [item.contact_entity_id for item in governed] == list(fixture.members)

    run_async(scenario())


def test_an_allowed_use_decision_is_what_makes_a_hook_personalizable() -> None:
    """The complement of the AC9 denial case, so the exclusion there is the decision's doing rather
    than the bridge silently dropping every facet."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_m8d(conn, personas=(Persona.ECONOMIC_BUYER,))
            governed = await _resolver(conn, fixture).resolve_account(
                account_entity_id=fixture.account,
                workspace_id=fixture.scope.workspace_id,
            )
            assert len(governed) == 1
            assert [str(item.claim.field_key) for item in governed[0].personalization_claims] == [
                FACET_NICKNAME
            ]

    run_async(scenario())


# --- the legacy source, unchanged -------------------------------------------------------------


def test_a_project_run_with_no_fleet_run_still_reads_the_references_index() -> None:
    """The legacy path, byte-identical — this is the shape every historical/seeded run has, and the
    reason the pre-existing C7.6 suite passes untouched."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await load_committee_pack(conn)
            scope = await _scope(conn)
            account = await insert_account_entity(
                conn,
                canonical_name=f"Legacy Target {uuid4().hex[:6]}",
                primary_domain=f"{uuid4().hex[:10]}.example",
                status=AccountStatus.ACTIVE,
                workspace_id=scope.workspace_id,
            )
            contact = await _contact(conn, account, name="Legacy Buyer")
            run_id = new_run_id()
            claims = await _member_claims(
                conn,
                contact=contact,
                workspace_id=scope.workspace_id,
                product_id=scope.product_id,
                run_id=run_id,
            )
            account_run = new_run_id()
            await insert_account_run(
                conn,
                account_run_id=account_run,
                project_run_id=scope.project_run_id,
                entity_id=account,
                tier="top",
            )
            await save_references(
                conn,
                account_run,
                references_index={"committee": [str(claim.id) for claim in claims]},
                cost_cents=Decimal(0),
                status=AccountRunStatus.DONE,
            )

            # 2026-09-09 — read through the legacy chain explicitly: the ARV2 source now leads
            # the default chain and would answer for this account, so the default no longer
            # exercises the references index this test is about.
            governed = await _legacy_resolver(
                conn, project_run_id=scope.project_run_id, product_id=scope.product_id
            ).resolve_account(account_entity_id=account, workspace_id=scope.workspace_id)
            assert [item.contact_entity_id for item in governed] == [contact]

    run_async(scenario())


def test_a_fleet_run_that_has_published_no_coverage_leaves_the_legacy_source_in_charge() -> None:
    """A launched-but-silent run has not yet spoken about a single account.

    Treating it as the authority would blank a committee an earlier completed pass legitimately
    resolved, purely because a new run was launched. Applicability therefore requires published
    output; once the run has any coverage row, the previous test's supersession rule takes over.
    (This is also the shape Lane E's E3 acceptance fixture has: a real fleet run finalized without
    the R5 coverage compiler, alongside a durable references index.)
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await load_committee_pack(conn)
            scope = await _scope(conn)
            account = await insert_account_entity(
                conn,
                canonical_name=f"Hybrid Target {uuid4().hex[:6]}",
                primary_domain=f"{uuid4().hex[:10]}.example",
                status=AccountStatus.ACTIVE,
                workspace_id=scope.workspace_id,
            )
            await _launch_for(conn, scope, (account,))
            contact = await _contact(conn, account, name="Prior Pass Buyer")
            claims = await _member_claims(
                conn,
                contact=contact,
                workspace_id=scope.workspace_id,
                product_id=scope.product_id,
                run_id=new_run_id(),
            )
            account_run = new_run_id()
            await insert_account_run(
                conn,
                account_run_id=account_run,
                project_run_id=scope.project_run_id,
                entity_id=account,
                tier="top",
            )
            await save_references(
                conn,
                account_run,
                references_index={"committee": [str(claim.id) for claim in claims]},
                cost_cents=Decimal(0),
                status=AccountRunStatus.DONE,
            )

            # 2026-09-09 — read through the legacy chain explicitly: the ARV2 source now leads
            # the default chain and would answer for this account, so the default no longer
            # exercises the references index this test is about.
            governed = await _legacy_resolver(
                conn, project_run_id=scope.project_run_id, product_id=scope.product_id
            ).resolve_account(account_entity_id=account, workspace_id=scope.workspace_id)
            assert [item.contact_entity_id for item in governed] == [contact]

    run_async(scenario())


# --- AC10: the read layer over real M8D output ------------------------------------------------


def test_the_c7_committee_section_populates_from_m8d_output() -> None:
    """AC10: the governed committee view reader — the read layer's committee section — over a
    live-shaped M8D fixture. Before R11.5 this returned zero references on this shape."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_m8d(conn)
            reader = build_governed_committee_view_reader(_resolver(conn, fixture))
            seed = await reader.read_committee(
                ResearchViewReadRequest(
                    workspace_id=fixture.scope.workspace_id,
                    project_id=fixture.scope.project_id,
                    project_run_id=fixture.scope.project_run_id,
                    subject_entity_id=fixture.account,
                    product_id=fixture.scope.product_id,
                ),
                ResearchSubjectRef(
                    entity_id=fixture.account,
                    entity_type=EntityType.ACCOUNT,
                    canonical_entity_version=1,
                ),
            )
            assert {reference.subject.entity_id for reference in seed.references} == set(
                fixture.members
            )
            assert all(
                reference.product_id == fixture.scope.product_id for reference in seed.references
            )
            evidence: set[ClaimId] = {
                claim_id
                for reference in seed.references
                for claim_id in reference.evidence_claim_ids
            }
            assert evidence <= {claim.id for claim in fixture.claims}
            assert evidence

    run_async(scenario())


def test_the_contact_subject_read_of_the_c7_section_is_bridged_too() -> None:
    """The contact-detail arm of the same reader goes through ``resolve_contact``, so it inherits
    the bridge without a second source decision."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_m8d(conn, personas=(Persona.ECONOMIC_BUYER,))
            reader = build_governed_committee_view_reader(_resolver(conn, fixture))
            seed = await reader.read_committee(
                ResearchViewReadRequest(
                    workspace_id=fixture.scope.workspace_id,
                    project_id=fixture.scope.project_id,
                    project_run_id=fixture.scope.project_run_id,
                    subject_entity_id=fixture.members[0],
                    product_id=fixture.scope.product_id,
                ),
                ResearchSubjectRef(
                    entity_id=fixture.members[0],
                    entity_type=EntityType.CONTACT,
                    canonical_entity_version=1,
                    parent_account_id=fixture.account,
                ),
            )
            assert [reference.subject.entity_id for reference in seed.references] == [
                fixture.members[0]
            ]

    run_async(scenario())


# --- Slice D / D4: honest role provenance keeps display continuity ------------------------------


async def _agent_inferred_role_pair(
    conn: AsyncConnection,
    *,
    contact: EntityId,
    workspace_id: str,
    product_id: str,
    run_id: RunId,
    persona: Persona,
    title: str,
) -> tuple[Claim, Claim]:
    """The role/persona pair exactly as D3's ``record_committee_role_inferences`` writes it.

    Written through the committee package's own ``write_committee_claim`` — the production writer
    the D3 tool calls — rather than through this file's ``_claim`` helper, because the whole point
    of D4 is that the *post-D1* shape serves: LLM_SYNTHESIS / tier 4 / PLATFORM_INFERRED, grounded
    in a real URL + the member's own title span, and born UNVERIFIED. Stamping it by hand would
    prove only that a fixture can be shaped to pass. ``write_committee_claim`` returns ids, so the
    rows are read back to hand the coverage fixture the ``Claim`` objects it builds refs from.
    """

    source_url = f"https://{uuid4().hex[:10]}.example/team"
    evidence_span = f"title: {title}"
    role_claim_id = await write_committee_claim(
        conn,
        contact,
        ROLE_ON_COMMITTEE,
        {
            "role": persona.value,
            "confidence": 0.87,
            "plausible": True,
            "rationale": "the operations leader owns the workflow this product changes",
        },
        confidence=0.87,
        method=ExtractionMethod.LLM_SYNTHESIS,
        tier=SourceTier(4),
        source_url=source_url,
        evidence_span=evidence_span,
        run_id=run_id,
        workspace_id=workspace_id,
        identity_binding=IdentityBinding.STRONG,
        product_id=product_id,
    )
    persona_claim_id = await write_committee_claim(
        conn,
        contact,
        PERSONA,
        persona.value,
        confidence=0.87,
        method=ExtractionMethod.LLM_SYNTHESIS,
        tier=SourceTier(4),
        source_url=source_url,
        evidence_span=evidence_span,
        run_id=run_id,
        workspace_id=workspace_id,
        identity_binding=IdentityBinding.STRONG,
        product_id=product_id,
    )
    written = await claims_by_ids(
        conn,
        (role_claim_id, persona_claim_id),
        scope=WorkspaceScope.for_workspace(workspace_id),
    )
    return written[role_claim_id], written[persona_claim_id]


@dataclass(frozen=True)
class _AgentInferred:
    """One coverage row holding both post-D3 member shapes: role-inferred, and honestly roleless."""

    fixture: _M8D
    coverage_id: UUID
    inferred: EntityId
    roleless: EntityId
    role_claim: Claim
    persona_claim: Claim


async def _seed_agent_inferred(conn: AsyncConnection) -> _AgentInferred:
    """One account whose committee is the post-D3 world: one member the account agent gave a role,
    one member nobody could ground a role for (the D2 ``agent_deferred`` intermediate state, or a
    member the D3 batch simply omitted — D3 never fills an omitted member)."""

    await load_committee_pack(conn)
    scope = await _scope(conn)
    account = await insert_account_entity(
        conn,
        canonical_name=f"D4 Target {uuid4().hex[:6]}",
        primary_domain=f"{uuid4().hex[:10]}.example",
        status=AccountStatus.ACTIVE,
        workspace_id=scope.workspace_id,
    )
    envelope = await _launch_for(conn, scope, (account,))
    run_id = new_run_id()

    inferred = await _contact(conn, account, name="Agent Inferred Person")
    inferred_title = await _claim(
        conn,
        contact=inferred,
        field_key=CURRENT_TITLE,
        value="VP of Operations",
        workspace_id=scope.workspace_id,
        product_id=scope.product_id,
        run_id=run_id,
    )
    role_claim, persona_claim = await _agent_inferred_role_pair(
        conn,
        contact=inferred,
        workspace_id=scope.workspace_id,
        product_id=scope.product_id,
        run_id=run_id,
        persona=Persona.ECONOMIC_BUYER,
        title="VP of Operations",
    )

    roleless = await _contact(conn, account, name="Roleless Person")
    roleless_title = await _claim(
        conn,
        contact=roleless,
        field_key=CURRENT_TITLE,
        value="Director of Finance",
        workspace_id=scope.workspace_id,
        product_id=scope.product_id,
        run_id=run_id,
    )

    claims = (inferred_title, role_claim, persona_claim, roleless_title)
    members = (inferred, roleless)
    coverage_id = await _coverage(
        conn,
        envelope,
        account_entity_id=account,
        workspace_id=scope.workspace_id,
        claims=claims,
        members=members,
        committee_status="needs_review",
    )
    return _AgentInferred(
        fixture=_M8D(
            scope=scope,
            envelope=envelope,
            account=account,
            run_id=run_id,
            members=members,
            claims=claims,
        ),
        coverage_id=coverage_id,
        inferred=inferred,
        roleless=roleless,
        role_claim=role_claim,
        persona_claim=persona_claim,
    )


async def _persisted_member_ids(conn: AsyncConnection, coverage_id: UUID) -> list[EntityId]:
    row = (
        await conn.execute(
            text(
                "SELECT committee_member_ids FROM entity_research_account_coverage "
                "WHERE coverage_id=:coverage_id"
            ),
            {"coverage_id": coverage_id},
        )
    ).scalar_one()
    return [EntityId(UUID(str(value))) for value in row]


def test_an_agent_inferred_member_serves_exactly_like_a_worker_inferred_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D4: the honest post-D1/D3 role provenance did not cost the contacts read a single member.

    Every other scenario in this file writes the *pre-D1* role shape (tier-1 HUMAN), which is the
    provenance D1 retired: an LLM's role judgment stamped as a human-asserted fact. D3 replaced it
    with an agent-derived claim — LLM_SYNTHESIS, tier 4, PLATFORM_INFERRED, born UNVERIFIED. This
    pins that the eligibility resolver's ``_resolve_contact_claims`` admits that shape by the same
    route it admitted the old one (STRONG-bound role *and* persona, ``plausible`` not false,
    ``role == persona``), which is why the ``role_claim_id``/``persona_claim_id`` identity check
    below matters: it proves the seat came from the agent-written pair and not from some other row.

    The second half is the contract's other half — a member with no grounded role is *not*
    eligibility-committee material, but is still a discovered person. The coverage row keeps them
    in ``committee_member_ids`` (the frontend contacts list reads members; their role simply renders
    empty), so an honest refusal to guess a role never erases the person.

    Toggle pinned to the pilot posture explicitly: the workspace ``.env`` runs the
    ``integration_pilot`` overlay (verification disabled), and this test must state that dependence
    rather than inherit it.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            monkeypatch.setenv("CLUE_VERIFICATION_ENABLED", "false")
            seeded = await _seed_agent_inferred(conn)
            # Coverage is again the only membership record — no legacy references index exists.
            assert await _account_runs(conn) == 0

            governed = await _resolver(conn, seeded.fixture).resolve_account(
                account_entity_id=seeded.fixture.account,
                workspace_id=seeded.fixture.scope.workspace_id,
            )
            assert [item.contact_entity_id for item in governed] == [seeded.inferred]
            member = governed[0]
            assert member.persona is Persona.ECONOMIC_BUYER
            assert member.role_on_committee == Persona.ECONOMIC_BUYER.value
            # The seat is the agent's pair, not an incidental row that happened to merge.
            assert member.role_claim_id == seeded.role_claim.id
            assert member.persona_claim_id == seeded.persona_claim.id
            assert seeded.role_claim.extraction_method is ExtractionMethod.LLM_SYNTHESIS
            assert seeded.role_claim.source_tier == 4
            assert seeded.role_claim.verification_status is not VerificationStatus.VERIFIED
            # The member's discovery-era professional facts ride along unchanged.
            assert CURRENT_TITLE in {str(item.claim.field_key) for item in member.claims}

            # The roleless member is not eligibility-committee material …
            assert seeded.roleless not in {item.contact_entity_id for item in governed}
            # … but is still a discovered person the contacts list must show.
            assert await _persisted_member_ids(conn, seeded.coverage_id) == [
                seeded.inferred,
                seeded.roleless,
            ]

    run_async(scenario())


def test_a_verification_enabled_deployment_withholds_the_unjudged_agent_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Continuity, not regression: with verification ENABLED the merge's verified-tier-4 gate
    withholds the born-UNVERIFIED agent pair, so the member does not take a committee seat until
    the M9.3 judge verifies it.

    This is exact parity with a *worker*-written role after D1 — that pair is tier-4 UNVERIFIED at
    birth too — so the toggle branch is a property of honest agent provenance, not of D3's tool.
    The pre-D1 tier-1 HUMAN shape is what used to sail through both states (which is precisely the
    false-provenance D1 retired); the sibling test above pins the pilot posture that serves these
    roles today.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            monkeypatch.setenv("CLUE_VERIFICATION_ENABLED", "true")
            seeded = await _seed_agent_inferred(conn)
            governed = await _resolver(conn, seeded.fixture).resolve_account(
                account_entity_id=seeded.fixture.account,
                workspace_id=seeded.fixture.scope.workspace_id,
            )
            assert governed == ()
            # Withheld from the seat, never erased from discovery: both members stay visible.
            assert await _persisted_member_ids(conn, seeded.coverage_id) == [
                seeded.inferred,
                seeded.roleless,
            ]

    run_async(scenario())


# --- ARV2 R3 Task 7: the ARV2 committee source leads the chain -----------------------------------
#
# 2026-09-09, founder ruling "ARV2's own rows are the only truth": committee membership is now read
# from the claim store — a contact under the account holding a live ``contact.persona`` claim — and
# ``Arv2CommitteeReferenceSource`` sits FIRST in ``default_claim_reference_source()``. Every
# scenario above still proves the *coverage* source itself, which ``_resolver`` now injects
# explicitly rather than reaching it through a chain the ARV2 source leads; the three tests below
# prove the new leader and the chain order.


async def _seated(
    conn: AsyncConnection,
    scope: _Scope,
    account: EntityId,
    *,
    name: str,
    persona: Persona = Persona.ECONOMIC_BUYER,
) -> tuple[EntityId, tuple[Claim, ...]]:
    """One contact seated the way R3's committee step seats one: persona + role, on the contact."""

    contact = await _contact(conn, account, name=name)
    claims = await _member_claims(
        conn,
        contact=contact,
        workspace_id=scope.workspace_id,
        product_id=scope.product_id,
        run_id=new_run_id(),
        persona=persona,
    )
    return contact, claims


async def _bare_account(conn: AsyncConnection, scope: _Scope) -> EntityId:
    return await insert_account_entity(
        conn,
        canonical_name=f"ARV2 Target {uuid4().hex[:6]}",
        primary_domain=f"{uuid4().hex[:10]}.example",
        status=AccountStatus.ACTIVE,
        workspace_id=scope.workspace_id,
    )


def test_the_arv2_source_reads_the_committee_off_live_persona_and_role_claims() -> None:
    """No fleet run, no coverage row, no ``account_run`` — the claims alone are the committee."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await load_committee_pack(conn)
            scope = await _scope(conn)
            account = await _bare_account(conn, scope)
            seated, claims = await _seated(conn, scope, account, name="Seated Person")
            unseated = await _contact(conn, account, name="Unseated Person")
            title = await _claim(
                conn,
                contact=unseated,
                field_key=CURRENT_TITLE,
                value="Head of RevOps",
                workspace_id=scope.workspace_id,
                product_id=scope.product_id,
                run_id=new_run_id(),
            )

            references = await Arv2CommitteeReferenceSource().read(
                conn,
                project_run_id=scope.project_run_id,
                account_entity_id=account,
                workspace_id=scope.workspace_id,
            )
            assert references is not None
            assert references.committee_member_ids == (seated,)
            assert {claim.id for claim in claims} <= set(references.claim_ids)
            # A contact with claims but no persona claim is not on the committee, and none of
            # their claims ride along on somebody else's membership.
            assert title.id not in references.claim_ids
            assert await _account_runs(conn) == 0

    run_async(scenario())


def test_the_arv2_source_does_not_apply_when_no_contact_holds_a_persona_claim() -> None:
    """``None`` means "not my account" — which is what leaves the legacy sources in charge."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await load_committee_pack(conn)
            scope = await _scope(conn)
            account = await _bare_account(conn, scope)
            unseated = await _contact(conn, account, name="Unseated Person")
            await _claim(
                conn,
                contact=unseated,
                field_key=CURRENT_TITLE,
                value="Head of RevOps",
                workspace_id=scope.workspace_id,
                product_id=scope.product_id,
                run_id=new_run_id(),
            )

            assert (
                await Arv2CommitteeReferenceSource().read(
                    conn,
                    project_run_id=scope.project_run_id,
                    account_entity_id=account,
                    workspace_id=scope.workspace_id,
                )
                is None
            )

    run_async(scenario())


def test_the_default_chain_answers_from_arv2_before_the_coverage_row() -> None:
    """Both sources apply; ARV2 wins. The bystander is seated in the claim store and absent from
    the coverage row's ``committee_member_ids``, so serving them can only be the ARV2 answer."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _seed_m8d(conn, personas=(Persona.ECONOMIC_BUYER,))
            bystander, _ = await _seated(
                conn,
                fixture.scope,
                fixture.account,
                name="Bystander Person",
                persona=Persona.CHAMPION,
            )
            governed = await build_contact_eligibility_resolver(
                project_run_id=fixture.scope.project_run_id,
                product_id=fixture.scope.product_id,
                conn_factory=_factory(conn),
            ).resolve_account(
                account_entity_id=fixture.account,
                workspace_id=fixture.scope.workspace_id,
            )
            assert {item.contact_entity_id for item in governed} == {*fixture.members, bystander}

    run_async(scenario())
