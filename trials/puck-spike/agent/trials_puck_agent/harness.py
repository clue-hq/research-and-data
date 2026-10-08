"""The lean agent harness (T3 of the phase-2 spike): one agent, our tools, three skills.

Built with LangChain's create_agent and the deepagents middleware we want, the way the
platform's scene solo graph is composed (lumen_agent/harness.py::_create_scene_solo_graph):
create_deep_agent always adds a subagent tool, a todo tool and a base prompt, and that weight is
what this spike measures against. The pieces:

- file tools over the run workspace (deepagents FilesystemMiddleware), with writes denied
  outside page.json, shell.json, plan.md and new notes;
- skills carried in the system prompt (cached across calls and sessions), files kept in the workspace;
- malformed tool calls patched back to the model (PatchToolCallsMiddleware);
- context clearing, as the platform website agent does it: superseded renders and asset views,
  out-of-date reads of the site files, and finished planning reads become one-line stubs in the
  model request (never the saved history), changed in batches so the cache holds
  (ContextEditingMiddleware with SupersededResults). On by default: run a2 showed the cache misses
  happen with clearing off too;
- compaction (LangChain SummarizationMiddleware) when one request passes 300k tokens, keeping the
  most recent 60k tokens; no message counts; clearing only once a session passes 60k tokens;
- a read_file without a limit reads the whole file (WholeFileReads);
- tool calls from one response run one at a time, in the order the model wrote them;
- RunRecorder: per-call usage and cost, the 40-call safety stop, and the finish guard (a turn
  cannot end on an invalid page; after two reminders it ends "completed with errors").
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from .tools import PageTools

AGENT_DIR = Path(__file__).resolve().parents[1]
SAFETY_STOP_CALLS = 40
#: Compaction is a safety net for one very long request, by tokens only (founder, 2026-10-08): it
#: starts at 300k tokens and keeps the most recent 60k tokens word for word; older turns are summarised.
COMPACT_AT_TOKENS = 300_000
COMPACT_KEEP_TOKENS = 60_000
#: Context clearing starts only once a session passes this many tokens (founder, 2026-10-08).
CLEAR_FROM_TOKENS = 60_000
FINISH_REMINDERS = 2

READ_ONLY = [
    "/.run.json", "/brief.md", "/site.md", "/history.md", "/skills/**", "/skills-e5/**", "/catalog/**", "/brand/**", "/research/**",
    "/seller/**", "/fetched/**", "/versions/**", "/renders/**",
]


# --- context clearing ----------------------------------------------------------------------------
#
# The platform website agent's lesson (lumen_agent/context_clearing.py, 2026-10-06): earlier tool
# results the model no longer needs become a one-line stub that says what it was and how to get it
# back. Only the model request is edited; the saved history keeps everything. The cleared set
# changes only at two moments — planning ends (plan.md written and the first page write), and a new
# render lands — so between those moments the prompt prefix is byte-identical and the cache holds.

#: Planning reads: once plan.md records the decisions and building has started, they leave the
#: request. Skills, the brief, brand.md and sections.md stay (they are needed while building).
_PLANNING_PREFIXES = ("/catalog/clones/", "/catalog/index.md", "/research/", "/seller/", "/fetched/")
_PLANNING_TOOLS = ("fetch_page", "web_search", "ls", "glob", "grep")
_SITE_FILES = ("/page.json", "/shell.json", "/plan.md")
_WRITERS = ("write_file", "edit_file")


def _calls_by_id(messages: list) -> dict[str, dict]:
    return {
        call["id"]: call
        for message in messages if isinstance(message, AIMessage)
        for call in (message.tool_calls or []) if call.get("id")
    }


def _is_site_file(path: object) -> bool:
    return isinstance(path, str) and (path in _SITE_FILES or (path.startswith("/pages/") and path.endswith(".json")))


def _stub(message: ToolMessage, text: str) -> ToolMessage:
    return message.model_copy(update={"content": text, "artifact": None})


def clear_superseded_results(messages: list) -> list:
    """A copy of ``messages`` with superseded tool results replaced by stubs."""
    calls = _calls_by_id(messages)

    def call_of(message: ToolMessage) -> dict:
        return calls.get(message.tool_call_id) or {}

    last_render, plan_written, build_started = -1, -1, -1
    for index, message in enumerate(messages):
        if not isinstance(message, ToolMessage) or message.status == "error":
            continue
        call = call_of(message)
        path = (call.get("args") or {}).get("file_path")
        if message.name == "render_page" and isinstance(message.content, list):
            last_render = index
        elif message.name in _WRITERS and path == "/plan.md" and plan_written < 0:
            plan_written = index
        elif message.name in _WRITERS and _is_site_file(path) and path != "/plan.md" and build_started < 0:
            build_started = index
    planning_over = max(plan_written, build_started) if plan_written >= 0 and build_started >= 0 else -1

    # Site files written before the last render: earlier reads of them are out of date.
    written_before_render: dict[str, int] = {}
    for index, message in enumerate(messages[: max(last_render, 0)]):
        if isinstance(message, ToolMessage) and message.name in _WRITERS:
            path = (call_of(message).get("args") or {}).get("file_path")
            if _is_site_file(path):
                written_before_render[path] = index

    out = list(messages)
    for index, message in enumerate(messages):
        if not isinstance(message, ToolMessage) or message.status == "error":
            continue
        call = call_of(message)
        args = call.get("args") or {}
        name = message.name or call.get("name")
        path = args.get("file_path")
        if name == "render_page" and isinstance(message.content, list) and index < last_render:
            facts = " | ".join(
                block.get("text", "") for block in message.content
                if isinstance(block, dict) and block.get("type") == "text"
            )
            out[index] = _stub(message, "[cleared to save context: screenshots from an earlier render_page; "
                                        f"a newer render replaced them. Facts then: {facts}]")
        elif name == "view_asset" and index < last_render:
            files = ", ".join(args.get("files") or [])
            out[index] = _stub(message, f"[cleared to save context: images you looked at earlier ({files}). "
                                        "Call view_asset again to see them.]")
        elif name == "read_file" and _is_site_file(path) and written_before_render.get(path, -1) > index:
            out[index] = _stub(message, f"[cleared to save context: an older read of {path}; it has changed "
                                        "since. Read it again for the current version.]")
        elif index < planning_over and (
            (name == "read_file" and isinstance(path, str) and path.startswith(_PLANNING_PREFIXES))
            or name in _PLANNING_TOOLS
        ):
            what = f"{name}({path or args.get('url') or args.get('query') or args.get('pattern') or args.get('path') or ''})"
            saved = ""
            if name == "fetch_page" and isinstance(message.content, str) and message.content.startswith("Saved to "):
                saved = " " + message.content.split(" (status")[0] + "."
            out[index] = _stub(message, f"[cleared to save context: {what} from planning; your decisions are "
                                        f"in plan.md.{saved} Call it again if you need the details.]")
    return out


@dataclass
class SupersededResults:
    """A ContextEdit for LangChain's ContextEditingMiddleware. It does nothing below
    CLEAR_FROM_TOKENS: in a short session each clearing made the next call miss the whole cache
    (E2b: $0.76 of $2.73), more than clearing saved. The count is taken on the full saved history,
    so once a session passes the threshold it keeps clearing and the prefix stays stable."""

    def apply(self, messages: list, *, count_tokens: Any) -> None:
        if count_tokens(messages) < CLEAR_FROM_TOKENS:
            return
        messages[:] = clear_superseded_results(messages)


# --- tool calls in order -------------------------------------------------------------------------

class OrderedToolCalls(AgentMiddleware):
    """One response's tool calls run one at a time, in the order the model wrote them, so a
    write is never validated before it lands."""

    def __init__(self) -> None:
        super().__init__()
        self._turnstile = threading.Condition()
        self._busy = False
        self._done: set[str] = set()

    def wrap_tool_call(self, request, handler):
        messages = (request.state or {}).get("messages", [])
        latest = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
        order = [call["id"] for call in (latest.tool_calls if latest else [])]
        mine = request.tool_call.get("id")
        earlier = order[: order.index(mine)] if mine in order else []
        with self._turnstile:
            self._turnstile.wait_for(lambda: not self._busy and all(i in self._done for i in earlier))
            self._busy = True
        try:
            return handler(request)
        finally:
            with self._turnstile:
                self._busy = False
                self._done.add(mine)
                self._turnstile.notify_all()


# --- live trace ----------------------------------------------------------------------------------

def _short(text: str, limit: int = 300) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + " …"


def describe_call(call: dict) -> str:
    args = call.get("args") or {}
    name = call["name"]
    if name in ("write_file", "edit_file"):
        size = len(args.get("content") or args.get("new_string") or "")
        return f"{name} {args.get('file_path')} ({size} chars)"
    if name in ("glob", "grep"):
        return f"{name} {args.get('pattern')!r} in {args.get('path', '/')}"
    for key in ("file_path", "path", "query", "url", "version"):
        if key in args:
            return f"{name} {args[key]}"
    return name


class LiveTrace(AgentMiddleware):
    """Prints each tool result as it lands (shortened)."""

    def __init__(self, trace) -> None:
        super().__init__()
        self.trace = trace

    def wrap_tool_call(self, request, handler):
        result = handler(request)
        content = getattr(result, "content", result)
        if isinstance(content, list):
            content = " | ".join(b.get("text", "[image]") if isinstance(b, dict) and b.get("type") == "text"
                                 else "[image]" for b in content)
        self.trace(f"    <- {describe_call(request.tool_call)}: {_short(content)}")
        return result


class WholeFileReads(AgentMiddleware):
    """read_file shows 100 lines unless given a limit; here a read without a limit gets the whole
    file (up to 1000 lines), so a skill or a research page is never silently cut off."""

    def wrap_tool_call(self, request, handler):
        call = request.tool_call
        if call["name"] == "read_file" and "limit" not in (call.get("args") or {}):
            request = request.override(tool_call={**call, "args": {**call["args"], "limit": 1000}})
        return handler(request)


# --- the run record ------------------------------------------------------------------------------

@dataclass
class TurnRecord:
    prompt: str
    started: float = field(default_factory=time.time)
    calls: list[dict] = field(default_factory=list)
    reminders: list[str] = field(default_factory=list)
    status: str = "running"
    seconds: float = 0.0


class RunRecorder(AgentMiddleware):
    """Usage and cost per model call, the safety stop and the finish guard."""

    def __init__(self, page_tools: PageTools, *, safety_stop: int = SAFETY_STOP_CALLS, trace=None) -> None:
        super().__init__()
        self.page_tools = page_tools
        self.trace = trace or (lambda line: None)
        self.safety_stop = safety_stop
        self.turns: list[TurnRecord] = []
        self.prompt_size: dict | None = None

    @property
    def turn(self) -> TurnRecord:
        return self.turns[-1]

    def start_turn(self, prompt: str) -> None:
        self.turns.append(TurnRecord(prompt=prompt))

    @hook_config(can_jump_to=["end"])
    def before_model(self, state, runtime):
        if len(self.turn.calls) >= self.safety_stop:
            self.turn.status = "stopped by the safety stop"
            self.trace(f"    !! safety stop at {self.safety_stop} model calls")
            return {
                "messages": [AIMessage(content=f"Stopped: {self.safety_stop} model calls in one turn (safety stop).")],
                "jump_to": "end",
            }
        return None

    def wrap_model_call(self, request, handler):
        if self.prompt_size is None:
            from langchain_core.utils.function_calling import convert_to_openai_tool

            schemas = [convert_to_openai_tool(tool) for tool in request.tools or []]
            system = request.system_prompt or ""
            self.prompt_size = {
                "system_prompt_chars": len(system),
                "system_prompt_words": len(system.split()),
                "tools": [schema["function"]["name"] for schema in schemas],
                "tool_schema_chars": len(json.dumps(schemas)),
            }
        started = time.monotonic()
        response = handler(request)
        message = next((m for m in response.result if isinstance(m, AIMessage)), None)
        usage = (message.usage_metadata if message else None) or {}
        metadata = (message.response_metadata if message else None) or {}
        self.turn.calls.append({
            "seconds": round(time.monotonic() - started, 2),
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "cached_tokens": (usage.get("input_token_details") or {}).get("cache_read", 0),
            "cost_cents": float(metadata.get("clue_cost_cents") or 0),
            "model": metadata.get("clue_answering_model") or metadata.get("model_name"),
            "tool_calls": [call["name"] for call in (message.tool_calls if message else [])],
            "messages_sent": len(request.messages),
        })
        record = self.turn.calls[-1]
        self.trace(
            f"[call {len(self.turn.calls)} · {record['seconds']}s · in {record['input_tokens']:,} "
            f"(cached {record['cached_tokens']:,}) · out {record['output_tokens']:,} · "
            f"${record['cost_cents'] / 100:.4f}]"
        )
        if message is not None and message.text:
            self.trace(f"    says: {_short(message.text, 600)}")
        for call in (message.tool_calls if message else []):
            self.trace(f"    -> {describe_call(call)}")
        return response

    @hook_config(can_jump_to=["model"])
    def after_model(self, state, runtime):
        latest = state["messages"][-1]
        if not isinstance(latest, AIMessage) or latest.tool_calls or self.turn.status != "running":
            return None
        check = self.page_tools._validate_raw()
        if check["valid"]:
            self.turn.status = "completed"
            return None
        if len(self.turn.reminders) >= FINISH_REMINDERS:
            self.turn.status = "completed with errors"
            return None
        errors = "\n".join(f"- {error}" for error in check["errors"])
        self.turn.reminders.append(errors)
        self.trace(f"    !! finish guard: the page is invalid, reminder {len(self.turn.reminders)}")
        return {
            "messages": [HumanMessage(content=(
                "The page is still invalid, so this turn cannot finish yet:\n" + errors
                + "\nFix these and validate again. If one cannot be fixed, leave that part out and "
                "say why in plan.md and in your report."
            ))],
            "jump_to": "model",
        }


class SummaryUsage:
    """Records the compaction model's calls in the run record (they bypass wrap_model_call)."""

    def __new__(cls, recorder: "RunRecorder"):
        from langchain_core.callbacks import BaseCallbackHandler

        class _Handler(BaseCallbackHandler):
            def on_llm_end(self, response, **kwargs):
                message = getattr(response.generations[0][0], "message", None)
                usage = (getattr(message, "usage_metadata", None) or {}) if message else {}
                metadata = (getattr(message, "response_metadata", None) or {}) if message else {}
                recorder.turn.calls.append({
                    "seconds": 0.0, "summary": True,
                    "input_tokens": usage.get("input_tokens", 0), "output_tokens": usage.get("output_tokens", 0),
                    "cached_tokens": (usage.get("input_token_details") or {}).get("cache_read", 0),
                    "cost_cents": float(metadata.get("clue_cost_cents") or 0),
                    "model": metadata.get("clue_answering_model"), "tool_calls": [], "messages_sent": 0,
                })
                recorder.trace(f"    !! compacted the conversation (summary: in {usage.get('input_tokens', 0):,}, "
                               f"${float(metadata.get('clue_cost_cents') or 0) / 100:.4f})")

        return _Handler()


# --- the agent -----------------------------------------------------------------------------------

def system_prompt_with_skills(workspace: Path, *, allow_new_sections: bool = False) -> str:
    """The system prompt with the skills after it: the same text every call and every session, so it
    stays in the prompt cache (E2b re-read about 6k tokens of skills in every session)."""
    folders = ["skills", *(["skills-e5"] if allow_new_sections else [])]
    skills = [
        f"### Skill: {path.parent.name} ({'/' + folder + '/' + path.parent.name}/SKILL.md)\n\n{path.read_text().strip()}"
        for folder in folders for path in sorted((workspace / folder).glob("*/SKILL.md"))
    ]
    return (AGENT_DIR / "system_prompt.md").read_text().rstrip() + "\n\n## Your skills\n\n" + "\n\n".join(skills) + "\n"


def build_model() -> Any:
    """The model through our gateway; the model id is the LUMEN_AGENT_MODEL env setting."""
    from lumen_agent.config import AgentRuntimeConfig
    from lumen_agent.llm import init_model

    config = AgentRuntimeConfig.from_env()
    return init_model(
        config.orchestrator_model,
        base_url=config.agent_base_url,
        api_key=config.agent_api_key,
        reasoning=config.agent_reasoning,
        max_tokens=config.agent_max_tokens,
        provider_sort=config.agent_provider_sort,
        timeout_s=config.agent_llm_timeout_s,
        role="puck_page_agent",
        chat_completions=config.agent_chat_completions,
    )


def page_tool_set(page_tools: PageTools, *, allow_new_sections: bool = False) -> list:
    from langchain_core.tools import StructuredTool

    extra = [
        StructuredTool.from_function(
            page_tools.write_section, name="write_section",
            description="Write a new section as one React file (see the writing-a-section skill). It is "
            "checked for brand tokens and types; if it passes, place it in a page by its name.",
        ),
    ] if allow_new_sections else []
    return extra + [
        StructuredTool.from_function(
            page_tools.validate_page, name="validate_page",
            description="Check page.json and shell.json against the components, the catalog, the brand "
            "and the evidence. Returns VALID (and saves a version) or INVALID with each error and its fix.",
        ),
        StructuredTool.from_function(
            page_tools.render_page, name="render_page",
            description="Publish the site and return a desktop (1440 wide) and a mobile (375 wide) "
            "full-page screenshot of one page, with facts about broken images, overflow and console "
            "errors. route is \"/\" for page.json or \"/<name>\" for pages/<name>.json. Refuses while "
            "the site is invalid.",
        ),
        StructuredTool.from_function(
            page_tools.restore_version, name="restore_version",
            description="Bring back a version saved by validate_page into page.json, shell.json and pages/.",
        ),
        StructuredTool.from_function(
            page_tools.view_asset, name="view_asset",
            description="Look at up to four of the brand's images (files from brand/brand.md), each with "
            "its description, before you choose one for a section.",
        ),
        StructuredTool.from_function(
            page_tools.web_search, name="web_search",
            description="Search the web. Set include_domains to the seller's domain to find its own "
            "published case studies and customer stories.",
        ),
        StructuredTool.from_function(
            page_tools.fetch_page, name="fetch_page",
            description="Open a page and save its text under fetched/ as evidence. Use it before you put "
            "a number or a quote from that page on the page.",
        ),
    ]


def build_agent(page_tools: PageTools, *, model: Any, checkpointer: Any = None,
                safety_stop: int = SAFETY_STOP_CALLS, trace=None, clear_context: bool = True,
                compact_at_tokens: int | None = COMPACT_AT_TOKENS, summary_model: Any = None,
                allow_new_sections: bool = False):
    """Returns (agent, recorder)."""
    from deepagents import FilesystemPermission
    from deepagents.backends import FilesystemBackend
    from deepagents.middleware.filesystem import FilesystemMiddleware
    from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
    from langchain.agents import create_agent
    from langchain.agents.middleware import ContextEditingMiddleware, SummarizationMiddleware
    from langgraph.checkpoint.memory import InMemorySaver

    backend = FilesystemBackend(root_dir=page_tools.workspace, virtual_mode=True)
    trace = trace or (lambda line: None)
    recorder = RunRecorder(page_tools, safety_stop=safety_stop, trace=trace)
    if summary_model is not None:
        summary_model.callbacks = [SummaryUsage(recorder)]
    middleware = [
        FilesystemMiddleware(
            backend=backend,
            _permissions=[FilesystemPermission(operations=["write"], paths=READ_ONLY, mode="deny")],
        ),
        PatchToolCallsMiddleware(),
        *([SummarizationMiddleware(summary_model or model, trigger=("tokens", compact_at_tokens),
                                   keep=("tokens", COMPACT_KEEP_TOKENS))]
          if compact_at_tokens else []),
        *([ContextEditingMiddleware(edits=[SupersededResults()])] if clear_context else []),
        WholeFileReads(),
        OrderedToolCalls(),
        LiveTrace(trace),
        recorder,
    ]
    agent = create_agent(
        model,
        tools=page_tool_set(page_tools, allow_new_sections=allow_new_sections),
        system_prompt=system_prompt_with_skills(page_tools.workspace, allow_new_sections=allow_new_sections),
        middleware=middleware,
        checkpointer=checkpointer if checkpointer is not None else InMemorySaver(),
        name="puck-page-agent",
    ).with_config({"recursion_limit": 9_999})
    return agent, recorder
