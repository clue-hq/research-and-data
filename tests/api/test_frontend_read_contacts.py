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

import hashlib
import json
import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from httpx import ASGITransport
from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.display.blocks import insert_block
from clue_api.arv2.display.gather import SectionInput
from clue_api.arv2.display.recipes import recipes_for
from clue_api.arv2.display.render import display_claim
from clue_api.arv2.display.runner import SectionDraft
from clue_api.client_context_binding import bind_workspace_client
from clue_api.frontend_read import FRONTEND_READ_PREFIX
from clue_api.frontend_read.contract_v1 import (
    AccountContactDetailResponseV1,
    AccountContactsResponseV1,
)
from clue_api.frontend_read.display_pages import DisplayPages
from clue_api.frontend_read.v1_shared import tenure
from clue_api.projections_app import create_projections_app
from clue_config import load_settings
from clue_core import (
    AccountStatus,
    ClaimId,
    Confidence,
    EntityId,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    Persona,
    ProjectRunId,
    ResearchMode,
    ReuseScope,
    RunId,
    UseClass,
    VerificationStatus,
    contact_claim,
    new_project_run_id,
    new_run_id,
)
from clue_research.claimstore import (
    WorkspaceScope,
    claims_by_ids,
    insert_claim,
    load_core_pack,
)
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
from clue_research.narrative import CONTACT_OVERVIEW, load_prose_pack
from clue_research.profiling.committee import PERSONA, ROLE_ON_COMMITTEE, load_committee_pack
from clue_research.profiling.fields import load_deep_profiling_pack
from clue_spine import Project
from clue_storage import artifact_key, content_address, record_artifact
from tests._workspace import seed_project, seed_workspace
from tests.api.contract_v1.oracle import zod_validate

# The v1 seed and its harness, shared rather than re-written: the contacts table, the contact page
# and the account detail are three views of one account and must be proven against one seed. The
# names are module-private in that suite only because nothing else had needed them.
from tests.api.test_frontend_read_account_detail import (  # noqa: PLC2701
    _WS as _V1_WS,
)
from tests.api.test_frontend_read_account_detail import (  # noqa: PLC2701
    _build_v1,
    _launch_research_job,
    _lenient_claim,
    _V1Fixture,
)
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
_TITLE_ARTIFACT_BODY = b"Dana Buyer is VP Finance at Acme Contacts."
_TITLE_ARTIFACT_KEY = artifact_key(_WS, content_address(_TITLE_ARTIFACT_BODY))

#: The ``solo`` member's single signal family, deliberately **list-valued with more than one item**:
#: it is what makes ``signals.typeCount`` falsifiable (a per-item unit would report 3, the ratified
#: per-field unit reports 1). Named here so the assertion reads the same data the fixture seeds.
_SOLO_APPEARANCES: tuple[dict[str, str], ...] = (
    {"title": "keynote at DevCon"},
    {"title": "panel at SaaStr"},
    {"title": "podcast on Ops Weekly"},
)

#: The five contact-page sections, in recipe order. Pinned here so a recipe reordering has to be a
#: deliberate change to a contract the frontend renders in order, not a silent one.
_CONTACT_SECTION_ORDER = [
    "why-this-person",
    "problem-right-now",
    "openers",
    "angles",
    "do-not-mention",
]


# --- harness --------------------------------------------------------------------------------


class _MemoryStorage:
    def __init__(self, blobs: dict[str, bytes] | None = None) -> None:
        self.blobs = dict(blobs or {})

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        del media_type
        self.blobs[key] = data

    async def get(self, key: str) -> bytes:
        return self.blobs[key]

    async def delete(self, key: str) -> None:
        self.blobs.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.blobs

    async def presign(self, key: str, *, expires_in: int = 3600) -> str:
        raise AssertionError(f"must not presign {key!r} for {expires_in}s")

    async def list_blobs(self) -> AsyncIterator[tuple[str, datetime]]:
        if False:
            yield "", datetime.min.replace(tzinfo=UTC)


def _app(
    conn: AsyncConnection,
    *,
    enabled: bool = True,
    evidence_storage: _MemoryStorage | None = None,
):
    """The real projections app with the flag on and the DB seam bound to the test's connection.

    ``arv2_display_generate_on_read=False`` is not decoration: the composition root reads a real
    ``Secrets()``, so on a developer machine with ``OPENROUTER_API_KEY`` set the D3 display seam
    would build a live runner and the ``?contract=v1`` half of this suite would *spend money*
    writing contact pages. Off, the seam is a pure projection over the blocks the fixture stored.
    """
    return create_projections_app(
        surface=None,  # type: ignore[arg-type]
        tool_invoker=None,  # type: ignore[arg-type]
        settings=load_settings(
            _env_file=None,
            frontend_read_enabled=enabled,
            arv2_display_generate_on_read=False,
        ),
        conn_factory=conn_session_factory(conn),
        ingestion_storage=evidence_storage,
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
    evidence_storage: _MemoryStorage | None = None,
) -> httpx.Response:
    async with _client(_app(conn, evidence_storage=evidence_storage)) as client:
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
    source_url: str | None = None,
    observed_at: datetime | None = None,
) -> uuid.UUID:
    retained_key: str | None = None
    if field_key == _TITLE:
        retained_key = _TITLE_ARTIFACT_KEY
        await record_artifact(
            conn,
            storage_key=retained_key,
            workspace_id=_WS,
            content_sha256=content_address(_TITLE_ARTIFACT_BODY),
            media_type="text/plain",
            size_bytes=len(_TITLE_ARTIFACT_BODY),
            source_key=source_key,
            source_url=(
                source_url
                if source_url is not None
                else f"https://evidence.example.test/contact/{field_key}"
            ),
        )
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
            source_url=(
                source_url
                if source_url is not None
                else f"https://evidence.example.test/contact/{field_key}"
            ),
            evidence_span=f"evidence for {field_key}",
            observed_at=observed_at,
        ),
        workspace_id=_WS,
    ).model_copy(
        update={
            "source_key": source_key,
            "artifact_key": retained_key,
            "verification_status": (
                VerificationStatus.VERIFIED
                if binding is IdentityBinding.STRONG
                else VerificationStatus.UNVERIFIED
            ),
        }
    )
    await insert_claim(conn, claim)
    return uuid.UUID(str(claim.id))


async def _contact_overview_claim(
    conn: AsyncConnection,
    *,
    contact_id: EntityId,
    run_id: RunId,
    paragraphs: Sequence[str],
    status: VerificationStatus = VerificationStatus.VERIFIED,
    research_outcome: str = "completed",
) -> None:
    """One Lane-E-shaped contact overview, independent of committee reference indexing."""

    claim = contact_claim(
        entity_id=contact_id,
        field_key=CONTACT_OVERVIEW,
        value_json={
            "paragraphs": list(paragraphs),
            "prompt_version": "contact_overview_v1",
            "synthesized_from_job_id": str(uuid.uuid4()),
            "research_outcome": research_outcome,
            "project_id": None,
        },
        source_tier=4,
        extraction_method=ExtractionMethod.LLM_SYNTHESIS,
        confidence=Confidence(0.7),
        run_id=run_id,
        research_mode=ResearchMode.CONTACT_PROFILING,
        identity_binding=IdentityBinding.STRONG,
        use_class=UseClass.PROFESSIONAL_PUBLIC,
        source_url="clue://narrative/prose",
        evidence_span="verified professional contact facts",
    ).model_copy(
        update={
            "source_key": "llm_synthesis",
            "verification_status": status,
            "reuse_scope": ReuseScope.TENANT_PRIVATE,
            "workspace_id": _WS,
        }
    )
    await insert_claim(conn, claim)


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
    await load_prose_pack(conn)

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
    # The one-project member, carrying exactly ONE signal family whose value is a three-item list —
    # the fixture behind the ratified unit: `signals.typeCount` counts the *field*, so this member
    # reports 1, and a per-item unit would report 3.
    solo, solo_refs = await _member(
        conn,
        account_id=acme,
        account_run=account_run_a,
        name="Sam Technical",
        suffix="sam-technical",
        persona=Persona.TECHNICAL_EVALUATOR,
        role_confidence=0.62,
        extra=(
            (
                _PUBLIC_APPEARANCES,
                list(_SOLO_APPEARANCES),
                UseClass.PROFESSIONAL_PUBLIC,
                IdentityBinding.STRONG,
            ),
        ),
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


def test_persona_and_role_use_the_backend_vocabulary() -> None:
    """No display mapping: the wire carries ``Persona``'s own values.

    ARV2 D8 appended ``user`` to ``Persona``, so the backend vocabulary is no longer exactly the
    four values this screen's zod enum pins. The parity that matters is unchanged and asserted
    here: the four the frontend contract knows are all still backend values, and every value this
    endpoint actually serves is a backend value.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            rows = _rows((await _list(conn, fixture.acme)).json())

            allowed = {persona.value for persona in Persona}
            assert {"champion", "economic_buyer", "technical_evaluator", "blocker"} <= allowed
            for row in rows.values():
                assert row["persona"] in allowed
                assert row["roleOnCommittee"]["value"] in allowed

            assert rows[str(fixture.shared)]["persona"] == Persona.ECONOMIC_BUYER.value
            assert rows[str(fixture.solo)]["persona"] == Persona.TECHNICAL_EVALUATOR.value
            assert rows[str(fixture.masked)]["persona"] == Persona.BLOCKER.value
            assert rows[str(fixture.solo)]["roleOnCommittee"]["confidence"] == pytest.approx(0.62)
            assert rows[str(fixture.solo)]["roleOnCommittee"]["reasoning"] == "seeded"

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
            assert facts[_TITLE]["claimId"] is None
            assert facts[_TITLE]["provider"] is None
            assert facts[_TITLE]["observedAt"] is None
            assert all(item["fieldKey"] != _TITLE for item in payload["evidence"])
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
    facet outside the signal families. Exactly one is counted.

    The wire key is ``typeCount``, not ``count``: the founder's 2026-08-08 unit ruling (FI-1 §9) is
    that the chip reports how many signal **types** are present, and the field is named for the unit
    it carries. The exact-dict comparison pins the key, so a silent rename back to ``count`` — or an
    extra sibling key — fails here.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            rows = _rows((await _list(conn, fixture.acme)).json())
            assert rows[str(fixture.shared)]["signals"] == {"typeCount": 1}
            # A member with no facets at all counts zero rather than omitting the slot.
            assert rows[str(fixture.masked)]["signals"] == {"typeCount": 0}

    run_async(scenario())


def test_a_list_valued_signal_facet_counts_as_one_type_not_one_per_item() -> None:
    """The ratified unit, proven rather than asserted in a comment.

    ``solo`` holds exactly one display-eligible signal family whose value is a three-item list. A
    per-item unit would report 3; ``typeCount`` reports **1** — one per signal *field* that holds a
    display-eligible statement, which is the whole reason the key is not called ``count``.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            assert len(_SOLO_APPEARANCES) > 1, "the fixture really is multi-item"
            rows = _rows((await _list(conn, fixture.acme)).json())
            assert rows[str(fixture.solo)]["signals"] == {"typeCount": 1}

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

            providers = {item["provider"] for item in payload["evidence"]}
            assert providers == {"committee_inference", "linkedin_snapshot", "sumble"}
            evidence_by_claim = {item["claimId"]: item for item in payload["evidence"]}
            for fact in payload["professionalFacts"]:
                if fact["restricted"]:
                    assert fact["claimId"] is None
                    continue
                assert fact["claimId"] in evidence_by_claim
                item = evidence_by_claim[fact["claimId"]]
                assert item["fieldKey"] == fact["fieldKey"]
                assert item["evidenceSpan"] == f"evidence for {fact['fieldKey']}"

    run_async(scenario())


def test_contact_overview_is_a_typed_current_claim_not_a_professional_fact() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            await _contact_overview_claim(
                conn,
                contact_id=fixture.shared,
                run_id=new_run_id(),
                paragraphs=(
                    "Dana leads financial evaluation for Acme's buying committee.",
                    "The current record identifies procurement as a relevant professional theme.",
                ),
                research_outcome="needs_review",
            )

            payload = (await _profile(conn, fixture.acme, fixture.shared)).json()
            assert payload["overview"] == {
                "state": "available",
                "paragraphs": [
                    "Dana leads financial evaluation for Acme's buying committee.",
                    "The current record identifies procurement as a relevant professional theme.",
                ],
                "researchOutcome": "needs_review",
            }
            assert CONTACT_OVERVIEW not in _facts(payload)

    run_async(scenario())


def test_contact_overview_distinguishes_not_composed_from_restricted() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            assert (await _profile(conn, fixture.acme, fixture.shared)).json()["overview"] == {
                "state": "not_composed",
                "paragraphs": [],
                "researchOutcome": None,
            }

            await _contact_overview_claim(
                conn,
                contact_id=fixture.shared,
                run_id=new_run_id(),
                paragraphs=("This rejected overview must never be served.",),
                status=VerificationStatus.REJECTED,
            )
            overview = (await _profile(conn, fixture.acme, fixture.shared)).json()["overview"]
            assert overview == {
                "state": "restricted",
                "paragraphs": [],
                "researchOutcome": None,
            }
            assert "rejected overview" not in str(overview)

    run_async(scenario())


def test_evidence_carries_exact_safe_urls_claim_mapping_and_review_metadata() -> None:
    """FI-2 Slice 5 supersedes G4: public links are exact and every record names its claim."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            payload = (await _profile(conn, fixture.acme, fixture.shared)).json()
            assert payload["evidence"]
            for item in payload["evidence"]:
                assert set(item) == {
                    "claimId",
                    "fieldKey",
                    "sourceTitle",
                    "provider",
                    "sourceUrl",
                    "evidenceSpan",
                    "confidence",
                    "freshness",
                    "observedAt",
                    "protectedArtifactAvailable",
                }
                assert item["sourceTitle"] == item["provider"]
                assert item["sourceUrl"] == (
                    f"https://evidence.example.test/contact/{item['fieldKey']}"
                )
                assert item["evidenceSpan"] == f"evidence for {item['fieldKey']}"
                assert item["confidence"] == 1.0
                assert item["freshness"] in {"fresh", "stale"}
                assert item["observedAt"].startswith("2026-08-01")
                assert item["protectedArtifactAvailable"] is (item["fieldKey"] == _TITLE)

    run_async(scenario())


def test_retained_contact_evidence_is_streamed_after_current_authorization_only() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            storage = _MemoryStorage({_TITLE_ARTIFACT_KEY: _TITLE_ARTIFACT_BODY})
            profile = (
                await _profile(
                    conn,
                    fixture.acme,
                    fixture.shared,
                    evidence_storage=storage,
                )
            ).json()
            title_evidence = next(
                item for item in profile["evidence"] if item["fieldKey"] == _TITLE
            )
            assert title_evidence["protectedArtifactAvailable"] is True
            assert _TITLE_ARTIFACT_KEY not in str(profile)

            path = (
                f"{_BASE}/{fixture.acme}/contacts/{fixture.shared}/evidence/"
                f"{title_evidence['claimId']}"
            )
            async with _client(_app(conn, evidence_storage=storage)) as client:
                response = await client.get(path, headers={"X-Workspace-Id": _WS})
                crossed = await client.get(path, headers={"X-Workspace-Id": _OTHER_WS})
                unaddressable = await client.get(
                    f"{_BASE}/{fixture.acme}/contacts/{uuid.uuid4()}/evidence/"
                    f"{title_evidence['claimId']}",
                    headers={"X-Workspace-Id": _WS},
                )

            assert response.status_code == 200
            assert response.content == _TITLE_ARTIFACT_BODY
            assert response.headers["cache-control"] == "private, no-store"
            assert response.headers["content-security-policy"].startswith("sandbox")
            assert response.headers["x-content-type-options"] == "nosniff"
            assert "signed" not in str(response.headers).lower()
            assert crossed.status_code == 404
            assert crossed.json()["error"]["code"] == "EVIDENCE_NOT_FOUND"
            assert unaddressable.status_code == 404

            await conn.execute(
                text("UPDATE artifact SET erased_at=now() WHERE storage_key=:key"),
                {"key": _TITLE_ARTIFACT_KEY},
            )
            async with _client(_app(conn, evidence_storage=storage)) as client:
                erased = await client.get(path, headers={"X-Workspace-Id": _WS})
            assert erased.status_code == 404
            assert erased.json()["error"]["code"] == "EVIDENCE_NOT_FOUND"

    run_async(scenario())


def test_retention_expired_contact_claim_exposes_neither_value_nor_evidence() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            before = (await _profile(conn, fixture.acme, fixture.shared)).json()
            title_evidence = next(item for item in before["evidence"] if item["fieldKey"] == _TITLE)
            await conn.execute(
                text(
                    """
                    INSERT INTO lawful_basis_record (
                        claim_id, lawful_basis, third_party_collected, regime, retention_until
                    ) VALUES (
                        :claim_id, 'legitimate_interest', true, 'gdpr', :expired_at
                    )
                    """
                ),
                {
                    "claim_id": title_evidence["claimId"],
                    "expired_at": datetime(2026, 7, 1, tzinfo=UTC),
                },
            )

            after = (await _profile(conn, fixture.acme, fixture.shared)).json()
            assert _TITLE not in _facts(after)
            assert all(item["claimId"] != title_evidence["claimId"] for item in after["evidence"])

            storage = _MemoryStorage({_TITLE_ARTIFACT_KEY: _TITLE_ARTIFACT_BODY})
            path = (
                f"{_BASE}/{fixture.acme}/contacts/{fixture.shared}/evidence/"
                f"{title_evidence['claimId']}"
            )
            async with _client(_app(conn, evidence_storage=storage)) as client:
                expired = await client.get(path, headers={"X-Workspace-Id": _WS})
            assert expired.status_code == 404
            assert expired.json()["error"]["code"] == "EVIDENCE_NOT_FOUND"

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


def test_the_workspace_client_has_no_target_contact_surface() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_workspace(conn, _WS)
            client = await _account(conn, name="Insight Health", domain="insighthealth.ai")
            await bind_workspace_client(
                conn,
                workspace_id=_WS,
                client_entity_id=client,
            )

            response = await _list(conn, client)
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"

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
    """FI-1 §4.5 and Slice-3 addressability: every linked surface imports one committee reader."""

    from pathlib import Path

    import clue_api.frontend_read.account_detail as account_detail
    import clue_api.frontend_read.committee as committee
    import clue_api.frontend_read.contacts as module

    contact_body = Path(module.__file__).read_text().split('"""', 2)[2]
    detail_body = Path(account_detail.__file__).read_text().split('"""', 2)[2]
    committee_body = Path(committee.__file__).read_text().split('"""', 2)[2]
    assert "contact_ids_for_account" not in contact_body + detail_body + committee_body
    assert "read_governed_committee" in contact_body
    assert "read_governed_committee" in detail_body
    assert "ContactEligibilityResolver" in committee_body
    assert "latest_project_run_context" in committee_body
    assert "FROM project_run" in committee_body
    assert "FROM project_run" not in contact_body + detail_body


def test_the_display_gate_is_the_shared_c7_predicate() -> None:
    """Governance is mirrored by *reuse*, not by a copy that is free to drift."""

    from clue_api.frontend_read import contacts
    from clue_api.research_view_governance import display_allowed

    assert contacts.display_allowed is display_allowed


# --- contract v1 (ARV2 D3, E4/E5) -------------------------------------------------------------
#
# The v1 half of this suite, and deliberately the **same seed** the account-detail and
# account-workspace suites use: the contacts table and the contact page are the other two views of
# one account, so proving them against a private fixture would let three screens be built from
# three different pictures of the same company. ``_build_v1`` is imported from that suite and
# extended with the ARV2 contact this contract is actually about — a fully-researched person
# carrying every rail fact E5 renders — plus:
#
# * a **coverage row**, so the committee is the research's own list rather than "every contact with
#   a claim". Without it the fallback would put every seeded person on the committee and the
#   non-committee-but-addressable case (the E5 ruling) could not exist;
# * a person the coverage row leaves out who still holds claims (served on E5, absent from E4);
# * a person with no claims at all (the honest 404);
# * one stored ``contact/openers`` section, written by hand through D2's own ``insert_block`` so
#   the read surface is proven to compose what is stored rather than to write anything.


class _V1Contacts:
    def __init__(
        self,
        *,
        v1: _V1Fixture,
        nick: EntityId,
        priya: EntityId,
        blank: EntityId,
        email_claim_id: str,
        location_claim_id: str,
        signal_claim_ids: tuple[str, str],
    ) -> None:
        self.v1 = v1
        self.zafran = v1.zafran
        self.dana = v1.dana
        self.ravi = v1.ravi
        #: The fully-researched ARV2 contact E5 is about.
        self.nick = nick
        #: Under the account, holding claims, absent from the coverage committee.
        self.priya = priya
        #: Under the account, no claims and no page.
        self.blank = blank
        self.email_claim_id = email_claim_id
        self.location_claim_id = location_claim_id
        #: What the stored ``openers`` section cites.
        self.signal_claim_ids = signal_claim_ids


#: The current position the career history records — the tenure the header is computed from.
_V1_POSITION_START = date(2024, 4, 1)


async def _seed_coverage(
    conn: AsyncConnection,
    *,
    account_id: EntityId,
    project_id: str,
    members: Sequence[EntityId],
) -> None:
    """One finalized ``entity_research_account_coverage`` row naming this account's committee.

    The coverage row is what makes committee membership the *research's* answer rather than "every
    contact the store holds a claim for", which is the fallback ``committee_members`` uses before
    any run has published one. The run and job rows are the FK anchors it hangs off, launched
    through the same production entry point the detail suite uses.
    """
    launch = await _launch_research_job(conn, project_id=project_id, account_id=account_id)
    coverage = {"origin": "frontend-read-contacts-v1"}
    body = json.dumps(coverage, sort_keys=True)
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_account_coverage
                (coverage_id, research_run_id, job_id, workspace_id, account_entity_id,
                 result_refs, completed_field_keys, unresolved_field_keys, unresolved_reasons,
                 committee_result_refs, committee_member_ids, committee_status, review_flags,
                 claim_refs, evidence_refs, coverage_json, coverage_sha256)
            VALUES (:coverage_id, :run_id, :job_id, :workspace_id, :account, :empty, :empty,
                    :empty, :empty, :empty, :members, 'complete', :empty, :empty, :empty,
                    CAST(:coverage AS jsonb), :sha)
            """
        ),
        {
            "coverage_id": uuid.uuid4(),
            "run_id": launch["research_run_id"],
            "job_id": launch["job_id"],
            "workspace_id": _V1_WS,
            "account": account_id,
            "empty": [],
            "members": [uuid.UUID(str(member)) for member in members],
            "coverage": body,
            "sha": hashlib.sha256(body.encode()).hexdigest(),
        },
    )


async def _seed_openers_block(
    conn: AsyncConnection, *, contact_id: EntityId, cited: Sequence[str]
) -> None:
    """One live ``contact/openers`` block for this person, with the send line the page renders."""
    recipe = next(item for item in recipes_for("contact") if item.section_key == "openers")
    claims = await claims_by_ids(
        conn,
        [ClaimId(uuid.UUID(claim_id)) for claim_id in cited],
        scope=WorkspaceScope.for_workspace(_V1_WS),
    )
    section = SectionInput(
        recipe=recipe,
        claims=tuple(display_claim(claim, subject=None) for claim in claims.values()),
        deduped={},
    )
    draft = SectionDraft(
        section_key=recipe.section_key,
        intro=[],
        items=[
            {
                "id": "openers-1",
                "h2": "He is hiring a demand-gen lead",
                "body": [
                    {"text": "He posted about the search last week.", "claimIds": list(cited)}
                ],
                "sendLine": {
                    "channel": "linkedin",
                    "text": "Saw you are hiring a demand-gen lead — how are you sequencing it?",
                    "claimIds": [cited[0]],
                },
                "contactRefs": [],
                "priority": 1,
                "newSinceLastVisit": False,
            }
        ],
        cited_claim_ids=list(cited),
        checks={"unknown_aliases": [], "off_recipe": []},
        aliases={f"c{index}": claim_id for index, claim_id in enumerate(cited, start=1)},
        cost=None,
        model="x-ai/grok-4.6",
        raw_refs=(),
    )
    await insert_block(
        conn,
        workspace_id=_V1_WS,
        subject_kind="contact",
        subject_id=str(contact_id),
        page="contact",
        recipe=recipe,
        draft=draft,
        section=section,
        now=datetime.now(UTC),
    )


async def _build_v1_contacts(conn: AsyncConnection) -> _V1Contacts:
    """The shared v1 account, plus the three people the contacts contract is proven over."""
    v1 = await _build_v1(conn)
    await load_deep_profiling_pack(conn)

    nick = await insert_contact_entity(
        conn,
        account_entity_id=v1.zafran,
        full_name="Nick Fisher",
        linkedin_url="https://www.linkedin.com/in/nicholastfisher",
        status=AccountStatus.ACTIVE,
    )
    for field_key, value in (
        (_TITLE, "VP of Marketing"),
        (PERSONA, "economic_buyer"),
        (
            ROLE_ON_COMMITTEE,
            {
                "role": "economic_buyer",
                "rationale": "Owns the demand-generation budget.",
                "influence": "High",
            },
        ),
        ("contact.facet.alma_mater", {"institution": "Columbia", "degree": "MBA"}),
        (
            "contact.facet.career_history",
            [
                {
                    "company": "Zafran",
                    "titles": ["VP of Marketing"],
                    "date": {"start": _V1_POSITION_START.isoformat(), "end": None},
                },
                {
                    "company": "Cato Networks",
                    "titles": ["Director of Demand Gen"],
                    "date": {"start": "2021-02-01", "end": "2024-03-31"},
                },
            ],
        ),
        ("contact.network_statistics", {"followers": 6808, "connections": 500}),
        ("contact.member_badges", ["creator"]),
        ("contact.facet.best_channel", "LinkedIn, then email"),
    ):
        await _lenient_claim(
            conn,
            entity_id=nick,
            entity_type=EntityType.CONTACT,
            field_key=field_key,
            value=value,
            research_mode=ResearchMode.CONTACT_PROFILING,
            source_url="https://www.linkedin.com/in/nicholastfisher",
            evidence_span="Nick Fisher, VP of Marketing at Zafran.",
        )
    email_claim_id = await _lenient_claim(
        conn,
        entity_id=nick,
        entity_type=EntityType.CONTACT,
        field_key="core.work_email",
        value={"address": "nick@zafran.io", "status": "verified_smtp"},
        research_mode=ResearchMode.CONTACT_PROFILING,
        source_url="https://zafran.io/team",
    )
    location_claim_id = await _lenient_claim(
        conn,
        entity_id=nick,
        entity_type=EntityType.CONTACT,
        field_key="contact.current_location",
        value={"raw": "New York, New York", "country": "United States"},
        research_mode=ResearchMode.CONTACT_PROFILING,
        source_url="https://www.linkedin.com/in/nicholastfisher",
    )
    # Two outreach-usable P1 signals and one the appropriateness gate refused: the header's count
    # is the *usable* one, so an unsafe P1 must not be counted (and is not displayable either).
    signal_ids: list[str] = []
    for field_key, value, source_url, span in (
        (
            _RECENT_POST,
            "Hiring a demand-gen lead — DM me.",
            "https://www.linkedin.com/posts/nicholastfisher-hiring",
            "Hiring a demand-gen lead — DM me.",
        ),
        (
            "contact.facet.hooks",
            ["Ran the Cato demand-gen team through its Series C"],
            "https://www.linkedin.com/in/nicholastfisher",
            "Ran the Cato demand-gen team through its Series C.",
        ),
    ):
        signal_ids.append(
            await _lenient_claim(
                conn,
                entity_id=nick,
                entity_type=EntityType.CONTACT,
                field_key=field_key,
                value=value,
                research_mode=ResearchMode.CONTACT_PROFILING,
                source_url=source_url,
                evidence_span=span,
                signal_priority=1,
                outreach_safe=True,
            )
        )
    signals = (signal_ids[0], signal_ids[1])
    await _lenient_claim(
        conn,
        entity_id=nick,
        entity_type=EntityType.CONTACT,
        field_key="contact.facet.excluded_lookalike",
        value={"title": "a different Nick Fisher", "reason": "wrong company"},
        research_mode=ResearchMode.CONTACT_PROFILING,
        source_url="https://www.linkedin.com/in/another-nick-fisher",
        signal_priority=1,
        outreach_safe=False,
    )
    # Ravi reports to Nick — the ``reports`` chips are committee members pointing *at* the subject.
    await _lenient_claim(
        conn,
        entity_id=v1.ravi,
        entity_type=EntityType.CONTACT,
        field_key="contact.reports_to",
        value={"contact_id": str(nick), "name": "Nick Fisher"},
        research_mode=ResearchMode.CONTACT_PROFILING,
        source_url="https://zafran.io/team",
    )

    # Under the account, researched, and left off the coverage committee — the E5 ruling's case.
    # No LinkedIn URL either, which is the second thing this person proves.
    priya = await insert_contact_entity(
        conn,
        account_entity_id=v1.zafran,
        full_name="Priya Raman",
        linkedin_url=None,
        status=AccountStatus.ACTIVE,
    )
    await _lenient_claim(
        conn,
        entity_id=priya,
        entity_type=EntityType.CONTACT,
        field_key=_TITLE,
        value="Head of RevOps",
        research_mode=ResearchMode.CONTACT_PROFILING,
        source_url="https://zafran.io/team",
    )
    # Under the account and never researched: no claims, no page, no contact detail.
    blank = await insert_contact_entity(
        conn,
        account_entity_id=v1.zafran,
        full_name="Blank Person",
        linkedin_url=None,
        status=AccountStatus.ACTIVE,
    )

    await _seed_coverage(
        conn,
        account_id=v1.zafran,
        project_id=v1.base.project_a.project_id,
        members=(v1.dana, nick, v1.ravi),
    )
    await _seed_openers_block(conn, contact_id=nick, cited=signals)
    return _V1Contacts(
        v1=v1,
        nick=nick,
        priya=priya,
        blank=blank,
        email_claim_id=email_claim_id,
        location_claim_id=location_claim_id,
        signal_claim_ids=signals,
    )


async def _list_v1(
    conn: AsyncConnection,
    account_id: uuid.UUID | str,
    *,
    workspace_id: str = _V1_WS,
    contract: str | None = "v1",
) -> httpx.Response:
    async with _client(_app(conn)) as client:
        return await client.get(
            f"{_BASE}/{account_id}/contacts",
            params={} if contract is None else {"contract": contract},
            headers={"X-Workspace-Id": workspace_id},
        )


async def _profile_v1(
    conn: AsyncConnection,
    account_id: uuid.UUID | str,
    contact_id: uuid.UUID | str,
    *,
    workspace_id: str = _V1_WS,
    contract: str | None = "v1",
) -> httpx.Response:
    async with _client(_app(conn)) as client:
        return await client.get(
            f"{_BASE}/{account_id}/contacts/{contact_id}",
            params={} if contract is None else {"contract": contract},
            headers={"X-Workspace-Id": workspace_id},
        )


def test_the_v1_contacts_table_is_the_coverage_committee_in_screen_order() -> None:
    """E4: every field of the row, from the sources decisions 2/12/13 name — and the order the
    screens show, which is the account detail's committee order, not insertion order."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build_v1_contacts(conn)
            response = await _list_v1(conn, fixture.zafran)
            assert response.status_code == 200
            body = response.json()

            assert set(body) == {"data", "meta"}
            AccountContactsResponseV1.model_validate(body)
            assert body["meta"]["total"] == 3
            # Persona rank first (economic_buyer, then champion), then name — and the two people
            # the coverage row leaves out are absent from the table entirely.
            assert [row["name"] for row in body["data"]] == [
                "Dana Katz",
                "Nick Fisher",
                "Ravi Mehta",
            ]

            nick = next(row for row in body["data"] if row["id"] == str(fixture.nick))
            assert nick["title"] == "VP of Marketing"
            assert nick["persona"] == "economic_buyer"
            assert nick["personaTone"] == "olive"
            # The committee claim carries its own influence, so the persona default is not used.
            assert nick["influence"] == "High"
            assert nick["emailStatus"] == "available"
            assert nick["emailLabel"] == "nick@zafran.io"
            assert nick["socials"] == ["linkedin"]
            assert nick["profileAction"] == "page"
            assert "avatarUrl" not in nick

            for row in body["data"]:
                zod_validate(row, "AccountContactSummarySchema")

    run_async(scenario())


def test_the_v1_contact_page_serves_every_rail_fact_the_display_and_its_evidence() -> None:
    """E5: the row, the rail's served labels, the generated page and the provenance behind it."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build_v1_contacts(conn)
            response = await _profile_v1(conn, fixture.zafran, fixture.nick)
            assert response.status_code == 200
            body = response.json()

            assert set(body) == {"data"}
            AccountContactDetailResponseV1.model_validate(body)
            data = body["data"]

            # --- the row, repeated verbatim from the table
            assert data["id"] == str(fixture.nick)
            assert data["name"] == "Nick Fisher"
            assert data["title"] == "VP of Marketing"
            assert data["influence"] == "High"
            assert data["profileAction"] == "page"

            # --- the account this page hangs under
            assert data["accountId"] == str(fixture.zafran)
            assert data["accountName"] == "Zafran"
            assert data["accountLogoPath"] is None

            # --- the served rail labels (never derived in the browser)
            assert data["recentSignalsLabel"] == "2 signals", "the unsafe P1 is not a usable signal"
            assert data["linkedinLabel"] == "nicholastfisher"
            assert data["linkedinUrl"] == "https://www.linkedin.com/in/nicholastfisher"
            assert data["emailVerifiedAt"] is not None
            assert data["emailClaimId"] == fixture.email_claim_id
            assert data["locationLabel"] == "New York, New York"
            assert data["locationClaimId"] == fixture.location_claim_id
            assert data["bestFirstChannelLabel"] == "LinkedIn, then email"
            assert data["educationLabel"] == "Columbia, MBA"
            assert data["tenureLabel"] == tenure(_V1_POSITION_START, now=date.today())[0]
            assert data["employmentStartedAt"] == _V1_POSITION_START.isoformat()
            assert data["linkedinFollowers"] == 6808
            assert data["linkedinCreator"] is True
            assert "xLabel" not in data
            assert "xUrl" not in data

            # --- who reports to this person
            assert [ref["contactId"] for ref in data["reports"]] == [str(fixture.ravi)]
            assert data["reports"][0]["name"] == "Ravi Mehta"
            assert data["reports"][0]["accountId"] == str(fixture.zafran)

            # --- the generated page: the whole recipe grammar, written section and all
            assert data["contactDisplay"]["page"] == "contact"
            sections = {section["key"]: section for section in data["contactDisplay"]["sections"]}
            assert list(sections) == _CONTACT_SECTION_ORDER
            assert sections["openers"]["empty"] is False
            assert sections["openers"]["items"][0]["sendLine"]["channel"] == "linkedin"
            assert [key for key, section in sections.items() if section["empty"] is True] == [
                "why-this-person",
                "problem-right-now",
                "angles",
                "do-not-mention",
            ], "generation is off in this suite, so nothing else can have been written"

            # --- the evidence behind every citation and both claim-id chips
            evidence = {row["claimId"] for row in data["researchEvidence"]}
            assert evidence == {
                *fixture.signal_claim_ids,
                fixture.email_claim_id,
                fixture.location_claim_id,
            }
            assert all("fieldKey" not in row for row in data["researchEvidence"])

            # --- the two legacy slots the display layer replaced
            assert data["overviewParagraphs"] == []
            assert data["evidence"] == []

            assert data["lastModifiedAt"].endswith("Z")
            zod_validate(data, "AccountContactDetailSchema")

    run_async(scenario())


def test_a_researched_contact_off_the_coverage_committee_still_has_a_page() -> None:
    """The E5 addressability ruling: a contact **under this account** holding a live claim has a
    page whether or not the latest coverage row listed them — and a contact with no safe LinkedIn
    URL is served with the site root rather than a fabricated profile link or a 404."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build_v1_contacts(conn)
            listed = {row["id"] for row in (await _list_v1(conn, fixture.zafran)).json()["data"]}
            assert str(fixture.priya) not in listed

            response = await _profile_v1(conn, fixture.zafran, fixture.priya)
            assert response.status_code == 200
            data = response.json()["data"]
            assert data["name"] == "Priya Raman"
            assert data["title"] == "Head of RevOps"
            # No committee claim and no persona claim: the neutral member of the vocabulary.
            assert data["persona"] == "user"
            assert data["influence"] == "Medium"
            assert data["socials"] == []
            assert data["linkedinUrl"] == "https://www.linkedin.com/"
            assert data["linkedinLabel"] == "LinkedIn"
            assert data["recentSignalsLabel"] == "No signals yet"
            assert data["reports"] == []
            AccountContactDetailResponseV1.model_validate({"data": data})
            zod_validate(data, "AccountContactDetailSchema")

    run_async(scenario())


def test_a_contact_with_neither_claims_nor_a_page_is_an_enveloped_404() -> None:
    """The other half of the ruling: being under the account is not on its own a page."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build_v1_contacts(conn)
            response = await _profile_v1(conn, fixture.zafran, fixture.blank)

            assert response.status_code == 404
            error = response.json()["error"]
            assert error["code"] == "CONTACT_NOT_FOUND"
            assert error["requestId"] == response.headers["X-Request-Id"]

    run_async(scenario())


def test_the_contact_routes_serve_both_contracts_side_by_side() -> None:
    """``?contract=v1`` selects the ARV2 payloads; its absence leaves the FI-2 ones byte-for-byte.

    Proven on **this suite's own FI-2 fixture**, where the governed committee is populated. On the
    ARV2 seed the FI-2 reader legitimately sees nobody — its committee comes from
    ``account_run.references_index``, whose only production writer sits behind the M8D R1
    quarantine — so an unchanged FI-2 payload would be indistinguishable there from a broken one.

    The two contracts also disagree about *who* is listed, on purpose: the ARV2 display predicate
    does not consult ``identity_binding`` (D3 ruling S10), so the weakly-bound person the governed
    FI-2 reader drops is a real contact with real claims to the v1 table.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)

            fi2_rows = (await _list(conn, fixture.acme)).json()
            assert {"roleOnCommittee", "signals", "projectIds"} <= set(fi2_rows["data"][0])
            fi2_profile = (await _profile(conn, fixture.acme, fixture.shared)).json()
            assert "data" not in fi2_profile
            assert {"professionalFacts", "overview", "roleOnCommittee"} <= set(fi2_profile)

            v1_rows = (await _list_v1(conn, fixture.acme, workspace_id=_WS)).json()
            assert {"personaTone", "influence", "profileAction"} <= set(v1_rows["data"][0])
            assert all("roleOnCommittee" not in row for row in v1_rows["data"])
            assert v1_rows["meta"]["total"] == len(v1_rows["data"])

            v1_profile = (
                await _profile_v1(conn, fixture.acme, fixture.shared, workspace_id=_WS)
            ).json()
            assert set(v1_profile) == {"data"}
            assert {"recentSignalsLabel", "contactDisplay", "lastModifiedAt"} <= set(
                v1_profile["data"]
            )
            assert v1_profile["data"]["id"] == str(fixture.shared)

    run_async(scenario())


def test_an_unrecognised_contract_value_is_refused_on_both_contact_routes() -> None:
    """A typo'd ``?contract=v2`` that quietly served *something* is what the parameter prevents."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build_v1_contacts(conn)
            for response in (
                await _list_v1(conn, fixture.zafran, contract="v2"),
                await _profile_v1(conn, fixture.zafran, fixture.nick, contract="v2"),
            ):
                assert response.status_code == 422
                error = response.json()["error"]
                assert error["code"] == "VALIDATION_ERROR"
                assert error["requestId"] == response.headers["X-Request-Id"]

    run_async(scenario())


def test_the_v1_evidence_route_authorises_a_claim_the_contact_page_cites() -> None:
    """The evidence route authorises against the **union** of both contracts.

    The FI-2 profile is committee-only and exposes only claims with a retained blob, so a claim the
    v1 contact page cites would open onto a 404 if the v1 half were not consulted. It is consulted
    with ``generate=False``, so the check can never write a page or schedule one.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build_v1_contacts(conn)
            cited = fixture.signal_claim_ids[0]
            storage = _MemoryStorage()

            async with _client(_app(conn, evidence_storage=storage)) as client:
                response = await client.get(
                    f"{_BASE}/{fixture.zafran}/contacts/{fixture.nick}/evidence/{cited}",
                    headers={"X-Workspace-Id": _V1_WS},
                )
            # Authorised (it is not the "no such evidence" refusal) but nothing is retained for
            # this claim, so the stream itself is still the same honest 404.
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "EVIDENCE_NOT_FOUND"

            page = await DisplayPages(
                settings=load_settings(_env_file=None, arv2_display_generate_on_read=False),
                secrets=None,
                conn_factory=conn_session_factory(conn),
            ).page(
                conn,
                workspace_id=_V1_WS,
                subject_kind="contact",
                subject_id=str(fixture.nick),
                page="contact",
                generate=False,
            )
            assert cited in page.cited_claim_ids

    run_async(scenario())
