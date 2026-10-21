# Research Cost Phase 1 (Waste Removal) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (chosen: inline
> implementation by the session, then one whole-branch review on **Fable 5.1**). Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut an account's research cost from ~$25 to ~$12–15, and its time from ~55 to ~30–35
minutes, by removing waste only. Research content, depth, models and media behaviour stay the
same.

**Architecture:** Every behaviour change ships as **quality recipe 26**. Recipe 26 adds new tool
versions alongside the old ones, new account and person profiles and prompts, and new runtime
behaviour that switches on only when a job's `quality_recipe_version >= 26`. Jobs pinned to
recipe 25 run exactly as they do today, so the comparison against production is like for like.
The one exception is the `read_file` default-window fix, which is already global and
uncommitted on this branch.

**Tech Stack:** Python 3.12, deepagents 0.6.12, langchain 1.3.14 (`langchain.agents.middleware`),
pydantic v2, SQLAlchemy async/Postgres, pytest. The DB suites run on the throwaway DB
`clue_dushanbe_test` only.

**Spec (sources this plan argues from):**
- `docs/reports/2026-10-07-dialpad-loopio-research-cost-breakdown.md`: the measured cost
  breakdown of the production run on 2026-10-06.
- `2026-10-06-account-research-v26-cost-and-speed-plan.md` (repo root, untracked): the
  co-founder's plan. This plan implements its W1 items 1–10, minus item 12 (media off), which
  the founder rejected on 2026-10-07: media stays on.
- Founder decisions in chat on 2026-10-07: do Step 1 only, keep media on, and defer the
  content-scope, v26-pipeline and round-budget decisions.

## Global Constraints

- **Media stays on.** Do not touch `discover_media`, `read_media` or the media skills
  (founder, 2026-10-07).
- **No change to research content or depth.** Do not change coverage instructions, caps or
  the person-depth charter (decisions deferred by the founder).
- **No pre-emptive caps** (ruling 2026-09-08): do not add round, call or time limits.
- **No code that counts words, lines or items in agent prose** (ruling 2026-10-04).
- **Agent-facing text** (prompts, skills, tool descriptions, placeholders) is shown to the
  founder before it is written (memory `skill-content-founder-review`). See Task 8.
- **Env parity** (CLAUDE.md): every new setting goes into `.env.example` with its default at
  the moment it is introduced. The local `.env` gets the same keys.
- **Recipe gating:** every behaviour change checks `quality_recipe_version >= 26`. The single
  exception is Task 1, the already-global paging fix.
- **Hash-pinned resources:** never edit a `v25` prompt, skill, profile, recipe or launch
  manifest in place. Add `v26` files.
- **Commits** are local only, with no AI attribution (CLAUDE.md overrides the harness default),
  on branch `perf/research-cost-phase1`.
- **Live provider runs spend money.** Task 12 is triggered by the founder only.
- **Name clash:** this plan's "recipe 26" is *not* the co-founder's proposed "v26 pipeline". If
  that pipeline is built later, it becomes recipe 27 or higher.

## Review Focus

1. **Prompt cache stability.** Tool-result clearing must not change the prompt prefix on every
   call. Once the clearing boundary has advanced, it must stay put until the next threshold
   crossing (Task 4 test `test_boundary_is_stable_between_crossings`).
2. **Resumed and continued turns.** A checkpointed turn resumed after a lease loss, and a
   reconciliation continuation, must keep the same cleared set and must not re-add the identity
   message (Task 3 and Task 4 continuation tests).
3. **A person finishes before its account imports.** The contact page is deferred rather than
   failing, and it is written later by the generation's final step. Nothing gets stuck if the
   account fails without importing (Task 10 tests).
4. **A save with mixed valid and invalid findings.** Valid findings are saved; invalid ones are
   named with a precise reason. No silent default review is ever invented (Task 6).
5. **Recipe-25 jobs that are already running** see no behaviour change anywhere: views, tools,
   receipts, release, rewrites (a "recipe 25 unchanged" assertion in every task).

---

## File map

| File | Responsibility | Tasks |
|---|---|---|
| `platform/api/clue_api/arv2/quality_workspace.py` | Evidence view rendering; add `render_text` | 1, 2 |
| `platform/api/clue_api/arv2/quality_views.py` | `/research/*` views: plain-text passages for recipe ≥26, `agrep` literal search | 2, 5 |
| `platform/api/clue_api/arv2/quality_recipe.py` (new) | `RECIPE_26 = 26`, `recipe_of(scope) -> int`, `at_least(scope, n) -> bool` | 2–11 |
| `platform/agents/clue_agents/tool_result_clearing.py` (new) | `BatchedToolResultClearing` middleware, plus the gutter strip for `read_file` | 4 |
| `platform/api/clue_api/quality_research_wiring.py` | Research-only seams: middleware, compaction, identity dedupe, tool registration, profile rung | 3, 4, 6, 7, 9 |
| `libs/clue-config/clue_config/settings.py`, `.env.example` | New `arv2_research_*` settings | 4 |
| `platform/api/clue_api/arv2/quality_tools.py` | `search_evidence@2` precondition refusals for recipe ≥26 | 5 |
| `platform/api/clue_api/arv2/dossier_json.py`, `quality_json_dossier.py` | `EntryReview` with visible statuses; `save_dossier_section@2` / `update_dossier_findings@2` partial save | 6 |
| `platform/api/clue_api/arv2/quality_provider_tools.py` | `acquire_research_evidence@2` receipt with preview and an honest `empty` status | 7 |
| `platform/agents/catalog/research-quality/**` | v26 prompts and profiles, `recipe-v26.json`, `launch-v4-r26.json` | 8, 9 |
| `platform/api/clue_api/arv2/quality_catalog.py` | `CURRENT_RECIPE_VERSION = 26` | 9 |
| `platform/api/clue_api/arv2/quality_person_release.py` | Release at nomination for recipe ≥26 | 10 |
| `platform/api/clue_api/arv2/page_writer_runtime.py`, `account_research_driver.py`, `quality_coverage.py`, `quality_generation.py` | Deferred contact pages; one final page step; skip when unchanged | 10, 11 |
| `scripts/compare_research_runs.py` (new) | Before/after metrics from the DB and Langfuse | 12 |

---

### Task 1: Commit the `read_file` default-window fix (already implemented)

**Files:**
- Modify (already modified, uncommitted): `platform/api/clue_api/arv2/quality_workspace.py:44-58`
- Test (already added): `tests/arv2/test_research_read_bounds.py::test_a_read_without_a_window_returns_the_whole_view_at_the_libraries_real_default`

**Interfaces:** Produces the `render_view(value, *, offset, limit)` behaviour that every later
task relies on: `limit in (DEFAULT_READ_LIMIT, 2000)` or `limit <= 0` returns the whole view.

- [ ] **Step 1: Re-prove RED on the base commit.** Stash only this file's change in a temporary
  worktree, never `git stash`. The test must fail there.

```bash
cd /Users/aryankeshri/conductor/workspaces/research-and-data/dushanbe
git worktree add --detach /private/tmp/claude-501/p1-base d4575ee32 -q
cp tests/arv2/test_research_read_bounds.py /private/tmp/claude-501/p1-base/tests/arv2/
cd /private/tmp/claude-501/p1-base && /Users/aryankeshri/conductor/workspaces/research-and-data/dushanbe/.venv/bin/python -m pytest -q tests/arv2/test_research_read_bounds.py -p no:cacheprovider
```
Expected: 1 failed (`test_a_read_without_a_window…`).

- [ ] **Step 2: GREEN on the branch.**

```bash
cd /Users/aryankeshri/conductor/workspaces/research-and-data/dushanbe
.venv/bin/python -m pytest -q tests/arv2/test_research_read_bounds.py tests/arv2/test_quality_workspace_db.py -p no:cacheprovider
git worktree remove --force /private/tmp/claude-501/p1-base
```
Expected: all pass. The DB file needs `CLUE_DATABASE_URL` pointed at `clue_dushanbe_test`.

- [ ] **Step 3: Commit.**

```bash
git add platform/api/clue_api/arv2/quality_workspace.py tests/arv2/test_research_read_bounds.py
git commit -m "Research views return the whole file when read_file omits its window

deepagents 0.6.12 fills an omitted limit with 100, not the 2000 the view assumed, so
'read the whole file' returned 100 lines and agents paged 700-line results 80 lines
at a time (~330 extra reads across the 12 production jobs of 2026-10-06)."
```

---

### Task 2: Plain-text research views for recipe ≥26 (no 256-char chunks, no JSON inside JSON)

**Files:**
- Create: `platform/api/clue_api/arv2/quality_recipe.py`
- Modify: `platform/api/clue_api/arv2/quality_workspace.py` (`render_text`; `EvidenceWorkspace.aread` source branch)
- Modify: `platform/api/clue_api/arv2/quality_views.py` (`_passage` callers: operations, documents, capabilities, person brief, claim, transcripts)
- Test: `tests/arv2/test_research_plain_views.py` (new), `tests/arv2/test_quality_workspace_db.py`

**Interfaces:**
- Produces `quality_recipe.recipe_of(scope: JobScope) -> int`, which returns `int((scope.input_refs or {}).get("quality_recipe_version", 0))`.
- Produces `quality_recipe.at_least(scope: JobScope, version: int) -> bool`.
- Produces `quality_recipe.RECIPE_26: Final = 26`.
- Produces `quality_workspace.render_text(header: str, body: str, *, offset: int, limit: int) -> ReadResult`. The output is `header + "\n" + body`. It is line-sliced only when the caller passes an explicit window, using the same whole-by-default rule as `render_view`.
- **Measured baseline:** the current rendering spends 20% of read tokens on formatting
  (2026-10-07: 75,750 → 60,755 tokens over 80 real reads). An operation result is today
  escaped compact JSON cut into 256-char segments, wrapped in indented JSON.

- [ ] **Step 1: Write the failing tests.**

```python
# tests/arv2/test_research_plain_views.py
"""Recipe 26 research views are the document itself, not escaped 256-character segments."""
import json

from deepagents.middleware.filesystem import DEFAULT_READ_LIMIT

from clue_api.arv2.quality_recipe import RECIPE_26, at_least, recipe_of
from clue_api.arv2.quality_views import passage_view
from clue_api.arv2.quality_workspace import render_text


class _Scope:
    def __init__(self, version):
        self.input_refs = {"quality_recipe_version": version}


def test_recipe_helpers_read_the_pinned_version():
    assert recipe_of(_Scope(26)) == 26 and at_least(_Scope(26), RECIPE_26)
    assert not at_least(_Scope(25), RECIPE_26)


def test_plain_text_view_is_header_plus_body_with_no_escaping():
    body = json.dumps({"report": "Dialpad's CMO left in Sept 2025.", "n": 3})
    result = render_text("# /research/operations/x/0.json", body, offset=0, limit=DEFAULT_READ_LIMIT)
    content = result.file_data["content"]
    assert content.splitlines()[0] == "# /research/operations/x/0.json"
    assert json.loads(content.split("\n", 1)[1]) == {"report": "Dialpad's CMO left in Sept 2025.", "n": 3}
    assert "\\\"" not in content and "text_segments" not in content


def test_recipe_26_passage_is_plain_and_recipe_25_keeps_segments():
    body = "x" * 1000
    new = passage_view(body, 0, "documents/a", recipe=26)
    old = passage_view(body, 0, "documents/a", recipe=25)
    assert isinstance(new, str) and new.endswith(body)
    assert old["text_segments"][0]["text"] == "x" * 256  # recipe 25 unchanged


def test_plain_view_honours_an_explicit_window_and_a_nonzero_start():
    body = "\n".join(f"line {i}" for i in range(500))
    window = render_text("# h", body, offset=10, limit=5).file_data["content"].splitlines()
    assert window == [f"line {i}" for i in range(9, 14)]  # header is line 0
    assert passage_view(body, 7, "documents/a", recipe=26).endswith(body[7:])
```

- [ ] **Step 2: Run, expect failure.**
  Run: `.venv/bin/python -m pytest -q tests/arv2/test_research_plain_views.py -p no:cacheprovider`
  Expected: `ModuleNotFoundError: clue_api.arv2.quality_recipe`.

- [ ] **Step 3: Implement.**

```python
# platform/api/clue_api/arv2/quality_recipe.py
"""Recipe gates for quality research behaviour (one place, read from the job's pinned refs)."""
from typing import Any, Final

RECIPE_26: Final = 26  # phase-1 waste removal (docs/superpowers/plans/2026-10-07-research-cost-phase1.md)


def recipe_of(scope: Any) -> int:
    return int((getattr(scope, "input_refs", None) or {}).get("quality_recipe_version", 0))


def at_least(scope: Any, version: int) -> bool:
    return recipe_of(scope) >= version
```

In `quality_workspace.py`, add:

```python
def render_text(header: str, body: str, *, offset: int, limit: int) -> ReadResult:
    """A research view as plain text: one header line, then the document exactly as stored."""
    rendered = f"{header}\n{body}"
    if limit <= 0 or limit in (DEFAULT_READ_LIMIT, 2000):
        limit = max(1, len(rendered.splitlines()))
    sliced = slice_read_response({"content": rendered, "encoding": "utf-8"}, offset, limit)
    if isinstance(sliced, ReadResult):
        return sliced
    return ReadResult(file_data={"content": sliced, "encoding": "utf-8"})
```

- In `quality_views.py`, rename `_passage` to a new public `passage_view(body, start, path, *, recipe) -> dict | str`.
  - It returns the old dict when `recipe < RECIPE_26`.
  - For recipe 26 it returns `body[start:]`. The header is added by the caller.
  - Keep `_passage = lambda b, s, p: passage_view(b, s, p, recipe=0)`, so existing imports and tests stay valid.
- Every `_view` branch that returned `_passage(...)` returns a `(header, text)` pair when `at_least(scope, RECIPE_26)`.
  - `aread` then calls `render_text(header, text, ...)` instead of `render_view`.
  - The header format is `# {path} — {total_chars} chars` plus, for operations, ` — operation {status}`.
- **Operations branch only (recipe ≥26).** `raw` is compact JSON. Serve it as `json.dumps(json.loads(raw), ensure_ascii=False, indent=1)` so nested strings are no longer escaped twice. Measure: the test asserts no `\"` sequences.
- **`EvidenceWorkspace.aread` source branch (recipe ≥26).** Render the metadata (path, title, url, kind, published) as `key: value` header lines, then the source `text` unsegmented.
  - `EvidenceWorkspace` receives the scope recipe through a new keyword `recipe: int = 0`.
  - `ResearchViewMount` passes it in from `self._scope`.

- [ ] **Step 4: GREEN.**
  Run: `.venv/bin/python -m pytest -q tests/arv2/test_research_plain_views.py tests/arv2/test_research_read_bounds.py tests/arv2/test_quality_workspace_db.py tests/arv2/test_quality_path_tools_db.py tests/arv2/test_person_research_port_db.py -p no:cacheprovider`
  Expected: all pass. The existing tests run at recipe <26 and keep their segment assertions.

- [ ] **Step 5: Add a recipe-26 DB test** to `tests/arv2/test_quality_workspace_db.py`. Seed a job with `quality_recipe_version: 26`, then read an evidence source and an operation result through `research_backend(...)`. Assert:
  - the content starts with `#`
  - it contains no `text_segments`
  - it equals header + stored text

  Run it and expect PASS.

- [ ] **Step 6: Commit** `"Recipe 26 research views serve the document as plain text"`.

---

### Task 3: Remove the duplicated identity prompt from research turns (recipe ≥26)

**Files:**
- Modify: `platform/api/clue_api/quality_research_wiring.py` (`_Contexts.assemble`, ~L353-386)
- Test: `tests/arv2/test_research_identity_once.py` (new)

**Interfaces:**
- Consumes `AssembledAgentContext(manifest, messages, materializations, continuation)` from `platform/agents/clue_agents/ports.py:122`.
- Consumes `ResolvedAgentProfile.system_prompt`, which is `prompt_body + "\n\n" + generated_resource_map`. That is the same text the runtime already sends as the system message (`runtime.py:640` + `ExactAgentToolSurfaceMiddleware`, `runtime.py:189-196`).
- Produces `drop_identity_echo(context: AssembledAgentContext, identity: str) -> AssembledAgentContext`.

**Why:** today every research call carries the prompt and resource map twice: once as the system message, and again as `SystemMessage` messages[0]. A reconciliation continuation (`runtime.py:774`) appends a third copy after the saved history.

- [ ] **Step 1: Failing test.**

```python
# tests/arv2/test_research_identity_once.py
from langchain_core.messages import HumanMessage, SystemMessage

from clue_api.quality_research_wiring import drop_identity_echo
from clue_agents.ports import AssembledAgentContext


def _ctx(messages):
    return AssembledAgentContext.model_construct(manifest=None, messages=tuple(messages), materializations=())


def test_the_identity_system_message_is_removed_once_and_only_it():
    identity = "PROMPT\n\nRESOURCE MAP"
    ctx = _ctx([SystemMessage(identity), SystemMessage("Pinned context card"), HumanMessage("go")])
    out = drop_identity_echo(ctx, identity)
    assert [m.content for m in out.messages] == ["Pinned context card", "go"]


def test_no_identity_message_is_a_no_op():
    ctx = _ctx([HumanMessage("go")])
    assert drop_identity_echo(ctx, "PROMPT").messages == ctx.messages
```

- [ ] **Step 2: Run, expect failure** with `ImportError: drop_identity_echo`.

- [ ] **Step 3: Implement** in `quality_research_wiring.py`:

```python
def drop_identity_echo(context: AssembledAgentContext, identity: str) -> AssembledAgentContext:
    """The runtime already sends the identity as the system message; drop its in-conversation copy."""
    kept = tuple(
        m for m in context.messages
        if not (isinstance(m, SystemMessage) and m.content == identity)
    )
    return context if kept == context.messages else context.model_copy(update={"messages": kept})
```

In `_Contexts.assemble`, after `.assemble(...)`:

```python
assembled = await build_agent_context_assembler(...).assemble(request=request, profile=profile, history=history)
if at_least(runtime.scope, RECIPE_26):
    assembled = drop_identity_echo(assembled, resolved.system_prompt)
return assembled
```

The context manifest and receipt are unchanged: the L1 layer is still recorded, only its duplicate is not sent.

- [ ] **Step 4: Add a DB test** to `tests/arv2/test_reconciliation_continuation_db.py`, extending `test_account_continues_native_history_repairs_submission_and_replays` with a recipe-26 variant. Capture the model request with the existing fake model, then assert that no `SystemMessage` whose content equals `resolved.system_prompt` appears in `request.messages`, either on the first turn or on the continuation. Expected: PASS.

- [ ] **Step 5: Measure.** Print `len(resolved.system_prompt)` for the v26 account profile into the commit message as the per-call saving. Today the v25 prompt is 10,399 bytes plus the resource map.

- [ ] **Step 6: Commit** `"Research turns send the identity prompt once (recipe 26)"`.

---

### Task 4: Batched tool-result clearing, gutter strip and a research-only compaction backstop

**Files:**
- Create: `platform/agents/clue_agents/tool_result_clearing.py`
- Modify: `platform/api/clue_api/quality_research_wiring.py` (`bindings()` ~L743 middleware tuple; `compaction_for` at ~L1090)
- Modify: `libs/clue-config/clue_config/settings.py`, `.env.example`, local `.env`
- Test: `tests/agents/test_tool_result_clearing.py` (new), `tests/agents/test_compaction.py`

**Interfaces:**
- Produces `BatchedToolResultClearing(trigger_tokens: int, target_tokens: int, keep_paths: tuple[str, ...], placeholder: Callable[[str | None], str])`, an `AgentMiddleware` with a `state_schema` that adds `cleared_tool_call_ids: list[str]`.
- Produces `strip_read_gutter(content: str) -> str`.
- New settings, with `.env.example` lines:
  - `arv2_research_clear_trigger_tokens: int = 100_000` (`CLUE_ARV2_RESEARCH_CLEAR_TRIGGER_TOKENS=100000`)
  - `arv2_research_clear_target_tokens: int = 50_000` (`CLUE_ARV2_RESEARCH_CLEAR_TARGET_TOKENS=50000`)
  - `arv2_research_compact_trigger_tokens: int = 150_000` (`CLUE_ARV2_RESEARCH_COMPACT_TRIGGER_TOKENS=150000`)
  - `arv2_research_compact_keep_messages: int = 40` (`CLUE_ARV2_RESEARCH_COMPACT_KEEP_MESSAGES=40`)

**Design (why not LangChain's `ClearToolUsesEdit`):** the stock edit recomputes "all but the
last N results" on every call. Once over its threshold, the cleared boundary moves one result
per round, which rewrites the prompt prefix and makes everything after it uncached ($2.00 vs
$0.53 per million on Grok 4.6). Ours keeps the cleared set **in graph state**. When the
effective size crosses `trigger_tokens`, it clears the oldest results until the effective size
is ≤ `target_tokens`, then leaves the set alone until the next crossing. The prefix therefore
stays byte-identical between crossings. Replaying the 604 real calls of 2026-10-06 with a reset
at 100k → 30k modelled −35% model cost (compaction simulation, 2026-10-07).

- **Not cleared:** reads of skills (`/.deepagent/skills/`, so the agent never has to re-read
  its instructions), any result inside the newest 2 rounds, and `finalize_turn` and refusal
  messages.
- **Placeholder** (text for founder review, Task 8):
  `"[Earlier result removed to keep the conversation small. Re-read {path} if you need it.]"`,
  or `"...Re-run the tool if you need it."` when there is no path.
- **The gutter:** the same middleware's `awrap_tool_call` strips the `cat -n` gutter
  (`^\s*\d+(\.\d+)?\t`) from `read_file` results under `/research/`, `/evidence/` and
  `/.deepagent/skills/`. Measured at 13% of read tokens. deepagents adds it unconditionally
  (`backends/utils.py:119`).
- **Compaction backstop:** for recipe ≥26 research turns, the runtime receives
  `CompactionSettings(0.90, 0.10, trigger_tokens=150_000, keep_messages=40, context_window=None)`
  instead of the 450k window rule.

- [ ] **Step 1: Failing unit tests.**

```python
# tests/agents/test_tool_result_clearing.py
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from clue_agents.tool_result_clearing import BatchedToolResultClearing, plan_clearing, strip_read_gutter


def _round(i, size):
    call = {"id": f"c{i}", "name": "read_file", "args": {"file_path": f"/research/operations/{i}/0.json"}}
    return [AIMessage("", tool_calls=[call]), ToolMessage("x" * size, tool_call_id=f"c{i}", name="read_file")]


def test_nothing_clears_under_the_trigger():
    msgs = [HumanMessage("go"), *_round(1, 4000)]
    assert plan_clearing(msgs, cleared=[], trigger=100_000, target=50_000, keep_paths=()) == []


def test_crossing_clears_oldest_down_to_target_and_skips_the_newest_two_rounds():
    msgs = [HumanMessage("go")] + sum((_round(i, 40_000) for i in range(12)), [])  # ~120k tokens
    cleared = plan_clearing(msgs, cleared=[], trigger=100_000, target=50_000, keep_paths=())
    assert cleared[0] == "c0" and "c10" not in cleared and "c11" not in cleared


def test_boundary_is_stable_between_crossings():
    msgs = [HumanMessage("go")] + sum((_round(i, 40_000) for i in range(12)), [])
    first = plan_clearing(msgs, cleared=[], trigger=100_000, target=50_000, keep_paths=())
    msgs += _round(12, 4_000)  # effective size still under trigger after the first clearing
    assert plan_clearing(msgs, cleared=first, trigger=100_000, target=50_000, keep_paths=()) == first


def test_skill_reads_are_never_cleared():
    msgs = [HumanMessage("go")]
    for i in range(12):
        call = {"id": f"s{i}", "name": "read_file", "args": {"file_path": f"/.deepagent/skills/a/v{i}/SKILL.md"}}
        msgs += [AIMessage("", tool_calls=[call]), ToolMessage("x" * 40_000, tool_call_id=f"s{i}", name="read_file")]
    assert plan_clearing(msgs, cleared=[], trigger=100_000, target=50_000, keep_paths=("/.deepagent/skills/",)) == []


def test_gutter_is_stripped_and_content_kept():
    assert strip_read_gutter("     1\t{\n     2\t  \"a\": 1\n    12.1\tcontinued") == "{\n  \"a\": 1\ncontinued"
```

- [ ] **Step 2: Run, expect `ModuleNotFoundError`.**

- [ ] **Step 3: Implement** `tool_result_clearing.py`.
  - `plan_clearing` is a pure function. It counts tokens with `langchain_core.messages.utils.count_tokens_approximately` on the effective messages, i.e. with already-cleared contents swapped for the placeholder. If the effective count is ≤ trigger, it returns `cleared` unchanged. Otherwise it walks ToolMessages oldest to newest, skipping:
    - ids already cleared
    - the newest 2 rounds
    - `keep_paths` reads
    - error or refusal results (`status == "error"`)

    It appends ids until the effective count is ≤ target, then returns the new list.
  - `BatchedToolResultClearing.before_model(state, runtime)` calls `plan_clearing` and, when the list changed, returns `{"cleared_tool_call_ids": new_list}`.
  - `awrap_model_call` applies the placeholder to messages whose `tool_call_id` is in `request.state["cleared_tool_call_ids"]`. It edits a deep copy only, so the checkpoint keeps the originals, as `ContextEditingMiddleware` does.
  - `awrap_tool_call` returns `ToolMessage(content=strip_read_gutter(...))` for `read_file` under the three prefixes.

- [ ] **Step 4: GREEN** on the unit file.

- [ ] **Step 5: Wire it (research only, recipe ≥26).**
  - In `bindings()`, put `BatchedToolResultClearing(...)` **first** in the returned `middleware` tuple when `at_least(self.scope, RECIPE_26)`. The tuple lands outer to the summariser (`runtime.py:661-665`), so the summariser counts the cleared context and acts only as a backstop.
  - At ~L1090, pass a research-specific `compaction_for`:
    `lambda model_id: CompactionSettings(0.90, 0.10, s.arv2_research_compact_trigger_tokens, s.arv2_research_compact_keep_messages, None)` when the recipe is ≥26, and the shared `compaction_for` otherwise.

- [ ] **Step 6: Wiring tests.** In `tests/agents/test_compaction.py`, add `test_research_recipe_26_stack_has_clearing_first_and_backstop_trigger`, reusing `_stack_of` (L82-96) to capture the final stack.
  - Assert `BatchedToolResultClearing` is present and `ClueSummarizationMiddleware.trigger == ("tokens", 150000)` for a recipe-26 research runtime.
  - Assert both are absent or unchanged for recipe 25 and for the Head of ABM.

  In `tests/agents/test_turn_budget.py`, run `test_an_agent_reaches_every_configured_round_and_ends_through_finalize` with the middleware added. The new `before_model` hook must not change the round count.

- [ ] **Step 7: Settings parity.** Add the four fields next to the existing `arv2_*` settings, and the four lines to `.env.example` under the ARV2 block with a one-line comment each. Add the same keys to the local `.env`.
  Run: `.venv/bin/python -m pytest -q tests/test_storage_settings_documented.py tests/arv2/test_settings.py -p no:cacheprovider`
  Expected: PASS. These are the env-parity guards.

- [ ] **Step 8: Commit** `"Research agents clear processed tool results in batches and compact at 150k (recipe 26)"`.

---

### Task 5: Close the grep → search_evidence → finalize trap (recipe ≥26)

**Files:**
- Modify: `platform/api/clue_api/arv2/quality_views.py` (`ResearchViewMount.agrep`)
- Modify: `platform/api/clue_api/arv2/quality_tools.py` (`SearchPathEvidenceTool.invoke`, ~L371)
- Test: `tests/arv2/test_quality_path_tools_db.py`, `tests/agents/test_finalize_contract.py`

**Interfaces:**
- Consumes `clue_toolbelt.PreconditionFailed`, which the invoker records as `journal.blocked`, not as `node.failed` (`invoker.py:308`). Blocked nodes are not in `unresolved_interaction_failures` (`executor.py:2593`) and do not spend the repair budget (`honest_read`, `agent_runtime_wiring.py:974-993`).

**Measured:** in production, 9 `search_evidence` calls failed with "Invalid source reference", and 7 of 12 jobs had their finish refused, each repaired at ~200k context.

- [ ] **Step 1: Failing tests.**
  - `test_search_on_a_research_view_is_a_precondition_refusal_not_a_failure` (DB, recipe 26): call `SearchPathEvidenceTool` with `source_path="/research/operations/<uuid>/0.json"`. Assert that `PreconditionFailed` is raised with a message naming `grep`.
  - `test_recipe_25_search_refusal_is_unchanged`: the same call at recipe 25 still raises `EvidenceUnavailable`.
  - `test_grep_finds_literal_lines_in_a_research_view` (DB, recipe 26): `research_backend(...).agrep("CMO", path="/research/operations/<id>/0.json")` returns `GrepResult(matches=[...])`, with line numbers matching the plain view from Task 2.
  - `test_a_blocked_search_does_not_stop_finalize`: in `tests/agents/test_finalize_contract.py`, using the executor fixtures from `tests/execution/test_executor.py:1311`, a blocked read node leaves `unresolved_interaction_failures(...) == ()`.

- [ ] **Step 2: Run, expect failures.**

- [ ] **Step 3: Implement.**
  - **Search tool.** In `SearchPathEvidenceTool.invoke`, when `at_least(self.scope, RECIPE_26)`:

```python
try:
    source = await resolve_source(conn, authority.grant, args.source_path)
except EvidenceUnavailable as exc:
    hint = (" search_evidence searches original sources under /evidence/; to search a "
            "research view use grep on that file, or read it.") if args.source_path.startswith("/research/") else ""
    raise PreconditionFailed(f"{exc}{hint}") from exc
```

  - **grep.** Add `ResearchViewMount.agrep` for recipe ≥26:
    - For a single file path under `/research/` or `/evidence/`, read the view exactly as `aread` would (whole, plain text). Return each line containing `pattern` (literal, case-sensitive, as deepagents' grep contract says) as `{"path", "line", "text"}`, capped at deepagents' own `grep_max_count` default.
    - For a directory path, return the existing guidance error. Framework tool errors never create governed failures.
    - Recipe <26 keeps today's refusal.

- [ ] **Step 4: GREEN**, plus a regression run:
  `.venv/bin/python -m pytest -q tests/arv2/test_quality_path_tools_db.py tests/arv2/test_quality_evidence_db.py tests/agents/test_finalize_contract.py tests/agents/test_governed_tool_feedback.py tests/execution/test_executor.py -p no:cacheprovider`

- [ ] **Step 5: Commit** `"A research-view search is a refusal, not a failure; grep works on research views (recipe 26)"`.

---

### Task 6: `save_dossier_section@2` / `update_dossier_findings@2`: visible statuses, per-finding refusal

**Files:**
- Modify: `platform/api/clue_api/arv2/dossier_json.py` (new `EntryReviewV2`, `EntryV2`, `SaveSectionInputV2`)
- Modify: `platform/api/clue_api/arv2/quality_json_dossier.py` (new `SaveDossierSectionToolV2`, `UpdateDossierFindingsToolV2`, `version = "2"`)
- Modify: `platform/api/clue_api/quality_research_wiring.py:244-249` (register the v2 classes; `make_default` stays on v1)
- Test: `tests/arv2/test_quality_json_dossier.py`, `tests/arv2/test_quality_json_dossier_db.py`

**Measured:** all 27 rejected saves of 2026-10-06 (56 individual errors) were
`findings.N.review: Field required`. LangChain rejected the whole call before our tool ran
(`agent_runtime_wiring.py:1031-1039`; ToolNode default handler). Every valid finding in the
section then had to be re-sent. The model never sees the allowed statuses, because
`EntryReview.status` is a plain `str`.

**Decision (no silent default):** a finding without a review is **not** given one. Assigning
`supported` would overstate; assigning `insufficient_context` would quietly demote real
findings out of page prose.

- [ ] **Step 1: Failing tests.**

```python
# tests/arv2/test_quality_json_dossier.py (additions)
from clue_api.arv2.dossier_json import EntryV2, SaveSectionInputV2


def test_v2_schema_shows_the_allowed_review_statuses():
    schema = SaveSectionInputV2.model_json_schema()
    review = schema["$defs"]["EntryReviewV2"]["properties"]["status"]
    assert set(review["enum"]) == {"supported", "duplicate", "wrong_entity", "insufficient_context", "potential_conflict"}


def test_v2_accepts_a_finding_without_review_at_the_argument_layer():
    SaveSectionInputV2.model_validate({"section": "s", "findings": [
        {"id": "F001", "topic": "t", "claim_type": "observation", "finding": "x", "source_paths": []}]})


def test_v1_schema_and_hash_are_unchanged():
    # recipe-25 profiles pin save_dossier_section@1 by input_schema_sha256 8278e906…
    from clue_api.arv2.quality_json_dossier import SaveDossierSectionTool
    assert SaveDossierSectionTool.version == "1"
```

  DB test `test_v2_saves_valid_findings_and_names_the_ones_missing_review`:
  - save F001 (with review), F002 (without) and F003 (with).
  - Assert the receipt is `{"saved": True, "entries": 2, "refused": [{"id": "F002", "reason": "review is required: add review.status (one of ...) and review.reason"}]}`.
  - Assert the stored section has exactly F001 and F003.
  - A follow-up `update_dossier_findings@2` with F002 plus a review appends it.

- [ ] **Step 2: Run, expect failures.**

- [ ] **Step 3: Implement.**
  - `EntryReviewV2(EntryReview)` overrides `status: Literal["supported","duplicate","wrong_entity","insufficient_context","potential_conflict"] = Field(description=...)`. It keeps the `contract` validator.
  - `EntryV2(Entry)` has `review: EntryReviewV2 | None = None`.
  - `SaveSectionInputV2` has `findings: list[EntryV2]`.
  - In `SaveDossierSectionToolV2.apply`, split the findings into `ready` (review present) and `refused` (review missing, each with the reason string above). Run `self.change_document` on `ready` only, then return the receipt with `refused`.
  - Other `ValueError`s keep today's `saved: False` path. `parse_json_dossier` and `finish_dossier` are unchanged: every stored entry still has a review.
  - Tool descriptions: v1 text, plus "Every finding needs review.status and review.reason; findings without one are not saved and are listed under refused." This is founder-review text, Task 8.

- [ ] **Step 4: GREEN**, plus the existing dossier suites: `tests/arv2/test_dossier_json.py tests/arv2/test_dossier_updates.py tests/arv2/test_quality_json_dossier.py tests/arv2/test_quality_json_dossier_db.py tests/arv2/test_dossier_import_db.py`.

- [ ] **Step 5: Commit** `"Dossier save v2 shows the review statuses and saves the valid findings of a mixed batch"`.

---

### Task 7: `acquire_research_evidence@2`: content-bearing receipts and an honest `empty` status

**Files:**
- Modify: `platform/api/clue_api/arv2/quality_provider_tools.py` (`AcquireResearchReceiptV2`, `AcquireResearchToolV2`, `version = "2"`)
- Modify: `platform/api/clue_api/quality_research_wiring.py` (register v2; the capabilities lookup keeps `"1"`)
- Test: `tests/arv2/test_quality_provider_db.py`, `tests/arv2/test_receipt_preview.py` (new)

**Interfaces:**
- Produces `receipt_preview(value: dict) -> tuple[list[ReceiptHit], int | None]`, where `ReceiptHit = {title, url, published, path, snippet}`.
- The snippet is ≤ 300 chars, there are at most 8 hits, and the serialized preview is ≤ 6 KiB, staying under the 12 KiB spill threshold (`execution.py:57`).
- The status gains `"empty"`. It is set when the body has no top-level error but `n_results == 0`, or `results == []`, or a deep `report` is empty.

**Measured:** each evidence call today returns two UUIDs and a path. The agent spends a round
reading `/research/operations/<id>/0.json` just to see what came back, and "completed" is
reported for empty searches and failed fetches.

- [ ] **Step 1: Failing unit tests** (`test_receipt_preview.py`) with three real body shapes copied from the code paths:
  - `search_web` `{result_ref, n_results, source_navigation:{sources:[...]}}`
  - `fetch_page` `{result_ref, results:[{url,title,text}], statuses:[...]}`
  - deep `{report, gaps, source_navigation}`

  Assert hit count, ≤300-char snippets, `path` taken from `source_navigation`, `empty` for `n_results=0`, and a total JSON size under 6 KiB for 40 large results.

- [ ] **Step 2: RED. Step 3: Implement** the v2 tool as a subclass that reuses v1's `invoke` and overrides only the receipt construction. Refactor v1's tail into `_settle(...) -> (value, unknown, refused, code)` so both versions share it. v1's output is byte-identical: assert this with its existing tests.

- [ ] **Step 4: GREEN**, plus `tests/arv2/test_quality_provider_db.py tests/arv2/test_research_receipt_spill_db.py tests/arv2/test_person_research_port_db.py`.

- [ ] **Step 5: Commit** `"Evidence receipt v2 carries a preview of what came back and says when it was empty"`.

---

### Task 8: **CHECKPOINT: founder review of agent-facing text** (no code)

Show the founder in chat, verbatim, then wait for approval before Task 9:
1. **Account prompt v26.** The diff against v25, limited to:
   - **Nominate first** (replaces L51 "After developing the account picture, select relevant candidates…"). New text: start the committee with AI Ark SMART role searches in the opening rounds; nominate as soon as a person is supported; keep researching the account in parallel; write the brief from what is known at nomination.
   - One line on the v2 receipts: "Each evidence call returns a preview; read the result path only when you need the full text."
   - One line on reading: "Research views return whole; read each file once rather than paging."
2. **Person prompt v26-person.** One line: the parent account dossier may not exist yet when you start; read `/research/parent-account-dossier.json` only if `/research/context.json` lists it.
3. **Tool descriptions:** `save_dossier_section@2`, `update_dossier_findings@2`, `acquire_research_evidence@2`.
4. **The cleared-result placeholder text** (Task 4).
5. **Error strings** from Task 5.

Record the approved text in the ledger. Any change requested goes back into Tasks 4–7 before Task 9.

---

### Task 9: Recipe 26 bundle (profiles, prompts, recipe, launch manifest, selector)

**Files:**
- Create: `platform/agents/catalog/research-quality/prompts/quality-account-research/v26/SYSTEM.md` and `prompts/quality-person-research/v26-person/SYSTEM.md` (the approved text)
- Create: `profiles/quality-account-research/v26/profile.yaml` and `profiles/quality-person-research/v26-person/profile.yaml`. Copy v25 and change:
  - the prompt version and sha
  - the tool pins `save_dossier_section`/`update_dossier_findings` → `'2'` and `acquire_research_evidence` → `'2'`, each with its new `input_schema_sha256`/`output_schema_sha256` computed from the models
- Create: `recipe-v26.json` (copy of v25 with `version: 26` and the v2 tool addresses) and `launch-v4-r26.json` (v25 resources, with v26 prompts, profiles and recipe, rehashed)
- Modify: `platform/api/clue_api/arv2/quality_catalog.py:14` `CURRENT_RECIPE_VERSION = 26`
- Modify: `platform/api/clue_api/quality_research_wiring.py:312-330`. Add a rung:
  `("v26-person" if person else "v26") if version >= 26 and role == AgentRole.ACCOUNT_RESEARCH else ...`
- Modify tests that assert 25: `tests/arv2/test_quality_owned_narrative.py:64`, `tests/arv2/test_quality_json_dossier.py:30`
- Test: `tests/arv2/test_recipe_26_bundle.py` (new)

- [ ] **Step 1: Failing test.**

```python
# tests/arv2/test_recipe_26_bundle.py
from clue_api.arv2.quality_catalog import CURRENT_RECIPE_VERSION, load_quality_resources


def test_recipe_26_loads_hash_verified_and_pins_the_v2_tools():
    assert CURRENT_RECIPE_VERSION == 26
    bundle = load_quality_resources("arv2-account", version=26)
    tools = {t["name"]: t["version"] for t in bundle.profile_tools()}
    assert tools["save_dossier_section"] == "2" and tools["acquire_research_evidence"] == "2"


def test_recipe_25_still_loads_byte_identical():
    load_quality_resources("arv2-account", version=25)  # raises if any v25 file changed
```

  Adapt `bundle.profile_tools()` to whatever accessor the bundle exposes. Read `quality_catalog.py` first, and ledger a ruling if it differs.

- [ ] **Step 2: RED. Step 3: Create the files**, computing the hashes with `hashlib.sha256(path.read_bytes()).hexdigest()`. Compute the schema hashes the same way `envelope.py:168-170` does. **Step 4: GREEN**, plus the full `tests/arv2/test_quality_*` set on the test DB.

- [ ] **Step 5: Commit** `"Quality recipe 26: v26 research profiles and prompts pin the waste-removal tools"`.

---

### Task 10: Contacts start at nomination; contact pages wait for the account import (recipe ≥26)

**Files:**
- Modify: `platform/api/clue_api/arv2/quality_person_release.py` (`ready_person_jobs` CASE; new `RELEASE_AT_NOMINATION = 26`)
- Modify: `platform/api/clue_api/arv2/account_research_driver.py` (`_write_pages` ~L1796; `person_task_instruction` flag ~L1407-1412)
- Modify: `platform/api/clue_api/arv2/quality_coverage.py` (~L93-120)
- Test: `tests/arv2/test_quality_person_release_db.py`, `tests/arv2/test_page_writer_hook.py`

**Behaviour (recipe ≥26):**
- **Release.** `ready_person_jobs` releases a `not_started` person whose parent is `in_progress` or terminal, without requiring the parent's import-ready reference. All the other guards are kept: privacy, suspended, same run and account.
- **Parent dossier advertised only when it exists.** `account_dossier_available` for the person's task instruction becomes "the parent import-ready reference exists *now*", not "recipe ≥18".
- **Contact page deferred.** In `_write_pages`, for a person with `parent_job_id` whose parent dossier is not imported yet: do not write the page. Set `result.finalization["contact_page"] = "deferred"`.
- **Coverage.** `coverage()` does not count the `contact` page as missing when the job's finalization says `deferred`, so the job settles `completed`.

- [ ] **Step 1: Failing DB tests.** Extend `test_ready_before_account_settlement_and_published_parent_view`, using the `child_job(..., version=26)` helper (L45):
  - (a) a recipe-26 child is ready while the parent is `in_progress` with **no** import.
  - (b) a recipe-25 child is still not ready (unchanged).
  - (c) a privacy-stopped recipe-26 child is never ready.

  In `tests/arv2/test_page_writer_hook.py`, add `test_recipe_26_person_defers_its_page_until_the_parent_imports`: with no parent import, `write_job_pages` is **not** called and the outcome stays `completed` with `contact_page == "deferred"`.

- [ ] **Step 2: RED. Step 3: Implement** the four changes behind `at_least(scope, RELEASE_AT_NOMINATION)`, plus the SQL CASE branch on `quality_recipe_version >= 26`. **Step 4: GREEN**, plus `tests/arv2/test_quality_person_release_db.py tests/arv2/test_page_writer_hook.py tests/arv2/test_quality_completion_db.py tests/arv2/test_generation_locking_db.py`.

- [ ] **Step 5: Commit** `"Recipe 26 people start at nomination; their pages wait for the account import"`.

---

### Task 11: One final page step per generation; skip when nothing changed (recipe ≥26)

**Files:**
- Modify: `platform/api/clue_api/arv2/quality_generation.py` (`pending_continuations`, L388-436)
- Modify: `platform/api/clue_api/arv2/page_writer_runtime.py` (`rewrite_account_pages`, L667-729; `write_job_pages`, L618)
- Modify: `platform/api/clue_api/arv2/account_research_driver.py` (`_rewrite_account`, L849-905)
- Test: `tests/arv2/test_quality_reconciliation_db.py`, `tests/arv2/test_page_writer_runtime_db.py`

**Measured:** in production, 8 account-page writer calls ran after the jobs finished (4 per
account), $1.10 in total, some from identical input. The gate opens when a child's dossier
import exists, so every later person result reopens it.

**Behaviour (recipe ≥26):**
- **Gate.** Drop the `arv2_research_import_ready` escape. Open only when every child of the generation is `completed`, `needs_review` or `suspended`, and is not privacy-stopped. Recipes 20–25 keep today's clause exactly.
- **Final step**, in `_rewrite_account`, before the account rewrite. Write the deferred contact pages: children with finalization `contact_page == "deferred"` and status `completed`. Use `asyncio.gather`, reusing `write_job_pages` with each child's scope. The parent is imported by now, or `_account_dossier_for_person` falls back to `{}` after catching the missing-import `ValueError`.
- **Skip when unchanged.** `write_job_pages(..., skip_if_unchanged=True)` computes `input_sha256 = sha256(system + "\x00" + user)` of the writer request. It compares this with the `input_sha256` stored in the newest `_WRITER_KIND` retained artifact for the job.
  - If they are equal, it runs `after_publish` (which settles the revision) without a model call, and returns `()`.
  - Store `input_sha256` in the retained writer JSON from now on.

- [ ] **Step 1: Failing DB tests.**
  - `test_recipe_26_gate_waits_for_every_person` (modelled on `test_batch_waits_for_all_imports_or_failures_and_scope_is_enforced`, L362): one child imported but still `in_progress` → no pending continuation. After it settles → exactly one pending continuation, covering the latest revision.
  - `test_recipe_25_gate_is_unchanged`: the same fixture at version 25 opens on import, as today.
  - `test_final_step_writes_deferred_contact_pages_then_the_account`.
  - `test_rewrite_with_identical_inputs_settles_without_a_model_call`: the fake model call count stays the same on the second rewrite.

- [ ] **Step 2: RED. Step 3: Implement. Step 4: GREEN**, plus `tests/arv2/test_quality_reconciliation_db.py tests/arv2/test_page_writer_runtime_db.py tests/arv2/test_person_attach_db.py tests/arv2/test_quality_generation_db.py`.

- [ ] **Step 5: Commit** `"Recipe 26 writes a generation's pages once after every person settles"`.

---

### Task 12: Measure it (comparison script + founder-triggered live run)

**Files:**
- Create: `scripts/compare_research_runs.py`
- Test: `tests/scripts/test_compare_research_runs.py`

`compare_research_runs.py --workspace ws_… --before <job ids|run id> --after <job ids|run id>`
prints a per-job and per-account table with:
- `cost_usd`, `model_rounds`, `tool_calls`, wall time
- rejected saves, finalize refusals, search_evidence failures (from Langfuse, via `CLUE_LANGFUSE_*`)
- page-writer calls per account
- findings per dossier section
- claim count by conclusion

The `--before` jobs are the 2026-10-06 production jobs, copied into `clue_dushanbe`. The script
uses read-only queries only.

- [ ] **Step 1: Test** the pure aggregation (`summarise(rows) -> dict`) on fixture rows. **Step 2: RED. Step 3: Implement. Step 4: GREEN. Step 5: Commit.**
- [ ] **Step 6: Live run (FOUNDER TRIGGERS; spends ~$12–15 per account).**
  - Start the dushanbe lane stack per DEV_STACK.md, with the sandbox image present and media on.
  - Relaunch Dialpad research at recipe 26 in the Clue HQ workspace.
  - Run the comparison.

  **Pass criteria:**
  - cost per account ≤ $15
  - zero rejected saves, zero finalize refusals caused by search_evidence
  - ≤ 2 account page-writer calls per account
  - contact jobs start < 2 min after nomination
  - seller-critical items still present: ABM/field hiring, new Head of Growth (May 2026), vacant CMO seat since Sept 2025, SVP Marketing hire (Feb 2026), named marketing leaders, the ABM manager's own posts
  - every page quote is a substring of its source

  Record the results in `_memory/`.

---

## Final: whole-branch review on Fable 5.1

After Task 11 (and Task 12 steps 1–5), produce the review package
(`review-package PLAN merge-base HEAD`). Dispatch **one** reviewer agent with
`model: "fable"`, given:
- the package
- this plan
- the two spec documents
- this plan's Review Focus list, verbatim
- the ledger's `Ruling:` lines

Critical and Important findings get one fix pass, each verified RED→GREEN with the suite rerun.
Minor findings go to the ledger as deferred. Report the rulings and deferred minors to the
founder.

## Deferred (explicitly not in this plan)

- **Media**: ffmpeg and podcast-page resolution. Founder: fix separately, keep media on.
- **Content decisions:** caps, personal depth, Miscellaneous; the v26 extract/judge pipeline;
  round budgets for judges.
- **Removing the unused `task` prompt.** It goes through the global harness profile, affects
  every governed agent, and is worth ~0.4%.
- **The worker-wide `_db_lock`** (speed, not cost).
- **The deepagents 0.7 upgrade.**
