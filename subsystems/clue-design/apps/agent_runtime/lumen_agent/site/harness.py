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

import contextlib
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from py_lumen_obs import get_logger

from ..config import AgentRuntimeConfig
from .inputs import SiteSection, SiteTurnInputs
from .tools import SiteTools, site_tool_set
from .workspace import (
    SITE_DIR,
    collect_working_copy,
    materialize_workspace,
    overlay_working_copy,
    read_site_files,
    record_component,
    working_copy_digest,
)

logger = get_logger("lumen_agent.site.harness")

#: Context clearing starts only once a session passes this many tokens (founder, 2026-10-08).
CLEAR_FROM_TOKENS = 60_000
FINISH_REMINDERS = 2
READ_ONLY = [
    "/brief.md", "/site.md", "/history.md", "/skills/**", "/skills-e5/**", "/skills-live/**", "/catalog/**",
    "/brand/**", "/research/**", "/seller/**", "/fetched/**", "/project-context/**", "/work/**",
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
    not checked. After two reminders the request ends "completed with errors". A validator that
    cannot run is not an invalid page: the request completes and the save gives the verdict (the
    executor's persist meets design_write_site's own check).
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
        if check["valid"] or check.get("unavailable"):
            # Unavailable: no reminder the model could act on, and not site_invalid; the save decides.
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

    def seconds_used(self) -> float:
        return self._clock() - self.started

    def carry_over(self, *, rounds: int, seconds_used: float, stop_reason: str | None) -> None:
        """A taken-over turn keeps the rounds and time its earlier attempts used (founder point d):
        repeated takeovers can never buy it a fresh 100 rounds or 30 minutes."""

        self.rounds = int(rounds)
        self.started = self._clock() - float(seconds_used)
        self.stop_reason = stop_reason


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


#: A live workspace's two prompt lines (founder-approved wording, 2026-10-15): render_page's notes
#: report hydration differences, and step 1 names the interactive-section skill.
RENDER_PAGE_LINE = "- `render_page`: a desktop and a mobile screenshot of one page.\n"
LIVE_RENDER_PAGE_LINE = (
    "- `render_page`: a desktop and a mobile screenshot of one page; its notes name any place the server and the "
    "browser drew a section differently.\n"
)
SKILLS_STEP = (
    "1. Your skills are below this prompt: `account-page-copy`, `building-with-puck`,\n"
    "   `images-and-logos` and `page-review`, and for new sections `writing-a-section` and\n"
    "   `rebuilding-a-section`. Follow them.\n"
)
LIVE_SKILLS_STEP = (
    "1. Your skills are below this prompt: `account-page-copy`, `building-with-puck`,\n"
    "   `images-and-logos` and `page-review`, and for new sections `writing-a-section` and\n"
    "   `rebuilding-a-section`, and, on this site, `making-a-section-interactive` when a section needs\n"
    "   to respond to the visitor. Follow them.\n"
)


def _base_prompt(workspace: Path, *, live: bool = False) -> str:
    text = (SITE_DIR / "system_prompt.md").read_text()
    assert RENDER_PAGE_LINE in text and SKILLS_STEP in text, "system_prompt.md drifted from harness.py"
    if live:
        text = text.replace(RENDER_PAGE_LINE, LIVE_RENDER_PAGE_LINE).replace(SKILLS_STEP, LIVE_SKILLS_STEP)
    if (workspace / "research" / "claims.md").exists():
        return text
    assert CLAIMS_RESEARCH_LINE in text and CLAIMS_RULE in text, "system_prompt.md drifted from harness.py"
    return text.replace(CLAIMS_RESEARCH_LINE, PLAIN_RESEARCH_LINE).replace(CLAIMS_RULE, "")


def system_prompt_with_skills(workspace: Path, *, allow_new_sections: bool = True, live: bool = False) -> str:
    """The system prompt with the skills after it, read from the package so every call and every
    session sends the same text (the spike's, E5 on by default). ``live``: the workspace publishes
    live sites, so two prompt lines name render_page's hydration notes and the interactive-section
    skill, and the skills-live/ skills follow, when new sections are allowed."""

    folders = [
        "skills",
        *(["skills-e5"] if allow_new_sections else []),
        *(["skills-live"] if live and allow_new_sections else []),
    ]
    skills = [
        f"### Skill: {path.parent.name} ({'/' + folder + '/' + path.parent.name}/SKILL.md)\n\n{path.read_text().strip()}"
        for folder in folders
        for path in sorted((SITE_DIR / folder).glob("*/SKILL.md"))
    ]
    return _base_prompt(workspace, live=live).rstrip() + "\n\n## Your skills\n\n" + "\n\n".join(skills) + "\n"


# --- the working copy (site-turn durability, 2026-10-16) -----------------------------------------
#
# A running turn keeps ONE working copy, overwritten in place: the text of its editable files and
# the in-memory state a takeover must not lose, stamped with the conversation checkpoint they match.
# A worker that dies mid-turn is taken over by another that lays the copy over a folder rebuilt
# from the stored site and resumes the conversation from that checkpoint, so nothing finished is
# redone (docs/superpowers/plans/2026-10-16-site-turn-durability.md §2.1).

#: ``sink(checkpoint_id, files, turn_state, files_sha256)``: the executor's port to the copy's row.
#: ``files`` and ``files_sha256`` are ``None`` for a RE-STAMP: the files are those of the copy
#: already written, only its checkpoint and turn state move on (an update of the existing row).
WorkingCopySink = Callable[[str, "dict | None", dict, "str | None"], Any]


@dataclass(frozen=True)
class SiteTurnResume:
    """A taken-over turn's starting point: the working copy's checkpoint, files and turn state."""

    checkpoint_id: str
    files: dict
    turn_state: dict


def capture_turn_state(tools: SiteTools, limits: "TurnLimits", guard: FinishGuard, notes: dict) -> dict:
    """What a takeover must restore that the files do not hold."""

    return {
        "schema_version": 1,
        "sections": {
            name: {"digest": s.digest, "props_schema": s.props_schema, "module_js": s.module_js, "css": s.css}
            for name, s in tools.turn_sections().items()
        },
        "assets": tools.turn_assets(),
        "rounds": limits.rounds,
        "seconds_used": limits.seconds_used(),
        "stop_reason": limits.stop_reason,
        "finish": {"status": guard.status, "reminders": list(guard.reminders), "errors": list(guard.errors)},
        "skipped_files": list(notes.get("skipped") or []),
        "dropped_files": list(notes.get("dropped") or []),
    }


def restore_turn_state(tools: SiteTools, limits: "TurnLimits", guard: FinishGuard, state: dict) -> None:
    """Put a working copy's turn state back: the turn's sections (over any older pinned digest of
    the same name, and back in catalog/seller-components.md), its images, its round and time
    counters, and the finish guard's reminders."""

    for name, section in (state.get("sections") or {}).items():
        tools.sections[name] = SiteSection(
            name=name, digest=section["digest"], props_schema=section["props_schema"],
            module_js=section["module_js"], css=section["css"],
        )
        record_component(tools.workspace, name, section["props_schema"])
    tools.brand.setdefault("assets", {}).update(state.get("assets") or {})
    limits.carry_over(
        rounds=int(state.get("rounds") or 0),
        seconds_used=float(state.get("seconds_used") or 0.0),
        stop_reason=state.get("stop_reason"),
    )
    finish = state.get("finish") or {}
    guard.status = finish.get("status") or "running"
    guard.reminders = list(finish.get("reminders") or [])
    guard.errors = list(finish.get("errors") or [])


class WorkingCopy(AgentMiddleware):
    """First in the middleware list. Before each model call (the previous round's tools are done
    and its checkpoint, under ``durability="sync"``, committed) it writes the working copy when
    the files or the turn's sections and images changed. When they did not but the checkpoint moved
    on (a round that only read), it RE-STAMPS the copy already written with the new checkpoint and
    the current turn state, without sending the files again, so a takeover redoes at most the step
    in flight and its round and time counters are current. After the agent's answer it stamps the
    final copy, so a takeover after the last step makes no model call at all. The first round always
    writes a copy (the files as the turn starts), so there is a row to re-stamp from the start.

    A sink that fails is logged and retried at the next round: the turn goes on, its copy one round
    older. Anything that is not an ``Exception`` (a dying worker) is never caught here."""

    def __init__(self, tools: SiteTools, sink: WorkingCopySink) -> None:
        super().__init__()
        self.site_tools = tools
        self.sink = sink
        self.turn_limits: TurnLimits | None = None
        self.guard: FinishGuard | None = None
        self._written: tuple[str, str] | None = None
        #: The checkpoint the copy row is stamped with now (``None``: no copy written yet).
        self._stamped_at: str | None = None

    def bind(self, *, turn_limits: "TurnLimits", guard: FinishGuard) -> None:
        self.turn_limits, self.guard = turn_limits, guard

    def _capture(self) -> tuple[dict, dict, str, tuple[str, str]]:
        files, notes = collect_working_copy(self.site_tools.workspace)
        state = capture_turn_state(self.site_tools, self.turn_limits, self.guard, notes)
        files_sha = working_copy_digest(files)
        turn = json.dumps({"sections": state["sections"], "assets": state["assets"]}, sort_keys=True)
        return files, state, files_sha, (files_sha, turn)

    def prime(self, checkpoint_id: str | None = None) -> None:
        """Take the workspace as it stands (the start of the turn, or the restored copy) as the
        last copy written, so the first round writes only the starting copy (when none exists yet) unless something changed.
        ``checkpoint_id``: the restored copy's checkpoint (its row exists, so it can be re-stamped)."""

        self._written = self._capture()[3]
        self._stamped_at = checkpoint_id

    def _write(self, runtime: Any, *, always: bool) -> None:
        info = getattr(runtime, "execution_info", None)
        self.write_at(getattr(info, "checkpoint_id", None), always=always)

    def write_at(self, checkpoint_id: str | None, *, always: bool = True) -> None:
        """Write the copy stamped with ``checkpoint_id``: from the hooks, the checkpoint they run
        from; for a drained turn, the last step its graph committed."""

        files, state, files_sha, key = self._capture()
        if not checkpoint_id:
            return
        # Before any copy exists the first round writes one, changed or not, so even the rounds
        # before the first file change are never redone; after that an unchanged round re-stamps.
        if key == self._written and not always and self._stamped_at is not None:
            if checkpoint_id == self._stamped_at:
                return
            try:
                self.sink(checkpoint_id, None, state, None)
            except Exception:  # noqa: BLE001 - a lost re-stamp costs a redone round, never the turn
                logger.warning("site_turn.working_copy_restamp_failed", checkpoint_id=checkpoint_id, exc_info=True)
                return
            self._stamped_at = checkpoint_id
            return
        try:
            self.sink(checkpoint_id, files, state, files_sha)
        except Exception:  # noqa: BLE001 - a lost copy costs a redone round, never the turn
            logger.warning("site_turn.working_copy_write_failed", checkpoint_id=checkpoint_id, exc_info=True)
            return
        if state["dropped_files"]:
            logger.warning("site_turn.working_copy_dropped_offloads", dropped=len(state["dropped_files"]))
        self._written = key
        self._stamped_at = checkpoint_id

    def before_model(self, state, runtime):
        self._write(runtime, always=False)
        return None

    def after_agent(self, state, runtime):
        self._write(runtime, always=True)
        return None


def build_site_agent(
    tools: SiteTools,
    *,
    model: Any,
    model_id: str,
    checkpointer: Any = None,
    limits: TurnLimitsConfig = TurnLimitsConfig(),
    compaction: Any = None,
    allow_new_sections: bool = True,
    live: bool = False,
    working_copy: WorkingCopy | None = None,
):
    """Returns ``(agent, finish_guard, turn_limits)``. ``working_copy`` goes first in the list."""

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
    if working_copy is not None:
        working_copy.bind(turn_limits=turn_limits, guard=guard)
    middleware = [
        *([working_copy] if working_copy is not None else []),
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
        system_prompt=system_prompt_with_skills(tools.workspace, allow_new_sections=allow_new_sections, live=live),
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


def _latest_checkpoint_id(agent: Any, invoke_config: dict) -> str | None:
    """The newest checkpoint of the turn's thread; ``None`` when it cannot be read (the copy then
    stays at its last round, and the takeover redoes at most that round)."""

    try:
        snapshot = agent.get_state({"configurable": dict(invoke_config["configurable"])})
        return (snapshot.config or {}).get("configurable", {}).get("checkpoint_id")
    except Exception:  # noqa: BLE001 - a lost restamp costs a redone round, never the drain
        logger.warning("site_turn.drain_checkpoint_unreadable", exc_info=True)
        return None


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
    resume: SiteTurnResume | None = None,
    working_copy_sink: WorkingCopySink | None = None,
) -> SiteTurnResult:
    """Write the workspace, run one request, and read the site back. Never raises, except
    :class:`lumen_agent.drain.TurnDrained`.

    ``model`` is a test seam; production builds the orchestrator model through ``_instrument``
    with the run's cancellation probe attached.

    Site-turn durability (2026-10-16): the graph runs with ``durability="sync"``. With
    ``working_copy_sink`` the turn keeps its working copy (:class:`WorkingCopy`). With ``resume``
    (a taken-over turn) the copy's files are laid over the freshly built workspace AFTER the
    tools take the stored site as their baseline, its turn state is restored, and the
    conversation resumes from the copy's checkpoint. Without ``resume``, a thread that already
    carries this run is refused rather than resumed at its latest checkpoint.

    Drain (2026-10-16): a turn with a working copy registers in the drain scope its handler
    selected (:mod:`lumen_agent.drain`). Asked to drain, it stops at its next step boundary,
    stamps its copy at that step's checkpoint and raises ``TurnDrained``: the worker is shutting
    down, and the worker that takes the run over continues it from the copy.
    """

    from langgraph.errors import GraphDrained
    from langgraph.runtime import RunControl

    from .. import drain
    from ..cancellation import CANCELLED_STOP_REASON, TurnCancelled
    from ..checkpoint import RUN_ID_KEY, invoke_turn_graph
    from ..harness import _instrument
    from ..usage_collector import turn_collector

    tools: SiteTools | None = None
    try:
        materialize_workspace(workspace, inputs, site=site)
        # The baseline of "did this turn change anything" is the STORED site, taken before any
        # working copy is laid over the folder.
        tools = SiteTools(workspace=workspace, inputs=inputs, base_site=site, event_sink=event_sink)
        if resume is not None:
            overlay_working_copy(workspace, resume.files)
        if model is None:
            cancel_kwargs = {} if cancel_requested is None else {"cancel_probe": cancel_requested}
            model = _instrument(config, tools, config.orchestrator_model, "site", **cancel_kwargs)
        working_copy = WorkingCopy(tools, working_copy_sink) if working_copy_sink is not None else None
        agent, guard, turn_limits = build_site_agent(
            tools, model=model, model_id=config.orchestrator_model, checkpointer=checkpointer, limits=limits,
            live=inputs.live_sites, working_copy=working_copy,
        )
        if resume is not None:
            restore_turn_state(tools, turn_limits, guard, resume.turn_state)
        if working_copy is not None:
            working_copy.prime(resume.checkpoint_id if resume is not None else None)
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

    # Only a turn that keeps a working copy can be drained: a takeover continues it from that copy.
    control = RunControl() if working_copy is not None else None
    try:
        if cancel_requested is not None and cancel_requested():
            raise TurnCancelled()
        with drain.registered(control) if control is not None else contextlib.nullcontext():
            state = invoke_turn_graph(
                agent, initial, invoke_config=invoke_config, checkpointer=checkpointer,
                thread_id=thread_id, run_id=run_id,
                resume_checkpoint_id=resume.checkpoint_id if resume is not None else None,
                resume_latest=False, durability="sync", control=control,
            )
    except GraphDrained as drained:
        # The worker is shutting down. The graph stopped between two steps, and with
        # ``durability="sync"`` the last step's checkpoint is committed: stamp the copy there, so the
        # takeover redoes nothing this attempt finished. Not a failure, and nothing is saved.
        working_copy.write_at(_latest_checkpoint_id(agent, invoke_config))
        logger.info("site_turn.drained", run_id=run_id, reason=drained.reason, rounds=turn_limits.rounds)
        raise drain.TurnDrained(drained.reason) from None
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
        # Unavailable is no verdict on the page (FinishGuard's rule): the save decides.
        if not check["valid"] and not check.get("unavailable"):
            errors = list(check["errors"])
            return SiteTurnResult("failed", INVALID_SUMMARY.format(error=errors[0] if errors else ""),
                                  dict(site), "site_invalid", errors, calls())
    try:
        site_after = read_site_files(workspace, site, tools.sections)
    except json.JSONDecodeError as error:
        return SiteTurnResult("failed", INVALID_SUMMARY.format(error=f"a page file is not valid JSON ({error})"),
                              dict(site), "site_invalid", [str(error)], calls())
    return SiteTurnResult("applied", summary, site_after, turn_limits.stop_reason, [], calls())
