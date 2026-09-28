"""FI Lane D D0 — the durable thread shell's read side (DB-gated).

Three things are proven here, all against real rows:

* **The thread listing and both turn listings page by keyset.** Exact-limit (a full final page
  hands out no cursor), a mid-page cursor that resumes without repeating or skipping, and a
  workspace filter that makes another tenant's thread indistinguishable from a thread that does
  not exist.
* **Message summaries carry REQ-21's typed refs**, projected from the durable
  ``agent_artifact_ref`` / ``agent_finalization_domain_ref`` rows — attachments on the user
  message, outputs and the open gate on the assistant message, and nothing leaking across that
  boundary.
* **The grandfathered ``agent_turn`` → ``agent_thread`` foreign key holds for new writes**: a turn
  naming a thread that does not exist is refused by the database, and one naming a thread in
  another workspace is refused too.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.thread_store import create_thread, get_thread, new_thread_id
from clue_projections import (
    InvalidCursorError,
    MessageRefFlavor,
    agent_turns_for_project,
    agent_turns_for_thread,
    thread_messages,
    threads_for_project,
)
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)

SHA = "a" * 64
START = datetime(2026, 8, 8, 12, tzinfo=UTC)


@pytest.fixture
def require_thread_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


async def _artifact(conn: AsyncConnection, *, workspace_id: str, sha: str) -> str:
    key = f"{workspace_id}/{sha}"
    await conn.execute(
        text(
            "INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, "
            "size_bytes) VALUES (:key, :workspace, :sha, 'text/plain', 11) "
            "ON CONFLICT (storage_key) DO NOTHING"
        ),
        {"key": key, "workspace": workspace_id, "sha": sha},
    )
    return key


async def _stamp_created_at(conn: AsyncConnection, *, thread_id: str, at: datetime) -> None:
    """Give a thread a distinct creation time (``agent_thread`` is mutable shell state)."""

    await conn.execute(
        text("UPDATE agent_thread SET created_at = :at WHERE id = :id"),
        {"at": at, "id": thread_id},
    )


async def _turn(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    thread_id: str,
    requested_at: datetime,
    turn_id: UUID | None = None,
) -> UUID:
    """Insert one ``execution`` + ``agent_turn`` + latest status event, and return the turn id."""

    execution_id = uuid4()
    resolved = turn_id if turn_id is not None else uuid4()
    await conn.execute(
        text(
            "INSERT INTO execution (id, workspace_id, project_id, started_by, "
            "parameter_manifest_hash, pin_manifest_hash) "
            "VALUES (:id, :workspace, :project, 'human', :hash, :hash)"
        ),
        {"id": execution_id, "workspace": workspace_id, "project": project_id, "hash": "0" * 64},
    )
    manifest_key = await _artifact(conn, workspace_id=workspace_id, sha=SHA)
    await conn.execute(
        text(
            "INSERT INTO agent_turn (id, execution_id, workspace_id, project_id, thread_id, "
            " actor_id, role, workspace_root_id, profile_name, profile_version, profile_sha256, "
            " resource_manifest_key, resource_manifest_artifact_sha256, resource_manifest_sha256, "
            " retention_class, requested_at) "
            "VALUES (:id, :execution, :workspace, :project, :thread, 'actor-1', 'head_of_abm', "
            " 'root-1', 'head-of-abm', 'v1', :hash, :manifest_key, :sha, :hash, 'standard', :at)"
        ),
        {
            "id": resolved,
            "execution": execution_id,
            "workspace": workspace_id,
            "project": project_id,
            "thread": thread_id,
            "hash": "0" * 64,
            "manifest_key": manifest_key,
            "sha": SHA,
            "at": requested_at,
        },
    )
    await conn.execute(
        text(
            "INSERT INTO agent_turn_event (event_id, turn_id, workspace_id, status) "
            "VALUES (:event, :turn, :workspace, 'completed')"
        ),
        {"event": uuid4(), "turn": resolved, "workspace": workspace_id},
    )
    return resolved


async def _message(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    thread_id: str,
    turn_id: UUID,
    sequence: int,
    role: str,
) -> UUID:
    sha = f"{sequence:064x}"
    key = await _artifact(conn, workspace_id=workspace_id, sha=sha)
    message_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO agent_thread_message (id, workspace_id, thread_id, turn_id, sequence, "
            " role, body_artifact_key, body_sha256, retention_class) "
            "VALUES (:id, :workspace, :thread, :turn, :sequence, :role, :key, :sha, 'standard')"
        ),
        {
            "id": message_id,
            "workspace": workspace_id,
            "thread": thread_id,
            "turn": turn_id,
            "sequence": sequence,
            "role": role,
            "key": key,
            "sha": sha,
        },
    )
    return message_id


# --- thread listing ----------------------------------------------------------------------------


def test_thread_listing_pages_by_keyset_and_stops_at_its_workspace(
    require_thread_db: None,
) -> None:
    del require_thread_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "ws-d0-threads", name="D0 threads")
            other = await seed_project(conn, "ws-d0-other", name="D0 other tenant")
            # Lane D's B1 join made both ownership columns real foreign keys, so the creator this
            # listing cites has to exist in Lane B's substrate before a thread can name it.
            owner = await seed_principal(
                conn,
                workspace_id=project.workspace_id,
                user_id="usr_d0",
                membership_id="wsm_d0",
            )
            factory = conn_session_factory(conn)

            ids = []
            for index in range(5):
                row = await create_thread(
                    conn,
                    thread_id=new_thread_id(),
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    title=f"thread {index}",
                    created_by_user_id=owner.user_id,
                    created_via_membership_id=owner.membership_id,
                )
                # `now()` is transaction time, so five rows written in one transaction share a
                # timestamp and would order by their random ids. Distinct times make the assertion
                # readable; the tied-timestamp case is what the `(created_at, id)` row-value
                # comparison exists for, and has its own test.
                await _stamp_created_at(conn, thread_id=row.id, at=START + timedelta(minutes=index))
                ids.append(row.id)
            await create_thread(
                conn,
                thread_id=new_thread_id(),
                workspace_id=other.workspace_id,
                project_id=other.project_id,
                title="not yours",
            )

            first = await threads_for_project(
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                limit=2,
                conn_factory=factory,
            )
            assert [item.title for item in first.items] == ["thread 0", "thread 1"]
            assert first.next_cursor is not None

            second = await threads_for_project(
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                limit=2,
                cursor=first.next_cursor,
                conn_factory=factory,
            )
            assert [item.title for item in second.items] == ["thread 2", "thread 3"]

            # Exact-limit final page: five rows read two at a time ends on a page of one with no
            # cursor — the probe row proves there is nothing after it.
            last = await threads_for_project(
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                limit=2,
                cursor=second.next_cursor,
                conn_factory=factory,
            )
            assert [item.title for item in last.items] == ["thread 4"]
            assert last.next_cursor is None

            # The other tenant's project is empty from here even though its thread exists.
            assert (
                await threads_for_project(
                    workspace_id=project.workspace_id,
                    project_id=other.project_id,
                    conn_factory=factory,
                )
            ).items == ()
            assert (
                await get_thread(conn, workspace_id=other.workspace_id, thread_id=ids[0])
            ) is None

            with pytest.raises(InvalidCursorError):
                await threads_for_project(
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    cursor="not-a-cursor-we-minted",
                    conn_factory=factory,
                )

    run_async(scenario())


def test_threads_sharing_one_timestamp_still_page_without_repeating_or_skipping(
    require_thread_db: None,
) -> None:
    """Seven threads written in one transaction share a ``created_at`` exactly.

    This is the case an ``ORDER BY created_at`` cursor gets wrong — it either re-serves or skips
    the tied rows. The row-value comparison over ``(created_at, id)`` is total, so a full walk
    returns each thread exactly once.
    """

    del require_thread_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "ws-d0-ties", name="D0 ties")
            owner = await seed_principal(
                conn,
                workspace_id=project.workspace_id,
                user_id="usr_d0_ties",
                membership_id="wsm_d0_ties",
            )
            factory = conn_session_factory(conn)
            created = {
                (
                    await create_thread(
                        conn,
                        thread_id=new_thread_id(),
                        workspace_id=project.workspace_id,
                        project_id=project.project_id,
                        title=f"tied {index}",
                        created_by_user_id=owner.user_id,
                        created_via_membership_id=owner.membership_id,
                    )
                ).id
                for index in range(7)
            }

            walked: list[str] = []
            cursor: str | None = None
            while True:
                page = await threads_for_project(
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    limit=2,
                    cursor=cursor,
                    conn_factory=factory,
                )
                walked.extend(item.thread_id for item in page.items)
                if page.next_cursor is None:
                    break
                cursor = page.next_cursor

            assert len(walked) == len(created)
            assert set(walked) == created

    run_async(scenario())


def test_thread_listing_can_filter_archived_without_losing_the_row(
    require_thread_db: None,
) -> None:
    del require_thread_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "ws-d0-archive", name="D0 archive")
            owner = await seed_principal(
                conn,
                workspace_id=project.workspace_id,
                user_id="usr_d0_archive",
                membership_id="wsm_d0_archive",
            )
            factory = conn_session_factory(conn)
            kept = await create_thread(
                conn,
                thread_id=new_thread_id(),
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                title="active",
                created_by_user_id=owner.user_id,
                created_via_membership_id=owner.membership_id,
            )
            gone = await create_thread(
                conn,
                thread_id=new_thread_id(),
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                title="archived",
                created_by_user_id=owner.user_id,
                created_via_membership_id=owner.membership_id,
            )
            await conn.execute(
                text("UPDATE agent_thread SET status='archived' WHERE id=:id"),
                {"id": gone.id},
            )

            active = await threads_for_project(
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                status="active",
                conn_factory=factory,
            )
            assert [item.thread_id for item in active.items] == [kept.id]

            everything = await threads_for_project(
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                conn_factory=factory,
            )
            assert {item.thread_id for item in everything.items} == {kept.id, gone.id}

    run_async(scenario())


def test_machine_threads_never_appear_as_chats(require_thread_db: None) -> None:
    """Research runs and onboarding synthesis create threads with no user; they are not chats.

    Found live 2026-09-29: every research agent run surfaced in the sidebar as a "New chat".
    """
    del require_thread_db
    from clue_projections.threads import project_sidebar_page

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "ws-d0-machine", name="D0 machine threads")
            # The rail lists only active marketing projects.
            await conn.execute(
                text("UPDATE project SET status = 'active' WHERE project_id = :id"),
                {"id": project.project_id},
            )
            owner = await seed_principal(
                conn,
                workspace_id=project.workspace_id,
                user_id="usr_d0_machine",
                membership_id="wsm_d0_machine",
            )
            factory = conn_session_factory(conn)
            chat = await create_thread(
                conn,
                thread_id=new_thread_id(),
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                title="my chat",
                created_by_user_id=owner.user_id,
                created_via_membership_id=owner.membership_id,
            )
            await create_thread(
                conn,
                thread_id=f"research-quality-{uuid4()}",
                workspace_id=project.workspace_id,
                project_id=project.project_id,
            )

            listed = await threads_for_project(
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                conn_factory=factory,
            )
            assert [item.thread_id for item in listed.items] == [chat.id]

            rail = await project_sidebar_page(
                workspace_id=project.workspace_id, conn_factory=factory
            )
            rail_threads = [
                thread.thread_id
                for item in rail.items
                if item.project_id == project.project_id
                for thread in item.threads
            ]
            assert rail_threads == [chat.id]

    run_async(scenario())


# --- turn pagination ---------------------------------------------------------------------------


def test_project_and_thread_turn_listings_page_by_keyset(require_thread_db: None) -> None:
    del require_thread_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "ws-d0-turns", name="D0 turns")
            factory = conn_session_factory(conn)
            thread = await create_thread(
                conn,
                thread_id=new_thread_id(),
                workspace_id=project.workspace_id,
                project_id=project.project_id,
            )
            sibling = await create_thread(
                conn,
                thread_id=new_thread_id(),
                workspace_id=project.workspace_id,
                project_id=project.project_id,
            )
            turn_ids = [
                await _turn(
                    conn,
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    thread_id=thread.id,
                    requested_at=START + timedelta(minutes=index),
                )
                for index in range(4)
            ]
            sibling_turn = await _turn(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                thread_id=sibling.id,
                requested_at=START + timedelta(minutes=10),
            )

            first = await agent_turns_for_project(
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                limit=2,
                conn_factory=factory,
            )
            assert [item.turn_id for item in first.items] == turn_ids[:2]
            assert first.next_cursor is not None

            rest = await agent_turns_for_project(
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                limit=10,
                cursor=first.next_cursor,
                conn_factory=factory,
            )
            assert [item.turn_id for item in rest.items] == [*turn_ids[2:], sibling_turn]
            assert rest.next_cursor is None

            # Exact-limit: a page that exactly consumes the remaining rows hands out no cursor.
            exact = await agent_turns_for_thread(
                workspace_id=project.workspace_id,
                thread_id=thread.id,
                limit=4,
                conn_factory=factory,
            )
            assert [item.turn_id for item in exact.items] == turn_ids
            assert exact.next_cursor is None

            # The thread-scoped reader never sees the sibling thread's turn.
            assert sibling_turn not in {item.turn_id for item in exact.items}

            # Cross-workspace isolation: same project id, wrong tenant, nothing.
            assert (
                await agent_turns_for_project(
                    workspace_id="ws-d0-somebody-else",
                    project_id=project.project_id,
                    conn_factory=factory,
                )
            ).items == ()

    run_async(scenario())


def test_turn_pagination_refuses_a_foreign_cursor_and_an_impossible_limit(
    require_thread_db: None,
) -> None:
    del require_thread_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            factory = conn_session_factory(conn)
            with pytest.raises(InvalidCursorError):
                await agent_turns_for_project(
                    workspace_id="ws-d0",
                    project_id="prj",
                    cursor="tampered",
                    conn_factory=factory,
                )
            with pytest.raises(ValueError, match="page size"):
                await agent_turns_for_project(
                    workspace_id="ws-d0",
                    project_id="prj",
                    limit=0,
                    conn_factory=factory,
                )

    run_async(scenario())


# --- messages + typed refs ---------------------------------------------------------------------


def test_message_pages_carry_typed_refs_attributed_by_message_role(
    require_thread_db: None,
) -> None:
    del require_thread_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "ws-d0-messages", name="D0 messages")
            factory = conn_session_factory(conn)
            thread = await create_thread(
                conn,
                thread_id=new_thread_id(),
                workspace_id=project.workspace_id,
                project_id=project.project_id,
            )
            turn_id = await _turn(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                thread_id=thread.id,
                requested_at=START,
            )
            await _message(
                conn,
                workspace_id=project.workspace_id,
                thread_id=thread.id,
                turn_id=turn_id,
                sequence=1,
                role="user",
            )
            await _message(
                conn,
                workspace_id=project.workspace_id,
                thread_id=thread.id,
                turn_id=turn_id,
                sequence=2,
                role="assistant",
            )

            attachment_sha = "b" * 64
            attachment_key = await _artifact(
                conn, workspace_id=project.workspace_id, sha=attachment_sha
            )
            principal = await seed_principal(
                conn,
                workspace_id=project.workspace_id,
                user_id="usr-d0-message-refs",
            )
            onboarding_input_id = uuid4()
            await conn.execute(
                text(
                    "INSERT INTO onboarding_input "
                    "(id, workspace_id, brand_id, project_id, kind, artifact_key, "
                    " content_sha256, actor) "
                    "VALUES (:id, :workspace, :brand, :project, 'user_turn', :key, :sha, "
                    " 'human')"
                ),
                {
                    "id": onboarding_input_id,
                    "workspace": project.workspace_id,
                    "brand": project.brand_id,
                    "project": project.project_id,
                    "key": attachment_key,
                    "sha": attachment_sha,
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO agent_turn_submission "
                    "(turn_id, workspace_id, project_id, thread_id, submitted_by_user_id, "
                    " submitted_via_membership_id, onboarding_input_id, message_artifact_key, "
                    " message_sha256, idempotency_key, agent_profile_id) "
                    "VALUES (:turn, :workspace, :project, :thread, :user, :membership, "
                    " :input, :key, :sha, 'd0-context-refs', 'head-of-abm@v24')"
                ),
                {
                    "turn": turn_id,
                    "workspace": project.workspace_id,
                    "project": project.project_id,
                    "thread": thread.id,
                    "user": principal.user_id,
                    "membership": principal.membership_id,
                    "input": onboarding_input_id,
                    "key": attachment_key,
                    "sha": attachment_sha,
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO agent_turn_submission_context_ref "
                    "(turn_id, workspace_id, ordinal, object_type, object_id, object_version) "
                    "VALUES (:turn, :workspace, 0, 'contact', 'contact-second', 4), "
                    "(:turn, :workspace, 1, 'account', 'account-first', 2)"
                ),
                {"turn": turn_id, "workspace": project.workspace_id},
            )
            await conn.execute(
                text(
                    "INSERT INTO agent_artifact_ref (id, turn_id, workspace_id, owner_kind, "
                    " owner_id, ref_role, ordinal, artifact_key, artifact_sha256, "
                    " retention_class) "
                    "VALUES (:id, :turn, :workspace, 'turn', :turn, 'attachment', 0, :key, "
                    " :sha, 'standard')"
                ),
                {
                    "id": uuid4(),
                    "turn": turn_id,
                    "workspace": project.workspace_id,
                    "key": attachment_key,
                    "sha": attachment_sha,
                },
            )
            finalization_id = uuid4()
            execution_id = (
                await conn.execute(
                    text("SELECT execution_id FROM agent_turn WHERE id=:turn"),
                    {"turn": turn_id},
                )
            ).scalar_one()
            await conn.execute(
                text(
                    "INSERT INTO agent_finalization (id, turn_id, execution_id, workspace_id, "
                    " status, finalized_at) "
                    "VALUES (:id, :turn, :execution, :workspace, 'awaiting_input', now())"
                ),
                {
                    "id": finalization_id,
                    "turn": turn_id,
                    "execution": execution_id,
                    "workspace": project.workspace_id,
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO agent_finalization_domain_ref (finalization_id, workspace_id, "
                    " ref_role, ordinal, object_type, object_id, object_version) VALUES "
                    "(:id, :workspace, 'output', 0, 'research_directive', 'rd-1', 3), "
                    "(:id, :workspace, 'open_gate', 0, 'agent_gate', 'gate-1', NULL)"
                ),
                {"id": finalization_id, "workspace": project.workspace_id},
            )

            page = await thread_messages(
                workspace_id=project.workspace_id,
                thread_id=thread.id,
                conn_factory=factory,
            )
            user, assistant = page.items
            assert user.sequence == 1
            assert [ref.flavor for ref in user.refs] == [
                MessageRefFlavor.ATTACHMENT,
                MessageRefFlavor.CONTEXT,
                MessageRefFlavor.CONTEXT,
            ]
            assert user.refs[0].object_type == "artifact"
            assert user.refs[0].object_id == attachment_key
            assert [
                (ref.object_type, ref.object_id, ref.version, ref.ordinal)
                for ref in user.refs
                if ref.flavor is MessageRefFlavor.CONTEXT
            ] == [
                ("contact", "contact-second", 4, 0),
                ("account", "account-first", 2, 1),
            ]

            assert {ref.flavor for ref in assistant.refs} == {
                MessageRefFlavor.OUTPUT,
                MessageRefFlavor.OPEN_GATE,
            }
            output = next(ref for ref in assistant.refs if ref.flavor is MessageRefFlavor.OUTPUT)
            assert (output.object_type, output.object_id, output.version) == (
                "research_directive",
                "rd-1",
                3,
            )
            gate = next(ref for ref in assistant.refs if ref.flavor is MessageRefFlavor.OPEN_GATE)
            assert gate.version is None
            # The attachment belongs to the human's message, not to the reply.
            assert MessageRefFlavor.ATTACHMENT not in {ref.flavor for ref in assistant.refs}
            # Every ref stays inside the reading workspace.
            assert {ref.workspace_id for ref in (*user.refs, *assistant.refs)} == {
                project.workspace_id
            }

    run_async(scenario())


def test_message_pages_are_keyset_over_sequence_and_workspace_scoped(
    require_thread_db: None,
) -> None:
    """Newest page first, before-cursor walking backward (Slice C C5's flipped read)."""

    del require_thread_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "ws-d0-msgpage", name="D0 message paging")
            factory = conn_session_factory(conn)
            thread = await create_thread(
                conn,
                thread_id=new_thread_id(),
                workspace_id=project.workspace_id,
                project_id=project.project_id,
            )
            turn_id = await _turn(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                thread_id=thread.id,
                requested_at=START,
            )
            for sequence in range(1, 6):
                await _message(
                    conn,
                    workspace_id=project.workspace_id,
                    thread_id=thread.id,
                    turn_id=turn_id,
                    sequence=sequence,
                    role="user" if sequence % 2 else "assistant",
                )

            first = await thread_messages(
                workspace_id=project.workspace_id,
                thread_id=thread.id,
                limit=2,
                conn_factory=factory,
            )
            assert [item.sequence for item in first.items] == [4, 5]

            middle = await thread_messages(
                workspace_id=project.workspace_id,
                thread_id=thread.id,
                limit=2,
                cursor=first.next_cursor,
                conn_factory=factory,
            )
            assert [item.sequence for item in middle.items] == [2, 3]

            exact = await thread_messages(
                workspace_id=project.workspace_id,
                thread_id=thread.id,
                limit=1,
                cursor=middle.next_cursor,
                conn_factory=factory,
            )
            assert [item.sequence for item in exact.items] == [1]
            assert exact.next_cursor is None

            assert (
                await thread_messages(
                    workspace_id="ws-d0-not-ours",
                    thread_id=thread.id,
                    conn_factory=factory,
                )
            ).items == ()

    run_async(scenario())


# --- the grandfathered foreign key ---------------------------------------------------------------


def test_a_new_turn_must_name_a_thread_that_exists_in_its_own_workspace(
    require_thread_db: None,
) -> None:
    del require_thread_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "ws-d0-fk", name="D0 fk")
            with pytest.raises(IntegrityError, match="agent_turn_thread_fk"):
                await _turn(
                    conn,
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                    thread_id="thread-that-was-never-created",
                    requested_at=START,
                )

    run_async(scenario())

    async def cross_workspace() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            mine = await seed_project(conn, "ws-d0-fk-mine", name="D0 fk mine")
            theirs = await seed_project(conn, "ws-d0-fk-theirs", name="D0 fk theirs")
            elsewhere = await create_thread(
                conn,
                thread_id=new_thread_id(),
                workspace_id=theirs.workspace_id,
                project_id=theirs.project_id,
            )
            with pytest.raises(IntegrityError, match="agent_turn_thread_fk"):
                await _turn(
                    conn,
                    workspace_id=mine.workspace_id,
                    project_id=mine.project_id,
                    thread_id=elsewhere.id,
                    requested_at=START,
                )

    run_async(cross_workspace())
