# ARV2 Research Job Resume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A stopped ARV2 research job continues its saved conversation when re-claimed, restarts fresh inside the same job when its instructions changed, and can be resumed by a developer script or an admin endpoint with an audited allowance top-up.

**Architecture:** The agent runtime gains an opt-in "continue this turn's own saved state" mode. The research runner turns it on and stops writing a second opening-context receipt; on re-claim it compares the fresh context against the recorded one and only logs what drifted. A job-level restart counter feeds one shared execution-id function, so a restart is a new conversation under the same job, keeping purchases, claims and allowance. One module, `clue_api/arv2/job_resume.py`, owns identity, the restart signal, the stuck-job listing and the audited resume operation; the script and the endpoints call it.

**Tech Stack:** Python 3.12, SQLAlchemy async + asyncpg, Alembic (hand-written, hash ids), LangGraph checkpoints, FastAPI (`/frontend/v1`), pytest with real Postgres.

**Spec:** `docs/superpowers/specs/2026-10-14-arv2-research-job-resume-design.md` (founder-approved 2026-10-14, with rulings: script + list/resume endpoints, audited top-up, restart fresh on changed instructions, leave the six frozen 2026-10-03 jobs).

## Global Constraints

- No AI attribution in commits (CLAUDE.md overrides any attribution template). Commit locally; never push.
- Alembic: create the revision with `alembic revision -m "<slug>"` (random hash id), `down_revision` = the current single head; `upgrade()` and `downgrade()` both hand-written and reversible; named constraints and indexes. `alembic heads` must show exactly one head afterwards.
- No new runtime flags (spec §3.8). If you add one anyway, it goes into `.env.example` with its default in the same commit.
- Tests that touch the database run only on this plan's throwaway database, with no provider keys in the environment (`env -i`). Never run the full suite with real keys; never run a `*_live.py` test.
- Restart 0 must derive exactly today's execution id, `uuid5(NAMESPACE_URL, f"research-quality:{job_id}")`, so every existing job and its saved state keeps its id.
- A completed turn is never re-executed; used allowance counters are never reset; a top-up only adds to limits.
- Refusals are named codes, never silent no-ops.

## Plan rulings against the spec

These are decisions this plan makes where the spec left room or where the code showed a cheaper equivalent. The executor follows them; each costs little if wrong.

1. **No checkpoint yet (spec §3.1).** Instead of rebuilding the opening messages from the receipt's references: if the fresh context matches the receipt, start normally; if it drifted, raise `ResearchRestartRequired("context_changed_before_start")`. No checkpoint means no model call ran under the recorded context, so a fresh conversation loses nothing. Cost if wrong: one wasted restart in a millisecond-wide crash window.
2. **The resume path still assembles** (spec §3.1 said "do not assemble again"), with a receipt store that compares and never writes. The workspace's seed files come from assembly, so skipping it would break workspace verification. The recorded manifest replaces the fresh one, so every downstream reference names the recorded bundle. The comparison logs the drifted layers, which also answers the open question of what differed for the Doetsch job.
3. **Refusal codes.** `run_cancelled` is dropped: runs have no cancelled state (their status CHECK uses the job statuses). `research_stopped` is added for a generation a user suspended. `job_not_started` is added, because a held-back person job is not stuck. `outputs_frozen` is detected by `failure_code = 'workspace_conflict'`, the only producer of that state, fixed in `9f0d8b51e`.
4. **Reconciliation units keep their ids.** `research_execution_id(job, n, unit_key)` ignores the restart count when `unit_key` is set. Only the job's main conversation moves on a restart.
5. **A specialist whose context drifted before its first step** proceeds with the fresh context and logs the drift. Instruction changes restart the parent first, so this needs a crash inside a child's first milliseconds. Recorded as a residual.
6. **A second resume of a queued job** is a `409 job_already_queued` that writes nothing.
7. **The stranded-job requeue script** reuses the new shared offer helper, so the job-offer call exists once.
8. **Pinned bundle edits.** These are still caught earlier by the launch-pin check, which settles `needs_review` with a relaunch message, by design. The restart covers profile and tool-surface changes outside the bundle pin.
9. **Spec §4 test 4, "the account pages are rewritten".** This is covered by the unchanged settle path and the founder-triggered live proof (Task 9), not by a new scripted page test. A resumed job is `suspended`, which the generation already treats as unsettled: `pending_continuations` waits on any child whose status is not `completed`, `needs_review` or `failed`. When the resumed job settles, the existing `record_child_result` and signal path rewrites the pages. No generation code changes.

## Review Focus

1. **Resuming a job a live worker still holds** (its task is `claimed`) must refuse and write nothing, never start a second driver. Covered in Task 5: `test_a_job_with_an_open_task_is_refused_and_writes_nothing`.
2. **A topped-up job re-claimed later** must bind its execution without "research recovery cannot reset the shared allowance". Covered in Task 5: `test_a_topped_up_allowance_binds_on_the_next_claim`.
3. **A job restarted twice** gets a third distinct execution, and the second restart counts from the first. Covered in Task 2 (`test_each_restart_gets_its_own_stable_id`) and Task 4 (`test_a_second_restart_counts_from_the_first`).
4. **Another workspace's job id** at either endpoint is a 404 that looks exactly like a missing job. Covered in Task 7: `test_another_workspaces_job_is_not_found`.
5. **A specialist that was mid-flight when the worker stopped** resumes once and reserves its delegation once. Covered in Task 3: `test_a_specialist_stopped_mid_turn_resumes_once`.

---

## File structure

| File | Responsibility |
|---|---|
| `platform/agents/clue_agents/runtime.py` (modify) | `resume_saved_turn` flag: a turn whose own saved state exists continues it. |
| `alembic/versions/<hash>_arv2_research_job_resume.py` (create) | `arv2_research_job.restart_count`; `arv2_research_job_resume` audit table. |
| `platform/api/clue_api/arv2/job_resume.py` (create) | Execution identity, restart signal, top-up, audit, restart-on-claim, stuck listing, resume operation, job offer. |
| `platform/api/clue_api/arv2/account_research_store.py` (modify) | `JobRow.restart_count`. |
| `platform/api/clue_api/arv2/account_research_claims.py` (modify) | `JobScope.restart_count`. |
| `platform/api/clue_api/arv2/account_research_driver.py` (modify) | Scope carries the counter; restart signal → restart, park, requeue. |
| `platform/api/clue_api/arv2/quality_reconciliation.py` (modify) | Shared execution id. |
| `platform/api/clue_api/arv2/quality_execution.py` (modify) | `bind_execution` accepts recorded top-ups. |
| `platform/api/clue_api/agent_turn_wiring.py` (modify) | `DbAgentReplayReader.read_context_receipt`. |
| `platform/api/clue_api/agent_platform_wiring.py` (modify) | Assembler accepts an injected receipt store. |
| `platform/api/clue_api/quality_research_wiring.py` (modify) | Shared execution id; comparing receipts; instruction-change and drift rules; runtime flag. |
| `platform/api/clue_api/specialist_wiring.py` (modify) | Runtime flag for specialists. |
| `platform/api/clue_api/frontend_read/research_jobs.py` (create) | `GET /research/jobs/stuck`, `POST /research/jobs/{job_id}/resume`. |
| `platform/api/clue_api/frontend_read/settings.py` (modify) | Registers the research job routes. |
| `scripts/resume_arv2_research_job.py` (create) | Developer script, dry run by default. |
| `scripts/requeue_stranded_arv2_research_jobs.py` (modify) | Uses the shared offer helper. |
| `CLAUDE.md`, `AGENTS.md` (modify) | One runbook paragraph pointing at the script and endpoints. |
| Tests | `tests/agents/test_runtime_resume.py`, `tests/arv2/test_job_resume_identity.py`, `tests/arv2/test_quality_resume_db.py`, `tests/arv2/test_job_restart_db.py`, `tests/arv2/test_job_resume_db.py`, `tests/arv2/test_resume_script_db.py`, `tests/auth/test_research_jobs_api.py`, `tests/db/test_arv2_job_resume_migration.py` |

---

## Setup (before Task 1)

- [ ] **S1: Branch.** The spec lives on local branch `research/job-resume-spec` (worktree `scratchpad/arv2-resume`). If PR #115 (deadlock fix) has merged into `origin/research-streaming`, rebase onto it first; Task 5 edits the lines right after #115's lock change.

```bash
cd /private/tmp/claude-501/-Users-aryankeshri-conductor-workspaces-research-and-data-dushanbe/03c67e43-6e5f-458f-8b4a-8961a2a699b4/scratchpad/arv2-resume
git fetch -q origin research-streaming
git checkout -b research/job-resume
git rebase origin/research-streaming
```

- [ ] **S2: Throwaway database.** Create it once; the DB fixtures migrate it to head.

```bash
docker exec clue-pg-papeete psql -U clue -d postgres -c "CREATE DATABASE clue_dushanbe_resume"
```

- [ ] **S3: Test runner.** Tests use the dushanbe virtualenv with the worktree's packages first on `PYTHONPATH`, and an empty environment so no provider key can leak in. Declare `rt` in every shell you run tests from:

```bash
W=/private/tmp/claude-501/-Users-aryankeshri-conductor-workspaces-research-and-data-dushanbe/03c67e43-6e5f-458f-8b4a-8961a2a699b4/scratchpad/arv2-resume
D=/Users/aryankeshri/conductor/workspaces/research-and-data/dushanbe
SP=$(ls -d $D/.venv/lib/python*/site-packages)
PP="$W:$(for f in $SP/_editable_impl_*.pth; do head -1 "$f" | grep '^/'; done | sed "s#^$D#$W#" | sort -u | paste -sd: -)"
DBURL=$(grep '^CLUE_DATABASE_URL=' $D/.env | cut -d= -f2- | sed 's#/clue_dushanbe$#/clue_dushanbe_resume#')
rt() { (cd "$W" && env -i PATH="$PATH" HOME="$HOME" CLUE_DATABASE_URL="$DBURL" PYTHONPATH="$PP" "$D/.venv/bin/python" -m pytest -p no:cacheprovider -o addopts="" -q -rfEs "$@"); }
```

Check: `rt tests/agents/test_runtime_continuation.py` → `1 passed`.

---

### Task 1: The runtime continues a turn's own saved state

**Files:**
- Modify: `platform/agents/clue_agents/runtime.py` (constructor at `class DeepAgentTurnRuntime.__init__`; `_run_turn` state construction)
- Test: `tests/agents/test_runtime_resume.py`

**Interfaces:**
- Produces: `DeepAgentTurnRuntime(..., resume_saved_turn: bool = False)`. With `True` and no `continuation_config`, a turn whose thread (`thread_id=str(execution_id)`, `checkpoint_ns=""`) already has saved values is invoked with `None` input, so LangGraph runs its pending step without re-inserting the opening messages.

- [ ] **Step 1: Write the failing test**

```python
"""A re-claimed first turn continues its own saved conversation (spec 2026-10-14 §3.1).

The research runner opens every turn fresh. When a worker dies mid-turn and the job is claimed
again, the same turn runs again; with ``resume_saved_turn`` the runtime continues the turn's own
saved state instead of feeding the opening messages into it a second time.
"""

from __future__ import annotations

from typing import Any, cast

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from clue_agents import AgentTurnRequest, AssembledAgentContext, DeepAgentTurnRuntime
from clue_agents.model import ScriptedAgentChatModel
from clue_api.agent_runtime_wiring import GovernedAgentToolFactory
from clue_api.toolbelt_wiring import build_toolbelt
from tests.agents.test_contracts import context_manifest
from tests.agents.test_runtime import _CaptureModelInput
from tests.agents.test_runtime import _request
from tests.agents.test_runtime_continuation import (
    _CrashingModel,
    _FirstRequest,
    _Models,
    _SharedSaverExecution,
)
from tests.db.conftest import run_async

OPENING = "Research the account: resume marker 41c2."


def _run(
    request: AgentTurnRequest,
    resolved: Any,
    execution: _SharedSaverExecution,
    model: ScriptedAgentChatModel,
    messages: tuple[BaseMessage, ...],
    *,
    resume_saved_turn: bool,
    capture: _CaptureModelInput | None = None,
) -> Any:
    runtime = DeepAgentTurnRuntime(
        models=_Models(model),
        execution=execution,
        max_runtime_s=10,
        resume_saved_turn=resume_saved_turn,
    )
    tools = GovernedAgentToolFactory(
        request=request,
        resolved_profile=resolved,
        registry=build_toolbelt(storage=None, gateway=None),
        execution=cast(Any, execution),
        lease=cast(Any, object()),
        artifacts=cast(Any, object()),
    ).build()
    return run_async(
        runtime.run(
            request=request,
            resolved_profile=resolved,
            context=AssembledAgentContext(
                manifest=context_manifest().model_copy(
                    update={"execution_id": request.constitution.execution_id}
                ),
                messages=messages,
            ),
            backend=None,
            governed_tools=tools,
            callbacks=(capture,) if capture is not None else (),
        )
    )


def test_a_reclaimed_first_turn_continues_its_saved_conversation() -> None:
    request, resolved = _request()
    execution = _SharedSaverExecution(InMemorySaver())
    opening = (HumanMessage(content=OPENING),)

    crashed = _run(
        request,
        resolved,
        execution,
        _CrashingModel(responses=(AIMessage(content="never"),)),
        opening,
        resume_saved_turn=True,
    )
    assert crashed.status.value == "failed"

    capture = _FirstRequest()
    _run(
        request,
        resolved,
        execution,
        ScriptedAgentChatModel(
            responses=(AIMessage(content="Answer."), AIMessage(content="Done."))
        ),
        opening,
        resume_saved_turn=True,
        capture=capture,
    )
    sent = [str(getattr(message, "content", "")) for message in capture.messages[0]]
    assert sent.count(OPENING) == 1


def test_a_turn_with_no_saved_state_opens_with_its_messages() -> None:
    request, resolved = _request()
    execution = _SharedSaverExecution(InMemorySaver())
    capture = _FirstRequest()
    _run(
        request,
        resolved,
        execution,
        ScriptedAgentChatModel(
            responses=(AIMessage(content="Answer."), AIMessage(content="Done."))
        ),
        (HumanMessage(content=OPENING),),
        resume_saved_turn=True,
        capture=capture,
    )
    sent = [str(getattr(message, "content", "")) for message in capture.messages[0]]
    assert sent.count(OPENING) == 1
```

- [ ] **Step 2: Run it to verify it fails**

Run: `rt tests/agents/test_runtime_resume.py`
Expected: FAIL in both tests with `TypeError: DeepAgentTurnRuntime.__init__() got an unexpected keyword argument 'resume_saved_turn'`.

- [ ] **Step 3: Implement**

In `DeepAgentTurnRuntime.__init__`, add the parameter after `max_finalize_repairs: int | None = None,`:

```python
        resume_saved_turn: bool = False,
```

and next to `self._continuation_config = continuation_config`:

```python
        # A caller whose turns are re-claimed after a crash (research jobs) continues the turn's
        # own saved state instead of feeding its opening messages in a second time.
        self._resume_saved_turn = resume_saved_turn
```

In `_run_turn`, the `if self._continuation_config is not None:` block ends with `state = Command(update={"_summarization_event": ...})`. Directly after that block, at the same indentation as its `if`, and before `try:`, add:

```python
            elif self._resume_saved_turn:
                destination = {
                    "configurable": {
                        "thread_id": str(constitution.execution_id),
                        "checkpoint_ns": "",
                    }
                }
                current = await graph.aget_state(cast(RunnableConfig, destination))
                if current.values:
                    # Spec 2026-10-14 §3.1: the saved state already holds this turn's opening
                    # messages; LangGraph runs the pending step from it.
                    state = None
```

- [ ] **Step 4: Run the tests**

Run: `rt tests/agents/test_runtime_resume.py tests/agents/test_runtime_continuation.py tests/agents/test_runtime.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add platform/agents/clue_agents/runtime.py tests/agents/test_runtime_resume.py
git commit -m "Agent runtime: a re-claimed turn can continue its own saved state

Research turns are always first turns, so the redelivery branch that continuation turns use
never applied to them: a re-claimed research turn fed its opening messages into the saved
conversation a second time. resume_saved_turn (default off) continues the turn's own saved
state when it exists. Spec docs/superpowers/specs/2026-10-14-arv2-research-job-resume-design.md §3.1."
```

---

### Task 2: Restart identity — counter, audit table, one execution-id function

**Files:**
- Create: `alembic/versions/<hash>_arv2_research_job_resume.py`
- Create: `platform/api/clue_api/arv2/job_resume.py`
- Modify: `platform/api/clue_api/arv2/account_research_store.py` (`JobRow`, `_job`)
- Modify: `platform/api/clue_api/arv2/account_research_claims.py` (`JobScope`)
- Modify: `platform/api/clue_api/quality_research_wiring.py` (`ResearchUnitRuntime.__init__` execution id; `run()` reconciliation `source_execution`)
- Modify: `platform/api/clue_api/arv2/quality_reconciliation.py` (`account_research_model`)
- Modify: `platform/api/clue_api/arv2/account_research_driver.py` (`_compose_quality`)
- Test: `tests/arv2/test_job_resume_identity.py`, `tests/db/test_arv2_job_resume_migration.py`

**Interfaces:**
- Produces: `research_execution_id(job_id: UUID, restart_count: int = 0, unit_key: str | None = None) -> UUID`
- Produces: `class ResearchRestartRequired(RuntimeError)` with attribute `reason: RestartReason`, where `RestartReason = Literal["instructions_changed", "context_changed_before_start"]`
- Produces: `JobRow.restart_count: int`, `JobScope.restart_count: int = 0`
- Produces: tables `arv2_research_job.restart_count` and `arv2_research_job_resume(resume_id, workspace_id, job_id, attempt_before, actor, reason, restarted, top_up_model_calls, top_up_tool_calls, top_up_delegations, top_up_runtime_ms, created_at)`

- [ ] **Step 1: Write the failing tests**

`tests/arv2/test_job_resume_identity.py`:

```python
"""One function derives a research job's execution id (spec 2026-10-14 §3.2)."""

from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest

from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.job_resume import ResearchRestartRequired, research_execution_id


def test_restart_zero_is_the_id_every_job_already_has():
    job = uuid4()
    assert research_execution_id(job) == uuid5(NAMESPACE_URL, f"research-quality:{job}")
    assert research_execution_id(job, 0) == research_execution_id(job)


def test_each_restart_gets_its_own_stable_id():
    job = uuid4()
    ids = [research_execution_id(job, n) for n in range(3)]
    assert len(set(ids)) == 3
    assert research_execution_id(job, 2) == ids[2]


def test_a_reconciliation_unit_keeps_its_id_across_restarts():
    job = uuid4()
    legacy = uuid5(NAMESPACE_URL, f"research-quality:{job}:rev-3")
    assert research_execution_id(job, 0, "rev-3") == legacy
    assert research_execution_id(job, 4, "rev-3") == legacy


def test_a_negative_restart_count_is_refused():
    with pytest.raises(ValueError):
        research_execution_id(uuid4(), -1)


def test_the_restart_signal_names_its_reason():
    error = ResearchRestartRequired("instructions_changed")
    assert error.reason == "instructions_changed"


def test_a_job_scope_starts_at_restart_zero():
    assert JobScope.__dataclass_fields__["restart_count"].default == 0
```

`tests/db/test_arv2_job_resume_migration.py`:

```python
"""``arv2_research_job.restart_count`` and the ``arv2_research_job_resume`` audit table."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from clue_db import db_lifespan

from .conftest import run_async


@pytest.mark.usefixtures("require_db")
def test_restart_counter_and_audit_table_exist_with_their_checks() -> None:
    async def scenario() -> tuple[object, list[str]]:
        async with db_lifespan() as engine, engine.connect() as conn:
            column = (
                await conn.execute(
                    text(
                        "SELECT column_default FROM information_schema.columns "
                        "WHERE table_name='arv2_research_job' AND column_name='restart_count'"
                    )
                )
            ).scalar_one_or_none()
            checks = (
                await conn.execute(
                    text(
                        "SELECT conname FROM pg_constraint WHERE conname IN ("
                        "'arv2_research_job_restart_count','arv2_research_job_resume_reason',"
                        "'arv2_research_job_resume_actor','arv2_research_job_resume_top_up') "
                        "ORDER BY conname"
                    )
                )
            ).scalars().all()
        return column, list(checks)

    column, checks = run_async(scenario())
    assert column == "0"
    assert checks == [
        "arv2_research_job_restart_count",
        "arv2_research_job_resume_actor",
        "arv2_research_job_resume_reason",
        "arv2_research_job_resume_top_up",
    ]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `rt tests/arv2/test_job_resume_identity.py tests/db/test_arv2_job_resume_migration.py`
Expected: identity tests ERROR with `ModuleNotFoundError: No module named 'clue_api.arv2.job_resume'`; the migration test FAILS with `assert None == '0'`.

- [ ] **Step 3: Create the migration**

```bash
cd $W && PYTHONPATH="$PP" $D/.venv/bin/alembic heads && PYTHONPATH="$PP" $D/.venv/bin/alembic revision -m "arv2 research job resume"
```

Replace the generated file's body below the header docstring's `Revision ID`/`Revises` lines with this (keep the generated `revision` and `down_revision` values; `down_revision` must be the head printed above):

```python
"""arv2 research job resume: restart counter and resume audit

Revision ID: <keep generated>
Revises: <keep generated>

Spec docs/superpowers/specs/2026-10-14-arv2-research-job-resume-design.md §3.2 and §3.5:
``restart_count`` gives a job a fresh conversation identity without a new job; every resume and
restart writes one ``arv2_research_job_resume`` row (who, why, attempt, any allowance top-up).
"""

from __future__ import annotations

from alembic import op

# keep the generated revision identifiers here


def upgrade() -> None:
    op.execute("ALTER TABLE arv2_research_job ADD COLUMN restart_count integer NOT NULL DEFAULT 0")
    op.execute(
        "ALTER TABLE arv2_research_job ADD CONSTRAINT arv2_research_job_restart_count "
        "CHECK (restart_count >= 0)"
    )
    op.execute("""CREATE TABLE arv2_research_job_resume (
        resume_id uuid PRIMARY KEY,
        workspace_id text NOT NULL,
        job_id uuid NOT NULL REFERENCES arv2_research_job(job_id),
        attempt_before integer NOT NULL,
        actor text NOT NULL,
        reason text NOT NULL,
        restarted boolean NOT NULL,
        top_up_model_calls integer NOT NULL DEFAULT 0,
        top_up_tool_calls integer NOT NULL DEFAULT 0,
        top_up_delegations integer NOT NULL DEFAULT 0,
        top_up_runtime_ms bigint NOT NULL DEFAULT 0,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT arv2_research_job_resume_reason CHECK (length(btrim(reason)) > 0),
        CONSTRAINT arv2_research_job_resume_actor CHECK (length(btrim(actor)) > 0),
        CONSTRAINT arv2_research_job_resume_top_up CHECK (
            top_up_model_calls >= 0 AND top_up_tool_calls >= 0
            AND top_up_delegations >= 0 AND top_up_runtime_ms >= 0)
    )""")
    op.execute(
        "CREATE INDEX arv2_research_job_resume_job "
        "ON arv2_research_job_resume(workspace_id, job_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE arv2_research_job_resume")
    op.execute("ALTER TABLE arv2_research_job DROP CONSTRAINT arv2_research_job_restart_count")
    op.execute("ALTER TABLE arv2_research_job DROP COLUMN restart_count")
```

- [ ] **Step 4: Create `job_resume.py` with identity and the restart signal**

```python
"""Resume or restart a stopped ARV2 research job.

Spec: docs/superpowers/specs/2026-10-14-arv2-research-job-resume-design.md. One identity function
(§3.2), one restart signal, and one audited resume operation (§3.5) that the developer script
(§3.6) and the admin endpoints (§3.7) share.
"""

from __future__ import annotations

from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

RestartReason = Literal["instructions_changed", "context_changed_before_start"]


def research_execution_id(
    job_id: UUID, restart_count: int = 0, unit_key: str | None = None
) -> UUID:
    """The execution a research job's conversation runs under.

    Restart 0 is the id every job had before restarts existed, so existing jobs keep their saved
    state. A reconciliation unit keeps its own id whatever the restart count: only the job's main
    conversation moves on a restart.
    """
    if restart_count < 0:
        raise ValueError("a restart count is never negative")
    if unit_key:
        return uuid5(NAMESPACE_URL, f"research-quality:{job_id}:{unit_key}")
    if restart_count == 0:
        return uuid5(NAMESPACE_URL, f"research-quality:{job_id}")
    return uuid5(NAMESPACE_URL, f"research-quality:{job_id}:restart:{restart_count}")


class ResearchRestartRequired(RuntimeError):
    """The job's saved conversation cannot be continued; the driver gives it a fresh one."""

    def __init__(self, reason: RestartReason) -> None:
        super().__init__(f"research job needs a fresh conversation: {reason}")
        self.reason: RestartReason = reason
```

- [ ] **Step 5: Carry the counter on the job row and the scope**

In `account_research_store.py`, add to `JobRow` after `selection_claim_ids: tuple[UUID, ...] | None = None`:

```python
    #: How many times the job was given a fresh conversation (spec 2026-10-14 §3.2).
    restart_count: int = 0
```

and in `_job(...)`, after the `selection_claim_ids=...` argument:

```python
        restart_count=int(row.get("restart_count") or 0),
```

In `account_research_claims.py`, add to `JobScope` after `input_refs: Mapping[str, Any] | None = None`:

```python
    #: The job's restart counter; selects which conversation the job runs (spec 2026-10-14 §3.2).
    restart_count: int = 0
```

- [ ] **Step 6: Use the one id function at all three sites**

In `quality_research_wiring.py` add `from clue_api.arv2.job_resume import ResearchRestartRequired, research_execution_id` beside the other `clue_api.arv2` imports. Replace the `self.execution_id = ExecutionId(uuid5(...))` block in `ResearchUnitRuntime.__init__` with:

```python
        self.execution_id = ExecutionId(
            research_execution_id(scope.job_id, scope.restart_count, unit_key)
        )
```

and in `run()` replace the reconciliation `source_execution = ExecutionId(uuid5(NAMESPACE_URL, f"research-quality:{self.scope.job_id}"))` with:

```python
            source_execution = ExecutionId(
                research_execution_id(self.scope.job_id, self.scope.restart_count)
            )
```

In `quality_reconciliation.py`, in `account_research_model`, replace `execution_id = uuid5(NAMESPACE_URL, f"research-quality:{scope.job_id}")` with:

```python
    execution_id = research_execution_id(scope.job_id, scope.restart_count)
```

and add `from clue_api.arv2.job_resume import research_execution_id`. Remove `uuid5`/`NAMESPACE_URL` from that module's imports only if ruff reports them unused.

In `account_research_driver.py`, in `_compose_quality`, immediately after the `if person: ... else: ...` block that assigns `scope` (before the line `from clue_api.arv2.person_research_brief import person_task_instruction, read_person_brief`), add:

```python
        # Spec 2026-10-14 §3.2: the counter picks which conversation this job runs.
        scope = replace(scope, restart_count=job.restart_count)
```

- [ ] **Step 7: Run the tests**

Run: `rt tests/arv2/test_job_resume_identity.py tests/db/test_arv2_job_resume_migration.py tests/arv2/test_quality_runtime_db.py tests/arv2/test_quality_driver_db.py tests/arv2/test_quality_reconciliation_db.py`
Expected: all pass. `PYTHONPATH="$PP" $D/.venv/bin/alembic heads` prints one head.

- [ ] **Step 8: Commit**

```bash
git add alembic/versions/*_arv2_research_job_resume.py platform/api/clue_api/arv2/job_resume.py \
  platform/api/clue_api/arv2/account_research_store.py platform/api/clue_api/arv2/account_research_claims.py \
  platform/api/clue_api/quality_research_wiring.py platform/api/clue_api/arv2/quality_reconciliation.py \
  platform/api/clue_api/arv2/account_research_driver.py \
  tests/arv2/test_job_resume_identity.py tests/db/test_arv2_job_resume_migration.py
git commit -m "ARV2 research: restart counter, resume audit table, one execution-id function

A job's conversation identity was derived in three places from the job id alone, so a job could
never get a fresh conversation. research_execution_id(job, restart_count) replaces the three
derivations; restart 0 is today's id, so existing jobs keep their saved state. Adds
arv2_research_job.restart_count and the arv2_research_job_resume audit table.
Spec 2026-10-14 §3.2, §3.5."
```

---

### Task 3: The research runner resumes instead of rebuilding

**Files:**
- Modify: `platform/api/clue_api/agent_turn_wiring.py` (`DbAgentReplayReader`)
- Modify: `platform/api/clue_api/agent_platform_wiring.py` (`build_agent_context_assembler`)
- Modify: `platform/api/clue_api/quality_research_wiring.py` (`_Contexts`, `ResearchUnitRuntime.__init__`, `ResearchUnitRuntime.run`)
- Modify: `platform/api/clue_api/specialist_wiring.py` (the `DeepAgentTurnRuntime(` call in the specialist runner)
- Test: `tests/arv2/test_quality_resume_db.py`

**Interfaces:**
- Consumes: `DeepAgentTurnRuntime(resume_saved_turn=...)` (Task 1); `ResearchRestartRequired`, `research_execution_id` (Task 2)
- Produces: `DbAgentReplayReader.read_context_receipt(*, workspace_id: str, turn_id: UUID) -> AgentContextReplayReceipt | None`
- Produces: `build_agent_context_assembler(..., receipts: ContextReceiptStore | None = None)`
- Produces: `ResearchUnitRuntime.run()` raises `ResearchRestartRequired("instructions_changed")` when the turn was recorded under another profile or resource manifest, and `ResearchRestartRequired("context_changed_before_start")` when the context drifted and no saved state exists. Logs `arv2.quality.resume_context_drift` with `layers=[...]` when a recorded context drifted.

- [ ] **Step 1: Write the failing tests**

`tests/arv2/test_quality_resume_db.py`:

```python
"""A research turn re-claimed after it stopped continues its saved conversation.

Spec 2026-10-14 §3.1. Real research runtime, database and workspace; scripted models never spend.
Each test runs a job until a scripted model "dies", then builds a fresh runtime over the same
database and checkpoint store, as the next worker to claim the job would.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import PrivateAttr
from sqlalchemy import text
from structlog.testing import capture_logs

from clue_agents import (
    AgentExecutionStatus,
    AgentWorkspaceFactory,
    ScriptedAgentChatModel,
    WorkspaceRootPolicy,
)
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2.job_resume import ResearchRestartRequired
from clue_api.arv2.quality_execution import Allowance
from clue_api.quality_research_wiring import ResearchUnitRuntime, quality_tools
from clue_config import load_settings
from clue_storage.fs import FsStorage
from tests.arv2.test_quality_claims_db import setup
from tests.arv2.test_quality_evidence_db import save
from tests.arv2.test_quality_runtime_db import Models
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

REVISION = 15
MARKER = "Resume marker 7f3a"
OBJECTIVE = f"{MARKER}: read the saved report and delegate faithful claim processing."


class _StopOnce(ScriptedAgentChatModel):
    """Raises once when its script reaches ``stop_at``, as a worker dying mid-turn would."""

    stop_at: int = -1
    error: Any = RuntimeError
    _stopped: bool = PrivateAttr(default=False)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if not self._stopped and self._cursor == self.stop_at:
            self._stopped = True
            raise self.error("worker died mid-turn")
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class _ResumableModels(Models):
    """One model per role for the whole test, so a rebuilt runtime continues the script."""

    def __init__(self, *args, stop_role=None, stop_at=-1, error=RuntimeError, **kwargs):
        super().__init__(*args, **kwargs)
        self._models: dict[str, _StopOnce] = {}
        self.stop_role, self.stop_at, self.error = stop_role, stop_at, error

    def build(self, **kwargs):
        role = kwargs["role"]
        if role in self._models:
            self.builds.append(role)
            return self._models[role]
        scripted = super().build(**kwargs)
        self._models[role] = _StopOnce(
            responses=scripted.responses,
            stop_at=self.stop_at if role == self.stop_role else -1,
            error=self.error,
        )
        return self._models[role]


@asynccontextmanager
async def _job(tmp_path):
    async with rollback_conn() as conn:
        storage = FsStorage(tmp_path / "blobs")
        op, scope, context_id = await setup(conn, storage)
        scope = replace(
            scope, catalog_version="v4", input_refs={"quality_recipe_version": REVISION}
        )
        source = await save(conn, storage, op, {"employees": 64}, kind="provider_record", url=None)
        lock = asyncio.Lock()

        @asynccontextmanager
        async def connections():
            async with lock, conn.begin_nested():
                yield conn

        for directory in ("source", "home"):
            (tmp_path / directory).mkdir(mode=0o700)
        workspaces = AgentWorkspaceFactory(
            prepared_root=WorkspaceRootPolicy(
                configured_root=tmp_path / "runtime",
                source_root=tmp_path / "source",
                home_root=tmp_path / "home",
            ).prepare(),
            artifact_sink=DurableAgentArtifactStore(storage=storage, conn_factory=connections),
        )
        yield SimpleNamespace(
            conn=conn,
            storage=storage,
            scope=scope,
            context_id=context_id,
            source=source,
            connections=connections,
            workspaces=workspaces,
        )


def _runtime(job, models, saver, scope=None) -> ResearchUnitRuntime:
    @asynccontextmanager
    async def checkpoints(execution_id):
        yield saver

    scope = scope or job.scope
    return ResearchUnitRuntime(
        scope=scope,
        context_id=job.context_id,
        settings=load_settings(_env_file=None),
        storage=job.storage,
        connections=job.connections,
        models=models,
        workspaces=job.workspaces,
        tools=quality_tools(scope, job.storage, purge=True),
        limits=Allowance(20, 30, 4),
        checkpointer_factory=checkpoints,
    )


async def _count(job, sql: str) -> int:
    return (await job.conn.execute(text(sql), {"job": job.scope.job_id})).scalar_one()


_BUNDLES = (
    "SELECT count(*) FROM agent_context_bundle b JOIN arv2_quality_execution q "
    "ON q.execution_id=b.execution_id WHERE q.job_id=:job AND q.role={role}"
)


@pytest.fixture
def prompts(monkeypatch) -> list[str]:
    seen: list[str] = []
    original = ScriptedAgentChatModel._generate

    def capture(self, messages, *args, **kwargs):
        seen.append("\n".join(str(message.content) for message in messages))
        return original(self, messages, *args, **kwargs)

    monkeypatch.setattr(ScriptedAgentChatModel, "_generate", capture)
    return seen


def test_a_parent_stopped_mid_turn_continues_its_saved_conversation(tmp_path, prompts):
    async def case():
        async with _job(tmp_path) as job:
            models = _ResumableModels(
                job.source, job.scope, job.context_id, stop_role="account_research", stop_at=3
            )
            saver = InMemorySaver()
            first = await _runtime(job, models, saver).run(objective=OBJECTIVE)
            assert first.status is AgentExecutionStatus.FAILED
            second = await _runtime(job, models, saver).run(objective=OBJECTIVE)
            assert second.status is AgentExecutionStatus.COMPLETED, second
            assert await _count(job, _BUNDLES.format(role="'account_research'")) == 1
            assert models.builds.count("research_claims") == 1
            delegations = await _count(
                job,
                "SELECT count(*) FROM arv2_quality_activity "
                "WHERE job_id=:job AND kind='delegation'",
            )
            assert delegations == 1
            assert prompts and all(prompt.count(MARKER) <= 1 for prompt in prompts)

    run_async(case())


def test_a_drifted_context_with_a_saved_conversation_continues_and_says_what_drifted(
    tmp_path, prompts
):
    async def case():
        async with _job(tmp_path) as job:
            models = _ResumableModels(
                job.source, job.scope, job.context_id, stop_role="account_research", stop_at=3
            )
            saver = InMemorySaver()
            first = await _runtime(job, models, saver).run(objective=OBJECTIVE)
            assert first.status is AgentExecutionStatus.FAILED
            with capture_logs() as logs:
                second = await _runtime(job, models, saver).run(
                    objective=OBJECTIVE + " Changed after the stop."
                )
            assert second.status is AgentExecutionStatus.COMPLETED, second
            drift = [e for e in logs if e["event"] == "arv2.quality.resume_context_drift"]
            assert drift and "l7_turn" in drift[0]["layers"]
            assert await _count(job, _BUNDLES.format(role="'account_research'")) == 1

    run_async(case())


def test_changed_instructions_ask_for_a_restart(tmp_path, prompts):
    async def case():
        async with _job(tmp_path) as job:
            models = _ResumableModels(
                job.source, job.scope, job.context_id, stop_role="account_research", stop_at=3
            )
            saver = InMemorySaver()
            first = await _runtime(job, models, saver).run(objective=OBJECTIVE)
            assert first.status is AgentExecutionStatus.FAILED
            changed = replace(job.scope, input_refs={"quality_recipe_version": 14})
            with pytest.raises(ResearchRestartRequired) as restart:
                await _runtime(job, models, saver, scope=changed).run(objective=OBJECTIVE)
            assert restart.value.reason == "instructions_changed"

    run_async(case())


def test_a_drift_before_the_first_step_asks_for_a_restart(tmp_path, prompts):
    async def case():
        async with _job(tmp_path) as job:
            models = _ResumableModels(
                job.source, job.scope, job.context_id, stop_role="account_research", stop_at=0
            )
            first = await _runtime(job, models, InMemorySaver()).run(objective=OBJECTIVE)
            assert first.status is AgentExecutionStatus.FAILED
            # A store with no saved state: the worker died before LangGraph wrote anything.
            with pytest.raises(ResearchRestartRequired) as restart:
                await _runtime(job, models, InMemorySaver()).run(
                    objective=OBJECTIVE + " Changed before the first step."
                )
            assert restart.value.reason == "context_changed_before_start"

    run_async(case())


def test_an_unchanged_context_with_no_saved_state_starts_normally(tmp_path, prompts):
    async def case():
        async with _job(tmp_path) as job:
            models = _ResumableModels(
                job.source, job.scope, job.context_id, stop_role="account_research", stop_at=0
            )
            first = await _runtime(job, models, InMemorySaver()).run(objective=OBJECTIVE)
            assert first.status is AgentExecutionStatus.FAILED
            second = await _runtime(job, models, InMemorySaver()).run(objective=OBJECTIVE)
            assert second.status is AgentExecutionStatus.COMPLETED, second

    run_async(case())


def test_a_specialist_stopped_mid_turn_resumes_once(tmp_path, prompts):
    async def case():
        async with _job(tmp_path) as job:
            models = _ResumableModels(
                job.source,
                job.scope,
                job.context_id,
                stop_role="research_claims",
                stop_at=2,
                error=asyncio.CancelledError,
            )
            saver = InMemorySaver()
            with pytest.raises(asyncio.CancelledError):
                await _runtime(job, models, saver).run(objective=OBJECTIVE)
            second = await _runtime(job, models, saver).run(objective=OBJECTIVE)
            assert second.status is AgentExecutionStatus.COMPLETED, second
            assert await _count(job, _BUNDLES.format(role="'research_claims'")) == 1
            delegations = await _count(
                job,
                "SELECT count(*) FROM arv2_quality_activity "
                "WHERE job_id=:job AND kind='delegation'",
            )
            assert delegations == 1
            assert all(prompt.count(MARKER) <= 1 for prompt in prompts)

    run_async(case())
```

- [ ] **Step 2: Run them to verify they fail**

Run: `rt tests/arv2/test_quality_resume_db.py`
Expected, on today's code:
- `test_a_parent_stopped_mid_turn_...` FAILS on `prompt.count(MARKER) <= 1`, because the opening messages are re-inserted.
- `test_a_drifted_context_...` FAILS with `ValueError: turn already has a different opening context receipt`.
- `test_changed_instructions_...` FAILS with `ValueError: turn id already exists with different immutable inputs`.
- `test_a_drift_before_the_first_step_...` FAILS with the receipt `ValueError`.
- `test_an_unchanged_context_...` PASSES. It guards that a clean re-run stays untouched.
- `test_a_specialist_stopped_mid_turn_resumes_once` FAILS on the marker count or the receipt count.

If a failure has a different cause, that is a finding about the harness. Use superpowers:systematic-debugging before changing anything.

- [ ] **Step 3: Read a recorded receipt back**

In `agent_turn_wiring.py`, add to `DbAgentReplayReader` after `require_replayable`:

```python
    async def read_context_receipt(
        self, *, workspace_id: str, turn_id: UUID
    ) -> AgentContextReplayReceipt | None:
        """The opening context recorded for a turn, or ``None`` before it has one."""
        async with self._conn_factory() as conn:
            return await self._read_context(conn, workspace_id, turn_id)
```

- [ ] **Step 4: Let a caller supply the receipt store**

In `agent_platform_wiring.py`, add `ContextReceiptStore` to the `from clue_agents import (...)` list. In `build_agent_context_assembler`, add the parameter after `conn_factory: ConnFactory = transaction,`:

```python
    receipts: ContextReceiptStore | None = None,
```

and replace `receipts=DbAgentContextReceiptStore(conn_factory=conn_factory),` with:

```python
        # A resumed turn passes a store that compares and never writes (spec 2026-10-14 §3.1).
        receipts=receipts or DbAgentContextReceiptStore(conn_factory=conn_factory),
```

- [ ] **Step 5: Compare instead of re-recording, in the research runner**

In `quality_research_wiring.py`:

1. Change the import `from clue_api.agent_turn_wiring import DbAgentTurnJournal` to `from clue_api.agent_turn_wiring import DbAgentReplayReader, DbAgentTurnJournal`.
2. Add `ContextAssemblyReceipt` and `ContextBundleManifest` to the `from clue_agents import (...)` list, plus `AgentTurnRequest` if it is not already there.
3. Add `from langchain_core.runnables import RunnableConfig`.

Add this class directly above `class _Contexts:`:

```python
class _ResumeReceipts:
    """Receipt store for a turn that already recorded its opening context.

    A turn has exactly one receipt, so a resumed turn never writes a second. It compares what it
    would have recorded with what was recorded and keeps the layers that differ, so the runner can
    log them and decide whether the saved conversation can still be continued.
    """

    def __init__(self, recorded: ContextBundleManifest) -> None:
        self.recorded = recorded
        self.drifted: tuple[str, ...] = ()

    async def record(self, *, request: AgentTurnRequest, receipt: ContextAssemblyReceipt) -> None:
        del request
        before = {m.layer.value: m.content_sha256s for m in self.recorded.layers}
        now = {m.layer.value: m.content_sha256s for m in receipt.manifest.layers}
        self.drifted = tuple(
            sorted(layer for layer in before.keys() | now.keys() if before.get(layer) != now.get(layer))
        )
```

In `_Contexts.__init__`, add `self.drift: dict[UUID, tuple[str, ...]] = {}`. Replace the body of `_Contexts.assemble` from `assembled = await build_agent_context_assembler(` through the `.assemble(request=request, profile=profile, history=history)` call with:

```python
        recorded = await runtime.replay.read_context_receipt(
            workspace_id=request.constitution.workspace_id, turn_id=request.turn_id
        )
        receipts = _ResumeReceipts(recorded.manifest) if recorded is not None else None
        assembled = await build_agent_context_assembler(
            resolved_profile=resolved,
            artifacts=runtime.artifacts,
            cards=_PinnedContextOnly(),
            memory=_PinnedContextOnly(),
            memory_recipe=RECIPE,
            requested_memory_types=(),
            policy=ContextAssemblyPolicy(
                version="research-quality-v1",
                token_counter_version="utf8-bytes-v1",
                budgets=tuple(
                    LayerBudget(layer=layer, max_tokens=budget)
                    for layer, budget in zip(
                        tuple(ContextLayer), (24000, 0, 12000, 0, 2000, 0, 16000), strict=True
                    )
                ),
            ),
            conn_factory=runtime.connections,
            receipts=receipts,
        ).assemble(request=request, profile=profile, history=history)
        if recorded is not None and receipts is not None:
            self.drift[request.turn_id] = receipts.drifted
            if receipts.drifted:
                log.warning(
                    "arv2.quality.resume_context_drift",
                    job_id=str(runtime.scope.job_id),
                    turn_id=str(request.turn_id),
                    layers=list(receipts.drifted),
                )
            # Everything downstream keeps naming the bundle the model actually opened with.
            assembled = assembled.model_copy(update={"manifest": recorded.manifest})
```

Keep the existing `if at_least(runtime.scope, RECIPE_26): assembled = drop_identity_echo(...)` and `return assembled` after it.

In `ResearchUnitRuntime.__init__`, after `self.turns = DbAgentTurnJournal(conn_factory=connections)`, add:

```python
        self.replay = DbAgentReplayReader(storage=storage, conn_factory=connections)
```

Add two methods to `ResearchUnitRuntime`, after `artifact(...)`:

```python
    async def _refuse_changed_instructions(self, request: AgentTurnRequest) -> None:
        """A turn recorded under other instructions is never continued (spec 2026-10-14 §3.1)."""
        constitution = request.constitution
        async with self.connections() as conn:
            recorded = (
                await conn.execute(
                    text(
                        "SELECT profile_name, profile_version, profile_sha256, "
                        "resource_manifest_sha256 FROM agent_turn "
                        "WHERE id=:turn AND workspace_id=:ws"
                    ),
                    {"turn": request.turn_id, "ws": constitution.workspace_id},
                )
            ).one_or_none()
        if recorded is not None and tuple(recorded) != (
            constitution.profile_ref.name,
            constitution.profile_ref.version,
            constitution.profile_ref.sha256,
            constitution.resource_manifest_sha256,
        ):
            raise ResearchRestartRequired("instructions_changed")

    async def _has_saved_state(self, execution: ExecutionId) -> bool:
        async with self.checkpointer_factory(execution) as saver:
            saved = await saver.aget_tuple(
                cast(
                    RunnableConfig,
                    {"configurable": {"thread_id": str(execution), "checkpoint_ns": ""}},
                )
            )
        return saved is not None
```

In `ResearchUnitRuntime.run`, directly before `await self.turns.create(request=request, profile=resolved.profile)`, add:

```python
            await self._refuse_changed_instructions(request)
```

Directly after `assembled = await self.contexts.assemble(request=request, profile=resolved.profile, history=())`, add:

```python
            if self.contexts.drift.get(request.turn_id) and not await self._has_saved_state(
                execution
            ):
                # Nothing ran under the recorded context, so a fresh conversation loses nothing.
                raise ResearchRestartRequired("context_changed_before_start")
```

In the `DeepAgentTurnRuntime(` call inside `run`, add `resume_saved_turn=True,` after `continuation_config=continuation_config,`.

- [ ] **Step 6: Specialists continue their own saved state too**

In `specialist_wiring.py`, inside the specialist runner's `DurableDeepAgentTurnRunner(runtime=DeepAgentTurnRuntime(compaction_for=compaction_for, ...))`, add `resume_saved_turn=True,` to the `DeepAgentTurnRuntime(` arguments. Add this comment on the line above it:

```python
                    # A child execution exists per delegation, so saved state on it is always
                    # this delegation's own half-run turn (spec 2026-10-14 §3.3).
```

- [ ] **Step 7: Run the tests**

Run: `rt tests/arv2/test_quality_resume_db.py tests/arv2/test_quality_runtime_db.py tests/agents/test_runtime_resume.py`
Expected: all pass.

Then run every file that imports the changed modules:

```bash
cd $W && FILES=$(git grep -l -e quality_research_wiring -e specialist_wiring -e agent_platform_wiring -e DbAgentReplayReader -- 'tests/*.py' | grep -v '_live.py' | sort -u)
rt $FILES
```

Expected: all pass. Report any failure by name.

- [ ] **Step 8: Commit**

```bash
git add platform/api/clue_api/agent_turn_wiring.py platform/api/clue_api/agent_platform_wiring.py \
  platform/api/clue_api/quality_research_wiring.py platform/api/clue_api/specialist_wiring.py \
  tests/arv2/test_quality_resume_db.py
git commit -m "ARV2 research: a re-claimed job continues its saved conversation

A re-claimed research turn rebuilt its opening context, was refused by the one-receipt guard
when anything had changed, and otherwise restarted the conversation on top of the saved one.
The runner now compares the fresh context with the recorded receipt without writing a second,
logs which layers drifted, and continues the saved state (parent and specialists). Changed
instructions, or drift before any step ran, raise ResearchRestartRequired.
Spec 2026-10-14 §3.1, §3.3."
```

---

### Task 4: The driver restarts a job that cannot be continued

**Files:**
- Modify: `platform/api/clue_api/arv2/job_resume.py` (add `TopUp`, `_audit`, `restart_on_claim`)
- Modify: `platform/api/clue_api/arv2/account_research_driver.py` (`run()` exception handling)
- Test: `tests/arv2/test_job_restart_db.py`

**Interfaces:**
- Consumes: `ResearchRestartRequired` (Task 2), `JobRow.restart_count` (Task 2)
- Produces: `@dataclass(frozen=True) class TopUp(model_calls: int = 0, tool_calls: int = 0, delegations: int = 0, runtime_minutes: int = 0)` with `is_empty() -> bool`
- Produces: `async def restart_on_claim(conn, *, job_id: UUID, attempt: int, reason: RestartReason) -> bool`, fenced on `attempt` and `status='in_progress'`
- Produces: `async def _audit(conn, *, workspace_id: str, job_id: UUID, attempt_before: int, actor: str, reason: str, top_up: TopUp, restarted: bool) -> None`

- [ ] **Step 1: Write the failing tests**

`tests/arv2/test_job_restart_db.py`:

```python
"""A job whose conversation cannot be continued restarts under a new execution (spec §3.2)."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import text

from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2.account_research_catalog import arv2_account_profile_sha256
from clue_api.arv2.account_research_driver import Arv2AccountResearchWorkHandler
from clue_api.arv2.account_research_launch import launch_arv2_account_research
from clue_api.arv2.account_research_store import begin_job, read_job
from clue_api.arv2.claim_writer import LenientClaimWriter
from clue_api.arv2.display.recipes import load_display_recipes
from clue_api.arv2.job_resume import ResearchRestartRequired, restart_on_claim
from clue_storage.fs import FsStorage
from tests.arv2.icp_fixture import seed_icp_fixture, settings_for
from tests.arv2.test_account_research_driver_db import _Clients
from tests.arv2.test_account_research_launch_db import _request
from tests.arv2.test_quality_driver_db import Queue, work
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


async def _launch(conn, storage):
    fixture = await seed_icp_fixture(conn, storage)
    await load_display_recipes(conn)
    settings = settings_for(arv2_account_research_enabled=True)
    launch = await launch_arv2_account_research(
        conn,
        _request(fixture, account_entity_ids=(fixture.accounts[0],)),
        settings=settings,
        storage=storage,
        profile_sha256=arv2_account_profile_sha256(version="v4"),
    )
    return fixture, settings, launch


async def _audits(conn, job):
    return (
        await conn.execute(
            text(
                "SELECT actor, restarted, attempt_before FROM arv2_research_job_resume "
                "WHERE job_id=:job ORDER BY created_at"
            ),
            {"job": job},
        )
    ).all()


def test_restart_on_claim_moves_the_counter_parks_the_job_and_audits(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            _, _, launch = await _launch(conn, FsStorage(tmp_path))
            job = launch.job_ids[0]
            claimed = await begin_job(conn, job_id=job)
            assert claimed is not None and claimed.attempt == 1
            assert await restart_on_claim(
                conn, job_id=job, attempt=1, reason="instructions_changed"
            )
            row = await read_job(conn, job_id=job)
            assert (row.status, row.restart_count) == ("suspended", 1)
            assert [tuple(a) for a in await _audits(conn, job)] == [
                ("system:instructions_changed", True, 1)
            ]
            # Fenced: the same attempt cannot restart a job it no longer runs.
            assert not await restart_on_claim(
                conn, job_id=job, attempt=1, reason="instructions_changed"
            )
            assert len(await _audits(conn, job)) == 1

    run_async(case())


def test_a_second_restart_counts_from_the_first(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            _, _, launch = await _launch(conn, FsStorage(tmp_path))
            job = launch.job_ids[0]
            for attempt in (1, 2):
                assert (await begin_job(conn, job_id=job)).attempt == attempt
                assert await restart_on_claim(
                    conn, job_id=job, attempt=attempt, reason="context_changed_before_start"
                )
            assert (await read_job(conn, job_id=job)).restart_count == 2

    run_async(case())


def test_the_driver_restarts_requeues_and_the_next_claim_runs_the_new_conversation(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path / "blobs")
            fixture, settings, launch = await _launch(conn, storage)
            lock = asyncio.Lock()

            @asynccontextmanager
            async def connections():
                async with lock, conn.begin_nested():
                    yield conn

            seen = []

            class NoLegacyModels:
                def build(self, **kwargs):
                    raise AssertionError("legacy agent must not run for a quality job")

            async def runner(*, scope, context_id, runtime, objective, model_id, unit_key=None):
                seen.append(scope.restart_count)
                if len(seen) == 1:
                    raise ResearchRestartRequired("instructions_changed")
                raise RuntimeError("second claim reached the runner")

            handler = Arv2AccountResearchWorkHandler(
                settings=settings,
                conn_factory=connections,
                artifacts=DurableAgentArtifactStore(storage=storage, conn_factory=connections),
                storage=storage,
                clients=_Clients(),
                model_provider=NoLegacyModels(),
                model_id="fixture/research",
                writer=LenientClaimWriter(lenient=True),
                quality_runner=runner,
                queue=Queue(),
            )
            job = launch.job_ids[0]
            first = await handler.handle(work(job, launch.run_id, fixture.workspace_id))
            assert (first.outcome, first.requeue) == ("stopped", True)
            row = await read_job(conn, job_id=job)
            assert (row.status, row.restart_count) == ("suspended", 1)
            await handler.handle(work(job, launch.run_id, fixture.workspace_id))
            assert seen == [0, 1]

    run_async(case())
```

- [ ] **Step 2: Run them to verify they fail**

Run: `rt tests/arv2/test_job_restart_db.py`
Expected: ERROR with `ImportError: cannot import name 'restart_on_claim' from 'clue_api.arv2.job_resume'`.

- [ ] **Step 3: Add the audit, the top-up type, and restart-on-claim to `job_resume.py`**

Extend the imports:

```python
from dataclasses import dataclass
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
```

Append:

```python
_RESTART_REASONS: dict[str, str] = {
    "instructions_changed": "The agent's instructions changed since this job's last attempt.",
    "context_changed_before_start": (
        "The job's opening context changed before its first step ran."
    ),
}


@dataclass(frozen=True)
class TopUp:
    """An admin's explicit addition to a job's allowance limits (spec §3.5)."""

    model_calls: int = 0
    tool_calls: int = 0
    delegations: int = 0
    runtime_minutes: int = 0

    def is_empty(self) -> bool:
        return not (self.model_calls or self.tool_calls or self.delegations or self.runtime_minutes)


async def _audit(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    job_id: UUID,
    attempt_before: int,
    actor: str,
    reason: str,
    top_up: TopUp,
    restarted: bool,
) -> None:
    await conn.execute(
        text("""
      INSERT INTO arv2_research_job_resume(
        resume_id,workspace_id,job_id,attempt_before,actor,reason,restarted,
        top_up_model_calls,top_up_tool_calls,top_up_delegations,top_up_runtime_ms)
      VALUES (:id,:ws,:job,:attempt,:actor,:reason,:restarted,:model,:tool,:delegation,:runtime)
    """),
        {
            "id": uuid4(),
            "ws": workspace_id,
            "job": job_id,
            "attempt": attempt_before,
            "actor": actor,
            "reason": reason,
            "restarted": restarted,
            "model": top_up.model_calls,
            "tool": top_up.tool_calls,
            "delegation": top_up.delegations,
            "runtime": top_up.runtime_minutes * 60_000,
        },
    )


async def restart_on_claim(
    conn: AsyncConnection, *, job_id: UUID, attempt: int, reason: RestartReason
) -> bool:
    """Give this attempt's job a fresh conversation and park it for requeue (spec §3.2).

    Fenced like ``suspend_job``: only the attempt that claimed the job, and only while it is
    ``in_progress``. Returns whether it restarted.
    """
    row = (
        await conn.execute(
            text("""
      UPDATE arv2_research_job SET restart_count=restart_count+1, status='suspended',
        updated_at=now()
      WHERE job_id=:job AND attempt=:attempt AND status='in_progress'
      RETURNING workspace_id
    """),
            {"job": job_id, "attempt": attempt},
        )
    ).one_or_none()
    if row is None:
        return False
    await _audit(
        conn,
        workspace_id=row.workspace_id,
        job_id=job_id,
        attempt_before=attempt,
        actor=f"system:{reason}",
        reason=_RESTART_REASONS[reason],
        top_up=TopUp(),
        restarted=True,
    )
    return True
```

- [ ] **Step 4: Catch the restart signal in the driver**

In `account_research_driver.py` add `from clue_api.arv2.job_resume import ResearchRestartRequired, restart_on_claim`. In `Arv2AccountResearchWorkHandler.handle`, in the `try: ending = await self._run(...)` chain, add this clause after `except _JobSuperseded:` and before `except Exception as error:`:

```python
        except ResearchRestartRequired as restart:
            # Spec 2026-10-14 §3.2: the saved conversation cannot be continued, so the job gets a
            # fresh one under a new execution and goes back to the queue. The runner only raises
            # this after the claim, so the attempt is known.
            if claim.attempt is None:
                raise
            async with self._connection() as conn:
                restarted = await restart_on_claim(
                    conn, job_id=scope.job_id, attempt=claim.attempt, reason=restart.reason
                )
            log.warning(
                "arv2.quality.job_restarted",
                job_id=str(scope.job_id),
                attempt=claim.attempt,
                reason=restart.reason,
                restarted=restarted,
            )
            return WorkResult(outcome="stopped", references=references, requeue=True)
```

The handler method's name is the one holding `claim = _Claim()` and `ending = await self._run(scope, claim, task_attempt=context.task_attempt)`. Insert the clause there.

- [ ] **Step 5: Run the tests**

Run: `rt tests/arv2/test_job_restart_db.py tests/arv2/test_quality_driver_db.py tests/arv2/test_account_research_driver_db.py`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add platform/api/clue_api/arv2/job_resume.py platform/api/clue_api/arv2/account_research_driver.py \
  tests/arv2/test_job_restart_db.py
git commit -m "ARV2 research: the driver restarts a job whose conversation cannot be continued

ResearchRestartRequired from the runner moves the job's restart counter, writes a system audit
row, parks the job and requeues the task; the next claim runs the new conversation under the
same job, so purchases, claims and the shared allowance carry over. Spec 2026-10-14 §3.2."
```

---

### Task 5: The resume operation, stuck-job listing, and allowance top-up

**Files:**
- Modify: `platform/api/clue_api/arv2/job_resume.py` (add listing, resume, offer, top-up)
- Modify: `platform/api/clue_api/arv2/quality_execution.py` (`bind_execution` limits comparison)
- Modify: `scripts/requeue_stranded_arv2_research_jobs.py` (`apply_requeue` uses `offer_research_job`)
- Test: `tests/arv2/test_job_resume_db.py`

**Interfaces:**
- Consumes: `TopUp`, `_audit` (Task 4); `research_execution_id` (Task 2)
- Produces: `class ResumeRefused(Exception)` with `code: str`, `message: str`
- Produces: `@dataclass(frozen=True) class StuckJob` with fields `job_id, run_id, workspace_id, subject_type, account_id, account_name, person_id, person_name, state, status, failure_code, failure_message, rounds, tool_calls, cost_usd, stopped_at, restart_count, resumable, refusal`, and `as_json() -> dict[str, Any]`
- Produces: `@dataclass(frozen=True) class ResumeResult(job_id: UUID, status: str, attempt: int, restarted: bool, top_up_applied: TopUp)` with `as_json()`
- Produces: `async def list_stuck_jobs(conn, *, workspace_id: str | None) -> list[StuckJob]`
- Produces: `async def resume_research_job(conn, *, workspace_id: str, job_id: UUID, actor: str, reason: str, top_up: TopUp = TopUp(), restart_fresh: bool = False) -> ResumeResult`
- Produces: `async def offer_research_job(conn, *, job_id: UUID, run_id: UUID, workspace_id: str) -> bool`
- Refusal codes: `job_not_found`, `job_completed`, `job_not_started`, `job_already_queued`, `privacy_stopped`, `research_stopped`, `outputs_frozen`, `reason_required`, `invalid_top_up`

- [ ] **Step 1: Write the failing tests**

`tests/arv2/test_job_resume_db.py`:

```python
"""One audited operation takes a stopped research job back into the queue (spec §3.5)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from clue_api.arv2.account_research_store import read_job
from clue_api.arv2.job_resume import (
    ResumeRefused,
    TopUp,
    list_stuck_jobs,
    offer_research_job,
    resume_research_job,
)
from clue_api.arv2.quality_execution import Allowance, bind_execution
from clue_api.arv2.quality_generation import ensure_generation
from clue_storage.fs import FsStorage
from tests.arv2.test_quality_claims_db import setup
from tests.arv2.test_quality_execution_db import execution
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

BASE = Allowance(20, 30, 4, 600_000)


async def _fail(conn, job, code="d_b_a_p_i_error"):
    await conn.execute(
        text(
            "UPDATE arv2_research_job SET status='needs_review', attempt=1, started_at=now(), "
            "finished_at=now(), failure_code=:code, failure_message='stopped' WHERE job_id=:job"
        ),
        {"job": job, "code": code},
    )


async def _audit_count(conn, job):
    return (
        await conn.execute(
            text("SELECT count(*) FROM arv2_research_job_resume WHERE job_id=:job"), {"job": job}
        )
    ).scalar_one()


async def _open_tasks(conn, job):
    return (
        await conn.execute(
            text(
                "SELECT count(*) FROM fleet_task WHERE work_id=:job "
                "AND status IN ('queued','claimed')"
            ),
            {"job": job},
        )
    ).scalar_one()


async def _resume(conn, op, **kwargs):
    return await resume_research_job(
        conn,
        workspace_id=kwargs.pop("workspace_id", op.workspace_id),
        job_id=op.job_id,
        actor="operator:test",
        reason=kwargs.pop("reason", "deadlock fixed"),
        **kwargs,
    )


def test_resume_moves_a_failed_job_back_to_the_queue_with_an_audit_row(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            op, _, _ = await setup(conn, FsStorage(tmp_path))
            await _fail(conn, op.job_id)
            result = await _resume(conn, op)
            assert (result.status, result.restarted, result.attempt) == ("suspended", False, 1)
            row = await read_job(conn, job_id=op.job_id)
            assert (row.status, row.failure_code, row.finished_at) == ("suspended", None, None)
            assert row.restart_count == 0
            assert await _open_tasks(conn, op.job_id) == 1
            assert await _audit_count(conn, op.job_id) == 1

    run_async(case())


def test_restart_fresh_moves_the_counter(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            op, _, _ = await setup(conn, FsStorage(tmp_path))
            await _fail(conn, op.job_id)
            result = await _resume(conn, op, restart_fresh=True)
            assert result.restarted
            assert (await read_job(conn, job_id=op.job_id)).restart_count == 1
            restarted = (
                await conn.execute(
                    text("SELECT restarted FROM arv2_research_job_resume WHERE job_id=:job"),
                    {"job": op.job_id},
                )
            ).scalar_one()
            assert restarted is True

    run_async(case())


def test_a_job_with_an_open_task_is_refused_and_writes_nothing(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            op, _, _ = await setup(conn, FsStorage(tmp_path))
            await _fail(conn, op.job_id)
            await _resume(conn, op)
            with pytest.raises(ResumeRefused) as refused:
                await _resume(conn, op)
            assert refused.value.code == "job_already_queued"
            assert await _audit_count(conn, op.job_id) == 1

    run_async(case())


@pytest.mark.parametrize(
    "prepare,code",
    [
        ("UPDATE arv2_research_job SET status='completed', finished_at=now() WHERE job_id=:job",
         "job_completed"),
        ("SELECT 1", "job_not_started"),
        ("UPDATE arv2_research_job SET input_refs=COALESCE(input_refs,'{}'::jsonb)"
         " || '{\"privacy_stopped\": true}'::jsonb, status='suspended' WHERE job_id=:job",
         "privacy_stopped"),
    ],
)
def test_jobs_that_are_not_stuck_or_were_stopped_are_refused(tmp_path, prepare, code):
    async def case():
        async with rollback_conn() as conn:
            op, _, _ = await setup(conn, FsStorage(tmp_path))
            await conn.execute(text(prepare), {"job": op.job_id})
            with pytest.raises(ResumeRefused) as refused:
                await _resume(conn, op)
            assert refused.value.code == code
            assert await _audit_count(conn, op.job_id) == 0

    run_async(case())


def test_a_suspended_generation_and_frozen_outputs_are_refused(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            op, _, cid = await setup(conn, FsStorage(tmp_path))
            await _fail(conn, op.job_id, code="workspace_conflict")
            with pytest.raises(ResumeRefused) as frozen:
                await _resume(conn, op)
            assert frozen.value.code == "outputs_frozen"
            await _fail(conn, op.job_id)
            generation = await ensure_generation(conn, op, context_id=cid)
            await conn.execute(
                text(
                    "UPDATE arv2_account_research_generation SET state='suspended' "
                    "WHERE generation_id=:id"
                ),
                {"id": generation.generation_id},
            )
            with pytest.raises(ResumeRefused) as stopped:
                await _resume(conn, op)
            assert stopped.value.code == "research_stopped"

    run_async(case())


def test_input_errors_and_other_workspaces_are_refused(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            op, _, _ = await setup(conn, FsStorage(tmp_path))
            await _fail(conn, op.job_id)
            for kwargs, code in (
                ({"reason": "  "}, "reason_required"),
                ({"top_up": TopUp(tool_calls=-1)}, "invalid_top_up"),
                ({"top_up": TopUp(tool_calls=5)}, "invalid_top_up"),  # no allowance row yet
                ({"workspace_id": "ws_someone_else"}, "job_not_found"),
            ):
                with pytest.raises(ResumeRefused) as refused:
                    await _resume(conn, op, **kwargs)
                assert refused.value.code == code, kwargs
            assert await _audit_count(conn, op.job_id) == 0

    run_async(case())


def test_a_topped_up_allowance_binds_on_the_next_claim(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            op, scope, cid = await setup(conn, FsStorage(tmp_path))
            parent = await execution(conn, op, scope.project_id)
            await bind_execution(
                conn, op, execution_id=parent, context_id=cid, role="account_research", limits=BASE
            )
            await _fail(conn, op.job_id)
            top_up = TopUp(model_calls=5, tool_calls=10, delegations=1, runtime_minutes=2)
            assert (await _resume(conn, op, top_up=top_up)).top_up_applied == top_up
            limits = (
                await conn.execute(
                    text(
                        "SELECT max_model_calls,max_tool_calls,max_delegations,max_runtime_ms "
                        "FROM arv2_quality_allowance WHERE job_id=:job"
                    ),
                    {"job": op.job_id},
                )
            ).one()
            assert tuple(limits) == (25, 40, 5, 720_000)
            # The next claim binds with the configured base limits; the recorded top-up explains
            # the difference, so it is not mistaken for a reset.
            restarted = await execution(conn, op, scope.project_id)
            await bind_execution(
                conn,
                op,
                execution_id=restarted,
                context_id=cid,
                role="account_research",
                limits=BASE,
            )
            with pytest.raises(ValueError):
                await bind_execution(
                    conn,
                    op,
                    execution_id=await execution(conn, op, scope.project_id),
                    context_id=cid,
                    role="account_research",
                    limits=Allowance(21, 30, 4, 600_000),
                )

    run_async(case())


def test_runtime_top_up_on_an_unlimited_allowance_is_refused(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            op, scope, cid = await setup(conn, FsStorage(tmp_path))
            parent = await execution(conn, op, scope.project_id)
            await bind_execution(
                conn,
                op,
                execution_id=parent,
                context_id=cid,
                role="account_research",
                limits=Allowance(20, 30, 4, 0),
            )
            await _fail(conn, op.job_id)
            with pytest.raises(ResumeRefused) as refused:
                await _resume(conn, op, top_up=TopUp(runtime_minutes=5))
            assert refused.value.code == "invalid_top_up"

    run_async(case())


def test_the_stuck_list_shows_failed_and_stranded_jobs_with_their_resumability(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            op, _, _ = await setup(conn, FsStorage(tmp_path))
            other = (
                await conn.execute(
                    text(
                        "SELECT job_id FROM arv2_research_job WHERE run_id=:run AND job_id<>:job"
                    ),
                    {"run": op.run_id, "job": op.job_id},
                )
            ).scalar_one()
            assert await list_stuck_jobs(conn, workspace_id=op.workspace_id) == []
            await _fail(conn, op.job_id, code="workspace_conflict")
            await conn.execute(
                text(
                    "UPDATE arv2_research_job SET status='in_progress', attempt=1, "
                    "started_at=now() WHERE job_id=:job"
                ),
                {"job": other},
            )
            stuck = {j.job_id: j for j in await list_stuck_jobs(conn, workspace_id=op.workspace_id)}
            assert set(stuck) == {op.job_id, other}
            assert (stuck[op.job_id].state, stuck[op.job_id].resumable) == ("failed", False)
            assert stuck[op.job_id].refusal == "outputs_frozen"
            assert (stuck[other].state, stuck[other].resumable) == ("stalled", True)
            await offer_research_job(
                conn, job_id=other, run_id=op.run_id, workspace_id=op.workspace_id
            )
            listed = {j.job_id for j in await list_stuck_jobs(conn, workspace_id=op.workspace_id)}
            assert listed == {op.job_id}
            assert await list_stuck_jobs(conn, workspace_id="ws_someone_else") == []
            assert stuck[op.job_id].as_json()["job_id"] == str(op.job_id)

    run_async(case())
```

- [ ] **Step 2: Run them to verify they fail**

Run: `rt tests/arv2/test_job_resume_db.py`
Expected: ERROR with `ImportError: cannot import name 'ResumeRefused' from 'clue_api.arv2.job_resume'`.

- [ ] **Step 3: Add listing, resume and offer to `job_resume.py`**

Replace the module's imports with:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_store import refresh_run_status
from clue_api.arv2.fleet_task import (
    ARV2_ACCOUNT_DEDUP_PREFIX,
    ARV2_ACCOUNT_TASK_PRIORITY,
    arv2_account_work_id,
)
from clue_core import ProjectRunId
from clue_fleet import FleetTaskKind
from clue_fleet.queue import enqueue_task
```

Append:

```python
_MESSAGES: dict[str, str] = {
    "job_not_found": "No research job with that id in this workspace.",
    "job_completed": "The job completed; there is nothing to resume.",
    "job_not_started": "The job has not started; it is waiting for its turn, not stuck.",
    "job_already_queued": "The job is already queued or running.",
    "privacy_stopped": "Research on this subject was stopped for privacy.",
    "research_stopped": "Research on this account was stopped; resume the account first.",
    "outputs_frozen": (
        "This job's outputs were frozen by the pre-fix finalize bug and it cannot be resumed."
    ),
    "reason_required": "Say why this job is being resumed.",
}


class ResumeRefused(Exception):
    """A named reason a job cannot be resumed (spec §3.5)."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        self.message = message or _MESSAGES.get(code, code)
        super().__init__(f"{code}: {self.message}")


@dataclass(frozen=True)
class StuckJob:
    job_id: UUID
    run_id: UUID
    workspace_id: str
    subject_type: str
    account_id: UUID
    account_name: str | None
    person_id: UUID | None
    person_name: str | None
    state: Literal["failed", "stalled"]
    status: str
    failure_code: str | None
    failure_message: str | None
    rounds: int
    tool_calls: int
    cost_usd: Decimal
    stopped_at: datetime
    restart_count: int
    resumable: bool
    refusal: str | None

    def as_json(self) -> dict[str, Any]:
        body = asdict(self)
        for key in ("job_id", "run_id", "account_id", "person_id"):
            body[key] = str(body[key]) if body[key] is not None else None
        body["cost_usd"] = str(self.cost_usd)
        body["stopped_at"] = self.stopped_at.isoformat()
        return body


@dataclass(frozen=True)
class ResumeResult:
    job_id: UUID
    status: str
    attempt: int
    restarted: bool
    top_up_applied: TopUp

    def as_json(self) -> dict[str, Any]:
        return {
            "job_id": str(self.job_id),
            "status": self.status,
            "attempt": self.attempt,
            "restarted": self.restarted,
            "top_up_applied": asdict(self.top_up_applied),
        }


_JOBS = """
SELECT j.job_id, j.run_id, j.workspace_id, j.subject_type, j.status, j.attempt,
  j.account_entity_id, a.canonical_name AS account_name,
  j.subject_entity_id, c.full_name AS person_name,
  j.failure_code, j.failure_message, j.model_rounds, j.tool_calls, j.cost_usd,
  COALESCE(j.finished_at, j.updated_at) AS stopped_at, j.restart_count,
  (COALESCE(j.input_refs->>'privacy_stopped', 'false') = 'true' OR EXISTS (
     SELECT 1 FROM arv2_account_research_generation g
     WHERE g.workspace_id = j.workspace_id AND g.run_id = j.run_id
       AND g.account_id = j.account_entity_id AND g.state = 'privacy_stopped'))
    AS privacy_stopped,
  EXISTS (
     SELECT 1 FROM arv2_account_research_generation g
     WHERE g.workspace_id = j.workspace_id AND g.run_id = j.run_id
       AND g.account_id = j.account_entity_id AND g.state = 'suspended') AS research_stopped,
  EXISTS (
     SELECT 1 FROM fleet_task t
     WHERE t.kind = CAST(:kind AS fleet_task_kind) AND t.work_id = j.job_id
       AND t.status IN ('queued', 'claimed')) AS queued
FROM arv2_research_job j
LEFT JOIN account_entity a ON a.id = j.account_entity_id
LEFT JOIN contact_entity c ON c.id = j.subject_entity_id
"""


def _refusal(row: Any) -> str | None:
    """Why this job cannot be resumed, or ``None`` when it can."""
    if row.status == "completed":
        return "job_completed"
    if row.status == "not_started":
        return "job_not_started"
    if row.queued:
        return "job_already_queued"
    if row.privacy_stopped:
        return "privacy_stopped"
    if row.research_stopped:
        return "research_stopped"
    if row.failure_code == "workspace_conflict":
        return "outputs_frozen"
    return None


def _stuck(row: Any) -> StuckJob:
    refusal = _refusal(row)
    return StuckJob(
        job_id=row.job_id,
        run_id=row.run_id,
        workspace_id=row.workspace_id,
        subject_type=row.subject_type,
        account_id=row.account_entity_id,
        account_name=row.account_name,
        person_id=row.subject_entity_id,
        person_name=row.person_name,
        state="failed" if row.status == "needs_review" else "stalled",
        status=row.status,
        failure_code=row.failure_code,
        failure_message=row.failure_message,
        rounds=row.model_rounds,
        tool_calls=row.tool_calls,
        cost_usd=row.cost_usd,
        stopped_at=row.stopped_at,
        restart_count=row.restart_count,
        resumable=refusal is None,
        refusal=refusal,
    )


async def list_stuck_jobs(conn: AsyncConnection, *, workspace_id: str | None) -> list[StuckJob]:
    """Failed jobs, and started jobs nothing is queued to continue, newest first.

    ``workspace_id=None`` lists every workspace (the developer script only).
    """
    rows = (
        await conn.execute(
            text(
                _JOBS
                + " WHERE (CAST(:ws AS text) IS NULL OR j.workspace_id = :ws)"
                " AND j.status IN ('needs_review', 'suspended', 'in_progress')"
                " ORDER BY stopped_at DESC, j.job_id"
            ),
            {"ws": workspace_id, "kind": FleetTaskKind.ARV2_ACCOUNT_RESEARCH.value},
        )
    ).all()
    return [_stuck(row) for row in rows if row.status == "needs_review" or not row.queued]


async def offer_research_job(
    conn: AsyncConnection, *, job_id: UUID, run_id: UUID, workspace_id: str
) -> bool:
    """Offer a research job to the fleet the way its launch does; re-opens a closed task."""
    return await enqueue_task(
        conn,
        kind=FleetTaskKind.ARV2_ACCOUNT_RESEARCH,
        project_run_id=ProjectRunId(arv2_account_work_id(job_id)),
        dedup_key=f"{ARV2_ACCOUNT_DEDUP_PREFIX}{job_id}",
        priority=ARV2_ACCOUNT_TASK_PRIORITY,
        payload={"job_id": str(job_id), "run_id": str(run_id), "workspace_id": workspace_id},
        reopen_terminal=True,
    )


async def _apply_top_up(
    conn: AsyncConnection, *, workspace_id: str, job_id: UUID, top_up: TopUp
) -> None:
    allowance = (
        await conn.execute(
            text(
                "SELECT max_runtime_ms FROM arv2_quality_allowance "
                "WHERE job_id=:job AND workspace_id=:ws FOR NO KEY UPDATE"
            ),
            {"job": job_id, "ws": workspace_id},
        )
    ).one_or_none()
    if allowance is None:
        raise ResumeRefused(
            "invalid_top_up", "This job has no allowance yet; resume it without a top-up."
        )
    if top_up.runtime_minutes and allowance.max_runtime_ms == 0:
        raise ResumeRefused(
            "invalid_top_up", "This job's runtime is unlimited; drop the runtime top-up."
        )
    await conn.execute(
        text("""
      UPDATE arv2_quality_allowance SET max_model_calls=max_model_calls+:model,
        max_tool_calls=max_tool_calls+:tool, max_delegations=max_delegations+:delegation,
        max_runtime_ms=max_runtime_ms+:runtime
      WHERE job_id=:job AND workspace_id=:ws
    """),
        {
            "model": top_up.model_calls,
            "tool": top_up.tool_calls,
            "delegation": top_up.delegations,
            "runtime": top_up.runtime_minutes * 60_000,
            "job": job_id,
            "ws": workspace_id,
        },
    )


async def resume_research_job(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    job_id: UUID,
    actor: str,
    reason: str,
    top_up: TopUp = TopUp(),
    restart_fresh: bool = False,
) -> ResumeResult:
    """Take a stopped job back into the queue, audited (spec §3.5). One transaction: the
    caller's. Raises :class:`ResumeRefused` with a named code and writes nothing on refusal."""
    if not reason.strip():
        raise ResumeRefused("reason_required")
    if min(top_up.model_calls, top_up.tool_calls, top_up.delegations, top_up.runtime_minutes) < 0:
        raise ResumeRefused("invalid_top_up", "Top-ups are whole numbers, zero or more.")
    row = (
        await conn.execute(
            text(_JOBS + " WHERE j.job_id = :job AND j.workspace_id = :ws FOR UPDATE OF j"),
            {"job": job_id, "ws": workspace_id, "kind": FleetTaskKind.ARV2_ACCOUNT_RESEARCH.value},
        )
    ).one_or_none()
    if row is None:
        raise ResumeRefused("job_not_found")
    refusal = _refusal(row)
    if refusal is not None:
        raise ResumeRefused(refusal)
    if not top_up.is_empty():
        await _apply_top_up(conn, workspace_id=workspace_id, job_id=job_id, top_up=top_up)
    await conn.execute(
        text("""
      UPDATE arv2_research_job SET status='suspended', failure_code=NULL, failure_message=NULL,
        finished_at=NULL, updated_at=now(),
        restart_count=restart_count + CASE WHEN :restart THEN 1 ELSE 0 END
      WHERE job_id=:job AND workspace_id=:ws
    """),
        {"job": job_id, "ws": workspace_id, "restart": restart_fresh},
    )
    await offer_research_job(conn, job_id=job_id, run_id=row.run_id, workspace_id=workspace_id)
    await refresh_run_status(conn, run_id=row.run_id)
    await _audit(
        conn,
        workspace_id=workspace_id,
        job_id=job_id,
        attempt_before=row.attempt,
        actor=actor,
        reason=reason.strip(),
        top_up=top_up,
        restarted=restart_fresh,
    )
    return ResumeResult(
        job_id=job_id,
        status="suspended",
        attempt=row.attempt,
        restarted=restart_fresh,
        top_up_applied=top_up,
    )
```

- [ ] **Step 4: Recorded top-ups are the only way the limits grow**

In `quality_execution.py`, in `bind_execution`, replace the comparison block

```python
    if tuple(saved) != (
        limits.model_calls,
        limits.tool_calls,
        limits.delegations,
        limits.runtime_ms,
    ):
        raise ValueError("research recovery cannot reset the shared allowance")
```

with

```python
    granted = (
        await conn.execute(
            text("""
      SELECT COALESCE(sum(top_up_model_calls),0), COALESCE(sum(top_up_tool_calls),0),
        COALESCE(sum(top_up_delegations),0), COALESCE(sum(top_up_runtime_ms),0)
      FROM arv2_research_job_resume WHERE job_id=:job AND workspace_id=:ws
    """),
            {"job": scope.job_id, "ws": scope.workspace_id},
        )
    ).one()
    # An admin's recorded top-up (spec 2026-10-14 §3.5) is the only way the limits grow.
    if tuple(saved) != (
        limits.model_calls + granted[0],
        limits.tool_calls + granted[1],
        limits.delegations + granted[2],
        limits.runtime_ms + granted[3],
    ):
        raise ValueError("research recovery cannot reset the shared allowance")
```

- [ ] **Step 5: The stranded-job script offers jobs through the shared helper**

In `scripts/requeue_stranded_arv2_research_jobs.py`, replace the body of `apply_requeue` with:

```python
    offered = 0
    for job in plan:
        offered += await offer_research_job(
            conn, job_id=job.job_id, run_id=job.run_id, workspace_id=job.workspace_id
        )
    return offered
```

Add `from clue_api.arv2.job_resume import offer_research_job`. Remove any imports ruff then reports as unused (`enqueue_task`, `ProjectRunId`, `ARV2_ACCOUNT_DEDUP_PREFIX`, `ARV2_ACCOUNT_TASK_PRIORITY`, `arv2_account_work_id`); keep `FleetTaskKind`, which `plan_requeue` still uses.

- [ ] **Step 6: Run the tests**

Run: `rt tests/arv2/test_job_resume_db.py tests/arv2/test_quality_execution_db.py tests/arv2/test_job_restart_db.py`
Expected: all pass. Also run `cd $W && PYTHONPATH="$PP" $D/.venv/bin/python -c "import scripts.requeue_stranded_arv2_research_jobs"`; expected: no output.

- [ ] **Step 7: Commit**

```bash
git add platform/api/clue_api/arv2/job_resume.py platform/api/clue_api/arv2/quality_execution.py \
  scripts/requeue_stranded_arv2_research_jobs.py tests/arv2/test_job_resume_db.py
git commit -m "ARV2 research: one audited operation resumes a stopped job, with optional top-up

resume_research_job refuses with a named code (completed, not started, already queued,
privacy or research stopped, frozen outputs, no reason, invalid top-up) or moves the job to
suspended, re-offers its task, refreshes the run, applies an explicit allowance top-up and
writes an audit row. list_stuck_jobs is the shared reading. bind_execution accepts limits grown
only by recorded top-ups. Spec 2026-10-14 §3.5."
```

---

### Task 6: The developer script

**Files:**
- Create: `scripts/resume_arv2_research_job.py`
- Test: `tests/arv2/test_resume_script_db.py`

**Interfaces:**
- Consumes: `list_stuck_jobs`, `resume_research_job`, `ResumeRefused`, `TopUp` (Task 5)
- Produces: `async def run(*, connect: ConnFactory, workspace_id: str | None, job_id: UUID | None, reason: str, top_up: TopUp, restart_fresh: bool, apply: bool, actor: str) -> list[str]`

- [ ] **Step 1: Write the failing test**

```python
"""The resume script lists stuck jobs, plans by default, and writes only with --apply (§3.6)."""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from sqlalchemy import text

from clue_api.arv2.account_research_store import read_job
from clue_api.arv2.job_resume import TopUp
from clue_storage.fs import FsStorage
from scripts.resume_arv2_research_job import run
from tests.arv2.test_job_resume_db import _fail
from tests.arv2.test_quality_claims_db import setup
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def test_list_plan_and_apply(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            op, _, _ = await setup(conn, FsStorage(tmp_path))
            await _fail(conn, op.job_id)

            @asynccontextmanager
            async def connect():
                async with conn.begin_nested():
                    yield conn

            common = dict(
                connect=connect,
                reason="deadlock fixed",
                top_up=TopUp(),
                restart_fresh=False,
                actor="operator:test",
            )
            listing = await run(workspace_id=op.workspace_id, job_id=None, apply=False, **common)
            assert any(str(op.job_id) in line and "resumable" in line for line in listing)

            planned = await run(workspace_id=None, job_id=op.job_id, apply=False, **common)
            assert planned[-1].startswith("dry run")
            assert (await read_job(conn, job_id=op.job_id)).status == "needs_review"

            applied = await run(workspace_id=None, job_id=op.job_id, apply=True, **common)
            assert any(line.startswith("resumed") for line in applied)
            assert (await read_job(conn, job_id=op.job_id)).status == "suspended"

            refused = await run(workspace_id=None, job_id=op.job_id, apply=True, **common)
            assert refused == ["refused: job_already_queued: The job is already queued or running."]
            audits = (
                await conn.execute(
                    text("SELECT count(*) FROM arv2_research_job_resume WHERE job_id=:job"),
                    {"job": op.job_id},
                )
            ).scalar_one()
            assert audits == 1

    run_async(case())
```

- [ ] **Step 2: Run it to verify it fails**

Run: `rt tests/arv2/test_resume_script_db.py`
Expected: ERROR with `ModuleNotFoundError: No module named 'scripts.resume_arv2_research_job'`.

- [ ] **Step 3: Implement the script**

```python
#!/usr/bin/env python3
"""List stuck ARV2 research jobs, and resume one (spec 2026-10-14 §3.6).

    set -a; source .env; set +a
    uv run python scripts/resume_arv2_research_job.py                         # list every workspace
    uv run python scripts/resume_arv2_research_job.py --workspace ws_...      # list one workspace
    uv run python scripts/resume_arv2_research_job.py --job <id> --reason "deadlock fixed"
    uv run python scripts/resume_arv2_research_job.py --job <id> --reason "..." \\
        --top-up-tool-calls 50 --apply

**Dry run by default.** Without ``--apply`` it prints what it would do and writes nothing. Add
``--restart-fresh`` to give the job a new conversation instead of continuing its saved one. In
production, run it from a worker container, which carries the database settings.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
from uuid import UUID

from sqlalchemy import text

from clue_api.arv2.job_resume import (
    ResumeRefused,
    StuckJob,
    TopUp,
    list_stuck_jobs,
    resume_research_job,
)
from clue_db import ConnFactory, db_lifespan, transaction


class _DryRun(Exception):
    """Raised inside the transaction so a planned resume rolls back."""


def _line(job: StuckJob) -> str:
    who = job.person_name or job.account_name or str(job.account_id)
    can = "resumable" if job.resumable else f"not resumable ({job.refusal})"
    return (
        f"{job.workspace_id}  {job.state:7}  {job.subject_type:7}  {who}  "
        f"{job.failure_code or '-'}  rounds {job.rounds}  ${job.cost_usd}  "
        f"job {job.job_id}  {can}"
    )


async def run(
    *,
    connect: ConnFactory,
    workspace_id: str | None,
    job_id: UUID | None,
    reason: str,
    top_up: TopUp,
    restart_fresh: bool,
    apply: bool,
    actor: str,
) -> list[str]:
    lines: list[str] = []
    try:
        async with connect() as conn:
            if job_id is None:
                jobs = await list_stuck_jobs(conn, workspace_id=workspace_id)
                lines.extend(_line(job) for job in jobs)
                lines.append(f"{len(jobs)} stuck jobs")
                return lines
            owner = (
                await conn.execute(
                    text("SELECT workspace_id FROM arv2_research_job WHERE job_id=:job"),
                    {"job": job_id},
                )
            ).scalar_one_or_none()
            try:
                result = await resume_research_job(
                    conn,
                    workspace_id=owner or "",
                    job_id=job_id,
                    actor=actor,
                    reason=reason,
                    top_up=top_up,
                    restart_fresh=restart_fresh,
                )
            except ResumeRefused as refused:
                return [f"refused: {refused.code}: {refused.message}"]
            lines.append(
                f"resumed job {job_id} in {owner}: attempt {result.attempt}, "
                f"restarted {result.restarted}, top-up {result.top_up_applied}"
            )
            if not apply:
                raise _DryRun
    except _DryRun:
        lines.append("dry run: nothing written; pass --apply to resume")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", help="List only this workspace's stuck jobs.")
    parser.add_argument("--job", type=UUID, help="The job to resume.")
    parser.add_argument("--reason", default="", help="Why the job is being resumed (required).")
    parser.add_argument("--restart-fresh", action="store_true")
    parser.add_argument("--top-up-model-calls", type=int, default=0)
    parser.add_argument("--top-up-tool-calls", type=int, default=0)
    parser.add_argument("--top-up-delegations", type=int, default=0)
    parser.add_argument("--top-up-runtime-minutes", type=int, default=0)
    parser.add_argument("--apply", action="store_true", help="Write. Without it, nothing is.")
    args = parser.parse_args()
    top_up = TopUp(
        model_calls=args.top_up_model_calls,
        tool_calls=args.top_up_tool_calls,
        delegations=args.top_up_delegations,
        runtime_minutes=args.top_up_runtime_minutes,
    )

    async def go() -> None:
        async with db_lifespan():
            for line in await run(
                connect=transaction,
                workspace_id=args.workspace,
                job_id=args.job,
                reason=args.reason,
                top_up=top_up,
                restart_fresh=args.restart_fresh,
                apply=args.apply,
                actor=f"operator:{getpass.getuser()}",
            ):
                print(line)

    asyncio.run(go())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the test**

Run: `rt tests/arv2/test_resume_script_db.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/resume_arv2_research_job.py tests/arv2/test_resume_script_db.py
git commit -m "Scripts: resume_arv2_research_job lists stuck jobs and resumes one, dry run by default

Spec 2026-10-14 §3.6. Lists across workspaces (or one), plans a resume with an optional
top-up or fresh restart, and writes only with --apply; the actor is recorded as operator:<user>."
```

---

### Task 7: Admin endpoints

**Files:**
- Create: `platform/api/clue_api/frontend_read/research_jobs.py`
- Modify: `platform/api/clue_api/frontend_read/settings.py` (`register_settings_routes`)
- Test: `tests/auth/test_research_jobs_api.py`

**Interfaces:**
- Consumes: `list_stuck_jobs`, `resume_research_job`, `ResumeRefused`, `TopUp` (Task 5)
- Produces: `register_research_job_routes(router: APIRouter, *, conn_factory: ConnFactory) -> None` serving `GET /frontend/v1/research/jobs/stuck` and `POST /frontend/v1/research/jobs/{job_id}/resume`, both requiring `research.approve_spend`

- [ ] **Step 1: Write the failing tests**

```python
"""Workspace admins list stuck research jobs and resume one (spec 2026-10-14 §3.7)."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import text

from clue_api.arv2.account_research_catalog import arv2_account_profile_sha256
from clue_api.arv2.account_research_launch import launch_arv2_account_research
from clue_auth.store import create_platform_user, create_workspace_membership, link_auth_identity
from clue_research.claimstore import load_core_pack
from clue_storage.fs import FsStorage
from tests.arv2.icp_fixture import seed_icp_fixture, settings_for
from tests.arv2.test_account_research_launch_db import _request

from .conftest import rollback_conn, run_async
from .test_settings_integration import build_app, headers, seed

pytestmark = pytest.mark.usefixtures("require_auth_db")

STUCK = "/frontend/v1/research/jobs/stuck"


async def _failed_job(conn, storage, workspace_id: str, user_id: str):
    fixture = await seed_icp_fixture(conn, storage, workspace_id=workspace_id, user_id=user_id)
    launch = await launch_arv2_account_research(
        conn,
        _request(fixture, requested_by_user_id=user_id, account_entity_ids=(fixture.accounts[0],)),
        settings=settings_for(arv2_account_research_enabled=True),
        storage=storage,
        profile_sha256=arv2_account_profile_sha256(version="v4"),
    )
    job = launch.job_ids[0]
    await conn.execute(
        text(
            "UPDATE arv2_research_job SET status='needs_review', attempt=1, started_at=now(), "
            "finished_at=now(), failure_code='d_b_a_p_i_error', failure_message='stopped' "
            "WHERE job_id=:job"
        ),
        {"job": job},
    )
    return job


def _client(conn, workspace_id: str, subject: str = "owner") -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=build_app(conn, [])),
        base_url="http://test",
        headers=headers(workspace_id, subject),
    )


def test_an_owner_lists_and_resumes_a_failed_job(tmp_path):
    async def scenario():
        async with rollback_conn() as conn:
            owner = await seed(conn)
            await load_core_pack(conn)
            ws = owner.workspace.workspace_id
            job = await _failed_job(conn, FsStorage(tmp_path), ws, "usr_jobs_api")
            async with _client(conn, ws) as client:
                listed = await client.get(STUCK)
                assert listed.status_code == 200, listed.text
                row = next(j for j in listed.json()["jobs"] if j["job_id"] == str(job))
                assert (row["state"], row["resumable"]) == ("failed", True)
                resumed = await client.post(
                    f"/frontend/v1/research/jobs/{job}/resume",
                    json={"reason": "deadlock fixed", "top_up": {}},
                )
                assert resumed.status_code == 200, resumed.text
                assert resumed.json()["status"] == "suspended"
                assert resumed.json()["restarted"] is False
                again = await client.post(
                    f"/frontend/v1/research/jobs/{job}/resume", json={"reason": "again"}
                )
                assert again.status_code == 409
                assert again.json()["error"]["code"] == "job_already_queued"
                blank = await client.post(
                    f"/frontend/v1/research/jobs/{job}/resume", json={"reason": " "}
                )
                assert blank.status_code == 409
            actor = (
                await conn.execute(
                    text("SELECT actor FROM arv2_research_job_resume WHERE job_id=:job"),
                    {"job": job},
                )
            ).scalar_one()
            assert actor == f"human:{owner.user.user_id}"

    run_async(scenario())


@pytest.mark.parametrize("role", ["owner", "admin", "operator", "viewer"])
def test_only_owners_and_admins_may_list_or_resume(tmp_path, role):
    async def scenario():
        async with rollback_conn() as conn:
            owner = await seed(conn)
            await load_core_pack(conn)
            ws = owner.workspace.workspace_id
            user = await create_platform_user(conn)
            await link_auth_identity(
                conn, user_id=user.user_id, provider_key="clerk", provider_subject="member"
            )
            await create_workspace_membership(
                conn, workspace_id=ws, user_id=user.user_id, role_key=role
            )
            job = await _failed_job(conn, FsStorage(tmp_path), ws, "usr_jobs_roles")
            expected = 200 if role in ("owner", "admin") else 403
            async with _client(conn, ws, "member") as client:
                assert (await client.get(STUCK)).status_code == expected
                resumed = await client.post(
                    f"/frontend/v1/research/jobs/{job}/resume", json={"reason": "fixed"}
                )
                assert resumed.status_code == expected, resumed.text

    run_async(scenario())


def test_another_workspaces_job_is_not_found(tmp_path):
    async def scenario():
        async with rollback_conn() as conn:
            owner = await seed(conn)
            await load_core_pack(conn)
            elsewhere = await _failed_job(conn, FsStorage(tmp_path), "ws_jobs_other", "usr_other")
            async with _client(conn, owner.workspace.workspace_id) as client:
                listed = (await client.get(STUCK)).json()["jobs"]
                assert all(j["job_id"] != str(elsewhere) for j in listed)
                resumed = await client.post(
                    f"/frontend/v1/research/jobs/{elsewhere}/resume", json={"reason": "fixed"}
                )
                assert resumed.status_code == 404
                assert resumed.json()["error"]["code"] == "job_not_found"

    run_async(scenario())
```

- [ ] **Step 2: Run them to verify they fail**

Run: `rt tests/auth/test_research_jobs_api.py`
Expected: FAIL with `assert 404 == 200` on the first `GET`, because the route does not exist yet.

- [ ] **Step 3: Implement the routes**

`platform/api/clue_api/frontend_read/research_jobs.py`:

```python
"""Admin endpoints over stuck ARV2 research jobs (spec 2026-10-14 §3.7).

Both require ``research.approve_spend`` (workspace owners and admins): a resume may top up the
job's allowance, which approves more spend.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from clue_api.arv2.job_resume import ResumeRefused, TopUp, list_stuck_jobs, resume_research_job
from clue_api.frontend_read.app import WorkspaceDep
from clue_api.frontend_read.settings_authority import lock_manager, principal_for, refused
from clue_db import ConnFactory

PERMISSION = "research.approve_spend"
#: Refusal codes that are not 409. A job in another workspace is indistinguishable from none.
_STATUS = {"job_not_found": 404}


class TopUpBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_calls: int = Field(0, ge=0)
    tool_calls: int = Field(0, ge=0)
    delegations: int = Field(0, ge=0)
    runtime_minutes: int = Field(0, ge=0)


class ResumeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str
    restart_fresh: bool = False
    top_up: TopUpBody = Field(default_factory=TopUpBody)


def register_research_job_routes(router: APIRouter, *, conn_factory: ConnFactory) -> None:
    @router.get("/research/jobs/stuck")
    async def stuck_jobs(request: Request, workspace_id: WorkspaceDep) -> dict[str, Any]:
        principal_for(request, workspace_id, permission=PERMISSION)
        async with conn_factory() as conn:
            jobs = await list_stuck_jobs(conn, workspace_id=workspace_id)
        return {"jobs": [job.as_json() for job in jobs]}

    @router.post("/research/jobs/{job_id}/resume")
    async def resume_job(
        job_id: UUID, body: ResumeBody, request: Request, workspace_id: WorkspaceDep
    ) -> dict[str, Any]:
        principal = principal_for(request, workspace_id, permission=PERMISSION)
        try:
            async with conn_factory() as conn:
                await lock_manager(conn, principal, PERMISSION)
                result = await resume_research_job(
                    conn,
                    workspace_id=workspace_id,
                    job_id=job_id,
                    actor=f"human:{principal.user_id}",
                    reason=body.reason,
                    top_up=TopUp(**body.top_up.model_dump()),
                    restart_fresh=body.restart_fresh,
                )
        except ResumeRefused as error:
            raise refused(_STATUS.get(error.code, 409), error.code, error.message) from error
        return result.as_json()
```

In `frontend_read/settings.py`, add `from clue_api.frontend_read.research_jobs import register_research_job_routes` and, after `register_research_field_routes(router, conn_factory=conn_factory)`:

```python
    register_research_job_routes(router, conn_factory=conn_factory)
```

- [ ] **Step 4: Run the tests**

Run: `rt tests/auth/test_research_jobs_api.py tests/auth/test_research_fields_settings.py tests/auth/test_settings_integration.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/frontend_read/research_jobs.py platform/api/clue_api/frontend_read/settings.py \
  tests/auth/test_research_jobs_api.py
git commit -m "Frontend API: admins list stuck research jobs and resume one

GET /frontend/v1/research/jobs/stuck and POST /frontend/v1/research/jobs/{job_id}/resume, both
gated on research.approve_spend (owners and admins), workspace from X-Workspace-Id, refusals as
named codes (404 for another workspace's job, 409 otherwise). Spec 2026-10-14 §3.7."
```

---

### Task 8: Runbook lines, full check, and memory

**Files:**
- Modify: `CLAUDE.md` (the "ARV2 work — coding agents start here" section)
- Modify: `AGENTS.md` (a new section before "## Current branch charter")
- Modify: `_memory/` session note in the dushanbe checkout

- [ ] **Step 1: Add the runbook paragraph to `CLAUDE.md`**, at the end of the "## ARV2 work — coding agents start here (added 2026-09-04)" section, after the line ending `the master plan wins.`:

```markdown

**Stuck research jobs — runbook (2026-10-14).** A failed (`needs_review`) or stalled ARV2 research job is resumed, never hand-edited in the database: `uv run python scripts/resume_arv2_research_job.py` lists every stuck job and whether it can be resumed (writes nothing); `--job <id> --reason "<why>"` plans a resume, optionally with `--top-up-*` or `--restart-fresh`, and `--apply` performs it (in production, from a worker container). Workspace owners and admins have the same operation at `GET /frontend/v1/research/jobs/stuck` and `POST /frontend/v1/research/jobs/{job_id}/resume`. Every resume is audited in `arv2_research_job_resume`. Spec: `docs/superpowers/specs/2026-10-14-arv2-research-job-resume-design.md`.
```

- [ ] **Step 2: Add the same paragraph to `AGENTS.md`** under a heading of its own, inserted directly before the line `## Current branch charter — frontend ⇄ backend ⇄ design integration (`integration/frontend-design-part-ii`)`:

```markdown
## Stuck research jobs — runbook (2026-10-14)
A failed (`needs_review`) or stalled ARV2 research job is resumed, never hand-edited in the database: `uv run python scripts/resume_arv2_research_job.py` lists every stuck job and whether it can be resumed (writes nothing); `--job <id> --reason "<why>"` plans a resume, optionally with `--top-up-*` or `--restart-fresh`, and `--apply` performs it (in production, from a worker container). Workspace owners and admins have the same operation at `GET /frontend/v1/research/jobs/stuck` and `POST /frontend/v1/research/jobs/{job_id}/resume`. Every resume is audited in `arv2_research_job_resume`. Spec: `docs/superpowers/specs/2026-10-14-arv2-research-job-resume-design.md`.

```

- [ ] **Step 3: Lint, types, contracts, and every touched test file**

```bash
cd $W
F=$(git diff --name-only origin/research-streaming...HEAD -- '*.py')
$D/.venv/bin/ruff format --check $F && $D/.venv/bin/ruff check $F
PYTHONPATH="$PP" MYPYPATH="$PP" $D/.venv/bin/mypy $(echo $F | tr ' ' '\n' | grep -v '^tests/\|^alembic/\|^scripts/')
PYTHONPATH="$PP" $D/.venv/bin/lint-imports
PYTHONPATH="$PP" $D/.venv/bin/alembic heads
TESTS=$( (git grep -l -e job_resume -e quality_research_wiring -e specialist_wiring -e agent_platform_wiring \
  -e quality_execution -e account_research_driver -e account_research_store -e frontend_read.settings -- 'tests/*.py'; \
  git diff --name-only origin/research-streaming...HEAD -- 'tests/*.py') | grep -v '_live.py' | sort -u)
rt $TESTS
```

Expected: ruff `All checks passed!`; mypy `Success`; import-linter `0 broken`; one alembic head; the test run ends `N passed` with no failures and no skips. Report any failure by name.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md AGENTS.md
git commit -m "Docs: point CLAUDE.md and AGENTS.md at the stuck research job runbook"
```

- [ ] **Step 5: Memory.** Append to `_memory/2026-10-13-disrupt-deploy-and-conduit-demo.md` in the dushanbe checkout: the branch, commit range, the tests run with their counts, the plan rulings taken, and the owed live proof. No secrets.

---

### Task 9: Live proof (founder-triggered, spends money; not run by the executor)

Owed before production use, on a lane stack, with the founder's go-ahead:

1. Start a real person research job and restart the fleet workers in the middle of it. Expected: the job continues and completes. There is exactly one opening-context receipt for its turn, and any drift is logged as `arv2.quality.resume_context_drift`.
2. Land a job in `needs_review` by stopping it mid-run. Then list it with the script, resume it with `--apply`, and confirm it completes and the account pages are rewritten. This closes spec §4 test 4.
3. Deploy a change to a tool's shape while a job is parked. Expected: the next claim restarts it, the audit records `system:instructions_changed`, and earlier purchases replay from the ledger without a second charge.
