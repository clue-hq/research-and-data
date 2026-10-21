"""``run_python@1`` — the Head of ABM runs a short script over its own workspace.

The agent can already read a markdown file and write one. What it could not do is *open* the
things people actually attach to a project: a PDF of last year's results, a spreadsheet of
accounts, a deck. Those are files no prompt can read by looking at them; they need code. This
tool is that code path, and it is deliberately the narrowest one that works — one short script,
one locked-down container, one turn's workspace, a handful of runs per turn.

Four things are the tool's own job, and everything else belongs to the three modules under
:mod:`clue_api.sandbox` that it composes:

* **Deciding whether a run may happen at all.** Five refusals, each with a stable code: the
  sandbox is off, this deployment composed no workspace registry, the host cannot run the image,
  this turn registered no workspace, or this turn has spent its runs. Every one of them is raised
  *before* a container starts, and a refused call never costs the turn a run.
* **Spending the turn's budget.** :meth:`~clue_api.sandbox.workspaces.SandboxWorkspaces.take_run`
  is the meter, and the remaining count travels back in the result so the model can see what it
  has left rather than discovering the ceiling by hitting it.
* **Keeping the event loop free.** The container, the before-picture and the policy sweep all
  block; they run together on one worker thread, so a sixty-second script does not stop the
  process serving every other turn.
* **Keeping the output bounded.** Everything past
  :data:`INLINE_OUTPUT_BUDGET_BYTES` is written to a file under the thread's ``reads/`` directory
  and named in the result instead of being poured into the conversation. A script that prints a
  whole spreadsheet gets a path back, which is a thing the agent can open with the file tools it
  already has.

The tool takes no database connection and reads no row: its entire authority is the turn's own
execution id and the directories the worker bound to it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import ClassVar, Final

from pydantic import Field

from clue_agents.manual import tool_manual_link
from clue_api.sandbox.docker_runner import SandboxLimits, SandboxRun, docker_available, run_script
from clue_api.sandbox.policy_sweep import SweepResult, snapshot, sweep
from clue_api.sandbox.workspaces import RunBudgetExhausted, SandboxMounts, SandboxWorkspaces
from clue_config import Settings
from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
    PreconditionFailed,
    PreconditionFailure,
    ReplayPolicy,
    ReplaySafety,
    Tool,
    ToolContext,
    ToolEffectClass,
    ToolInput,
    ToolOutput,
    ToolResult,
)

__all__ = [
    "INLINE_OUTPUT_BUDGET_BYTES",
    "RunPythonInput",
    "RunPythonOutput",
    "RunPythonTool",
    "build_run_python_tools",
]

#: How much of each stream may travel inline in the result. Past this the whole stream is written
#: to a file and the result names the path. 16 KB is about four pages of text: enough that an
#: ordinary "print what you found" script never spills, small enough that a runaway loop cannot
#: fill the turn's context with its own output.
INLINE_OUTPUT_BUDGET_BYTES: Final = 16 * 1024
#: Where a spilled stream lands. ``reads/`` is the thread's read-only-to-the-container folder, so
#: the next script cannot overwrite the output of the last one, and the agent's own file tools can
#: open it by the exact relative path the result reports.


class RunPythonInput(ToolInput):
    #: The whole script, as source. It runs with no network and no arguments; anything it needs
    #: it reads from the workspace, and anything it produces it prints or writes to a file.
    code: str = Field(min_length=1, max_length=65_536)
    #: Ask for *less* wall-clock time than the operator allows — useful for a probe you expect to
    #: be instant. It is clamped to the operator's ceiling, so it can never buy more.
    timeout_s: float | None = Field(default=None, gt=0)
    #: One line saying what this run is for, carried into the journal beside the code.
    note: str | None = Field(default=None, max_length=200)


class RunPythonOutput(ToolOutput):
    #: The script's exit status; ``None`` exactly when the run timed out.
    exit_code: int | None
    timed_out: bool
    duration_ms: int
    #: The script's stdout, up to :data:`INLINE_OUTPUT_BUDGET_BYTES`.
    stdout: str
    #: Workspace-relative path of the whole stdout when it was larger than the inline budget.
    stdout_spilled_to: str | None
    #: The container's own output cap cut this stream before the tool ever saw the end of it.
    stdout_truncated: bool
    stderr: str
    stderr_spilled_to: str | None
    stderr_truncated: bool
    #: ``{"path": …, "size": …}`` for every file this run wrote or changed and the policy kept.
    files_written: tuple[dict[str, object], ...]
    #: ``{"path": …, "reason": …}`` for everything the post-run sweep took back out.
    files_removed: tuple[dict[str, str], ...]
    #: How many runs this turn may still take.
    runs_remaining: int


def _refuse(code: str, message: str) -> PreconditionFailed:
    return PreconditionFailed([PreconditionFailure(code, message)])


def _execute(
    code: str, *, mounts: SandboxMounts, limits: SandboxLimits, timeout_s: float, label: str
) -> tuple[SandboxRun, SweepResult]:
    """The three blocking steps, in the one order that makes the sweep's answer mean anything.

    The before-picture has to be taken while nothing is running, and the sweep has to run before
    any other tool call can see the tree — so they belong on the same thread hop as the container
    itself rather than being three awaits a cancellation could land between.
    """

    before = snapshot(mounts)
    run = run_script(
        code, mounts=mounts, limits=limits, timeout_s=timeout_s, label=label, area=mounts.area
    )
    return run, sweep(mounts, before=before)


def _inline(
    raw: bytes, *, spill: Callable[[str, bytes], str] | None, name: str
) -> tuple[str, str | None]:
    """``(what travels in the result, where the whole thing was written)``.

    Decoding replaces undecodable bytes rather than raising: a script that prints a binary blob
    has made a mistake worth *reporting*, not one worth failing the turn over. The inline cut is
    measured in bytes and drops the character it lands inside, so what comes back is always text.
    """

    text = raw.decode(errors="replace")
    encoded = text.encode()
    if len(encoded) <= INLINE_OUTPUT_BUDGET_BYTES:
        return text, None
    # The whole stream lands in ``reads/`` through the workspace, inside its quota (F3 §12).
    # Mounts built by hand carry no spill; their output is then reported cut, never written raw.
    return (
        encoded[:INLINE_OUTPUT_BUDGET_BYTES].decode(errors="ignore"),
        None if spill is None else spill(name, raw),
    )


class RunPythonTool(Tool):
    """Run one short Python script in a locked-down container over this turn's workspace."""

    name = "run_python"
    version = "1"
    model_description = (
        "Run a short Python script in a locked-down container over this turn's workspace. Use it "
        "to read files that plain text tools cannot open — PDFs, Word documents, slide decks, "
        "spreadsheets — and to do arithmetic or produce a CSV, a chart or a report. "
        "The script's working directory holds the same folders your file tools use: "
        "`attachments/` (read-only) holds every file anyone has attached in this project, "
        "`project/` and `brand/` are read-only too, and `scratch/`, `work/` and `outputs/` are "
        "yours to write. Write a file if you want to keep it; print what you want to read back. "
        "There is no network, so do not try to download anything, and nothing outside those "
        "folders exists. Output longer than 16 KB is written to a file and the result tells you "
        "its path. You get a few runs per turn, and the result says how many are left, so plan "
        "the script before you call. " + tool_manual_link("run_python")
    )
    input_model: ClassVar[type[ToolInput]] = RunPythonInput
    output_model: ClassVar[type[ToolOutput]] = RunPythonOutput
    effect_class = ToolEffectClass.WRITE
    replay = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="this operation's journaled receipt",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(safe_display_fields=("code", "note", "timeout_s"))
    #: ``project`` is the spine row the execution is bound to — the same replay identity the
    #: gallery read pins, and the project whose ``attachments/`` the container can see.
    pin_requirements = ("project",)

    def __init__(self, *, settings: Settings, workspaces: SandboxWorkspaces | None) -> None:
        self._settings = settings
        self._workspaces = workspaces

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, RunPythonInput)
        settings = self._settings
        if not settings.sandbox_enabled:
            raise _refuse(
                "sandbox_unavailable",
                "the code sandbox is not enabled on this deployment (CLUE_SANDBOX_ENABLED is off)",
            )
        workspaces = self._workspaces
        if workspaces is None:
            raise _refuse(
                "sandbox_unavailable",
                "this process composed no sandbox workspace registry, so no run can be bound "
                "to a turn",
            )
        # Blocking: it talks to the Docker daemon. Same thread discipline as the run itself.
        available, reason = await asyncio.to_thread(docker_available, settings.sandbox_image)
        if not available:
            raise _refuse("sandbox_unavailable", reason)
        if ctx.execution_id is None:
            raise _refuse(
                "workspace_unavailable",
                "this call is not part of a turn, so it has no workspace to run over",
            )
        mounts = workspaces.mounts_for(ctx.execution_id)
        if mounts is None:
            raise _refuse(
                "workspace_unavailable",
                "this turn has no registered sandbox workspace; its lease is gone or was never "
                "bound",
            )
        try:
            runs_remaining = workspaces.take_run(ctx.execution_id)
        except RunBudgetExhausted as exhausted:
            raise _refuse(
                "run_budget_exhausted",
                "this turn has already used all of its sandbox runs; do the rest of the work in "
                "one script on the next turn",
            ) from exhausted

        ceiling = settings.sandbox_timeout_s
        timeout_s = ceiling if inputs.timeout_s is None else min(inputs.timeout_s, ceiling)
        limits = SandboxLimits(
            image=settings.sandbox_image,
            timeout_s=ceiling,
            cpus=settings.sandbox_cpus,
            memory_mb=settings.sandbox_memory_mb,
            max_output_bytes=settings.sandbox_max_output_bytes,
        )
        run, swept = await asyncio.to_thread(
            _execute,
            inputs.code,
            mounts=mounts,
            limits=limits,
            timeout_s=timeout_s,
            label=str(ctx.execution_id),
        )
        stdout, stdout_spilled_to = _inline(
            run.stdout, spill=mounts.spill, name=f"{ctx.operation_id}.stdout.txt"
        )
        stderr, stderr_spilled_to = _inline(
            run.stderr, spill=mounts.spill, name=f"{ctx.operation_id}.stderr.txt"
        )
        output = RunPythonOutput(
            exit_code=run.exit_code,
            timed_out=run.timed_out,
            duration_ms=run.duration_ms,
            stdout=stdout,
            stdout_spilled_to=stdout_spilled_to,
            stdout_truncated=run.stdout_truncated,
            stderr=stderr,
            stderr_spilled_to=stderr_spilled_to,
            stderr_truncated=run.stderr_truncated,
            files_written=tuple({"path": path, "size": size} for path, size in swept.kept),
            files_removed=tuple(
                {"path": path, "reason": removal} for path, removal in swept.removed
            ),
            runs_remaining=runs_remaining,
        )
        return ToolResult(tool=self.name, version=self.version, references=output.model_dump())


def build_run_python_tools(
    *, settings: Settings, workspaces: SandboxWorkspaces | None
) -> tuple[Tool, ...]:
    """The sandbox tool. Registered on every deployment, composed where turns are driven.

    ``workspaces`` is ``None`` everywhere the turn worker is not — a script has no workspace to
    run over in a process that holds no lease — and the tool then refuses ``sandbox_unavailable``
    before it reaches for a container, exactly as it does on a host with no image. Registering it
    regardless keeps the platform's write surface and its authority audit complete.
    """

    return (RunPythonTool(settings=settings, workspaces=workspaces),)
