"""Which database address each ingestion-pool process uses (first deployment, Task 3 Step 3).

On the worker VM every container reaches Postgres through PgBouncer in transaction mode, except
the ingestion pool's controller: its leadership claim is a SESSION advisory lock, which
transaction pooling would leave on a server connection other clients then borrow. So the
controller alone may be given a direct address (``LUMEN_INGESTION_CONTROLLER_DATABASE_URL``);
the coordinator and analysis children keep the container's ``CLUE_DATABASE_URL``.
"""

from __future__ import annotations

import subprocess

import pytest
from lumen_api import ingestion_pool
from py_lumen_config import Settings

DIRECT = "postgresql+asyncpg://clue_worker:pw@proxy.example:41234/railway?ssl=require"


@pytest.fixture
def engine_calls(monkeypatch: pytest.MonkeyPatch) -> list[str | None]:
    calls: list[str | None] = []
    monkeypatch.setattr(ingestion_pool, "create_engine", lambda url=None: calls.append(url))
    return calls


def test_the_controller_uses_its_own_direct_url_when_one_is_set(
    monkeypatch: pytest.MonkeyPatch, engine_calls: list[str | None]
) -> None:
    monkeypatch.setattr(ingestion_pool.settings, "lumen_ingestion_controller_database_url", DIRECT)
    ingestion_pool.controller_engine()
    assert engine_calls == [DIRECT]


def test_the_controller_falls_back_to_clue_database_url_when_unset(
    monkeypatch: pytest.MonkeyPatch, engine_calls: list[str | None]
) -> None:
    """Unset (the shipped default) = today's behaviour everywhere but the VM: ``None`` makes
    ``clue_db.create_engine`` read ``CLUE_DATABASE_URL``."""
    monkeypatch.setattr(ingestion_pool.settings, "lumen_ingestion_controller_database_url", "")
    ingestion_pool.controller_engine()
    assert engine_calls == [None]


def test_the_children_are_not_handed_the_controller_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Children inherit the container's environment untouched, so they keep the PgBouncer
    ``CLUE_DATABASE_URL``; nothing copies the direct address into it for them."""
    monkeypatch.setattr(ingestion_pool.settings, "lumen_ingestion_controller_database_url", DIRECT)
    started: list[dict] = []

    class FakeChild:
        pid = 4242

        def poll(self) -> None:
            return None

    def fake_popen(argv, **kwargs):
        started.append({"argv": argv, **kwargs})
        return FakeChild()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    processes = ingestion_pool.LocalProcesses()
    processes.log_dir = tmp_path
    processes.reconcile(["coordinator", "analysis"])
    assert [s["argv"][s["argv"].index("--role") + 1] for s in started] == [
        "coordinator",
        "analysis",
    ]
    for spawn in started:
        assert "env" not in spawn, "a child must inherit the container env, not a rewritten one"


def test_the_setting_loads_from_its_env_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LUMEN_INGESTION_CONTROLLER_DATABASE_URL", DIRECT)
    assert Settings(_env_file=None).lumen_ingestion_controller_database_url == DIRECT
    monkeypatch.delenv("LUMEN_INGESTION_CONTROLLER_DATABASE_URL")
    assert Settings(_env_file=None).lumen_ingestion_controller_database_url == ""
