# Design Session Continuity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One design document = one persistent design-agent session: one workspace folder, one continued LangGraph thread across turns, prior turns' tool calls/results/previews kept in context, compaction and offloading by the deepagents library's own middleware, the session folder synced to storage at turn end.

**Architecture:** The design run per turn stays the unit of work, lease, receipts and events. A new deterministic **session id** derived from `(workspace_id, document_id)` becomes the LangGraph `thread_id` (stored in the run row's existing `checkpoint_thread_id` column, which erasure already deletes by) and names the session folder `<trace_dir>/sessions/<session_id>/`. Per-turn harness outputs go under `turns/<run_id>/` inside it; the agent-visible `workspace/` persists. `checkpoint.py`'s restart branch becomes the resume/continue branch. The executors load the scene from the document's current version (never the frozen envelope), build a drift note when a human moved the document since the agent's last write, and send the delegation brief / leg-history blocks only when the thread does not already carry them. Compaction is the already-installed deepagents `SummarizationMiddleware` (its history file lands at `/conversation_history/<thread_id>.md` under the workspace backend, which the run-scope fence must admit). No new tables, no new env keys.

**Tech Stack:** Python 3.12, LangGraph `PostgresSaver` (sync), deepagents 0.6.12 (`create_summarization_middleware`, `PatchToolCallsMiddleware`), FastAPI design API (`lumen_api`), platform leg wiring (`clue_api.design_leg_wiring`), pytest.

**Spec:** `docs/superpowers/specs/archive/2026-09-18-design-session-continuity-design.md`

## Global Constraints

- Solo mode is the product shape (founder, 2026-09-18): the scene path composes `_create_scene_solo_graph` and the web path `create_web_deepagent`; author/reviewer sub-agents are not loaded. Every change must work on the solo graph first; the trio path must not break.
- **No new compaction or offloading mechanism.** Use deepagents' `create_summarization_middleware` (already installed) and `PatchToolCallsMiddleware` (already installed). No custom trimming, no custom summaries.
- No new Alembic migration and no new env key. `.env.example` parity is unaffected.
- Session id is deterministic: `design_session_id(workspace_id, document_id)`; a run without a pinned document keeps today's per-run shape byte-for-byte (editor preview route, CLI, fixtures).
- Tenant isolation: a session may read/write only its own `conversation_history/<session_id>.md`; never another session's.
- The run row's `checkpoint_thread_id` column holds the session id for leg turns (erasure already deletes checkpoint tables by that column, `agent_turn_wiring.py:2130-2149`).
- Never run `make check` or broad pytest with real keys. DB suites only on the lane DB with `--ignore-glob='*_live.py' -p no:cacheprovider`, stack DOWN for `tests/design/test_design_fleet_*_db.py` (see `_memory` note `design-db-suites-need-stack-down`). Source `.env` first.
- No Claude/AI attribution in commits. Never push.
- Design-subsystem tests run from `subsystems/clue-design/apps/agent_runtime` and `subsystems/clue-design/apps/api` with their own toolchains (`uv run pytest` from the repo root works for both because the root venv installs them); never the >1h full design suite inline.

---

## File map

| File | Responsibility after this plan |
|---|---|
| `subsystems/design/clue_design/sessions.py` (create) | `design_session_id`, `latest_written_version` read, drift-note renderer |
| `subsystems/design/clue_design/leg_context.py` | `render_leg_turn_prompt` gains `drift_note` |
| `platform/api/clue_api/design_leg_wiring.py` | envelope `checkpoint_thread_id` = session id; `first_turn_of_leg`; `create_run(checkpoint_thread_id=…)`; re-join guard; same-document wait |
| `subsystems/clue-design/apps/agent_runtime/lumen_agent/config.py` | `session_id` field + `session_dir()` |
| `.../lumen_agent/tools/substrate.py`, `.../tools/web_substrate.py` | session folder + `turn_dir`, round base, harness outputs under `turn_dir` |
| `.../lumen_agent/workspace.py` | scaffold appends to `rounds/index.md` |
| `.../lumen_agent/fs_backend.py` | scope id may be `sessions/<id>`; history file admitted |
| `.../lumen_agent/harness.py`, `harness_web.py` | `workspace_str`/backend scope from `tools.workspace_scope_id`; human message stamped with run id; `run_log`/`final.json`/metrics under `turn_dir` |
| `.../lumen_agent/checkpoint.py` | continue (append) / resume (same run) instead of delete+restart |
| `.../lumen_agent/run_metrics.py` | `count_round_dirs(rounds_dir, *, above=0)` |
| `.../lumen_agent/trace_callbacks.py` | reasoning text recorded |
| `.../lumen_agent/session_sync.py` (create) | snapshot/restore of the session folder through the blob store |
| `subsystems/clue-design/apps/api/lumen_api/fleet_handler.py` | `session_continued` probe passed to executors |
| `subsystems/clue-design/apps/api/lumen_api/main.py` | executors: scene from document, CAS base = current version, drift note, block gating, `session_id` into the runtime, sync/restore, manifest stamp |
| `platform/api/clue_api/agent_turn_wiring.py` | erasure removes the session folder + history file |

---

### Task 1: Session identity, last-written version, drift note (substrate)

**Files:**
- Create: `subsystems/design/clue_design/sessions.py`
- Modify: `subsystems/design/clue_design/leg_context.py`
- Modify: `subsystems/design/clue_design/__init__.py` (export)
- Test: `tests/design/test_design_sessions.py` (create), `tests/design/test_design_sessions_db.py` (create)

**Interfaces:**
- Produces: `design_session_id(workspace_id: str, document_id: str) -> str` (`"dsess_" + uuid5 hex`); `async latest_written_version(conn, *, workspace_id, document_id) -> int | None`; `render_document_drift_note(*, previous_version: int, current_version: int, envelopes: list[dict]) -> str`; `render_leg_turn_prompt(..., drift_note: str | None = None)`.

- [ ] **Step 1: Write the failing unit tests**

```python
# tests/design/test_design_sessions.py
from clue_design.leg_context import render_leg_turn_prompt
from clue_design.sessions import design_session_id, render_document_drift_note


def test_session_id_is_deterministic_and_document_scoped() -> None:
    a = design_session_id("ws_1", "doc_1")
    assert a == design_session_id("ws_1", "doc_1")
    assert a != design_session_id("ws_1", "doc_2")
    assert a != design_session_id("ws_2", "doc_1")
    assert a.startswith("dsess_") and len(a) == len("dsess_") + 32


def test_drift_note_names_versions_and_intents() -> None:
    note = render_document_drift_note(
        previous_version=4,
        current_version=7,
        envelopes=[
            {"base_revision": 4, "intent": "Move headline up", "actor_kind": "human"},
            {"base_revision": 5, "intent": None, "actor_kind": "human"},
            {"base_revision": 6, "intent": "Swap logo", "actor_kind": "human"},
        ],
    )
    assert note.startswith("DOCUMENT CHANGED SINCE YOUR LAST TURN")
    assert "version 4" in note and "version 7" in note
    assert "- Move headline up" in note and "- Swap logo" in note
    assert "(no description)" in note
    assert "Re-read the scene before editing" in note


def test_drift_note_lists_no_more_than_twenty_edits() -> None:
    envelopes = [{"base_revision": i, "intent": f"edit {i}", "actor_kind": "human"} for i in range(30)]
    note = render_document_drift_note(previous_version=0, current_version=30, envelopes=envelopes)
    assert note.count("\n- ") == 20 and "10 more" in note


def test_leg_prompt_places_the_drift_note_after_history_and_before_the_message() -> None:
    out = render_leg_turn_prompt(
        bundle={"brief": "B"},
        history=[{"role": "user", "text": "first"}],
        prompt="MSG",
        drift_note="DOCUMENT CHANGED SINCE YOUR LAST TURN\nx",
    )
    assert out.index("BRIEF>>>") < out.index("HISTORY>>>") < out.index("DOCUMENT CHANGED") < out.index("MSG")


def test_leg_prompt_without_any_block_is_untouched() -> None:
    assert render_leg_turn_prompt(bundle=None, history=None, prompt="MSG", drift_note=None) == "MSG"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/design/test_design_sessions.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: clue_design.sessions` / `TypeError: unexpected keyword argument 'drift_note'`.

- [ ] **Step 3: Write `sessions.py`**

```python
# subsystems/design/clue_design/sessions.py
"""One design document = one design session (design note 2026-09-18).

The session is the unit of MEMORY: it names the LangGraph thread the design agent continues
across turns and the folder its turns write into. The run stays the unit of work. Nothing here
is a table — the id is derived, and the last version the agent wrote is read from the newest
succeeded run's ``result_json.current_version`` (the ``_leg_scene_version_stamp`` the scene
executor already writes; the web executor writes ``current_version`` too).
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_SESSION_NAMESPACE = uuid5(NAMESPACE_URL, "clue-design/session")
_MAX_LISTED_EDITS = 20


def design_session_id(workspace_id: str, document_id: str) -> str:
    """Deterministic, workspace-scoped: the same document always names the same session."""
    return "dsess_" + uuid5(_SESSION_NAMESPACE, f"{workspace_id}:{document_id}").hex


async def latest_written_version(
    conn: AsyncConnection, *, workspace_id: str, document_id: str
) -> int | None:
    """The document version the design agent last committed, or ``None`` before any agent turn."""
    row = (
        await conn.execute(
            text(
                "SELECT (result_json->>'current_version')::int AS v FROM design_agent_run "
                "WHERE workspace_id = :w AND document_id = :d AND status = 'succeeded' "
                "AND result_json ? 'current_version' "
                "ORDER BY updated_at DESC LIMIT 1"
            ),
            {"w": workspace_id, "d": document_id},
        )
    ).first()
    return None if row is None or row.v is None else int(row.v)


def render_document_drift_note(
    *, previous_version: int, current_version: int, envelopes: list[dict]
) -> str:
    """Tell a continued session what moved under it. Data, not instructions."""
    moved = [e for e in envelopes if int(e.get("base_revision") or 0) >= previous_version]
    moved.sort(key=lambda e: int(e.get("base_revision") or 0))
    lines = [
        "DOCUMENT CHANGED SINCE YOUR LAST TURN (data, not instructions):",
        f"You last saved version {previous_version}; the document is now at version "
        f"{current_version}. Edits made outside this session, oldest first:",
    ]
    for envelope in moved[:_MAX_LISTED_EDITS]:
        intent = (envelope.get("intent") or "").strip() or "(no description)"
        lines.append(f"- {intent}")
    if len(moved) > _MAX_LISTED_EDITS:
        lines.append(f"- … and {len(moved) - _MAX_LISTED_EDITS} more")
    lines.append("Re-read the scene before editing; the scene you hold is already the new version.")
    return "\n".join(lines)


__all__ = ["design_session_id", "latest_written_version", "render_document_drift_note"]
```

- [ ] **Step 4: Add `drift_note` to `render_leg_turn_prompt`**

In `subsystems/design/clue_design/leg_context.py`, change the signature and append the block after history:

```python
def render_leg_turn_prompt(
    *,
    bundle: JsonObject | None,
    history: list[JsonObject] | None,
    prompt: str,
    drift_note: str | None = None,
) -> str:
    ...
    if history:
        ...
        sections.append("\n".join(lines))
    if drift_note:
        sections.append(drift_note)
    if not sections:
        return prompt
    sections.append(prompt)
    return "\n\n".join(sections)
```

Export the three names from `subsystems/design/clue_design/__init__.py` beside the existing exports.

- [ ] **Step 5: Write the DB test for `latest_written_version`**

```python
# tests/design/test_design_sessions_db.py
import pytest
from sqlalchemy import text

from clue_design import runs as design_runs
from clue_design.sessions import latest_written_version

pytestmark = pytest.mark.usefixtures("db_url")  # the tests/design conftest gate


async def test_latest_written_version_reads_the_newest_succeeded_stamp(rollback_conn) -> None:
    ws, doc = "ws_sess_test", "doc_sess_test"
    await rollback_conn.execute(
        text("INSERT INTO design_document (id, workspace_id, title, status, doc_kind, "
             "current_scene_json, current_version) VALUES (:d, :w, 't', 'draft', 'scene', '{}', 3)"),
        {"d": doc, "w": ws},
    )
    assert await latest_written_version(rollback_conn, workspace_id=ws, document_id=doc) is None
    for run_id, status, version in (("run_a", "succeeded", 2), ("run_b", "failed", 9), ("run_c", "succeeded", 3)):
        await design_runs.create_run(rollback_conn, workspace_id=ws, run_id=run_id, document_id=doc)
        await rollback_conn.execute(
            text("UPDATE design_agent_run SET status = :s, result_json = :r, updated_at = now() "
                 "WHERE run_id = :id"),
            {"s": status, "r": f'{{"current_version": {version}}}', "id": run_id},
        )
    assert await latest_written_version(rollback_conn, workspace_id=ws, document_id=doc) == 3
```

Use the `rollback_conn` fixture the `tests/design` conftest already provides (see `tests/design/test_durable_jobs_dal_db.py` for the import and fixture names; copy them exactly). If `design_agent_run.status` is an enum type, cast in the UPDATE: `status = CAST(:s AS design_run_status)`.

- [ ] **Step 6: Run both test files**

Run: `set -a; source .env; set +a; uv run pytest tests/design/test_design_sessions.py tests/design/test_design_sessions_db.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add subsystems/design/clue_design/sessions.py subsystems/design/clue_design/leg_context.py subsystems/design/clue_design/__init__.py tests/design/test_design_sessions.py tests/design/test_design_sessions_db.py
git commit -m "feat(design): design session id, last-written version read, document drift note"
```

---

### Task 2: The envelope names the session; the run row stores it; a second leg on the same document waits

**Files:**
- Modify: `platform/api/clue_api/design_leg_wiring.py` (`_envelope` ~1646-1831, `_dispatch` ~1511-1645)
- Test: `tests/design/test_design_fleet_turns_db.py`, `tests/design/test_p37_design_entry_consumption.py`, `tests/design/test_durable_jobs_dal_db.py`, new `tests/api/test_design_leg_session_db.py`

**Interfaces:**
- Consumes: `design_session_id` (Task 1); `clue_design.runs.active_run_for_document`.
- Produces: `DesignTurnEnvelope.checkpoint_thread_id == design_session_id(ws, doc)` when a document is pinned, else `run_id`; `config["leg"]["first_turn_of_leg"]: bool`; the run row's `checkpoint_thread_id` column equals the envelope's; `_dispatch` waits while another run is `running` on the same document.

- [ ] **Step 1: Write the failing tests**

Add to `tests/design/test_p37_design_entry_consumption.py` (it already builds envelopes through the real `_envelope`; follow its fixture style):

```python
async def test_a_pinned_leg_turn_names_the_document_session_as_its_thread(leg_envelope_factory) -> None:
    envelope = await leg_envelope_factory(document_id="doc_x", prior_history=())
    assert envelope.checkpoint_thread_id == design_session_id(envelope.workspace_id, "doc_x")
    assert envelope.config["leg"]["first_turn_of_leg"] is True


async def test_a_later_turn_on_the_leg_is_not_the_first(leg_envelope_factory) -> None:
    envelope = await leg_envelope_factory(document_id="doc_x", prior_history=(_history_ref("user"),))
    assert envelope.config["leg"]["first_turn_of_leg"] is False


async def test_a_document_less_leg_keeps_the_run_id_as_its_thread(leg_envelope_factory) -> None:
    envelope = await leg_envelope_factory(document_id=None, prior_history=())
    assert envelope.checkpoint_thread_id == envelope.run_id
```

If no such factory exists in that file, add one that calls `DesignLegRunner._envelope(...)` with the same arguments the existing tests pass (copy the first existing call site's argument list verbatim).

New `tests/api/test_design_leg_session_db.py` (stack DOWN):

```python
async def test_dispatch_stores_the_session_thread_on_the_run_row(leg_runner_db) -> None:
    run = await leg_runner_db.dispatch_one(document_id="doc_s")  # helper mirrors test_design_fleet_turns_db's dispatch
    row = await leg_runner_db.run_row(run["run_id"])
    assert row["checkpoint_thread_id"] == design_session_id(leg_runner_db.workspace_id, "doc_s")


async def test_dispatch_waits_while_another_run_drives_the_same_document(leg_runner_db, monkeypatch) -> None:
    # A foreign run is 'running' on the document; the lane must not drive until it is terminal.
    foreign = await leg_runner_db.insert_running_run(document_id="doc_s", run_id="run_foreign")
    drove: list[str] = []
    async def fake_drive(*, envelope):
        drove.append(envelope.run_id)
    monkeypatch.setattr(leg_runner_db.lane, "drive", fake_drive)
    task = asyncio.create_task(leg_runner_db.dispatch_one(document_id="doc_s"))
    await asyncio.sleep(0.3)
    assert drove == [], "must wait while the foreign run is live"
    await leg_runner_db.finish_run("run_foreign")
    await asyncio.wait_for(task, timeout=5)
    assert len(drove) == 1
```

Model `leg_runner_db` on the fixtures in `tests/design/test_design_fleet_turns_db.py` (`:60-140` builds a runner with a fake lane). Set the runner's `document_wait_poll_s=0.05` in the fixture.

Update the pinned expectation `checkpoint_thread_id=run_id` in `tests/design/test_design_fleet_turns_db.py:87` and `test_durable_jobs_dal_db.py:145` where the envelope carries a document: expected value becomes `design_session_id(ws, document_id)`; envelopes without a document keep `run_id`.

- [ ] **Step 2: Run to verify they fail**

Run: `set -a; source .env; set +a; uv run pytest tests/design/test_p37_design_entry_consumption.py tests/api/test_design_leg_session_db.py -q -p no:cacheprovider`
Expected: FAIL (`checkpoint_thread_id` still equals the run id; no `first_turn_of_leg`; no wait).

- [ ] **Step 3: Change `_envelope`**

In `platform/api/clue_api/design_leg_wiring.py`:

```python
from clue_design.sessions import design_session_id
```

In `_envelope`, after `document = pinned_document or {}`:

```python
        document_id = leg.get("document_id")
        thread_id = (
            design_session_id(workspace_id, str(document_id)) if document_id else run_id
        )
```

Inside `config["leg"]` add:

```python
                # Session continuity: the design side sends the DELEGATION BRIEF block on the
                # first turn of each leg and never re-sends the HISTORY block on a continued
                # thread; this flag is how it knows which turn this is without a second read.
                "first_turn_of_leg": not history_texts,
```

And the constructor:

```python
        return DesignTurnEnvelope(
            kind=kind,
            work_id=design_runs.work_id_for_run(run_id),
            workspace_id=workspace_id,
            run_id=run_id,
            checkpoint_thread_id=thread_id,
            document_id=document_id,
            project_id=submission.project_id,
            config=config,
        )
```

- [ ] **Step 4: Change `_dispatch`**

Re-join guard (`~:1546-1551`): replace `or envelope.checkpoint_thread_id != run_id` with

```python
                or envelope.checkpoint_thread_id
                not in {run_id, design_session_id(workspace_id, str(envelope.document_id or ""))}
```

`create_run` call (`~:1586`): add `checkpoint_thread_id=envelope.checkpoint_thread_id,`.

Before `await self._lane.drive(envelope=envelope)` (`~:1639`), add the same-document wait:

```python
        if envelope.document_id is not None:
            await self._wait_for_document(
                workspace_id=workspace_id, document_id=str(envelope.document_id), run_id=run_id
            )
```

with the method (constructor gains `document_wait_poll_s: float = 2.0`, `document_wait_timeout_s: float = 1800.0`):

```python
    async def _wait_for_document(self, *, workspace_id: str, document_id: str, run_id: str) -> None:
        """Founder ruling 2026-09-18: a second thread on a driven document QUEUES behind it.

        Sessions make this a correctness rule, not a spend rule — two turns continuing one
        LangGraph thread at once would interleave their checkpoints.
        """
        deadline = asyncio.get_running_loop().time() + self._document_wait_timeout_s
        announced = False
        while True:
            async with self._conn_factory() as conn:
                active = await design_runs.active_run_for_document(
                    conn, workspace_id=workspace_id, document_id=document_id
                )
            if active is None or active.get("run_id") == run_id:
                return
            if not announced:
                log.info("design_leg.waiting_for_document", run_id=run_id,
                         document_id=document_id, active_run_id=active.get("run_id"))
                announced = True
            if asyncio.get_running_loop().time() >= deadline:
                raise RuntimeError("another design turn held this document past the wait window")
            await asyncio.sleep(self._document_wait_poll_s)
```

Check the exact return shape of `active_run_for_document` (`subsystems/design/clue_design/runs.py:494-537`) and adapt `active.get("run_id")` to it.

- [ ] **Step 5: Run the tests**

Run: `./scripts/dev_stack_san_salvador.sh down; set -a; source .env; set +a; uv run pytest tests/design/test_p37_design_entry_consumption.py tests/api/test_design_leg_session_db.py tests/design/test_design_fleet_turns_db.py tests/design/test_durable_jobs_dal_db.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add platform/api/clue_api/design_leg_wiring.py tests/design tests/api/test_design_leg_session_db.py
git commit -m "feat(design-leg): the envelope names the document session as its thread; a second leg on a driven document waits"
```

---

### Task 3: Runtime config and substrates own a session folder with per-turn subfolders

**Files:**
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/config.py`
- Modify: `.../lumen_agent/tools/substrate.py` (ctor `:340-370`; writes at `:458, :537, :575-600, :3181, :3583, :4556, :5242, :5470-5476, :5566, :5730, :5826-5833`)
- Modify: `.../lumen_agent/tools/web_substrate.py` (ctor `:972-1010`; `:8535`, `:9305`, `:10005-10011`, `:1230`)
- Modify: `.../lumen_agent/workspace.py` (`scaffold_workspace` rounds index `:380`)
- Modify: `.../lumen_agent/run_metrics.py` (`count_round_dirs`)
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_session_folder.py` (create), `tests/test_run_metrics.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `AgentRuntimeConfig.session_id: str | None = None`; `AgentRuntimeConfig.session_dir() -> Path | None`; on tools: `trace_dir` (session dir when `session_id` set, else `<trace_dir>/<run_id>` as today), `turn_dir` (`trace_dir / "turns" / run_id` for sessions, `== trace_dir` otherwise), `workspace_scope_id` (`f"sessions/{session_id}"` or `run_id`), `round_base: int`; `count_round_dirs(rounds_dir, *, above: int = 0)`.

- [ ] **Step 1: Write the failing tests**

```python
# subsystems/clue-design/apps/agent_runtime/tests/test_session_folder.py
from dataclasses import replace
from pathlib import Path

from lumen_agent.tools.substrate import LumenDesignTools
from lumen_agent.workspace import scaffold_workspace, workspace_root


def _tools(config, prompt="p"):
    return LumenDesignTools(config, prompt, initial_scene=None)


def test_without_a_session_the_run_folder_is_unchanged(runtime_config, tmp_path) -> None:
    tools = _tools(replace(runtime_config, trace_dir=tmp_path))
    assert tools.trace_dir == tmp_path / tools.run_id
    assert tools.turn_dir == tools.trace_dir
    assert tools.workspace_scope_id == tools.run_id
    assert tools.round_base == 0


def test_a_session_owns_one_folder_and_each_turn_a_subfolder(runtime_config, tmp_path) -> None:
    config = replace(runtime_config, trace_dir=tmp_path, session_id="dsess_abc")
    first = _tools(config)
    second = _tools(config)
    assert first.trace_dir == second.trace_dir == tmp_path / "sessions" / "dsess_abc"
    assert first.turn_dir == first.trace_dir / "turns" / first.run_id
    assert second.turn_dir != first.turn_dir
    assert first.workspace_scope_id == "sessions/dsess_abc"
    assert workspace_root(first) == workspace_root(second)


def test_rounds_continue_numbering_across_turns(runtime_config, tmp_path) -> None:
    config = replace(runtime_config, trace_dir=tmp_path, session_id="dsess_r")
    first = _tools(config)
    scaffold_workspace(first, "p")
    (workspace_root(first) / "rounds" / "round_1").mkdir(parents=True)
    (workspace_root(first) / "rounds" / "round_2").mkdir()
    second = _tools(config)
    assert second.round_base == 2
    scaffold_workspace(second, "p2")
    index = (workspace_root(second) / "rounds" / "index.md").read_text()
    assert index.count("# Rounds") == 1 and f"## Turn {second.run_id}" in index
    assert (workspace_root(second) / "rounds" / "round_1").is_dir(), "earlier rounds are never deleted"


def test_turn_outputs_land_in_the_turn_folder(runtime_config, tmp_path) -> None:
    config = replace(runtime_config, trace_dir=tmp_path, session_id="dsess_o")
    tools = _tools(config)
    assert (tools.turn_dir / "input.json").is_file()
    tools.record("coordinator", "x", output_summary="y")
    assert (tools.turn_dir / "trace.jsonl").is_file()
    assert not (tools.trace_dir / "trace.jsonl").exists()
```

Use the `runtime_config` fixture the suite already has (see `tests/conftest.py` in `agent_runtime/tests`; if it is named differently, use that name). For `test_run_metrics.py`, add:

```python
def test_count_round_dirs_above_a_base(tmp_path: Path) -> None:
    for n in (1, 2, 3):
        (tmp_path / f"round_{n}").mkdir()
    assert count_round_dirs(tmp_path) == 3
    assert count_round_dirs(tmp_path, above=2) == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest subsystems/clue-design/apps/agent_runtime/tests/test_session_folder.py subsystems/clue-design/apps/agent_runtime/tests/test_run_metrics.py -q -p no:cacheprovider`
Expected: FAIL (`session_id` unknown field; no `turn_dir`).

- [ ] **Step 3: Config**

In `config.py`, add after `asset_store_root`:

```python
    # Design session continuity (2026-09-18): when set, the substrate lands this turn inside the
    # persistent session folder ``<trace_dir>/sessions/<session_id>/turns/<run_id>`` and the
    # agent's workspace ``<trace_dir>/sessions/<session_id>/workspace`` survives across turns.
    # None keeps the per-run folder ``<trace_dir>/<run_id>`` (editor preview, CLI, fixtures).
    session_id: str | None = None
```

and a method beside `workspace_root`:

```python
    def session_dir(self) -> Path | None:
        return None if self.session_id is None else self.trace_dir / "sessions" / self.session_id
```

- [ ] **Step 4: Scene substrate**

Replace `:361-364`:

```python
        session_dir = config.session_dir()
        if session_dir is None:
            self.trace_dir = config.trace_dir / self.run_id
            self.turn_dir = self.trace_dir
            self.workspace_scope_id = self.run_id
        else:
            self.trace_dir = session_dir
            self.turn_dir = session_dir / "turns" / self.run_id
            self.workspace_scope_id = f"sessions/{config.session_id}"
        self.iterations_dir = self.turn_dir / "iterations"
        self.turn_dir.mkdir(parents=True, exist_ok=True)
        self.iterations_dir.mkdir(parents=True, exist_ok=True)
        # Rounds are numbered across the whole session: a second turn's first round follows the
        # highest round directory the workspace already holds.
        self.round_base = self._highest_round_dir()
```

Add the helper (extract from `_fast_loop_round_number`):

```python
    def _highest_round_dir(self) -> int:
        rounds = self.trace_dir / "workspace" / "rounds"
        highest = 0
        try:
            for child in rounds.iterdir():
                if child.is_dir() and child.name.startswith("round_"):
                    suffix = child.name[len("round_") :]
                    if suffix.isdigit():
                        highest = max(highest, int(suffix))
        except OSError:
            return 0
        return highest
```

`_fast_loop_round_number`: `if self.solo_rounds_executed is not None: return self.round_base + self.solo_rounds_executed` and the fallback returns `self._highest_round_dir()`. In the solo round starter (`:565-575`) compute `next_round` as today, then `path = ... / f"round_{self.round_base + next_round}"` and record `self.round_base + next_round`.

Move every harness-owned output from `self.trace_dir` to `self.turn_dir`: `input.json` (`:458-467`), `knowledge.json` (`:537`), `baseline_preflight.json` (`:3583`), `gaps.json` (`:4556`), instance previews (`:3181`), `final.json` (`:5242`, `:5470`), `final_scene.json` (`:5476`), `trace.jsonl` (`:5566`), `operations_ledger.json` (`:5833`). The containment check at `:5730` becomes `path.relative_to(self.trace_dir.resolve())` (the session root contains the turn dir). Leave `workspace/**` paths (`:575`, `:4143-4148`, `:4170`, `:4236`) on `trace_dir`.

- [ ] **Step 5: Web substrate**

Same split at `:1001-1003`:

```python
        session_dir = config.session_dir()
        if session_dir is None:
            self.trace_dir = config.trace_dir / self.run_id
            self.turn_dir = self.trace_dir
            self.workspace_scope_id = self.run_id
        else:
            self.trace_dir = session_dir
            self.turn_dir = session_dir / "turns" / self.run_id
            self.workspace_scope_id = f"sessions/{config.session_id}"
        self.turn_dir.mkdir(parents=True, exist_ok=True)
        bind_run_id(self.run_id)
```

Move `review_<n>` (`:8535`), `iter_<n>` (`:9305`), the four `final_*.json` (`:10005-10011`) and `trace.jsonl` (`:1230`) to `self.turn_dir`. `custom_component_projection_root` stays under `self.trace_dir` (session-wide).

- [ ] **Step 6: Scaffold appends the round index; metrics count above the base**

`workspace.py:380-385`:

```python
    index = rounds / "index.md"
    header = (
        "# Rounds — this design session\n\n"
        "One line per round: round number, verdict, and the one mistake the next "
        "round must not repeat.\n"
    )
    if not index.exists():
        index.write_text(header, encoding="utf-8")
    with index.open("a", encoding="utf-8") as handle:
        handle.write(f"\n## Turn {tools.run_id}\n")
```

`run_metrics.py`: `def count_round_dirs(rounds_dir: Path, *, above: int = 0) -> int` counting only `int(suffix) > above`; `emit_run_metrics` calls it with `above=getattr(tools, "round_base", 0)` and writes `metrics.json` into `tools.turn_dir` (find the write site in `emit_run_metrics`; it currently writes "next to final.json").

- [ ] **Step 7: Run the tests, then the substrate neighbours**

Run: `uv run pytest subsystems/clue-design/apps/agent_runtime/tests/test_session_folder.py subsystems/clue-design/apps/agent_runtime/tests/test_run_metrics.py subsystems/clue-design/apps/agent_runtime/tests/test_run_log_scope.py subsystems/clue-design/apps/agent_runtime/tests/test_scene_solo_runtime.py subsystems/clue-design/apps/agent_runtime/tests/test_web_substrate.py -q -p no:cacheprovider`
Expected: PASS. Tests that assert `tools.trace_dir / "final.json"` for non-session runs still pass because `turn_dir == trace_dir` there.

- [ ] **Step 8: Commit**

```bash
git add subsystems/clue-design/apps/agent_runtime/lumen_agent subsystems/clue-design/apps/agent_runtime/tests
git commit -m "feat(lumen-agent): session folder with per-turn subfolders; rounds number across the session"
```

---

### Task 4: The workspace backend scopes a session and admits its conversation history

**Files:**
- Modify: `.../lumen_agent/fs_backend.py` (`__init__ :90-99`, `_scope_roots :142-150`, `_check_run_scope :152-163`, `_assert_writable :165-…`)
- Modify: `.../lumen_agent/harness.py` (`:457`, `:466-471`)
- Modify: `.../lumen_agent/harness_web.py` (`:266-269`)
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_workspace_run_isolation.py`

**Interfaces:**
- Consumes: `tools.workspace_scope_id` (Task 3).
- Produces: `AgentWorkspaceBackend(..., active_run_id="sessions/<id>")` works; the backend admits reads and writes to `/conversation_history/<thread>.md` and `/conversation_history/media/**` for the active session only, via a new `history_thread_id: str | None = None` constructor argument.

- [ ] **Step 1: Write the failing tests** (append to `test_workspace_run_isolation.py`, reusing its helpers)

```python
def test_a_session_scope_admits_its_own_history_file_and_nothing_else(tmp_path: Path) -> None:
    root = tmp_path
    (root / "sessions" / "dsess_a" / "workspace").mkdir(parents=True)
    (root / "conversation_history").mkdir()
    (root / "conversation_history" / "dsess_b.md").write_text("other tenant", encoding="utf-8")
    backend = AgentWorkspaceBackend(
        root_dir=str(root), active_run_id="sessions/dsess_a", history_thread_id="dsess_a"
    )
    backend.write("/conversation_history/dsess_a.md", "mine")
    assert (root / "conversation_history" / "dsess_a.md").read_text() == "mine"
    assert backend.read("/conversation_history/dsess_a.md").startswith("mine") or "mine" in backend.read("/conversation_history/dsess_a.md")
    with pytest.raises(PermissionError):
        backend.read("/conversation_history/dsess_b.md")
    with pytest.raises(PermissionError):
        backend.write("/conversation_history/dsess_b.md", "x")
    backend.write("/conversation_history/media/abc.png", "bytes")
    assert (root / "conversation_history" / "media" / "abc.png").is_file()


def test_a_session_scope_still_fences_sibling_sessions(tmp_path: Path) -> None:
    root = tmp_path
    (root / "sessions" / "dsess_a" / "workspace").mkdir(parents=True)
    (root / "sessions" / "dsess_b" / "workspace").mkdir(parents=True)
    (root / "sessions" / "dsess_b" / "workspace" / "brief.md").write_text("b", encoding="utf-8")
    backend = AgentWorkspaceBackend(root_dir=str(root), active_run_id="sessions/dsess_a")
    with pytest.raises(PermissionError):
        backend.read("/sessions/dsess_b/workspace/brief.md")
    backend.write("/sessions/dsess_a/workspace/note.md", "ok")
```

Use the same read/write method names the existing tests in that file use (they wrap `read_file`/`write_file` through the deepagents backend API; copy their calling convention).

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest subsystems/clue-design/apps/agent_runtime/tests/test_workspace_run_isolation.py -q -p no:cacheprovider`
Expected: FAIL (`history_thread_id` unknown; history path refused).

- [ ] **Step 3: Backend**

```python
    def __init__(self, root_dir, max_file_size_mb=10, custom_components_root=None,
                 reference_turn=False, critique_observer=None, active_run_id=None,
                 history_thread_id: str | None = None) -> None:
        ...
        self._history_thread_id = history_thread_id

    def _history_roots(self) -> tuple[Path, ...]:
        if self._history_thread_id is None:
            return ()
        root = Path(self._workspace_root).resolve() / "conversation_history"
        return (root / f"{self._history_thread_id}.md", root / "media")

    def _scope_roots(self) -> tuple[Path, ...]:
        assert self._active_run_id is not None
        root = Path(self._workspace_root).resolve()
        return (
            root / self._active_run_id,
            root / "knowledge_docs",
            root / ".deepagent",
            self._custom_components_root or root / "custom_components",
            *self._history_roots(),
        )
```

In `_assert_writable`, treat the history roots as writable: `run_root, *readonly = self._scope_roots()` becomes

```python
        scope = self._scope_roots()
        history = set(self._history_roots())
        run_root = scope[0]
        readonly = [r for r in scope[1:] if r not in history]
        writable = (run_root, *history)
        if not any(resolved.is_relative_to(w) for w in writable) or any(...readonly check unchanged...):
```

`root / self._active_run_id` with `"sessions/dsess_a"` already resolves to the nested folder; the error string `f"/{self._active_run_id}/"` reads `/sessions/dsess_a/`, which is the agent's path. Keep `_check_run_scope` unchanged (it already iterates `_scope_roots`).

- [ ] **Step 4: Harness wiring**

`harness.py:457` → `workspace_str = f"/{tools.workspace_scope_id}/workspace"`; `:466-471`:

```python
    backend = AgentWorkspaceBackend(
        root_dir=str(runtime_config.workspace_root),
        active_run_id=tools.workspace_scope_id,
        history_thread_id=runtime_config.session_id,
        reference_turn=bool(runtime_config.reference_assets),
        critique_observer=tools.observe_written_critique,
    )
```

`harness_web.py:266-269`: add `history_thread_id=runtime_config.session_id`. Grep both harnesses and `workspace.py`/`prompts*.py` for `tools.run_id}/workspace` and `f"/{tools.run_id}` and replace with `workspace_scope_id` (the prompt's workspace path must be the session path, or a continued thread references a folder that no longer exists).

- [ ] **Step 5: Run the isolation suite and the harness suites**

Run: `uv run pytest subsystems/clue-design/apps/agent_runtime/tests/test_workspace_run_isolation.py subsystems/clue-design/apps/agent_runtime/tests/test_deepagent_harness.py subsystems/clue-design/apps/agent_runtime/tests/test_deepagent_fs_and_usage.py subsystems/clue-design/apps/agent_runtime/tests/test_scene_guidance_reads.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add subsystems/clue-design/apps/agent_runtime
git commit -m "feat(lumen-agent): the workspace backend scopes a session folder and admits its own conversation history"
```

---

### Task 5: Continue the thread instead of restarting it

**Files:**
- Modify: `.../lumen_agent/checkpoint.py`
- Modify: `.../lumen_agent/harness.py` (`:974-978`, `:991`, `:1004-1008`, `:1021-1027`, `:1077`)
- Modify: `.../lumen_agent/harness_web.py` (`:626`, `:633-651`)
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_checkpoint_resume.py` (rewrite the restart test), `tests/test_run_log_scope.py`

**Interfaces:**
- Produces: `invoke_turn_graph(agent, initial_state, *, invoke_config, checkpointer=None, thread_id=None, run_id=None)`: no checkpointer → invoke as before; fresh thread → invoke with `initial_state`; thread with state whose last human message carries `additional_kwargs["lumen_run_id"] == run_id` → **resume** with `agent.invoke(None, config)`; otherwise → **continue** with `agent.invoke(initial_state, config)` (LangGraph appends the message; state keys are overwritten). The human message is built as `HumanMessage(content=prompt, additional_kwargs={"lumen_run_id": run_id})`.

- [ ] **Step 1: Rewrite the pinned test and add the two new ones**

Replace `test_a_thread_that_already_ran_is_cleared_and_restarted_from_the_top` with:

```python
def _snapshot_with_last_human(run_id: str | None):
    msg = HumanMessage(content="make a poster", additional_kwargs={} if run_id is None else {"lumen_run_id": run_id})
    return _Snapshot("2026-01-01T00:00:00Z", values={"messages": [msg]})


def test_a_thread_with_earlier_turns_is_continued_with_the_new_message() -> None:
    # Design session continuity (2026-09-18): the thread is the document's session. A NEW run on
    # it appends its message; nothing is deleted.
    agent = _FakeAgent(snapshot=_snapshot_with_last_human("run_old"))
    saver = _FakeSaver()
    initial = {"messages": [HumanMessage(content="now make it red", additional_kwargs={"lumen_run_id": "run_new"})]}
    invoke_turn_graph(agent, initial, invoke_config=_config("dsess_1"), checkpointer=saver,
                      thread_id="dsess_1", run_id="run_new")
    assert saver.deleted == []
    assert agent.invocations == [(initial, "dsess_1")]


def test_the_same_run_retried_resumes_without_re_sending_its_message() -> None:
    agent = _FakeAgent(snapshot=_snapshot_with_last_human("run_same"))
    initial = {"messages": [HumanMessage(content="make a poster", additional_kwargs={"lumen_run_id": "run_same"})]}
    invoke_turn_graph(agent, initial, invoke_config=_config("dsess_2"), checkpointer=_FakeSaver(),
                      thread_id="dsess_2", run_id="run_same")
    assert agent.invocations == [(None, "dsess_2")]
```

Give `_Snapshot` a `values` attribute (default `{"messages": []}`) and import `HumanMessage` from `langchain_core.messages`. Keep the other four tests as they are; `test_checkpoint_bookkeeping_never_fails_a_runnable_turn` no longer needs `delete_raises` (delete is gone) — keep the unreadable-state case and assert the turn still invokes with `initial_state`.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest subsystems/clue-design/apps/agent_runtime/tests/test_checkpoint_resume.py -q -p no:cacheprovider`
Expected: FAIL (`run_id` unexpected; `deleted == ["dsess_1"]`).

- [ ] **Step 3: Rewrite `checkpoint.py`**

```python
"""Durable-graph seam for the two turn harnesses.

Design session continuity (founder ruling 2026-09-18) replaces D5's resume-as-restart. The
thread is the document's SESSION, so a thread that already carries state is the normal case,
not a crash: a new run appends its user message and the graph continues with every earlier tool
call, result and critique still in the window; a retried run (same run id as the thread's last
user message) resumes from the last checkpoint with input ``None``. ``PatchToolCallsMiddleware``
(deepagents, installed on both graphs) repairs a dangling tool call left by an interrupted attempt.
The tool substrate is reconstructible now: the scene is reloaded from the document at turn start
and per-turn files live under the session folder's ``turns/<run_id>``.
"""

from __future__ import annotations

from typing import Any

from py_lumen_obs import get_logger

logger = get_logger("lumen_agent.checkpoint")

RUN_ID_KEY = "lumen_run_id"


def invoke_turn_graph(
    agent: Any,
    initial_state: dict,
    *,
    invoke_config: dict,
    checkpointer: Any = None,
    thread_id: str | None = None,
    run_id: str | None = None,
) -> Any:
    if checkpointer is None or thread_id is None:
        return agent.invoke(initial_state, config=invoke_config)

    last_run = _last_user_run_id(agent, invoke_config, thread_id)
    if last_run is None:
        return agent.invoke(initial_state, config=invoke_config)
    if run_id is not None and last_run == run_id:
        logger.info("turn.checkpoint_resume", thread_id=thread_id, run_id=run_id)
        return agent.invoke(None, config=invoke_config)
    logger.info("turn.checkpoint_continue", thread_id=thread_id, run_id=run_id, after_run=last_run)
    return agent.invoke(initial_state, config=invoke_config)


def _last_user_run_id(agent: Any, invoke_config: dict, thread_id: str) -> str | None:
    """The run id stamped on the thread's newest user message; ``None`` for a fresh thread."""
    try:
        snapshot = agent.get_state(invoke_config)
    except Exception:  # noqa: BLE001 - never let checkpoint bookkeeping fail a runnable turn
        logger.warning("turn.checkpoint_state_unreadable", thread_id=thread_id, exc_info=True)
        return None
    if getattr(snapshot, "created_at", None) is None:
        return None
    messages = (getattr(snapshot, "values", None) or {}).get("messages") or []
    for message in reversed(messages):
        if getattr(message, "type", None) == "human":
            return (getattr(message, "additional_kwargs", None) or {}).get(RUN_ID_KEY) or "unknown"
    return "unknown"


__all__ = ["RUN_ID_KEY", "invoke_turn_graph"]
```

- [ ] **Step 4: Harness changes**

`harness.py`:
- `:974` `run_log_path = tools.turn_dir / "logs" / "run.jsonl"`; `:975-978` guard gets `tools.turn_dir`.
- `:991`:

```python
        from langchain_core.messages import HumanMessage
        from .checkpoint import RUN_ID_KEY

        initial_state = {
            "messages": [HumanMessage(content=prompt, additional_kwargs={RUN_ID_KEY: tools.run_id})],
            **initial_turn_state(tools, prompt),
        }
```

- `:1021-1027` add `run_id=tools.run_id` to `invoke_turn_graph(...)`.
- `:1077` `final_path = tools.turn_dir / "final.json"`.

`harness_web.py:626` same `HumanMessage`; `:645-651` add `run_id=tools.run_id`; any `tools.trace_dir / "final*.json"` reads in the web runner → `tools.turn_dir`.

- [ ] **Step 5: Run**

Run: `uv run pytest subsystems/clue-design/apps/agent_runtime/tests/test_checkpoint_resume.py subsystems/clue-design/apps/agent_runtime/tests/test_run_log_scope.py subsystems/clue-design/apps/agent_runtime/tests/test_scene_solo_runtime.py subsystems/clue-design/apps/agent_runtime/tests/test_final_acceptance_contract.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add subsystems/clue-design/apps/agent_runtime
git commit -m "feat(lumen-agent): continue the session thread across turns; resume a retried run instead of restarting it"
```

---

### Task 6: The executors read the document, note drift, gate the brief and history, and pass the session to the runtime

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/fleet_handler.py` (`_execute_turn :584-604`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py` (`run_agent_turn_preview :9236-9300` config build; `_execute_agent_turn_job :10408-10600`; `run_web_agent_turn :9862`; `_execute_web_turn_job :11079-11170`)
- Test: `subsystems/clue-design/apps/api/tests/test_scene_turn_persist.py`, `tests/design/test_p37_design_entry_consumption.py`, `tests/design/test_design_fleet_turns_db.py`, `subsystems/clue-design/apps/api/tests/test_web_turns.py`

**Interfaces:**
- Consumes: `design_session_id`, `latest_written_version`, `render_document_drift_note` (Task 1); `AgentRuntimeConfig.session_id` (Task 3).
- Produces: `execute_agent_turn_job(..., session_continued: bool = False)` / `execute_web_turn_job(..., session_continued: bool = False)`; `run_agent_turn_preview(..., session_id: str | None = None)`; `run_web_agent_turn(..., session_id: str | None = None)`; the response keeps `current_version`.

- [ ] **Step 1: Write the failing tests**

In `tests/design/test_p37_design_entry_consumption.py` (drives the real executor with a stubbed runner; extend its existing fixture):

```python
def test_a_continued_session_sends_neither_brief_nor_history_unless_the_leg_is_new(stubbed_executor) -> None:
    seen = stubbed_executor.run(config_history=[{"role": "user", "text": "old"}],
                                first_turn_of_leg=False, session_continued=True)
    assert "<<<HISTORY" not in seen.prompt and "<<<BRIEF" not in seen.prompt

    seen = stubbed_executor.run(config_history=[], first_turn_of_leg=True, session_continued=True)
    assert "<<<BRIEF" in seen.prompt and "<<<HISTORY" not in seen.prompt

    seen = stubbed_executor.run(config_history=[{"role": "user", "text": "old"}],
                                first_turn_of_leg=False, session_continued=False)
    assert "<<<HISTORY" in seen.prompt


def test_the_scene_comes_from_the_document_not_the_frozen_envelope(stubbed_executor) -> None:
    stubbed_executor.document_scene({"meta": {"title": "fresh"}}, version=9)
    seen = stubbed_executor.run(envelope_scene={"meta": {"title": "stale"}}, base_version=7)
    assert seen.initial_scene["meta"]["title"] == "fresh"
    assert seen.expected_base_version == 9, "the CAS base is the version read at execution"


def test_a_moved_document_yields_a_drift_note_not_a_conflict(stubbed_executor) -> None:
    stubbed_executor.document_scene({"meta": {}}, version=9)
    stubbed_executor.last_written_version(6)
    stubbed_executor.envelopes([{"base_revision": 6, "intent": "human moved the logo"}])
    seen = stubbed_executor.run(base_version=6, session_continued=True)
    assert "DOCUMENT CHANGED SINCE YOUR LAST TURN" in seen.prompt
    assert "human moved the logo" in seen.prompt
    assert seen.status != "failed"


def test_the_runtime_receives_the_session_id(stubbed_executor) -> None:
    seen = stubbed_executor.run(document_id="doc_q")
    assert seen.session_id == design_session_id(seen.workspace_id, "doc_q")
```

Build `stubbed_executor` on the file's existing stub runner pattern (`host.agent_turn_runner` override), recording `prompt`, `initial_scene`, the `expected_base_version` the committer is built with, and the `session_id` forwarded. `last_written_version` and `envelopes` are monkeypatched at `lumen_api.main.latest_written_version_sync` / the store's `list_envelopes`.

Update `test_design_fleet_turns_db.py` docstrings/asserts at `:408-411`, `:514-520`, `:538` to the session thread.

- [ ] **Step 2: Run to verify they fail**

Run: `set -a; source .env; set +a; uv run pytest tests/design/test_p37_design_entry_consumption.py -q -p no:cacheprovider`
Expected: FAIL.

- [ ] **Step 3: `fleet_handler._execute_turn`**

```python
    with checkpointer_cm as checkpointer:
        session_continued = _thread_has_state(checkpointer, envelope.checkpoint_thread_id)
        ...
        status, response, event_type, event_data = executor(
            envelope, store=store, host=host, event_sink=sink, checkpointer=checkpointer,
            lease_generation=generation, spend_drain=spend_drain, callbacks=callbacks,
            session_continued=session_continued,
        )
```

with

```python
def _thread_has_state(checkpointer: Any, thread_id: str) -> bool:
    """Does the session thread already carry earlier turns? Best-effort; ``False`` on doubt."""
    if checkpointer is None:
        return False
    try:
        return checkpointer.get_tuple({"configurable": {"thread_id": thread_id}}) is not None
    except Exception:  # noqa: BLE001 - a saver that cannot answer must not fail the turn
        logger.warning("design_job.session_state_unreadable", thread_id=thread_id, exc_info=True)
        return False
```

- [ ] **Step 4: Scene executor (`_execute_agent_turn_job`)**

Signature gains `session_continued: bool = False` (both the public `execute_agent_turn_job` and the private one). Replace the prompt-composition gate (`:10508-10514`):

```python
    first_turn_of_leg = bool(leg_block.get("first_turn_of_leg", True)) if isinstance(leg_block, dict) else True
    bundle_block = delegation_bundle if (delegation_bundle and (not session_continued or first_turn_of_leg)) else None
    history_block = None if session_continued else leg_history
    drift_note = None
```

Replace the conflict block (`:10536-10554`) with the fresh read and the drift note, BEFORE `render_leg_turn_prompt`:

```python
        if leg_persist:
            doc = store.require_document(document_id)
            base_version = int(doc["current_version"])
            last_written = latest_written_version_sync(store, workspace_id=workspace_id, document_id=str(document_id))
            if last_written is not None and last_written < base_version:
                drift_note = render_document_drift_note(
                    previous_version=last_written,
                    current_version=base_version,
                    envelopes=store.list_envelopes(str(document_id), newest_first=False),
                )
            payload = payload.model_copy(update={"scene": doc["scene"]})
```

(the frozen `document_base_version` from the envelope is no longer the CAS base; `_own_checkpoint_version` and `conflicted_agent_turn_response` lose their leg callers — delete them if nothing else uses them.) Then compose the prompt with `render_leg_turn_prompt(bundle=bundle_block, history=history_block, prompt=composed_prompt, drift_note=drift_note)`; build the `_LegSceneCommitter` with `doc` and the fresh `base_version`. Add `session_id=design_session_id(workspace_id, str(document_id)) if document_id else None` to the `run_agent_turn_preview(...)` call. Add to `main.py`:

```python
def latest_written_version_sync(store: HybridRepository, *, workspace_id: str, document_id: str) -> Optional[int]:
    return store._bridge._run(
        lambda conn: latest_written_version(conn, workspace_id=workspace_id, document_id=document_id)
    )
```

(use the same `_bridge._run` idiom `list_envelopes` uses at `design_store.py:2122`; if `store` exposes a cleaner sync bridge helper, prefer it.)

- [ ] **Step 5: `run_agent_turn_preview` / `run_web_agent_turn`**

Both gain `session_id: str | None = None`; after `config = AgentRuntimeConfig.from_env(root)`: `if session_id: config = replace(config, session_id=session_id)`.

- [ ] **Step 6: Web executor**

Same three changes: the gate (`:11079-11088`), the conflict (`:11106-11108` → `base_version = int(doc["current_version"])` + drift note through `latest_written_version_sync`), and `session_id=` on the `run_web_agent_turn(...)` call (`:11132-11166`). The persist (`:11222-11242`) keeps `expected_base_version=base_version`.

- [ ] **Step 7: Run**

Run: `./scripts/dev_stack_san_salvador.sh down; set -a; source .env; set +a; uv run pytest tests/design/test_p37_design_entry_consumption.py tests/design/test_design_fleet_turns_db.py tests/design/test_design_checkpoint_forwarding.py subsystems/clue-design/apps/api/tests/test_scene_turn_persist.py subsystems/clue-design/apps/api/tests/test_web_turns.py subsystems/clue-design/apps/api/tests/test_agent_run_write_lock.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add subsystems/clue-design/apps/api tests/design
git commit -m "feat(design-api): leg turns read the document, note drift instead of conflicting, gate the brief and history blocks, and run inside the document's session"
```

---

### Task 7: Record the model's reasoning text

**Files:**
- Modify: `.../lumen_agent/trace_callbacks.py` (`_message_to_dict :339-…`)
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_trace_callbacks.py` (add)

- [ ] **Step 1: Failing test**

```python
def test_reasoning_text_is_recorded_when_the_provider_returned_it() -> None:
    from langchain_core.messages import AIMessage
    from lumen_agent.trace_callbacks import _message_to_dict

    with_reasoning = AIMessage(content="done", additional_kwargs={"reasoning_content": "I compared the two layouts."})
    assert _message_to_dict(with_reasoning)["reasoning_content"] == "I compared the two layouts."
    assert "reasoning_content" not in _message_to_dict(AIMessage(content="done"))
```

- [ ] **Step 2: Run to verify it fails** — `uv run pytest subsystems/clue-design/apps/agent_runtime/tests/test_trace_callbacks.py -q -p no:cacheprovider` → FAIL (`KeyError`).

- [ ] **Step 3: Implement** — in `_message_to_dict`, after `out["content"] = ...`:

```python
    reasoning = (getattr(message, "additional_kwargs", None) or {}).get("reasoning_content")
    if isinstance(reasoning, str) and reasoning.strip():
        # Founder ruling 2026-09-18: the model's own reasoning is part of the session RECORD.
        # It is recorded here (trace.jsonl / run.jsonl); re-sending it as context is a
        # per-provider decision the gateway owns (clue_gateway.openrouter_chat._retain_reasoning).
        out["reasoning_content"] = reasoning
```

- [ ] **Step 4: Run** → PASS. **Step 5: Commit** — `git commit -am "feat(lumen-agent): record the provider's reasoning text in the run trace"`.

---

### Task 8: Sync the session folder to storage at turn end; restore it at turn start

**Files:**
- Create: `.../lumen_agent/session_sync.py`
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py` (`run_agent_turn_preview`, `run_web_agent_turn`: around the runtime call)
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_session_sync.py` (create), `subsystems/clue-design/apps/api/tests/test_scene_turn_persist.py` (manifest stamp)

**Interfaces:**
- Produces: `snapshot_session(session_dir: Path, *, register: Callable[[bytes, str, str], str], history_file: Path | None) -> dict` (manifest `{"schema_version": 1, "files": {relpath: {"sha256", "size", "media_type"}}}`); `restore_session(session_dir: Path, manifest: dict, *, read_blob: Callable[[str], tuple[str, bytes]], history_file: Path | None) -> int`; `response["session_manifest_sha256"]` on every session run; restore happens when the session folder is missing and the newest succeeded run carries a manifest.

- [ ] **Step 1: Failing tests**

```python
# subsystems/clue-design/apps/agent_runtime/tests/test_session_sync.py
import hashlib
from pathlib import Path

from lumen_agent.session_sync import restore_session, snapshot_session


class _Blobs:
    def __init__(self) -> None:
        self.store: dict[str, tuple[str, bytes]] = {}

    def register(self, data: bytes, media_type: str, source_key: str) -> str:
        sha = hashlib.sha256(data).hexdigest()
        self.store[sha] = (media_type, data)
        return sha

    def read_blob(self, sha: str) -> tuple[str, bytes]:
        return self.store[sha]


def test_snapshot_covers_workspace_and_history_and_skips_turn_outputs(tmp_path: Path) -> None:
    session = tmp_path / "sessions" / "dsess_a"
    (session / "workspace" / "rounds").mkdir(parents=True)
    (session / "workspace" / "brief.md").write_text("brief", encoding="utf-8")
    (session / "workspace" / "rounds" / "round_1.png").write_bytes(b"\x89PNG")
    (session / "turns" / "run_1").mkdir(parents=True)
    (session / "turns" / "run_1" / "trace.jsonl").write_text("x", encoding="utf-8")
    history = tmp_path / "conversation_history" / "dsess_a.md"
    history.parent.mkdir()
    history.write_text("summary", encoding="utf-8")
    blobs = _Blobs()
    manifest = snapshot_session(session, register=blobs.register, history_file=history)
    assert set(manifest["files"]) == {"workspace/brief.md", "workspace/rounds/round_1.png", "conversation_history/dsess_a.md"}
    assert manifest["files"]["workspace/rounds/round_1.png"]["media_type"] == "image/png"


def test_restore_rebuilds_a_missing_session_folder(tmp_path: Path) -> None:
    session = tmp_path / "sessions" / "dsess_b"
    (session / "workspace").mkdir(parents=True)
    (session / "workspace" / "brief.md").write_text("brief", encoding="utf-8")
    history = tmp_path / "conversation_history" / "dsess_b.md"
    history.parent.mkdir()
    history.write_text("summary", encoding="utf-8")
    blobs = _Blobs()
    manifest = snapshot_session(session, register=blobs.register, history_file=history)
    import shutil; shutil.rmtree(session); history.unlink()
    restored = restore_session(session, manifest, read_blob=blobs.read_blob, history_file=history)
    assert restored == 2
    assert (session / "workspace" / "brief.md").read_text() == "brief"
    assert history.read_text() == "summary"
```

- [ ] **Step 2: Run to verify they fail** — `uv run pytest subsystems/clue-design/apps/agent_runtime/tests/test_session_sync.py -q -p no:cacheprovider` → `ModuleNotFoundError`.

- [ ] **Step 3: Implement `session_sync.py`**

```python
"""Sync a design session's folder to content-addressed storage (design note §3.2, ruling: sync).

What travels: the agent-visible ``workspace/`` tree and the deepagents conversation-history file
for the session (``<root>/conversation_history/<session_id>.md``). What does not: ``turns/<run>``
outputs (observability, not continuity) and files over ``MAX_FILE_BYTES``.
"""

from __future__ import annotations

import hashlib
import mimetypes
from collections.abc import Callable
from pathlib import Path

MAX_FILE_BYTES = 25 * 1024 * 1024
_HISTORY_KEY_PREFIX = "conversation_history/"


def _iter_workspace_files(session_dir: Path):
    workspace = session_dir / "workspace"
    if not workspace.is_dir():
        return
    for path in sorted(p for p in workspace.rglob("*") if p.is_file()):
        if path.stat().st_size <= MAX_FILE_BYTES:
            yield path.relative_to(session_dir).as_posix(), path


def snapshot_session(
    session_dir: Path,
    *,
    register: Callable[[bytes, str, str], str],
    history_file: Path | None,
) -> dict:
    files: dict[str, dict] = {}
    entries = list(_iter_workspace_files(session_dir))
    if history_file is not None and history_file.is_file():
        entries.append((_HISTORY_KEY_PREFIX + history_file.name, history_file))
    for key, path in entries:
        data = path.read_bytes()
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        sha = register(data, media_type, f"design-session/{key}")
        files[key] = {"sha256": sha, "size": len(data), "media_type": media_type}
    return {"schema_version": 1, "files": files}


def restore_session(
    session_dir: Path,
    manifest: dict,
    *,
    read_blob: Callable[[str], tuple[str, bytes]],
    history_file: Path | None,
) -> int:
    restored = 0
    for key, entry in (manifest.get("files") or {}).items():
        if key.startswith(_HISTORY_KEY_PREFIX):
            if history_file is None:
                continue
            target = history_file
        else:
            target = session_dir / key
            if not target.resolve().is_relative_to(session_dir.resolve()):
                continue
        _, data = read_blob(entry["sha256"])
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise RuntimeError(f"session blob digest mismatch for {key}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        restored += 1
    return restored


__all__ = ["MAX_FILE_BYTES", "restore_session", "snapshot_session"]
```

- [ ] **Step 4: Wire into the two runtime entry points in `main.py`**

Inside `run_agent_turn_preview` (and the web twin), once `config` is final and `session_id` is set:

```python
    session_dir = config.session_dir()
    history_file = None if session_dir is None else config.trace_dir / "conversation_history" / f"{session_id}.md"
    if session_dir is not None and not session_dir.exists() and session_manifest is not None:
        restored = restore_session(session_dir, session_manifest, read_blob=turn_blobs.read_blob, history_file=history_file)
        logger.info("design_session.restored", session_id=session_id, files=restored)
    ... run_deepagent_turn(...) ...
    if session_dir is not None:
        manifest = snapshot_session(session_dir, register=lambda data, mt, src: turn_blobs.register(data, media_type=mt, source_key=src), history_file=history_file)
        manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
        response["session_manifest_sha256"] = turn_blobs.register(manifest_bytes, media_type="application/json", source_key="design-session/manifest")
```

`session_manifest` is a new keyword the executors pass, read in the executor with the same `_bridge._run` idiom: the newest succeeded run's `result_json->'session_manifest_sha256'` for the document (add `latest_session_manifest(conn, *, workspace_id, document_id) -> dict | None` to `clue_design/sessions.py`, loading the blob through the store's `read_blob`). Note: `harness.py` applies `trace_dir / "scene-candidate"` for the candidate bundle AFTER `run_agent_turn_preview` builds `config`; `config.session_dir()` must therefore be computed from the SAME adjusted trace dir — expose `lumen_agent.harness.effective_runtime_config(config) -> AgentRuntimeConfig` (the candidate `replace` extracted into a pure function, used by both `create_design_deepagent` and this sync code) so the two never disagree on where the session lives.

- [ ] **Step 5: Run** — `uv run pytest subsystems/clue-design/apps/agent_runtime/tests/test_session_sync.py subsystems/clue-design/apps/api/tests/test_scene_turn_persist.py -q -p no:cacheprovider` → PASS (add one assertion to `test_scene_turn_persist.py` that a session run's response carries `session_manifest_sha256`).

- [ ] **Step 6: Commit** — `git add subsystems/clue-design && git commit -m "feat(design): sync the session folder and conversation history to storage at turn end; restore on a fresh worker"`.

---

### Task 9: Erasure removes the session folder and history; docs and memory

**Files:**
- Modify: `platform/api/clue_api/agent_turn_wiring.py` (`erase_artifacts` around `:2152-2237`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/fleet_handler.py` docstring (`:661-663`, "thread id is the design run id" → the session)
- Modify: `.env.example` (comment only, beside `LUMEN_AGENT_TRACE_DIR`: sessions live under `<trace_dir>/sessions/`; no key change)
- Modify: `_memory/2026-09-18-design-session-continuity.md` (closing entry)
- Test: `tests/api/test_design_memory_privacy_db.py` (extend) or new `tests/api/test_design_session_erasure_db.py`

- [ ] **Step 1: Failing test**

```python
async def test_erasure_removes_the_session_folder_and_its_history(erasure_harness, tmp_path, monkeypatch) -> None:
    sid = design_session_id(erasure_harness.workspace_id, "doc_e")
    root = tmp_path
    (root / "sessions" / sid / "workspace").mkdir(parents=True)
    (root / "conversation_history").mkdir()
    (root / "conversation_history" / f"{sid}.md").write_text("h", encoding="utf-8")
    monkeypatch.setenv("LUMEN_AGENT_TRACE_DIR", str(root))
    await erasure_harness.seed_design_run(document_id="doc_e", checkpoint_thread_id=sid)
    await erasure_harness.erase_project()
    assert not (root / "sessions" / sid).exists()
    assert not (root / "conversation_history" / f"{sid}.md").exists()
```

Model `erasure_harness` on the fixtures in `tests/api/test_design_memory_privacy_db.py` (it already drives `erase_artifacts` over seeded design rows).

- [ ] **Step 2: Run to verify it fails** — `set -a; source .env; set +a; uv run pytest tests/api/test_design_session_erasure_db.py -q -p no:cacheprovider` → FAIL (folder survives).

- [ ] **Step 3: Implement**

In `erase_artifacts`, after the design-run scrub (`~:2220`), add:

```python
            session_threads = sorted(
                {str(row["checkpoint_thread_id"]) for row in design_rows
                 if str(row["checkpoint_thread_id"]).startswith("dsess_")}
            )
            if session_threads:
                removed = self._design_sessions.erase(session_threads)
                log.info("erase.design_sessions_removed", workspace_id=workspace_id, count=removed)
```

with a small collaborator injected at the composition root (same place `_workspaces` is), `clue_api.design_sessions.DesignSessionEraser(trace_dir: Path)` whose `erase(session_ids) -> int` does `shutil.rmtree(trace_dir / "sessions" / sid, ignore_errors=True)` and unlinks `trace_dir / "conversation_history" / f"{sid}.md"`, for both `trace_dir` and `trace_dir / "scene-candidate"`. The trace dir comes from `lumen_agent.config.AgentRuntimeConfig.from_env(repo_root).trace_dir` through the same lazy import pattern `design_fleet.py` uses (fail-loud `DesignRuntimeUnavailable` only when `design_runtime_enabled`; a no-op eraser otherwise). The checkpoint tables are already deleted by thread id at `:2130-2149`; the session id is in that set because Task 2 stored it on the run rows.

- [ ] **Step 4: Docs and memory** — update the `fleet_handler.py` docstring, add the `.env.example` comment, and append the closing entry to the memory note (commits, verification, owed live proofs from spec §7).

- [ ] **Step 5: Run** — the erasure test plus `tests/api/test_design_memory_privacy_db.py tests/api/test_design_leg_receipts_db.py` → PASS.

- [ ] **Step 6: Commit** — `git add platform/api/clue_api .env.example subsystems/clue-design/apps/api/lumen_api/fleet_handler.py _memory tests/api && git commit -m "feat(erasure): remove a design session's folder and conversation history with its runs; docs"`.

---

### Task 10: Whole-branch gates and the live acceptance checklist

- [ ] **Step 1: Static gates** — `uv run ruff check` and `uv run ruff format --check` on every touched file under `platform/` and `subsystems/design/`; `uv run mypy` (expect only the four pre-existing errors); `uv run lint-imports` (28 kept / 0 broken). The design subsystem stays outside root ruff/mypy; run `uv run ruff check` on the touched `lumen_agent`/`lumen_api` files only and compare with the baseline count on HEAD.
- [ ] **Step 2: Suites (stack DOWN, `.env` sourced)** — `tests/design tests/api/test_design_leg_session_db.py tests/api/test_design_session_erasure_db.py tests/api/test_design_leg_receipts_db.py tests/api/test_genweb_web_turn_dispatch_db.py --ignore-glob='*_live.py' -p no:cacheprovider`; then the agent-runtime suites named in Tasks 3–8 plus `test_materialize_concurrency.py`, `test_workspace_run_isolation.py`; then `subsystems/clue-design/apps/api/tests/test_scene_turn_persist.py test_web_turns.py test_agent_run_write_lock.py test_ad_assets_runtime_composition.py test_spend_scope.py test_scoped_preferences_delivery.py`.
- [ ] **Step 3: Stack up** — `./scripts/dev_stack_san_salvador.sh up`, `status` shows every process UP.
- [ ] **Step 4: Live acceptance (founder-triggered, spends money; record in the memory note)** — spec §7 items 1–4: (1) two turns on one ad → second turn's Langfuse trace shows `turn.checkpoint_continue`, no skill reads, fewer model calls; `SELECT checkpoint_thread_id FROM design_agent_run WHERE document_id=… ORDER BY created_at` shows one `dsess_` id for both; (2) a hand edit between turns → the drift note in the second turn's opening prompt (trace.jsonl under `turns/<run_id>/`) and no conflict; (3) a forced overflow across turns → `conversation_history/<dsess_id>.md` exists and the agent answers a question about turn one; (4) delete the session folder on the host, send a turn → `design_session.restored` in the worker log.

---

## Self-review

- **Spec coverage.** §3.1 session identity → Tasks 1–2; §3.2 folder → Task 3 (+ sync in Task 8); §3.3 continued context and library compaction → Tasks 4–5 (the middleware is already installed on both solo and web graphs; Task 4 only lets its history file through the fence); §3.4 session-bound tools + resume branch → Tasks 3, 5, 6; §3.5 drift → Tasks 1, 6; §3.6 sub-agents → moot in solo mode (founder, 2026-09-18), no task; §3.7 reasoning text → Task 7; §4 unchanged surfaces → no task touches run/lease/receipt/leg/exit-judge code beyond thread naming; §6 erasure → Task 9; §6 trigger/keep → library defaults, revisit after acceptance item 3; §7 acceptance → Task 10.
- **Placeholder scan.** Every code step carries the code; the few "copy the fixture from file X" instructions name the file and lines. Task 8's `latest_session_manifest` is named with its signature and its home.
- **Type consistency.** `session_id` is a `str | None` on `AgentRuntimeConfig` (Task 3) and a keyword on both runtime entry points (Task 6, Task 8); `workspace_scope_id` (Task 3) is consumed by Task 4; `run_id=` on `invoke_turn_graph` (Task 5) is passed from both harnesses; `session_continued` flows fleet_handler → executors (Task 6); `first_turn_of_leg` is written by Task 2 and read by Task 6; `checkpoint_thread_id` on the run row (Task 2) is what Task 9's erasure filters on.
