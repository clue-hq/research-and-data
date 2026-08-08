"""FI-2 slice 0 — the canonical fixture: **two projects, one account** (spec §10).

One workspace ``W``. Project **A** *discovers* ``acme.com`` through the real DISCOVERY phase
(channel → admission gate → identity → claims). Project **B** then *imports* the same company
through the real import pipeline. The whole point of slice 0 is what happens where those two paths
meet:

* the account is **one** ``account_entity`` — workspace-global, never a per-project copy (R1);
* what the projects own is **membership** — ``project_account``, one row per project, each recording
  the channel that brought it in (P1 / §2);
* every claim either path wrote back-joins to *its* project through ``run_lineage`` (P2 / §3);
* the second sighting *teaches* the survivor instead of being discarded (H2 / §8.2);
* a third, name-only sighting reaches human review instead of minting a duplicate (H1 / §8.1);
* and a human merge moves the loser's memberships onto the survivor (§2), so a project's target
  list never points at a merged-away account.

Each test rebuilds the fixture inside its own rolled-back transaction (``_build_two_projects``), so
they neither see nor leave each other's rows. Every count and every read is **workspace-scoped** —
this suite shares a database with suites that commit, and an unscoped ``count(*)`` would make it
fail for reasons that have nothing to do with FI-2.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    AccountStatus,
    EntityId,
    EntityType,
    ICPCreatedFrom,
    PhaseContext,
    PhaseStatus,
    ProjectPhase,
    RunId,
    new_project_run_id,
    new_run_id,
)
from clue_research.discovery_scoring import (
    AdmissionStatus,
    ChannelRegistry,
    DiscoveryPhaseHandler,
    admit,
)
from clue_research.discovery_scoring.discovery import CandidateHypothesis
from clue_research.discovery_scoring.phases import discovery_run_id
from clue_research.icp import create_icp_spec
from clue_research.identity import get_account, insert_account_entity, mark_merged
from clue_research.membership import projects_for_accounts
from clue_research.stage0 import ImportRow, import_accounts, import_batch_run_id
from clue_spine import Project
from tests._run_lineage import assert_written_claims_are_attributable
from tests._workspace import seed_phase_run, seed_project, seed_workspace
from tests.discovery_scoring.conftest import const_channel, record
from tests.stage0._fakes import build_confirmed_icp
from tests.stage0.conftest import rollback_conn

from .conftest import run_async

pytestmark = pytest.mark.usefixtures("require_integration_db")

_WS = "fi2-slice0-two-projects"
_ACCOUNT_DOMAIN = "acme.com"
_DISCOVERED_NAME = "Acme Corporation"
_IMPORTED_NAME = "Acme Corp"
# A fixed batch id (not a fresh one per run) so the import's run id is *derivable* by the test:
# ``import_batch_run_id`` is a uuid5 of it. Safe only because every test here runs in an
# always-rolled-back transaction — nothing commits, so two runs of this module can never collide on
# the batch's idempotency key.
_IMPORT_BATCH_ID = "fi2-slice0-canonical"


# --- the fixture ------------------------------------------------------------
@dataclass(frozen=True)
class TwoProjects:
    """The canonical fixture's ids — what the assertions below are written against."""

    workspace_id: str
    project_a: Project
    project_b: Project
    account_id: EntityId
    client_entity_id: EntityId
    discovery_ctx: PhaseContext
    discovery_run: RunId
    import_run: RunId


def _session_factory(
    conn: AsyncConnection,
) -> Callable[[], AbstractAsyncContextManager[AsyncConnection]]:
    """Hand the phase handler the test's rollback connection (it must not open its own)."""

    @asynccontextmanager
    async def _session() -> AsyncIterator[AsyncConnection]:
        yield conn

    return _session


async def _build_two_projects(conn: AsyncConnection) -> TwoProjects:
    """Project A discovers ``acme.com``; project B then imports it. Both through the real paths.

    Nothing here is a shortcut around production: A runs the actual ``DiscoveryPhaseHandler`` (only
    its *channel* is a double, because a real channel is a paid network call), and B runs the actual
    ``import_accounts`` pipeline.
    """
    workspace_id = await seed_workspace(conn, _WS)
    project_a = await seed_project(conn, workspace_id, name="Project A (discovery)")
    project_b = await seed_project(conn, workspace_id, name="Project B (import)")

    # --- A: discovery -------------------------------------------------------
    await create_icp_spec(
        conn,
        workspace_id=workspace_id,
        icp_key="discovery",
        created_from=ICPCreatedFrom.SYNTHESIS,
        discovery_strategy={"channels": ["exa"], "static_queries": {"exa": ["series-b saas"]}},
        activate=True,
    )
    ctx = PhaseContext(
        project_run_id=new_project_run_id(),
        project_id=project_a.project_id,
        brand_id=project_a.brand_id,
        phase=ProjectPhase.DISCOVERY,
        workspace_id=workspace_id,
        icp_key="discovery",
        icp_version=1,
    )
    await seed_phase_run(conn, ctx)
    handler = DiscoveryPhaseHandler(
        channels=ChannelRegistry(
            (
                const_channel(
                    "exa", [record("exa:acme", domain=_ACCOUNT_DOMAIN, name=_DISCOVERED_NAME)]
                ),
            )
        ),
        session_factory=_session_factory(conn),
    )
    phase_result = await handler.run(ctx)
    assert phase_result.status is PhaseStatus.COMPLETED
    assert phase_result.payload["admitted"] == 1
    discovered = await _account_by_domain(conn, workspace_id, _ACCOUNT_DOMAIN)
    assert discovered is not None

    # --- B: import ----------------------------------------------------------
    client_entity_id = await insert_account_entity(
        conn,
        canonical_name="The Client",
        primary_domain="client.example",
        status=AccountStatus.ACTIVE,
        workspace_id=workspace_id,
    )
    icp_b = await build_confirmed_icp(conn, workspace_id=workspace_id, icp_key="import")
    import_result = await import_accounts(
        conn,
        [
            ImportRow(
                row_index=1,
                name=_IMPORTED_NAME,
                domain=_ACCOUNT_DOMAIN,
                aliases=("ACME Worldwide",),
                registry_ids={"DUNS": "12-345-6789"},
                geo={"country": "US"},
            )
        ],
        icp_b,
        workspace_id=workspace_id,
        client_entity_id=client_entity_id,
        import_batch_id=_IMPORT_BATCH_ID,
        project_id=project_b.project_id,
    )
    assert import_result.unresolved == ()
    assert [row.account_entity_id for row in import_result.resolved] == [discovered]

    return TwoProjects(
        workspace_id=workspace_id,
        project_a=project_a,
        project_b=project_b,
        account_id=discovered,
        client_entity_id=client_entity_id,
        discovery_ctx=ctx,
        discovery_run=discovery_run_id(ctx),
        import_run=import_batch_run_id(_IMPORT_BATCH_ID),
    )


# --- workspace-scoped readers (never an unscoped count — the shared-DB hazard) ---
async def _account_by_domain(
    conn: AsyncConnection, workspace_id: str, domain: str
) -> EntityId | None:
    rows = (
        await conn.execute(
            text(
                "SELECT id FROM account_entity "
                "WHERE workspace_id = :ws AND primary_domain = :domain"
            ),
            {"ws": workspace_id, "domain": domain},
        )
    ).scalars()
    ids = [EntityId(value) for value in rows]
    assert len(ids) <= 1, f"{domain} resolved to {len(ids)} accounts in {workspace_id}"
    return ids[0] if ids else None


async def _live_accounts(conn: AsyncConnection, workspace_id: str) -> set[EntityId]:
    """Every un-merged account of the workspace (the ids a duplicate would show up in)."""
    rows = (
        await conn.execute(
            text("SELECT id FROM account_entity WHERE workspace_id = :ws AND merged_into IS NULL"),
            {"ws": workspace_id},
        )
    ).scalars()
    return {EntityId(value) for value in rows}


async def _membership(
    conn: AsyncConnection, workspace_id: str, account_id: EntityId
) -> tuple[tuple[str, str], ...]:
    """``(project_id, added_via)`` for one account, oldest membership first."""
    rows = (
        await conn.execute(
            text(
                "SELECT project_id, added_via FROM project_account "
                "WHERE workspace_id = :ws AND account_entity_id = :account "
                "ORDER BY added_at, project_id"
            ),
            {"ws": workspace_id, "account": account_id},
        )
    ).all()
    return tuple((str(project_id), str(added_via)) for project_id, added_via in rows)


async def _claim_runs_by_project(
    conn: AsyncConnection, workspace_id: str
) -> dict[str | None, set[uuid.UUID]]:
    """Group every claim about **any account of this workspace** by the project its run resolves to.

    A ``None`` key means the claim's ``run_id`` has no ``run_lineage`` row *or* has one with no
    project — i.e. an unattributable claim, which is exactly what P2 exists to prevent.

    The scope is the workspace's *entities*, not ``claim.workspace_id``: that column is the M2.5
    reuse-class tenant binding, and a DB CHECK forces it ``NULL`` on every ``public_footprint``
    claim (``core.claim``'s "Reuse-class ⟺ tenant binding" invariant). Filtering on it would
    silently drop the public claims — which is most of what these two paths write — leaving the
    sweep *vacuous*, not stronger (verified: with ``WHERE c.workspace_id = :ws`` this test fails
    with an empty partition). Scoping through ``account_entity.workspace_id`` is the honest
    workspace filter: it covers the target account *and* the client entity, and ``_WS`` is unique
    to this module, so it can never see another suite's rows.
    """
    rows = (
        await conn.execute(
            text(
                "SELECT DISTINCT c.run_id, l.project_id "
                "FROM claim c LEFT JOIN run_lineage l ON l.run_id = c.run_id "
                "WHERE c.entity_id IN "
                "  (SELECT id FROM account_entity WHERE workspace_id = :ws)"
            ),
            {"ws": workspace_id},
        )
    ).all()
    grouped: dict[str | None, set[uuid.UUID]] = {}
    for run_id, project_id in rows:
        key = None if project_id is None else str(project_id)
        grouped.setdefault(key, set()).add(uuid.UUID(str(run_id)))
    return grouped


# --- (a) one account --------------------------------------------------------
def test_both_entry_paths_converge_on_one_account_entity() -> None:
    """(a) Discovery and import land on the **same** ``account_entity`` — one spine, not a copy."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            fixture = await _build_two_projects(conn)

            # `_account_by_domain` itself asserts the domain resolves to at most one account; this
            # pins that it resolved to exactly the id both paths reported.
            by_domain = await _account_by_domain(conn, fixture.workspace_id, _ACCOUNT_DOMAIN)
            assert by_domain == fixture.account_id
            # The workspace holds the client and the one target account — no second acme.
            assert await _live_accounts(conn, fixture.workspace_id) == {
                fixture.client_entity_id,
                fixture.account_id,
            }

    run_async(_run())


# --- (b) membership ---------------------------------------------------------
def test_membership_records_both_channels_with_the_discovering_project_first() -> None:
    """(b) Exactly two memberships — ``(A,'discovered')`` and ``(B,'imported')`` — and
    ``projects_for_accounts`` orders A first, so A is the account's ``primaryProjectId``."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            fixture = await _build_two_projects(conn)

            assert await _membership(conn, fixture.workspace_id, fixture.account_id) == (
                (fixture.project_a.project_id, "discovered"),
                (fixture.project_b.project_id, "imported"),
            )
            lens = await projects_for_accounts(
                conn, workspace_id=fixture.workspace_id, account_ids=[fixture.account_id]
            )
            assert lens[fixture.account_id] == (
                fixture.project_a.project_id,
                fixture.project_b.project_id,
            )

    run_async(_run())


# --- (c) claim → project ----------------------------------------------------
def test_every_claim_both_paths_wrote_back_joins_to_its_own_project() -> None:
    """(c) P2's whole contract on the canonical fixture: the discovery claims resolve to A, the
    import claims resolve to B, and **no** claim about this account is unattributable."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            fixture = await _build_two_projects(conn)

            await assert_written_claims_are_attributable(
                conn,
                fixture.discovery_run,
                kind="discovery",
                workspace_id=fixture.workspace_id,
                project_id=fixture.project_a.project_id,
                project_run_id=fixture.discovery_ctx.project_run_id,
            )
            # Import is not run-scoped (it has no project_run of its own), so it attributes to the
            # project the caller supplied and to no run.
            await assert_written_claims_are_attributable(
                conn,
                fixture.import_run,
                kind="import",
                workspace_id=fixture.workspace_id,
                project_id=fixture.project_b.project_id,
                project_run_id=None,
            )

            # The sweep: partition *every* claim in the workspace by the project its run resolves
            # to — not merely the acme account's, so a stray unattributable write anywhere the two
            # paths touched (the client entity included) still fails this test.
            by_project = await _claim_runs_by_project(conn, fixture.workspace_id)
            unattributed = by_project.get(None)
            assert unattributed is None, (
                f"claims in {fixture.workspace_id} whose run resolves to no project: {unattributed}"
            )
            assert set(by_project) == {
                fixture.project_a.project_id,
                fixture.project_b.project_id,
            }
            assert fixture.discovery_run in by_project[fixture.project_a.project_id]
            assert fixture.import_run in by_project[fixture.project_b.project_id]

    run_async(_run())


# --- (d) H2: the second sighting teaches the survivor -----------------------
def test_the_imports_observation_enriched_the_account_discovery_created() -> None:
    """(d) H2 (§8.2): B's row is not discarded onto the floor — its alias, the registry id and the
    geo A never had are absorbed, while A's canonical name is left alone."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            fixture = await _build_two_projects(conn)

            account = await get_account(conn, fixture.account_id)
            assert account is not None
            assert account.canonical_name == _DISCOVERED_NAME  # never renamed by a sighting
            assert {"acme corp", "acme worldwide"} <= set(account.aliases)
            assert account.registry_ids["DUNS"] == "123456789"  # canonicalized on the way in
            assert account.hq_geo == {"country": "US"}

    run_async(_run())


# --- (e) H1: a name-only re-encounter reaches review ------------------------
def test_a_name_only_re_encounter_reaches_review_instead_of_duplicating() -> None:
    """(e) H1 (§8.1): the discovery-minted account carries an embedding and its aliases, so meeting
    the same company again with **no domain** scores into the review band — no second entity."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            fixture = await _build_two_projects(conn)
            before = await _live_accounts(conn, fixture.workspace_id)

            re_encounter = await admit(
                conn,
                CandidateHypothesis(
                    matched_channel="firecrawl",
                    source_record_ref="rec:acme-name-only",
                    raw_name=_DISCOVERED_NAME,
                    matched_signal="series-b saas",
                    resolver_confidence=0.8,
                ),
                new_run_id(),
                workspace_id=fixture.workspace_id,
                project_id=fixture.project_a.project_id,
            )

            assert re_encounter.status is AdmissionStatus.NEEDS_REVIEW
            assert re_encounter.review_task_id is not None
            assert await _live_accounts(conn, fixture.workspace_id) == before
            # A review-band candidate has no entity yet, so it joins no project until a human
            # resolves it (the task carries the project — FI-2 slice 0, Task 5).
            assert await _membership(conn, fixture.workspace_id, fixture.account_id) == (
                (fixture.project_a.project_id, "discovered"),
                (fixture.project_b.project_id, "imported"),
            )

    run_async(_run())


# --- (f) merged-loser membership re-pointing --------------------------------
def test_a_merge_repoints_the_losers_membership_onto_the_survivor() -> None:
    """(f) §2: a genuinely distinct account, discovered by a *third* project, is human-merged into
    acme — its membership moves to the survivor and the merged-away account keeps none."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            fixture = await _build_two_projects(conn)
            project_c = await seed_project(
                conn, fixture.workspace_id, name="Project C (the duplicate's discoverer)"
            )

            # A real second company, not a near-duplicate: its own domain, its own name. Only a
            # human (or a strong-key match this pair does not have) can decide these are one.
            other = await admit(
                conn,
                CandidateHypothesis(
                    matched_channel="exa",
                    source_record_ref="rec:zephyr",
                    raw_name="Zephyr Dynamics",
                    candidate_domain="zephyr.example",
                    matched_signal="series-b saas",
                    resolver_confidence=0.8,
                ),
                new_run_id(),
                workspace_id=fixture.workspace_id,
                project_id=project_c.project_id,
            )
            assert other.status is AdmissionStatus.ADMITTED
            loser = other.account_entity_id
            assert loser is not None and loser != fixture.account_id
            assert await _membership(conn, fixture.workspace_id, loser) == (
                (project_c.project_id, "discovered"),
            )

            await mark_merged(conn, EntityType.ACCOUNT, loser, fixture.account_id)

            assert await _membership(conn, fixture.workspace_id, loser) == ()
            assert await _membership(conn, fixture.workspace_id, fixture.account_id) == (
                (fixture.project_a.project_id, "discovered"),
                (fixture.project_b.project_id, "imported"),
                (project_c.project_id, "discovered"),
            )
            # The lens agrees, and A is still the primary project (the merge does not rewrite it).
            lens = await projects_for_accounts(
                conn, workspace_id=fixture.workspace_id, account_ids=[fixture.account_id]
            )
            assert lens[fixture.account_id][0] == fixture.project_a.project_id
            assert set(lens[fixture.account_id]) == {
                fixture.project_a.project_id,
                fixture.project_b.project_id,
                project_c.project_id,
            }

    run_async(_run())
