"""ARV2 D3, the closing walk — the five contract-v1 payloads over the *real* Zafran data.

Every other D3 suite proves one endpoint against a fixture it seeded itself: precise, and blind to
the one question that matters at the end of the track — does the read surface serve the account the
platform actually researched? This suite answers it. It runs against the worktree database as it
stands: D1's answer key (294 claims for Zafran Security and its five committee members) and D2's
seventeen stored display blocks (the six overview sections, the six insights sections, and Nick
Fisher's five contact sections). Nothing here seeds a claim or writes a block.

Three properties make it safe to keep in the ordinary suite rather than behind a live marker:

* **it never calls a model.** ``arv2_display_generate_on_read=False`` is pinned on the settings the
  app is built from, exactly as the other route suites pin it, so the display seam is a pure
  projection over the stored blocks. There is no runner to spend money;
* **it skips rather than fails when the data is absent.** A checkout whose database was never
  loaded (or was reset) has no answer key and no blocks; the walk says so and skips. A red here
  therefore always means the read surface changed, never that the machine differs;
* **it reads inside the rolled-back transaction** every other DB suite uses, so it cannot leave a
  row behind even though it only ever issues ``SELECT``s.

Both halves of every payload are checked: the pydantic model of contract v1 *and* the frontend's
own vendored Zod, through ``tests/api/contract_v1/oracle.py``. And the same five requests are made
**without** ``?contract=v1`` to prove the D3 ruling — the FI-2 payloads are still served untouched,
except on ``/workspace``, which is a new endpoint and serves v1 in both modes.

The five v1 payloads are dumped to ``.artifacts/d3-zafran/`` (git-ignored) as the track's record;
set ``CLUE_D3_DUMP=0`` to skip the write.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.answer_key import ZAFRAN_RUN_ID
from clue_api.frontend_read import FRONTEND_READ_PREFIX
from clue_api.frontend_read.contract_v1 import (
    AccountContactDetailV1,
    AccountContactSummaryV1,
    AccountDetailV1,
    AccountV1,
    AccountWorkspaceV1,
)
from clue_api.projections_app import create_projections_app
from clue_config import load_settings
from tests.api.contract_v1.oracle import zod_validate
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_WS = "ws_arv2_answer_key"
_BASE = f"{FRONTEND_READ_PREFIX}/accounts"
_ZAFRAN_DOMAIN = "zafran.io"
_NICK = "Nick Fisher"

#: Where the walk's payloads are written for the record. Git-ignored: this is evidence for the
#: close-out note, not a fixture anything asserts against.
_DUMP_DIR = Path(__file__).resolve().parents[2] / ".artifacts" / "d3-zafran"

#: The six overview sections in recipe order — the order the screen renders them in.
_OVERVIEW_SECTION_ORDER = (
    "what-they-do",
    "why-they-fit",
    "why-now",
    "buying-committee",
    "how-to-approach",
    "watch-outs",
)

#: The six insights sections in recipe order.
_INSIGHTS_SECTION_ORDER = (
    "buying-signals",
    "money-and-momentum",
    "tools-they-already-use",
    "how-they-sell",
    "contact-insights",
    "context-only",
)

#: The five contact-page sections in recipe order.
_CONTACT_SECTION_ORDER = (
    "why-this-person",
    "problem-right-now",
    "openers",
    "angles",
    "do-not-mention",
)

#: The buying committee D1 recorded for Zafran. Order is not asserted (the payload sorts by
#: persona rank, which the E4 assertions cover); membership is.
_COMMITTEE = {"Vari Kaur", "Nick Fisher", "Sanaz Yashar", "Ben Seri", "Tom Anthony"}

#: The three other accounts the answer-key workspace carries. None was researched.
_UNRESEARCHED = {"Cogent Security", "Harmonic Security", "UPTIQ, Inc."}

_PERSONAS = {"economic_buyer", "champion", "technical_evaluator", "user", "blocker"}


# --- harness ----------------------------------------------------------------------------------


def _app(conn: AsyncConnection):
    """The real projections app, flag on, DB seam bound to the test's rolled-back connection.

    ``arv2_display_generate_on_read=False`` is load-bearing: the composition root reads a real
    ``Secrets()``, so on a machine with ``OPENROUTER_API_KEY`` set (this one) the display seam would
    otherwise build a live runner and this walk would *spend money* rewriting D2's pages.
    """
    return create_projections_app(
        surface=None,  # type: ignore[arg-type]
        tool_invoker=None,  # type: ignore[arg-type]
        settings=load_settings(
            _env_file=None, frontend_read_enabled=True, arv2_display_generate_on_read=False
        ),
        conn_factory=conn_session_factory(conn),
        manage_db_lifespan=False,
    )


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def _get(conn: AsyncConnection, path: str, **params: Any) -> httpx.Response:
    async with _client(_app(conn)) as client:
        return await client.get(path, params=params, headers={"X-Workspace-Id": _WS})


async def _require_answer_key(conn: AsyncConnection) -> None:
    """Skip — never fail — when this checkout's database carries no answer key or no blocks."""
    claim = await conn.execute(
        text("SELECT 1 FROM claim WHERE run_id = :run_id LIMIT 1"), {"run_id": str(ZAFRAN_RUN_ID)}
    )
    if claim.first() is None:
        pytest.skip(
            "the D1 answer key is not loaded in this database "
            f"(no claim carries run_id {ZAFRAN_RUN_ID}); load it to run the Zafran walk"
        )


async def _zafran(conn: AsyncConnection) -> uuid.UUID:
    row = await conn.execute(
        text(
            "SELECT id FROM account_entity "
            "WHERE workspace_id = :ws AND primary_domain = :domain AND merged_into IS NULL"
        ),
        {"ws": _WS, "domain": _ZAFRAN_DOMAIN},
    )
    found = row.first()
    if found is None:
        pytest.skip(f"no account with primary_domain {_ZAFRAN_DOMAIN} in {_WS}")
    account_id = uuid.UUID(str(found[0]))

    block = await conn.execute(
        text(
            "SELECT 1 FROM display_block "
            "WHERE workspace_id = :ws AND subject_kind = 'account' AND subject_id = :id "
            "AND page = 'overview' AND superseded_at IS NULL LIMIT 1"
        ),
        {"ws": _WS, "id": str(account_id)},
    )
    if block.first() is None:
        pytest.skip(
            "Zafran has no live overview display_block in this database; "
            "run the D2 loader to write the display pages, then re-run the walk"
        )
    return account_id


async def _contact(conn: AsyncConnection, account_id: uuid.UUID, *, name: str) -> uuid.UUID:
    row = await conn.execute(
        text(
            "SELECT id FROM contact_entity "
            "WHERE workspace_id = :ws AND account_entity_id = :account AND full_name = :name "
            "AND merged_into IS NULL"
        ),
        {"ws": _WS, "account": str(account_id), "name": name},
    )
    found = row.first()
    if found is None:
        pytest.skip(f"no contact named {name} under Zafran in {_WS}")
    return uuid.UUID(str(found[0]))


def _dump(name: str, payload: Any) -> None:
    """Write one payload to ``.artifacts/d3-zafran/`` for the close-out record."""
    if os.environ.get("CLUE_D3_DUMP", "1") != "1":
        return
    _DUMP_DIR.mkdir(parents=True, exist_ok=True)
    (_DUMP_DIR / f"{name}.json").write_text(json.dumps(payload, indent=2, sort_keys=True))


def _cited_claim_ids(node: Any) -> set[str]:
    """Every claim id cited anywhere inside a served display block.

    Walks the payload rather than reading ``display_block.cited_claim_ids``: what the citation
    chips need is that the *served* block's ids all resolve, and the two can only agree by being
    compared to each other.
    """
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "claimIds" and isinstance(value, list):
                found.update(str(item) for item in value)
            else:
                found |= _cited_claim_ids(value)
    elif isinstance(node, list):
        for item in node:
            found |= _cited_claim_ids(item)
    return found


def _section_items(block: dict[str, Any], *, restricted: bool | None = None) -> int:
    """Item count over the block's sections, optionally filtered by ``restricted``."""
    return sum(
        len(section["items"])
        for section in block["sections"]
        if restricted is None or bool(section.get("restricted", False)) is restricted
    )


def _keys(block: dict[str, Any]) -> tuple[str, ...]:
    return tuple(section["key"] for section in block["sections"])


def _non_empty_sections(block: dict[str, Any]) -> list[str]:
    """Sections that actually say something — items, or an intro when the recipe yields prose."""
    return [
        section["key"] for section in block["sections"] if section["items"] or section.get("intro")
    ]


def _evidence_ids(payload: dict[str, Any]) -> set[str]:
    return {row["claimId"] for row in payload["researchEvidence"]}


def _missing(cited: Iterable[str], covered: set[str]) -> set[str]:
    return {claim_id for claim_id in cited if claim_id not in covered}


# --- the walk ---------------------------------------------------------------------------------


def test_the_zafran_walk_serves_five_contract_v1_payloads_from_the_real_data() -> None:
    """One pass over E1–E5 with the real answer key behind them, dumped for the record."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _require_answer_key(conn)
            account_id = await _zafran(conn)
            nick_id = await _contact(conn, account_id, name=_NICK)

            # --- E1: the accounts list ------------------------------------------------------
            response = await _get(conn, _BASE, contract="v1", limit=200)
            assert response.status_code == 200, response.text
            accounts = response.json()
            _dump("accounts", accounts)

            rows = {row["name"]: row for row in accounts["data"]}
            assert len(accounts["data"]) == 4, sorted(rows)
            assert set(rows) == {"Zafran Security"} | _UNRESEARCHED

            zafran_row = rows["Zafran Security"]
            assert zafran_row["id"] == str(account_id)
            assert zafran_row["researchStatus"] == "completed"
            assert zafran_row["researchStatusLabel"] == "Researched"
            assert zafran_row["websiteUrl"] == "https://zafran.io"
            for name in _UNRESEARCHED:
                assert rows[name]["researchStatus"] == "not_started", name
            # No `account.scoring.fit` claim exists anywhere in the answer key, so no row may
            # invent a band or a zero (ruling R7): the pair is null together, everywhere.
            for name, row in rows.items():
                assert row["overallFit"] is None, name
                assert row["fitScore"] is None, name
                AccountV1.model_validate(row)
                zod_validate(row, "AccountSchema")

            # --- E2: the account detail -----------------------------------------------------
            response = await _get(conn, f"{_BASE}/{account_id}", contract="v1")
            assert response.status_code == 200, response.text
            detail_body = response.json()
            _dump("detail", detail_body)
            detail = detail_body["data"]

            overview = detail["overviewDisplay"]
            assert overview["page"] == "overview"
            assert _keys(overview) == _OVERVIEW_SECTION_ORDER
            what_they_do = overview["sections"][0]
            assert what_they_do["key"] == "what-they-do"
            assert what_they_do["intro"], "the what-they-do section is served as an intro"
            assert len(_non_empty_sections(overview)) >= 5, _non_empty_sections(overview)

            committee = detail["buyingCommittee"]
            assert len(committee) == 5
            assert {member["name"] for member in committee} == _COMMITTEE
            assert {member["persona"] for member in committee} <= _PERSONAS

            covered = _evidence_ids(detail)
            assert covered, "the detail cites claims, so it must serve their evidence"
            assert not _missing(_cited_claim_ids(overview), covered)
            assert not _missing(
                {m["emailClaimId"] for m in committee if m["emailClaimId"] is not None}, covered
            )

            assert detail["activity"], "the answer-key run is itself activity"
            assert {row["actor"]["type"] for row in detail["activity"]} == {"clue"}
            assert detail["headcountLabel"]
            assert detail["revenueLabel"]
            assert detail["locationsLabel"]
            AccountDetailV1.model_validate(detail)
            zod_validate(detail, "AccountDetailSchema")

            # --- E3: the account workspace --------------------------------------------------
            response = await _get(conn, f"{_BASE}/{account_id}/workspace", contract="v1")
            assert response.status_code == 200, response.text
            workspace_body = response.json()
            _dump("workspace", workspace_body)
            workspace = workspace_body["data"]

            insights = workspace["insightsDisplay"]
            assert insights["page"] == "insights"
            assert _keys(insights) == _INSIGHTS_SECTION_ORDER
            # `insightSummary` counts items in *non-restricted* sections only — a watch-out is
            # context the marketer may not use, and counting it would overstate the page.
            unrestricted = _section_items(insights, restricted=False)
            assert unrestricted < _section_items(insights), "the restricted sections carry items"
            assert workspace["insightSummary"] == [f"{unrestricted} insights", "5 people"]
            assert workspace["artifacts"] == []
            assert workspace["insights"] == []
            assert not _missing(_cited_claim_ids(insights), _evidence_ids(workspace))
            AccountWorkspaceV1.model_validate(workspace)
            zod_validate(workspace, "AccountWorkspaceSchema")

            # --- E4: the contacts list ------------------------------------------------------
            response = await _get(conn, f"{_BASE}/{account_id}/contacts", contract="v1")
            assert response.status_code == 200, response.text
            contacts_body = response.json()
            _dump("contacts", contacts_body)
            contacts = contacts_body["data"]

            assert len(contacts) == 5
            assert contacts_body["meta"]["total"] == 5
            assert {row["name"] for row in contacts} == _COMMITTEE
            nick = next(row for row in contacts if row["id"] == str(nick_id))
            assert nick["persona"] == "economic_buyer"
            assert nick["personaTone"] == "olive"
            # The walk's one finding, pinned rather than papered over. Decision 13 (source map
            # §3.5/§3.6) reads the email chip off a `core.work_email` claim whose `value_json` is
            # the provider's `{address, status}` pair — the shape `AiArkEmailExport` insists on,
            # because "an address flattened away from its status/domainType pair is a claim nobody
            # can grade". No writer produces that shape yet: D1's answer key and FI-2's own
            # email-lookup writer both store the bare address string. So a real contact who *has*
            # an address is served `lookup`, which is the fail-closed direction (the screen offers
            # a lookup instead of showing an ungraded address as verified) but is not the screen
            # the ARV2 lane is aiming at. Recorded in the D3 close-out note as a writer gap, not a
            # reader change: flipping it is a product ruling about showing unverified addresses.
            assert nick["emailStatus"] == "lookup"
            assert nick.get("emailLabel") is None

            from clue_api.frontend_read.v1_shared import PERSONA_RANK

            ranks = [
                (PERSONA_RANK.index(row["persona"]) if row["persona"] in PERSONA_RANK else 99)
                for row in contacts
            ]
            assert ranks == sorted(ranks), [(r["name"], r["persona"]) for r in contacts]
            for row in contacts:
                AccountContactSummaryV1.model_validate(row)
                zod_validate(row, "AccountContactSummarySchema")

            # --- E5: the contact page -------------------------------------------------------
            response = await _get(conn, f"{_BASE}/{account_id}/contacts/{nick_id}", contract="v1")
            assert response.status_code == 200, response.text
            contact_body = response.json()
            _dump("contact-nick-fisher", contact_body)
            contact = contact_body["data"]

            page = contact["contactDisplay"]
            assert page["page"] == "contact"
            assert _keys(page) == _CONTACT_SECTION_ORDER
            openers = next(s for s in page["sections"] if s["key"] == "openers")
            assert openers["items"]
            for item in openers["items"]:
                assert item["sendLine"], item["id"]
                assert item["sendLine"]["text"]
            assert contact["tenureLabel"]
            assert contact["emailClaimId"]
            assert contact["linkedinLabel"] == "nicholastfisher"
            contact_covered = _evidence_ids(contact)
            assert not _missing(_cited_claim_ids(page), contact_covered)
            assert contact["emailClaimId"] in contact_covered
            AccountContactDetailV1.model_validate(contact)
            zod_validate(contact, "AccountContactDetailSchema")

    run_async(scenario())


def test_without_the_parameter_the_same_five_requests_still_serve_the_fi_2_shapes() -> None:
    """The D3 ruling, proven on the real data: v1 is opt-in, and E3 is v1 either way."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _require_answer_key(conn)
            account_id = await _zafran(conn)
            nick_id = await _contact(conn, account_id, name=_NICK)

            accounts = (await _get(conn, _BASE, limit=200)).json()
            row = next(item for item in accounts["data"] if item["id"] == str(account_id))
            assert "scores" in row
            assert "researchStatusLabel" not in row

            # The FI-2 detail and profile are served unenveloped; only the two list endpoints
            # carry `{data, meta}`. That asymmetry is FI-2's, and D3 left it exactly as it was.
            detail = (await _get(conn, f"{_BASE}/{account_id}")).json()
            assert "neutralFacts" in detail
            assert "overviewDisplay" not in detail

            contacts = (await _get(conn, f"{_BASE}/{account_id}/contacts")).json()["data"]
            assert contacts, "the FI-2 contacts reader serves the same committee"
            assert "roleOnCommittee" in contacts[0]

            profile = (await _get(conn, f"{_BASE}/{account_id}/contacts/{nick_id}")).json()
            assert "professionalFacts" in profile

            # E3 is a new endpoint: no FI-2 shape exists beside it, so it serves v1 in both modes.
            bare = (await _get(conn, f"{_BASE}/{account_id}/workspace")).json()
            pinned = (await _get(conn, f"{_BASE}/{account_id}/workspace", contract="v1")).json()
            assert bare == pinned
            assert "insightsDisplay" in bare["data"]

    run_async(scenario())
