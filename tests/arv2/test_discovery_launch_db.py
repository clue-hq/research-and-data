"""R4's launch against the real tables: one run pinned to the project's ICP, replayable, offered.

The discovery launch is the same authority boundary R2's is, applied to a different act: it says
*which document* a long list will be built from, *how many* companies were asked for, and *which*
of the document's hard gates the provider filters on — and everything the driver later spends is
spent against that row. So the same three properties are pinned here: the run is deterministic (the
same request is one run, not two), every refusal is typed and named, and the fleet is told only
after the rows are committed.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.discovery_launch import (
    ARV2_DISCOVERY_DEDUP_PREFIX,
    ARV2_DISCOVERY_TASK_PRIORITY,
    Arv2DiscoveryRefused,
    Arv2DiscoveryRequest,
    DbArv2DiscoveryService,
    enqueue_discovery_run,
    launch_arv2_discovery,
    read_pinned_icp,
)
from clue_api.arv2.discovery_request import DiscoveryBrief2
from clue_api.arv2.discovery_store import (
    end_discovery_run,
    read_discovery_run,
    record_wake_turn,
    release_discovery_for_turn,
)
from clue_db import db_lifespan
from clue_fleet import FleetTaskKind
from clue_research.claimstore import load_core_pack
from clue_storage.fs import FsStorage
from tests._workspace import seed_project
from tests.arv2.icp_fixture import (
    ICP_KEY,
    USER_ID,
    FakeQueue,
    IcpFixture,
    seed_icp_fixture,
    settings_for,
)
from tests.arv2.test_discovery_request import _brief

# The claim-store harness lives in a sibling test package; a fixture is only visible to a module
# that imports it, so re-export both (``require_claimstore_db`` depends on ``migrated_db``).
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

#: The brief the Head of ABM wrote (spec 2026-09-30 §3), as the run row stores it.
BRIEF = _brief().model_dump(mode="json")


def _settings(*, enabled: bool = True) -> Any:
    return settings_for(arv2_discovery_enabled=enabled)


def _request(fixture: IcpFixture, **overrides: Any) -> Arv2DiscoveryRequest:
    payload: dict[str, Any] = {
        "workspace_id": fixture.workspace_id,
        "project_id": fixture.project_id,
        "requested_by_user_id": USER_ID,
        "request_key": "turn-action:ask-1",
        "target_count": 20,
        "brief": DiscoveryBrief2.model_validate(BRIEF),
    }
    payload.update(overrides)
    return Arv2DiscoveryRequest(**payload)


async def _seed_turn(
    conn: AsyncConnection, fixture: IcpFixture, thread_id: str, *, thread_exists: bool = False
) -> UUID:
    """One ``agent_turn_submission`` on ``thread_id``, submitted by the fixture's user.

    Direct SQL (the ``test_chat_upload_tables_db`` shape): the launch reads only the turn's thread
    and submitter, so the smallest chain that satisfies the submission's foreign keys wins.
    ``thread_exists`` adds a later turn to a thread an earlier call seeded.
    """
    ws = fixture.workspace_id
    sha = uuid4().hex + uuid4().hex
    key = f"{ws}/{sha}"
    await conn.execute(
        text(
            "INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, "
            "size_bytes) VALUES (:key, :ws, :sha, 'text/plain', 3)"
        ),
        {"key": key, "ws": ws, "sha": sha},
    )
    onboarding_input_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO onboarding_input (id, workspace_id, brand_id, kind, artifact_key, "
            "content_sha256, actor) VALUES (:id, :ws, :brand, 'user_turn', :key, :sha, 'human')"
        ),
        {"id": onboarding_input_id, "ws": ws, "brand": fixture.brand_id, "key": key, "sha": sha},
    )
    if not thread_exists:
        await conn.execute(
            text("INSERT INTO agent_thread (id, workspace_id, project_id) VALUES (:id, :ws, :p)"),
            {"id": thread_id, "ws": ws, "p": fixture.project_id},
        )
    # One membership per user and workspace: a later turn reuses the first turn's.
    membership_id = (
        await conn.execute(
            text(
                "SELECT membership_id FROM workspace_membership "
                "WHERE workspace_id = :ws AND user_id = :user"
            ),
            {"ws": ws, "user": USER_ID},
        )
    ).scalar_one_or_none()
    if membership_id is None:
        membership_id = f"member_{uuid4().hex[:12]}"
        await conn.execute(
            text(
                "INSERT INTO workspace_membership (membership_id, workspace_id, user_id, "
                "role_key, status, activated_at) VALUES (:m, :ws, :user, 'owner', 'active', now())"
            ),
            {"m": membership_id, "ws": ws, "user": USER_ID},
        )
    turn_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO agent_turn_submission (turn_id, workspace_id, project_id, thread_id, "
            "submitted_by_user_id, submitted_via_membership_id, onboarding_input_id, "
            "message_artifact_key, message_sha256) "
            "VALUES (:turn, :ws, :p, :thread, :user, :m, :onb, :key, :sha)"
        ),
        {
            "turn": turn_id,
            "ws": ws,
            "p": fixture.project_id,
            "thread": thread_id,
            "user": USER_ID,
            "m": membership_id,
            "onb": onboarding_input_id,
            "key": key,
            "sha": sha,
        },
    )
    return turn_id


def test_a_launch_creates_one_run_pinned_to_the_projects_icp_and_records_lineage(
    tmp_path: Any,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            fixture = await seed_icp_fixture(conn, storage)

            receipt = await launch_arv2_discovery(
                conn,
                _request(fixture),
                settings=_settings(),
                storage=storage,
            )

            run = await read_discovery_run(conn, run_id=receipt.run_id)
            assert run is not None
            assert run.icp_artifact_sha256 == fixture.icp_artifact_sha256
            assert run.icp_artifact_key == fixture.icp_artifact_key
            assert run.icp_key == ICP_KEY and run.icp_version == 1
            assert run.brand_id == fixture.brand_id
            assert run.project_run_id == receipt.project_run_id
            assert run.requested_by_user_id == USER_ID
            # The brief is the agent's, stored whole; nothing is compiled out of the document and
            # there is no relaxed pass. Nothing is asked of the provider yet: the searches record
            # their asks as they run.
            assert run.target_count == 20 and run.asked is None
            assert run.brief == BRIEF and run.source == "websets"
            assert run.relaxed_enabled is False
            assert run.criteria_gate_keys == ()
            assert run.status == "not_started"
            assert receipt.replayed is False and receipt.to_enqueue is True
            assert receipt.workspace_id == fixture.workspace_id

            lineage = (
                await conn.execute(
                    text(
                        "SELECT kind, project_id, project_run_id FROM run_lineage WHERE run_id = :r"
                    ),
                    {"r": receipt.run_id},
                )
            ).one()
            assert tuple(lineage) == ("discovery", fixture.project_id, receipt.project_run_id)

            # The offer is the caller's, made after the rows are committed.
            queue = FakeQueue()
            assert await enqueue_discovery_run(queue, receipt) is True
            offered = queue.calls[0]
            assert offered["kind"] is FleetTaskKind.ARV2_DISCOVERY
            assert offered["payload"] == {
                "run_id": str(receipt.run_id),
                "workspace_id": fixture.workspace_id,
            }
            assert offered["dedup_key"] == f"{ARV2_DISCOVERY_DEDUP_PREFIX}{receipt.run_id}"
            assert offered["priority"] == ARV2_DISCOVERY_TASK_PRIORITY
            # A relaxed request re-offers a finished run's task, so the offer must reopen it.
            assert offered["reopen_terminal"] is True

    run_async(scenario())


def test_the_same_ask_replays_to_the_same_run_and_a_new_ask_is_a_new_run(tmp_path: Any) -> None:
    """The same ask retried is one run — a replayed turn does not buy two long lists — while a new
    ask with the SAME numbers is a new run (founder ruling 2026-09-28: "find more" is a new run)."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            fixture = await seed_icp_fixture(conn, storage)

            first = await launch_arv2_discovery(
                conn, _request(fixture), settings=_settings(), storage=storage
            )
            second = await launch_arv2_discovery(
                conn, _request(fixture), settings=_settings(), storage=storage
            )

            assert second.run_id == first.run_id
            assert first.replayed is False and second.replayed is True
            count = (
                await conn.execute(
                    text("SELECT count(*) FROM arv2_discovery_run WHERE project_id = :p"),
                    {"p": fixture.project_id},
                )
            ).scalar_one()
            assert count == 1

            # One unreleased discovery per project: each run ends before the next ask launches.
            await end_discovery_run(
                conn,
                run_id=first.run_id,
                status="completed",
                end_reason="filled",
                summary={},
                release=True,
            )
            # A different target is a different run — it is part of what was approved.
            other = await launch_arv2_discovery(
                conn, _request(fixture, target_count=40), settings=_settings(), storage=storage
            )
            assert other.run_id != first.run_id
            await end_discovery_run(
                conn,
                run_id=other.run_id,
                status="completed",
                end_reason="filled",
                summary={},
                release=True,
            )

            # And asking again for the very same number, in a new action, is a new run too.
            again = await launch_arv2_discovery(
                conn,
                _request(fixture, request_key="turn-action:ask-2"),
                settings=_settings(),
                storage=storage,
            )
            assert again.run_id not in {first.run_id, other.run_id}
            assert again.replayed is False and again.to_enqueue is True

    run_async(scenario())


def test_refusals_are_named(tmp_path: Any) -> None:
    """Every prerequisite failure is a typed code, never a stack trace the operator must read."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            fixture = await seed_icp_fixture(conn, storage)

            with pytest.raises(Arv2DiscoveryRefused) as disabled:
                await launch_arv2_discovery(
                    conn, _request(fixture), settings=_settings(enabled=False), storage=storage
                )
            assert disabled.value.code == "lane_disabled"

            with pytest.raises(Arv2DiscoveryRefused) as unknown_project:
                await launch_arv2_discovery(
                    conn,
                    _request(fixture, project_id="prj_nowhere"),
                    settings=_settings(),
                    storage=storage,
                )
            assert unknown_project.value.code == "project_not_found"

            with pytest.raises(Arv2DiscoveryRefused) as bad_count:
                await launch_arv2_discovery(
                    conn, _request(fixture, target_count=0), settings=_settings(), storage=storage
                )
            assert bad_count.value.code == "target_count_invalid"

            with pytest.raises(Arv2DiscoveryRefused) as no_brief:
                await launch_arv2_discovery(
                    conn, _request(fixture, brief=None), settings=_settings(), storage=storage
                )
            assert no_brief.value.code == "brief_required"

            # A project that pinned nothing has no ICP, and saying so is the honest answer. The pin
            # table is append-only, so the unpinned case is a second project rather than a delete.
            unpinned_project = await seed_project(conn, fixture.workspace_id, name="No ICP here")
            with pytest.raises(Arv2DiscoveryRefused) as unpinned:
                await launch_arv2_discovery(
                    conn,
                    _request(fixture, project_id=unpinned_project.project_id),
                    settings=_settings(),
                    storage=storage,
                )
            assert unpinned.value.code == "project_icp_not_pinned"

    run_async(scenario())


def test_the_pinned_icp_read_serves_the_document_a_run_is_pinned_to(
    tmp_path: Any,
) -> None:
    """The run records the document the project pinned — front matter, body and pins — as the
    context the agent was reading; the brief itself is the agent's."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            fixture = await seed_icp_fixture(conn, storage)

            document = await read_pinned_icp(
                conn,
                storage,
                workspace_id=fixture.workspace_id,
                project_id=fixture.project_id,
            )

            assert document.icp_key == ICP_KEY and document.icp_version == 1
            assert document.artifact_sha256 == fixture.icp_artifact_sha256
            assert document.artifact_key == fixture.icp_artifact_key
            assert document.brand_id == fixture.brand_id
            assert [gate["key"] for gate in document.front["hard_gates"]] == [
                "geography",
                "stage",
                "hiring",
                "intent",
            ]
            assert document.body.lstrip().startswith("# Who we sell to")

    run_async(scenario())


def test_the_launch_cannot_enqueue_at_all() -> None:
    """Rows first, offer second — the launch takes no queue and cannot reach one."""
    parameters = inspect.signature(launch_arv2_discovery).parameters
    assert "queue" not in parameters
    assert ".enqueue(" not in inspect.getsource(launch_arv2_discovery)


def test_the_service_offers_the_task_only_after_the_launch_transaction_closes(
    tmp_path: Any,
) -> None:
    """The production seam's ordering, pinned: rows committed, THEN the fleet is told."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            fixture = await seed_icp_fixture(conn, storage)
            trace: list[str] = []
            queue = FakeQueue(trace=trace)

            @asynccontextmanager
            async def factory() -> AsyncIterator[AsyncConnection]:
                trace.append("transaction_opened")
                try:
                    yield conn
                finally:
                    # The real ``transaction`` commits here; the test's connection rolls back at
                    # the end of the case, so what is asserted is the ORDER, not the durability.
                    trace.append("transaction_closed")

            service = DbArv2DiscoveryService(
                _settings(), storage, queue=queue, conn_factory=factory
            )

            receipt = await service.launch(_request(fixture))

            assert trace == ["transaction_opened", "transaction_closed", "enqueue"]
            assert queue.calls[0]["payload"]["run_id"] == str(receipt.run_id)

    run_async(scenario())


def test_a_launch_records_the_agents_brief_and_its_thread(tmp_path: Any) -> None:
    """The run carries the brief the agent wrote and the conversation it was launched from."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            fixture = await seed_icp_fixture(conn, storage)
            thread_id = f"thr_1_{uuid4().hex[:8]}"
            turn_id = await _seed_turn(conn, fixture, thread_id)

            receipt = await launch_arv2_discovery(
                conn,
                _request(
                    fixture,
                    request_key=f"turn-action:{turn_id}",
                    launching_turn_ref=f"turn-action:{turn_id}",
                ),
                settings=_settings(),
                storage=storage,
            )

            run = await read_discovery_run(conn, run_id=receipt.run_id)
            assert run is not None
            assert run.brief == BRIEF
            assert run.source == "websets"
            assert run.launched_thread_id == thread_id
            assert run.launching_turn_id == turn_id
            assert run.relaxed_enabled is False
            assert run.criteria_gate_keys == ()

    run_async(scenario())


def test_a_second_ask_while_one_runs_is_refused_by_name(tmp_path: Any) -> None:
    """One discovery per project: a new ask while one is active is refused, naming that run."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            fixture = await seed_icp_fixture(conn, storage)
            thread_id = f"thr_1_{uuid4().hex[:8]}"
            turn_id = await _seed_turn(conn, fixture, thread_id)

            first = await launch_arv2_discovery(
                conn,
                _request(fixture, request_key=f"turn-action:{turn_id}"),
                settings=_settings(),
                storage=storage,
            )
            with pytest.raises(Arv2DiscoveryRefused) as refused:
                await launch_arv2_discovery(
                    conn,
                    _request(fixture, request_key="turn-action:k2"),
                    settings=_settings(),
                    storage=storage,
                )
            assert refused.value.code == "discovery_in_progress"
            assert str(first.run_id) in str(refused.value)
            assert thread_id in str(refused.value)

    run_async(scenario())


async def _ended_run_and_its_wake(
    conn: AsyncConnection, fixture: IcpFixture, storage: FsStorage
) -> tuple[str, UUID, UUID]:
    """A run launched from a turn, ended, and woken — the lock still held by the wake turn.

    Returns ``(thread_id, run_id, wake_turn_id)``.
    """
    thread_id = f"thr_1_{uuid4().hex[:8]}"
    launching = await _seed_turn(conn, fixture, thread_id)
    first = await launch_arv2_discovery(
        conn,
        _request(
            fixture,
            request_key=f"turn-action:{launching}",
            launching_turn_ref=f"turn-action:{launching}",
        ),
        settings=_settings(),
        storage=storage,
    )
    await end_discovery_run(
        conn,
        run_id=first.run_id,
        status="needs_review",
        end_reason="failed",
        summary={},
        release=False,
    )
    wake = await _seed_turn(conn, fixture, thread_id, thread_exists=True)
    await record_wake_turn(conn, run_id=first.run_id, wake_turn_id=wake)
    return thread_id, first.run_id, wake


def test_the_runs_own_wake_turn_takes_the_lock_over_to_relaunch(tmp_path: Any) -> None:
    """The agent may search again once, from the turn that reports the run (Ruling 11). That turn
    holds the lock, so its launch hands the lock from the ended run to the new one in one step:
    the old run is released and the new run holds the same thread."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            fixture = await seed_icp_fixture(conn, storage)
            thread_id, old_run_id, wake = await _ended_run_and_its_wake(conn, fixture, storage)

            relaunch = await launch_arv2_discovery(
                conn,
                _request(
                    fixture,
                    request_key=f"turn-action:{wake}",
                    launching_turn_ref=f"turn-action:{wake}",
                ),
                settings=_settings(),
                storage=storage,
            )

            assert relaunch.run_id != old_run_id
            assert relaunch.replayed is False and relaunch.to_enqueue is True
            old = await read_discovery_run(conn, run_id=old_run_id)
            new = await read_discovery_run(conn, run_id=relaunch.run_id)
            assert old is not None and old.released_at is not None
            assert new is not None and new.released_at is None
            assert new.launched_thread_id == thread_id
            assert new.launching_turn_id == wake
            # The wake turn finishing later releases nothing: the new run is not its to release.
            assert (
                await release_discovery_for_turn(
                    conn, workspace_id=fixture.workspace_id, turn_id=wake
                )
                is None
            )

    run_async(scenario())


def test_only_the_runs_own_wake_turn_can_take_the_lock_over(tmp_path: Any) -> None:
    """Any other turn — another thread, or a stale one — is still refused while the wake runs."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            fixture = await seed_icp_fixture(conn, storage)
            _, old_run_id, _ = await _ended_run_and_its_wake(conn, fixture, storage)
            other = await _seed_turn(conn, fixture, f"thr_2_{uuid4().hex[:8]}")

            with pytest.raises(Arv2DiscoveryRefused) as refused:
                await launch_arv2_discovery(
                    conn,
                    _request(
                        fixture,
                        request_key=f"turn-action:{other}",
                        launching_turn_ref=f"turn-action:{other}",
                    ),
                    settings=_settings(),
                    storage=storage,
                )
            assert refused.value.code == "discovery_in_progress"
            old = await read_discovery_run(conn, run_id=old_run_id)
            assert old is not None and old.released_at is None

    run_async(scenario())


def test_replaying_the_same_ask_returns_the_same_run(tmp_path: Any) -> None:
    """The lock never refuses a run its own replay: the same ask is the same run, not a rival."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            fixture = await seed_icp_fixture(conn, storage)

            first = await launch_arv2_discovery(
                conn, _request(fixture, request_key="k1"), settings=_settings(), storage=storage
            )
            second = await launch_arv2_discovery(
                conn, _request(fixture, request_key="k1"), settings=_settings(), storage=storage
            )
            assert first.replayed is False
            assert second.replayed is True
            assert second.run_id == first.run_id

    run_async(scenario())


def test_a_launch_without_a_brief_is_refused(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            fixture = await seed_icp_fixture(conn, storage)
            with pytest.raises(Arv2DiscoveryRefused) as refused:
                await launch_arv2_discovery(
                    conn, _request(fixture, brief=None), settings=_settings(), storage=storage
                )
            assert refused.value.code == "brief_required"
            count = (
                await conn.execute(
                    text("SELECT count(*) FROM arv2_discovery_run WHERE project_id = :p"),
                    {"p": fixture.project_id},
                )
            ).scalar_one()
            assert count == 0

    run_async(scenario())


def test_two_simultaneous_launches_create_one_run(tmp_path: Any) -> None:
    """Two asks racing in two open transactions: neither sees the other's row at its pre-check,
    so the partial unique index is what decides — and its violation is the named refusal, never
    an ``IntegrityError``. The seed is committed (two transactions must both see it) under a
    workspace and user of its own, the ``test_generation_locking_db`` precedent."""

    async def scenario() -> None:
        storage = FsStorage(tmp_path)
        workspace_id = f"ws_disc_race_{uuid4().hex[:10]}"
        async with db_lifespan() as engine:
            async with engine.begin() as conn:
                await load_core_pack(conn)
                fixture = await seed_icp_fixture(
                    conn, storage, workspace_id=workspace_id, user_id=f"usr_{uuid4().hex[:10]}"
                )

            async with engine.connect() as first_conn, engine.connect() as second_conn:
                first_txn = await first_conn.begin()
                second_txn = await second_conn.begin()
                try:
                    first = await launch_arv2_discovery(
                        first_conn,
                        _request(fixture, request_key="k1"),
                        settings=_settings(),
                        storage=storage,
                    )
                    second_pid = (
                        await second_conn.execute(text("SELECT pg_backend_pid()"))
                    ).scalar_one()
                    second = asyncio.create_task(
                        launch_arv2_discovery(
                            second_conn,
                            _request(fixture, request_key="k2"),
                            settings=_settings(),
                            storage=storage,
                        )
                    )
                    # Wait until the second launch is blocked behind the first's uncommitted rows —
                    # past its pre-check, which therefore saw nothing — before the first commits.
                    for _ in range(200):
                        waiting = (
                            await first_conn.execute(
                                text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :p"),
                                {"p": second_pid},
                            )
                        ).scalar_one_or_none()
                        if waiting == "Lock" or second.done():
                            break
                        await asyncio.sleep(0.05)
                    assert waiting == "Lock", "the second launch never reached the insert race"
                    await first_txn.commit()

                    with pytest.raises(Arv2DiscoveryRefused) as refused:
                        await asyncio.wait_for(second, timeout=15)
                    assert refused.value.code == "discovery_in_progress"
                    assert str(first.run_id) in str(refused.value)
                finally:
                    if second_txn.is_active:
                        await second_txn.rollback()
                    if first_txn.is_active:
                        await first_txn.rollback()

            async with engine.connect() as conn:
                count = (
                    await conn.execute(
                        text("SELECT count(*) FROM arv2_discovery_run WHERE project_id = :p"),
                        {"p": fixture.project_id},
                    )
                ).scalar_one()
            assert count == 1

    run_async(scenario())
