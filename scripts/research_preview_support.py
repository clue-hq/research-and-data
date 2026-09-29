"""Shared local trace capture and tool restriction for isolated research previews."""

import json
from pathlib import Path
from time import monotonic

from langchain.agents.middleware import AgentMiddleware
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import ToolMessage


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n")


def content(message):
    if isinstance(message.content, str):
        return message.content
    return "\n".join(
        p["text"] for p in message.content if isinstance(p, dict) and p.get("type") == "text"
    )


class Audit(BaseCallbackHandler):
    def __init__(self, root, started):
        self.root = root
        self.started = started

    def event(self, kind, **data):
        with (self.root / "traces/events.jsonl").open("a") as f:
            f.write(
                json.dumps(
                    {"seconds": round(monotonic() - self.started, 3), "kind": kind, **data},
                    default=str,
                )
                + "\n"
            )

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        save(
            self.root / f"traces/{run_id}.input.json",
            [[m.model_dump(mode="json") for m in batch] for batch in messages],
        )
        self.event("model_started", run_id=str(run_id))

    def on_llm_end(self, response, *, run_id, **kwargs):
        save(self.root / f"traces/{run_id}.output.json", response.model_dump(mode="json"))
        self.event("model_finished", run_id=str(run_id))

    def on_tool_start(self, serialized, input_str, *, run_id, **kwargs):
        self.event(
            "tool_started",
            run_id=str(run_id),
            name=(serialized or {}).get("name"),
            arguments=input_str,
        )

    def on_tool_end(self, output, *, run_id, **kwargs):
        self.event("tool_finished", run_id=str(run_id))


ALLOWED = {"ls", "read_file", "glob", "grep", "capture_exa_request"}


class PreviewTools(AgentMiddleware):
    def __init__(self, allowed=ALLOWED):
        self.allowed = allowed

    async def awrap_model_call(self, request, handler):
        selected = [
            t
            for t in request.tools
            if (t.get("name") if isinstance(t, dict) else t.name) in self.allowed
        ]
        return await handler(request.override(tools=selected))

    async def awrap_tool_call(self, request, handler):
        if request.tool_call["name"] not in self.allowed:
            return ToolMessage(
                content="Unavailable in this prompt-only preview.",
                tool_call_id=request.tool_call["id"],
            )
        return await handler(request)


class ContinuationTools(PreviewTools):
    async def awrap_tool_call(self, request, handler):
        if request.tool_call["name"] in {"write_file", "edit_file"}:
            path = request.tool_call["args"].get("file_path", "")
            if not path.startswith("/scratch/") or ".." in Path(path).parts:
                return ToolMessage(
                    content="Original inputs are read-only; write notes in /scratch/.",
                    tool_call_id=request.tool_call["id"],
                )
        return await super().awrap_tool_call(request, handler)
