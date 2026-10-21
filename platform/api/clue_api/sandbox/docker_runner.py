"""The container a sandboxed script actually runs in, and the argv that locks it down.

This module is the whole boundary between the agent's Python and the host: it builds one
``docker run`` argv, feeds the script to it on stdin, and hands back what came out. It knows
nothing about tools, turns or the claim store, so the flags below are readable as one list and
every one of them can be argued for on its own line.

The shape is deliberately blunt. There is no network (``--network none``), no writable root
(``--read-only`` plus one ``noexec`` tmpfs for ``/tmp``), no capabilities (``--cap-drop ALL``,
``--security-opt no-new-privileges``), the worker's non-root UID/GID, and a
fork bomb hits ``--pids-limit`` before it hits the host. The *only* host state the container can
reach is the mounts :class:`~clue_api.sandbox.workspaces.SandboxMounts` names, and the only
environment it gets is two variables that keep Python and matplotlib from writing where they
must not — no ``CLUE_*``, no provider keys, nothing inherited from the serving process (the
``env=`` handed to :func:`subprocess.run` replaces the parent environment rather than extending
it, so a key cannot leak by being present on the box).

Everything here blocks. :func:`run_script` is a synchronous ``subprocess.run``; the caller
(the ``run_python@1`` tool) is responsible for putting it on a thread so the event loop keeps
serving while a script runs.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Final

from clue_api.sandbox.workspaces import SandboxMounts

__all__ = [
    "SandboxLimits",
    "SandboxRun",
    "build_command",
    "kill_area_containers",
    "docker_available",
    "run_script",
]

#: Where every mount lands inside the container; the script's working directory, so a relative
#: ``scratch/notes.md`` in agent code means the same path it means in the model's file tools.
_CONTAINER_WORKSPACE: Final = "/workspace"
#: Label key the timeout path kills by. A run that overran has already outlived its ``docker run``
#: client, so the container is found by label rather than by a pid we no longer have.
_LABEL_KEY: Final = "clue.execution"
#: Label key naming the worker area that started a container (F3, AW-19): a worker that starts
#: kills every container still carrying its own area, left by a run it was in when it died.
_AREA_LABEL_KEY: Final = "clue.worker-area"
#: Docker label values are free-form; ours are derived from ids, so anything outside this class is
#: dropped rather than quoted — an id that needed quoting is an id we should not be running under.
_LABEL_ALLOWED: Final = re.compile(r"[^A-Za-z0-9_.-]")
#: Short fuse on the *management* calls (`image inspect`, `ps`, `kill`). These talk to the daemon,
#: not to the script, so if they do not answer promptly the daemon is the problem.
_DAEMON_TIMEOUT_S: Final = 10.0


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    """The per-run ceilings an operator sets; every one of them becomes a ``docker run`` flag."""

    #: The sandbox image tag. Built by ``make sandbox-image``; never pulled at run time.
    image: str
    #: The default wall-clock ceiling. ``run_script`` takes its own ``timeout_s`` so a caller can
    #: shorten a single run, but never lengthens it beyond what the tool decides.
    timeout_s: float
    cpus: float
    memory_mb: int
    #: Per-stream byte cap. Output past it is cut and flagged, never buffered whole.
    max_output_bytes: int


@dataclass(frozen=True, slots=True)
class SandboxRun:
    """What one container did: its status, how long it took, and what it printed."""

    #: ``None`` exactly when the run timed out — there is no exit status to report.
    exit_code: int | None
    timed_out: bool
    duration_ms: int
    stdout: bytes
    stderr: bytes
    stdout_truncated: bool
    stderr_truncated: bool


def _sanitise_label(label: str) -> str:
    return _LABEL_ALLOWED.sub("", label)


def _worker_user() -> str:
    """Bind-mounted private files must have the same owner inside and outside Docker."""

    uid, gid = os.getuid(), os.getgid()
    if uid == 0:
        raise PermissionError("Run the fleet worker as a non-root user to use the code sandbox.")
    return f"{uid}:{gid}"


def build_command(
    mounts: SandboxMounts,
    limits: SandboxLimits,
    *,
    label: str | None = None,
    area: str | None = None,
) -> list[str]:
    """The exact ``docker run`` argv for one script.

    Mounts are emitted read-only first, each group sorted by name, so the argv is a pure function
    of its inputs and worker identity — two runs of the same turn produce identical commands, making
    the command itself something a reviewer or a log line can be compared against.
    """

    label_flags: list[str] = []
    if label is not None:
        label_flags = ["--label", f"{_LABEL_KEY}={_sanitise_label(label)}"]
    if area is not None:
        label_flags += ["--label", f"{_AREA_LABEL_KEY}={_sanitise_label(area)}"]
    mount_flags: list[str] = []
    for name, host_path in sorted(mounts.read_only.items()):
        mount_flags += ["-v", f"{host_path}:{_CONTAINER_WORKSPACE}/{name}:ro"]
    for name, host_path in sorted(mounts.read_write.items()):
        mount_flags += ["-v", f"{host_path}:{_CONTAINER_WORKSPACE}/{name}:rw"]
    return [
        "docker",
        "run",
        "--rm",
        "-i",
        "--network",
        "none",
        "--cpus",
        str(limits.cpus),
        "--memory",
        f"{limits.memory_mb}m",
        "--pids-limit",
        "256",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=256m",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        _worker_user(),
        "--workdir",
        _CONTAINER_WORKSPACE,
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--env",
        "MPLCONFIGDIR=/tmp",
        *label_flags,
        *mount_flags,
        limits.image,
        # Fixed startup only: agent code stays on stdin, never interpolated into the shell.
        # Set the mask in the child, not the multithreaded worker (umask is process-wide).
        "sh",
        "-c",
        "umask 077; exec python -I -",
    ]


def docker_available(image: str) -> tuple[bool, str]:
    """Whether this host can run the sandbox at all, and — when it cannot — what to do about it.

    Both failure modes name their own fix, because they have different owners: a missing image is
    the operator's one-command build, while an unreachable daemon is the box. Neither is allowed
    to hang: the inspect call talks to the daemon, so a daemon that is down must fail fast rather
    than stall the turn that asked.
    """

    try:
        _worker_user()
    except PermissionError as exc:
        return False, str(exc)
    if shutil.which("docker") is None:
        return False, "Docker is not installed on this host."
    try:
        completed = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
            timeout=_DAEMON_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return False, "Docker is not reachable: `docker image inspect` did not answer."
    except OSError as exc:  # the binary exists but cannot be executed
        return False, f"Docker is not reachable: {exc}."
    if completed.returncode == 0:
        return True, ""
    return (
        False,
        f"The sandbox image `{image}` is not built on this host; run `make sandbox-image`.",
    )


def kill_area_containers(area: str) -> int:
    """Kill every container a run of this worker area left behind; return how many were found.

    Called once when a worker starts, right after it claims its area: nothing of its own can be
    running yet, so whatever still carries the area's label belongs to a run its previous process
    was in when it died. Best effort, like ``_kill_by_label``.
    """

    try:
        listed = subprocess.run(
            ["docker", "ps", "-q", "--filter", f"label={_AREA_LABEL_KEY}={_sanitise_label(area)}"],
            capture_output=True,
            timeout=_DAEMON_TIMEOUT_S,
        )
        container_ids = listed.stdout.decode(errors="replace").split()
        if container_ids:
            subprocess.run(
                ["docker", "kill", *container_ids],
                capture_output=True,
                timeout=_DAEMON_TIMEOUT_S,
            )
    except (OSError, subprocess.SubprocessError):
        return 0
    return len(container_ids)


def _kill_by_label(label: str) -> None:
    """Kill whatever survived the timeout, best effort.

    ``subprocess.run``'s timeout kills the *client*; the container it started keeps running with
    nothing attached to it. It is labelled, so it can still be found. Every failure here is
    swallowed: the run already has its verdict, and a cleanup that cannot reach the daemon must
    not turn a reported timeout into an exception.
    """

    try:
        listed = subprocess.run(
            ["docker", "ps", "-q", "--filter", f"label={_LABEL_KEY}={label}"],
            capture_output=True,
            timeout=_DAEMON_TIMEOUT_S,
        )
        container_ids = listed.stdout.decode(errors="replace").split()
        if container_ids:
            subprocess.run(
                ["docker", "kill", *container_ids],
                capture_output=True,
                timeout=_DAEMON_TIMEOUT_S,
            )
    except (OSError, subprocess.SubprocessError):
        return


def _cut(raw: bytes | None, limit: int) -> tuple[bytes, bool]:
    data = raw or b""
    if len(data) <= limit:
        return data, False
    return data[:limit], True


def run_script(
    code: str,
    *,
    mounts: SandboxMounts,
    limits: SandboxLimits,
    timeout_s: float,
    label: str | None = None,
    area: str | None = None,
) -> SandboxRun:
    """Run one script in one container and return what it did. **Blocking** — call it in a thread.

    The script goes in on stdin rather than into a file the container mounts: nothing is written
    to the workspace that the script did not write itself, and there is no temp file to clean up
    on the timeout path.

    A timeout is a result, not an error. The container is killed by label, whatever the process
    managed to print before it was cut off is kept, and ``exit_code`` is ``None`` because there
    never was one.
    """

    for host_path in mounts.read_write.values():
        # A lease creates all six thread folders, but a caller may hand us mounts for a tree that
        # has not been opened yet; a missing rw path would otherwise be created by the daemon as
        # root-owned.
        host_path.mkdir(parents=True, exist_ok=True, mode=0o700)
    command = build_command(mounts, limits, label=label, area=area)
    # Resolve with the worker's installation path before removing its environment.
    # Docker Desktop/Homebrew may live outside the restricted child PATH.
    command[0] = shutil.which(command[0]) or command[0]
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            input=code.encode(),
            capture_output=True,
            timeout=timeout_s,
            env={"PATH": "/usr/bin:/bin:/usr/local/bin"},
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        if label is not None:
            _kill_by_label(_sanitise_label(label))
        stdout, stdout_truncated = _cut(_as_bytes(exc.stdout), limits.max_output_bytes)
        stderr, stderr_truncated = _cut(_as_bytes(exc.stderr), limits.max_output_bytes)
        return SandboxRun(
            exit_code=None,
            timed_out=True,
            duration_ms=duration_ms,
            stdout=stdout,
            stderr=stderr,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
        )
    duration_ms = int((time.monotonic() - started) * 1000)
    stdout, stdout_truncated = _cut(completed.stdout, limits.max_output_bytes)
    stderr, stderr_truncated = _cut(completed.stderr, limits.max_output_bytes)
    return SandboxRun(
        exit_code=completed.returncode,
        timed_out=False,
        duration_ms=duration_ms,
        stdout=stdout,
        stderr=stderr,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
    )


def _as_bytes(partial: bytes | str | None) -> bytes | None:
    """``TimeoutExpired`` carries whatever the stream was reading — typed ``Any``, possibly text."""

    if isinstance(partial, str):
        return partial.encode(errors="replace")
    return partial
