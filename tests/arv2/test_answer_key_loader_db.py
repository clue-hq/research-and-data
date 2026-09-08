"""D1 exit gate: the answer keys load into a real database with entities, lineage and committee."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.answer_key import (
    PEOPLE_RUN_ID,
    WORK_EMAIL_KEY,
    ZAFRAN_MANIFEST,
    ZAFRAN_RUN_ID,
)
from clue_api.arv2.answer_key_loader import (
    ARV2_STANDIN_ICP_KEY,
    EMAIL_REPAIR_MARKER,
    AlreadyLoaded,
    load_answer_key,
    repair_email_claims,
    repair_research_rows,
)
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
                "probook.ai",
            }
            assert len(report.contacts) == 12
            assert {s["reason"] for s in report.skips} == {"not_found", "duplicate_persona"}
            assert len(report.artifacts) == 3
            ws = ZAFRAN_MANIFEST.workspace_id
            # The launch prerequisites (seam 1, master plan §5.1): a confirmed product set to pin
            # and a confirmed ICP artifact to launch against, plus its persona document.
            assert report.product_selection_version == 1
            documents = dict(
                (
                    await conn.execute(
                        text(
                            "SELECT path, status FROM brand_knowledge_document "
                            "WHERE workspace_id = :ws AND version = 1"
                        ),
                        {"ws": ws},
                    )
                ).all()
            )
            assert documents == {
                "audience/icp-clue-abm-buyers.md": "confirmed",
                "audience/persona-clue-abm-buyers.md": "ready",
            }
            assert set(report.documents) == set(documents)
            icp_blob = (
                await conn.execute(
                    text(
                        "SELECT a.storage_key FROM brand_knowledge_document d "
                        "JOIN artifact a ON a.storage_key = d.artifact_key "
                        "WHERE d.workspace_id = :ws AND d.kind = 'icp-definition'"
                    ),
                    {"ws": ws},
                )
            ).scalar_one()
            rendered = (tmp_path / icp_blob).read_text(encoding="utf-8")
            assert "confirmed_for_project_id: prj_arv2_answer_key" in rendered
            assert "product_selection_version: 1" in rendered
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
            # The ARV2 rows the accounts screens read a researched account through (D4-b task 6):
            # one run and one job, ARV2's own, driven to ``completed`` through the store.
            run = (
                (
                    await conn.execute(
                        text(
                            "SELECT run_id::text, project_id, brand_id, project_run_id::text, "
                            " icp_key, icp_version, product_selection_version, effort, "
                            " committee_cap, requested_by_user_id, status, "
                            " finished_at IS NOT NULL AS finished, icp_artifact_key "
                            "FROM arv2_research_run WHERE workspace_id = :ws"
                        ),
                        {"ws": ws},
                    )
                )
                .mappings()
                .one()
            )
            assert run["run_id"] == report.research.run_id
            assert run["project_id"] == ZAFRAN_MANIFEST.project_id
            assert run["project_run_id"] == str(ZAFRAN_MANIFEST.project_run_id)
            assert (run["icp_key"], run["icp_version"]) == (ARV2_STANDIN_ICP_KEY, 1)
            assert (run["effort"], run["committee_cap"]) == ("full", 5)
            assert run["product_selection_version"] == 1
            assert (run["status"], run["finished"]) == ("completed", True)
            # The ICP pin resolves to bytes that were actually stored, not to a bare key.
            assert (
                (tmp_path / run["icp_artifact_key"])
                .read_text(encoding="utf-8")
                .startswith("# ARV2 answer key — stand-in ICP")
            )
            jobs = (
                (
                    await conn.execute(
                        text(
                            "SELECT job_id::text, account_entity_id::text, status, "
                            " finished_at IS NOT NULL AS finished, finalization_json "
                            "FROM arv2_research_job WHERE workspace_id = :ws"
                        ),
                        {"ws": ws},
                    )
                )
                .mappings()
                .all()
            )
            # Exactly one: the other three accounts were only ever named by the run, and an
            # invented ``not_started`` job would say they had been launched.
            assert len(jobs) == 1
            job = jobs[0]
            assert job["job_id"] == report.research.job_id
            assert job["account_entity_id"] == report.accounts["zafran.io"]
            assert (job["status"], job["finished"]) == ("completed", True)
            assert job["finalization_json"] == {
                "claims_written": ZAFRAN_CLAIMS,
                "source": "answer-key",
            }
            assert report.research.runs_created == 1
            assert report.research.jobs_created == 1
            assert report.research.status == "completed"
            # …and nothing at all in the old lane's tables (founder ruling 2026-09-09).
            for table in (
                "entity_research_run",
                "entity_research_account_fleet",
                "entity_research_job",
                "entity_research_account_coverage",
            ):
                legacy = (
                    await conn.execute(
                        text(f"SELECT count(*) FROM {table} WHERE workspace_id = :ws"),  # noqa: S608
                        {"ws": ws},
                    )
                ).scalar_one()
                assert legacy == 0, table
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
            assert events.count("created") == 5  # one per seeded account, Probook included
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
    """D2's committee read resolves the loaded rows (source map §3.3).

    The ARV2 committee rule is the contacts under the account that hold at least one live claim
    (founder ruling 2026-09-09), so the loaded answer key's five Zafran people are exactly what the
    contacts table, the committee card and the generated pages all list. The manifest's people at
    other domains hang under their own accounts and must not appear here.
    """

    from clue_api.arv2.display.gather import committee_members

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            await _skip_if_already_loaded(conn)
            report = await load_answer_key(
                conn,
                storage=FsStorage(tmp_path),
                context_root=REPO / ".context",
                settings=_settings(),
            )
            members = await committee_members(
                conn,
                workspace_id=report.workspace_id,
                account_id=report.accounts["zafran.io"],
            )
            # The committee rows carry ids and names; the manifest is what says who they are.
            name_by_id = {
                report.contacts[person.linkedin_url]: person.name
                for person in ZAFRAN_MANIFEST.people
            }
            names = {name_by_id[member.id] for member in members}
            assert names == {"Nick Fisher", "Sanaz Yashar", "Vari Kaur", "Tom Anthony", "Ben Seri"}

    run_async(_run())


# -- the D4-b email repair ------------------------------------------------------------------------

_NICK_EMAIL_ROW = "zaf-084"


async def _live_work_email(conn: AsyncConnection, source_row_id: str) -> dict[str, object]:
    row = (
        (
            await conn.execute(
                text(
                    """
                    SELECT id, entity_id, value_json, write_markers, source_key, observed_at,
                           identity_binding::text AS identity_binding, use_class::text AS use_class,
                           source_tier, signal_priority, outreach_safe
                    FROM claim
                    WHERE workspace_id = :workspace_id AND field_key = :field_key
                      AND superseded_by IS NULL
                      AND write_markers->>'source_row_id' = :source_row_id
                    """
                ),
                {
                    "workspace_id": ZAFRAN_MANIFEST.workspace_id,
                    "field_key": WORK_EMAIL_KEY,
                    "source_row_id": source_row_id,
                },
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        pytest.skip(
            "this database carries no live core.work_email claim for the answer key's "
            f"{source_row_id} row; the repair test needs the loaded answer key"
        )
    return dict(row)


def test_repair_gives_a_bare_work_email_claim_the_providers_verdict() -> None:
    """D4-b task 4: the D1 rows gain the verdict without losing an atom of their provenance.

    The pre-D4-b shape is planted here rather than assumed, so the test says the same thing on a
    database that has already been repaired and on one that has not: it supersedes the live claim
    with the bare address string D1 wrote (``validate_field=False`` — the registry now refuses that
    shape, which is exactly the point), runs the repair, and reads the result.
    """

    async def _run() -> None:
        from clue_core import ClaimId
        from clue_research.claimstore import WorkspaceScope, claims_by_ids, supersede_claim

        async with rollback_conn(seed_pack=False) as conn:
            live = await _live_work_email(conn, _NICK_EMAIL_ROW)
            claim_id = ClaimId(uuid.UUID(str(live["id"])))
            original = (
                await claims_by_ids(
                    conn,
                    [claim_id],
                    scope=WorkspaceScope.private_for_workspace(ZAFRAN_MANIFEST.workspace_id),
                )
            )[claim_id]
            address = "nick@zafran.io"
            legacy = original.model_copy(
                update={"id": uuid.uuid4(), "value_json": address, "superseded_by": None}
            )
            await supersede_claim(conn, original.id, legacy, validate_field=False)

            report = await repair_email_claims(
                conn, context_root=REPO / ".context", settings=_settings()
            )
            # The planted row is always among them; a database that has not had the real repair
            # run against it yet still carries the other three, and they are repaired too.
            assert report.found >= 1
            assert report.repaired == report.found and report.skipped == []

            repaired = await _live_work_email(conn, _NICK_EMAIL_ROW)
            assert repaired["value_json"] == {
                "address": address,
                "status": "verified_smtp",
                "checked_at": "2026-08-31T07:52:05.000725",
            }
            # The provenance is the row's own, and the rewrite is visible in the claim forever.
            assert repaired["write_markers"][EMAIL_REPAIR_MARKER] == "d4b"
            assert repaired["write_markers"]["source_row_id"] == _NICK_EMAIL_ROW
            for column in (
                "entity_id",
                "source_key",
                "observed_at",
                "identity_binding",
                "use_class",
                "source_tier",
                "signal_priority",
                "outreach_safe",
            ):
                assert repaired[column] == live[column], column
            superseded = (
                await conn.execute(
                    text("SELECT superseded_by FROM claim WHERE id = :id"), {"id": legacy.id}
                )
            ).scalar_one()
            assert str(superseded) == str(repaired["id"])

            # Idempotent: a second pass finds no bare string left to repair.
            again = await repair_email_claims(
                conn, context_root=REPO / ".context", settings=_settings()
            )
            assert again == type(again)(found=0, repaired=0, skipped=[])

    run_async(_run())


# -- the D4-b research-row repair -----------------------------------------------------------------


def test_repair_writes_the_research_rows_once_on_an_already_loaded_database(tmp_path: Path) -> None:
    """``--repair-research-rows`` gives a pre-D4-b database the ARV2 pair, and only once.

    Written against whatever this database holds: on a loaded one it repairs the real rows, and on
    an empty one it loads the answer key first so there is something to repair. Either way the
    assertions are the same — one run, one job, ``completed``, and a second pass that creates
    nothing — which is exactly what idempotency on a deterministic id means.
    """

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            loaded = (
                await conn.execute(
                    text("SELECT 1 FROM claim WHERE run_id = :run_id LIMIT 1"),
                    {"run_id": ZAFRAN_RUN_ID},
                )
            ).first()
            if loaded is None:
                await load_answer_key(
                    conn,
                    storage=FsStorage(tmp_path),
                    context_root=REPO / ".context",
                    settings=_settings(),
                )
                # A fresh load already wrote them, so the repair must find nothing to do.
                expected_created = 0
            else:
                await conn.execute(
                    text("DELETE FROM arv2_research_job WHERE workspace_id = :ws"),
                    {"ws": ZAFRAN_MANIFEST.workspace_id},
                )
                await conn.execute(
                    text("DELETE FROM arv2_research_run WHERE workspace_id = :ws"),
                    {"ws": ZAFRAN_MANIFEST.workspace_id},
                )
                expected_created = 1

            first = await repair_research_rows(conn, storage=FsStorage(tmp_path))
            assert (first.runs_created, first.jobs_created) == (
                expected_created,
                expected_created,
            )
            assert first.status == "completed"
            assert first.claims_written > 0

            second = await repair_research_rows(conn, storage=FsStorage(tmp_path))
            assert (second.runs_created, second.jobs_created) == (0, 0)
            assert second.status == "completed"

            rows = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM arv2_research_job j JOIN arv2_research_run r "
                        "USING (run_id) WHERE j.workspace_id = :ws AND j.status = 'completed' "
                        "AND r.status = 'completed'"
                    ),
                    {"ws": ZAFRAN_MANIFEST.workspace_id},
                )
            ).scalar_one()
            assert rows == 1
            # The repair touches no legacy row: whatever the old loader left is exactly as it was.
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM entity_research_job WHERE workspace_id = :ws "
                        "AND state <> 'terminal'"
                    ),
                    {"ws": ZAFRAN_MANIFEST.workspace_id},
                )
            ).scalar_one() == 0

    run_async(_run())
