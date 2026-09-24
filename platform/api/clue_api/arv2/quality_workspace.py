"""Disposable virtual evidence mount; canonical bytes and authorization remain in storage/DB.

Paths name complete JSON views of an original, with optional character offsets.
No source bytes are cached on a worker. Every framework read rechecks the same evidence grant as
the named tools, including after a prior successful read, replay, revocation or privacy erasure.
"""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

from deepagents.backends.protocol import (
    BackendProtocol,
    EditResult,
    FileDownloadResponse,
    FileInfo,
    FileUploadResponse,
    GlobResult,
    GrepResult,
    LsResult,
    ReadResult,
    WriteResult,
)
from deepagents.backends.utils import slice_read_response

from clue_api.arv2.quality_evidence import (
    EvidenceGrant,
    EvidenceUnavailable,
    list_sources,
    read_source,
)
from clue_db import ConnFactory
from clue_storage import StorageBackend, StorageError

_READ_ONLY = "permission_denied: evidence originals are read-only"
_ASYNC = "Use the asynchronous research runtime for authorized evidence access."
_SOURCE = re.compile(r"/evidence/([0-9a-f-]{36})/(0|[1-9][0-9]*)\.json\Z")
_INDEX = re.compile(r"/evidence/index/(0|[1-9][0-9]*)\.json\Z")


def render_view(value: Any, *, offset: int, limit: int) -> ReadResult:
    """Return the complete view by default; explicit positive line windows remain optional.

    Deep Agents supplies 2000 when the caller omits its line limit. Treat that framework
    default, and nonpositive limits, as unbounded for these research views.
    """
    rendered = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    if limit <= 0 or limit == 2000:
        limit = max(1, len(rendered.splitlines()))
    sliced = slice_read_response({"content": rendered, "encoding": "utf-8"}, offset, limit)
    if isinstance(sliced, ReadResult):
        return sliced
    return ReadResult(file_data={"content": sliced, "encoding": "utf-8"})


class EvidenceWorkspace(BackendProtocol):
    """Mount at /evidence on an isolated governed workspace; provides no shell or host paths."""

    def __init__(self, conn_factory: ConnFactory, storage: StorageBackend, grant: EvidenceGrant):
        self._connections = conn_factory
        self._storage = storage
        self._grant = grant

    async def aread(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        if offset < 0:
            return ReadResult(error="Read offset must be nonnegative.")
        source = _SOURCE.fullmatch(file_path)
        index = _INDEX.fullmatch(file_path)
        try:
            async with self._connections() as conn:
                if index:
                    result = await list_sources(conn, self._grant, after=int(index[1]), limit=0)
                    after = result.get("next_after")
                    result["next_path"] = f"/evidence/index/{after}.json" if after else None
                    for item in result["sources"]:
                        item["path"] = f"/evidence/{item['source_id']}/0.json"
                elif source:
                    result = await read_source(
                        conn, self._storage, self._grant, UUID(source[1]), start=int(source[2])
                    )
                    after = result.get("next_start")
                    result["next_path"] = (
                        f"/evidence/{source[1]}/{after}.json" if after is not None else None
                    )
                    # Framework file tools cap individual lines. Split without changing bytes
                    # so a long report paragraph cannot be silently clipped by that formatter.
                    body = result.pop("text")
                    result["text_segments"] = [
                        {"start": result["start"] + i, "text": body[i : i + 256]}
                        for i in range(0, len(body), 256)
                    ]
                else:
                    # Do not hand arbitrary input paths to an underlying filesystem/backend.
                    return ReadResult(error="Unknown evidence path; read /evidence/index/0.json.")
            return render_view(result, offset=offset, limit=limit)
        except (EvidenceUnavailable, StorageError, ValueError):
            return ReadResult(
                error="Evidence unavailable; request a current grant from the parent."
            )

    async def als(self, path: str) -> LsResult:
        if path.rstrip("/") != "/evidence":
            return LsResult(error="List /evidence, then follow the paginated index.")
        read = await self.aread("/evidence/index/0.json")
        if read.error:
            return LsResult(error=read.error)
        return LsResult(entries=[FileInfo(path="/evidence/index/0.json", is_dir=False)])

    async def aglob(self, pattern: str, path: str | None = None) -> GlobResult:
        return GlobResult(
            error="Use /evidence/index/0.json and its continuation for scoped listing."
        )

    async def agrep(
        self, pattern: str, path: str | None = None, glob: str | None = None
    ) -> GrepResult:
        return GrepResult(error="Use search_evidence with a granted source_id and a literal query.")

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        return ReadResult(error=_ASYNC)

    def ls(self, path: str) -> LsResult:
        return LsResult(error=_ASYNC)

    def glob(self, pattern: str, path: str | None = None) -> GlobResult:
        return GlobResult(error=_ASYNC)

    def grep(self, pattern: str, path: str | None = None, glob: str | None = None) -> GrepResult:
        return GrepResult(error=_ASYNC)

    def write(self, file_path: str, content: str) -> WriteResult:
        return WriteResult(error=_READ_ONLY)

    def edit(
        self, file_path: str, old_string: str, new_string: str, replace_all: bool = False
    ) -> EditResult:
        return EditResult(error=_READ_ONLY)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        return [FileUploadResponse(path=p, error="permission_denied") for p, _ in files]

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        return [FileDownloadResponse(path=p, error="permission_denied") for p in paths]
