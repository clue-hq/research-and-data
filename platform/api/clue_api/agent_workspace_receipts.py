"""Where a chat's saved file came from, read from the rows the turn already wrote (AW-22, AW-24).

F3 Phase 2 expires a raw input's or a working file's bytes and keeps a :class:`Receipt` in their
place, so the agent is still told what the file held and how to get the same thing again. Nothing
new is journalled for it: the facts are already durable, and this is the reader that joins them to
a path.

The path says which rule answers:

``reads/<operation_id>.json``
    A governed tool's whole result, written by the runtime's spill sink, or a tool's own spill
    (a CRM read). The ``execution_node`` row for that call names the tool and its displayed
    parameters; the ``agent_tool_result`` row, when there is one, points at the result artifact
    whose ``references`` say how much came back. One governed call has two operation ids and the
    file may be named by either — see :data:`_NODE_SQL`.
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
from clue_agents.execution import operation_id_for_plan_node
from clue_agents.ports import ReceiptSource
from clue_agents.workspace_snapshot import UNKNOWN_RECEIPT, Receipt
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_db import ConnFactory, transaction
from clue_obs import get_logger

__all__ = ["READ_AGAIN", "DbReceiptSource"]

log = get_logger("clue_api.agent_workspace_receipts")

#: The one sentence each receipt shows the agent once the bytes are gone, keyed by the receipt's
#: source. The wording is the founder-approved text of 2026-10-23 (Phase 2, Task 8) and is not
#: paraphrased anywhere else: every branch below picks a key from here and formats it.
#:
#: ``"tool"`` is the CRM read's sentence, and it is used only when the receipt knows both values
#: it names. A ``reads/`` spill from any other governed tool — and a CRM read whose result row no
#: longer says which provider answered — takes ``"read_spill"``, which names the tool the
#: ``execution_node`` row recorded.
READ_AGAIN: Final[Mapping[str, str]] = {
    "tool": "Run run_crm_action again with the same action and arguments: {action} on {provider}.",
    "read_spill": "Run {tool} again with the same arguments.",
    "run_python": "Run the script again; this was its {stream}.",
    "conversation_history": "Nothing to do: this was a copy of this conversation, which the "
    "platform still has in full.",
    "large_tool_results": "Run the tool again that produced it.",
    "unknown": UNKNOWN_RECEIPT.read_again,
}

#: The ``references`` keys of a read's result the receipt keeps (``RunCrmActionOutput``): how much
#: came back, and which CRM answered. ``provider`` is here and not among the displayed parameters
#: because the ``"tool"`` sentence names it and ``safe_display_fields`` carries only the slug.
_KEPT_REFERENCE_KEYS: Final = ("record_count", "total", "done", "provider")

_UUID: Final = r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}"
#: ``AgentWorkspaceBackend.write_spill`` names a result spill after its operation id.
_TOOL_READ: Final = re.compile(rf"reads/(?P<operation>{_UUID})\.json")
#: ``write_spill_file``'s own name rule, so a stream spill is recognised exactly as it is written.
_STREAM: Final = re.compile(
    r"reads/(?P<operation>[a-z0-9][a-z0-9-]{0,127})\.(?P<stream>stdout|stderr)\.txt"
)
_HISTORY: Final = re.compile(r"work/conversation_history/(?:media/.+|(?P<execution>[^/]+)\.md)")
_LARGE_RESULTS: Final = "work/large_tool_results/"


def _read_again_for(tool_name: str, details: Mapping[str, JsonValue]) -> str:
    """The sentence a spilled governed read is shown once its bytes are gone.

    A CRM read names the action and the CRM it ran against, because those two words are what the
    agent types to run it again. Anything else — another tool's spill, or a CRM read whose result
    row can no longer say which provider answered — names the tool the ``execution_node`` row
    recorded, which is the one word the agent needs to run it again.
    """

    action, provider = details.get("slug"), details.get("provider")
    if tool_name == "run_crm_action" and isinstance(action, str) and isinstance(provider, str):
        return READ_AGAIN["tool"].format(action=action, provider=provider)
    return READ_AGAIN["read_spill"].format(tool=tool_name)


#: The call behind a ``reads/<operation_id>.json`` spill, **scoped to the asking workspace**.
#:
#: One governed tool call carries two operation ids, both derived from its execution and its
#: ``node_key``: the plan operation's (``operation_id_for_plan_node``; ``agent_plan_operation``
#: and ``agent_tool_result`` are keyed on it) and the executor node's (``operation_id_from_key``;
#: ``execution_node`` and the tool's own ``ToolContext``). A spilled governed result is named after
#: the first (``_receipt_reference_values``); a tool that spills for itself — ``run_crm_action`` —
#: after the second. Files already saved are named both ways, so the node is found by either: its
#: own id, or the plan operation at the same ``node_key`` of the same execution. Keying on the
#: node's id alone left every spilled governed result "unknown" (live run, 2026-10-24).
#:
#: ``execution_node`` has no ``workspace_id`` of its own; it is scoped through ``execution``, so
#: that join is the scoping and it is an inner one. Without it the driving row came from whichever
#: workspace owns the operation id, and the id comes from a file name the agent writes (review I4).
_NODE_SQL: Final = text(
    """
    WITH named AS (
        SELECT n.id FROM execution_node n WHERE n.operation_id = :operation
        UNION ALL
        SELECT n.id
        FROM agent_plan_operation o
        JOIN agent_plan p ON p.id = o.plan_id
        JOIN execution_node n ON n.execution_id = p.execution_id AND n.node_key = o.node_key
        WHERE o.operation_id = :operation
    )
    SELECT n.execution_id, n.node_key, n.tool_name, n.display_params_json, n.created_at
    FROM named
    JOIN execution_node n ON n.id = named.id
    JOIN execution e ON e.id = n.execution_id AND e.workspace_id = :workspace
    ORDER BY n.created_at DESC
    LIMIT 1
    """
)

#: The result of that call, keyed on its plan operation — whichever id named the file. Absent for
#: a call with no result row, which must still name itself, so this is a separate, optional read.
_RESULT_SQL: Final = text(
    """
    SELECT r.result_artifact_key, r.result_sha256, a.media_type, a.size_bytes
    FROM agent_tool_result r
    JOIN artifact a ON a.storage_key = r.result_artifact_key
    WHERE r.operation_id = :operation AND r.workspace_id = :workspace
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
            # The result row is the plan operation's, whichever of the two ids named the file.
            parameters["operation"] = operation_id_for_plan_node(
                row["execution_id"], row["node_key"]
            )
            result = (await conn.execute(_RESULT_SQL, parameters)).mappings().first()
        display: dict[str, JsonValue] = dict(row["display_params_json"] or {})
        details: dict[str, JsonValue] = {**display, **await self._counts(workspace_id, result)}
        return Receipt(
            source=str(row["tool_name"]),
            operation_id=operation,
            produced_at=row["created_at"],
            details=details,
            read_again=_read_again_for(str(row["tool_name"]), details),
        )

    async def _counts(self, workspace_id: str, row: Any) -> dict[str, JsonValue]:
        """What the read's own result says about itself — ``{}`` when it cannot be read.

        The call is already named by the time this runs, so a missing result row, an erased
        artifact or bytes storage cannot serve must leave the receipt poorer, never absent.
        """

        if row is None:
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
        return {
            key: references[key] for key in _KEPT_REFERENCE_KEYS if references.get(key) is not None
        }
