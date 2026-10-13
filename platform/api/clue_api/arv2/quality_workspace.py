"""Disposable virtual evidence mount; canonical bytes and authorization remain in storage/DB.

Paths name complete JSON views of an original, with optional character offsets.
No source bytes are cached on a worker. Every framework read rechecks the same evidence grant as
the named tools, including after a prior successful read, replay, revocation or privacy erasure.
"""

from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Any

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
from deepagents.backends.utils import MAX_LINE_LENGTH, slice_read_response
from deepagents.middleware.filesystem import DEFAULT_READ_LIMIT

from clue_api.arv2.evidence_paths import INDEX_PATH, SOURCE_PATH
from clue_api.arv2.quality_evidence import (
    EvidenceGrant,
    EvidenceUnavailable,
    list_sources,
    read_source,
    resolve_source,
)
from clue_api.arv2.quality_recipe import RECIPE_26
from clue_db import ConnFactory
from clue_storage import StorageBackend, StorageError

_READ_ONLY = "permission_denied: evidence originals are read-only"
_ASYNC = "Use the asynchronous research runtime for authorized evidence access."


#: Deep Agents cuts any read over 80,000 characters (its 20,000-token limit, which
#: ``create_deep_agent`` does not let us change), counted after it adds a line-number column,
#: and points at a shell tool research agents do not have. A whole-file read therefore comes
#: back in parts that stay well under that limit, each ending with the offset to read next.
READ_PART_CHARS = 64_000
#: Deep Agents' line-number column (``%6d`` and a tab), plus margin, per line or line chunk.
_GUTTER_CHARS = 8
CONTINUES = "\n[This file continues. Read it again with offset={offset} to see the rest.]"


def _window(rendered: str, *, offset: int, limit: int) -> ReadResult:
    """Return the file from ``offset``: whole by default, in parts when it is very long.

    Deep Agents fills an omitted line limit with its own default (``DEFAULT_READ_LIMIT``, 100 in
    0.6.12; 2000 in older releases). Treat that framework default, the old one, and nonpositive
    limits as "the rest of the file" for these research views. A model that explicitly asks for
    exactly the default window gets the same; the two calls are indistinguishable here. An
    explicit window is returned as asked. A single line longer than a part cannot be split by
    line offset and is returned as it is.
    """
    lines = rendered.splitlines(keepends=True)
    more_at: int | None = None
    if limit <= 0 or limit in (DEFAULT_READ_LIMIT, 2000):
        end, used = offset, 0
        while end < len(lines):
            cost = len(lines[end]) + _GUTTER_CHARS * (1 + len(lines[end]) // MAX_LINE_LENGTH)
            if used + cost > READ_PART_CHARS and end > offset:
                break
            used += cost
            end += 1
        limit = max(1, end - offset)
        more_at = end if end < len(lines) else None
    sliced = slice_read_response({"content": rendered, "encoding": "utf-8"}, offset, limit)
    if isinstance(sliced, ReadResult):
        return sliced
    if more_at is not None:
        sliced = sliced.removesuffix("\n") + CONTINUES.format(offset=more_at)
    return ReadResult(file_data={"content": sliced, "encoding": "utf-8"})


def render_view(value: Any, *, offset: int, limit: int) -> ReadResult:
    """A research view as JSON, read by the rules of ``_window``."""
    rendered = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    return _window(rendered, offset=offset, limit=limit)


def render_text(header: str, body: str, *, offset: int, limit: int) -> ReadResult:
    """A research view as plain text: header line(s), then the document exactly as stored.

    Recipe 26+. Read by the rules of ``_window``.
    """
    return _window(f"{header}\n{body}", offset=offset, limit=limit)


def plain_source(source: dict[str, Any]) -> tuple[str, str]:
    """An evidence source as ``key: value`` header lines plus its unsegmented text."""
    fields = {k: v for k, v in source.items() if k not in {"text", "metadata", "next_path"}}
    fields.update({k: v for k, v in (source.get("metadata") or {}).items() if k not in fields})
    lines = [f"# {fields.pop('path', '/evidence')}"]
    lines += [
        f"{key}: {value}"
        for key, value in fields.items()
        if value is not None and not isinstance(value, (dict, list))
    ]
    return "\n".join(lines), str(source.get("text") or "")


class EvidenceWorkspace(BackendProtocol):
    """Mount at /evidence on an isolated governed workspace; provides no shell or host paths."""

    def __init__(
        self,
        conn_factory: ConnFactory,
        storage: StorageBackend,
        grant: EvidenceGrant,
        *,
        recipe: int = 0,
    ):
        self._connections = conn_factory
        self._storage = storage
        self._grant = grant
        # Recipe 26+: sources are served as plain text (see quality_recipe.py).
        self._recipe = recipe

    async def aread(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        if offset < 0:
            return ReadResult(error="Read offset must be nonnegative.")
        try:
            async with self._connections() as conn:
                if file_path == INDEX_PATH:
                    result = await list_sources(conn, self._grant, after=0, limit=0)
                    result["next_path"] = None
                elif SOURCE_PATH.fullmatch(file_path):
                    ref = await resolve_source(conn, self._grant, file_path)
                    result = await read_source(conn, self._storage, self._grant, ref.source_id)
                    result["next_path"] = None
                    if self._recipe >= RECIPE_26:
                        header, body = plain_source(result)
                        return render_text(header, body, offset=offset, limit=limit)
                    # Segment long lines without changing the original bytes.
                    body = result.pop("text")
                    result["text_segments"] = [
                        {"start": i, "text": body[i : i + 256]} for i in range(0, len(body), 256)
                    ]
                else:
                    return ReadResult(
                        error=f"Unknown evidence path; read {INDEX_PATH} or ls /evidence."
                    )
            return render_view(result, offset=offset, limit=limit)
        except EvidenceUnavailable as exc:
            return ReadResult(error=str(exc))
        except StorageError:
            return ReadResult(
                error="Source bytes are unavailable or erased. Inspect "
                f"{INDEX_PATH}; report the listed path rather than guessing another name."
            )

    async def als(self, path: str) -> LsResult:
        if path.rstrip("/") != "/evidence":
            return LsResult(
                error=f"Evidence files live directly under /evidence; read {INDEX_PATH}."
            )
        try:
            async with self._connections() as conn:
                page = await list_sources(conn, self._grant, after=0, limit=0)
            return LsResult(
                entries=[
                    FileInfo(path=INDEX_PATH, is_dir=False),
                    *[
                        FileInfo(path=row["path"], is_dir=False, size=row["byte_size"])
                        for row in page["sources"]
                        if row.get("available")
                    ],
                ]
            )
        except (EvidenceUnavailable, StorageError):
            return LsResult(error="Evidence authority unavailable; request an authorized task.")

    async def aglob(self, pattern: str, path: str | None = None) -> GlobResult:
        listing = await self.als(path or "/evidence")
        if listing.error:
            return GlobResult(error=listing.error)
        if not pattern or ".." in PurePosixPath(pattern).parts:
            return GlobResult(
                error="Use a file-name pattern such as *hiring*.json under /evidence."
            )
        return GlobResult(
            matches=[
                row for row in listing.entries or [] if PurePosixPath(row["path"]).match(pattern)
            ]
        )

    async def agrep(
        self, pattern: str, path: str | None = None, glob: str | None = None
    ) -> GrepResult:
        return GrepResult(
            error="Use search_evidence with the readable source path and a literal query."
        )

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
