"""Where a chat's saved file came from, read from the rows the turn already wrote (AW-22, AW-24).

F3 Phase 2 expires a raw input's or a working file's bytes and keeps a :class:`Receipt` in their
place, so the agent is still told what the file held and how to get the same thing again. Nothing
new is journalled for it: the facts are already durable, and this is the reader that joins them to
a path.

The path says which rule answers:

``reads/<operation_id>.json``
    A governed tool's whole result, written by the runtime's spill sink. The ``execution_node``
    row for that operation names the tool and its displayed parameters; the ``agent_tool_result``
    row, when there is one, points at the result artifact whose ``references`` say how much came
    back.
``reads/<operation_id>.stdout.txt`` / ``.stderr.txt``
    One ``run_python`` output stream.
``work/conversation_history/**``
    A compaction offload. The conversation itself is never deleted (AW-26), so this one is
    rebuildable from the chat's own history.
``work/large_tool_results/<name>``
    The summariser's overflow clip of a tool result.

Anything else — and any row that is not there — answers with :data:`UNKNOWN_RECEIPT`, and so does
any lookup that raises: a receipt is a convenience, never the file, and it may never fail a save.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any, Final
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import text

from clue_agents.contracts import ArtifactRef
from clue_agents.ports import ReceiptSource
from clue_agents.workspace_snapshot import UNKNOWN_RECEIPT, Receipt
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_db import ConnFactory, transaction
from clue_obs import get_logger

__all__ = ["READ_AGAIN", "DbReceiptSource"]

log = get_logger("clue_api.agent_workspace_receipts")

#: The one sentence each receipt shows the agent once the bytes are gone, keyed by the receipt's
#: source. Task 8 of the Phase 2 plan replaces this wording with the founder-approved text; it all
#: lives here, in one mapping, so that is a single-file edit and never a hunt through branches.
READ_AGAIN: Final[Mapping[str, str]] = {
    "tool": "These bytes are gone. Call {tool} again with the same parameters ({params}) to get "
    "the same thing back.",
    "run_python": "These bytes are gone. Run the same code again with run_python to print this "
    "{stream} again.",
    "conversation_history": "These bytes are gone. This was part of this conversation's own "
    "history, which is never deleted — say what you need from it and it is rebuilt from the "
    "conversation.",
    "large_tool_results": "These bytes are gone. This was the overflow of a tool result; call "
    "that tool again to get it.",
    "unknown": "",
}

#: The ``references`` keys of a read's result that say how much came back (``RunCrmActionOutput``).
_COUNT_KEYS: Final = ("record_count", "total", "done")

_UUID: Final = r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}"
#: ``AgentWorkspaceBackend.write_spill`` names a result spill after its operation id.
_TOOL_READ: Final = re.compile(rf"reads/(?P<operation>{_UUID})\.json")
#: ``write_spill_file``'s own name rule, so a stream spill is recognised exactly as it is written.
_STREAM: Final = re.compile(
    r"reads/(?P<operation>[a-z0-9][a-z0-9-]{0,127})\.(?P<stream>stdout|stderr)\.txt"
)
_HISTORY: Final = re.compile(r"work/conversation_history/(?:media/.+|(?P<execution>[^/]+)\.md)")
_LARGE_RESULTS: Final = "work/large_tool_results/"

_NODE_SQL: Final = text(
    """
    SELECT n.tool_name, n.display_params_json, n.created_at,
           r.result_artifact_key, r.result_sha256, a.media_type, a.size_bytes
    FROM execution_node n
    LEFT JOIN agent_tool_result r
           ON r.operation_id = n.operation_id AND r.workspace_id = :workspace
    LEFT JOIN artifact a ON a.storage_key = r.result_artifact_key
    WHERE n.operation_id = :operation
    ORDER BY n.created_at DESC
    LIMIT 1
    """
)


class DbReceiptSource(ReceiptSource):
    """Answer for every saved path from Postgres and the artifact store, or say ``unknown``."""

    def __init__(
        self,
        *,
        conn_factory: ConnFactory = transaction,
        artifacts: DurableAgentArtifactStore,
    ) -> None:
        self._conn_factory = conn_factory
        self._artifacts = artifacts

    async def receipt_for(self, *, workspace_id: str, thread_id: str, path: str) -> Receipt:
        try:
            return await self._lookup(workspace_id=workspace_id, path=path)
        except Exception as exc:  # noqa: BLE001 — a receipt may never fail a save (AW-22)
            log.warning(
                "agent_workspace.receipt_unavailable",
                workspace_id=workspace_id,
                thread_id=thread_id,
                path=path,
                error=type(exc).__name__,
            )
            return UNKNOWN_RECEIPT

    async def _lookup(self, *, workspace_id: str, path: str) -> Receipt:
        stream = _STREAM.fullmatch(path)
        if stream is not None:
            return Receipt(
                source="run_python",
                operation_id=stream["operation"],
                details={"stream": stream["stream"]},
                read_again=READ_AGAIN["run_python"].format(stream=stream["stream"]),
            )
        read = _TOOL_READ.fullmatch(path)
        if read is not None:
            return await self._tool_read(workspace_id=workspace_id, operation=read["operation"])
        history = _HISTORY.fullmatch(path)
        if history is not None:
            execution = history["execution"]
            return Receipt(
                source="conversation_history",
                # A media file is named by the summariser, not by the execution, so there is no
                # execution id to record for it — and none is needed: the whole folder is rebuilt
                # from the conversation, which outlives every snapshot (AW-26).
                details={"execution_id": execution} if execution is not None else {},
                read_again=READ_AGAIN["conversation_history"],
            )
        if path.startswith(_LARGE_RESULTS):
            return Receipt(source="large_tool_results", read_again=READ_AGAIN["large_tool_results"])
        return UNKNOWN_RECEIPT

    async def _tool_read(self, *, workspace_id: str, operation: str) -> Receipt:
        async with self._conn_factory() as conn:
            parameters = {"operation": UUID(operation), "workspace": workspace_id}
            row = (await conn.execute(_NODE_SQL, parameters)).mappings().first()
        if row is None or not row["tool_name"]:
            return UNKNOWN_RECEIPT
        display: dict[str, JsonValue] = dict(row["display_params_json"] or {})
        details: dict[str, JsonValue] = {**display, **await self._counts(workspace_id, row)}
        return Receipt(
            source=str(row["tool_name"]),
            operation_id=operation,
            produced_at=row["created_at"],
            details=details,
            read_again=READ_AGAIN["tool"].format(
                tool=row["tool_name"], params=json.dumps(display, sort_keys=True, default=str)
            ),
        )

    async def _counts(self, workspace_id: str, row: Any) -> dict[str, JsonValue]:
        """How much the read returned, from its result artifact — ``{}`` when it cannot be read.

        The call is already named by the time this runs, so a missing result row, an erased
        artifact or bytes storage cannot serve must leave the receipt poorer, never absent.
        """

        if row["result_artifact_key"] is None or row["media_type"] is None:
            return {}
        try:
            body = await self._artifacts.read(
                ArtifactRef(
                    workspace_id=workspace_id,
                    artifact_key=str(row["result_artifact_key"]),
                    sha256=str(row["result_sha256"]),
                    media_type=str(row["media_type"]),
                    byte_count=int(row["size_bytes"]),
                )
            )
            references = json.loads(body).get("references")
        except Exception as exc:  # noqa: BLE001 — the tool name alone is still worth keeping
            log.warning(
                "agent_workspace.receipt_result_unreadable",
                workspace_id=workspace_id,
                artifact_key=row["result_artifact_key"],
                error=type(exc).__name__,
            )
            return {}
        if not isinstance(references, dict):
            return {}
        return {key: references[key] for key in _COUNT_KEYS if references.get(key) is not None}
