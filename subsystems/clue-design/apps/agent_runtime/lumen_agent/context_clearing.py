"""Context clearing for the website design agent (founder decisions 2026-10-06).

Every model call resends the whole conversation. On the Syracuse run (2026-10-05) screenshots
and planning results (section searches, inspections, section pictures) were about half of the
conversation history each late call resent; replaying that run through this rule cut its total
input by about a quarter (the latest round's screenshots stay). This module decides which earlier
tool results the model no longer needs and replaces each with a one-line stub that says what
it was and how to get it back.

It runs inside LangChain's ContextEditingMiddleware, which rebuilds the edited copy from the
full saved history before every call: the saved history and the run view keep everything.

Cache rule: the result depends only on the message list, and the cleared set changes only when
a new successful render_web_preview result lands or planning ends (plan.md written and building
started, whichever is later). Between those
moments the edited prefix is byte-identical from call to call, so the prompt cache holds.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
from py_lumen_obs import get_logger

log = get_logger(__name__)

CLEARED_MARKER = "web_context_clearing"

#: `view` targets that read the latest render; a newer successful render supersedes them.
_RENDER_BOUND_PREFIXES = ("preview:", "state:", "layout:", "typography:", "node:")
_RENDER_BOUND_EXACT = ("review", "doc")
#: Planning reads, superseded once plan.md records the decisions.
_PLANNING_TOOLS = ("search_cloned_sections", "inspect_cloned_section")
_PLAN_WRITERS = ("write_file", "edit_file")
#: Tools that change the page: the first successful one means building has started.
_BUILD_TOOLS = (
    "author_web_page",
    "patch_web_page",
    "author_web_subtree",
    "web_ops",
    "assemble_cloned_sections",
    "insert_cloned_section",
    "compose_web_section",
    "repair_cloned_section",
    "mint_campaign_shells",
    "assemble_abm_page",
)


def _calls_by_id(messages: Sequence[AnyMessage]) -> dict[str, dict]:
    calls: dict[str, dict] = {}
    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls or []:
                if call.get("id"):
                    calls[call["id"]] = call
    return calls


def _is_plan_path(path: object) -> bool:
    return isinstance(path, str) and PurePosixPath(path).name == "plan.md"


def _boundaries(messages: Sequence[AnyMessage], calls: dict[str, dict]) -> tuple[int, int]:
    """(index of the latest successful render result, index where planning is over); -1 when
    absent. Planning is over once plan.md has been written AND building has started, at
    whichever of the two came later: an early skeleton plan does not end planning, and the
    stubs' "decisions are recorded in plan.md" is only said once plan.md exists."""
    last_render, plan_written, build_started = -1, -1, -1
    for index, message in enumerate(messages):
        if not isinstance(message, ToolMessage) or message.status == "error":
            continue
        call = calls.get(message.tool_call_id) or {}
        name = message.name or call.get("name")
        if name == "render_web_preview":
            last_render = index
        elif (
            plan_written < 0
            and name in _PLAN_WRITERS
            and _is_plan_path((call.get("args") or {}).get("file_path"))
        ):
            plan_written = index
        elif build_started < 0 and name in _BUILD_TOOLS:
            build_started = index
    if plan_written < 0 or build_started < 0:
        return last_render, -1
    return last_render, max(plan_written, build_started)


def _stub(message: ToolMessage, text: str, reason: str) -> ToolMessage:
    return message.model_copy(
        update={
            "content": text,
            "artifact": None,
            "response_metadata": {
                **message.response_metadata,
                CLEARED_MARKER: {"cleared": True, "reason": reason},
            },
        }
    )


def clear_superseded_tool_results(messages: Sequence[AnyMessage]) -> list[AnyMessage]:
    """Return a copy of ``messages`` with superseded tool results replaced by stubs."""
    calls = _calls_by_id(messages)
    last_render, planning_over = _boundaries(messages, calls)
    out: list[AnyMessage] = list(messages)
    for index, message in enumerate(messages):
        if not isinstance(message, ToolMessage):
            continue
        if message.response_metadata.get(CLEARED_MARKER, {}).get("cleared"):
            continue
        call = calls.get(message.tool_call_id) or {}
        name = message.name or call.get("name")
        args = call.get("args") or {}
        if name == "view":
            target = args.get("target")
            if not isinstance(target, str):
                continue
            render_bound = target in _RENDER_BOUND_EXACT or target.startswith(
                _RENDER_BOUND_PREFIXES
            )
            if render_bound and index < last_render:
                out[index] = _stub(
                    message,
                    f"[cleared to save context: view('{target}') from an earlier preview round; "
                    "a newer render_web_preview has replaced it. "
                    "Call view again for the current one.]",
                    "superseded_render",
                )
            elif target.startswith("cloned_section:") and planning_over > index:
                out[index] = _stub(
                    message,
                    f"[cleared to save context: view('{target}') from planning; your decisions are "
                    "recorded in plan.md. Call view again if you need the picture.]",
                    "after_plan",
                )
        elif name in _PLANNING_TOOLS and planning_over > index:
            key = args.get("fragment_id") or args.get("query") or ""
            out[index] = _stub(
                message,
                f"[cleared to save context: {name}({key}) from planning; your decisions are "
                f"recorded in plan.md. Call {name} again if you need the details.]",
                "after_plan",
            )
    return out


@dataclass(slots=True)
class SupersededToolResultsEdit:
    """`ContextEdit` adapter for ContextEditingMiddleware. Logs one line per batch."""

    _last_cleared: int = field(default=0, repr=False)

    def apply(self, messages: list[AnyMessage], *, count_tokens) -> None:
        before = count_tokens(messages)
        messages[:] = clear_superseded_tool_results(messages)
        cleared = sum(
            1
            for m in messages
            if isinstance(m, ToolMessage)
            and m.response_metadata.get(CLEARED_MARKER, {}).get("cleared")
        )
        if cleared != self._last_cleared:
            log.info(
                "web_context.cleared",
                cleared_results=cleared,
                approx_tokens_before=before,
                approx_tokens_after=count_tokens(messages),
            )
            self._last_cleared = cleared
