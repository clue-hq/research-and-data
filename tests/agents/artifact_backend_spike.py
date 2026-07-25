"""Disposable artifact-backed deepagents backend used only by the C6.0 spike.

This is evidence for the framework adapter shape, not the C6.1 production implementation.  The
framework normalizes model paths to a virtual leading slash before calling a backend, so this
adapter strips exactly that slash and then applies the frozen relative-path policy.  C6.1 must
enforce relative syntax at the agent-facing tool boundary *before* framework normalization.
"""

from __future__ import annotations

import fnmatch
import hashlib
from dataclasses import dataclass, field

from deepagents.backends.protocol import (
    BackendProtocol,
    EditResult,
    FileDownloadResponse,
    FileInfo,
    FileUploadResponse,
    GlobResult,
    GrepMatch,
    GrepResult,
    LsResult,
    ReadResult,
    WriteResult,
)

from clue_agents.contracts import normalize_virtual_path


@dataclass
class InMemoryArtifactStore:
    """Content-addressed blobs plus a workspace-scoped immutable path index."""

    blobs: dict[str, bytes] = field(default_factory=dict)
    indexes: dict[tuple[str, str], str] = field(default_factory=dict)

    def put(self, *, root_id: str, path: str, content: bytes) -> str:
        digest = hashlib.sha256(content).hexdigest()
        self.blobs[digest] = content
        self.indexes[(root_id, path)] = digest
        return digest

    def get(self, *, root_id: str, path: str) -> bytes | None:
        digest = self.indexes.get((root_id, path))
        return None if digest is None else self.blobs[digest]

    def paths(self, *, root_id: str) -> tuple[str, ...]:
        return tuple(sorted(path for scope, path in self.indexes if scope == root_id))


class ArtifactBackedDeepagentsSpikeBackend(BackendProtocol):
    """Minimal no-host-filesystem backend compatible with deepagents 0.6.12."""

    virtual_mode = True
    allowed_extensions = frozenset({".json", ".md", ".txt", ".yaml"})
    readable_prefixes = (".deepagent", "context", "inputs", "work", "outputs")
    writable_prefixes = ("work", "outputs")

    def __init__(self, store: InMemoryArtifactStore, *, root_id: str) -> None:
        self.store = store
        self.root_id = root_id

    @staticmethod
    def _logical(framework_path: str, *, allow_root: bool = False) -> str:
        # Deepagents' FilesystemMiddleware converts both relative and virtual-absolute input to one
        # leading-slash form.  It never passes a host path.  Strip only that compatibility marker.
        value = framework_path[1:] if framework_path.startswith("/") else framework_path
        if allow_root and value in {"", "."}:
            return ""
        return normalize_virtual_path(value)

    @staticmethod
    def _under(path: str, prefixes: tuple[str, ...]) -> bool:
        return any(path == prefix or path.startswith(f"{prefix}/") for prefix in prefixes)

    def _read_path(self, framework_path: str) -> tuple[str | None, str | None]:
        try:
            path = self._logical(framework_path)
        except ValueError as exc:
            return None, f"invalid_path: {exc}"
        if not self._under(path, self.readable_prefixes):
            return None, "permission_denied: path is outside readable prefixes"
        return path, None

    def _write_path(self, framework_path: str) -> tuple[str | None, str | None]:
        path, error = self._read_path(framework_path)
        if error or path is None:
            return None, error
        if not self._under(path, self.writable_prefixes):
            return None, "permission_denied: path is outside writable prefixes"
        suffix = "." + path.rsplit(".", maxsplit=1)[-1].lower() if "." in path else ""
        if suffix not in self.allowed_extensions:
            return None, "permission_denied: file type is not allowed"
        return path, None

    def ls(self, path: str) -> LsResult:
        try:
            prefix = self._logical(path, allow_root=True)
        except ValueError as exc:
            return LsResult(error=f"invalid_path: {exc}")
        if prefix and not self._under(prefix, self.readable_prefixes):
            return LsResult(error="permission_denied: path is outside readable prefixes")
        entries: list[FileInfo] = []
        for item in self.store.paths(root_id=self.root_id):
            if prefix and item != prefix and not item.startswith(f"{prefix}/"):
                continue
            content = self.store.get(root_id=self.root_id, path=item)
            entries.append({"path": item, "is_dir": False, "size": len(content or b"")})
        return LsResult(entries=entries)

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        path, error = self._read_path(file_path)
        if error or path is None:
            return ReadResult(error=error)
        content = self.store.get(root_id=self.root_id, path=path)
        if content is None:
            return ReadResult(error="file_not_found")
        lines = content.decode("utf-8").splitlines(keepends=True)
        selected = "".join(lines[offset : offset + limit])
        return ReadResult(file_data={"content": selected, "encoding": "utf-8"})

    def write(self, file_path: str, content: str) -> WriteResult:
        path, error = self._write_path(file_path)
        if error or path is None:
            return WriteResult(error=error)
        if self.store.get(root_id=self.root_id, path=path) is not None:
            return WriteResult(error="file_exists")
        self.store.put(root_id=self.root_id, path=path, content=content.encode())
        return WriteResult(path=path)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        path, error = self._write_path(file_path)
        if error or path is None:
            return EditResult(error=error)
        content_bytes = self.store.get(root_id=self.root_id, path=path)
        if content_bytes is None:
            return EditResult(error="file_not_found")
        content = content_bytes.decode()
        occurrences = content.count(old_string)
        if occurrences == 0:
            return EditResult(error="old_string_not_found")
        if not replace_all and occurrences != 1:
            return EditResult(error="old_string_not_unique")
        updated = content.replace(old_string, new_string, -1 if replace_all else 1)
        self.store.put(root_id=self.root_id, path=path, content=updated.encode())
        return EditResult(path=path, occurrences=occurrences if replace_all else 1)

    def glob(self, pattern: str, path: str | None = None) -> GlobResult:
        try:
            prefix = self._logical(path or "", allow_root=True)
        except ValueError as exc:
            return GlobResult(error=f"invalid_path: {exc}")
        matches: list[FileInfo] = []
        for item in self.store.paths(root_id=self.root_id):
            if prefix and not item.startswith(f"{prefix}/"):
                continue
            relative = item.removeprefix(f"{prefix}/") if prefix else item
            if fnmatch.fnmatch(relative, pattern):
                content = self.store.get(root_id=self.root_id, path=item)
                matches.append({"path": item, "is_dir": False, "size": len(content or b"")})
        return GlobResult(matches=matches)

    def grep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> GrepResult:
        candidates = self.glob(glob or "**", path)
        if candidates.error:
            return GrepResult(error=candidates.error)
        matches: list[GrepMatch] = []
        for entry in candidates.matches or []:
            item = entry["path"]
            content = self.store.get(root_id=self.root_id, path=item)
            for number, line in enumerate((content or b"").decode().splitlines(), start=1):
                if pattern in line:
                    matches.append({"path": item, "line": number, "text": line})
        return GrepResult(matches=matches)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        responses: list[FileUploadResponse] = []
        for path, content in files:
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                responses.append(FileUploadResponse(path=path, error="invalid_encoding"))
                continue
            result = self.write(path, text)
            responses.append(FileUploadResponse(path=path, error=result.error))
        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        responses: list[FileDownloadResponse] = []
        for requested in paths:
            path, error = self._read_path(requested)
            content = None if path is None else self.store.get(root_id=self.root_id, path=path)
            responses.append(
                FileDownloadResponse(
                    path=requested,
                    content=content,
                    error=error or (None if content is not None else "file_not_found"),
                )
            )
        return responses
