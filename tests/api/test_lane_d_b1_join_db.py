"""FI Lane D — the B1 join: ownership foreign keys, a provisioned dev principal, thread ownership.

Three things land in this slice and each is proved here against a real database:

1. **The ownership foreign keys** (migration ``c4ccc7b11810``). ``agent_thread`` and ``agent_turn``
   may name a human owner only if that human exists in Lane B's substrate, and may name a
   membership only if it is a membership *of their own workspace* (the composite FK). NULL still
   passes — a platform-originated thread or turn has no human owner, and Lane B ruling 8 forbids
   inventing one.
2. **The development principal is backed by real rows** (contract §4: even a dev adapter "must
   still resolve a real internal user/membership fixture from Postgres"). Provisioning is
   idempotent, goes through ``clue_auth``'s CRUD, and refuses loudly rather than degrading — it
   runs at startup, so a refusal must stop the process.
3. **``ensure_platform_thread`` no longer attaches a turn to another project's thread.** The D0
   review found that ``ON CONFLICT (id) DO NOTHING`` accepted any surviving row; it now proves the
   survivor's ``(workspace_id, project_id)`` and raises :class:`ThreadOwnershipMismatch` otherwise.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.chat import (
    DEV_PROVIDER_KEY,
    DevPrincipalUnavailable,
    ProductionPrincipalRequired,
    StartupDevPrincipalResolver,
    build_provisioned_dev_principal_resolver,
    dev_provider_subject,
    provision_dev_principal,
)
from clue_api.thread_store import ThreadOwnershipMismatch, ensure_platform_thread
from clue_auth import disable_platform_user, get_platform_user, get_workspace_membership
from clue_config import Settings, load_settings
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)

NOW_UTC = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)


@pytest.fixture
def require_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


def _settings(**kwargs: object) -> Settings:
    return load_settings(_env_file=None, chat_enabled=True, **kwargs)


async def _insert_thread(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    user_id: str | None,
    membership_id: str | None,
    thread_id: str | None = None,
) -> str:
    """Insert one ``agent_thread`` row directly — the FKs are what is under test, not the tools."""

    resolved = thread_id or f"thr_{uuid4().hex}"
    await conn.execute(
        text(
            "INSERT INTO agent_thread "
            "(id, workspace_id, project_id, created_by_user_id, created_via_membership_id) "
            "VALUES (:id, :workspace, :project, :user, :membership)"
        ),
        {
            "id": resolved,
            "workspace": workspace_id,
            "project": project_id,
            "user": user_id,
            "membership": membership_id,
        },
    )
    return resolved


async def _insert_turn(
    conn: AsyncConnection,
    *,
    label: str,
    workspace_id: str,
    project_id: str,
    user_id: str | None,
    membership_id: str | None,
) -> None:
    """Insert one ``agent_turn`` row with its mandatory execution + thread shell."""

    execution_id = uuid5(NAMESPACE_URL, f"lane-d-b1-join:{label}:execution")
    manifest_key = f"{workspace_id}/{'0' * 64}"
    await conn.execute(
        text(
            "INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, "
            " size_bytes) VALUES (:key, :workspace, :sha, 'application/json', 2) "
            "ON CONFLICT (storage_key) DO NOTHING"
        ),
        {"key": manifest_key, "workspace": workspace_id, "sha": "0" * 64},
    )
    thread_id = await _insert_thread(
        conn,
        workspace_id=workspace_id,
        project_id=project_id,
        user_id=None,
        membership_id=None,
    )
    await conn.execute(
        text(
            "INSERT INTO execution "
            "(id, workspace_id, project_id, started_by, parameter_manifest_hash, "
            " pin_manifest_hash) "
            "VALUES (:id, :workspace, :project, 'human', :hash, :hash) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": execution_id, "workspace": workspace_id, "project": project_id, "hash": "0" * 64},
    )
    await conn.execute(
        text(
            "INSERT INTO agent_turn "
            "(id, execution_id, workspace_id, project_id, thread_id, actor_id, role, "
            " workspace_root_id, profile_name, profile_version, profile_sha256, "
            " resource_manifest_key, resource_manifest_artifact_sha256, resource_manifest_sha256, "
            " retention_class, requested_at, submitted_by_user_id, submitted_via_membership_id) "
            "VALUES (:id, :execution, :workspace, :project, :thread, :actor, 'head_of_abm', "
            " :root, 'head-of-abm', 'v22', :sha, :key, :sha, :sha, 'test', :at, "
            " :submitted_by, :submitted_via)"
        ),
        {
            "id": uuid5(NAMESPACE_URL, f"lane-d-b1-join:{label}:turn"),
            "execution": execution_id,
            "workspace": workspace_id,
            "project": project_id,
            "thread": thread_id,
            "actor": user_id or "agent:unauthenticated",
            "root": f"root-{label}",
            "sha": "0" * 64,
            "key": manifest_key,
            "at": NOW_UTC,
            "submitted_by": user_id,
            "submitted_via": membership_id,
        },
    )


# --- 1. the ownership foreign keys -------------------------------------------------------------


def test_a_thread_owner_must_be_a_real_platform_user(require_db: None) -> None:
    """An invented ``usr_…`` string is now a database error; NULL and a real user both pass."""

    del require_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "ws-b1join-user", name="B1 join")
            seeded = await seed_principal(
                conn, workspace_id=project.workspace_id, user_id="usr_b1join_real"
            )

            with pytest.raises(IntegrityError) as refused:
                async with conn.begin_nested():
                    await _insert_thread(
                        conn,
                        workspace_id=project.workspace_id,
                        project_id=project.project_id,
                        user_id="usr_b1join_ghost",
                        membership_id=None,
                    )
            assert "agent_thread_created_by_user_fk" in str(refused.value)

            # A platform-originated thread carries no creator at all — still legal.
            await _insert_thread(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                user_id=None,
                membership_id=None,
            )
            # …and a real Lane B user is accepted.
            await _insert_thread(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                user_id=seeded.user_id,
                membership_id=None,
            )

    run_async(scenario())


def test_a_thread_membership_must_be_a_membership_of_the_threads_own_workspace(
    require_db: None,
) -> None:
    """The composite FK: one user, two workspaces, and the wrong membership cannot be cited."""

    del require_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            mine = await seed_project(conn, "ws-b1join-mine", name="B1 join mine")
            theirs = await seed_project(conn, "ws-b1join-theirs", name="B1 join theirs")
            here = await seed_principal(
                conn, workspace_id=mine.workspace_id, user_id="usr_b1join_two_ws"
            )
            elsewhere = await seed_principal(
                conn, workspace_id=theirs.workspace_id, user_id="usr_b1join_two_ws"
            )
            # One user, two workspaces, two distinct memberships (contract §3.3).
            assert here.membership_id != elsewhere.membership_id

            with pytest.raises(IntegrityError) as refused:
                async with conn.begin_nested():
                    await _insert_thread(
                        conn,
                        workspace_id=mine.workspace_id,
                        project_id=mine.project_id,
                        user_id=here.user_id,
                        membership_id=elsewhere.membership_id,
                    )
            assert "agent_thread_created_via_membership_fk" in str(refused.value)

            await _insert_thread(
                conn,
                workspace_id=mine.workspace_id,
                project_id=mine.project_id,
                user_id=here.user_id,
                membership_id=here.membership_id,
            )

    run_async(scenario())


def test_a_turn_submitter_must_be_a_real_user_and_a_local_membership(require_db: None) -> None:
    """``agent_turn`` carries the same two guarantees as ``agent_thread``."""

    del require_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            mine = await seed_project(conn, "ws-b1join-turn", name="B1 join turn")
            theirs = await seed_project(conn, "ws-b1join-turn-other", name="B1 join turn other")
            here = await seed_principal(
                conn, workspace_id=mine.workspace_id, user_id="usr_b1join_submitter"
            )
            elsewhere = await seed_principal(
                conn, workspace_id=theirs.workspace_id, user_id="usr_b1join_submitter"
            )

            with pytest.raises(IntegrityError) as ghost:
                async with conn.begin_nested():
                    await _insert_turn(
                        conn,
                        label="ghost",
                        workspace_id=mine.workspace_id,
                        project_id=mine.project_id,
                        user_id="usr_b1join_turn_ghost",
                        membership_id=None,
                    )
            assert "agent_turn_submitted_by_user_fk" in str(ghost.value)

            with pytest.raises(IntegrityError) as foreign:
                async with conn.begin_nested():
                    await _insert_turn(
                        conn,
                        label="foreign",
                        workspace_id=mine.workspace_id,
                        project_id=mine.project_id,
                        user_id=here.user_id,
                        membership_id=elsewhere.membership_id,
                    )
            assert "agent_turn_submitted_via_membership_fk" in str(foreign.value)

            # The machine turn every producer writes today, and the authenticated human turn D2
            # will write: both legal.
            await _insert_turn(
                conn,
                label="machine",
                workspace_id=mine.workspace_id,
                project_id=mine.project_id,
                user_id=None,
                membership_id=None,
            )
            await _insert_turn(
                conn,
                label="human",
                workspace_id=mine.workspace_id,
                project_id=mine.project_id,
                user_id=here.user_id,
                membership_id=here.membership_id,
            )

    run_async(scenario())


# --- 2. the provisioned development principal ---------------------------------------------------


def test_provisioning_creates_lane_b_rows_and_is_idempotent(require_db: None) -> None:
    """Second boot finds its rows: same ids, one user, one membership, one identity mapping."""

    del require_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "ws-b1join-dev", name="B1 join dev")
            settings = _settings(
                chat_dev_principal_user_id="usr_b1join_dev",
                chat_dev_principal_membership_id="wsm_b1join_dev",
                chat_dev_principal_workspace_id=project.workspace_id,
            )

            first = await provision_dev_principal(conn, settings=settings)
            second = await provision_dev_principal(conn, settings=settings)
            assert first == second
            assert first.user_id == "usr_b1join_dev"
            assert first.membership_id == "wsm_b1join_dev"
            assert first.workspace_id == project.workspace_id
            assert first.role_key == "owner"

            # Real rows, through Lane B's own tables — not strings in a settings file.
            user = await get_platform_user(conn, first.user_id)
            assert user is not None and user.status == "active"
            membership = await get_workspace_membership(
                conn, workspace_id=project.workspace_id, user_id=first.user_id
            )
            assert membership is not None and membership.status == "active"
            counts = (
                await conn.execute(
                    text(
                        "SELECT (SELECT count(*) FROM platform_user WHERE user_id = :u), "
                        "       (SELECT count(*) FROM workspace_membership WHERE user_id = :u), "
                        "       (SELECT count(*) FROM auth_identity "
                        "        WHERE provider_key = :p AND provider_subject = :s)"
                    ),
                    {
                        "u": first.user_id,
                        "p": DEV_PROVIDER_KEY,
                        "s": dev_provider_subject(first.user_id),
                    },
                )
            ).one()
            assert tuple(counts) == (1, 1, 1)

            # And the ownership FKs accept exactly these ids — the point of the whole slice.
            await _insert_thread(
                conn,
                workspace_id=project.workspace_id,
                project_id=project.project_id,
                user_id=first.user_id,
                membership_id=first.membership_id,
            )

    run_async(scenario())


def test_provisioning_refuses_rather_than_inventing_what_it_cannot_find(require_db: None) -> None:
    """Every refusal path names the setting or row that is wrong; none of them degrades."""

    del require_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "ws-b1join-refuse", name="B1 join refuse")
            base = {
                "chat_dev_principal_user_id": "usr_b1join_refuse",
                "chat_dev_principal_membership_id": "wsm_b1join_refuse",
                "chat_dev_principal_workspace_id": project.workspace_id,
            }

            with pytest.raises(DevPrincipalUnavailable) as unnamed:
                await provision_dev_principal(
                    conn, settings=_settings(**{**base, "chat_dev_principal_workspace_id": ""})
                )
            assert "CLUE_CHAT_DEV_PRINCIPAL_WORKSPACE_ID" in str(unnamed.value)

            with pytest.raises(DevPrincipalUnavailable) as absent:
                await provision_dev_principal(
                    conn,
                    settings=_settings(
                        **{**base, "chat_dev_principal_workspace_id": "ws-b1join-nonexistent"}
                    ),
                )
            assert "does not exist" in str(absent.value)

            with pytest.raises(DevPrincipalUnavailable) as blank:
                await provision_dev_principal(
                    conn, settings=_settings(**{**base, "chat_dev_principal_user_id": "  "})
                )
            assert "CLUE_CHAT_DEV_PRINCIPAL_USER_ID" in str(blank.value)

            # A membership id that disagrees with Postgres is a configuration error, not a second
            # membership: ``unique (workspace_id, user_id)`` means the pair has exactly one.
            await provision_dev_principal(conn, settings=_settings(**base))
            with pytest.raises(DevPrincipalUnavailable) as mismatched:
                await provision_dev_principal(
                    conn,
                    settings=_settings(
                        **{**base, "chat_dev_principal_membership_id": "wsm_b1join_other"}
                    ),
                )
            assert "wsm_b1join_refuse" in str(mismatched.value)

            # A disabled identity is never silently reactivated.
            await disable_platform_user(conn, "usr_b1join_refuse")
            with pytest.raises(DevPrincipalUnavailable) as disabled:
                await provision_dev_principal(conn, settings=_settings(**base))
            assert "disabled" in str(disabled.value)

    run_async(scenario())


def test_the_provisioned_resolver_carries_verified_ids_and_stays_out_of_production(
    require_db: None,
) -> None:
    """The resolver closes over provisioned ids; production still refuses the dev principal."""

    del require_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "ws-b1join-resolver", name="B1 join resolver")
            settings = _settings(
                chat_dev_principal_user_id="usr_b1join_resolver",
                chat_dev_principal_membership_id="wsm_b1join_resolver",
                chat_dev_principal_workspace_id=project.workspace_id,
            )
            cf = conn_session_factory(conn)

            resolver = await build_provisioned_dev_principal_resolver(settings, conn_factory=cf)
            principal = resolver(project.workspace_id)
            assert principal.user_id == "usr_b1join_resolver"
            assert principal.membership_id == "wsm_b1join_resolver"
            assert principal.workspace_id == project.workspace_id
            assert await get_platform_user(conn, principal.user_id) is not None

            # The principal is pinned to the workspace it holds a membership of; the router's
            # existing re-check turns any other selector into 403 WORKSPACE_FORBIDDEN.
            assert resolver("ws-b1join-somewhere-else").workspace_id == project.workspace_id

            with pytest.raises(ProductionPrincipalRequired):
                await build_provisioned_dev_principal_resolver(
                    _settings(
                        projections_auth_mode="service",
                        chat_dev_principal_workspace_id=project.workspace_id,
                    ),
                    conn_factory=cf,
                )

    run_async(scenario())


def test_the_startup_resolver_answers_nobody_until_provisioning_succeeded(
    require_db: None,
) -> None:
    """Startup binding is the only way this resolver starts answering; a failure stops the boot."""

    del require_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "ws-b1join-startup", name="B1 join startup")
            cf = conn_session_factory(conn)
            resolver = StartupDevPrincipalResolver()

            with pytest.raises(DevPrincipalUnavailable):
                resolver(project.workspace_id)

            # An unprovisionable configuration fails the bind — which is what aborts startup — and
            # leaves the resolver still refusing rather than half-bound.
            with pytest.raises(DevPrincipalUnavailable):
                await resolver.bind(
                    _settings(chat_dev_principal_workspace_id="ws-b1join-nonexistent"),
                    conn_factory=cf,
                )
            with pytest.raises(DevPrincipalUnavailable):
                resolver(project.workspace_id)

            ids = await resolver.bind(
                _settings(
                    chat_dev_principal_user_id="usr_b1join_startup",
                    chat_dev_principal_membership_id="wsm_b1join_startup",
                    chat_dev_principal_workspace_id=project.workspace_id,
                ),
                conn_factory=cf,
            )
            assert ids.user_id == "usr_b1join_startup"
            assert resolver(project.workspace_id).membership_id == ids.membership_id

    run_async(scenario())


# --- 3. ensure_platform_thread ------------------------------------------------------------------


def test_ensuring_the_same_platform_thread_twice_is_a_no_op(require_db: None) -> None:
    """The idempotent path the turn journal depends on stays idempotent."""

    del require_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, "ws-b1join-ensure", name="B1 join ensure")
            thread_id = f"thr_{uuid4().hex}"
            for _ in range(2):
                await ensure_platform_thread(
                    conn,
                    thread_id=thread_id,
                    workspace_id=project.workspace_id,
                    project_id=project.project_id,
                )
            rows = (
                await conn.execute(
                    text("SELECT count(*) FROM agent_thread WHERE id = :id"), {"id": thread_id}
                )
            ).scalar_one()
            assert rows == 1

    run_async(scenario())


def test_a_turn_cannot_attach_to_a_thread_owned_by_another_project(require_db: None) -> None:
    """The D0 review's finding: same workspace, different project, silently accepted. No longer."""

    del require_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            first = await seed_project(conn, "ws-b1join-attach", name="B1 join attach one")
            second = await seed_project(conn, "ws-b1join-attach", name="B1 join attach two")
            elsewhere = await seed_project(conn, "ws-b1join-attach-other", name="B1 join attach ws")
            assert first.project_id != second.project_id

            thread_id = f"thr_{uuid4().hex}"
            await ensure_platform_thread(
                conn,
                thread_id=thread_id,
                workspace_id=first.workspace_id,
                project_id=first.project_id,
            )

            with pytest.raises(ThreadOwnershipMismatch) as crossed:
                await ensure_platform_thread(
                    conn,
                    thread_id=thread_id,
                    workspace_id=first.workspace_id,
                    project_id=second.project_id,
                )
            assert crossed.value.reason_code == "thread_project_mismatch"
            # The refusal never names the owner: an id guesser learns nothing.
            assert first.project_id not in str(crossed.value)

            with pytest.raises(ThreadOwnershipMismatch) as foreign:
                await ensure_platform_thread(
                    conn,
                    thread_id=thread_id,
                    workspace_id=elsewhere.workspace_id,
                    project_id=elsewhere.project_id,
                )
            assert foreign.value.reason_code == "thread_project_mismatch"

            # Nothing was written by either refusal, and the original row is untouched.
            owner = (
                await conn.execute(
                    text("SELECT workspace_id, project_id FROM agent_thread WHERE id = :id"),
                    {"id": thread_id},
                )
            ).one()
            assert tuple(owner) == (first.workspace_id, first.project_id)

    run_async(scenario())
