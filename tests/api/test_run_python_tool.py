"""``run_python@1`` — the refusals it owes, the run it reports, and where it is registered.

Nothing here starts a container. The tool's whole job above :mod:`clue_api.sandbox` is deciding
whether a run may happen at all, spending the turn's budget when it may, and turning what came
back into a bounded typed result — so the container itself is the one thing that is replaced with
a stub. Every test either checks a refusal before ``run_script`` would be reached, or hands the
tool a scripted :class:`~clue_api.sandbox.docker_runner.SandboxRun` and reads what it made of it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from clue_agents import AgentRole
from clue_api.agent_registry_wiring import C6_AGENT_TOOL_AUTHORITY, c6_roles_for_tool
from clue_api.run_python_tool import (
    INLINE_OUTPUT_BUDGET_BYTES,
    RunPythonInput,
    RunPythonTool,
    build_run_python_tools,
)
from clue_api.sandbox.docker_runner import SandboxRun
from clue_api.sandbox.workspaces import SandboxMounts, SandboxWorkspaces, sandbox_mounts_for_lease
from clue_api.toolbelt_wiring import build_toolbelt
from clue_config import Settings
from clue_core import ExecutionId, OperationId
from clue_db import transaction
from clue_toolbelt import PreconditionFailed, ToolContext, ToolEffectClass, ToolResult
from tests.agents.workspace_helpers import make_workspace, policy
from tests.api.sandbox.test_workspaces import _mounts

_EXECUTION = ExecutionId(UUID("00000000-0000-0000-0000-0000000010a1"))
_UNREGISTERED = ExecutionId(UUID("00000000-0000-0000-0000-0000000010a2"))
_OPERATION = OperationId(UUID("00000000-0000-0000-0000-0000000010b1"))


def _settings(**updates: Any) -> Settings:
    """A settings object with the sandbox switched on, so a test only names what it changes."""

    return Settings(_env_file=None, **{"sandbox_enabled": True, **updates})


def _context(execution_id: ExecutionId | None = _EXECUTION) -> ToolContext:
    return ToolContext(
        workspace_id="ws-1",
        actor="agent",
        conn_factory=transaction,
        operation_id=_OPERATION,
        execution_id=execution_id,
    )


def _registry(tmp_path: Path, *, max_runs_per_turn: int = 3) -> SandboxWorkspaces:
    """A registry with this turn's workspace bound and its read-write tree on disk."""

    registry = SandboxWorkspaces(max_runs_per_turn=max_runs_per_turn)
    mounts = _mounts(tmp_path)
    for host in mounts.read_write.values():
        host.mkdir(parents=True, exist_ok=True)
    registry.register(_EXECUTION, mounts)
    return registry


def _lease_registry(tmp_path: Path, *, max_total_bytes: int) -> tuple[SandboxWorkspaces, Path]:
    """A registry bound from a real workspace lease, so its spill goes through the workspace.

    Returns the registry and the lease's agent root (F3 §12: spills count against the quota).
    """

    harness = make_workspace(
        tmp_path,
        active_policy=policy(
            max_total_bytes=max_total_bytes, max_file_bytes=max_total_bytes, max_file_count=50
        ),
    )
    registry = SandboxWorkspaces(max_runs_per_turn=3)
    registry.register(
        _EXECUTION,
        sandbox_mounts_for_lease(
            harness.lease, harness.factory, brand=None, project_library=False, attachments=False
        ),
    )
    return registry, harness.thread_path


def _available(monkeypatch: pytest.MonkeyPatch, *, ok: bool = True, reason: str = "") -> None:
    monkeypatch.setattr("clue_api.run_python_tool.docker_available", lambda image: (ok, reason))


def _stub_run(
    monkeypatch: pytest.MonkeyPatch,
    *,
    stdout: bytes = b"",
    stderr: bytes = b"",
    exit_code: int | None = 0,
    timed_out: bool = False,
    writes: dict[str, bytes] | None = None,
    seen: dict[str, Any] | None = None,
) -> None:
    """Replace the container with a function that records its arguments and writes some files."""

    def _fake(
        code: str,
        *,
        mounts: SandboxMounts,
        limits: Any,
        timeout_s: float,
        label: str | None = None,
        area: str | None = None,
    ) -> SandboxRun:
        if seen is not None:
            seen.update(
                code=code, limits=limits, timeout_s=timeout_s, label=label, mounts=mounts, area=area
            )
        for relative, body in (writes or {}).items():
            mount, _, rest = relative.partition("/")
            path = mounts.read_write[mount] / rest
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        return SandboxRun(
            exit_code=exit_code,
            timed_out=timed_out,
            duration_ms=12,
            stdout=stdout,
            stderr=stderr,
            stdout_truncated=False,
            stderr_truncated=False,
        )

    monkeypatch.setattr("clue_api.run_python_tool.run_script", _fake)


def _invoke(tool: RunPythonTool, inputs: RunPythonInput, ctx: ToolContext) -> ToolResult:
    return asyncio.run(tool.invoke(inputs, ctx))


def _refusal(excinfo: pytest.ExceptionInfo[PreconditionFailed]) -> tuple[str, str]:
    failures = excinfo.value.failures
    assert len(failures) == 1
    return failures[0].reason_code, failures[0].message


def test_a_switched_off_sandbox_refuses_before_it_looks_at_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The operator has not turned the sandbox on, so there is no run to plan."""

    _available(monkeypatch)
    tool = RunPythonTool(settings=_settings(sandbox_enabled=False), workspaces=_registry(tmp_path))

    with pytest.raises(PreconditionFailed) as excinfo:
        _invoke(tool, RunPythonInput(code="print(1)"), _context())

    code, message = _refusal(excinfo)
    assert code == "sandbox_unavailable"
    assert "not enabled" in message


def test_a_deployment_with_no_workspace_registry_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    """Registered everywhere, composed only where the turn worker binds workspaces."""

    _available(monkeypatch)
    tool = RunPythonTool(settings=_settings(), workspaces=None)

    with pytest.raises(PreconditionFailed) as excinfo:
        _invoke(tool, RunPythonInput(code="print(1)"), _context())

    code, _message = _refusal(excinfo)
    assert code == "sandbox_unavailable"


def test_a_host_without_the_image_refuses_and_names_the_command_that_builds_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one fix an operator can actually apply travels in the refusal."""

    _available(
        monkeypatch,
        ok=False,
        reason="The sandbox image `clue-agent-sandbox:latest` is not built on this host; "
        "run `make sandbox-image`.",
    )
    tool = RunPythonTool(settings=_settings(), workspaces=_registry(tmp_path))

    with pytest.raises(PreconditionFailed) as excinfo:
        _invoke(tool, RunPythonInput(code="print(1)"), _context())

    code, message = _refusal(excinfo)
    assert code == "sandbox_unavailable"
    assert "make sandbox-image" in message


def test_a_call_outside_a_turn_has_no_workspace_to_run_over(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No execution id, so nothing bound this call to a thread's directories."""

    _available(monkeypatch)
    tool = RunPythonTool(settings=_settings(), workspaces=_registry(tmp_path))

    with pytest.raises(PreconditionFailed) as excinfo:
        _invoke(tool, RunPythonInput(code="print(1)"), _context(execution_id=None))

    code, _message = _refusal(excinfo)
    assert code == "workspace_unavailable"


def test_a_turn_nobody_registered_is_refused_rather_than_run_over_a_guessed_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _available(monkeypatch)
    tool = RunPythonTool(settings=_settings(), workspaces=_registry(tmp_path))

    with pytest.raises(PreconditionFailed) as excinfo:
        _invoke(tool, RunPythonInput(code="print(1)"), _context(execution_id=_UNREGISTERED))

    code, _message = _refusal(excinfo)
    assert code == "workspace_unavailable"


def test_the_turn_run_budget_refuses_the_run_after_it_the_last_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One run per turn means the second call is refused, not queued or silently allowed."""

    _available(monkeypatch)
    _stub_run(monkeypatch, stdout=b"ok\n")
    tool = RunPythonTool(settings=_settings(), workspaces=_registry(tmp_path, max_runs_per_turn=1))

    first = _invoke(tool, RunPythonInput(code="print(1)"), _context())
    assert first.references["runs_remaining"] == 0

    with pytest.raises(PreconditionFailed) as excinfo:
        _invoke(tool, RunPythonInput(code="print(2)"), _context())

    code, _message = _refusal(excinfo)
    assert code == "run_budget_exhausted"


def test_a_refused_run_does_not_spend_the_turn_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A host without an image must not cost the turn the run it never got."""

    _available(monkeypatch, ok=False, reason="no image; run `make sandbox-image`.")
    workspaces = _registry(tmp_path, max_runs_per_turn=2)
    tool = RunPythonTool(settings=_settings(), workspaces=workspaces)

    with pytest.raises(PreconditionFailed):
        _invoke(tool, RunPythonInput(code="print(1)"), _context())

    assert workspaces.runs_remaining(_EXECUTION) == 2


def test_a_successful_run_reports_its_output_its_files_and_what_is_left_of_the_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The happy path: exit status, the files the sweep kept, and the decremented budget."""

    _available(monkeypatch)
    _stub_run(
        monkeypatch,
        stdout=b"rows: 3\n",
        stderr=b"",
        writes={"scratch/summary.md": b"hello", "scratch/tool.py": b"import os"},
    )
    tool = RunPythonTool(settings=_settings(), workspaces=_registry(tmp_path))

    result = _invoke(tool, RunPythonInput(code="print('rows: 3')"), _context())

    references = result.references
    assert result.tool == "run_python"
    assert references["exit_code"] == 0
    assert references["timed_out"] is False
    assert references["stdout"] == "rows: 3\n"
    assert references["stdout_spilled_to"] is None
    assert references["stderr"] == ""
    assert references["runs_remaining"] == 2
    # The sweep's verdict travels verbatim: the profile allows `.md` and never `.py`.
    assert references["files_written"] == ({"path": "scratch/summary.md", "size": 5},)
    assert references["files_removed"] == (
        {"path": "scratch/tool.py", "reason": "extension_not_allowed"},
    )


def test_a_timeout_is_a_result_with_no_exit_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The container overran; that is reported, not raised."""

    _available(monkeypatch)
    _stub_run(monkeypatch, stdout=b"partial", exit_code=None, timed_out=True)
    tool = RunPythonTool(settings=_settings(), workspaces=_registry(tmp_path))

    result = _invoke(tool, RunPythonInput(code="while True: pass"), _context())

    assert result.references["timed_out"] is True
    assert result.references["exit_code"] is None
    assert result.references["stdout"] == "partial"


def test_a_requested_timeout_is_clamped_to_the_operator_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A model may ask for less time than the operator allows, and never for more."""

    _available(monkeypatch)
    seen: dict[str, Any] = {}
    _stub_run(monkeypatch, seen=seen)
    tool = RunPythonTool(settings=_settings(sandbox_timeout_s=30.0), workspaces=_registry(tmp_path))

    _invoke(tool, RunPythonInput(code="pass", timeout_s=300.0), _context())
    assert seen["timeout_s"] == 30.0

    _invoke(tool, RunPythonInput(code="pass", timeout_s=5.0), _context())
    assert seen["timeout_s"] == 5.0

    _invoke(tool, RunPythonInput(code="pass"), _context())
    assert seen["timeout_s"] == 30.0


def test_the_run_is_labelled_with_the_turn_so_a_timed_out_container_can_be_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _available(monkeypatch)
    seen: dict[str, Any] = {}
    _stub_run(monkeypatch, seen=seen)
    tool = RunPythonTool(settings=_settings(), workspaces=_registry(tmp_path))

    _invoke(tool, RunPythonInput(code="pass"), _context())

    assert seen["label"] == str(_EXECUTION)
    assert seen["limits"].image == "clue-agent-sandbox:latest"
    assert seen["limits"].max_output_bytes == 1_048_576


def test_output_past_the_inline_budget_spills_to_a_file_the_agent_can_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A wall of stdout does not enter the turn's context; its path does."""

    _available(monkeypatch)
    body = b"x" * (INLINE_OUTPUT_BUDGET_BYTES + 500)
    _stub_run(monkeypatch, stdout=body, stderr=b"y" * (INLINE_OUTPUT_BUDGET_BYTES + 1))
    workspaces, agent_root = _lease_registry(tmp_path, max_total_bytes=1_000_000)
    tool = RunPythonTool(settings=_settings(), workspaces=workspaces)

    result = _invoke(tool, RunPythonInput(code="pass"), _context())

    references = result.references
    assert references["stdout_spilled_to"] == f"reads/{_OPERATION}.stdout.txt"
    assert references["stderr_spilled_to"] == f"reads/{_OPERATION}.stderr.txt"
    assert len(references["stdout"].encode()) == INLINE_OUTPUT_BUDGET_BYTES
    spilled = agent_root / "reads" / f"{_OPERATION}.stdout.txt"
    assert spilled.read_bytes() == body
    # 0o600: the spill is the turn's, and nothing on the host but this process reads it.
    assert spilled.stat().st_mode & 0o777 == 0o600


def test_output_within_the_inline_budget_spills_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _available(monkeypatch)
    _stub_run(monkeypatch, stdout=b"short")
    tool = RunPythonTool(settings=_settings(), workspaces=_registry(tmp_path))

    result = _invoke(tool, RunPythonInput(code="pass"), _context())

    assert result.references["stdout_spilled_to"] is None
    assert not (tmp_path / "reads").exists()


def test_undecodable_output_is_replaced_rather_than_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A script that prints raw bytes must not take the turn down with a decode error."""

    _available(monkeypatch)
    _stub_run(monkeypatch, stdout=b"\xff\xfe ok")
    tool = RunPythonTool(settings=_settings(), workspaces=_registry(tmp_path))

    result = _invoke(tool, RunPythonInput(code="pass"), _context())

    assert result.references["stdout"].endswith(" ok")


def test_the_builder_yields_one_tool_and_composes_without_a_registry() -> None:
    tools = build_run_python_tools(settings=_settings(), workspaces=None)

    assert [tool.descriptor.address for tool in tools] == ["run_python@1"]


def test_the_tool_is_registered_at_run_python_1_and_granted_to_the_head_of_abm() -> None:
    """Task 10 registered the write surface ungranted; `head-of-abm@v58` is the grant.

    The grant is a reviewed profile bump, never an edit to the authority dict: the profile
    version that holds it also pins the tool's two schema digests, opens `attachments` on the
    readable prefixes, and mints the skill and the manual chapters that teach it.
    """

    registry = build_toolbelt(storage=None, gateway=None)
    descriptor = registry.descriptor("run_python")

    assert descriptor.address == "run_python@1"
    assert descriptor.effect_class is ToolEffectClass.WRITE
    assert descriptor.recipe_safe
    assert descriptor.pin_requirements == ("project",)
    assert "attachments/" in descriptor.model_description
    assert C6_AGENT_TOOL_AUTHORITY["run_python"] == (AgentRole.HEAD_OF_ABM,)
    assert c6_roles_for_tool("run_python@1") == (AgentRole.HEAD_OF_ABM,)
    # Exactly one role holds it: the sandbox is the project conversation's, not a specialist's.
    assert len(C6_AGENT_TOOL_AUTHORITY["run_python"]) == 1


def test_an_output_spill_counts_against_the_workspace_quota(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F3 §12: a spill is an ordinary file of the workspace, so a full workspace refuses it."""

    from clue_agents import WorkspaceQuotaExceeded

    _available(monkeypatch)
    _stub_run(monkeypatch, stdout=b"x" * (INLINE_OUTPUT_BUDGET_BYTES + 500))
    workspaces, agent_root = _lease_registry(tmp_path, max_total_bytes=INLINE_OUTPUT_BUDGET_BYTES)
    tool = RunPythonTool(settings=_settings(), workspaces=workspaces)
    with pytest.raises(WorkspaceQuotaExceeded):
        _invoke(tool, RunPythonInput(code="pass"), _context())
    assert not (agent_root / "reads" / f"{_OPERATION}.stdout.txt").exists()
