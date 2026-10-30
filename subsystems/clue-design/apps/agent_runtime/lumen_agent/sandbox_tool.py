"""``run_python`` for the design agents (spec 2026-10-30 §3.5).

The ad, site and web agents run a short script in the same locked-down container the Head of ABM
uses (``clue_agents.sandbox``: no network, read-only root, capabilities dropped, a post-run sweep).
The container sees exactly two folders of the agent's workspace: ``attachments/`` (the files sent
in this chat) read-only, so a person's file is never changed, and ``outputs/`` to write. Nothing
else of the workspace is mounted.

Off — no tool at all — when ``CLUE_SANDBOX_ENABLED`` is false or Docker cannot run the sandbox
image on this host. The tool description is founder-approved wording (2026-10-30).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from py_lumen_obs import get_logger

from clue_agents.contracts import WorkspacePolicy
from clue_agents.sandbox.docker_runner import SandboxLimits, docker_available, run_script
from clue_agents.sandbox.policy_sweep import snapshot, sweep
from clue_agents.sandbox.workspaces import SandboxMounts
from clue_agents.worker_area import process_area_name

from .session_sync import MAX_FILE_BYTES

__all__ = [
    "design_run_python",
    "OUTPUTS_DIR",
    "OUTPUTS_MAX_BYTES",
    "RUN_PYTHON_DESCRIPTION",
    "build_design_run_python_tool",
    "design_sandbox_mounts",
]

logger = get_logger("lumen_agent.sandbox_tool")

OUTPUTS_DIR = "outputs"
#: What one design workspace's ``outputs/`` may hold, in all.
OUTPUTS_MAX_BYTES = 50 * 1024 * 1024
#: What a run's printed output may put back into the conversation; the rest is cut, with a note.
_INLINE_OUTPUT_BYTES = 16 * 1024

RUN_PYTHON_DESCRIPTION = (
    "Run a short Python script in a locked-down container. Use it to open files your other "
    "tools cannot read (PDFs, Word documents, slide decks, spreadsheets), to pull out their "
    "text and tables, do arithmetic, or turn a page of a PDF or deck into an image in "
    "`outputs/`. The script sees two folders. `attachments/` holds the files sent in this chat; "
    "it is read-only, so you can read and copy them but never change them. `outputs/` is yours "
    "to write. Write what you want to keep to `outputs/`; print what you want to read back. "
    "Nothing else from your workspace is there, and there is no network. You get a few runs per "
    "request, and the result says how many are left, so plan the script before you call."
)


def design_sandbox_mounts(workspace: Path) -> SandboxMounts:
    """The two folders a design agent's script sees, created if absent."""

    attachments = workspace / "attachments"
    outputs = workspace / OUTPUTS_DIR
    attachments.mkdir(parents=True, exist_ok=True)
    outputs.mkdir(parents=True, exist_ok=True)
    return SandboxMounts(
        thread_root=workspace,
        read_only={"attachments": attachments},
        read_write={OUTPUTS_DIR: outputs},
        policy=WorkspacePolicy(
            max_total_bytes=OUTPUTS_MAX_BYTES,
            # Review M-3: no file larger than a session snapshot carries, so nothing the agent
            # keeps lives only on one worker's disk (AW-8).
            max_file_bytes=MAX_FILE_BYTES,
            max_file_count=200,
            # The sweep adds the sandbox's own outputs (CSV, XLSX, DOCX, PPTX, PDF, PNG).
            allowed_extensions=(".md", ".txt", ".json", ".jpg", ".jpeg", ".webp"),
            readable_prefixes=("attachments", OUTPUTS_DIR),
            writable_prefixes=(OUTPUTS_DIR,),
            retention_class="design-run",
        ),
    )


def _inline(raw: bytes) -> str:
    text = raw.decode(errors="replace")
    encoded = text.encode()
    if len(encoded) <= _INLINE_OUTPUT_BYTES:
        return text
    cut = encoded[:_INLINE_OUTPUT_BYTES].decode(errors="ignore")
    return cut + "\n[output cut here; write long output to a file in outputs/ instead]"


def build_design_run_python_tool(
    *, workspace: Path, run_id: str, settings: Any = None
) -> Any | None:
    """The ``run_python`` tool over ``workspace``, or ``None`` when the sandbox cannot run here."""

    from langchain_core.tools import StructuredTool

    if settings is None:
        from clue_config import load_settings

        settings = load_settings()
    if not settings.sandbox_enabled:
        return None
    available, reason = docker_available(settings.sandbox_image)
    if not available:
        logger.info("design_run_python_unavailable", reason=reason)
        return None
    limits = SandboxLimits(
        image=settings.sandbox_image,
        timeout_s=settings.sandbox_timeout_s,
        cpus=settings.sandbox_cpus,
        memory_mb=settings.sandbox_memory_mb,
        max_output_bytes=settings.sandbox_max_output_bytes,
    )
    budget = {"left": int(settings.sandbox_max_runs_per_turn)}
    lock = threading.Lock()

    def run_python(code: str) -> str:
        with lock:
            if budget["left"] <= 0:
                return json.dumps(
                    {
                        "error": "run_budget_exhausted",
                        "message": "This request has used all of its runs.",
                    }
                )
            budget["left"] -= 1
            remaining = budget["left"]
        mounts = design_sandbox_mounts(workspace)
        before = snapshot(mounts)
        run = run_script(
            code,
            mounts=mounts,
            limits=limits,
            timeout_s=limits.timeout_s,
            label=run_id,
            # Review M-2: the worker area's label, so a container a dead worker left running is
            # killed by the next process of this area, as the Head of ABM's are.
            area=process_area_name(),
        )
        swept = sweep(mounts, before=before)
        return json.dumps(
            {
                "exit_code": run.exit_code,
                "timed_out": run.timed_out,
                "stdout": _inline(run.stdout),
                "stderr": _inline(run.stderr),
                "files_written": [{"path": path, "size": size} for path, size in swept.kept],
                "files_removed": [
                    {"path": path, "reason": reason} for path, reason in swept.removed
                ],
                "runs_remaining": remaining,
            },
            ensure_ascii=False,
        )

    return StructuredTool.from_function(
        run_python, name="run_python", description=RUN_PYTHON_DESCRIPTION
    )


def design_run_python(tools: Any, workspace: Path, platform_reads: Any) -> Any | None:
    """The tool for one design request: only on a leg turn (the chat's files arrive only there),
    and only when the sandbox can run. Records whether the agent has it, so the turn's file list
    can say when documents cannot be opened."""

    tool = None
    if platform_reads is not None:
        try:
            tool = build_design_run_python_tool(
                workspace=workspace, run_id=str(getattr(tools, "run_id", None) or workspace.name)
            )
        except Exception:  # noqa: BLE001 - a sandbox that cannot be composed is no tool, not a crash
            logger.warning("design_run_python_failed", exc_info=True)
            tool = None
    tools.run_python_available = tool is not None
    return tool
