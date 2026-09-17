"""Design-owned local run custody and scoped physical erasure.

This host can erase only its configured runtime root. A different worker host or
an unresolvable historical locator is a refusal, never a successful empty purge.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import json
import re
import shutil
import socket
from pathlib import Path

_RUN_ID = re.compile(r"run_[0-9a-f]{32}\Z")
_BINDING = "run_binding.json"
_LOCK = ".runtime-active.lock"


@contextlib.contextmanager
def bind_runtime_workspace(*, workspace_id, outer_run_id, inner_run_id, trace_dir, emit):
    """Fence physical erasure for the call's lifetime and journal its owner first."""
    path = Path(trace_dir)
    if not _RUN_ID.fullmatch(inner_run_id) or path.name != inner_run_id or path.is_symlink():
        raise RuntimeError("design_privacy.invalid_runtime_path")
    if (path / _LOCK).is_symlink() or (path / _BINDING).is_symlink():
        raise RuntimeError("design_privacy.runtime_owner_mismatch")
    binding = {
        "version": 1,
        "workspace_id": workspace_id,
        "outer_run_id": outer_run_id,
        "inner_run_id": inner_run_id,
        "trace_dir": str(path.absolute()),
        "host": socket.gethostname(),
    }
    with (path / _LOCK).open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            marker = path / _BINDING
            if marker.exists() and json.loads(marker.read_text()) != binding:
                raise RuntimeError("design_privacy.runtime_owner_mismatch")
            marker.write_text(json.dumps(binding, sort_keys=True))
            # Caller supplies the direct fenced writer, not the best-effort UI sink.
            emit("runtime_workspace_bound", binding)
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _locators(target):
    found = []
    for event in target.events:
        # Raw run_event progress payloads use event_type/data. Terminal payloads
        # put the runtime's response under result; don't walk arbitrary model data.
        if event.get("event_type") == "runtime_workspace_bound":
            data = event.get("data")
            if not isinstance(data, dict):
                raise RuntimeError("design_privacy.invalid_runtime_binding")
            found.append(data)
    result = target.result_json
    if isinstance(result, dict) and result.get("trace_dir"):
        found.append({"trace_dir": result["trace_dir"], "inner_run_id": result.get("run_id")})
    return found


def purge_runtime_workspaces(*, workspace_id, runs, roots):
    """Remove only verified run directories; active runs must finish before retry."""
    allowed = tuple(Path(root).absolute().resolve() for root in roots)
    for target in runs:
        locators = _locators(target)
        if not locators:
            # No body can be delivered by the new path before a bound receipt.
            # Older started runs lack that guarantee and require explicit recovery.
            if target.events or target.result_json:
                raise RuntimeError("design_privacy.runtime_locator_unavailable")
            continue
        removed = set()
        for locator in locators:
            path = Path(locator.get("trace_dir", "")).absolute()
            inner = locator.get("inner_run_id")
            if (
                not isinstance(inner, str)
                or not _RUN_ID.fullmatch(inner)
                or path.name != inner
                or locator.get("workspace_id", workspace_id) != workspace_id
                or locator.get("outer_run_id", target.run_id) != target.run_id
                or locator.get("host", socket.gethostname()) != socket.gethostname()
            ):
                raise RuntimeError("design_privacy.runtime_owner_mismatch")
            # Exact allowed depth excludes sibling caches and other arbitrary paths.
            resolved = path.resolve()
            if (
                not any(resolved.parent in (root, root / "scene-candidate") for root in allowed)
                or path.is_symlink()
            ):
                raise RuntimeError("design_privacy.runtime_path_outside_host")
            if path in removed or not path.exists():
                continue
            marker = path / _BINDING
            if marker.is_symlink():
                raise RuntimeError("design_privacy.runtime_owner_mismatch")
            if marker.exists():
                owner = json.loads(marker.read_text())
                if any(
                    owner.get(key) != value
                    for key, value in (
                        ("workspace_id", workspace_id),
                        ("outer_run_id", target.run_id),
                        ("inner_run_id", inner),
                        ("host", socket.gethostname()),
                    )
                ):
                    raise RuntimeError("design_privacy.runtime_owner_mismatch")
            else:
                # Legacy system-authored result locator plus its original inner ID.
                source = path / "input.json"
                if source.is_symlink() or not source.is_file():
                    raise RuntimeError("design_privacy.runtime_owner_unavailable")
                if json.loads(source.read_text()).get("run_id") != inner:
                    raise RuntimeError("design_privacy.runtime_owner_mismatch")
            lock_path = path / _LOCK
            if lock_path.is_symlink():
                raise RuntimeError("design_privacy.runtime_owner_mismatch")
            with lock_path.open("a") as lock:
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise RuntimeError("design_privacy.runtime_still_active") from None
                shutil.rmtree(path)
            removed.add(path)


def build_runtime_workspace_purger():
    """Composition seam: platform code need not know design runtime paths."""
    from py_lumen_config import settings

    root = (
        settings.lumen_agent_trace_dir
        or settings.lumen_agent_workspace_root
        or Path(__file__).resolve().parents[3] / ".deepagent-workspace"
    )

    async def purge(*, workspace_id, runs):
        await asyncio.to_thread(
            purge_runtime_workspaces, workspace_id=workspace_id, runs=runs, roots=[root]
        )

    return purge
