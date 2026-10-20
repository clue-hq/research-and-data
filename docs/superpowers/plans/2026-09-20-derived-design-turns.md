# Derived Design Turns Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A message the exit judge closes and routes on renders once, and a design session starts generating the moment it opens — no "go".

**Architecture:** Both are one mechanism: a **derived turn**, a submission the server makes from the user's own bytes, marked by two nullable columns on `agent_turn_submission` (`derivation`, `derived_from_turn_id`). A derived turn keeps its durable user row (role-scoped history needs it) and renders no user bubble in the transcript. `open_design_leg` queues a derived first turn in the transaction that opens the leg; the leg runner runs it without the exit judge, addressing every document. Prompt v12 / profile v59 say generation starts at once.

**Tech Stack:** Python 3.12 (FastAPI, SQLAlchemy async, Alembic, pydantic), Postgres, TypeScript (Next.js, node:test via tsx), the agent catalog (immutable versioned prompts/profiles).

**Spec:** `docs/superpowers/specs/archive/2026-09-20-derived-design-turns-design.md`

## Global Constraints

- Repo rules: local commits only, **never push**; no AI attribution in commits; stage by explicit path; never `git stash`.
- **Never run `tests/db/test_db_migrations.py`** (it drops/recreates the live lane database). Migration reversibility is checked with `uv run alembic downgrade -1` then `uv run alembic upgrade head` against the lane DB ONLY in Task 1's step, after the stack is confirmed idle.
- Never run `make check` or broad pytest with real keys in the environment; run the named test files only, with `set -a; source .env; set +a` first (the DB tests need `CLUE_DATABASE_URL`).
- Python: `uv run ruff check <files>` and `uv run ruff format <files>` on every touched file. Frontend: `cd apps/frontend && npx tsx --test <files>` for the touched tests and `npx eslint <files>`.
- Derivation values are exactly `design_leg_redelivery` and `design_leg_first_turn`.
- Idempotency key of the first turn: `design-leg-first-turn:<leg_id>:<opening turn_id>`.
- Catalog versions are immutable: a new prompt is a new directory `v12`; a new profile is a new directory `v59`; never edit v11/v58 in place. The conversation recipe stays at 29; the manual re-mints at `manual-*@v6` (ruling 2026-09-20: the generated chapters carry the profile version in their title, so a profile bump re-mints them — the v57 precedent).
- Every commit's tests must be green before the commit; each task is its own commit.

---

### Task 1: The two columns, the row model, the redelivery stamps itself

**Files:**
- Create: `alembic/versions/c937a6b69e8a_derived_turn_submissions.py`
- Modify: `platform/api/clue_api/agent_turn_submission.py` (`_COLUMNS` line 84, `AgentTurnSubmissionRow` line 137, `insert_submission` line 182)
- Modify: `platform/api/clue_api/design_leg_tools.py` (the `insert_submission(` call at ~line 1566)
- Test: `tests/api/test_p35_finish_design_leg_db.py` (the redelivery test around line 274–302)
- Test: `tests/api/test_lane_d2_turn_submission_db.py` (one new test)

**Interfaces:**
- Produces: `AgentTurnSubmissionRow.derivation: str | None`, `AgentTurnSubmissionRow.derived_from_turn_id: UUID | None`; `insert_submission(..., derivation: str | None = None, derived_from_turn_id: UUID | None = None)`; module constants `DERIVATION_DESIGN_LEG_REDELIVERY = "design_leg_redelivery"`, `DERIVATION_DESIGN_LEG_FIRST_TURN = "design_leg_first_turn"` in `agent_turn_submission.py`.

- [ ] **Step 1: Write the migration**

```python
"""derived turn submissions

Revision ID: c937a6b69e8a
Revises: b9c5e4829868
Create Date: 2026-09-20 14:00:00.000000+00:00

Spec 2026-09-20 (derived design turns) §2.1: a submission the server made from a user's own
message bytes says so. ``derivation`` names the kind (the out-of-scope redelivery that always
existed, and the design leg's first turn), ``derived_from_turn_id`` names the turn whose bytes it
carries. Both or neither. Readers use the columns to append no second user row and render no
second user bubble.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c937a6b69e8a"
down_revision: str | None = "b9c5e4829868"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE agent_turn_submission
            ADD COLUMN derivation text NULL,
            ADD COLUMN derived_from_turn_id uuid NULL,
            ADD CONSTRAINT agent_turn_submission_derivation_kind
                CHECK (derivation IS NULL
                       OR derivation IN ('design_leg_redelivery', 'design_leg_first_turn')),
            ADD CONSTRAINT agent_turn_submission_derivation_pair
                CHECK ((derivation IS NULL) = (derived_from_turn_id IS NULL))
        """
    )
    op.execute(
        "COMMENT ON COLUMN agent_turn_submission.derivation IS 'Set when the server made this "
        "submission from a user''s own message bytes: design_leg_redelivery (an out-of-scope "
        "leg close re-delivering the message to head-of-abm) or design_leg_first_turn (the "
        "design leg''s first turn, queued by open_design_leg). NULL for a human submission.'"
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE agent_turn_submission
            DROP CONSTRAINT agent_turn_submission_derivation_pair,
            DROP CONSTRAINT agent_turn_submission_derivation_kind,
            DROP COLUMN derived_from_turn_id,
            DROP COLUMN derivation
        """
    )
```

- [ ] **Step 2: Apply it to the lane DB and prove it reverses**

Run, from the repo root with the stack UP (the migration only adds nullable columns; no process needs restarting for the schema itself):

```bash
set -a; source .env; set +a
uv run alembic heads          # expect: b9c5e4829868 (head)
uv run alembic upgrade head   # expect: b9c5e4829868 -> c937a6b69e8a
uv run alembic downgrade -1   # expect: c937a6b69e8a -> b9c5e4829868
uv run alembic upgrade head
uv run alembic heads          # expect: c937a6b69e8a (head)
```

- [ ] **Step 3: Row model + insert**

In `agent_turn_submission.py`:

```python
#: A submission the SERVER made from a user's own message bytes says which kind it is (spec
#: 2026-09-20 §2.1). Readers treat any non-NULL value the same way: no second user row, no
#: second user bubble.
DERIVATION_DESIGN_LEG_REDELIVERY = "design_leg_redelivery"
DERIVATION_DESIGN_LEG_FIRST_TURN = "design_leg_first_turn"

_COLUMNS = (
    "turn_id, workspace_id, project_id, thread_id, submitted_by_user_id, "
    "submitted_via_membership_id, onboarding_input_id, message_artifact_key, message_sha256, "
    "idempotency_key, agent_profile_id, previous_turn_outcome, requested_at, "
    "derivation, derived_from_turn_id"
)
```

`AgentTurnSubmissionRow` gains, after `requested_at`:

```python
    #: Spec 2026-09-20 §2.1: set when the server made this submission from a user's own bytes.
    derivation: str | None = None
    derived_from_turn_id: UUID | None = None
```

`insert_submission` gains two keyword parameters after `previous_turn_outcome`:

```python
    derivation: str | None = None,
    derived_from_turn_id: UUID | None = None,
```

and its INSERT lists `derivation, derived_from_turn_id` in the column list and `:derivation, :derived_from_turn_id` in VALUES (keep the existing `requested_at` expression verbatim), with the two bound in the parameter dict. Add a guard before the INSERT:

```python
    if (derivation is None) != (derived_from_turn_id is None):
        raise ValueError("a derived submission names both its derivation and its source turn")
```

Replay comparison: the existing conflict check compares the message digest; leave it as is (a replay of a derived submission carries the same digest).

- [ ] **Step 4: The redelivery stamps itself**

In `design_leg_tools.py`, the `insert_submission(` call inside the out-of-scope close (~line 1566) gains:

```python
                    derivation=DERIVATION_DESIGN_LEG_REDELIVERY,
                    derived_from_turn_id=turn.turn_id,
```

Import `DERIVATION_DESIGN_LEG_REDELIVERY` beside the existing lazy import of `insert_submission` (~line 1495).

- [ ] **Step 5: Tests**

In `tests/api/test_p35_finish_design_leg_db.py`, in the redelivery test (the one that finds `redelivered` in `thread_submissions`, ~line 297), add after the two existing byte assertions:

```python
            assert redelivered.derivation == "design_leg_redelivery"
            assert redelivered.derived_from_turn_id == closing.turn_id
            # The user's own submission is not derived from anything.
            assert closing.derivation is None and closing.derived_from_turn_id is None
```

In `tests/api/test_lane_d2_turn_submission_db.py`, add one test next to `test_duplicate_submission_replays_one_turn_and_enqueues_nothing_new` (reuse that test's seeding helpers verbatim for a workspace/project/thread and a captured message ref):

```python
def test_a_derived_submission_names_both_halves_or_neither(tmp_path: Path) -> None:
    """Spec 2026-09-20 §2.1: ``derivation`` and ``derived_from_turn_id`` travel together."""
    # ... seed exactly as the duplicate-submission test does, then:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            # (seeding here)
            with pytest.raises(ValueError, match="both its derivation"):
                await insert_submission(
                    conn,
                    turn_id=uuid4(), workspace_id=..., project_id=..., thread_id=...,
                    submitted_by_user_id=USER_ID, submitted_via_membership_id=..., onboarding_input_id=...,
                    message_artifact_key=ref.artifact_key, message_sha256=ref.sha256,
                    idempotency_key=None,
                    derivation="design_leg_first_turn",
                )
            derived, created = await insert_submission(
                conn, ... same ..., idempotency_key="derived:1",
                derivation="design_leg_first_turn", derived_from_turn_id=source_turn_id,
            )
            assert created is True
            assert derived.derivation == "design_leg_first_turn"
            assert derived.derived_from_turn_id == source_turn_id
            again = await get_submission(conn, workspace_id=..., turn_id=derived.turn_id)
            assert again is not None and again.derivation == "design_leg_first_turn"
    run_async(scenario())
```

(The `...` above are the same literal values the neighbouring test passes; copy them — the plan cannot know the helper's local names, the file can.)

- [ ] **Step 6: Run, lint, commit**

```bash
set -a; source .env; set +a
uv run pytest tests/api/test_p35_finish_design_leg_db.py tests/api/test_lane_d2_turn_submission_db.py -q -p no:cacheprovider
uv run ruff check alembic/versions/c937a6b69e8a_derived_turn_submissions.py platform/api/clue_api/agent_turn_submission.py platform/api/clue_api/design_leg_tools.py tests/api/test_p35_finish_design_leg_db.py tests/api/test_lane_d2_turn_submission_db.py
uv run ruff format <same files>
git add <those five files by path>
git commit -m "feat(turns): a derived submission says so — derivation + derived_from_turn_id; the leg redelivery stamps itself"
```

---

### Task 2: REMOVED by controller ruling (2026-09-20)

The first cut of this task (runners append no user row for a derived turn) was reverted before
review closed: `load_head_of_abm_history` filters by turn role and the leg loader by leg, so the
derived turn's own user row is the ONLY copy of the question each role's later history can see.
Dropping it left an answer with no question. The rows stay; Task 3 hides the bubble. Spec §2.2
amended. Nothing to implement here.

---

### Task 3: The wire carries `derivation`; the transcript shows no user bubble for a derived turn; the notices say "generating now"

**Files:**
- Modify: `platform/projections/clue_projections/threads.py` (`_TURN_UNION_SELECT`, `ThreadTurnView`, `_thread_turn_view`)
- Modify: `platform/api/clue_api/chat/stream.py` (the turn list `data` items ~line 380–395)
- Modify: `apps/frontend/src/features/projects/model/chat-turn.ts` (wire schema + `ChatTurn` + transform)
- Modify: `apps/frontend/src/features/projects/data/chat-turns.repository.ts` (both fixture turn literals: `derivation: null`)
- Modify: `apps/frontend/src/features/projects/model/chat-transcript.ts` (`composeTranscript`, ~line 612–636)
- Modify: `apps/frontend/src/features/projects/model/design-leg.ts` (`designLegNotice`)
- Test: `apps/frontend/src/features/projects/model/chat-transcript.test.ts`, `apps/frontend/src/features/projects/model/design-leg.test.ts`, `tests/api/test_lane_d3_turn_stream_db.py` (or wherever the `/turns` list is asserted — find with `rg -n "submission_message" tests/api`)

**Interfaces:**
- Consumes: the `derivation` column (Task 1).
- Produces: `ThreadTurnView.derivation: str | None`; turn-list wire item `"derivation": <str|null>`; `ChatTurn.derivation: string | null`.

- [ ] **Step 1: Projection + wire**

`_TURN_UNION_SELECT` adds `s.derivation,` after `s.message_sha256,`. `ThreadTurnView` gains `derivation: str | None = None` with the docstring line "Spec 2026-09-20 §2.2: set when the server made this turn from the user's own bytes; the client renders no user bubble for it." `_thread_turn_view` sets `derivation=(None if row.get("derivation") is None else str(row["derivation"]))`. In `stream.py`'s turn list item add `"derivation": item.derivation,` after `"generation_attempts"`.

- [ ] **Step 2: Frontend wire + transcript**

`chat-turn.ts`: `derivation: z.string().nullable().default(null),` in `TurnViewWireSchema`; `derivation: string | null;` on `ChatTurn` with the doc comment "Non-null when the server made this turn from the user's own message (a design-leg redelivery or first turn): the transcript renders no user bubble for it."; `derivation: item.derivation,` in the transform. Repository fixtures: `derivation: null,` in both turn literals.

`chat-transcript.ts`, in `composeTranscript`:

```ts
    const derived = durableTurn?.derivation != null;
    const durableUser = durable.find((message) => message.role === "user");
    const acceptedUser = durableTurn?.submissionMessage;
    if (derived) {
      // A derived turn (a design-leg redelivery or first turn) carries the user's own bytes,
      // which the transcript already shows under the turn they were typed on.
    } else if (durableUser) {
```

(the rest of the chain unchanged; the assistant composition below it unchanged).

`design-leg.ts`: `leg.opened` → `"Design session opened — generating now."`, `leg.reopened` → `"Design session reopened — generating now."`.

- [ ] **Step 3: Tests**

`chat-transcript.test.ts`: add `test("a derived turn renders its assistant answer and no user bubble", ...)` — turns `[{...same shape as the accepted-message test..., derivation: "design_leg_redelivery", submissionMessage: acceptedMessage}]`, messages `[the durable USER row for that turn (sequence 1), the assistant row (sequence 2)]`; assert no message with `role === "user"` for that turn and the assistant one is present (the durable user row exists — role-scoped history keeps it — and is hidden by `derivation`, not by absence); a second variant with `messages: []` and only `submissionMessage` set asserts the same; also assert a turn with `derivation: null` still renders the accepted user message (reuse the existing test's literal). Every other turn literal in this test file gains `derivation: null` (TypeScript will require it).

`design-leg.test.ts`: update the two expected strings.

Backend: in the test that asserts the `/turns` list payload (find with `rg -n "submission_message" tests/api`), assert `"derivation" in item` and `item["derivation"] is None` for a human turn. If no such test exists, add the assertion to `tests/api/test_lane_d2_turn_submission_db.py::test_a_submitted_turn_is_durable_and_queued_before_anything_runs` by reading the turn through `thread_turns(...)` and asserting `.derivation is None`.

- [ ] **Step 4: Run, lint, commit**

```bash
cd apps/frontend && npx tsx --test src/features/projects/model/chat-transcript.test.ts src/features/projects/model/design-leg.test.ts src/features/projects/model/chat-turn.test.ts 2>/dev/null; npx eslint <touched ts files>; npx tsc --noEmit -p tsconfig.json | rg "chat-turn|chat-transcript|design-leg|chat-turns.repository"   # expect nothing new
cd ../.. && set -a; source .env; set +a && uv run pytest <the backend test file> -q -p no:cacheprovider
git commit -m "feat(chat): the turn list says which turns are derived; the transcript shows no user bubble for them; leg notices say generating now"
```

---

### Task 4: `open_design_leg` queues the leg's first turn

**Files:**
- Modify: `platform/api/clue_api/design_leg_tools.py` (`OpenDesignLegTool.invoke` ~line 696–850; the tool's output references)
- Test: `tests/api/test_p34_design_leg_tool_db.py`

**Interfaces:**
- Consumes: `insert_submission(..., derivation=, derived_from_turn_id=)`, `DERIVATION_DESIGN_LEG_FIRST_TURN`, `submission_context_refs`, `dispatch_next_thread_turn`, `get_submission`, `turn_id_for_submission` (all in `clue_api.agent_turn_submission`).
- Produces: nothing new on the wire. Ruling 2026-09-20: `OpenDesignLegOutput` is the tool's `output_model` and the profile pins its schema digest, so the references do NOT change; the tool logs `design_leg.first_turn_queued` (`leg_id`, `turn_id`, `first_turn_id`). The derived id is `turn_id_for_submission(workspace_id=, thread_id=, idempotency_key=f"design-leg-first-turn:{leg_id}:{opening_turn_id}")`.

- [ ] **Step 1: A helper on the tool**

```python
    async def _queue_first_turn(
        self, conn: AsyncConnection, *, ctx: ToolContext, turn: TurnIdentity, leg_id: str
    ) -> str | None:
        """Spec 2026-09-20 §2.3: the leg's first design turn, queued in the transaction that
        opened (or reopened) the leg, from the opening turn's own submission — so nobody has to
        say "go". Derived under ONE key per (leg, opening turn): a replayed open converges on
        the same submission. A turn with no submission of its own (machine-originated) queues
        nothing and the leg waits for the user exactly as before."""
        submission = await get_submission(conn, workspace_id=ctx.workspace_id, turn_id=turn.turn_id)
        if submission is None:
            log.info("design_leg.first_turn_skipped_no_submission", leg_id=leg_id, turn_id=str(turn.turn_id))
            return None
        key = f"design-leg-first-turn:{leg_id}:{turn.turn_id}"
        first_turn_id = turn_id_for_submission(
            workspace_id=ctx.workspace_id, thread_id=turn.thread_id, idempotency_key=key
        )
        context_refs = await submission_context_refs(conn, workspace_id=ctx.workspace_id, turn_id=turn.turn_id)
        await insert_submission(
            conn,
            turn_id=first_turn_id,
            workspace_id=ctx.workspace_id,
            project_id=submission.project_id,
            thread_id=turn.thread_id,
            submitted_by_user_id=submission.submitted_by_user_id,
            submitted_via_membership_id=submission.submitted_via_membership_id,
            onboarding_input_id=submission.onboarding_input_id,
            message_artifact_key=submission.message_artifact_key,
            message_sha256=submission.message_sha256,
            idempotency_key=key,
            context_refs=context_refs,
            derivation=DERIVATION_DESIGN_LEG_FIRST_TURN,
            derived_from_turn_id=turn.turn_id,
        )
        # A no-op while the opening turn's own task is in flight; the worker offers the next
        # turn when that task finishes (the redelivery relies on the same property).
        await dispatch_next_thread_turn(conn, workspace_id=ctx.workspace_id, thread_id=turn.thread_id)
        log.info("design_leg.first_turn_queued", leg_id=leg_id, turn_id=str(turn.turn_id), first_turn_id=str(first_turn_id))
        return str(first_turn_id)
```

Imports: the same lazy-import block the exit tool uses (~line 1495) — move it to a module-level import if the tool module does not already import these names at the top; keep the existing exit-tool behaviour unchanged.

- [ ] **Step 2: Call it on both opening paths**

In `invoke`: after `_emit_leg_lifecycle(... LEG_REOPENED ...)` and after `_emit_leg_lifecycle(... LEG_OPENED ...)` (still inside the `async with self._conn_factory() as conn:` block) call `await self._queue_first_turn(conn, ctx=ctx, turn=resolved.turn, leg_id=str(leg["id"]))`. The `existing_leg` replay branch does nothing new (the first call already queued; `insert_submission` under the same key would replay anyway, but there is no need to touch it). The tool's `references` and `OpenDesignLegOutput` are NOT changed.

- [ ] **Step 3: Tests** (`tests/api/test_p34_design_leg_tool_db.py`)

In the full-delegation test (~line 222–320, the one that asserts `leg["state"] == "open_awaiting_user"` and then replays):

```python
            first_turn_id = turn_id_for_submission(
                workspace_id=seeds["workspace_id"],
                thread_id=seeds["thread_id"],
                idempotency_key=f"design-leg-first-turn:{refs['leg_id']}:{seeds['turn_id']}",
            )
            first = await get_submission(conn, workspace_id=seeds["workspace_id"], turn_id=first_turn_id)
            assert first is not None
            assert first.derivation == "design_leg_first_turn"
            assert first.derived_from_turn_id == seeds["turn_id"]
            opening = await get_submission(conn, workspace_id=seeds["workspace_id"], turn_id=seeds["turn_id"])
            assert (first.message_artifact_key, first.message_sha256) == (opening.message_artifact_key, opening.message_sha256)
            assert first.thread_id == seeds["thread_id"]
```

and after the replay: `submissions_for_thread(...)` holds exactly ONE submission with `derivation == "design_leg_first_turn"` (the replayed open queued nothing new). If the seeded opening turn in this test has no submission row, seed one the way the exit-bridge test seeds the closing turn's submission (`tests/api/test_p37_exit_bridge_db.py` ~line 280–300) before invoking the tool. Add one more test: opening from a turn with NO submission inserts no derived submission (`submissions_for_thread` holds none with a derivation) and the leg is still `open_awaiting_user`.

- [ ] **Step 4: Run, lint, commit**

```bash
set -a; source .env; set +a
uv run pytest tests/api/test_p34_design_leg_tool_db.py tests/api/test_p35_finish_design_leg_db.py -q -p no:cacheprovider
uv run ruff check / format
git commit -m "feat(design-legs): open_design_leg queues the leg's first turn from the user's own message — no more go"
```

---

### Task 5: The leg runner runs the first turn without the exit judge, on every document

**Files:**
- Modify: `platform/api/clue_api/design_leg_wiring.py` (`run_leg_turn`, the `exit_decision = await self._judge_exit(` block ~line 1350)
- Test: `tests/api/test_p34_design_leg_engine_db.py`

**Interfaces:**
- Consumes: `submission.derivation == DERIVATION_DESIGN_LEG_FIRST_TURN` (Task 1). Extend the test file's `_submit_message` (~line 194) with keyword arguments `derivation: str | None = None, derived_from_turn_id: UUID | None = None` passed straight to `insert_submission` (Task 2 was removed, so this task adds them).

- [ ] **Step 1: Skip the judge on the first turn**

```python
            if submission.derivation == DERIVATION_DESIGN_LEG_FIRST_TURN:
                # Spec 2026-09-20 §2.3: the leg's first turn is the ask that opened it, queued
                # by open_design_leg. Nobody has spoken ON the leg yet, so there is nothing to
                # judge, and it addresses every document of the leg.
                log.info("design_leg.first_turn", leg_id=leg_id, turn_id=str(turn_id), documents=len(leg_documents))
                exit_decision = None
            else:
                exit_decision = await self._judge_exit(...)   # the existing call, unchanged
```

The `addressed` computation below already defaults to every document when `exit_decision is None`. Import the constant from `clue_api.agent_turn_submission`.

- [ ] **Step 2: Test**

`test_the_first_turn_of_a_leg_runs_every_document_without_the_judge`: build the runner with `exit_judge=` a callable that raises `AssertionError("the first turn is never judged")` and a finisher (so `_judge_exit` would run if reached — see how the existing judged tests in this file or `tests/api/test_p37_exit_bridge_db.py` construct the runner with a judge; copy that construction), submit with `derivation="design_leg_first_turn", derived_from_turn_id=<the leg's opening turn id from seeds>`, run with `_FakeLane(...)`; assert the outcome is `AWAITING_INPUT`, the lane saw exactly one envelope (one-document leg), and the turn's `agent_thread_message` roles are `["user", "assistant"]` (the row stays — ruling 2026-09-20; the transcript hides it). Then a control: the same runner on a NON-derived submission raises the judge's `AssertionError` (proving the judge is reached on ordinary turns).

- [ ] **Step 3: Run, lint, commit**

```bash
set -a; source .env; set +a
uv run pytest tests/api/test_p34_design_leg_engine_db.py -q -p no:cacheprovider
git commit -m "feat(design-legs): the leg's first turn skips the exit judge and addresses every document"
```

---

### Task 6: Prompt v12, profile v59, the pins

**Files:**
- Create: `platform/agents/catalog/prompts/head-of-abm/v12/SYSTEM.md` (copy of v11 with one sentence changed)
- Create: `platform/agents/catalog/profiles/head-of-abm/v59/profile.yaml` (copy of v58: `version: v59`, prompt pin `v12` + its sha256, the manual chapters re-pinned at `v6`, a new leading header comment)
- Create: `platform/agents/catalog/skills/manual-*/v6/SKILL.md` — re-minted by the manual builder (`platform/agents/clue_agents/manual/build.py::PROFILE_VERSION` → `"v59"`, then `make manual` or the builder's own command) so every chapter's body is byte-identical to v5 except the header line naming the profile version
- Modify: `platform/api/clue_api/agent_registry_wiring.py` (`C6_ACTIVE_PROFILE_VERSIONS[HEAD_OF_ABM]` → `"v59"` with a comment in the house style)
- Modify: every pin the tests hold — find them all with `rg -n '"v58"|head-of-abm@v58' platform tests` and move each to v59 where it names the ACTIVE version (the historical lists that enumerate every registered version, e.g. `tests/agents/test_catalog.py` ~line 330–345, gain a `"profile:head-of-abm@v59"` entry with a one-line comment; `tests/agents/test_manual_drift.py`'s comment block gains "Unmoved a fourth time at `head-of-abm@v59`: it changes only the prompt.")

**Interfaces:**
- Produces: active profile `head-of-abm@v59`, prompt `head-of-abm@v12`.

- [ ] **Step 1: Prompt v12**

Copy `v11/SYSTEM.md` to `v12/SYSTEM.md`. Replace exactly:

```
summary it hands back. Opening a leg starts nothing: the user's next message begins generation,
and every artifact generates at the same time, for minutes. Say the design session is open, name
what will be made, and end your turn.
```

with:

```
summary it hands back. Opening a leg starts generation at once: every artifact generates at the
same time, for minutes, and the user need not say anything to begin. Say the design session is
open and what is being made, and end your turn.
```

Nothing else changes. Compute `shasum -a 256 platform/agents/catalog/prompts/head-of-abm/v12/SYSTEM.md`.

- [ ] **Step 2: Profile v59**

Copy `v58/profile.yaml` to `v59/profile.yaml`; set `version: v59`; set `prompt.version: v12` and `prompt.sha256` to the digest from Step 1; prepend a header comment in the file's own style:

```
# v59 (the leg's first turn starts itself — spec 2026-09-20): v58's surface exactly — the same
# grant, the same skills, the same workspace, the same caps — with the prompt that no longer tells
# the user to speak before generation begins. `open_design_leg@5` now queues the leg's first
# design turn from the user's own message in the transaction that opens the leg, so prompt
# v11 -> v12 changes one sentence: "Opening a leg starts nothing: the user's next message begins
# generation" becomes "Opening a leg starts generation at once". No tool address moves, so the
# conversation recipe stays at 29. The manual re-mints at `manual-*@v6` because its generated
# chapters render THIS profile's version into their title (the v57 precedent); every body is
# byte-identical to v5.
```

- [ ] **Step 3: Pins**

Registry default → `"v59"` with a comment in the style of the v58 comment above it. Then run `rg -n '"v58"|head-of-abm@v58' platform tests` and move every ACTIVE-version pin (the ones that assert what production resolves to) to v59; leave historical enumerations and comments that describe v58's own change as they are, adding v59 entries where a list enumerates every registered profile.

- [ ] **Step 4: Run, lint, commit**

```bash
set -a; source .env; set +a
uv run pytest tests/agents/test_catalog.py tests/agents/test_manual_drift.py tests/api/test_agent_registry_wiring.py tests/api/test_comprehensive_research_contract.py tests/api/test_client_knowledge_privacy_s4e.py tests/api/test_recipe_contracts.py -q -p no:cacheprovider
git add platform/agents/catalog/prompts/head-of-abm/v12/SYSTEM.md platform/agents/catalog/profiles/head-of-abm/v59/profile.yaml platform/api/clue_api/agent_registry_wiring.py <every test file touched>
git commit -m "feat(head-of-abm): v59 — prompt v12, a design session starts generating at once"
```

---

### Task 7 (controller): stack, records, live check

- [ ] Restart the platform APIs and the fleet workers through the runbook (`./scripts/dev_stack_san_salvador.sh restart-api` and `restart-workers`, each under `timeout 40`).
- [ ] Records: `_memory/2026-09-20-derived-design-turns.md`; a CLAUDE.md bullet `[design×legs]` addendum; note the migration for the other lanes.
- [ ] Owed live proof (founder-triggered): one ask for two tagged accounts → the transcript shows the ask once, "Design session opened — generating now.", two runs start with no further message, the per-document summary lands; a later out-of-scope message closes the leg and shows once.
