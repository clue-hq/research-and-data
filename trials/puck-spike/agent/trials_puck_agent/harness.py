"""The lean agent harness (T3 of the phase-2 spike): one agent, our tools, three skills.

Built with LangChain's create_agent and the deepagents middleware we want, the way the
platform's scene solo graph is composed (lumen_agent/harness.py::_create_scene_solo_graph):
create_deep_agent always adds a subagent tool, a todo tool and a base prompt, and that weight is
what this spike measures against. The pieces:

- file tools over the run workspace (deepagents FilesystemMiddleware), with writes denied
  outside page.json, shell.json, plan.md and new notes;
- skills (deepagents SkillsMiddleware) with a short listing prompt;
- malformed tool calls patched back to the model (PatchToolCallsMiddleware);
- context clearing: a newer render_page replaces older screenshots in the model request, never
  in the saved history (ContextEditingMiddleware with RenderClearing);
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
FINISH_REMINDERS = 2

SKILLS_PROMPT = """## Skills

{skills_list}

When a skill's description applies, read its whole file with read_file (limit=1000).
{skills_locations}{skills_load_warnings}"""

READ_ONLY = [
    "/.run.json", "/brief.md", "/skills/**", "/catalog/**", "/brand/**", "/research/**",
    "/seller/**", "/fetched/**", "/versions/**", "/renders/**",
]


# --- context clearing ----------------------------------------------------------------------------

def _is_render(message: Any) -> bool:
    return isinstance(message, ToolMessage) and message.name == "render_page" and isinstance(message.content, list)


def clear_old_renders(messages: list) -> list:
    """Replace every render_page result but the newest with a one-line stub that keeps its facts.

    The result depends only on the message list and changes only when a new render lands, so the
    prompt cache holds between renders."""
    renders = [index for index, message in enumerate(messages) if _is_render(message)]
    out = list(messages)
    for index in renders[:-1]:
        message = messages[index]
        facts = " | ".join(
            block.get("text", "") for block in message.content
            if isinstance(block, dict) and block.get("type") == "text"
        )
        out[index] = message.model_copy(update={
            "content": "[cleared to save context: screenshots from an earlier render_page; a newer "
                       f"render replaced them. Facts then: {facts}]",
        })
    return out


@dataclass
class RenderClearing:
    """A ContextEdit for LangChain's ContextEditingMiddleware."""

    def apply(self, messages: list, *, count_tokens: Any) -> None:
        messages[:] = clear_old_renders(messages)


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

    def __init__(self, page_tools: PageTools, *, safety_stop: int = SAFETY_STOP_CALLS) -> None:
        super().__init__()
        self.page_tools = page_tools
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
        return {
            "messages": [HumanMessage(content=(
                "The page is still invalid, so this turn cannot finish yet:\n" + errors
                + "\nFix these and validate again. If one cannot be fixed, leave that part out and "
                "say why in plan.md and in your report."
            ))],
            "jump_to": "model",
        }


# --- the agent -----------------------------------------------------------------------------------

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


def page_tool_set(page_tools: PageTools) -> list:
    from langchain_core.tools import StructuredTool

    return [
        StructuredTool.from_function(
            page_tools.validate_page, name="validate_page",
            description="Check page.json and shell.json against the components, the catalog, the brand "
            "and the evidence. Returns VALID (and saves a version) or INVALID with each error and its fix.",
        ),
        StructuredTool.from_function(
            page_tools.render_page, name="render_page",
            description="Publish the page and return a desktop (1440 wide) and a mobile (375 wide) "
            "full-page screenshot, with facts about broken images, overflow and console errors. "
            "Refuses while the page is invalid.",
        ),
        StructuredTool.from_function(
            page_tools.restore_version, name="restore_version",
            description="Bring back a version saved by validate_page into page.json and shell.json.",
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


def build_agent(page_tools: PageTools, *, model: Any, checkpointer: Any = None, safety_stop: int = SAFETY_STOP_CALLS):
    """Returns (agent, recorder)."""
    from deepagents import FilesystemPermission
    from deepagents.backends import FilesystemBackend
    from deepagents.middleware.filesystem import FilesystemMiddleware
    from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
    from deepagents.middleware.skills import SkillsMiddleware
    from langchain.agents import create_agent
    from langchain.agents.middleware import ContextEditingMiddleware
    from langgraph.checkpoint.memory import InMemorySaver

    backend = FilesystemBackend(root_dir=page_tools.workspace, virtual_mode=True)
    recorder = RunRecorder(page_tools, safety_stop=safety_stop)
    middleware = [
        SkillsMiddleware(backend=backend, sources=["/skills"], system_prompt=SKILLS_PROMPT),
        FilesystemMiddleware(
            backend=backend,
            _permissions=[FilesystemPermission(operations=["write"], paths=READ_ONLY, mode="deny")],
        ),
        PatchToolCallsMiddleware(),
        ContextEditingMiddleware(edits=[RenderClearing()]),
        OrderedToolCalls(),
        recorder,
    ]
    agent = create_agent(
        model,
        tools=page_tool_set(page_tools),
        system_prompt=(AGENT_DIR / "system_prompt.md").read_text(),
        middleware=middleware,
        checkpointer=checkpointer if checkpointer is not None else InMemorySaver(),
        name="puck-page-agent",
    ).with_config({"recursion_limit": 9_999})
    return agent, recorder
