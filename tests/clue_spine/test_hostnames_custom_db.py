from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from clue_spine import create_workspace
from clue_spine.hostnames import (
    HostnameRefused,
    delete_custom_hostname,
    get_custom_hostname,
    hostname_exists,
    insert_custom_hostname,
    lock_system_hostname,
    record_custom_hostname_check,
    replace_system_label,
    resolve_active_hostname,
    set_custom_hostname_provider,
    set_custom_hostname_status,
    system_hostname,
)

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_spine_db")
SUFFIX = "pages.test"
T0 = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def _host() -> str:
    return f"go.{uuid4().hex[:8]}.example"


def test_connect_lifecycle_rows() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = await create_workspace(
                conn, name="Acme " + uuid4().hex[:4], pages_system_suffix=SUFFIX
            )
            host = _host()
            assert await get_custom_hostname(conn, ws.workspace_id) is None
            assert not await hostname_exists(conn, host)
            row = await insert_custom_hostname(
                conn, workspace_id=ws.workspace_id, hostname=host, cname_target="pages.test"
            )
            assert row.status == "pending_dns" and row.ownership_txt_name == "pending"
            assert await hostname_exists(conn, host)
            await set_custom_hostname_provider(
                conn,
                hostname=host,
                cf_custom_hostname_id="cf_1",
                ownership_txt_name=f"_cf-custom-hostname.{host}",
                ownership_txt_value="tok",
            )
            checked = await record_custom_hostname_check(
                conn,
                hostname=host,
                status="verifying_ownership",
                observed_cname="pages.test",
                observed_txt_present=False,
                last_error_code=None,
                last_error_detail=None,
                checked_at=T0,
            )
            assert checked.observed_cname == "pages.test" and checked.activated_at is None
            assert await resolve_active_hostname(conn, host) is None
            active = await record_custom_hostname_check(
                conn,
                hostname=host,
                status="active",
                observed_cname="pages.test",
                observed_txt_present=True,
                last_error_code=None,
                last_error_detail=None,
                checked_at=T0,
            )
            assert active.activated_at is not None
            assert await resolve_active_hostname(conn, host) == ws.workspace_id
            await set_custom_hostname_status(conn, hostname=host, status="disconnecting")
            assert await resolve_active_hostname(conn, host) is None
            assert await delete_custom_hostname(conn, hostname=host) is True
            assert await delete_custom_hostname(conn, hostname=host) is False

    run_async(scenario())


def test_second_custom_row_and_taken_hostname_are_integrity_errors() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            a = await create_workspace(
                conn, name="A " + uuid4().hex[:4], pages_system_suffix=SUFFIX
            )
            b = await create_workspace(
                conn, name="B " + uuid4().hex[:4], pages_system_suffix=SUFFIX
            )
            host = _host()
            await insert_custom_hostname(
                conn, workspace_id=a.workspace_id, hostname=host, cname_target="pages.test"
            )
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await insert_custom_hostname(
                        conn, workspace_id=b.workspace_id, hostname=host, cname_target="pages.test"
                    )
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await insert_custom_hostname(
                        conn,
                        workspace_id=a.workspace_id,
                        hostname=_host(),
                        cname_target="pages.test",
                    )

    run_async(scenario())


def test_replace_system_label_is_atomic_and_frees_the_old_label() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = await create_workspace(
                conn, name="Label " + uuid4().hex[:4], pages_system_suffix=SUFFIX
            )
            old = await system_hostname(conn, ws.workspace_id)
            new = await replace_system_label(
                conn,
                workspace_id=ws.workspace_id,
                label="acme-hq-" + uuid4().hex[:4],
                suffix=SUFFIX,
            )
            assert new.kind == "system" and new.status == "active"
            assert await system_hostname(conn, ws.workspace_id) == new.hostname
            assert old is not None and await resolve_active_hostname(conn, old) is None
            other = await create_workspace(
                conn, name="Other " + uuid4().hex[:4], pages_system_suffix=SUFFIX
            )
            with pytest.raises(HostnameRefused) as caught:
                await replace_system_label(
                    conn,
                    workspace_id=other.workspace_id,
                    label=new.hostname.removesuffix("." + SUFFIX),
                    suffix=SUFFIX,
                )
            assert caught.value.code == "label_taken"
            with pytest.raises(HostnameRefused):
                await replace_system_label(
                    conn, workspace_id=ws.workspace_id, label="www", suffix=SUFFIX
                )

    run_async(scenario())


def test_label_locks_at_first_publish() -> None:
    """F5 R-F5-5, adopted 2026-09-28: the first publish freezes the system label."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = await create_workspace(
                conn, name="Lock " + uuid4().hex[:4], pages_system_suffix=SUFFIX
            )
            first = await lock_system_hostname(conn, workspace_id=ws.workspace_id)
            assert first.locked_at is not None
            again = await lock_system_hostname(conn, workspace_id=ws.workspace_id)
            assert again.locked_at == first.locked_at  # idempotent, never moves forward
            assert again.hostname == first.hostname
            with pytest.raises(HostnameRefused) as caught:
                await replace_system_label(
                    conn,
                    workspace_id=ws.workspace_id,
                    label="acme-new-" + uuid4().hex[:4],
                    suffix=SUFFIX,
                )
            assert caught.value.code == "label_locked"
            # The refusal left the locked row exactly where it was.
            assert await system_hostname(conn, ws.workspace_id) == first.hostname

    run_async(scenario())


def test_lock_without_a_system_row_refuses() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = await create_workspace(
                conn, name="Bare " + uuid4().hex[:4], pages_system_suffix=SUFFIX
            )
            await conn.execute(
                text("DELETE FROM workspace_hostname WHERE workspace_id = :w AND kind = 'system'"),
                {"w": ws.workspace_id},
            )
            with pytest.raises(HostnameRefused) as caught:
                await lock_system_hostname(conn, workspace_id=ws.workspace_id)
            assert caught.value.code == "system_hostname_missing"

    run_async(scenario())
