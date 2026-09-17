"""D2 exit gate: Nick Fisher's contact page, written by the real model from the real answer key.

Every other display test proves a mechanism against a provider double. This one proves the whole
thing at once — the D1 answer key in a real database, the recipes read from their table, five
sections written concurrently by Luna over the live gateway, the floor, the blocks, the evidence
drawer — and it asserts the three properties that are not negotiable no matter what the model
says:

* **nothing unsafe leaks.** Every claim cited outside the restricted section was ``outreach_safe``
  when the section was written, which is what ``cited_flags`` records.
* **nothing is cited that cannot be opened.** Every ``claimIds`` entry on the page is a real claim
  id that the evidence resolver returns a card for.
* **the model never writes the machinery down.** No alias (``c7``) and no url survives into prose.

The page is written inside a rolled-back transaction: the persisted pages are
``scripts/generate_arv2_display.py``'s job, not a test's. The money is still spent — one contact
page is five calls, ≈$0.03 — so this test runs once, deliberately, and skips (never fails) when
there is no key or no answer key to write about.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator, Mapping
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.answer_key import ZAFRAN_RUN_ID
from clue_api.arv2.display.blocks import live_blocks
from clue_api.arv2.display.page import default_runner_factory, ensure_page
from clue_api.arv2.display.recipes import RESTRICTED_SECTION_KEYS, recipes_for
from clue_config import Secrets, Settings
from tests.arv2.conftest import require_secret
from tests.arv2.test_provider_ledger_db import FakeArtifacts

# The claim-store harness lives in a sibling test package; a fixture is only visible to a module
# that imports it, so re-export both (``require_claimstore_db`` depends on ``migrated_db``).
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

#: The workspace ``scripts/load_arv2_answer_key.py`` seeds.
WORKSPACE = "ws_arv2_answer_key"

#: The one person this test writes about. Five sections, all of them about a real researched human.
CONTACT_NAME = "Nick Fisher"

CONTACT_SECTIONS = tuple(recipe.section_key for recipe in recipes_for("contact"))

#: What an alias looks like in the payload the model is sent (``render.alias_table``). Seeing one
#: in prose means the model wrote its own scaffolding into the copy a marketer reads.
_ALIAS_IN_PROSE = re.compile(r"\bc\d+\b")


async def _skip_without_the_answer_key(conn: AsyncConnection) -> None:
    """Skip, naming the reason, when this database does not carry the D1 answer key.

    The inverse of ``test_answer_key_loader_db._skip_if_already_loaded``: that test needs a
    database *without* the key, and this one needs a database *with* it. Either way the honest
    answer to "the precondition is not met" is a skip that says which precondition, never a red.
    """
    loaded = (
        await conn.execute(
            text("SELECT 1 FROM claim WHERE run_id = :run_id LIMIT 1"), {"run_id": ZAFRAN_RUN_ID}
        )
    ).first()
    if loaded is None:
        pytest.skip(
            f"the ARV2 answer key (run {ZAFRAN_RUN_ID}) is not in this database; "
            "load it with scripts/load_arv2_answer_key.py first"
        )


async def _contact_id(conn: AsyncConnection) -> str:
    row = (
        await conn.execute(
            text(
                "SELECT id FROM contact_entity "
                "WHERE workspace_id = :workspace_id AND full_name = :full_name"
            ),
            {"workspace_id": WORKSPACE, "full_name": CONTACT_NAME},
        )
    ).scalar_one_or_none()
    if row is None:
        pytest.skip(f"no contact named {CONTACT_NAME!r} in {WORKSPACE}")
    return str(row)


_RESULT_ROWS_SQL = (
    "SELECT provider, extras_json FROM provider_call_ledger "
    "WHERE workspace_id = :workspace_id AND phase = 'result' ORDER BY recorded_at"
)


async def _result_row_count(conn: AsyncConnection) -> int:
    """How many provider result rows this workspace has, on the test's own transaction.

    Slice 1b: the page's spend lands on ``provider_call_ledger``, not on a JSONL file, and the
    spend factory this test injects is its own rolled-back connection — so the rows are counted
    here and roll back with everything else.
    """
    return int(
        (
            await conn.execute(
                text(
                    "SELECT count(*) FROM provider_call_ledger "
                    "WHERE workspace_id = :workspace_id AND phase = 'result'"
                ),
                {"workspace_id": WORKSPACE},
            )
        ).scalar_one()
    )


def _sections(block: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {section["key"]: section for section in block["sections"]}


def _cited_payloads(section: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    """Every payload of one composed section that can carry ``claimIds``."""
    for sentence in section.get("intro", []):
        yield sentence
        yield from sentence.get("segments", [])
    for item in section.get("items", []):
        for sentence in item.get("body", []):
            yield sentence
            yield from sentence.get("segments", [])
        send_line = item.get("sendLine")
        if send_line is not None:
            yield send_line


def _prose(section: Mapping[str, Any]) -> Iterator[str]:
    """Every string a marketer actually reads in one composed section."""
    for payload in _cited_payloads(section):
        yield str(payload.get("text", ""))
    for item in section.get("items", []):
        yield str(item.get("h2", ""))


def test_nick_fishers_contact_page_is_written_end_to_end_by_the_real_model(
    live_secrets: Secrets,
) -> None:
    require_secret(live_secrets, "openrouter_api_key")
    settings = Settings()

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            await _skip_without_the_answer_key(conn)
            contact_id = await _contact_id(conn)
            before = await _result_row_count(conn)

            result = await ensure_page(
                conn,
                workspace_id=WORKSPACE,
                subject_kind="contact",
                subject_id=contact_id,
                page="contact",
                settings=settings,
                runner_factory=default_runner_factory(settings, live_secrets),
                artifacts=FakeArtifacts(),
                spend_conn_factory=conn_session_factory(conn),
            )

            # -- 1. every section is accounted for: written, or honestly empty ------------------
            assert result.failed == ()
            assert result.regenerated == ()
            assert result.stale_served == ()
            assert set(result.generated) | set(result.skipped_empty) == set(CONTACT_SECTIONS)
            assert not set(result.generated) & set(result.skipped_empty)

            sections = _sections(result.display_block)
            assert tuple(sections) == CONTACT_SECTIONS
            for key in result.generated:
                assert sections[key]["items"], f"{key} was written but says nothing"
                assert not sections[key]["empty"]
            for key in result.skipped_empty:
                assert sections[key]["empty"]

            # -- 2. every citation opens: a uuid, and a card in the drawer ---------------------
            evidence_ids = {ref["claimId"] for ref in result.evidence}
            cited_anywhere: set[str] = set()
            for section in sections.values():
                for payload in _cited_payloads(section):
                    for claim_id in payload["claimIds"]:
                        uuid.UUID(claim_id)  # raises if the model's id survived unresolved
                        assert claim_id in evidence_ids
                        cited_anywhere.add(claim_id)
            assert cited_anywhere
            assert cited_anywhere <= set(result.cited_claim_ids)

            # -- 3. the floor: nothing unsafe is cited outside the restricted section ----------
            stored = await live_blocks(
                conn,
                workspace_id=WORKSPACE,
                subject_kind="contact",
                subject_id=contact_id,
                page="contact",
            )
            for key, block in stored.items():
                if key in RESTRICTED_SECTION_KEYS:
                    continue
                flags = block.body_json["cited_flags"]
                assert all(flags.values()), f"{key} cited an unsafe claim: {flags}"
            unsafe_evidence = {ref["claimId"] for ref in result.evidence if not ref["outreachSafe"]}
            for key, section in sections.items():
                if key in RESTRICTED_SECTION_KEYS:
                    continue
                section_cited = {
                    claim_id
                    for payload in _cited_payloads(section)
                    for claim_id in payload["claimIds"]
                }
                assert not section_cited & unsafe_evidence

            # -- 4. the contact page's send lines ---------------------------------------------
            if "openers" in result.generated:
                for item in sections["openers"]["items"]:
                    assert item["sendLine"] is not None, f"{item['id']} has no send line"
                    assert item["sendLine"]["text"].strip()

            # -- 5. no machinery in the copy ---------------------------------------------------
            for key, section in sections.items():
                for line in _prose(section):
                    assert "http" not in line.lower(), f"{key} put a url in the copy: {line!r}"
                    assert not _ALIAS_IN_PROSE.search(line), f"{key} wrote an alias: {line!r}"

            # -- 6. the money is real, metered, and on the ledger -------------------------------
            assert result.cost_usd > Decimal(0)
            assert await _result_row_count(conn) > before, (
                "the page was written but provider_call_ledger gained no result row"
            )
            results = (
                (
                    await conn.execute(
                        text(f"{_RESULT_ROWS_SQL} OFFSET :before"),
                        {"workspace_id": WORKSPACE, "before": before},
                    )
                )
                .mappings()
                .all()
            )
            assert all(row["extras_json"]["cost_source"] == "metered" for row in results)
            assert all(row["provider"] == "openrouter" for row in results)

    run_async(_run())
