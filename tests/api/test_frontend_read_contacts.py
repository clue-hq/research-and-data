"""FI-2 slice 1, Task 4 — the contacts union (`GET /frontend/v1/accounts/{id}/contacts[/{cid}]`).

Same harness as the accounts-list and account-detail suites: the real projections app driven
in-process through ``httpx.ASGITransport`` on the test's rolled-back connection, so the endpoints
read exactly the rows the test seeded and nothing commits.

The fixture is the slice-0 canonical shape — **two projects over one workspace, one shared
account** — with the committee shapes this endpoint's rules turn on:

* a member referenced by **both** projects' account runs (must appear ONCE carrying both
  ``projectIds``);
* a member referenced by only one (one ``projectId``);
* a member whose role/persona binding is **WEAK** (the governed reader drops them entirely — they
  are not a 404-able contact either, because they are not on any committee);
* a member holding a **display-denied** professional fact (a special-category title) and a
  **weakly-bound** one (which the merge itself excludes) — the two honest absences, only one of
  which is `restricted`;
* facets across the three interesting classes: a display-eligible signal, a use-class-denied
  signal, and a display-eligible facet that is **not** a signal family.

Every read is workspace-scoped: this suite shares a database with suites that commit.

**Live-data note (not a fixture accident).** ``ContactEligibilityResolver.resolve_account`` reads
``account_run.references_index``, whose only production writer is behind the M8D R1 quarantine, so
on real data every committee is empty until the R11 bridge lands. The empty-committee test below is
therefore the *production* case today, and the populated ones are the post-R11 contract.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from httpx import ASGITransport
from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.frontend_read import FRONTEND_READ_PREFIX
from clue_api.projections_app import create_projections_app
from clue_config import load_settings
from clue_core import (
    AccountStatus,
    Confidence,
    EntityId,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    Persona,
    ProjectRunId,
    ResearchMode,
    RunId,
    UseClass,
    VerificationStatus,
    contact_claim,
    new_project_run_id,
    new_run_id,
)
from clue_research.claimstore import insert_claim, load_core_pack
from clue_research.durable import (
    AccountRunStatus,
    ensure_project_run,
    insert_account_run,
    save_references,
)
from clue_research.identity import (
    insert_account_entity,
    insert_contact_entity,
    mark_merged,
    stamp_reuse,
)
from clue_research.membership import ensure_project_account
from clue_research.profiling.committee import PERSONA, ROLE_ON_COMMITTEE, load_committee_pack
from clue_research.profiling.fields import load_deep_profiling_pack
from clue_spine import Project
from tests._workspace import seed_project, seed_workspace
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_WS = "fi2-slice1-contacts"
_OTHER_WS = "fi2-slice1-contacts-other"
_BASE = f"{FRONTEND_READ_PREFIX}/accounts"

_TITLE = "contact.current_title"
_JOB_LEVEL = "contact.job_level"
_RECENT_POST = "contact.facet.recent_post"
_PUBLIC_APPEARANCES = "contact.facet.public_appearances"
_STATED_INTERESTS = "contact.facet.stated_interests"


# --- harness --------------------------------------------------------------------------------


def _app(conn: AsyncConnection, *, enabled: bool = True):
    return create_projections_app(
        surface=None,  # type: ignore[arg-type]
        tool_invoker=None,  # type: ignore[arg-type]
        settings=load_settings(_env_file=None, frontend_read_enabled=enabled),
        conn_factory=conn_session_factory(conn),
        manage_db_lifespan=False,
    )


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def _list(
    conn: AsyncConnection, account_id: uuid.UUID | str, *, workspace_id: str = _WS
) -> httpx.Response:
    async with _client(_app(conn)) as client:
        return await client.get(
            f"{_BASE}/{account_id}/contacts", headers={"X-Workspace-Id": workspace_id}
        )


async def _profile(
    conn: AsyncConnection,
    account_id: uuid.UUID | str,
    contact_id: uuid.UUID | str,
    *,
    workspace_id: str = _WS,
) -> httpx.Response:
    async with _client(_app(conn)) as client:
        return await client.get(
            f"{_BASE}/{account_id}/contacts/{contact_id}",
            headers={"X-Workspace-Id": workspace_id},
        )


def _rows(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in payload["data"]}


def _facts(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {fact["fieldKey"]: fact for fact in payload["professionalFacts"]}


# --- seeding --------------------------------------------------------------------------------


async def _account(
    conn: AsyncConnection, *, name: str, domain: str | None, workspace_id: str = _WS
) -> EntityId:
    return await insert_account_entity(
        conn,
        canonical_name=name,
        primary_domain=domain,
        status=AccountStatus.ACTIVE,
        workspace_id=workspace_id,
    )


async def _contact_claim(
    conn: AsyncConnection,
    *,
    contact_id: EntityId,
    field_key: str,
    value: JsonValue,
    run_id: RunId,
    use_class: UseClass,
    binding: IdentityBinding = IdentityBinding.STRONG,
    source_key: str = "seed_source",
    observed_at: datetime | None = None,
) -> uuid.UUID:
    claim = stamp_reuse(
        contact_claim(
            entity_id=contact_id,
            field_key=field_key,
            value_json=value,
            source_tier=1,
            extraction_method=ExtractionMethod.HUMAN,
            confidence=Confidence(1.0),
            run_id=run_id,
            research_mode=ResearchMode.COMMITTEE_DISCOVERY,
            identity_binding=binding,
            use_class=use_class,
            evidence_span=f"evidence for {field_key}",
            observed_at=observed_at,
        ),
        workspace_id=_WS,
    ).model_copy(
        update={
            "source_key": source_key,
            "verification_status": (
                VerificationStatus.VERIFIED
                if binding is IdentityBinding.STRONG
                else VerificationStatus.UNVERIFIED
            ),
        }
    )
    await insert_claim(conn, claim)
    return uuid.UUID(str(claim.id))


async def _member(
    conn: AsyncConnection,
    *,
    account_id: EntityId,
    account_run: RunId,
    name: str,
    suffix: str,
    persona: Persona = Persona.ECONOMIC_BUYER,
    binding: IdentityBinding = IdentityBinding.STRONG,
    role_confidence: float = 0.87,
    extra: Sequence[tuple[str, JsonValue, UseClass, IdentityBinding]] = (),
) -> tuple[EntityId, tuple[uuid.UUID, ...]]:
    """One committee member plus every claim id the account run references."""
    contact = await insert_contact_entity(
        conn,
        account_entity_id=account_id,
        full_name=name,
        linkedin_url=f"https://linkedin.com/in/{suffix}",
        status=AccountStatus.ACTIVE,
    )
    base = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    claim_ids = [
        await _contact_claim(
            conn,
            contact_id=contact,
            field_key=ROLE_ON_COMMITTEE,
            value={
                "role": persona.value,
                "confidence": role_confidence,
                "plausible": True,
                "rationale": "seeded",
            },
            run_id=account_run,
            use_class=UseClass.PROFESSIONAL_PUBLIC,
            binding=binding,
            source_key="committee_inference",
            observed_at=base,
        ),
        await _contact_claim(
            conn,
            contact_id=contact,
            field_key=PERSONA,
            value=persona.value,
            run_id=account_run,
            use_class=UseClass.PROFESSIONAL_PUBLIC,
            binding=binding,
            source_key="committee_inference",
            observed_at=base,
        ),
    ]
    for ordinal, (field_key, value, use_class, field_binding) in enumerate(extra):
        claim_ids.append(
            await _contact_claim(
                conn,
                contact_id=contact,
                field_key=field_key,
                value=value,
                run_id=account_run,
                use_class=use_class,
                binding=field_binding,
                source_key="linkedin_snapshot" if field_key.startswith("contact.f") else "sumble",
                observed_at=base + timedelta(minutes=ordinal),
            )
        )
    return contact, tuple(claim_ids)


class _Fixture:
    def __init__(
        self,
        *,
        project_a: Project,
        project_b: Project,
        run_a: ProjectRunId,
        run_b: ProjectRunId,
        acme: EntityId,
        shared: EntityId,
        solo: EntityId,
        masked: EntityId,
        unbound: EntityId,
    ) -> None:
        self.project_a = project_a
        self.project_b = project_b
        self.run_a = run_a
        self.run_b = run_b
        self.acme = acme
        self.shared = shared
        self.solo = solo
        self.masked = masked
        self.unbound = unbound


async def _build(conn: AsyncConnection) -> _Fixture:
    await seed_workspace(conn, _WS)
    await load_core_pack(conn)  # `contact.facet.recent_post` lives in the core pack
    await load_committee_pack(conn)
    await load_deep_profiling_pack(conn)

    project_a = await seed_project(conn, _WS, name="Contacts project A")
    project_b = await seed_project(conn, _WS, name="Contacts project B")
    base = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

    acme = await _account(conn, name="Acme Contacts", domain="acme-contacts.test")
    await ensure_project_account(
        conn,
        workspace_id=_WS,
        project_id=project_a.project_id,
        account_entity_id=acme,
        added_via="discovered",
        added_at=base,
    )
    await ensure_project_account(
        conn,
        workspace_id=_WS,
        project_id=project_b.project_id,
        account_entity_id=acme,
        added_via="imported",
        added_at=base + timedelta(minutes=5),
    )

    run_a = new_project_run_id()
    await ensure_project_run(
        conn,
        project_run_id=run_a,
        project_id=project_a.project_id,
        workspace_id=_WS,
        icp_key="alpha",
        icp_version=1,
    )
    run_b = new_project_run_id()
    await ensure_project_run(
        conn,
        project_run_id=run_b,
        project_id=project_b.project_id,
        workspace_id=_WS,
        icp_key="beta",
        icp_version=3,
    )
    account_run_a = new_run_id()
    await insert_account_run(
        conn, account_run_id=account_run_a, project_run_id=run_a, entity_id=acme, tier="top"
    )
    account_run_b = new_run_id()
    await insert_account_run(
        conn, account_run_id=account_run_b, project_run_id=run_b, entity_id=acme, tier="top"
    )

    # The two-project member. Three facets: one display-eligible signal, one signal denied by its
    # use-class (special-category), one display-eligible facet that is not a signal family.
    shared, shared_refs = await _member(
        conn,
        account_id=acme,
        account_run=account_run_a,
        name="Dana Buyer",
        suffix="dana-buyer",
        persona=Persona.ECONOMIC_BUYER,
        extra=(
            (_TITLE, "VP Finance", UseClass.PROFESSIONAL_PUBLIC, IdentityBinding.STRONG),
            (
                _RECENT_POST,
                "posted about procurement",
                UseClass.PERSONAL_PUBLIC_NON_SENSITIVE,
                IdentityBinding.STRONG,
            ),
            (
                _PUBLIC_APPEARANCES,
                [{"title": "faith-community panel", "venue": "a congregation"}],
                UseClass.SENSITIVE,
                IdentityBinding.STRONG,
            ),
            (
                _STATED_INTERESTS,
                ["cycling"],
                UseClass.PERSONAL_PUBLIC_NON_SENSITIVE,
                IdentityBinding.STRONG,
            ),
        ),
    )
    solo, solo_refs = await _member(
        conn,
        account_id=acme,
        account_run=account_run_a,
        name="Sam Technical",
        suffix="sam-technical",
        persona=Persona.TECHNICAL_EVALUATOR,
        role_confidence=0.62,
    )
    # Two honest absences on one member: a special-category title (held, display-denied →
    # `restricted`) and a weakly-bound job level (the merge itself refuses to promote it, so it is
    # simply not there — no marker, because there is no current statement to mark).
    masked, masked_refs = await _member(
        conn,
        account_id=acme,
        account_run=account_run_a,
        name="Chris Blocker",
        suffix="chris-blocker",
        persona=Persona.BLOCKER,
        extra=(
            (_TITLE, "Head Chaplain", UseClass.SENSITIVE, IdentityBinding.STRONG),
            (_JOB_LEVEL, "director", UseClass.PROFESSIONAL_PUBLIC, IdentityBinding.WEAK),
        ),
    )
    # Membership is identity-bearing: a WEAK role/persona binding is dropped by the governed reader.
    unbound, unbound_refs = await _member(
        conn,
        account_id=acme,
        account_run=account_run_a,
        name="Unbound Person",
        suffix="unbound-person",
        persona=Persona.CHAMPION,
        binding=IdentityBinding.WEAK,
    )

    await save_references(
        conn,
        account_run_a,
        references_index={
            "committee": [
                str(claim_id) for claim_id in shared_refs + solo_refs + masked_refs + unbound_refs
            ]
        },
        cost_cents=Decimal("0"),
        status=AccountRunStatus.DONE,
    )
    # Project B's run referenced only the shared member — the same governed claims, which is what
    # makes the union a union rather than two disjoint lists.
    await save_references(
        conn,
        account_run_b,
        references_index={"committee": [str(claim_id) for claim_id in shared_refs]},
        cost_cents=Decimal("0"),
        status=AccountRunStatus.DONE,
    )

    return _Fixture(
        project_a=project_a,
        project_b=project_b,
        run_a=run_a,
        run_b=run_b,
        acme=acme,
        shared=shared,
        solo=solo,
        masked=masked,
        unbound=unbound,
    )


# --- the union ------------------------------------------------------------------------------


def test_a_member_of_two_committees_appears_once_carrying_both_project_ids() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            payload = (await _list(conn, fixture.acme)).json()

            ids = [row["id"] for row in payload["data"]]
            assert ids.count(str(fixture.shared)) == 1
            rows = _rows(payload)
            assert rows[str(fixture.shared)]["projectIds"] == [
                fixture.project_a.project_id,
                fixture.project_b.project_id,
            ]
            assert rows[str(fixture.solo)]["projectIds"] == [fixture.project_a.project_id]
            # The WEAK-bound member is not a committee member at all.
            assert str(fixture.unbound) not in rows
            assert payload["meta"]["total"] == len(payload["data"]) == 3

    run_async(scenario())


def test_persona_and_role_use_the_backend_four_value_vocabulary() -> None:
    """No display mapping: the wire carries ``Persona``'s own values."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            rows = _rows((await _list(conn, fixture.acme)).json())

            allowed = {persona.value for persona in Persona}
            assert allowed == {"champion", "economic_buyer", "technical_evaluator", "blocker"}
            for row in rows.values():
                assert row["persona"] in allowed
                assert row["roleOnCommittee"]["value"] in allowed

            assert rows[str(fixture.shared)]["persona"] == Persona.ECONOMIC_BUYER.value
            assert rows[str(fixture.solo)]["persona"] == Persona.TECHNICAL_EVALUATOR.value
            assert rows[str(fixture.masked)]["persona"] == Persona.BLOCKER.value
            assert rows[str(fixture.solo)]["roleOnCommittee"]["confidence"] == pytest.approx(0.62)

    run_async(scenario())


def test_the_row_carries_the_governed_title_and_the_linkedin_identity() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            row = _rows((await _list(conn, fixture.acme)).json())[str(fixture.shared)]
            assert row["name"] == "Dana Buyer"
            assert row["title"] == "VP Finance"
            assert row["titleRestricted"] is False
            assert row["linkedinUrl"] == "https://linkedin.com/in/dana-buyer"

    run_async(scenario())


# --- governance -----------------------------------------------------------------------------


def test_a_display_denied_title_is_absent_with_a_restricted_marker() -> None:
    """The Band-2 translation of C7's ``RESTRICTED`` availability: the value never appears, and the
    caller can tell "policy withheld this" from "we do not know this"."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            row = _rows((await _list(conn, fixture.acme)).json())[str(fixture.masked)]
            assert row["title"] is None
            assert row["titleRestricted"] is True

            payload = (await _profile(conn, fixture.acme, fixture.masked)).json()
            facts = _facts(payload)
            assert facts[_TITLE]["restricted"] is True
            assert facts[_TITLE]["value"] is None
            # ...and nothing about the withheld claim leaks through the slot.
            assert facts[_TITLE]["provider"] is None
            assert facts[_TITLE]["observedAt"] is None
            assert "Chaplain" not in str(payload)

    run_async(scenario())


def test_a_weakly_bound_professional_fact_is_simply_absent_not_marked_restricted() -> None:
    """A WEAK contact claim never becomes current truth (the merge refuses to promote it), so there
    is no statement to withhold — the field is absent, and inventing a `restricted` marker for it
    would misreport a gap as a policy decision. Neither path fabricates, neither crashes."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            payload = (await _profile(conn, fixture.acme, fixture.masked)).json()
            assert _JOB_LEVEL not in _facts(payload)
            assert "director" not in str(payload)

    run_async(scenario())


def test_signal_counts_count_display_eligible_signal_families_only() -> None:
    """Three facets on one member: an eligible signal, a use-class-denied signal, and an eligible
    facet outside the signal families. Exactly one is counted."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            rows = _rows((await _list(conn, fixture.acme)).json())
            assert rows[str(fixture.shared)]["signals"] == {"count": 1}
            # A member with no facets at all counts zero rather than omitting the slot.
            assert rows[str(fixture.solo)]["signals"] == {"count": 0}

    run_async(scenario())


def test_a_workspace_that_will_not_display_professional_facts_has_no_listable_committee() -> None:
    """Fail-closed: role and persona are what make someone a committee member, so a policy that
    will not display those claims cannot leave the *person* on the list with the role blanked —
    there would be nothing honest to render them as."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            assert (await _list(conn, fixture.acme)).json()["data"], "populated before the policy"

            await conn.execute(
                text(
                    "INSERT INTO workspace_policy (policy_id, workspace_id, posture, "
                    "display_professional_public, version) "
                    "VALUES (:pid, :ws, 'conservative_default', false, 9)"
                ),
                {"pid": f"p-{uuid.uuid4()}", "ws": _WS},
            )
            payload = (await _list(conn, fixture.acme)).json()
            assert payload == {"data": [], "meta": {"total": 0}}
            assert (await _profile(conn, fixture.acme, fixture.shared)).status_code == 404

    run_async(scenario())


def test_the_signal_field_keys_are_registered_facet_fields() -> None:
    """The signal families are a *display* selection over registered facet fields; if one is ever
    renamed in its pack this fails instead of silently counting zero forever."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            from clue_api.frontend_read.contacts import CONTACT_SIGNAL_FIELD_KEYS
            from clue_research.claimstore import get_field

            await _build(conn)
            assert set(CONTACT_SIGNAL_FIELD_KEYS) == {_RECENT_POST, _PUBLIC_APPEARANCES}
            for field_key in CONTACT_SIGNAL_FIELD_KEYS:
                field = await get_field(conn, field_key)
                assert field is not None, field_key
                assert field.field_key.startswith("contact.facet.")

    run_async(scenario())


# --- the profile ----------------------------------------------------------------------------


def test_the_profile_adds_account_identity_professional_facts_and_evidence() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            payload = (await _profile(conn, fixture.acme, fixture.shared)).json()

            assert payload["id"] == str(fixture.shared)
            assert payload["accountId"] == str(fixture.acme)
            assert payload["accountName"] == "Acme Contacts"
            assert payload["redirectedFrom"] is None
            assert _facts(payload)[_TITLE]["value"] == "VP Finance"
            assert _facts(payload)[_TITLE]["provider"] == "sumble"
            assert payload["projectIds"] == [
                fixture.project_a.project_id,
                fixture.project_b.project_id,
            ]

            providers = {chip["provider"] for chip in payload["evidence"]}
            assert providers == {"committee_inference", "linkedin_snapshot", "sumble"}

    run_async(scenario())


def test_evidence_chips_carry_no_urls() -> None:
    """FI-1 G4 v1: provenance chips are non-link. The provider is the raw ``source_key`` — no
    display-name surface exists — and the evidence slot carries nothing else."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            payload = (await _profile(conn, fixture.acme, fixture.shared)).json()
            assert payload["evidence"]
            for chip in payload["evidence"]:
                assert set(chip) == {"provider", "observedAt"}
                assert "http" not in chip["provider"]
                assert chip["observedAt"].startswith("2026-08-01")

    run_async(scenario())


def test_no_email_avatar_or_non_linkedin_social_reaches_the_wire() -> None:
    """FI-1 G1/G2/G3: no avatar, no non-LinkedIn socials, no email address (not even a capability
    flag in this slice's shape)."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            payloads = [
                (await _list(conn, fixture.acme)).json(),
                (await _profile(conn, fixture.acme, fixture.shared)).json(),
            ]
            banned = {
                "email",
                "workEmail",
                "emailStatus",
                "avatar",
                "avatarUrl",
                "socials",
                "twitterUrl",
                "xUrl",
                "phone",
                "directPhone",
            }

            def walk(node: Any, path: str = "") -> None:
                if isinstance(node, dict):
                    for key, value in node.items():
                        assert key not in banned, f"{path}.{key}"
                        assert not key.endswith("Label"), f"display string at {path}.{key}"
                        walk(value, f"{path}.{key}")
                elif isinstance(node, list):
                    for index, value in enumerate(node):
                        walk(value, f"{path}[{index}]")

            for payload in payloads:
                walk(payload)
                assert "@" not in str(payload)

    run_async(scenario())


def test_a_merged_loser_contact_redirects_to_its_survivor() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            loser = await insert_contact_entity(
                conn,
                account_entity_id=fixture.acme,
                full_name="Dana B.",
                status=AccountStatus.ACTIVE,
            )
            await mark_merged(conn, EntityType.CONTACT, loser_id=loser, survivor_id=fixture.shared)
            response = await _profile(conn, fixture.acme, loser)
            assert response.status_code == 200
            payload = response.json()
            assert payload["id"] == str(fixture.shared)
            assert payload["redirectedFrom"] == str(loser)

    run_async(scenario())


# --- emptiness & 404s -----------------------------------------------------------------------


def test_an_account_with_no_committee_serves_an_empty_list_not_a_404() -> None:
    """The live-data reality until the M8D R11 bridge lands: no ``account_run`` references means no
    governed committee, and "no committee yet" is a 200 with an empty list."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            bare = await _account(conn, name="Bare", domain="bare.test")
            await ensure_project_account(
                conn,
                workspace_id=_WS,
                project_id=fixture.project_a.project_id,
                account_entity_id=bare,
                added_via="manual",
            )
            response = await _list(conn, bare)
            assert response.status_code == 200
            assert response.json() == {"data": [], "meta": {"total": 0}}

    run_async(scenario())


def test_a_membership_less_account_serves_an_empty_list() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _build(conn)
            seedling = await _account(conn, name="Seedling", domain=None)
            response = await _list(conn, seedling)
            assert response.status_code == 200
            assert response.json()["data"] == []

    run_async(scenario())


def test_an_account_in_another_workspace_is_a_404_not_a_leak() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            await seed_workspace(conn, _OTHER_WS)
            foreign = await _account(
                conn, name="Foreign", domain="foreign.test", workspace_id=_OTHER_WS
            )
            for response in (
                await _list(conn, foreign),
                await _profile(conn, foreign, fixture.shared),
                # ...and the reverse: this workspace's account read with the foreign tenant header.
                await _list(conn, fixture.acme, workspace_id=_OTHER_WS),
            ):
                assert response.status_code == 404
                assert response.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"

    run_async(scenario())


def test_an_unknown_contact_is_an_enveloped_404() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            response = await _profile(conn, fixture.acme, uuid.uuid4())
            assert response.status_code == 404
            error = response.json()["error"]
            assert error["code"] == "CONTACT_NOT_FOUND"
            assert error["requestId"]

    run_async(scenario())


def test_a_contact_on_no_committee_of_this_account_is_a_404() -> None:
    """The URL is account-scoped, and the committee is the governed membership authority: a contact
    row that exists under the account but is on no committee is not addressable here."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            assert (await _profile(conn, fixture.acme, fixture.unbound)).status_code == 404
            stranger = await insert_contact_entity(
                conn,
                account_entity_id=fixture.acme,
                full_name="Never Researched",
                status=AccountStatus.ACTIVE,
            )
            response = await _profile(conn, fixture.acme, stranger)
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "CONTACT_NOT_FOUND"

    run_async(scenario())


def test_a_contact_of_another_account_is_a_404_under_this_account() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            other = await _account(conn, name="Other", domain="other.test")
            response = await _profile(conn, other, fixture.shared)
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "CONTACT_NOT_FOUND"

    run_async(scenario())


def test_a_workspace_header_is_structurally_required() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            async with _client(_app(conn)) as client:
                response = await client.get(f"{_BASE}/{fixture.acme}/contacts")
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "UNAUTHORIZED"

    run_async(scenario())


def test_a_non_uuid_contact_id_is_an_enveloped_validation_error() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            response = await _profile(conn, fixture.acme, "not-a-uuid")
            assert response.status_code == 422
            assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    run_async(scenario())


def test_the_routes_are_absent_when_the_flag_is_off() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            async with _client(_app(conn, enabled=False)) as client:
                response = await client.get(
                    f"{_BASE}/{fixture.acme}/contacts", headers={"X-Workspace-Id": _WS}
                )
            assert response.status_code == 404

    run_async(scenario())


# --- the disciplines ------------------------------------------------------------------------


def test_contacts_never_scope_a_claim_read_by_claim_workspace_id() -> None:
    """The slice-0 trap: a DB CHECK forces ``claim.workspace_id`` NULL on public claims, so that
    predicate silently *empties* a read instead of narrowing it."""

    from pathlib import Path

    import clue_api.frontend_read.contacts as module

    body = Path(module.__file__).read_text().split('"""', 2)[2]
    assert "claim.workspace_id" not in body


def test_the_committee_reader_is_the_governed_resolver_not_the_identity_helper() -> None:
    """FI-1 §4.5 ruling — and the per-project context rule is *imported* from the account-detail
    module, never re-derived (there is exactly one recorded latest-run-wins rule)."""

    from pathlib import Path

    import clue_api.frontend_read.contacts as module

    body = Path(module.__file__).read_text().split('"""', 2)[2]
    assert "contact_ids_for_account" not in body
    assert "ContactEligibilityResolver" in body
    assert "latest_project_run_context" in body
    assert "FROM project_run" not in body


def test_the_display_gate_is_the_shared_c7_predicate() -> None:
    """Governance is mirrored by *reuse*, not by a copy that is free to drift."""

    from clue_api.frontend_read import contacts
    from clue_api.research_view_governance import display_allowed

    assert contacts.display_allowed is display_allowed
