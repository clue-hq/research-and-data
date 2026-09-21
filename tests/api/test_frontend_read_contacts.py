"""The contacts table and the contact page
(`GET /frontend/v1/accounts/{id}/contacts[/{cid}]`), plus the contact evidence stream.

Same harness as the accounts-list and account-detail suites: the real projections app driven
in-process through ``httpx.ASGITransport`` on the test's rolled-back connection, so the endpoints
read exactly the rows the test seeded and nothing commits.

Two fixtures. ``_build`` is the two-project workspace the emptiness and refusal rules are proven
against — an account with no researched contacts at all, the workspace's own client binding, a
foreign workspace, a contact that belongs to another account. ``_build_v1_contacts`` is the ARV2
seed: a researched account whose contacts hold real claims, one of them with a written page and
retained evidence, so the table's order, the rail's facts and the page's citations are proven
against the shapes production really holds.

Every read is workspace-scoped: this suite shares a database with suites that commit.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_store import RunRow, create_job, create_run, finish_job
from clue_api.arv2.display.blocks import insert_block
from clue_api.arv2.display.gather import SectionInput
from clue_api.arv2.display.recipes import recipes_for
from clue_api.arv2.display.render import display_claim
from clue_api.arv2.display.runner import SectionDraft
from clue_api.client_context_binding import bind_workspace_client
from clue_api.frontend_read import FRONTEND_READ_PREFIX
from clue_api.frontend_read.app import build_frontend_read_router
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
from clue_fleet import FleetTaskKind
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
    would build a live runner and this suite would *spend money* writing contact pages. Off, the
    seam is a pure projection over the blocks the fixture stored.
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


# --- emptiness, refusal & the disciplines ------------------------------------------------------


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


def test_contacts_never_scope_a_claim_read_by_claim_workspace_id() -> None:
    """The slice-0 trap: a DB CHECK forces ``claim.workspace_id`` NULL on public claims, so that
    predicate silently *empties* a read instead of narrowing it."""

    from pathlib import Path

    import clue_api.frontend_read.contacts as module

    body = Path(module.__file__).read_text().split('"""', 2)[2]
    assert "claim.workspace_id" not in body


# --- the table and the page (ARV2 E4/E5) -------------------------------------------------------
#
# The v1 half of this suite, and deliberately the **same seed** the account-detail and
# account-workspace suites use: the contacts table and the contact page are the other two views of
# one account, so proving them against a private fixture would let three screens be built from
# three different pictures of the same company. ``_build_v1`` is imported from that suite and
# extended with the ARV2 contact this contract is actually about — a fully-researched person
# carrying every rail fact E5 renders — plus:
#
# * a person who holds one claim and nothing else — no persona, no committee role — so the table's
#   placeholders and its persona-rank ordering are both proved against a real row rather than an
#   invented one;
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
        #: Under the account, holding one claim, and carrying no committee facts at all.
        self.priya = priya
        #: Under the account, no claims and no page.
        self.blank = blank
        self.email_claim_id = email_claim_id
        self.location_claim_id = location_claim_id
        #: What the stored ``openers`` section cites.
        self.signal_claim_ids = signal_claim_ids


#: The current position the career history records — the tenure the header is computed from.
_V1_POSITION_START = date(2024, 4, 1)


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

    # Under the account, researched, and carrying no persona or committee role — the placeholder
    # case. No LinkedIn URL either, which is the second thing this person proves.
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
    conn: AsyncConnection, account_id: uuid.UUID | str, *, workspace_id: str = _V1_WS
) -> httpx.Response:
    return await _list(conn, account_id, workspace_id=workspace_id)


async def _profile_v1(
    conn: AsyncConnection,
    account_id: uuid.UUID | str,
    contact_id: uuid.UUID | str,
    *,
    workspace_id: str = _V1_WS,
) -> httpx.Response:
    return await _profile(conn, account_id, contact_id, workspace_id=workspace_id)


def test_the_contacts_table_is_the_researched_committee_in_screen_order() -> None:
    """E4: every field of the row, from the sources decisions 2/12/13 name — and the order the
    screens show, which is the account detail's committee order, not insertion order.

    The committee is ARV2's own answer (founder ruling 2026-09-09): the contacts under this
    account that hold a live claim. So the person with no claims at all is absent, and the person
    with one title claim and no committee facts is present — being unresearched, not being left
    off somebody's list, is what keeps a name out of this table.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build_v1_contacts(conn)
            response = await _list_v1(conn, fixture.zafran)
            assert response.status_code == 200
            body = response.json()

            assert set(body) == {"data", "meta"}
            AccountContactsResponseV1.model_validate(body)
            assert body["meta"]["total"] == 4
            # Persona rank first (economic_buyer, then champion, then the personaless member),
            # then name — never insertion order. Blank Person holds no claims and is absent.
            assert [row["name"] for row in body["data"]] == [
                "Dana Katz",
                "Nick Fisher",
                "Ravi Mehta",
                "Priya Raman",
            ]
            assert str(fixture.blank) not in {row["id"] for row in body["data"]}

            nick = next(row for row in body["data"] if row["id"] == str(fixture.nick))
            assert nick["title"] == "VP of Marketing"
            # Display text on the wire (D4-b decision 5); the *tone* still keys on the vocabulary
            # value behind it, which is why the two fields do not look like they agree.
            assert nick["persona"] == "Economic buyer"
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


def test_the_contact_page_serves_every_rail_fact_the_display_and_its_evidence() -> None:
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
            # A ``ResearchContactReference`` carries display text like every other persona slot.
            assert data["reports"][0]["persona"] == "Champion"

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


def test_a_researched_contact_with_no_committee_facts_is_listed_and_has_a_page() -> None:
    """The E5 addressability ruling: a contact **under this account** holding a live claim is on
    the committee and has a page, even when the research recorded no persona and no role for them
    — and a contact with no safe LinkedIn URL is served with the site root rather than a
    fabricated profile link or a 404."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build_v1_contacts(conn)
            listed = {row["id"] for row in (await _list_v1(conn, fixture.zafran)).json()["data"]}
            assert str(fixture.priya) in listed

            response = await _profile_v1(conn, fixture.zafran, fixture.priya)
            assert response.status_code == 200
            data = response.json()["data"]
            assert data["name"] == "Priya Raman"
            assert data["title"] == "Head of RevOps"
            # No committee claim and no persona claim: the neutral member of the vocabulary,
            # served as the word a marketer reads.
            assert data["persona"] == "User"
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


def test_the_evidence_route_authorises_a_claim_the_contact_page_cites() -> None:
    """The evidence route authorises against what this person's own contact page cites.

    It asks the display seam with ``generate=False``, so the check can never write a page or
    schedule one — an authorising GET must be safe to retry.
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


# --- the provider's own shapes for the rail (D3 close-out finding from the Zafran walk) ---------


def test_followers_and_creator_badge_read_the_providers_record_shapes() -> None:
    """The answer key stores AI Ark's own records: followers nested under ``network`` and the
    badges as one flag per badge, not the registry sketches (``{"followers": n}``, a list)."""
    from types import SimpleNamespace

    from clue_api.frontend_read.contacts import _creator_badge, _followers

    def claim(value: object) -> Any:
        return SimpleNamespace(value_json=value)

    assert _followers(claim({"followers": 6808})) == 6808
    assert (
        _followers(claim({"network": {"followers_count": 6808, "connections_count": 4776}})) == 6808
    )
    assert _followers(claim({"network": {"followers_count": "6808"}})) is None
    assert _followers(claim({"followers": -1})) is None
    assert _followers(None) is None

    assert _creator_badge(claim(["creator"])) is True
    assert _creator_badge(claim({"creator": True, "premium": True, "hiring": False})) is True
    assert _creator_badge(claim({"creator": False, "premium": True})) is False
    assert _creator_badge(claim({"premium": True})) is None
    assert _creator_badge(None) is None


# --- the contacts tab is one of the three "on open" moments (plan 2026-09-21) -------------------


class _RecordingQueue:
    """The fleet's work queue, reduced to the one call the display seam makes."""

    def __init__(self) -> None:
        self.offers: list[dict[str, Any]] = []

    async def enqueue(self, **kwargs: Any) -> bool:
        self.offers.append(kwargs)
        return True


def _scheduling_app(conn: AsyncConnection, queue: _RecordingQueue):
    """The read surface with a work queue behind it — a seam that schedules instead of writing.

    ``secrets=None`` keeps it honest about money: with no runner it could not write a page even
    if it wanted to, so the only thing this app can do about a missing page is offer its task.
    """
    app = FastAPI()
    app.include_router(
        build_frontend_read_router(
            settings=load_settings(
                _env_file=None,
                frontend_read_enabled=True,
                arv2_display_generate_on_read=True,
            ),
            conn_factory=conn_session_factory(conn),
            secrets=None,
            work_queue=queue,
        )
    )
    return app


async def _settled_person_job(
    conn: AsyncConnection, *, project: Project, account_id: EntityId, contact_id: EntityId
) -> uuid.UUID:
    """One completed ``person`` job for this committee member — what makes their page offerable."""
    project_run_id = new_project_run_id()
    await ensure_project_run(
        conn,
        project_run_id=project_run_id,
        project_id=project.project_id,
        workspace_id=project.workspace_id,
        icp_key="contacts-tab",
        icp_version=1,
    )
    run_id = uuid.uuid4()
    sha = "b" * 64
    await create_run(
        conn,
        RunRow(
            run_id=run_id,
            workspace_id=project.workspace_id,
            project_id=project.project_id,
            brand_id=project.brand_id,
            project_run_id=uuid.UUID(str(project_run_id)),
            icp_artifact_key=f"{project.workspace_id}/{sha}",
            icp_artifact_sha256=sha,
            icp_key="contacts-tab",
            icp_version=1,
            product_selection_version=1,
            effort="full",
            committee_cap=3,
            directive_text="",
            profile_ref="arv2-account/v1",
            profile_sha256=sha,
            requested_by_user_id="u_owner",
            request_sha256=sha,
        ),
    )
    job_id = uuid.uuid4()
    await create_job(
        conn,
        job_id=job_id,
        run_id=run_id,
        workspace_id=project.workspace_id,
        account_entity_id=uuid.UUID(str(account_id)),
        subject_type="person",
        subject_entity_id=uuid.UUID(str(contact_id)),
    )
    await finish_job(
        conn,
        job_id=job_id,
        status="completed",
        finalization={"outcome": "completed"},
        model_rounds=1,
        tool_calls=1,
        cost_usd=Decimal("0"),
        credits=Decimal("0"),
        media_seconds=0,
    )
    return job_id


def test_reading_the_contacts_tab_offers_the_pages_of_settled_members_without_one() -> None:
    """Opening the tab starts the members' pages on the fleet, and skips the ones already written.

    Ravi's research has settled and he has no page — his is offered, stamped with the job whose
    claims it will be written from. Nick's research has settled too, but the fixture already holds
    a live ``contact/openers`` block for him, so re-offering his page would pay twice for words
    that are already on the screen.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build_v1_contacts(conn)
            project = fixture.v1.base.project_a
            ravi_job = await _settled_person_job(
                conn, project=project, account_id=fixture.zafran, contact_id=fixture.ravi
            )
            await _settled_person_job(
                conn, project=project, account_id=fixture.zafran, contact_id=fixture.nick
            )

            queue = _RecordingQueue()
            async with _client(_scheduling_app(conn, queue)) as client:
                response = await client.get(
                    f"{_BASE}/{fixture.zafran}/contacts", headers={"X-Workspace-Id": _V1_WS}
                )

            assert response.status_code == 200
            assert [offer["payload"]["subject_id"] for offer in queue.offers] == [str(fixture.ravi)]
            offer = queue.offers[0]
            assert offer["kind"] is FleetTaskKind.ARV2_DISPLAY_PAGE
            assert offer["payload"]["page"] == "contact"
            assert offer["payload"]["job_id"] == str(ravi_job)
            assert offer["reopen_terminal"] is True

    run_async(scenario())


def test_reading_the_contacts_tab_without_a_queue_offers_nothing() -> None:
    """The default deployment is unchanged: no queue, no offers, and no extra statements."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build_v1_contacts(conn)
            await _settled_person_job(
                conn,
                project=fixture.v1.base.project_a,
                account_id=fixture.zafran,
                contact_id=fixture.ravi,
            )
            response = await _list(conn, fixture.zafran, workspace_id=_V1_WS)
            assert response.status_code == 200

    run_async(scenario())
