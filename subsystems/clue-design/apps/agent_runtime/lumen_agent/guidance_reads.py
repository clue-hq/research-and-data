"""Pagination visibility for explicitly selected candidate-scene guidance.

Stock read_file owns permissions, slicing, numbering and size limits. This
middleware only annotates its final response. Metadata comes from a second,
contained backend read of that same selected resource, never from repo sources.
The returned excerpt must match that snapshot; the two reads are not atomic.
No per-request data is retained and no receipt certifies comprehension.
"""

from __future__ import annotations

import asyncio
import hashlib
from io import StringIO

from deepagents.backends.utils import check_empty_content, format_content_with_line_numbers
from deepagents.middleware.filesystem import DEFAULT_READ_LIMIT, DEFAULT_READ_OFFSET
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

from .fs_backend import AgentWorkspaceBackend


class SceneGuidanceReadMiddleware(AgentMiddleware):
    """Attach source-range notices without changing the underlying file tool."""

    def __init__(self, backend: AgentWorkspaceBackend):
        super().__init__()
        self._backend = backend

    def wrap_tool_call(self, request, handler):
        return self._annotate(request.tool_call, handler(request))

    async def awrap_tool_call(self, request, handler):
        result = await handler(request)
        if request.tool_call.get("name") != "read_file":
            return result
        return await asyncio.to_thread(self._annotate, request.tool_call, result)

    @staticmethod
    def _notice(result, metadata, notice):
        return result.model_copy(
            update={
                "content": f"[Guidance read: {notice}]\n\n{result.content}",
                "additional_kwargs": {**result.additional_kwargs, "guidance_read": metadata},
            }
        )

    def _annotate(self, call, result):
        if (
            call.get("name") != "read_file"
            or not isinstance(result, ToolMessage)
            or result.status != "success"
            or not isinstance(result.content, str)
        ):
            return result
        args = call.get("args") or {}
        path = args.get("file_path")
        offset = args.get("offset", DEFAULT_READ_OFFSET)
        limit = args.get("limit", DEFAULT_READ_LIMIT)
        if (
            not isinstance(path, str)
            or type(offset) is not int
            or offset < 0
            or type(limit) is not int
            or limit <= 0
        ):
            return result
        try:
            canonical = self._backend._to_virtual_path(self._backend._resolve_path(path))
        except (OSError, RuntimeError, ValueError):
            return result
        if not canonical.endswith(".md") or not (
            canonical.startswith("/knowledge_docs/")
            or canonical.startswith("/.deepagent/skills/")
            or canonical == "/.deepagent/AGENTS.md"
        ):
            return result
        metadata = {"path": canonical, "offset": offset, "limit": limit}
        if "[Output was truncated due to size limits." in result.content:
            return self._notice(
                result,
                {**metadata, "status": "truncated"},
                (
                    "Output was size-truncated; no complete source range is certified. "
                    f"Re-read offset={offset} with a smaller limit. If one line still "
                    "truncates, report the resource-size gap."
                ),
            )
        try:
            downloaded = self._backend.download_files([path])[0]
            if downloaded.error or downloaded.content is None:
                raise ValueError("Resource metadata is unavailable")
            source = StringIO(downloaded.content.decode("utf-8"), newline=None).read()
            lines = source.splitlines(keepends=True)
            metadata.update(
                source_lines=len(lines),
                source_snapshot_sha256=hashlib.sha256(downloaded.content).hexdigest(),
            )
            if empty_warning := check_empty_content(source):
                if result.content != format_content_with_line_numbers(empty_warning, offset + 1):
                    raise ValueError("The resource became empty after the file read")
                return self._notice(
                    result,
                    {**metadata, "status": "empty"},
                    (
                        "The resource has no non-whitespace content; "
                        "no instruction body was returned."
                    ),
                )
            expected = format_content_with_line_numbers(
                "".join(lines[offset : offset + limit]),
                start_line=offset + 1,
            )
            if result.content != expected:
                raise ValueError("The returned excerpt does not match the metadata snapshot")
        except (OSError, RuntimeError, ValueError, IndexError):
            return self._notice(
                result,
                {"path": canonical, "status": "unavailable"},
                (
                    "Pagination metadata is unavailable or the resource changed during the read. "
                    "Do not infer that this is the complete resource; re-read as needed."
                ),
            )
        end = min(offset + limit, len(lines))
        eof = end == len(lines)
        whole = offset == 0 and eof
        metadata.update(
            status="range",
            start_line=offset + 1,
            end_line=end,
            reaches_eof=eof,
            whole_resource=whole,
            next_offset=None if eof else end,
        )
        notice = f"Source lines {offset + 1}–{end} of {len(lines)}. "
        if whole:
            notice += "Whole resource returned; end of resource."
        elif eof:
            notice += "End of resource; this response is a tail excerpt, not the whole resource."
        else:
            notice += f"Partial excerpt; more follows. Continue read_file with offset={end}."
        return self._notice(result, metadata, notice)
