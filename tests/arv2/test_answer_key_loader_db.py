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
    EMAIL_REPAIR_MARKER,
    AlreadyLoaded,
    load_answer_key,
    repair_email_claims,
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


def test_committee_read_sees_the_five_members(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The existing governed committee read resolves the loaded rows (source map §3.3).

    The answer key's committee is five under the shipped R0 posture — verification off, per
    ``.env.example`` — because two of the five ``contact.role_on_committee`` rows are the run's own
    tier-4 synthesis, and ``active_merge_policy`` serves an unverified tier-4 claim as current truth
    only in that posture. With verification on, those two members are hidden until their rows are
    verified, and that is the platform's tier-4 eligibility rule, not a loader defect.
    """
    monkeypatch.setenv("CLUE_VERIFICATION_ENABLED", "false")

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
