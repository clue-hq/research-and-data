"""Repo-root-confined filesystem backend for the deepagent (RIDER 1).

deepagents 0.6.12 `FilesystemBackend(root_dir=..., virtual_mode=False)` gives the
model direct filesystem access: absolute paths (`/etc/passwd`) bypass `root_dir`
entirely and relative `..` segments can climb out of it (the backend's own
docstring warns of exactly this). We cannot flip `virtual_mode=True` to close the
hole, because our prompts hand the model HOST-ABSOLUTE paths under the repo
(`/…/clue-design/havana/apps/agent_runtime/knowledge_docs/…` and the run
workspace) — under virtual mode those absolute paths are re-anchored onto
`root_dir` as virtual paths (`_resolve_path` does `(cwd / vpath.lstrip("/"))`),
so every real path 404s and the loop breaks.

The minimal robust guard: keep the non-virtual legacy resolution (absolute paths
as-is, relative under `root_dir`, symlink-loop detection) untouched, then add ONE
containment check — the resolved real path must live inside `root_dir`. An escape
is reported to the model as a clear error STRING (never an uncaught exception that
crashes the run): the parent methods (`read`/`write`/`edit`/`ls`/`grep`/`glob`)
already wrap `_resolve_path` in `except (OSError, RuntimeError)`, so raising an
`OSError` there lands as a normal `*Result(error=...)`. `upload_files` /
`download_files` classify by exception type, so we translate the escape into their
response objects explicitly.

Everything else — the read-only `knowledge_docs` write-deny, workspace read/write,
the whole tool surface — is unchanged; this class only narrows WHICH paths the
existing behaviors are allowed to touch.
"""

from __future__ import annotations

from pathlib import Path

from deepagents.backends.filesystem import FilesystemBackend
from deepagents.backends.protocol import (
    INVALID_PATH,
    FileDownloadResponse,
    FileUploadResponse,
)


class RepoRootedFilesystemBackend(FilesystemBackend):
    """`FilesystemBackend` that rejects any path resolving outside `root_dir`.

    Constructed with `virtual_mode=False` so the model keeps using the real
    host-absolute paths our prompts give it; the escape hole that mode leaves
    open is closed by a post-resolution containment check.
    """

    def __init__(self, root_dir: str | Path, max_file_size_mb: int = 10) -> None:
        super().__init__(
            root_dir=root_dir, virtual_mode=False, max_file_size_mb=max_file_size_mb
        )

    def _escape_message(self, key: str) -> str:
        return (
            f"Path '{key}' is outside the permitted repository root "
            f"({self.cwd}) and was rejected. Use an absolute path under the "
            f"run workspace or the repo, and never '..' segments that climb "
            f"above the root."
        )

    def _resolve_path(self, key: str) -> Path:
        """Resolve exactly as the parent does (absolute as-is, relative under
        root, symlink-loop detection preserved), then reject any result whose
        real location escapes `root_dir`.

        Containment is checked against the fully-resolved real path so that a
        symlink pointing outside the root, or an absolute/`..` path, can't slip
        through. Raises `OSError` on escape — the parent file methods catch that
        and surface it to the model as a clean error string.
        """
        resolved = super()._resolve_path(key)
        try:
            resolved.resolve().relative_to(self.cwd)
        except ValueError:
            raise OSError(self._escape_message(key)) from None
        return resolved

    def upload_files(self, files):  # type: ignore[override]
        """Reject out-of-root uploads with an INVALID_PATH response instead of
        letting the escape raise (this method classifies by exception type and
        re-raises unrecognized ones, so the guard is applied explicitly here)."""
        responses = []
        allowed: list[tuple[str, bytes]] = []
        placeholders: dict[int, FileUploadResponse] = {}
        for index, (path, content) in enumerate(files):
            try:
                self._resolve_path(path)
            except OSError:
                placeholders[index] = FileUploadResponse(path=path, error=INVALID_PATH)
                continue
            allowed.append((path, content))
        allowed_responses = iter(super().upload_files(allowed)) if allowed else iter(())
        for index in range(len(files)):
            responses.append(placeholders.get(index) or next(allowed_responses))
        return responses

    def download_files(self, paths):  # type: ignore[override]
        """Reject out-of-root downloads with an INVALID_PATH response instead of
        letting the escape raise."""
        responses = []
        allowed: list[str] = []
        placeholders: dict[int, FileDownloadResponse] = {}
        for index, path in enumerate(paths):
            try:
                self._resolve_path(path)
            except OSError:
                placeholders[index] = FileDownloadResponse(
                    path=path, content=None, error=INVALID_PATH
                )
                continue
            allowed.append(path)
        allowed_responses = (
            iter(super().download_files(allowed)) if allowed else iter(())
        )
        for index in range(len(paths)):
            responses.append(placeholders.get(index) or next(allowed_responses))
        return responses
