"""The closing walk — the five contract-v1 payloads over the *real* Zafran data.

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
own vendored Zod, through ``tests/api/contract_v1/oracle.py``. The same five requests are also made
**without** ``?contract=v1``, which since 2026-09-09 must serve the identical body: the selector is
gone and there is only one contract to serve.

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
from clue_api.frontend_read.v1_shared import RESEARCH_STATUS_LABELS
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

#: The insights sections in recipe order.
_INSIGHTS_SECTION_ORDER = (
    "buying-signals",
    "money-and-momentum",
    "tools-they-already-use",
    "how-they-sell",
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
#: The four addresses AI Ark exported and verified over SMTP, plus the one person it found none
#: for. The answer key holds no fifth address, so a fifth would be an invention, not a finding.
_COMMITTEE_EMAILS = {
    "Vari Kaur": "vari@zafran.io",
    "Nick Fisher": "nick@zafran.io",
    "Sanaz Yashar": "sanaz@zafran.io",
    "Tom Anthony": "tom@zafran.io",
    "Ben Seri": None,
}

#: The three other accounts the answer-key workspace carries. None was researched.
_UNRESEARCHED = {"Cogent Security", "Harmonic Security", "UPTIQ, Inc."}

#: The personas as the wire serves them: display text, never the vocabulary value (D4-b
#: decision 5). The vocabulary itself still orders the table — see the ``ranks`` assertion.
_PERSONAS = {"Economic buyer", "Champion", "Technical evaluator", "User", "Blocker"}


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


def _block_personas(block: dict[str, Any]) -> set[str]:
    """Every persona stored inside a generated block — the chips and the item subjects.

    These are written into ``display_block.body_json`` at generation time and served verbatim, so
    they are what ``scripts/rewrite_display_persona_labels.py`` repaired on this database.
    """
    found: set[str] = set()
    for section in block["sections"]:
        for item in section["items"]:
            for ref in [*item.get("contactRefs", []), item.get("subject")]:
                persona = (ref or {}).get("persona")
                if persona is not None:
                    found.add(persona)
    return found


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
            response = await _get(conn, _BASE, limit=200)
            assert response.status_code == 200, response.text
            accounts = response.json()
            _dump("accounts", accounts)

            rows = {row["name"]: row for row in accounts["data"]}
            assert len(accounts["data"]) == 4, sorted(rows)
            assert set(rows) == {"Zafran Security"} | _UNRESEARCHED

            zafran_row = rows["Zafran Security"]
            assert zafran_row["id"] == str(account_id)
            # The status is ARV2's own ``arv2_research_job`` row (D4-b task 1), which the D1
            # loader now writes for Zafran (task 6) — so the walk is back to naming the state.
            assert zafran_row["researchStatus"] == "completed"
            assert zafran_row["researchStatusLabel"] == "Researched"
            assert (
                zafran_row["researchStatusLabel"]
                == RESEARCH_STATUS_LABELS[zafran_row["researchStatus"]]
            )
            assert zafran_row["websiteUrl"] == "https://zafran.io"
            # The revenue column reads its `core.revenue_band` claim as words. The answer key's
            # only stored band is `"10m_50m"`, which the table used to print verbatim at a
            # marketer (D4-b controller ruling 2).
            assert zafran_row["revenueBand"] == "$10M–50M"
            for name in _UNRESEARCHED:
                assert rows[name]["revenueBand"] == "Unknown", name
                assert rows[name]["researchStatus"] == "not_started", name
            # No `account.scoring.fit` claim exists anywhere in the answer key, so no row may
            # invent a band or a zero (ruling R7): the pair is null together, everywhere.
            for name, row in rows.items():
                assert row["overallFit"] is None, name
                assert row["fitScore"] is None, name
                AccountV1.model_validate(row)
                zod_validate(row, "AccountSchema")

            # --- E2: the account detail -----------------------------------------------------
            response = await _get(conn, f"{_BASE}/{account_id}")
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
            # The stored blocks speak display text too, because the one-shot rewrote the rows the
            # D2 lane wrote before the ruling. A vocabulary value here means either a block was
            # regenerated by an un-fixed runner or the one-shot has not been run on this checkout.
            assert _block_personas(overview) <= _PERSONAS, _block_personas(overview)

            committee = detail["buyingCommittee"]
            assert len(committee) == 5
            assert {member["name"] for member in committee} == _COMMITTEE
            assert {member["persona"] for member in committee} <= _PERSONAS
            # D4-b task 4: the four people AI Ark exported an SMTP-verified address for carry it
            # on the card; Ben Seri, whom the run never found an address for, carries null. The
            # claim id travels either way for everyone who *has* a work-email claim.
            assert {member["name"]: member["email"] for member in committee} == _COMMITTEE_EMAILS
            assert all(
                (member["emailClaimId"] is not None) is (member["email"] is not None)
                for member in committee
            ), [(m["name"], m["email"], m["emailClaimId"]) for m in committee]

            covered = _evidence_ids(detail)
            assert covered, "the detail cites claims, so it must serve their evidence"
            assert not _missing(_cited_claim_ids(overview), covered)
            assert not _missing(
                {m["emailClaimId"] for m in committee if m["emailClaimId"] is not None}, covered
            )

            assert detail["activity"], "the answer-key run is itself activity"
            assert {row["actor"]["type"] for row in detail["activity"]} == {"clue"}
            assert detail["headcountLabel"]
            assert detail["locationsLabel"]
            # The two labels D4-b taught to read their registry *objects* instead of rendering
            # them. Before the fix these served the pipeline's own dump —
            # "amount_max: 25000000; amount_min: 10000000; as_of: 2026-08-22; …" — at a marketer.
            # The values are the answer key's: `core.annual_revenue` is a provider band, and
            # `account.recent_funding` is the provider's list of rounds (whose objects carry no
            # currency of their own, hence the bare "60M" beside the total's "$130.5M").
            assert detail["revenueLabel"] == "$10M–25M"
            assert detail["fundingLabel"].startswith("Series C")
            # The round object carries no `currency`; its sibling total says USD, and the two are
            # the same account's funding in the same provider record — so the round borrows it
            # (D4-b controller ruling 1) rather than printing a bare "60M" beside "$130.5M".
            assert detail["fundingLabel"] == "Series C · $60M · $130.5M"
            AccountDetailV1.model_validate(detail)
            zod_validate(detail, "AccountDetailSchema")

            # --- E3: the account workspace --------------------------------------------------
            response = await _get(conn, f"{_BASE}/{account_id}/workspace")
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
            assert _block_personas(insights) <= _PERSONAS, _block_personas(insights)
            AccountWorkspaceV1.model_validate(workspace)
            zod_validate(workspace, "AccountWorkspaceSchema")

            # --- E4: the contacts list ------------------------------------------------------
            response = await _get(conn, f"{_BASE}/{account_id}/contacts")
            assert response.status_code == 200, response.text
            contacts_body = response.json()
            _dump("contacts", contacts_body)
            contacts = contacts_body["data"]

            assert len(contacts) == 5
            assert contacts_body["meta"]["total"] == 5
            assert {row["name"] for row in contacts} == _COMMITTEE
            nick = next(row for row in contacts if row["id"] == str(nick_id))
            # Display text on the wire; the tone still keys on the vocabulary value behind it.
            assert nick["persona"] == "Economic buyer"
            assert nick["personaTone"] == "olive"
            # D3's one finding, closed by D4-b task 4. The chip reads a `core.work_email` claim
            # whose value is the provider's `{address, status, checked_at}` — the shape
            # `AiArkEmailExport` insists on, because "an address flattened away from its
            # status/domainType pair is a claim nobody can grade". D1 stored the bare address, so
            # every real contact read `lookup`; the registry now declares the object, the loader
            # and the lookup writer produce it, and `--repair-emails` gave the loaded rows their
            # AI Ark verdict. The date is the provider's own check, not the day we wrote the row.
            assert nick["emailStatus"] == "available"
            assert nick["emailLabel"] == "nick@zafran.io"
            with_addresses = {row["name"] for row in contacts if row["emailStatus"] == "available"}
            assert with_addresses == set(_COMMITTEE_EMAILS) - {"Ben Seri"}
            # ``emailLabel`` is omitted, not null, when there is nothing to show (contract v1).
            assert {row["name"]: row.get("emailLabel") for row in contacts} == _COMMITTEE_EMAILS

            from clue_api.frontend_read.v1_shared import PERSONA_LABELS, PERSONA_RANK

            # The order is still the *vocabulary's* order — the rows now carry the label, so the
            # rank is looked up through it. That the two maps agree is the point.
            _rank_of = {PERSONA_LABELS[key]: index for index, key in enumerate(PERSONA_RANK)}
            ranks = [_rank_of.get(row["persona"], 99) for row in contacts]
            assert ranks == sorted(ranks), [(r["name"], r["persona"]) for r in contacts]
            for row in contacts:
                AccountContactSummaryV1.model_validate(row)
                zod_validate(row, "AccountContactSummarySchema")

            # --- E5: the contact page -------------------------------------------------------
            response = await _get(conn, f"{_BASE}/{account_id}/contacts/{nick_id}")
            assert response.status_code == 200, response.text
            contact_body = response.json()
            _dump("contact-nick-fisher", contact_body)
            contact = contact_body["data"]

            page = contact["contactDisplay"]
            assert page["page"] == "contact"
            assert _keys(page) == _CONTACT_SECTION_ORDER
            assert _block_personas(page) <= _PERSONAS, _block_personas(page)
            openers = next(s for s in page["sections"] if s["key"] == "openers")
            assert openers["items"]
            for item in openers["items"]:
                assert item["sendLine"], item["id"]
                assert item["sendLine"]["text"]
            assert contact["tenureLabel"]
            assert contact["emailClaimId"]
            # The date on the chip is AI Ark's own SMTP check (2026-08-31), not the day D1 wrote
            # the claim (2026-09-02) — the reader shows when the mailbox answered.
            assert contact["emailVerifiedAt"] == "2026-08-31"
            assert contact["linkedinLabel"] == "nicholastfisher"
            contact_covered = _evidence_ids(contact)
            assert not _missing(_cited_claim_ids(page), contact_covered)
            assert contact["emailClaimId"] in contact_covered
            AccountContactDetailV1.model_validate(contact)
            zod_validate(contact, "AccountContactDetailSchema")

    run_async(scenario())


def test_without_the_parameter_the_same_five_requests_serve_the_same_bodies() -> None:
    """One contract: ``?contract=`` selects nothing, so the parameter cannot change a payload."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _require_answer_key(conn)
            account_id = await _zafran(conn)
            nick_id = await _contact(conn, account_id, name=_NICK)

            for path, params in (
                (_BASE, {"limit": 200}),
                (f"{_BASE}/{account_id}", {}),
                (f"{_BASE}/{account_id}/workspace", {}),
                (f"{_BASE}/{account_id}/contacts", {}),
                (f"{_BASE}/{account_id}/contacts/{nick_id}", {}),
            ):
                bare = await _get(conn, path, **params)
                pinned = await _get(conn, path, **params, contract="v1")
                assert bare.status_code == pinned.status_code == 200, path
                assert bare.json() == pinned.json(), path

    run_async(scenario())
