"""ARV2 D3, E3 — the account workspace payload (`GET /frontend/v1/accounts/{id}/workspace`).

Same harness as the account-detail suite, and deliberately the **same seed**: this endpoint is the
other half of one account's screen, so proving it against a second fixture would let the two
screens be built from two different pictures of the same account. ``_build_v1`` is therefore
imported from that suite (module-private only because nothing outside this package had needed it
before) and extended with the two stored **insights** sections this payload is about:

* one ``buying-signals`` block — the non-restricted section whose items ``insightSummary`` counts;
* one ``context-only`` block — the *restricted* section whose items it must not count, because a
  watch-out is context the marketer may not use and counting it would overstate the page.

``arv2_display_generate_on_read=False`` throughout (inherited from that suite's ``_app``): the
composition root reads a real ``Secrets()``, so on a machine with ``OPENROUTER_API_KEY`` set the
display seam would otherwise build a live runner and this suite would spend money writing pages.
Off, the seam is a pure projection over the blocks seeded here.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.display.blocks import insert_block
from clue_api.arv2.display.gather import SectionInput
from clue_api.arv2.display.recipes import recipes_for
from clue_api.arv2.display.render import display_claim
from clue_api.arv2.display.runner import SectionDraft
from clue_api.client_context_binding import bind_workspace_client
from clue_api.frontend_read import FRONTEND_READ_PREFIX
from clue_api.frontend_read.contract_v1 import AccountWorkspaceResponseV1
from clue_api.projections_app import create_projections_app
from clue_config import load_settings
from clue_core import ClaimId, EntityId, EntityType
from clue_research.claimstore import WorkspaceScope, claims_by_ids
from clue_research.identity import mark_merged
from tests._workspace import seed_workspace
from tests.api.contract_v1.oracle import zod_validate

# The v1 seed and its harness, shared rather than re-written: the workspace payload and the
# account detail are two halves of one screen and must be proven against one account. The names
# are module-private in that suite only because nothing else had needed them; importing them is
# deliberate, and lifting them into a third module would leave the detail suite reaching across
# packages for its own fixture.
from tests.api.test_frontend_read_account_detail import (  # noqa: PLC2701
    _OTHER_WS,
    _WS,
    _account,
    _app,
    _build_v1,
    _client,
    _lenient_claim,
    _V1Fixture,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_BASE = f"{FRONTEND_READ_PREFIX}/accounts"

#: The insights sections, in recipe order. Pinned here so a recipe reordering has to be a
#: deliberate change to a contract the frontend renders in order, not a silent one.
_INSIGHTS_SECTION_ORDER = [
    "buying-signals",
    "money-and-momentum",
    "tools-they-already-use",
    "how-they-sell",
    "context-only",
    "miscellaneous",
]


# --- harness ----------------------------------------------------------------------------------


async def _get(
    conn: AsyncConnection,
    account_id: uuid.UUID | str,
    *,
    workspace_id: str = _WS,
    contract: str | None = None,
) -> httpx.Response:
    """One workspace request. The ``contract`` parameter is inert and only proven so here."""
    async with _client(_app(conn)) as client:
        return await client.get(
            f"{_BASE}/{account_id}/workspace",
            params={} if contract is None else {"contract": contract},
            headers={"X-Workspace-Id": workspace_id},
        )


def _sections(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {section["key"]: section for section in payload["insightsDisplay"]["sections"]}


async def _seed_insights_block(
    conn: AsyncConnection,
    *,
    account_id: EntityId,
    section_key: str,
    cited: Sequence[str],
    item_count: int,
    now: datetime | None = None,
    page: str = "insights",
) -> None:
    """One live ``<page>/<section_key>`` block, written by hand through D2's ``insert_block``.

    No model is called: what this suite needs is a *stored* section, so the read surface can be
    proven to compose what is stored rather than to write anything. ``page`` is a parameter
    because the insights page's restricted section is a SHARED one since Task 7 — it owns no
    block and renders the overview's ``watch-outs``, so that is where the row has to go.
    """
    recipe = next(item for item in recipes_for(page) if item.section_key == section_key)
    claims = await claims_by_ids(
        conn,
        [ClaimId(uuid.UUID(claim_id)) for claim_id in cited],
        scope=WorkspaceScope.for_workspace(_WS),
    )
    section = SectionInput(
        recipe=recipe,
        claims=tuple(display_claim(claim, subject=None) for claim in claims.values()),
        deduped={},
    )
    draft = SectionDraft(
        section_key=section_key,
        intro=[],
        items=[
            {
                "id": f"{section_key}-{ordinal}",
                "h2": f"{recipe.h1} {ordinal}",
                "body": [{"text": "They are hiring detection engineers.", "claimIds": list(cited)}],
                "sendLine": None,
                "contactRefs": [],
                "priority": ordinal,
                "newSinceLastVisit": False,
            }
            for ordinal in range(1, item_count + 1)
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
        workspace_id=_WS,
        subject_kind="account",
        subject_id=str(account_id),
        page=page,
        recipe=recipe,
        draft=draft,
        section=section,
        now=now or datetime.now(UTC),
    )


class _Fixture:
    def __init__(
        self,
        *,
        v1: _V1Fixture,
        signal_claim_ids: tuple[str, ...],
        restricted_claim_id: str,
    ) -> None:
        self.v1 = v1
        self.zafran = v1.zafran
        #: What the stored ``buying-signals`` block cites.
        self.signal_claim_ids = signal_claim_ids
        #: What the stored (restricted) owner block — the overview's ``watch-outs`` — cites.
        self.restricted_claim_id = restricted_claim_id


async def _build(conn: AsyncConnection) -> _Fixture:
    """The shared v1 account, plus the two stored insights sections this payload is about."""
    v1 = await _build_v1(conn)
    signals = (
        await _lenient_claim(
            conn,
            entity_id=v1.zafran,
            entity_type=EntityType.ACCOUNT,
            field_key="account.strategic_moves",
            value="Opened a detection-engineering team in Boston.",
            source_key="exa_contents",
            source_url="https://zafran.io/blog/detection",
            evidence_span="Zafran opened a detection-engineering team in Boston.",
        ),
        await _lenient_claim(
            conn,
            entity_id=v1.zafran,
            entity_type=EntityType.ACCOUNT,
            field_key="account.operational_pain",
            value="Alert triage backlog across three SIEMs.",
            source_key="exa_contents",
            source_url="https://zafran.io/blog/triage",
            evidence_span="Their triage backlog spans three SIEMs.",
        ),
    )
    restricted = await _lenient_claim(
        conn,
        entity_id=v1.zafran,
        entity_type=EntityType.ACCOUNT,
        field_key="account.reputation_risk",
        value="A public outage postmortem in June.",
        source_key="exa_contents",
        source_url="https://zafran.io/status/june",
        evidence_span="Zafran published an outage postmortem in June.",
    )
    await _seed_insights_block(
        conn,
        account_id=v1.zafran,
        section_key="buying-signals",
        cited=signals,
        item_count=2,
    )
    # The insights page's ``context-only`` shares the overview's ``watch-outs`` (Task 7), so the
    # restricted body is stored on the OWNER page and rendered under the sharer's chrome.
    await _seed_insights_block(
        conn,
        account_id=v1.zafran,
        section_key="watch-outs",
        cited=(restricted,),
        item_count=2,
        page="overview",
    )
    return _Fixture(v1=v1, signal_claim_ids=signals, restricted_claim_id=restricted)


# --- the payload ------------------------------------------------------------------------------


def test_the_workspace_payload_serves_the_insights_page_for_a_populated_account() -> None:
    """Every field of E3, composed from the sources the plan names — and the whole body validated
    twice: by the strict pydantic model and by the frontend's own Zod."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            response = await _get(conn, fixture.zafran)
            assert response.status_code == 200
            body = response.json()

            assert set(body) == {"data"}
            AccountWorkspaceResponseV1.model_validate(body)
            data = body["data"]
            assert data["accountId"] == str(fixture.zafran)

            # --- the generated page: the whole recipe grammar, written sections and all
            assert data["insightsDisplay"]["page"] == "insights"
            sections = _sections(data)
            assert list(sections) == _INSIGHTS_SECTION_ORDER
            assert sections["buying-signals"]["empty"] is False
            assert sections["context-only"]["empty"] is False
            assert sections["context-only"]["restricted"] is True
            assert [key for key, section in sections.items() if section["empty"] is True] == [
                "money-and-momentum",
                "tools-they-already-use",
                "how-they-sell",
                "miscellaneous",
            ], "generation is off in this suite, so nothing else can have been written"
            assert [item["id"] for item in sections["buying-signals"]["items"]] == [
                "buying-signals-1",
                "buying-signals-2",
            ]

            # --- the served summary: two non-restricted items, two committee members
            assert data["insightSummary"] == ["2 insights", "2 people"]

            # --- the two slots that are honestly empty in v1
            assert data["insights"] == []
            assert data["artifacts"] == []

            # --- the evidence behind every citation on the page
            evidence = {row["claimId"]: row for row in data["researchEvidence"]}
            assert set(evidence) == {*fixture.signal_claim_ids, fixture.restricted_claim_id}
            assert all("fieldKey" not in row for row in data["researchEvidence"])

            # --- activity
            assert len(data["activity"]) == 1
            entry = data["activity"][0]
            assert entry["actor"] == {"type": "clue"}
            assert entry["text"] == "Summary refreshed"
            assert entry["occurredAt"].endswith("Z")

            zod_validate(data, "AccountWorkspaceSchema")

    run_async(scenario())


def test_the_restricted_sections_items_are_not_counted_as_insights() -> None:
    """``insightSummary``'s count is the point of the restricted flag: a "context only" item is
    context the marketer must not use, so counting it would overstate what the page offers."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            sections = _sections((await _get(conn, fixture.zafran)).json()["data"])

            shown = sum(
                len(section["items"]) for section in sections.values() if not section["restricted"]
            )
            hidden = sum(
                len(section["items"]) for section in sections.values() if section["restricted"]
            )
            assert shown == 2
            assert hidden == 2, "the restricted section really does hold items"
            body = (await _get(conn, fixture.zafran)).json()["data"]
            assert body["insightSummary"] == [f"{shown} insights", "2 people"]

    run_async(scenario())


def test_an_account_with_no_committee_and_no_blocks_is_an_all_empty_page() -> None:
    """An empty, flagged page is a correct output — never a 500 and never a fabrication."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _build(conn)
            bare = await _account(conn, name="Bare Workspace", domain=None)
            data = (await _get(conn, bare)).json()["data"]

            sections = _sections(data)
            assert list(sections) == _INSIGHTS_SECTION_ORDER
            assert all(section["empty"] is True for section in sections.values())
            assert data["insightSummary"] == ["0 insights", "0 people"]
            assert data["researchEvidence"] == []
            assert data["activity"] == []
            assert data["insights"] == []
            assert data["artifacts"] == []
            AccountWorkspaceResponseV1.model_validate({"data": data})

    run_async(scenario())


def test_the_artifacts_tab_lists_the_design_documents_made_for_the_account() -> None:
    """D0 ruling S9's later slice: every project's artifacts for this account, newest first.

    A design document belongs to an account through its ``design_account`` row's
    ``account_entity_id``. Every project's documents are listed (founder, 2026-09-30), labelled
    with the project's name; archived ones and other accounts' are not. The thumbnail is the
    gallery's own route.
    """
    from tests._identity import seed_principal
    from tests._workspace import seed_project
    from tests.api.test_design_artifact_feed_db import (  # noqa: PLC2701
        USER_ID,
        _seed_design_document,
        _seed_leg,
        _seed_thread,
    )

    async def document(
        conn: AsyncConnection,
        *,
        project_id: str,
        document_id: str,
        title: str,
        kind: str,
        at: datetime,
    ) -> None:
        await _seed_design_document(
            conn,
            workspace_id=_WS,
            document_id=document_id,
            title=title,
            doc_kind=kind,
            updated_at=at,
        )
        thread_id = await _seed_thread(
            conn, workspace_id=_WS, project_id=project_id, thread_id=f"thr_{document_id}"
        )
        await _seed_leg(
            conn,
            workspace_id=_WS,
            project_id=project_id,
            thread_id=thread_id,
            document_id=document_id,
        )

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            other = await _account(conn, name="Other Health", domain="other.example")
            await seed_principal(conn, workspace_id=_WS, user_id=USER_ID)
            first = await seed_project(conn, _WS, name="Albany outreach")
            second = await seed_project(conn, _WS, name="Q4 campaign")
            for account_id, entity in (("acc_zafran", fixture.zafran), ("acc_other", other)):
                await conn.execute(
                    text(
                        "INSERT INTO design_account"
                        " (account_id, workspace_id, name, account_entity_id)"
                        " VALUES (:id, :ws, 'Account', :entity)"
                    ),
                    {"id": account_id, "ws": _WS, "entity": entity},
                )
            t0 = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
            await document(
                conn,
                project_id=first.project_id,
                document_id="doc_ad",
                title="Zafran LinkedIn ad",
                kind="scene",
                at=t0 + timedelta(days=2),
            )
            await document(
                conn,
                project_id=second.project_id,
                document_id="doc_web",
                title="Zafran landing page",
                kind="web",
                at=t0 + timedelta(days=1),
            )
            await document(
                conn,
                project_id=first.project_id,
                document_id="doc_old",
                title="Archived ad",
                kind="scene",
                at=t0,
            )
            await document(
                conn,
                project_id=first.project_id,
                document_id="doc_other",
                title="Other ad",
                kind="scene",
                at=t0,
            )
            await conn.execute(
                text(
                    "UPDATE design_document SET account_id = 'acc_zafran'"
                    " WHERE id IN ('doc_ad', 'doc_web', 'doc_old')"
                )
            )
            await conn.execute(
                text("UPDATE design_document SET account_id = 'acc_other' WHERE id = 'doc_other'")
            )
            await conn.execute(
                text("UPDATE design_document SET archived_at = now() WHERE id = 'doc_old'")
            )

            data = (await _get(conn, fixture.zafran)).json()["data"]

            assert [item["id"] for item in data["artifacts"]] == ["doc_ad", "doc_web"]
            ad, web = data["artifacts"]
            assert (ad["title"], ad["type"], ad["projectName"]) == (
                "Zafran LinkedIn ad",
                "ad",
                "Albany outreach",
            )
            assert (web["type"], web["projectName"]) == ("web", "Q4 campaign")
            assert ad["thumbnailPath"] == "/api/clue/design/documents/doc_ad/thumbnail?v=0"
            assert ad["accountId"] == str(fixture.zafran)
            assert ad["updatedAt"].startswith("2026-09-03")
            assert ad["lastEditedLabel"].startswith("Last edited")
            AccountWorkspaceResponseV1.model_validate({"data": data})
            zod_validate(data, "AccountWorkspaceSchema")

            # The other account sees only its own.
            other_data = (await _get(conn, other)).json()["data"]
            assert [item["id"] for item in other_data["artifacts"]] == ["doc_other"]

    run_async(scenario())


# --- resolution & refusal ---------------------------------------------------------------------


def test_a_merged_loser_is_followed_silently() -> None:
    """Same three resolution rules as the detail — and this contract has no ``redirectedFrom``
    slot, so the survivor is simply served rather than a field being invented to announce it."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            loser = await _account(conn, name="Zafran Dup", domain="zafran-dup.test")
            await mark_merged(conn, EntityType.ACCOUNT, loser_id=loser, survivor_id=fixture.zafran)

            data = (await _get(conn, loser)).json()["data"]
            assert data["accountId"] == str(fixture.zafran)
            assert "redirectedFrom" not in data
            assert data["insightSummary"] == ["2 insights", "2 people"]

    run_async(scenario())


def test_an_unknown_id_is_an_enveloped_404() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _build(conn)
            response = await _get(conn, uuid.uuid4())

            assert response.status_code == 404
            error = response.json()["error"]
            assert error["code"] == "ACCOUNT_NOT_FOUND"
            assert error["requestId"] == response.headers["X-Request-Id"]

    run_async(scenario())


def test_an_account_in_another_workspace_is_a_404_not_a_leak() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _build(conn)
            await seed_workspace(conn, _OTHER_WS)
            foreign = await _account(
                conn, name="Foreign Workspace", domain="foreign-ws.test", workspace_id=_OTHER_WS
            )
            response = await _get(conn, foreign)

            assert response.status_code == 404
            assert response.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"

    run_async(scenario())


def test_the_workspace_client_cannot_be_opened_as_a_target_account() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_workspace(conn, _WS)
            client_entity = await _account(conn, name="Insight Health", domain="insighthealth.ai")
            await bind_workspace_client(conn, workspace_id=_WS, client_entity_id=client_entity)

            response = await _get(conn, client_entity)
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"

    run_async(scenario())


# --- the retired contract parameter & the flag -------------------------------------------------


def test_a_contract_parameter_is_ignored_whatever_it_says() -> None:
    """One contract, so the selector is inert (it was deleted on 2026-09-09).

    It is *ignored* rather than refused on purpose: the frontend adapters sent ``?contract=v1``
    until the same change removed them, and 422ing a request this route can answer perfectly well
    would have made the two halves of one PR undeployable apart.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            default = await _get(conn, fixture.zafran)
            pinned = await _get(conn, fixture.zafran, contract="v1")
            stale = await _get(conn, fixture.zafran, contract="v2")

            assert default.status_code == pinned.status_code == stale.status_code == 200
            assert default.json() == pinned.json() == stale.json()

    run_async(scenario())


def test_the_route_is_absent_when_the_flag_is_off() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            app = create_projections_app(
                surface=None,  # type: ignore[arg-type]
                tool_invoker=None,  # type: ignore[arg-type]
                settings=load_settings(_env_file=None, frontend_read_enabled=False),
                conn_factory=conn_session_factory(conn),
                manage_db_lifespan=False,
            )
            async with _client(app) as client:
                response = await client.get(
                    f"{_BASE}/{fixture.zafran}/workspace", headers={"X-Workspace-Id": _WS}
                )
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "NOT_FOUND"
            assert response.json()["error"]["requestId"] == response.headers["X-Request-Id"]

    run_async(scenario())


def test_a_workspace_header_is_structurally_required() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            async with _client(_app(conn)) as client:
                response = await client.get(f"{_BASE}/{fixture.zafran}/workspace")
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "UNAUTHORIZED"

    run_async(scenario())


def test_the_activity_feed_is_the_accounts_own() -> None:
    """The workspace payload and the account detail serve one account's activity, from one read —
    so an event added here appears on both screens with the same actor and stamp."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await _build(conn)
            await conn.execute(
                text(
                    "INSERT INTO account_activity_event (workspace_id, account_entity_id, kind, "
                    "actor_kind, text, action, occurred_at) "
                    "VALUES (:w, :a, 'contacts', 'clue', :t, NULL, :o)"
                ),
                {
                    "w": _WS,
                    "a": fixture.zafran,
                    "t": "Two contacts resolved",
                    "o": datetime.now(UTC) - timedelta(minutes=30),
                },
            )
            data = (await _get(conn, fixture.zafran)).json()["data"]

            assert [entry["text"] for entry in data["activity"]] == [
                "Two contacts resolved",
                "Summary refreshed",
            ]
            assert all(entry["occurredAt"].endswith("Z") for entry in data["activity"])
            assert all(entry["actor"] == {"type": "clue"} for entry in data["activity"])

    run_async(scenario())
