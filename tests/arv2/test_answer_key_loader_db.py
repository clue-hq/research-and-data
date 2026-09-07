"""D1 exit gate: the answer keys load into a real database with entities, lineage and committee."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.answer_key import PEOPLE_RUN_ID, ZAFRAN_MANIFEST, ZAFRAN_RUN_ID
from clue_api.arv2.answer_key_loader import AlreadyLoaded, load_answer_key
from clue_config import Settings
from clue_storage.fs import FsStorage

# The claim-store harness lives in a sibling test package; a fixture is only visible to a module
# that imports it, so re-export both (``require_claimstore_db`` depends on ``migrated_db``).
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async

REPO = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.usefixtures("require_claimstore_db")

#: The Zafran file holds 174 rows, 5 of which map to nothing (four ``NOT FOUND`` values and one
#: unmappable second persona); the loader adds three derived committee-role rows so every person
#: the run gave a persona is a resolvable committee member. The person-depth file yields 122.
ZAFRAN_CLAIMS = 174 - 5 + 3
PEOPLE_CLAIMS = 119 + 3


def _settings() -> Settings:
    return Settings(_env_file=None, claim_write_lenient=True)


async def _skip_if_already_loaded(conn: AsyncConnection) -> None:
    """Skip, naming the reason, when this database already carries a committed answer key.

    The loader is one-shot per database by design, and the D1 exit-gate load commits into the same
    development database these tests point at. The tenant cannot simply be cleared first: the M8D
    coverage/finalization rows are append-only at the substrate (their trigger refuses a DELETE),
    which is the store saying a finished research run is history, not scratch space. So the honest
    precondition is a database without the answer key in it — a fresh/throwaway one, which is what
    CI and ``make db-smoke`` provide — and anything else is a skip that says so, never a red.
    """
    loaded = (
        await conn.execute(
            text("SELECT 1 FROM claim WHERE run_id = :run_id LIMIT 1"), {"run_id": ZAFRAN_RUN_ID}
        )
    ).first()
    if loaded is not None:
        pytest.skip(
            "the ARV2 answer key is already committed in this database "
            f"(run {ZAFRAN_RUN_ID}); this test needs a database without it"
        )


def test_load_writes_every_row_and_the_screen_prerequisites(tmp_path: Path) -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            await _skip_if_already_loaded(conn)
            report = await load_answer_key(
                conn,
                storage=FsStorage(tmp_path),
                context_root=REPO / ".context",
                settings=_settings(),
            )
            assert report.claims_written == ZAFRAN_CLAIMS + PEOPLE_CLAIMS
            assert set(report.accounts) == {
                "zafran.io",
                "cogent.com",
                "harmonic.security",
                "uptiq.ai",
            }
            assert len(report.contacts) == 12
            assert {s["reason"] for s in report.skips} == {"not_found", "duplicate_persona"}
            assert len(report.artifacts) == 3
            ws = ZAFRAN_MANIFEST.workspace_id
            counts = dict(
                (
                    await conn.execute(
                        text(
                            "SELECT run_id::text, count(*) FROM claim "
                            "WHERE workspace_id = :ws GROUP BY run_id"
                        ),
                        {"ws": ws},
                    )
                ).all()
            )
            assert counts[str(ZAFRAN_RUN_ID)] == ZAFRAN_CLAIMS
            assert counts[str(PEOPLE_RUN_ID)] == PEOPLE_CLAIMS
            lineage = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM run_lineage "
                        "WHERE workspace_id = :ws AND project_id = :p"
                    ),
                    {"ws": ws, "p": ZAFRAN_MANIFEST.project_id},
                )
            ).scalar_one()
            assert lineage == 2
            job = (
                await conn.execute(
                    text(
                        "SELECT state, finalization_outcome FROM entity_research_job "
                        "WHERE workspace_id = :ws"
                    ),
                    {"ws": ws},
                )
            ).one()
            assert tuple(job) == ("terminal", "completed")
            members = (
                await conn.execute(
                    text(
                        "SELECT cardinality(committee_member_ids), committee_status "
                        "FROM entity_research_account_coverage WHERE workspace_id = :ws"
                    ),
                    {"ws": ws},
                )
            ).one()
            assert tuple(members) == (5, "complete")
            events = (
                (
                    await conn.execute(
                        text(
                            "SELECT kind FROM account_activity_event "
                            "WHERE workspace_id = :ws ORDER BY occurred_at"
                        ),
                        {"ws": ws},
                    )
                )
                .scalars()
                .all()
            )
            assert events.count("created") == 4
            assert "updated" in events and "contacts" in events
            unsafe = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM claim "
                        "WHERE workspace_id = :ws AND outreach_safe = false"
                    ),
                    {"ws": ws},
                )
            ).scalar_one()
            # Zafran's 12 unsafe rows minus the NOT FOUND one, plus one person row.
            assert unsafe == 11 + 1
            media = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM claim "
                        "WHERE workspace_id = :ws AND artifact_key IS NOT NULL"
                    ),
                    {"ws": ws},
                )
            ).scalar_one()
            assert media == 21
            with pytest.raises(AlreadyLoaded):
                await load_answer_key(
                    conn,
                    storage=FsStorage(tmp_path),
                    context_root=REPO / ".context",
                    settings=_settings(),
                )

    run_async(_run())


def test_committee_read_sees_the_five_members(tmp_path: Path) -> None:
    """The existing governed committee read resolves the loaded rows (source map §3.3)."""
    from clue_api.frontend_read.committee import read_governed_committee
    from clue_core import EntityId
    from clue_research.membership import memberships_for_accounts

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            await _skip_if_already_loaded(conn)
            report = await load_answer_key(
                conn,
                storage=FsStorage(tmp_path),
                context_root=REPO / ".context",
                settings=_settings(),
            )
            zafran = EntityId(uuid.UUID(report.accounts["zafran.io"]))
            memberships = await memberships_for_accounts(
                conn, workspace_id=report.workspace_id, account_ids=[zafran]
            )
            committee, _policy = await read_governed_committee(
                conn,
                account_id=zafran,
                workspace_id=report.workspace_id,
                memberships=list(memberships[zafran]),
            )
            # ``GovernedCommitteeContact`` carries ids, not names: the manifest is what names them.
            name_by_id = {
                report.contacts[person.linkedin_url]: person.name
                for person in ZAFRAN_MANIFEST.people
            }
            names = {name_by_id[str(member_id)] for member_id in committee.members}
            assert names == {"Nick Fisher", "Sanaz Yashar", "Vari Kaur", "Tom Anthony", "Ben Seri"}

    run_async(_run())
