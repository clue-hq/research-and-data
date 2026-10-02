# Lane 3 slice 4 — entity tags on traces — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every Langfuse trace that carried claims about an entity — the research job that wrote them and every chat turn whose read tools served them — is tagged with those entity ids (`entity:<id>` tags and an `entities` metadata list), so "every trace that carried contact X" is one query for the erasure lane and for an operator.

**Architecture:** One helper, `clue_obs.langfuse.tag_entities`, keeps a per-trace accumulator in a context variable and re-emits the whole set as an `entities.tagged` event inside `propagate_attributes` (the SDK merges nested propagation, so the outer trace name, session and tags survive). Three call sites: the research job (its subject at the start, everything `write_each` was asked to write at the end, each committee member as it is born), and the two ARV2 read tools that serve claims. Off is a no-op everywhere.

**Tech Stack:** as slice 3 (langfuse 4.15, opentelemetry-sdk 1.42, pytest).

**Spec:** `docs/superpowers/specs/2026-09-15-lane3-slice4-entity-tags-design.md` (D1, D2 ruled 2026-09-15). Parent: `docs/superpowers/specs/2026-09-14-telemetry-and-cost-observability-design.md` §5.3, §6, §9 slice 4.

## Global Constraints

- **Branch, commits, DB, spend, gates, shell, R11/R12, env parity:** exactly as plan 3a's Global Constraints (`docs/superpowers/plans/2026-09-15-lane3-slice3a-langfuse-foundation.md`). Alembic head is `b7193eb28363`; no migration in this slice. lint-imports 27 kept / 0 broken; mypy 4 pre-existing errors; never `make check` or a broad `pytest`; ambient env leaks stripped with `env -u`.
- **Off by default.** With Langfuse not installed `tag_entities` returns immediately; every call site's behaviour, rows, outputs and refusals are unchanged.
- **No network in tests.** `tests/_langfuse.py::langfuse_installed()` only.
- **R11.** Nothing under `subsystems/research/clue_research/**`; the ARV2 files under `platform/api/clue_api/arv2/**` are the only code touched besides `clue_obs.langfuse`.
- **Ids are strings.** `tag_entities` stringifies every id (`EntityId` is a UUID NewType); blanks are dropped; duplicates collapse; the emitted set is sorted.

## File structure

| File | Responsibility |
| --- | --- |
| `libs/clue-obs/clue_obs/langfuse.py` | **Modify.** `tag_entities`, the per-trace accumulator. |
| `tests/test_obs_langfuse.py` | **Modify.** Accumulator + event tests. |
| `platform/api/clue_api/arv2/account_research_tools.py` | **Modify.** `ToolRuntime.entities_touched`; `write_each` records the drafts' entities. |
| `platform/api/clue_api/arv2/account_research_agent.py` | **Modify.** Subject tag at the start; written entities at the ending. |
| `platform/api/clue_api/arv2/committee_step.py`, `account_research_launch.py` | **Modify.** Tag each member's contact id where its claims are written. |
| `tests/arv2/test_account_research_agent_langfuse.py`, `tests/arv2/test_committee_step_db.py` | **Modify.** |
| `platform/api/clue_api/arv2/read_tools.py` | **Modify.** The two read tools tag what they served. |
| `tests/arv2/test_read_tools_langfuse.py` | **Create.** |
| docs: parent note §6/§8/§9, lane index, slice 4 spec status, `_memory/2026-09-15-lane3-slice4-entity-tags.md`, `_memory/README.md` | **Modify/Create.** |

---

### Task 1: `tag_entities` — the per-trace accumulator and the `entities.tagged` event

**Files:**
- Modify: `libs/clue-obs/clue_obs/langfuse.py`
- Modify: `tests/test_obs_langfuse.py`

**Interfaces:**
- Produces: `tag_entities(entity_ids: Iterable[object]) -> None` (exported from `clue_obs.langfuse` and added to its `__all__`); `ENTITY_TAG_PREFIX = "entity:"`; `ENTITIES_METADATA_KEY = "entities"`.

- [ ] **Step 1: The failing tests**

Append to `tests/test_obs_langfuse.py` (add `tag_entities` to the `clue_obs.langfuse` import):

```python
def test_tag_entities_is_a_no_op_when_not_installed() -> None:
    tag_entities(["acc-1"])  # must not raise, must open nothing


def test_tag_entities_accumulates_per_trace_and_re_emits_the_whole_set() -> None:
    with langfuse_installed() as (exporter, _provider):
        with (
            propagate_trace(trace_name="head-of-abm.turn", session_id="t-1", tags=("head_of_abm",)),
            observation("turn", as_type="agent"),
        ):
            tag_entities(["acc-1", "", None])
            tag_entities(["con-9", "acc-1"])
        with observation("another-trace", as_type="agent"):
            tag_entities(["con-2"])
        spans = finished_spans(exporter)
    tagged = [s for s in spans if s.name == "entities.tagged"]
    assert len(tagged) == 3
    first, second, third = (_attrs(s) for s in tagged)
    assert first["langfuse.trace.tags"] == ("head_of_abm", "entity:acc-1")
    assert first["langfuse.trace.metadata.entities"] == "acc-1"
    assert second["langfuse.trace.tags"] == ("head_of_abm", "entity:acc-1", "entity:con-9")
    assert second["langfuse.trace.metadata.entities"] == "acc-1,con-9"
    assert second["langfuse.trace.name"] == "head-of-abm.turn"
    assert second["session.id"] == "t-1"
    assert json.loads(second["langfuse.observation.output"]) == {"entities": ["acc-1", "con-9"]}
    # A different trace starts a fresh set.
    assert third["langfuse.trace.metadata.entities"] == "con-2"
    assert third["langfuse.trace.tags"] == ("entity:con-2",)
    turn = next(s for s in tagged if _attrs(s)["langfuse.trace.metadata.entities"] == "acc-1")
    assert format(turn.context.trace_id, "032x") != format(tagged[2].context.trace_id, "032x")


def test_tag_entities_with_no_current_trace_opens_nothing() -> None:
    with langfuse_installed() as (exporter, _provider):
        tag_entities(["acc-1"])  # no span is current: nowhere to tag
        spans = finished_spans(exporter)
    assert [s.name for s in spans] == []
```

(`json` is already imported in that file; if not, add it.)

- [ ] **Step 2: Run to see them fail**

Run: `uv run pytest tests/test_obs_langfuse.py -q` → FAIL (`ImportError: tag_entities`).

- [ ] **Step 3: Implement**

In `clue_obs/langfuse.py` add to the imports `from collections.abc import Iterable` (extend the existing `collections.abc` import) and `from contextvars import ContextVar`; add to `__all__`: `"ENTITIES_METADATA_KEY"`, `"ENTITY_TAG_PREFIX"`, `"tag_entities"`. After the `propagate_trace` section:

```python
# --- entity tags (lane 3 slice 4, R5) ------------------------------------------------------

#: The trace tag naming one entity a trace carried claims about: ``entity:<id>``.
ENTITY_TAG_PREFIX = "entity:"
#: The trace metadata key holding the same ids, sorted and comma-joined (the "contains" filter).
ENTITIES_METADATA_KEY = "entities"

#: The entities tagged so far on the current trace: ``(trace_id, ids)``. Set, never reset, so it
#: outlives the ``propagate_trace`` block that opened the trace and reaches later work in the
#: same task (the research driver's committee step after the agent). A different current trace
#: starts a fresh set.
_entities: ContextVar[tuple[str, set[str]] | None] = ContextVar("clue_langfuse_entities", default=None)


def tag_entities(entity_ids: Iterable[object]) -> None:
    """Tag the current trace with the entities it wrote or served.

    The whole accumulated set is re-emitted on every call (as ``entity:<id>`` tags and as the
    ``entities`` metadata list) inside the SDK's own attribute propagation, so the trace ends up
    complete whether Langfuse merges trace attributes by union or by last writer, and the outer
    trace name, session, user and tags stay on the emitted span. A no-op when Langfuse is not
    installed, when no span is current, or when nothing is left after dropping blanks.
    """
    if _client is None:
        return
    ids = {str(item).strip() for item in entity_ids if item is not None and str(item).strip()}
    if not ids:
        return
    current = current_ids()
    if current is None:
        return
    held = _entities.get()
    seen = set(held[1]) if held is not None and held[0] == current.trace_id else set()
    seen |= ids
    _entities.set((current.trace_id, seen))
    ordered = sorted(seen)
    from langfuse import propagate_attributes

    with propagate_attributes(
        tags=[f"{ENTITY_TAG_PREFIX}{entity}" for entity in ordered],
        metadata={ENTITIES_METADATA_KEY: ",".join(ordered)},
    ):
        _client.create_event(name="entities.tagged", output={ENTITIES_METADATA_KEY: ordered})
```

`current_ids()` returns `None` when no span is current (its trace id check), which is the "opens nothing" case. If the SDK's `propagate_attributes` refuses an empty `tags` list or a metadata value type, adapt (the ids are strings; the list is never empty here).

- [ ] **Step 4: Run to see them pass**

Run: `uv run pytest tests/test_obs_langfuse.py -q` → PASS. If the tag tuple order differs from the assertion (the SDK may sort or dedupe), match the assertion to the SDK's actual order and say so in the report — the set must be complete, the order is the SDK's.

- [ ] **Step 5: Gates and commit**

ruff; mypy (4 baseline); lint-imports (27/0 — `clue_obs.langfuse -> langfuse` is already exempt).

```bash
git add libs/clue-obs/clue_obs/langfuse.py tests/test_obs_langfuse.py
git commit -m "feat(obs): tag_entities — the current trace accumulates the entities it carried, re-emitted as entity:<id> tags and an entities metadata list (lane 3 slice 4)"
```

---

### Task 2: The research job tags its subject, what it wrote, and each committee member

**Files:**
- Modify: `platform/api/clue_api/arv2/account_research_tools.py` (`ToolRuntime.__init__` ~line 336–392; `write_each` ~line 512)
- Modify: `platform/api/clue_api/arv2/account_research_agent.py` (`run_account_agent` ~line 400–450)
- Modify: `platform/api/clue_api/arv2/committee_step.py` (~line 222, the `if inserted:` write), `platform/api/clue_api/arv2/account_research_launch.py` (~line 903, the `committee_member_claims` write)
- Modify: `tests/arv2/test_account_research_agent_langfuse.py`, `tests/arv2/test_committee_step_db.py`

**Interfaces:**
- Consumes: `tag_entities` (Task 1); `ClaimDraft.entity_id`; `JobScope.account_id/contact_id`.
- Produces: `ToolRuntime.entities_touched: set[str]`.

- [ ] **Step 1: The failing tests**

In `tests/arv2/test_account_research_agent_langfuse.py` add (imports: `from clue_obs.langfuse import ENTITIES_METADATA_KEY`; reuse `SCOPE`, `_runtime`, `_ScriptedModel`, `_finalizing_tool`, `_drive`, `_run`, `_call`, `_priced`, `_attrs`):

```python
def _tagged_sets(spans: Any) -> list[str]:
    return [
        _attrs(s)[f"langfuse.trace.metadata.{ENTITIES_METADATA_KEY}"]
        for s in spans
        if s.name == "entities.tagged"
    ]


def test_the_job_tags_its_subject_and_every_entity_it_wrote() -> None:
    runtime = _runtime()
    written = StructuredTool.from_function(
        coroutine=_writing(runtime, "con-77"),
        name="write_claims",
        description="records an entity the job wrote about",
        args_schema=_NoArgs,
    )

    def respond(messages: Any) -> AIMessage:
        if any(getattr(m, "name", None) == "finalize_research" for m in messages):
            return _priced(AIMessage(content="done"))
        if any(getattr(m, "name", None) == "write_claims" for m in messages):
            return _priced(AIMessage(content="", tool_calls=[_call("finalize_research", 2)]))
        return _priced(AIMessage(content="", tool_calls=[_call("write_claims", 1)]))

    with langfuse_installed() as (exporter, _provider):
        outcome = _run(_drive(_ScriptedModel(respond), [written, _finalizing_tool(runtime)], runtime))
        spans = finished_spans(exporter)
    assert outcome.reason == "finalized"
    sets = _tagged_sets(spans)
    assert sets[0] == str(SCOPE.account_id)  # the subject, first thing in the trace
    assert sets[-1] == ",".join(sorted({str(SCOPE.account_id), "con-77"}))  # the ending
    job = next(s for s in spans if s.name == "arv2.account_research")
    last = next(s for s in spans if s.name == "entities.tagged" and _attrs(s)[f"langfuse.trace.metadata.{ENTITIES_METADATA_KEY}"] == sets[-1])
    assert format(last.context.trace_id, "032x") == format(job.context.trace_id, "032x")
    assert f"entity:{SCOPE.account_id}" in _attrs(last)["langfuse.trace.tags"]


def _writing(runtime: Any, entity: str) -> Any:
    async def call() -> str:
        runtime.tool_calls += 1
        runtime.entities_touched.add(entity)  # what write_each records for every draft it writes
        return json.dumps({"ok": True})

    return call
```

(`_NoArgs` and `StructuredTool` come from the existing agent test module; import them the same way the file imports the other helpers, or define `_NoArgs(BaseModel)` locally.) Also add a `write_each` unit test to the same file:

```python
def test_write_each_records_every_drafts_entity_before_writing() -> None:
    runtime = _runtime()

    class _Writer:
        async def write(self, conn: Any, draft: Any) -> Any:
            if draft.field_key.endswith("bad"):
                raise RuntimeError("store refused")
            return WriteReceipt(claim_id=uuid4(), field_key=draft.field_key)  # match the real ctor

    runtime._writer = _Writer()  # type: ignore[attr-defined]
    drafts = [_draft(runtime, "core.industry", "acc-1"), _draft(runtime, "core.bad", "con-2")]
    results = _run(runtime.write_each(drafts))
    assert len(results) == 2
    assert runtime.entities_touched == {"acc-1", "con-2"}
```

with `_draft(runtime, field_key, entity_id)` building a `ClaimDraft` from `clue_api.arv2.claim_writer` (read its dataclass: `entity_id`, `entity_type`, `field_key`, `value_json`, `extraction_method`, `run_id`, `research_mode`, `workspace_id`; take the enum values the existing tests use — `grep -n "ClaimDraft(" tests/arv2/*.py` shows a literal to copy) and `WriteReceipt`'s real constructor (`grep -n "class WriteReceipt" -A 8 platform/api/clue_api/arv2/*.py`).

In `tests/arv2/test_committee_step_db.py`, find the test that inserts a confirmed member (the one asserting the person job row and the three claims) and add a sibling test that runs the same scenario inside `langfuse_installed()` under `observation("job", as_type="agent")` and asserts one `entities.tagged` span whose `entities` metadata contains the inserted member's contact id (read the contact id back the way that test does). Lane-DB test: run with the DB preamble.

- [ ] **Step 2: Run to see them fail**

Run: `env -u CLUE_OPENROUTER_API_KEY -u CLUE_EXA_API_KEY uv run pytest tests/arv2/test_account_research_agent_langfuse.py -q` → FAIL (`entities_touched` missing / no tagged spans).

- [ ] **Step 3: Implement**

`account_research_tools.py`:
- `ToolRuntime.__init__`: after `self.compliance_log = []` add
  ```python
        #: Every entity this job asked the writer to write a claim about (lane 3 slice 4): the
        #: ending tags the job's trace with them, so "which traces carried contact X" is a query.
        self.entities_touched: set[str] = set()
  ```
- `write_each`: at the top of the `for draft in self.compliance_pass(drafts):` body, before the `try`, add `self.entities_touched.add(str(draft.entity_id))`.

`account_research_agent.py` (`from clue_obs.langfuse import ... tag_entities`):
- right after the `observation("arv2.account_research", as_type="agent", ...) as current,` block opens (first statement inside the `with`): `tag_entities([scope.account_id, scope.contact_id])` (the helper drops `None`).
- after `_report_ending(outcome)`: `tag_entities(runtime.entities_touched)`.

`committee_step.py` (`from clue_obs.langfuse import tag_entities`): inside `if inserted:`, before the `for draft in committee_member_claims(...)` loop: `tag_entities([contact_id])`.

`account_research_launch.py` (same import): before its `for draft in committee_member_claims(...)` loop (~line 903): `tag_entities([contact_id])`.

- [ ] **Step 4: Run to see them pass**

Run: `env -u CLUE_OPENROUTER_API_KEY -u CLUE_EXA_API_KEY uv run pytest tests/arv2/test_account_research_agent_langfuse.py tests/arv2/test_account_research_agent.py -q` → PASS. Lane DB: `env -u CLUE_CHAT_REASONING_TRACE_MODE uv run pytest tests/arv2/test_committee_step_db.py tests/arv2/test_account_research_launch_db.py -q` → PASS.

- [ ] **Step 5: Gates and commit**

ruff; mypy (4 baseline); lint-imports (27/0).

```bash
git add platform/api/clue_api/arv2/account_research_tools.py platform/api/clue_api/arv2/account_research_agent.py platform/api/clue_api/arv2/committee_step.py platform/api/clue_api/arv2/account_research_launch.py tests/arv2/test_account_research_agent_langfuse.py tests/arv2/test_committee_step_db.py
git commit -m "feat(arv2): the research job's trace is tagged with its subject, every entity it wrote about, and each committee member as it is born (lane 3 slice 4)"
```

---

### Task 3: The read tools tag what they served

**Files:**
- Modify: `platform/api/clue_api/arv2/read_tools.py` (`ReadAccountResearchTool.invoke` ~line 1492; `ReadClaimsTool.invoke` ~line 1852)
- Create: `tests/arv2/test_read_tools_langfuse.py`

**Interfaces:**
- Consumes: `tag_entities` (Task 1); `AccountResearch`, `ClaimsQueryPage`, `Arv2ReadRefused`.

- [ ] **Step 1: The failing test**

`tests/arv2/test_read_tools_langfuse.py`:

```python
"""Lane 3 slice 4, Task 3: a turn's read tools tag the turn's trace with the entity they served."""

from __future__ import annotations

from typing import Any

import pytest

from clue_api.arv2.read_tools import (
    AccountResearch,
    Arv2ReadRefused,
    ClaimsQueryPage,
    ReadAccountResearchTool,
    ReadClaimsTool,
)
from clue_core import new_operation_id
from clue_obs.langfuse import ENTITIES_METADATA_KEY, observation
from clue_toolbelt import PreconditionFailed, ToolContext
from tests._langfuse import finished_spans, langfuse_installed
from tests.db.conftest import run_async


class _Service:
    def __init__(self, *, refuse: bool = False) -> None:
        self._refuse = refuse

    async def read_account_research(self, **kwargs: Any) -> AccountResearch:
        if self._refuse:
            raise Arv2ReadRefused("account_not_in_workspace", "not yours")
        return AccountResearch(
            account_entity_id=kwargs["account_entity_id"], account_name="Acme", section="claims",
            overview=(), claims=(), truncated=False, excluded={}, offset=0, next_offset=None, prefixes={},
        )

    async def read_claims(self, **kwargs: Any) -> ClaimsQueryPage:
        if self._refuse:
            raise Arv2ReadRefused("entity_not_in_workspace", "not yours")
        return ClaimsQueryPage(
            entity_id=kwargs["entity_id"], entity_type="contact", claims=(), excluded={},
            prefixes={}, offset=0, next_offset=None, truncated=False,
        )


class _NullConnFactory:
    def __call__(self) -> Any:
        raise AssertionError("the fake service opens no connection")


def _ctx() -> ToolContext:
    return ToolContext(workspace_id="ws-1", actor="agent", conn_factory=_NullConnFactory(), operation_id=new_operation_id())  # type: ignore[arg-type]


def _tagged(spans: Any) -> list[str]:
    return [dict(s.attributes or {})[f"langfuse.trace.metadata.{ENTITIES_METADATA_KEY}"] for s in spans if s.name == "entities.tagged"]


def test_off_the_tools_answer_as_before() -> None:
    result = run_async(ReadClaimsTool(_Service()).invoke(ReadClaimsTool.input_model(entity_id="con-1"), _ctx()))
    assert result.references["entity_id"] == "con-1"


def test_read_claims_tags_the_entity_it_served() -> None:
    with langfuse_installed() as (exporter, _provider):
        with observation("turn", as_type="agent"):
            run_async(ReadClaimsTool(_Service()).invoke(ReadClaimsTool.input_model(entity_id="con-1"), _ctx()))
        spans = finished_spans(exporter)
    assert _tagged(spans) == ["con-1"]


def test_read_account_research_tags_the_account_and_a_turn_accumulates() -> None:
    with langfuse_installed() as (exporter, _provider):
        with observation("turn", as_type="agent"):
            run_async(ReadAccountResearchTool(_Service()).invoke(ReadAccountResearchTool.input_model(account_entity_id="acc-1", section="claims"), _ctx()))
            run_async(ReadClaimsTool(_Service()).invoke(ReadClaimsTool.input_model(entity_id="con-1"), _ctx()))
        spans = finished_spans(exporter)
    assert _tagged(spans) == ["acc-1", "acc-1,con-1"]


def test_a_refused_read_tags_nothing() -> None:
    with langfuse_installed() as (exporter, _provider):
        with observation("turn", as_type="agent"):
            with pytest.raises(PreconditionFailed):
                run_async(ReadClaimsTool(_Service(refuse=True)).invoke(ReadClaimsTool.input_model(entity_id="con-1"), _ctx()))
        spans = finished_spans(exporter)
    assert _tagged(spans) == []
```

Check `Arv2ReadRefused`'s constructor (`read_tools.py:131`) and the two input models' required fields (`ReadClaimsInput` ~1767, `ReadAccountResearchInput` ~1408) and adjust the literals; keep the assertions.

- [ ] **Step 2: Run to see it fail** → the off test passes; the rest FAIL (no tagged spans).

- [ ] **Step 3: Implement**

In `read_tools.py` add `from clue_obs.langfuse import tag_entities`. In `ReadAccountResearchTool.invoke`, after the `try/except` that obtains `research` and before building `output`: `tag_entities([research.account_entity_id])`. In `ReadClaimsTool.invoke`, after `page` is obtained: `tag_entities([page.entity_id])`. Nothing else changes (a refusal raises before the tag).

- [ ] **Step 4: Run to see it pass**

Run: `uv run pytest tests/arv2/test_read_tools_langfuse.py -q` → PASS; lane DB: `env -u CLUE_CHAT_REASONING_TRACE_MODE uv run pytest tests/arv2/test_read_tools_db.py -q` → PASS (unchanged behaviour with Langfuse off).

- [ ] **Step 5: Gates and commit**

ruff; mypy (4 baseline); lint-imports (27/0).

```bash
git add platform/api/clue_api/arv2/read_tools.py tests/arv2/test_read_tools_langfuse.py
git commit -m "feat(arv2): read_account_research and read_claims tag the turn's trace with the entity they served (lane 3 slice 4)"
```

---

### Task 4: Docs and the memory note

**Files:**
- Modify: `docs/superpowers/specs/2026-09-14-telemetry-and-cost-observability-design.md` (§6 "What lane 3 does" paragraph; §8 table; §9 item 4)
- Modify: `docs/superpowers/plans/2026-09-13-lane-plan-index.md` (row 4)
- Modify: `docs/superpowers/specs/2026-09-15-lane3-slice4-entity-tags-design.md` (status line)
- Create: `_memory/2026-09-15-lane3-slice4-entity-tags.md`; Modify: `_memory/README.md`

- [ ] **Step 1: §6** — after the sentence ending `one Langfuse query by metadata.` add: `Shipped 2026-09-15 (slice 4): the query is *traces with tag `entity:<id>`* (or metadata `entities` contains `<id>`); the job's trace carries its subject, every entity it wrote about and each committee member; a turn's trace carries every entity `read_account_research` / `read_claims` served.`
- [ ] **Step 2: §8** — add a row: `| Non-graph gateway completions (value narrative, exit judge, Stage-0 extractor, judges) and the old lane's Sumble / Exa tier-3 provider calls on a Postgres ledger | founder ruling 2026-09-15: leave as is; they are visible in Langfuse with settled cost (gateway path) or as httpx spans (old-lane resolvers); the cost read does not see them |`.
- [ ] **Step 3: §9 item 4** — replace with `4. **Entity tagging on traces — DONE 2026-09-15** (design: `2026-09-15-lane3-slice4-entity-tags-design.md`): `clue_obs.langfuse.tag_entities`; the job tags its subject, its writes and its committee members; the two read tools tag what they served. The Langfuse deletion step is the erasure lane's (R13).`
- [ ] **Step 4: lane index** — row `4`: `| 4 | `2026-09-15-lane3-slice4-entity-tags.md` | entity tags on traces: the job's subject/writes/members, the read tools' served entities; the erasure query | 3b |`.
- [ ] **Step 5: spec status** — `**Status:** approved in chat 2026-09-15 (D1 tags plus metadata; D2 ...); executed 2026-09-15.`
- [ ] **Step 6: memory note** — `_memory/2026-09-15-lane3-slice4-entity-tags.md` in the slice 3 note's style: what shipped (commits), D1/D2, the rulings from the SDD ledger, the erasure query, the audit findings of 2026-09-15 (what is and is not measured; the leave-as-is ruling; the owed Langfuse retention step), verification, and the owed live proof. README index line under "Topic notes", first.
- [ ] **Step 7: Commit**

```bash
git add docs/superpowers/specs/2026-09-14-telemetry-and-cost-observability-design.md docs/superpowers/plans/2026-09-13-lane-plan-index.md docs/superpowers/specs/2026-09-15-lane3-slice4-entity-tags-design.md _memory/2026-09-15-lane3-slice4-entity-tags.md _memory/README.md
git commit -m "docs(memory): lane 3 slice 4 — entity tags on traces; the erasure query; the coverage audit and the leave-as-is ruling"
```

## Self-review

- Spec §3.1 → Task 1; §3.2 → Task 2; §3.3 → Task 3; §3.4 → Task 4; §5 tests → Tasks 1–3.
- Names used consistently: `tag_entities`, `ENTITIES_METADATA_KEY`, `ENTITY_TAG_PREFIX`, `ToolRuntime.entities_touched`.
- The `WriteReceipt` constructor and `ClaimDraft` literal in Task 2's unit test are read from the code by the implementer (called out); everything else is literal.
