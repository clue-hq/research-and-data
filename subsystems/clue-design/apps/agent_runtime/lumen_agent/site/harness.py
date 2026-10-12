"""The site agent's harness (Lane B): the Puck spike's lean agent on the platform's seams.

LangChain's `create_agent` with the deepagents middleware the spike chose — file tools over the
request's workspace with writes denied on its inputs, patched tool calls, the spike's context
clearing (from 60k tokens) and ordered tool calls, whole-file reads, and the finish guard (a
request cannot end on an invalid page; after two reminders it ends with errors) — plus:
- the model through `lumen_agent.harness._instrument` (the governed gateway, role
  `design_site`, trace capture and the cancellation probe);
- compaction through `clue_agents.compaction`, sized by `compaction_for` (the scene harness's
  way), replacing the spike's fixed 300k/60k summariser;
- the founder's turn limits (100 model rounds, 50 tool calls per round, 30 minutes), replacing the
  spike's 40-call stop; no total-call or zero-yield caps;
- receipts through `usage_collector.turn_collector`; the invoke through
  `checkpoint.invoke_turn_graph` on a fresh thread per request (thread id = the run id).
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from ..config import AgentRuntimeConfig
from .inputs import SiteTurnInputs
from .tools import SiteTools, site_tool_set
from .workspace import SITE_DIR, materialize_workspace, read_site_files

#: Context clearing starts only once a session passes this many tokens (founder, 2026-10-08).
CLEAR_FROM_TOKENS = 60_000
FINISH_REMINDERS = 2
READ_ONLY = [
    "/brief.md", "/site.md", "/history.md", "/skills/**", "/skills-e5/**", "/catalog/**", "/brand/**",
    "/research/**", "/seller/**", "/fetched/**", "/project-context/**", "/work/**",
]
#: T12a–T12f (founder-approved, Task 0).
ROUND_LIMIT_NOTE = "Stopped: this request reached its limit of {limit} model calls."
TIME_LIMIT_NOTE = "Stopped: this request reached its limit of {minutes} minutes."
ROUND_REFUSAL = "Not run: this was call {n} in one response, and only the first {limit} run. Make it again in your next step."
CANCELLED_SUMMARY = "Stopped at your request. Nothing was saved."
CRASHED_SUMMARY = "The website turn stopped because of an error, and nothing was saved."
INVALID_SUMMARY = "The page was still invalid, so nothing was saved: {error}"


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

    last_render, last_compare, plan_written, build_started = -1, -1, -1, -1
    for index, message in enumerate(messages):
        if not isinstance(message, ToolMessage) or message.status == "error":
            continue
        call = call_of(message)
        path = (call.get("args") or {}).get("file_path")
        if message.name == "render_page" and isinstance(message.content, list):
            last_render = index
        elif message.name == "compare_section" and isinstance(message.content, list):
            last_compare = index
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
        elif name in ("compare_section", "view_clone") and isinstance(message.content, list) and index < last_compare:
            facts = " | ".join(
                block.get("text", "") for block in message.content
                if isinstance(block, dict) and block.get("type") == "text"
            )
            out[index] = _stub(message, f"[cleared to save context: pictures from an earlier {name}; a newer "
                                        f"comparison replaced them. Text then: {facts[:1500]}]")
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


class WholeFileReads(AgentMiddleware):
    """read_file shows 100 lines unless given a limit; here a read without a limit gets the whole
    file (up to 1000 lines), so a skill or a research page is never silently cut off."""

    def wrap_tool_call(self, request, handler):
        call = request.tool_call
        if call["name"] == "read_file" and "limit" not in (call.get("args") or {}):
            request = request.override(tool_call={**call, "args": {**call["args"], "limit": 1000}})
        return handler(request)


class FinishGuard(AgentMiddleware):
    """A request cannot end on an invalid page (the spike's RunRecorder.after_model).

    A request that never touched the site's files (it only wrote a section, or only answered) is
    not checked. After two reminders the request ends "completed with errors".
    """

    def __init__(self, tools: SiteTools) -> None:
        super().__init__()
        self.site_tools = tools
        self.reminders: list[str] = []
        self.errors: list[str] = []
        self.status = "running"

    @hook_config(can_jump_to=["model"])
    def after_model(self, state, runtime):
        latest = state["messages"][-1]
        if not isinstance(latest, AIMessage) or latest.tool_calls or self.status != "running":
            return None
        if self.site_tools.site_unchanged():
            self.status = "completed (site unchanged)"
            return None
        check = self.site_tools._validate_raw()
        if check["valid"]:
            self.status = "completed"
            self.errors = []
            return None
        self.errors = list(check["errors"])
        if len(self.reminders) >= FINISH_REMINDERS:
            self.status = "completed with errors"
            return None
        errors = "\n".join(f"- {error}" for error in check["errors"])
        self.reminders.append(errors)
        return {
            "messages": [HumanMessage(content=(
                "The page is still invalid, so this turn cannot finish yet:\n" + errors
                + "\nFix these and validate again. If one cannot be fixed, leave that part out and "
                "say why in plan.md and in your report."
            ))],
            "jump_to": "model",
        }


class TurnLimits(AgentMiddleware):
    """The founder's limits on one request (2026-09-08): model rounds and wall clock."""

    def __init__(self, *, max_rounds: int, max_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        super().__init__()
        self.max_rounds = max_rounds
        self.max_seconds = max_seconds
        self._clock = clock
        self.started = clock()
        self.rounds = 0
        self.stop_reason: str | None = None

    @hook_config(can_jump_to=["end"])
    def before_model(self, state, runtime):
        if self.rounds >= self.max_rounds:
            self.stop_reason = "round_limit"
            return {"messages": [AIMessage(content=ROUND_LIMIT_NOTE.format(limit=self.max_rounds))], "jump_to": "end"}
        if self._clock() - self.started >= self.max_seconds:
            self.stop_reason = "time_limit"
            minutes = round(self.max_seconds / 60)
            return {"messages": [AIMessage(content=TIME_LIMIT_NOTE.format(minutes=minutes))], "jump_to": "end"}
        self.rounds += 1
        return None


class RoundShape(AgentMiddleware):
    """At most ``limit`` tool calls of one response run; the rest are refused, each with a result
    (the ARV2 account agent's rule, `clue_api/arv2/account_research_agent.py:293-347`)."""

    def __init__(self, *, limit: int) -> None:
        super().__init__()
        self.limit = limit

    def wrap_tool_call(self, request, handler):
        call = request.tool_call
        messages = (request.state or {}).get("messages", [])
        latest = next((m for m in reversed(messages) if isinstance(m, AIMessage) and m.tool_calls), None)
        ids = [str(item.get("id") or "") for item in (latest.tool_calls if latest else [])]
        position = ids.index(str(call.get("id"))) if str(call.get("id")) in ids else None
        if position is not None and position >= self.limit:
            return ToolMessage(
                content=ROUND_REFUSAL.format(n=position + 1, limit=self.limit),
                tool_call_id=str(call.get("id")),
                name=str(call.get("name")),
                status="error",
            )
        return handler(request)


@dataclass(frozen=True)
class TurnLimitsConfig:
    max_rounds: int = 100
    max_calls_per_round: int = 50
    max_seconds: float = 1800.0

    @property
    def recursion_limit(self) -> int:
        """Covers every round's model call, its tool wave and the middleware hops (the ARV2 rule)."""

        return self.max_rounds * (self.max_calls_per_round + 2) + 4


# The two places the system prompt names research/claims.md. A workspace built without claims (R1's
# comparison arm) gets the research line without them and no claims rule.
CLAIMS_RESEARCH_LINE = (
    "- `research/`: what we know about the account (its overview and insights). Each statement ends\n"
    "  with the claims behind it, like `[c4, c9]`. `research/claims.md` lists each claim with what it\n"
    "  says, its source link and any notes. The \"Watch-outs\" and \"Context only\" sections are background\n"
    "  for your judgement: never put them on the page.\n"
)
PLAIN_RESEARCH_LINE = (
    "- `research/`: what we know about the account (its overview and insights). The \"Watch-outs\" and\n"
    "  \"Context only\" sections are background for your judgement: never put them on the page.\n"
)
CLAIMS_RULE = (
    "- For a number or a quote from the research, check its claim in `research/claims.md`. Use the\n"
    "  figure as the claim states it, and read its notes before you use it.\n"
)


def _base_prompt(workspace: Path) -> str:
    text = (SITE_DIR / "system_prompt.md").read_text()
    if (workspace / "research" / "claims.md").exists():
        return text
    assert CLAIMS_RESEARCH_LINE in text and CLAIMS_RULE in text, "system_prompt.md drifted from harness.py"
    return text.replace(CLAIMS_RESEARCH_LINE, PLAIN_RESEARCH_LINE).replace(CLAIMS_RULE, "")


def system_prompt_with_skills(workspace: Path, *, allow_new_sections: bool = True) -> str:
    """The system prompt with the skills after it, read from the package so every call and every
    session sends the same text (the spike's, E5 on by default)."""

    folders = ["skills", *(["skills-e5"] if allow_new_sections else [])]
    skills = [
        f"### Skill: {path.parent.name} ({'/' + folder + '/' + path.parent.name}/SKILL.md)\n\n{path.read_text().strip()}"
        for folder in folders
        for path in sorted((SITE_DIR / folder).glob("*/SKILL.md"))
    ]
    return _base_prompt(workspace).rstrip() + "\n\n## Your skills\n\n" + "\n\n".join(skills) + "\n"


def build_site_agent(
    tools: SiteTools,
    *,
    model: Any,
    model_id: str,
    checkpointer: Any = None,
    limits: TurnLimitsConfig = TurnLimitsConfig(),
    compaction: Any = None,
    allow_new_sections: bool = True,
):
    """Returns ``(agent, finish_guard, turn_limits)``."""

    from clue_agents import compaction_config
    from clue_agents.compaction import build_compaction_middleware
    from deepagents import FilesystemPermission
    from deepagents.backends import FilesystemBackend
    from deepagents.middleware.filesystem import FilesystemMiddleware
    from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
    from langchain.agents import create_agent
    from langchain.agents.middleware import ContextEditingMiddleware
    from langgraph.checkpoint.memory import InMemorySaver

    backend = FilesystemBackend(root_dir=tools.workspace, virtual_mode=True)
    guard = FinishGuard(tools)
    turn_limits = TurnLimits(max_rounds=limits.max_rounds, max_seconds=limits.max_seconds)
    # Offloaded history lands under /work/ (history_under_work=True), which the session snapshot
    # leaves out: a fresh session per request has no use for the previous request's offloads.
    summariser, compact_tool = build_compaction_middleware(
        model, backend, compaction or compaction_config.compaction_for(model_id), history_under_work=True
    )
    middleware = [
        FilesystemMiddleware(
            backend=backend,
            _permissions=[FilesystemPermission(operations=["write"], paths=READ_ONLY, mode="deny")],
        ),
        PatchToolCallsMiddleware(),
        summariser,
        compact_tool,
        ContextEditingMiddleware(edits=[SupersededResults()]),
        WholeFileReads(),
        OrderedToolCalls(),
        RoundShape(limit=limits.max_calls_per_round),
        turn_limits,
        guard,
    ]
    agent = create_agent(
        model,
        tools=site_tool_set(tools),
        system_prompt=system_prompt_with_skills(tools.workspace, allow_new_sections=allow_new_sections),
        middleware=middleware,
        checkpointer=checkpointer if checkpointer is not None else InMemorySaver(),
        name="clue-site-agent",
    )
    return agent, guard, turn_limits


@dataclass(frozen=True)
class SiteTurnResult:
    #: "applied" (the site is valid or untouched) or "failed".
    status: str
    summary: str
    site: dict
    stop_reason: str | None
    errors: list[str]
    model_calls: list[dict]


def _final_text(messages: list) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not message.tool_calls:
            content = message.content
            text = content if isinstance(content, str) else " ".join(
                block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"
            )
            if text.strip():
                return text.strip()
    return ""


def run_site_turn(
    prompt: str,
    *,
    config: AgentRuntimeConfig,
    inputs: SiteTurnInputs,
    workspace: Path,
    site: dict,
    run_id: str,
    checkpointer: Any = None,
    thread_id: str | None = None,
    cancel_requested: Any = None,
    callbacks: Any = None,
    event_sink: Any = None,
    limits: TurnLimitsConfig = TurnLimitsConfig(),
    model: Any = None,
) -> SiteTurnResult:
    """Write the workspace, run one request, and read the site back. Never raises.

    ``model`` is a test seam; production builds the orchestrator model through ``_instrument``
    with the run's cancellation probe attached.
    """

    from ..cancellation import CANCELLED_STOP_REASON, TurnCancelled
    from ..checkpoint import RUN_ID_KEY, invoke_turn_graph
    from ..harness import _instrument
    from ..usage_collector import turn_collector

    tools: SiteTools | None = None
    try:
        materialize_workspace(workspace, inputs, site=site)
        tools = SiteTools(workspace=workspace, inputs=inputs, base_site=site, event_sink=event_sink)
        if model is None:
            cancel_kwargs = {} if cancel_requested is None else {"cancel_probe": cancel_requested}
            model = _instrument(config, tools, config.orchestrator_model, "site", **cancel_kwargs)
        agent, guard, turn_limits = build_site_agent(
            tools, model=model, model_id=config.orchestrator_model, checkpointer=checkpointer, limits=limits
        )
        collector, handlers = turn_collector(callbacks)
    except Exception as error:  # noqa: BLE001 - a setup failure is the same honest crash, before any model call
        detail = f"{type(error).__name__}: {error}"[:500]
        if tools is not None:
            tools._record("crashed", error=detail)
        return SiteTurnResult("failed", CRASHED_SUMMARY, dict(site), "crashed", [detail], [])
    invoke_config = {
        "recursion_limit": limits.recursion_limit,
        "configurable": {"thread_id": thread_id or run_id},
        "callbacks": handlers,
    }
    initial = {"messages": [HumanMessage(content=prompt, additional_kwargs={RUN_ID_KEY: run_id})]}

    def calls() -> list[dict]:
        return [item.as_json() for item in collector.calls]

    try:
        if cancel_requested is not None and cancel_requested():
            raise TurnCancelled()
        state = invoke_turn_graph(
            agent, initial, invoke_config=invoke_config, checkpointer=checkpointer,
            thread_id=thread_id, run_id=run_id,
        )
    except TurnCancelled:
        tools._record("cancelled")
        return SiteTurnResult("failed", CANCELLED_SUMMARY, dict(site), CANCELLED_STOP_REASON, [], calls())
    except Exception as error:  # noqa: BLE001 - an honest failure, recorded verbatim
        detail = f"{type(error).__name__}: {error}"[:500]
        tools._record("crashed", error=detail)
        return SiteTurnResult("failed", CRASHED_SUMMARY, dict(site), "crashed", [detail], calls())

    summary = _final_text((state or {}).get("messages") or [])
    if guard.status == "completed with errors":
        first = guard.errors[0] if guard.errors else ""
        return SiteTurnResult("failed", INVALID_SUMMARY.format(error=first), dict(site), "site_invalid",
                              list(guard.errors), calls())
    if tools.site_unchanged():
        return SiteTurnResult("applied", summary, dict(site), turn_limits.stop_reason, [], calls())
    if turn_limits.stop_reason is not None:
        check = tools._validate_raw()
        if not check["valid"]:
            errors = list(check["errors"])
            return SiteTurnResult("failed", INVALID_SUMMARY.format(error=errors[0] if errors else ""),
                                  dict(site), "site_invalid", errors, calls())
    try:
        site_after = read_site_files(workspace, site, tools.sections)
    except json.JSONDecodeError as error:
        return SiteTurnResult("failed", INVALID_SUMMARY.format(error=f"a page file is not valid JSON ({error})"),
                              dict(site), "site_invalid", [str(error)], calls())
    return SiteTurnResult("applied", summary, site_after, turn_limits.stop_reason, [], calls())
