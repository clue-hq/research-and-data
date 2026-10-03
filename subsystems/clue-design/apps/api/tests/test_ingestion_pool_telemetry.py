"""Every ingestion-pool process installs production telemetry as ``clue-ingestion-pool`` at start
and flushes it on exit (first production deploy, 2026-10-03: the controller and the analysis
workers had none, and the coordinator reported as ``clue-design-api`` because importing
``lumen_api.main`` for a job installed it under that name)."""

from __future__ import annotations

import sys
from typing import Any

import pytest
from lumen_api import ingestion_pool


class _Runtime:
    def __init__(self) -> None:
        self.shut_down = False

    def shutdown(self) -> None:
        self.shut_down = True


@pytest.fixture
def installs(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    seen: dict[str, Any] = {"runtime": _Runtime(), "flushed": False}
    monkeypatch.setattr(ingestion_pool, "_process_has_tracer", lambda: False)
    monkeypatch.setattr(ingestion_pool, "load_settings", lambda: "settings")
    monkeypatch.setattr(ingestion_pool, "Secrets", lambda: "secrets")

    def tracing(settings: Any, secrets: Any, *, service_name: str) -> _Runtime:
        seen["tracing"] = service_name
        return seen["runtime"]

    def sentry(settings: Any, secrets: Any, *, service_name: str) -> bool:
        seen["sentry"] = service_name
        return True

    def langfuse(settings: Any, secrets: Any, *, runtime: Any, service_name: str) -> bool:
        seen["langfuse"] = (service_name, runtime)
        return True

    def flush() -> None:
        seen["flushed"] = True

    monkeypatch.setattr(ingestion_pool, "install_production_tracing", tracing)
    monkeypatch.setattr(ingestion_pool, "install_production_sentry", sentry)
    monkeypatch.setattr(ingestion_pool, "install_production_langfuse", langfuse)
    monkeypatch.setattr(ingestion_pool, "flush_langfuse", flush)
    monkeypatch.setattr(ingestion_pool, "shutdown_langfuse", lambda: None)
    return seen


@pytest.mark.parametrize("role", ["controller", "coordinator", "analysis"])
def test_every_role_installs_telemetry_as_the_pool_and_flushes_on_exit(
    monkeypatch: pytest.MonkeyPatch, installs: dict[str, Any], role: str
) -> None:
    ran: list[str] = []

    async def body() -> None:
        ran.append("ran")

    monkeypatch.setattr(ingestion_pool, "controller", body)
    monkeypatch.setattr(ingestion_pool, "execution", lambda role, parent_pid: body())
    monkeypatch.setattr(ingestion_pool, "setup", lambda: None)
    monkeypatch.setattr(sys, "argv", ["ingestion_pool", "--role", role])
    ingestion_pool.main()
    assert ran == ["ran"]
    assert installs["tracing"] == "clue-ingestion-pool"
    assert installs["sentry"] == "clue-ingestion-pool"
    assert installs["langfuse"] == ("clue-ingestion-pool", installs["runtime"])
    assert installs["flushed"] and installs["runtime"].shut_down


def test_a_process_that_already_has_a_tracer_is_left_alone(
    monkeypatch: pytest.MonkeyPatch, installs: dict[str, Any]
) -> None:
    monkeypatch.setattr(ingestion_pool, "_process_has_tracer", lambda: True)
    assert ingestion_pool.install_pool_telemetry() is None
    assert "tracing" not in installs


def test_telemetry_is_flushed_even_when_the_role_crashes(
    monkeypatch: pytest.MonkeyPatch, installs: dict[str, Any]
) -> None:
    async def boom() -> None:
        raise RuntimeError("crash")

    monkeypatch.setattr(ingestion_pool, "controller", boom)
    monkeypatch.setattr(ingestion_pool, "setup", lambda: None)
    monkeypatch.setattr(sys, "argv", ["ingestion_pool"])
    with pytest.raises(RuntimeError, match="crash"):
        ingestion_pool.main()
    assert installs["flushed"] and installs["runtime"].shut_down
