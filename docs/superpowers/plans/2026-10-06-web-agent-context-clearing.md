# Website Agent Context Clearing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the website design agent from resending superseded screenshots and finished planning results on every model call, so a 1:1 page costs a fraction of today's ~$7.71 without making the page worse.

**Architecture:** One new pure function decides which earlier tool results the model no longer needs and replaces each with a one-line stub. It runs inside LangChain's `ContextEditingMiddleware` (already installed, `langchain==1.3.14`), which rebuilds the edited copy from the full saved history before every model call. So the saved history and the run view keep everything; only what is sent shrinks. The rule depends only on the message list, and the set of cleared messages changes only when a new preview round lands or the plan is first written. That keeps the prompt cache warm between those moments.

**Tech Stack:** Python 3.12, LangChain 1.3 agent middleware, DeepAgents 0.6 (`create_deep_agent`), pytest. Design subsystem only (`subsystems/clue-design/`).

**Spec:** This plan is its own spec. The founder decisions behind it (2026-10-06, website-quality week 1) are recorded in the Decisions section below. The evidence is the Syracuse City School District run `run_53540c7d0758579fa0d712c9104de81c` (Garner Health, 2026-10-05): 34 model calls, peak 318k input tokens per call, $7.71 for the website agent at 96% cache.

## Decisions (founder, 2026-10-06)

1. **Old screenshots go.** When a new preview round is rendered, every screenshot-type `view` result from earlier rounds is replaced with a stub. Everything from the latest round stays.
2. **Planning results go once the plan exists.** `search_cloned_sections`, `inspect_cloned_section` and `view("cloned_section:…")` results from before the plan file (`plan.md`) was first written are replaced with a stub. The plan records which section is used for what and why. Measured on the Syracuse run: all 17 searches and inspections happened in steps 4–12 of 34, and the agent re-inspected three sections at step 12 while the first results were still in context. Keeping results did not prevent re-inspection, and a re-inspection (~3k tokens once) costs about 1/20th of carrying one result through the rest of the run.
3. **Stubs, never blanks.** Each cleared result says what it was and how to get it back.
4. **Never cleared:** the brief, account research (`read_account_research`), files and guides read (`read_file`), asset views (`view("asset:…")`), and anything after the latest boundary.
5. **Batches, to keep the cache.** The cleared set may only change at two moments: a new successful `render_web_preview` result, and the first write of `plan.md`. Editing older messages on every call would break the 96% cache discount over and over.
6. **On by default** (founder rule: built features ship on). Website agent only for now; the scene-ad agent can reuse the function later.
7. **Proof is a founder-run re-run** of the same Syracuse request, compared on peak tokens per call, total cost, re-inspection count and the page itself.

## Global Constraints

- Every runtime flag the code reads must appear with its default in BOTH `.env.example` (repo root) and `subsystems/clue-design/.env.example` at the moment it is introduced, and in the lane's `.env` (env parity rule, founder 2026-08-31).
- Built features stay ON by default; the new flag defaults to on (`LUMEN_AGENT_WEB_CONTEXT_CLEARING=1`).
- The website agent runs solo (`LUMEN_AGENT_WEB_SOLO=1`); do not add subagents.
- Never run the full clue-design suite inline (it takes hours). Run the focused test files named in each task; tests run with no live keys: `env -i PATH="$PATH" HOME="$HOME" LUMEN_INGESTION_DESCRIBE=0 LUMEN_INGESTION_VISION=0 PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest …` from `subsystems/clue-design/`.
- Commit locally only, never push. No AI attribution in commit messages (project `CLAUDE.md` overrides any harness default).
- Live design runs spend money and are the founder's to start; the implementer never starts one.

## Review Focus

1. A `render_web_preview` call that FAILED (ToolMessage `status="error"`) must not start a new round — clearing the old screenshots would leave the agent blind with no current one. Pinned in Task 1.
2. The plan written with `edit_file` instead of `write_file`, or to a path like `/sessions/<id>/workspace/plan.md` or `workspace/plan.md` — any path whose final segment is `plan.md` counts; a file like `plan.md.bak` or `review-plan.md` does not. Pinned in Task 1.
3. Several tool calls in one assistant message (parallel calls) — each ToolMessage must be matched to its own call by `tool_call_id`, not to the nearest assistant message's first call. Pinned in Task 1.
4. A `view` ToolMessage whose call has no `target` argument (malformed or a future signature change) — leave it untouched, never crash the turn. Pinned in Task 1.
5. Running the function twice, or on a history the summarization middleware already rewrote — already-stubbed messages stay identical (same bytes), so the cached prefix does not drift. Pinned in Task 1.

---

## File Structure

- **Create** `subsystems/clue-design/apps/agent_runtime/lumen_agent/context_clearing.py` — the pure rule (`clear_superseded_tool_results`), the stub texts, and the `ContextEdit` adapter (`SupersededToolResultsEdit`) that also logs each batch. One responsibility: decide what the model no longer needs.
- **Create** `subsystems/clue-design/apps/agent_runtime/tests/test_context_clearing.py` — rule tests on synthetic message lists.
- **Modify** `subsystems/clue-design/packages/py-lumen-config/py_lumen_config/config.py:434` — add the `lumen_agent_web_context_clearing` setting next to `lumen_agent_web_solo`.
- **Modify** `subsystems/clue-design/apps/agent_runtime/lumen_agent/config.py:259,327` — add `web_context_clearing` to `AgentRuntimeConfig` and read it in `from_env`.
- **Modify** `subsystems/clue-design/apps/agent_runtime/lumen_agent/harness_web.py:591-610` — add the middleware to `create_deep_agent(middleware=[...])` when the flag is on.
- **Modify** `subsystems/clue-design/apps/agent_runtime/tests/test_web_solo_mode.py` — wiring tests (flag on adds it; flag off leaves the composition unchanged).
- **Modify** `.env.example`, `subsystems/clue-design/.env.example`, the lane's `.env` — the new flag.
- **Create** `subsystems/clue-design/scripts/context_clearing_replay.py` — a standalone, read-only script that replays a finished run's saved messages through the rule and reports what each call would have sent. Free; gives a number before the founder spends on a live run.

---

### Task 1: The clearing rule

**Files:**
- Create: `subsystems/clue-design/apps/agent_runtime/lumen_agent/context_clearing.py`
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_context_clearing.py`

**Interfaces:**
- Consumes: `langchain_core.messages.{AIMessage, ToolMessage, AnyMessage, BaseMessage}`; `langchain.agents.middleware.context_editing.ContextEdit` protocol (`apply(messages: list, *, count_tokens) -> None`, edits in place).
- Produces:
  - `clear_superseded_tool_results(messages: Sequence[AnyMessage]) -> list[AnyMessage]` — returns a NEW list; never mutates its input.
  - `SupersededToolResultsEdit` — dataclass implementing `ContextEdit`; `apply` replaces `messages[:]` with the cleared list and logs `web_context.cleared` when the cleared count changes.
  - `CLEARED_MARKER = "web_context_clearing"` — the `response_metadata` key that marks a stubbed ToolMessage.

- [ ] **Step 1: Write the failing tests**

```python
"""The website agent's context clearing rule (founder decisions 2026-10-06).

Old screenshots go once a newer preview round exists; planning results (section searches,
inspections, section pictures) go once plan.md exists. Each becomes a stub that says what it
was and how to get it back. The rule depends only on the message list, so the cleared set
changes only when a new round lands or the plan is first written — that keeps the cache.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from lumen_agent.context_clearing import CLEARED_MARKER, clear_superseded_tool_results

_IMAGE = [{"type": "text", "text": "{\"tile\": 0}"},
          {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]


def _call(call_id: str, name: str, **args) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"id": call_id, "name": name, "args": args}])


def _result(call_id: str, name: str, content="ok", status="success") -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=call_id, name=name, status=status)


def _cleared(message) -> bool:
    return bool(message.response_metadata.get(CLEARED_MARKER, {}).get("cleared"))


def _history_with_two_rounds():
    return [
        HumanMessage(content="brief"),
        _call("r1", "render_web_preview"), _result("r1", "render_web_preview"),
        _call("v1", "view", target="preview:1440:tile:0"), _result("v1", "view", _IMAGE),
        _call("a1", "view", target="asset:asset_x"), _result("a1", "view", _IMAGE),
        _call("r2", "render_web_preview"), _result("r2", "render_web_preview"),
        _call("v2", "view", target="preview:1440:tile:0"), _result("v2", "view", _IMAGE),
    ]


def test_screenshots_from_an_earlier_round_become_stubs_and_the_latest_round_stays() -> None:
    out = clear_superseded_tool_results(_history_with_two_rounds())
    old, latest = out[4], out[10]
    assert _cleared(old) and isinstance(old.content, str)
    assert "view('preview:1440:tile:0')" in old.content and "render_web_preview" in old.content
    assert old.artifact is None
    assert not _cleared(latest) and latest.content == _IMAGE
    # The renders themselves and asset views are never cleared.
    assert not _cleared(out[2]) and not _cleared(out[8])
    assert not _cleared(out[6])


def test_a_failed_render_does_not_start_a_new_round() -> None:
    history = _history_with_two_rounds()[:7] + [
        _call("r2", "render_web_preview"), _result("r2", "render_web_preview", "boom", "error"),
    ]
    out = clear_superseded_tool_results(history)
    assert not _cleared(out[4])  # the round-1 screenshot is still the current one


def _planning_history(plan_tool: str = "write_file", plan_path: str = "/sessions/s/workspace/plan.md"):
    return [
        HumanMessage(content="brief"),
        _call("s1", "search_cloned_sections", query="hero"), _result("s1", "search_cloned_sections", "x" * 400),
        _call("i1", "inspect_cloned_section", fragment_id="frag_a"), _result("i1", "inspect_cloned_section", "y" * 400),
        _call("c1", "view", target="cloned_section:frag_a"), _result("c1", "view", _IMAGE),
        _call("p1", plan_tool, file_path=plan_path), _result("p1", plan_tool),
        _call("i2", "inspect_cloned_section", fragment_id="frag_b"), _result("i2", "inspect_cloned_section", "z" * 400),
    ]


def test_planning_results_stay_until_the_plan_is_written() -> None:
    history = _planning_history()[:7]
    out = clear_superseded_tool_results(history)
    assert not any(_cleared(m) for m in out if isinstance(m, ToolMessage))


def test_planning_results_before_the_plan_become_stubs_after_it_is_written() -> None:
    out = clear_superseded_tool_results(_planning_history())
    for index, tool, key in ((2, "search_cloned_sections", "hero"),
                             (4, "inspect_cloned_section", "frag_a"),
                             (6, "view", "cloned_section:frag_a")):
        assert _cleared(out[index]), index
        assert tool in out[index].content and key in out[index].content
        assert "plan.md" in out[index].content
    assert not _cleared(out[8])   # the plan write's own result
    assert not _cleared(out[10])  # an inspection after the plan stays


def test_the_plan_counts_when_edited_or_written_to_a_relative_path_but_not_a_lookalike() -> None:
    assert _cleared(clear_superseded_tool_results(_planning_history("edit_file"))[2])
    assert _cleared(clear_superseded_tool_results(_planning_history(plan_path="workspace/plan.md"))[2])
    assert not _cleared(clear_superseded_tool_results(_planning_history(plan_path="workspace/review-plan.md"))[2])
    assert not _cleared(clear_superseded_tool_results(_planning_history(plan_path="workspace/plan.md.bak"))[2])


def test_parallel_calls_in_one_message_are_matched_by_call_id() -> None:
    both = AIMessage(content="", tool_calls=[
        {"id": "va", "name": "view", "args": {"target": "asset:asset_y"}},
        {"id": "vb", "name": "view", "args": {"target": "preview:768"}},
    ])
    history = [
        _call("r1", "render_web_preview"), _result("r1", "render_web_preview"),
        both, _result("va", "view", _IMAGE), _result("vb", "view", _IMAGE),
        _call("r2", "render_web_preview"), _result("r2", "render_web_preview"),
    ]
    out = clear_superseded_tool_results(history)
    assert not _cleared(out[3])  # asset view kept
    assert _cleared(out[4])      # preview view from round 1 cleared


def test_a_view_without_a_target_is_left_untouched() -> None:
    history = [
        _call("r1", "render_web_preview"), _result("r1", "render_web_preview"),
        _call("v1", "view"), _result("v1", "view", _IMAGE),
        _call("r2", "render_web_preview"), _result("r2", "render_web_preview"),
    ]
    assert not _cleared(clear_superseded_tool_results(history)[3])


def test_the_rule_is_idempotent_and_does_not_mutate_its_input() -> None:
    history = _history_with_two_rounds()
    snapshot = [m.model_copy(deep=True) for m in history]
    once = clear_superseded_tool_results(history)
    twice = clear_superseded_tool_results(once)
    assert [m.model_dump() for m in once] == [m.model_dump() for m in twice]
    assert [m.model_dump() for m in history] == [m.model_dump() for m in snapshot]


def test_the_cleared_prefix_is_stable_between_boundaries() -> None:
    """Cache safety: with no new render and no first plan write in between, a longer history
    clears exactly the same earlier messages as the shorter one."""
    history = _history_with_two_rounds() + [
        _call("v3", "view", target="layout:1440"), _result("v3", "view", "{}"),
    ]
    short = clear_superseded_tool_results(history[:11])
    long = clear_superseded_tool_results(history)
    assert [m.model_dump() for m in long[:11]] == [m.model_dump() for m in short]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `subsystems/clue-design/`): `env -i PATH="$PATH" HOME="$HOME" PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/agent_runtime/tests/test_context_clearing.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'lumen_agent.context_clearing'`.

- [ ] **Step 3: Write the implementation**

```python
"""Context clearing for the website design agent (founder decisions 2026-10-06).

Every model call resends the whole conversation. On the Syracuse run (2026-10-05) old preview
screenshots and finished planning results (section searches, inspections, section pictures)
were about half of the 318k tokens each late call resent. This module decides which earlier
tool results the model no longer needs and replaces each with a one-line stub that says what
it was and how to get it back.

It runs inside LangChain's ContextEditingMiddleware, which rebuilds the edited copy from the
full saved history before every call: the saved history and the run view keep everything.

Cache rule: the result depends only on the message list, and the cleared set changes only when
a new successful render_web_preview result lands or plan.md is first written. Between those
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
    """(index of the latest successful render result, index of the first plan.md write result);
    -1 when absent."""
    last_render, plan_written = -1, -1
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
    return last_render, plan_written


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
    last_render, plan_written = _boundaries(messages, calls)
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
            render_bound = target in _RENDER_BOUND_EXACT or target.startswith(_RENDER_BOUND_PREFIXES)
            if render_bound and index < last_render:
                out[index] = _stub(
                    message,
                    f"[cleared to save context: view('{target}') from an earlier preview round; "
                    "a newer render_web_preview has replaced it. Call view again for the current one.]",
                    "superseded_render",
                )
            elif target.startswith("cloned_section:") and 0 <= plan_written and index < plan_written:
                out[index] = _stub(
                    message,
                    f"[cleared to save context: view('{target}') from planning; your decisions are "
                    "recorded in plan.md. Call view again if you need the picture.]",
                    "after_plan",
                )
        elif name in _PLANNING_TOOLS and 0 <= plan_written and index < plan_written:
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
            if isinstance(m, ToolMessage) and m.response_metadata.get(CLEARED_MARKER, {}).get("cleared")
        )
        if cleared != self._last_cleared:
            log.info(
                "web_context.cleared",
                cleared_results=cleared,
                approx_tokens_before=before,
                approx_tokens_after=count_tokens(messages),
            )
            self._last_cleared = cleared
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `env -i PATH="$PATH" HOME="$HOME" PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/agent_runtime/tests/test_context_clearing.py -q`
Expected: all 9 PASS.

- [ ] **Step 5: Commit**

```bash
git add subsystems/clue-design/apps/agent_runtime/lumen_agent/context_clearing.py subsystems/clue-design/apps/agent_runtime/tests/test_context_clearing.py
git commit -m "Website agent: clear superseded screenshots and finished planning results from the model request

Founder decisions 2026-10-06. A pure rule over the message list replaces old preview-round
screenshots and pre-plan section searches/inspections/pictures with one-line stubs. The
cleared set only changes on a new successful render or the first plan.md write, so the
prompt cache holds between those moments. Not wired yet."
```

---

### Task 2: The flag and the wiring

**Files:**
- Modify: `subsystems/clue-design/packages/py-lumen-config/py_lumen_config/config.py:434`
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/config.py:259,327`
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/harness_web.py:591-610`
- Modify: `.env.example` (repo root, next to `LUMEN_AGENT_WEB_SOLO=1`, line ~628), `subsystems/clue-design/.env.example` (line ~431), and the lane's `.env`
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_web_solo_mode.py`

**Interfaces:**
- Consumes: `SupersededToolResultsEdit` (Task 1); `langchain.agents.middleware.ContextEditingMiddleware(edits=[...])`.
- Produces: `AgentRuntimeConfig.web_context_clearing: bool` (default `True`); `Settings.lumen_agent_web_context_clearing: bool` (default `True`), read from `LUMEN_AGENT_WEB_CONTEXT_CLEARING`.

- [ ] **Step 1: Write the failing wiring tests** (append to `test_web_solo_mode.py`, which already has `_create_web_agent` and `_solo_config`)

```python
def test_context_clearing_rides_the_web_agent_by_default(tmp_path, monkeypatch) -> None:
    from langchain.agents.middleware import ContextEditingMiddleware

    from lumen_agent.context_clearing import SupersededToolResultsEdit

    captured = _create_web_agent(tmp_path, monkeypatch, _solo_config(tmp_path))
    editing = [m for m in captured["middleware"] if isinstance(m, ContextEditingMiddleware)]
    assert len(editing) == 1
    assert [type(e) for e in editing[0].edits] == [SupersededToolResultsEdit]


def test_context_clearing_flag_off_leaves_the_composition_unchanged(tmp_path, monkeypatch) -> None:
    from langchain.agents.middleware import ContextEditingMiddleware

    config = replace(_solo_config(tmp_path), web_context_clearing=False)
    captured = _create_web_agent(tmp_path, monkeypatch, config)
    assert not any(isinstance(m, ContextEditingMiddleware) for m in captured["middleware"])
```

- [ ] **Step 2: Run them to verify they fail**

Run: `env -i PATH="$PATH" HOME="$HOME" LUMEN_INGESTION_DESCRIBE=0 LUMEN_INGESTION_VISION=0 PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/agent_runtime/tests/test_web_solo_mode.py -q -k context_clearing`
Expected: FAIL (`web_context_clearing` is not a field / middleware absent).

- [ ] **Step 3: Implement**

`py_lumen_config/config.py`, directly under `lumen_agent_web_solo: bool = False` (line 434):

```python
    # Context clearing (founder decisions 2026-10-06): replace superseded preview screenshots and
    # finished planning results with stubs before each website-agent model call. On by default.
    lumen_agent_web_context_clearing: bool = True
```

`lumen_agent/config.py`, under `web_solo: bool = False` (line 259):

```python
    # Context clearing (founder decisions 2026-10-06): see lumen_agent/context_clearing.py.
    web_context_clearing: bool = True
```

and in `from_env`, next to `web_solo=settings.lumen_agent_web_solo,` (line 327):

```python
            web_context_clearing=settings.lumen_agent_web_context_clearing,
```

`harness_web.py`, replace `middleware=[WebDelegationCap(record=tools.record)],` in the `create_deep_agent(...)` call with:

```python
        middleware=[
            WebDelegationCap(record=tools.record),
            *_context_clearing_middleware(runtime_config),
        ],
```

and add near the other module-level helpers:

```python
def _context_clearing_middleware(runtime_config: AgentRuntimeConfig) -> list:
    """Founder decisions 2026-10-06: superseded screenshots and finished planning results leave
    the model request (never the saved history). Off restores the previous composition."""
    if not runtime_config.web_context_clearing:
        return []
    from langchain.agents.middleware import ContextEditingMiddleware

    from .context_clearing import SupersededToolResultsEdit

    return [ContextEditingMiddleware(edits=[SupersededToolResultsEdit()])]
```

Env files — add directly after `LUMEN_AGENT_WEB_SOLO=1` in BOTH `.env.example` files, and add `LUMEN_AGENT_WEB_CONTEXT_CLEARING=1` to the lane's `.env`:

```
# Website-agent context clearing (founder decisions 2026-10-06): before each model call, old
# preview screenshots (superseded by a newer render) and section searches/inspections from
# before plan.md become one-line stubs. Saved history is untouched. 0 sends everything again.
LUMEN_AGENT_WEB_CONTEXT_CLEARING=1
```

- [ ] **Step 4: Run the wiring tests and the existing solo/config tests**

Run: `env -i PATH="$PATH" HOME="$HOME" LUMEN_INGESTION_DESCRIBE=0 LUMEN_INGESTION_VISION=0 PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/agent_runtime/tests/test_web_solo_mode.py apps/agent_runtime/tests/test_web_review_cap.py apps/agent_runtime/tests/test_context_clearing.py -q` (`test_web_review_cap.py` also reads `captured["middleware"]`, filtering by type).
Expected: PASS, except the five tests already failing at HEAD before this work (`test_tool_surfaces_are_exactly_the_ledger`, `test_flag_on_author_toolset_includes_render`, `test_the_account_reads_are_registered_only_when_the_platform_injected_them[True]`, `test_the_create_website_skill_geometry_block_names_all_ten`, `test_the_tool_docstrings_carry_the_amendment_too`) if any of them is collected. Then find and run any env-parity test: `grep -rln "env.example" subsystems/clue-design/apps/*/tests subsystems/clue-design/packages/*/tests tests | head` and run those files.

- [ ] **Step 5: Commit**

```bash
git add subsystems/clue-design/packages/py-lumen-config/py_lumen_config/config.py subsystems/clue-design/apps/agent_runtime/lumen_agent/config.py subsystems/clue-design/apps/agent_runtime/lumen_agent/harness_web.py subsystems/clue-design/apps/agent_runtime/tests/test_web_solo_mode.py .env.example subsystems/clue-design/.env.example
git commit -m "Website agent: context clearing on by default (LUMEN_AGENT_WEB_CONTEXT_CLEARING)

Wires the clearing rule into the web deepagent through LangChain's ContextEditingMiddleware.
Flag documented in both .env.example files at its default (env parity rule). Off restores the
previous middleware list exactly."
```

(`.env` is not tracked; update it by hand and do not commit it.)

---

### Task 3: Free replay on the real Syracuse run

**Files:**
- Create: `subsystems/clue-design/scripts/context_clearing_replay.py`

**Interfaces:**
- Consumes: `clear_superseded_tool_results` (Task 1); the LangGraph `checkpoint_writes` table (channel `messages`, deserialized with `langgraph.checkpoint.serde.jsonplus.JsonPlusSerializer`).
- Produces: a printed table, per model call, of approximate tokens sent today vs with clearing, and the totals.

- [ ] **Step 1: Write the script**

```python
"""Replay a finished design run's messages through the context-clearing rule (read-only, free).

Rebuilds the run's message history from LangGraph's checkpoint_writes, then for each model call
compares what was sent (everything before that call) with what clearing would have sent. Token
counts use LangChain's approximate counter, so compare the two columns, not absolute dollars.

Usage (repo root):
    set -a; source .env; set +a
    .venv/bin/python subsystems/clue-design/scripts/context_clearing_replay.py dsess_b5f568ded78d5224abafd1d836c670f0
Env: CLUE_DATABASE_URL (the lane DB; the +asyncpg driver suffix is stripped).
"""

from __future__ import annotations

import os
import sys

import psycopg
from langchain_core.messages import AIMessage
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "agent_runtime"))
from lumen_agent.context_clearing import clear_superseded_tool_results  # noqa: E402


def load_messages(dsn: str, thread_id: str) -> list:
    serde = JsonPlusSerializer()
    rows = psycopg.connect(dsn).execute(
        "select type, blob from checkpoint_writes where thread_id=%s and channel='messages' "
        "order by checkpoint_id, task_id, idx",
        (thread_id,),
    ).fetchall()
    messages, seen = [], set()
    for typ, blob in rows:
        value = serde.loads_typed((typ, blob))
        for message in value if isinstance(value, list) else [value]:
            key = getattr(message, "id", None) or id(message)
            if key not in seen:
                seen.add(key)
                messages.append(message)
    return messages


def main() -> None:
    thread_id = sys.argv[1]
    dsn = os.environ["CLUE_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    messages = load_messages(dsn, thread_id)
    call_points = [i for i, m in enumerate(messages) if isinstance(m, AIMessage)]
    total_now = total_cleared = 0
    print(f"{'call':>4} {'sent today':>12} {'with clearing':>14}")
    for n, index in enumerate(call_points, start=1):
        history = messages[:index]
        now = count_tokens_approximately(history)
        cleared = count_tokens_approximately(clear_superseded_tool_results(history))
        total_now += now
        total_cleared += cleared
        print(f"{n:>4} {now:>12,} {cleared:>14,}")
    print(f"total {total_now:,} -> {total_cleared:,} ({100 * (1 - total_cleared / max(total_now, 1)):.0f}% less)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it on the Syracuse run**

Run (repo root): `set -a; source .env; set +a; .venv/bin/python subsystems/clue-design/scripts/context_clearing_replay.py dsess_b5f568ded78d5224abafd1d836c670f0`
Expected: one row per model call (34) and a total line. The system prompt and tool definitions (~48k per call) are not in the message history, so this undercounts both columns by the same amount; report the difference, not the totals, as the saving.

- [ ] **Step 3: Record the result and commit**

Add the per-call peak and total reduction to `_memory/2026-10-04-shashank-design-integration.md`, then:

```bash
git add subsystems/clue-design/scripts/context_clearing_replay.py _memory/2026-10-04-shashank-design-integration.md
git commit -m "Design runs: a free replay of a finished run through the context-clearing rule

Rebuilds the run's messages from checkpoint_writes and compares, per model call, what was sent
with what clearing would send. Syracuse run result recorded in session memory."
```

---

### Task 4: Live proof (founder-run)

**Files:** none changed; this task is a measurement.

- [ ] **Step 1: Restart the lane stack on the new commits** (`./scripts/dev_stack_trenton.sh down`, wait for the processes to exit, then `nohup ./scripts/dev_stack_trenton.sh up > /tmp/trenton_up.log 2>&1 < /dev/null & disown`; check `status` and the logs for tracebacks). Check nothing is mid-run first.
- [ ] **Step 2: The founder sends the same request** in the Garner Health workspace ("please make a personalised landing page for this account." with Syracuse City School District tagged). The implementer does not start it.
- [ ] **Step 3: Compare against the 2026-10-05 baseline** (website agent: 34 calls, peak 318k input tokens per call, $7.71; total with Head of ABM $8.15; ~12 minutes):
  - cost and peak from `model_call_usage` lines (`cost_cents`, `prompt_tokens`, `cached_prompt_tokens`) for the new run id in `/tmp/trenton_fleet_worker*.log`;
  - `web_context.cleared` log lines (how many batches, tokens before/after);
  - re-inspection count: `inspect_cloned_section` / `search_cloned_sections` calls after plan.md was written, from the run's checkpoint messages;
  - the page itself: send the founder the final preview, and scan the final text for leaked notes as in the 2026-10-05 check.
- [ ] **Step 4: Record the comparison** in `_memory/` and report to the founder. If re-inspections jump or the page gets worse, the founder decides whether to loosen the rule (for example, keep the latest inspection per section).
