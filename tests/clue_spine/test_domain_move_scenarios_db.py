"""The published-pages domain move, end to end (Wave 2 Contract 9).

Three real paths, no fakes for what is under test:

* the move script run as an operator runs it — a subprocess over COMMITTED rows in the test
  database (``scripts/move_system_hostnames.py``), dry run, apply, and a refused collision;
* connecting a custom domain after the move, through the real Settings → Pages route on the
  projections app, with the move's settings (only the Cloudflare provider and the DNS resolver are
  stood in, as the route's own suite does: they are external services, not what is tested here);
* the production env check run as the deploy runs it (``python3 deploy/check_prod_env.py``).

Scenario 8 commits rows because the script opens its own connection; every row it creates is
named with a random tag and deleted in a ``finally``, so a failing assertion still leaves the
throwaway test database as it found it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from fastapi import Request
from httpx import ASGITransport
from sqlalchemy import bindparam, text

from clue_api.chat import RequestPrincipal
from clue_api.frontend_read import FRONTEND_READ_PREFIX
from clue_api.frontend_read.app import frontend_read_workspace_resolver
from clue_api.projections_app import create_projections_app
from clue_auth.policy import permissions_for_role
from clue_config import load_settings
from clue_db import db_lifespan, transaction
from clue_db.engine import database_url
from clue_spine import create_workspace
from clue_spine.hostnames import (
    lock_system_hostname,
    move_system_hostnames,
    resolve_active_hostname,
    system_hostname,
)
from clue_storage import FsStorage
from tests._identity import fixture_membership_id, seed_principal
from tests.api.conftest import hermetic_flag_env
from tests.api.test_frontend_read_settings_pages_db import FakeCloudflare, FakeResolver
from tests.deploy.test_check_prod_env import GOOD_PLATFORM
from tests.profiling.conftest import conn_session_factory

from .conftest import rollback_conn, run_async

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MOVE_SCRIPT = _REPO_ROOT / "scripts" / "move_system_hostnames.py"
_CHECK_SCRIPT = _REPO_ROOT / "deploy" / "check_prod_env.py"

# --- scenario 8: the move script as a CLI ------------------------------------------------------


async def _hostname_rows(workspace_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Each workspace's system row, as committed (a fresh connection, nothing cached)."""
    async with db_lifespan(), transaction() as conn:
        rows = await conn.execute(
            text(
                "SELECT workspace_id, hostname, kind, status, locked_at FROM workspace_hostname "
                "WHERE workspace_id IN :ids AND kind = 'system'"
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": workspace_ids},
        )
        return {str(row.workspace_id): dict(row._mapping) for row in rows}


async def _create_committed_workspaces(
    specs: list[tuple[str, str]], created: list[str]
) -> list[str]:
    """``(name, suffix)`` → workspace ids, committed; each id is recorded for cleanup at once."""
    ids: list[str] = []
    async with db_lifespan():
        for name, suffix in specs:
            async with transaction() as conn:
                workspace = await create_workspace(conn, name=name, pages_system_suffix=suffix)
            created.append(workspace.workspace_id)
            ids.append(workspace.workspace_id)
    return ids


async def _lock(workspace_id: str) -> None:
    async with db_lifespan(), transaction() as conn:
        await lock_system_hostname(conn, workspace_id=workspace_id)


async def _resolve(hostname: str) -> str | None:
    async with db_lifespan(), transaction() as conn:
        return await resolve_active_hostname(conn, hostname)


async def _delete_workspaces(workspace_ids: list[str]) -> None:
    if not workspace_ids:
        return
    async with db_lifespan(), transaction() as conn:
        await conn.execute(
            text("DELETE FROM workspace_hostname WHERE workspace_id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": workspace_ids},
        )
        await conn.execute(
            text("DELETE FROM workspace WHERE workspace_id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": workspace_ids},
        )


async def _commit_custom_row(hostname: str, workspace_id: str) -> None:
    async with db_lifespan(), transaction() as conn:
        await conn.execute(
            text(
                "INSERT INTO workspace_hostname (hostname, workspace_id, kind, status, "
                "cname_target, ownership_txt_name, ownership_txt_value) VALUES "
                "(:h, :w, 'custom', 'pending_dns', 'pages.test', 'n', 'v')"
            ),
            {"h": hostname, "w": workspace_id},
        )


async def _hostnames_under(*suffixes: str) -> list[str]:
    async with db_lifespan(), transaction() as conn:
        found: list[str] = []
        for suffix in suffixes:
            rows = await conn.execute(
                text("SELECT hostname FROM workspace_hostname WHERE hostname LIKE :p"),
                {"p": f"%.{suffix}"},
            )
            found.extend(str(row[0]) for row in rows)
        return found


def _run_move(*, old: str, new: str, apply: bool) -> subprocess.CompletedProcess[str]:
    """The script exactly as the runbook runs it, pointed at the test database by its flag.

    The child's own ``CLUE_DATABASE_URL`` names an unreachable server: the script promises it never
    falls through to that variable, so a run that reads it fails instead of touching any DB.
    """
    env = {
        **os.environ,
        "CLUE_DATABASE_URL": "postgresql+asyncpg://nobody:nothing@127.0.0.1:9/never_used",
    }
    command = [
        sys.executable,
        str(_MOVE_SCRIPT),
        "--database-url",
        database_url(),
        "--from-suffix",
        old,
        "--to-suffix",
        new,
        *(["--apply"] if apply else []),
    ]
    return subprocess.run(
        command, capture_output=True, text=True, check=False, env=env, cwd=_REPO_ROOT, timeout=120
    )


def _label(hostname: str, suffix: str) -> str:
    assert hostname.endswith("." + suffix), hostname
    return hostname[: -(len(suffix) + 1)]


def test_the_move_script_dry_runs_applies_and_refuses_a_collision(
    require_spine_db: None,
) -> None:
    del require_spine_db
    tag = uuid4().hex[:8]
    old, new = f"old{tag}.test", f"new{tag}.test"
    created: list[str] = []
    try:
        first, second = run_async(
            _create_committed_workspaces(
                [(f"Move CLI Alpha {tag}", old), (f"Move CLI Beta {tag}", old)], created
            )
        )
        run_async(_lock(first))
        before = run_async(_hostname_rows([first, second]))
        assert before[first]["locked_at"] is not None
        assert before[second]["locked_at"] is None
        old_hosts = {ws: before[ws]["hostname"] for ws in (first, second)}
        labels = {ws: _label(old_hosts[ws], old) for ws in (first, second)}
        expected_moves = sorted(
            ({"from": old_hosts[ws], "to": f"{labels[ws]}.{new}"} for ws in (first, second)),
            key=lambda move: move["from"],
        )

        # 1. The dry run reports both rows and writes nothing.
        dry = _run_move(old=old, new=new, apply=False)
        assert dry.returncode == 0, dry.stderr
        assert json.loads(dry.stdout) == {
            "from_suffix": old,
            "to_suffix": new,
            "rows": 2,
            "collisions": [],
            "applied": False,
            "sample": expected_moves,
        }
        assert "dry run: nothing written" in dry.stderr
        assert run_async(_hostname_rows([first, second])) == before

        # 2. --apply moves both, keeping each label and each lock exactly.
        applied = _run_move(old=old, new=new, apply=True)
        assert applied.returncode == 0, applied.stderr
        report = json.loads(applied.stdout)
        assert report["rows"] == 2 and report["applied"] is True and report["collisions"] == []
        assert "REFUSED" not in applied.stderr
        after = run_async(_hostname_rows([first, second]))
        for ws in (first, second):
            assert after[ws] == {
                **before[ws],
                "hostname": f"{labels[ws]}.{new}",
            }, ws
        assert after[first]["locked_at"] == before[first]["locked_at"]
        assert after[second]["locked_at"] is None
        for ws in (first, second):
            assert run_async(_resolve(old_hosts[ws])) is None, old_hosts[ws]
            assert run_async(_resolve(f"{labels[ws]}.{new}")) == ws

        # 3. A collision refuses the whole move: exit 1, REFUSED, and NOTHING moves — not even the
        # row whose new hostname is free. Review finding S4-1 made a system label unique on every
        # domain, so a second workspace can no longer hold the clashing label on the new suffix;
        # what can still hold the new hostname is a custom row (the connect route refuses one under
        # our own domains, the table does not), committed here by hand.
        clashing, free, occupant = run_async(
            _create_committed_workspaces(
                [
                    (f"Move CLI Clash {tag}", old),
                    (f"Move CLI Free {tag}", old),
                    (f"Move CLI Occupant {tag}", new),
                ],
                created,
            )
        )
        prepared = run_async(_hostname_rows([clashing, free, occupant]))
        taken = f"{_label(prepared[clashing]['hostname'], old)}.{new}"
        run_async(_commit_custom_row(taken, occupant))
        refused = _run_move(old=old, new=new, apply=True)
        assert refused.returncode == 1, refused.stdout
        refused_report = json.loads(refused.stdout)
        assert refused_report["rows"] == 2
        assert refused_report["collisions"] == [taken]
        assert refused_report["applied"] is False
        assert "REFUSED: 1 new hostname(s) are already taken; nothing moved." in refused.stderr
        assert run_async(_hostname_rows([clashing, free, occupant])) == prepared
        assert run_async(_hostname_rows([first, second])) == after
    finally:
        run_async(_delete_workspaces(created))
        assert run_async(_hostnames_under(old, new)) == []


# --- scenario 9: connecting a custom domain after the move -------------------------------------

_SETTINGS_BASE = f"{FRONTEND_READ_PREFIX}/settings/pages"
_USER_ID = "usr_domain_move_settings"
_NEW_SUFFIX = "clue-pages.example"


def _settings_app(conn: Any, tmp_path: Path, *, legacy: str, cloudflare: FakeCloudflare) -> Any:
    app = create_projections_app(
        surface=None,  # type: ignore[arg-type]
        tool_invoker=None,  # type: ignore[arg-type]
        settings=load_settings(
            _env_file=None,
            frontend_read_enabled=True,
            arv2_display_generate_on_read=False,
            pages_system_suffix=_NEW_SUFFIX,
            pages_legacy_system_suffixes=legacy,
            pages_public_scheme="https",
            pages_public_port=None,
            pages_cname_target=_NEW_SUFFIX,
        ),
        conn_factory=conn_session_factory(conn),
        manage_db_lifespan=False,
        ingestion_storage=FsStorage(tmp_path / "blobs"),
    )
    app.state.pages_cloudflare = cloudflare
    app.state.pages_resolver = FakeResolver()

    async def _admin(request: Request) -> str:
        workspace_id = request.headers["X-Workspace-Id"]
        request.state.clue_principal = RequestPrincipal(
            user_id=_USER_ID,
            membership_id=fixture_membership_id(workspace_id=workspace_id, user_id=_USER_ID),
            workspace_id=workspace_id,
            role_key="admin",
            permissions=permissions_for_role("admin"),
            authenticated_at=datetime(2026, 10, 13, 9, 0, tzinfo=UTC),
        )
        return workspace_id

    app.dependency_overrides[frontend_read_workspace_resolver] = _admin
    return app


async def _settings_workspace(conn: Any, name: str, *, suffix: str = _NEW_SUFFIX) -> str:
    workspace = await create_workspace(
        conn, name=f"{name} {uuid4().hex[:4]}", pages_system_suffix=suffix
    )
    await seed_principal(conn, workspace_id=workspace.workspace_id, user_id=_USER_ID)
    return workspace.workspace_id


async def _connect(app: Any, workspace_id: str, hostname: str) -> httpx.Response:
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        return await client.post(
            f"{_SETTINGS_BASE}/custom-hostname",
            json={"hostname": hostname},
            headers={"X-Workspace-Id": workspace_id},
        )


def _refusal(response: httpx.Response) -> tuple[int, str, str]:
    error = response.json()["error"]
    return response.status_code, error["code"], error["message"]


def test_after_the_move_cluehq_ai_stays_reserved_through_the_settings_route(
    require_spine_db: None, tmp_path: Path
) -> None:
    del require_spine_db

    async def scenario() -> None:
        async with rollback_conn() as conn:
            cloudflare = FakeCloudflare()
            moved = _settings_app(conn, tmp_path, legacy="pages.cluehq.ai", cloudflare=cloudflare)
            # Acme was born on the old suffix and moved by the move's own DAL call (the one the
            # script runs), so the settings screen reads an address that really was moved.
            old = f"old{uuid4().hex[:8]}.test"
            acme = await _settings_workspace(conn, "Acme", suffix=old)
            born = await system_hostname(conn, acme)
            assert born is not None
            label = born.removesuffix("." + old)
            report = await move_system_hostnames(
                conn, from_suffix=old, to_suffix=_NEW_SUFFIX, apply=True
            )
            assert (report["rows"], report["applied"]) == (1, True)
            async with httpx.AsyncClient(
                transport=ASGITransport(app=moved), base_url="http://t"
            ) as client:
                read = await client.get(_SETTINGS_BASE, headers={"X-Workspace-Id": acme})
            assert read.status_code == 200, read.text
            assert read.json()["systemHostname"] == {
                "hostname": f"{label}.{_NEW_SUFFIX}",
                "label": label,
                "url": f"https://{label}.{_NEW_SUFFIX}",
            }

            reserved_ours = "Hostnames under cluehq.ai cannot be connected."
            for hostname in ("x.cluehq.ai", "acme.pages.cluehq.ai", "cluehq.ai"):
                assert _refusal(await _connect(moved, acme, hostname)) == (
                    422,
                    "hostname_reserved",
                    reserved_ours,
                ), hostname
            assert _refusal(await _connect(moved, acme, "acme.clue-pages.example")) == (
                422,
                "hostname_reserved",
                "Hostnames under clue-pages.example cannot be connected.",
            )
            assert cloudflare.calls == [], "a refused hostname never reaches the provider"

            accepted = await _connect(moved, acme, "go.acme.com")
            assert accepted.status_code == 201, accepted.text
            assert accepted.json()["customHostname"]["hostname"] == "go.acme.com"
            assert cloudflare.calls == [("create", "go.acme.com")]
            stored = (
                await conn.execute(
                    text("SELECT workspace_id, kind FROM workspace_hostname WHERE hostname = :h"),
                    {"h": "go.acme.com"},
                )
            ).one()
            assert (str(stored.workspace_id), str(stored.kind)) == (acme, "custom")

            # The legacy setting is what holds the reservation: empty it and cluehq.ai is just
            # another customer's domain, while the new suffix stays reserved on its own.
            unreserved = _settings_app(conn, tmp_path, legacy="", cloudflare=cloudflare)
            other = await _settings_workspace(conn, "Other")
            assert _refusal(await _connect(unreserved, other, "acme.clue-pages.example"))[:2] == (
                422,
                "hostname_reserved",
            )
            opened = await _connect(unreserved, other, "x.cluehq.ai")
            assert opened.status_code == 201, opened.text
            assert opened.json()["customHostname"]["hostname"] == "x.cluehq.ai"

    # The api suite's one policy for ambient activation flags (an operator's .env turns the chat
    # surface on, which this composition does not wire a principal for).
    with hermetic_flag_env():
        run_async(scenario())


# --- scenario 10: the production env check as a CLI -------------------------------------------


def _check(tmp_path: Path, name: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """``python3 deploy/check_prod_env.py platform-api <file>``, as the deploy runs it (the VM's
    system python3 — the script is standard library only)."""
    env_file = tmp_path / f"{name}.env"
    env_file.write_text("".join(f"{key}={value}\n" for key, value in env.items()), "utf-8")
    python = shutil.which("python3") or sys.executable
    return subprocess.run(
        [python, str(_CHECK_SCRIPT), "platform-api", str(env_file)],
        capture_output=True,
        text=True,
        check=False,
        cwd=_REPO_ROOT,
        timeout=60,
    )


def test_the_production_env_check_holds_the_move_to_its_rules(tmp_path: Path) -> None:
    moved = {**GOOD_PLATFORM, "CLUE_PAGES_SYSTEM_SUFFIX": _NEW_SUFFIX}

    today = _check(tmp_path, "today", GOOD_PLATFORM)
    assert (today.returncode, today.stdout) == (0, "OK\n")

    kept = _check(
        tmp_path, "moved-kept", {**moved, "CLUE_PAGES_LEGACY_SYSTEM_SUFFIXES": "pages.cluehq.ai"}
    )
    assert (kept.returncode, kept.stdout) == (0, "OK\n")

    for name, legacy in (("moved-dropped", "old.example"), ("moved-emptied", "")):
        dropped = _check(tmp_path, name, {**moved, "CLUE_PAGES_LEGACY_SYSTEM_SUFFIXES": legacy})
        assert dropped.returncode == 1, (name, dropped.stdout)
        assert dropped.stdout.splitlines() == [
            "PROBLEM: CLUE_PAGES_LEGACY_SYSTEM_SUFFIXES must keep pages.cluehq.ai once published "
            "pages move to their own domain (the custom-domain reservation depends on it)",
            "1 problem(s)",
        ], name

    elsewhere = _check(
        tmp_path, "pages2", {**GOOD_PLATFORM, "CLUE_PAGES_SYSTEM_SUFFIX": "pages2.cluehq.ai"}
    )
    assert elsewhere.returncode == 1, elsewhere.stdout
    assert elsewhere.stdout.splitlines() == [
        "PROBLEM: CLUE_PAGES_SYSTEM_SUFFIX must be pages.cluehq.ai or a hostname on the published "
        "pages' own domain, never another cluehq.ai name (is 'pages2.cluehq.ai')",
        "1 problem(s)",
    ]
