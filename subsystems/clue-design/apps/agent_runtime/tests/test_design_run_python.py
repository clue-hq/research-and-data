"""Design agents run Python over the chat's files (spec 2026-10-30 §3.5).

The ad, site and web agents get ``run_python``: the shared sandbox (``clue_agents.sandbox``) with
exactly two folders — ``attachments/`` read-only, so a person's file is never changed, and
``outputs/`` to write. Nothing else of the workspace is mounted. Off when the sandbox is disabled
or Docker cannot run it: the agent then has no such tool.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lumen_agent.sandbox_tool import (
    OUTPUTS_MAX_BYTES,
    RUN_PYTHON_DESCRIPTION,
    build_design_run_python_tool,
    design_sandbox_mounts,
)

from clue_agents.sandbox.docker_runner import docker_available
from clue_config import load_settings

_SETTINGS = load_settings(_env_file=None)
_DOCKER = docker_available(_SETTINGS.sandbox_image)[0]
needs_docker = pytest.mark.skipif(not _DOCKER, reason="no Docker or no sandbox image")


def test_the_mounts_are_attachments_to_read_and_outputs_to_write(tmp_path: Path) -> None:
    mounts = design_sandbox_mounts(tmp_path)
    assert dict(mounts.read_only) == {"attachments": tmp_path / "attachments"}
    assert dict(mounts.read_write) == {"outputs": tmp_path / "outputs"}
    assert mounts.policy.max_total_bytes == OUTPUTS_MAX_BYTES == 50 * 1024 * 1024
    assert (tmp_path / "attachments").is_dir() and (tmp_path / "outputs").is_dir()


def test_no_tool_when_the_sandbox_is_off(tmp_path: Path) -> None:
    off = _SETTINGS.model_copy(update={"sandbox_enabled": False})
    assert build_design_run_python_tool(workspace=tmp_path, run_id="run_1", settings=off) is None


def test_the_tool_says_what_it_is_for() -> None:
    assert "`attachments/` holds the files sent in this chat" in RUN_PYTHON_DESCRIPTION
    assert "`outputs/` is yours to write" in RUN_PYTHON_DESCRIPTION


@needs_docker
def test_a_script_reads_a_spreadsheet_and_writes_a_chart(tmp_path: Path) -> None:
    tool = build_design_run_python_tool(workspace=tmp_path, run_id="run_1", settings=_SETTINGS)
    # The host has no openpyxl; the sandbox image does. Make the person's spreadsheet there.
    made = json.loads(
        tool.invoke(
            {
                "code": (
                    "import openpyxl\n"
                    "book = openpyxl.Workbook()\n"
                    "book.active.append(['quarter', 'revenue'])\n"
                    "book.active.append(['Q3', 120])\n"
                    "book.save('outputs/report.xlsx')\n"
                )
            }
        )
    )
    assert made["exit_code"] == 0, made
    (tmp_path / "outputs" / "report.xlsx").rename(tmp_path / "attachments" / "report.xlsx")
    assert tool is not None and tool.name == "run_python"
    answer = json.loads(
        tool.invoke(
            {
                "code": (
                    "import openpyxl\n"
                    "rows = list(openpyxl.load_workbook('attachments/report.xlsx').active.values)\n"
                    "print(rows[1][1])\n"
                    "open('outputs/chart.png', 'wb').write(b'\\x89PNG\\r\\n\\x1a\\n')\n"
                )
            }
        )
    )
    assert answer["exit_code"] == 0 and answer["stdout"].strip() == "120"
    assert (tmp_path / "outputs" / "chart.png").is_file()


@needs_docker
def test_a_script_cannot_change_an_attached_file(tmp_path: Path) -> None:
    (tmp_path / "attachments").mkdir()
    (tmp_path / "attachments" / "brief.md").write_text("# Brief")
    tool = build_design_run_python_tool(workspace=tmp_path, run_id="run_1", settings=_SETTINGS)
    answer = json.loads(tool.invoke({"code": "open('attachments/brief.md', 'w').write('x')"}))
    assert answer["exit_code"] != 0
    assert (tmp_path / "attachments" / "brief.md").read_text() == "# Brief"


@needs_docker
def test_the_runs_per_request_are_counted(tmp_path: Path) -> None:
    settings = _SETTINGS.model_copy(update={"sandbox_max_runs_per_turn": 1})
    tool = build_design_run_python_tool(workspace=tmp_path, run_id="run_1", settings=settings)
    first = json.loads(tool.invoke({"code": "print(1)"}))
    assert first["runs_remaining"] == 0
    second = json.loads(tool.invoke({"code": "print(2)"}))
    assert second["error"] == "run_budget_exhausted"


def test_only_a_leg_request_gets_the_tool(tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace

    from lumen_agent import sandbox_tool

    sentinel = object()
    monkeypatch.setattr(sandbox_tool, "build_design_run_python_tool", lambda **kw: sentinel)
    direct, leg = SimpleNamespace(run_id="run_1"), SimpleNamespace(run_id="run_1")
    assert sandbox_tool.design_run_python(direct, tmp_path, None) is None
    assert direct.run_python_available is False
    assert sandbox_tool.design_run_python(leg, tmp_path, object()) is sentinel
    assert leg.run_python_available is True


def test_a_design_run_carries_the_workers_area_label(tmp_path: Path, monkeypatch) -> None:
    """Review M-2: a container a dead worker left running is killed by the next process of that
    worker area, which finds it by the area's label — so a design run must carry it too."""

    from types import SimpleNamespace

    from clue_agents import worker_area
    from lumen_agent import sandbox_tool

    seen: dict = {}

    def fake_run(code, *, mounts, limits, timeout_s, label=None, area=None):
        seen["area"] = area
        return SimpleNamespace(
            exit_code=0, timed_out=False, stdout=b"", stderr=b"",
            stdout_truncated=False, stderr_truncated=False, duration_ms=1,
        )

    monkeypatch.setattr(sandbox_tool, "run_script", fake_run)
    monkeypatch.setattr(sandbox_tool, "docker_available", lambda image: (True, ""))
    monkeypatch.setattr(worker_area, "_PROCESS_AREAS", {})
    (tmp_path / "root" / "workers").mkdir(parents=True)
    area = worker_area.process_worker_area(tmp_path / "root")
    tool = build_design_run_python_tool(workspace=tmp_path / "ws", run_id="run_1", settings=_SETTINGS)
    tool.invoke({"code": "print(1)"})
    assert seen["area"] == area.name
