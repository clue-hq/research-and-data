# Design Clarification Cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A design document's opening-move questions reach the user as a card above the composer, and the user's answer reaches the document that asked.

**Architecture:** The design runtime already produces the questions on the run result. A new `clarification` transcript part carries them from the leg runner to the client (live and on reload, like gate/plan parts); the leg's summary text carries them durably. "Open question" is derived from the document's latest terminal run, and feeds both the exit judge's artifact line and the per-document one-round guard. The card composes one ordinary chat message with a `design_document` context ref per answered document; routing stays the judge's.

**Tech Stack:** Python 3.12 (FastAPI, SQLAlchemy async, Alembic, pydantic), Postgres, TypeScript (Next.js, node:test via tsx, CSS modules over `@clue/design-system` tokens).

**Spec:** `docs/superpowers/specs/archive/2026-09-20-design-clarification-cards-design.md`

## Global Constraints

- Repo rules: local commits only, **never push**; no AI attribution in commits; stage by explicit path; never `git stash`.
- **Never run `tests/db/test_db_migrations.py`** (it drops the live lane database). Migration reversibility: `uv run alembic downgrade -1` then `upgrade head` on the lane DB, once, in Task 1.
- Never `make check` or broad pytest with real keys; run only the named test files, after `set -a; source .env; set +a`.
- Python: `uv run ruff check` + `uv run ruff format` on touched files. Frontend: `cd apps/frontend && npx tsx --test <files>`, `npx eslint <files>`, and `npx tsx --test src/design-system-tokens.test.ts` whenever a stylesheet changes.
- Part kind value: exactly `clarification`. Part id: `clarification:<document_id>`.
- Summary sentence: `Asked you {n} question{s} before designing: {q1}; {q2}.` — question texts verbatim, joined by `; `, terminated by `.`; `question`/`questions` by count.
- Exit judge artifact suffix: ` [asked: "<q1>" | "<q2>"]` (question texts verbatim, `" | "` between). Exit prompt version `v3` → `v4`.
- Card copy: header `<title> · <account>` (account omitted when null); pager `{i} of {n}`; free-text row placeholder `Something else…`; skip button `Skip` (its hover title `Skip — use {default}`; label shortened by founder 2026-09-21); strip `{k} designs have questions`; collapsed chip `{n} question{s} from {title} — answer`; hint line `↑↓ to navigate · Enter to select · Esc to skip`.
- Reply text format (exact):
  ```
  For "<title>":
  - <question> — <answer>
  - <question> — something else: <typed text>
  - <question> — use your default (<default>)
  ```
  documents separated by one blank line; one `design_document` context ref per document, in order.
- Tokens: only `--clue-ds-*` variables already present in `packages/design-system/generated/tokens.css`; no hex; no new variables.
- Founder rulings: opening-move only; finished siblings show summary lines, only the asking document gets a card; nothing waits on the answer.

---

### Task 1: The `clarification` part — model, CHECK, emitter

**Files:**
- Modify: `platform/api/clue_api/chat/turn_parts.py` (`PartKind` ~line 62, models after `GatePart` ~line 286, `TurnPart` union ~line 305)
- Modify: `platform/api/clue_api/chat/turn_stream.py` (`TurnStreamEmitter`, add `emit_clarification_part` after `emit_gate_part` ~line 885)
- Create: `alembic/versions/fc9580642b71_clarification_part_kind.py`
- Test: `tests/api/test_lane_d3_turn_stream_db.py` (one new test; the file's existing emitter harness — see `test_tool_parts_carry_the_lifecycle_and_the_durable_receipt` ~line 915 for how an emitter is opened and frames are read back)

**Interfaces:**
- Produces: `PartKind.CLARIFICATION = "clarification"`; `ClarificationQuestion(id, question, why_it_matters, options: tuple[str, ...], default, allow_freeform: bool)`; `ClarificationPart(part_id, revision, document_id, document_title, doc_kind, account_name: str | None, run_id, questions: tuple[ClarificationQuestion, ...])`; `clarification_part_id(document_id) -> str`; `TurnStreamEmitter.emit_clarification_part(*, document_id, document_title, doc_kind, account_name, run_id, questions: Sequence[Mapping[str, Any]]) -> None`.

- [ ] **Step 1: Models**

```python
class ClarificationQuestion(BaseModel):
    """One question the design runtime asked before designing (its ``request_clarification``
    payload, field for field). ``default`` is what the runtime uses when the answer is skipped."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    question: str
    why_it_matters: str = ""
    options: tuple[str, ...] = ()
    default: str
    allow_freeform: bool = True


class ClarificationPart(_Part):
    """Spec 2026-09-20 (clarification cards) §2.1: a document's opening-move questions.

    Emitted by the leg runner once per addressed document whose terminal run ended
    ``clarification_requested``. The card the client renders above the composer; on a turn that
    is no longer the latest it renders read-only. The durable record is the summary sentence on
    the turn's assistant message — this part is the live/replayed projection, like a gate's.
    """

    kind: PartKind = PartKind.CLARIFICATION
    document_id: str
    document_title: str
    doc_kind: str
    account_name: str | None = None
    run_id: str
    questions: tuple[ClarificationQuestion, ...]


def clarification_part_id(document_id: str) -> str:
    return f"clarification:{document_id}"
```

Add `CLARIFICATION = "clarification"` to `PartKind` (after `ACTION`) and `ClarificationPart` to the `TurnPart` union.

- [ ] **Step 2: Emitter**

```python
    async def emit_clarification_part(
        self,
        *,
        document_id: str,
        document_title: str,
        doc_kind: str,
        account_name: str | None,
        run_id: str,
        questions: Sequence[Mapping[str, Any]],
    ) -> None:
        """Spec 2026-09-20 §2.1: the questions a document's run asked, as one part per document."""

        part_id = clarification_part_id(document_id)
        await self._part(
            TurnEventType.PART_CREATED,
            ClarificationPart(
                part_id=part_id,
                revision=self._revision(part_id),
                document_id=document_id,
                document_title=document_title,
                doc_kind=doc_kind,
                account_name=account_name,
                run_id=run_id,
                questions=tuple(
                    ClarificationQuestion(
                        id=str(q["id"]),
                        question=str(q["question"]),
                        why_it_matters=str(q.get("why_it_matters") or ""),
                        options=tuple(str(o) for o in (q.get("options") or ())),
                        default=str(q["default"]),
                        allow_freeform=bool(q.get("allow_freeform", True)),
                    )
                    for q in questions
                ),
            ),
        )
```

- [ ] **Step 3: Migration** (`fc9580642b71`, down_revision `c937a6b69e8a`): drop `agent_turn_event_stream_part_kind` and re-add it with the list from `98a5ddafa21b` plus `'clarification'`; `downgrade` restores the old list. Copy the `_quoted`/list style of `98a5ddafa21b` lines 89–100 and 134–135. Apply: `alembic upgrade head`, `downgrade -1`, `upgrade head` (the stack may stay up).

- [ ] **Step 4: Test** — `test_a_clarification_part_lands_on_the_outbox_with_its_questions`: open an emitter as the file's tool-part test does, call `emit_clarification_part` with two questions (one with options, one without), read the outbox frame back and assert `event_type == "part.created"`, `part_kind == "clarification"`, `part_id == "clarification:doc_x"`, the two questions round-trip field for field (`options` as a list, `allow_freeform` default `True`).

- [ ] **Step 5: Run, lint, commit** — `uv run pytest tests/api/test_lane_d3_turn_stream_db.py -q -p no:cacheprovider`; ruff; `git commit -m "feat(chat): a clarification part carries a design document's opening questions"`.

---

### Task 2: Honest summary text and the open-question read

**Files:**
- Modify: `platform/api/clue_api/design_leg_wiring.py` (`_assistant_summary` ~line 825; `batch_summary` ~line 910)
- Modify: `subsystems/design/clue_design/runs.py` (add `latest_terminal_run_for_document` after `active_run_for_document` ~line 549)
- Test: `tests/api/test_p34_design_leg_engine_db.py` (beside `test_scene_summary_distinguishes_acceptance_from_execution_success` ~line 452)
- Test: `tests/design/test_durable_jobs_dal_db.py` (one new DAL test using that file's run seeding)

**Interfaces:**
- Produces: `clarification_sentence(result: Mapping[str, Any]) -> str | None` in `design_leg_wiring.py` (module-level, returns the sentence or `None` when the result is not a clarification); `design_runs.latest_terminal_run_for_document(conn, *, workspace_id, document_id) -> JsonObject | None` (the newest `succeeded`/`failed` run whose payload `document_id` matches, full row as `get_run` returns it).

- [ ] **Step 1: The sentence**

```python
def clarification_sentence(result: Mapping[str, Any]) -> str | None:
    """Spec 2026-09-20 §2.2: the durable record of an opening-move clarification, or ``None``."""

    if str(result.get("status") or "") != "clarification_requested":
        return None
    questions = (result.get("clarification") or {}).get("questions") or []
    texts = [str(q.get("question") or "").strip() for q in questions if q.get("question")]
    n = len(texts)
    noun = "question" if n == 1 else "questions"
    return f"Asked you {n} {noun} before designing: {'; '.join(texts)}."
```

In `_assistant_summary`, right after `status = ...` and before the `proposed` branch: `sentence = clarification_sentence(result); if sentence is not None: return sentence`. `batch_summary` needs no change beyond that (a succeeded run's line already calls `_assistant_summary`); confirm the line reads `<title>: Asked you 2 questions before designing: … (now version N)` only if `current_version` is present (a clarification writes nothing, so normally no version suffix).

- [ ] **Step 2: The DAL read**

```python
async def latest_terminal_run_for_document(
    conn: AsyncConnection, *, workspace_id: str, document_id: str
) -> JsonObject | None:
    """The newest TERMINAL run whose frozen envelope targets ``document_id``, else ``None``.

    Spec 2026-09-20 (clarification cards) §2.3: "this document has an open question" is derived
    — its latest terminal run's result status is ``clarification_requested`` — never stored.
    Same predicate as :func:`active_run_for_document` (the payload, not the nullable column).
    """
    row = (
        await conn.execute(
            text(
                "SELECT * FROM design_agent_run"
                " WHERE workspace_id = :w AND status IN ('succeeded', 'failed')"
                "   AND payload ->> 'document_id' = :d"
                " ORDER BY created_at DESC, run_id DESC"
                " LIMIT 1"
            ),
            {"w": workspace_id, "d": document_id},
        )
    ).mappings().first()
    return None if row is None else _row_to_run(dict(row))
```

(`_row_to_run` = whatever `get_run` uses to shape a row; use the same helper.)

- [ ] **Step 3: Tests** — summary: `clarification_sentence({"status": "clarification_requested", "clarification": {"questions": [{"question": "Which proof point?"}, {"question": "Which tone?"}]}}) == "Asked you 2 questions before designing: Which proof point?; Which tone?."`, singular form, and `None` for a proposed result; `_assistant_summary` on such a run returns the sentence. DAL: seed two terminal runs for one document (older `succeeded` with a plain result, newer `succeeded` with `result_json.status = "clarification_requested"`) plus one `running`; assert the read returns the newer terminal one and `None` for an unknown document.

- [ ] **Step 4: Run, lint, commit** — `git commit -m "feat(design-legs): a clarification reads honestly in the summary; the open question is derived from the latest terminal run"`.

---

### Task 3: The leg runner emits the parts, derives the per-document guard, and tells the judge

**Files:**
- Modify: `platform/api/clue_api/design_leg_wiring.py` (`run_leg_turn` after the batch ~line 1540–1580; `_finalize_awaiting_input` ~line 1611; `_envelope` scene request ~line 2509; `_exit_judge_artifact_lines` ~line 1830)
- Modify: `subsystems/design/clue_design/exit_judgment.py` (`EXIT_JUDGMENT_PROMPT_VERSION = "v4"`; one sentence in `render_exit_judgment_prompt`)
- Test: `tests/api/test_p34_design_leg_engine_db.py`, `tests/api/test_multi_artifact_leg_engine_db.py` (~line 737), `tests/api/test_p37_exit_judge_unit.py`, `tests/design/test_exit_judgment_golden.py` (~line 265)

**Interfaces:**
- Consumes: Task 1's `emit_clarification_part`; Task 2's `clarification_sentence`, `latest_terminal_run_for_document`.
- Produces: `_finalize_awaiting_input(..., clarifications: Sequence[dict[str, Any]] = ())` where each item is the kwargs of `emit_clarification_part`.

- [ ] **Step 1: Emit after the batch** — in `run_leg_turn`, after `dispatched` is known and before the summary: build `clarifications` = for each `(document, run)` in `dispatched` where `(run.get("result") or {}).get("status") == "clarification_requested"`: `{"document_id": document["document_id"], "document_title": _document_title(document), "doc_kind": str((run.get("result") or {}).get("doc_kind") or document.get("doc_kind") or "scene"), "account_name": (account_cards.get(key) or {}).get("name"), "run_id": str(run["run_id"]), "questions": ((run.get("result") or {}).get("clarification") or {}).get("questions") or []}`. Pass it to `_finalize_awaiting_input(..., clarifications=clarifications)`, which emits each via `stream.emit_clarification_part(**item)` BEFORE `stream.rehydrate(...)` (only when `stream is not None`). Log `design_leg.clarifications_emitted` with `documents=len(clarifications)`.

- [ ] **Step 2: Per-document guard** — in `_envelope`, for the scene request: replace `"previous_turn_outcome": submission.previous_turn_outcome` with the derived value:

```python
        previous_outcome = submission.previous_turn_outcome
        if document_id is not None:
            async with self._conn_factory() as conn:
                latest = await design_runs.latest_terminal_run_for_document(
                    conn, workspace_id=workspace_id, document_id=str(document_id)
                )
            if latest is not None and str(
                (latest.get("result") or {}).get("status") or ""
            ) == "clarification_requested":
                # Spec 2026-09-20 §2.4: the one-round guard is per document and derived here,
                # never echoed by the client.
                previous_outcome = "clarification_requested"
```

and use `previous_outcome` in the request dict. The web request is untouched (documented residual).

- [ ] **Step 3: The judge** — `_exit_judge_artifact_lines` gains, per document with a `document_id`, a read of `latest_terminal_run_for_document`; if its result status is `clarification_requested`, append ` [asked: "<q1>" | "<q2>"]` from the result's questions. In `render_exit_judgment_prompt`, under "How to reason about it:", add the line: `"- An artifact marked [asked: …] is waiting for an answer; a message that answers one of\n  those questions is work on THAT artifact, even when it names nothing.\n"` and bump `EXIT_JUDGMENT_PROMPT_VERSION` to `"v4"`.

- [ ] **Step 4: Tests**
  - `tests/api/test_p34_design_leg_engine_db.py`: a `_FakeLane` variant whose result is `{"schema_version": 1, "status": "clarification_requested", "stop_reason": "clarification_requested", "summary": "…", "clarification": {"questions": [{"id": "proof", "question": "Which proof point should lead the ad?", "why_it_matters": "It decides the headline.", "options": ["The 40% stat", "The logo wall"], "default": "The 40% stat"}]}}`; run the turn with a REAL emitter opened the way `tests/api/test_p37_leg_stream_events_db.py` opens one; assert the outcome is `AWAITING_INPUT`, the assistant message body is `Asked you 1 question before designing: Which proof point should lead the ad?.`, the outbox holds one `part.created` with `part_kind == "clarification"` and `part_id == f"clarification:{document_id}"` BEFORE the rehydrate frame; then submit a second message on the leg (a judge that returns a stay on `[1]`) and assert the lane's second envelope request carries `previous_turn_outcome == "clarification_requested"`.
  - `tests/api/test_multi_artifact_leg_engine_db.py` (~line 737): seed a terminal clarification run for "Mercy ad" and assert its line reads `'2. "Mercy ad" (scene ad) [asked: "Which proof point should lead the ad?"]'` while the others are unchanged.
  - `tests/api/test_p37_exit_judge_unit.py`: the prompt contains the new sentence and `prompt_version: v4`; `tests/design/test_exit_judgment_golden.py` line 265 → `v4`; the golden set still passes.

- [ ] **Step 5: Run, lint, commit** — the four test files; `git commit -m "feat(design-legs): a document's questions ride the turn as clarification parts; the guard is per document; the judge sees the open question"`.

---

### Task 4: Frontend model — the part, "which questions are open", and the reply text

**Files:**
- Modify: `apps/frontend/src/features/projects/model/chat-parts.ts` (`ChatPartKindSchema` line 25; a `ClarificationPartWireSchema` beside `GatePartWireSchema` ~line 400; `ChatClarificationPart`; the union at ~line 524; the parser switch ~line 598)
- Create: `apps/frontend/src/features/projects/model/clarification.ts`
- Test: `apps/frontend/src/features/projects/model/clarification.test.ts`, `apps/frontend/src/features/projects/model/chat-events.test.ts` (if present — else `chat-transcript.test.ts`) for the wire parse

**Interfaces:**
- Produces:
  ```ts
  export interface ChatClarificationQuestion { id: string; question: string; whyItMatters: string; options: readonly string[]; default: string; allowFreeform: boolean }
  export interface ChatClarificationPart { kind: "clarification"; partId: string; revision: number; documentId: string; documentTitle: string; docKind: string; accountName: string | null; runId: string; questions: readonly ChatClarificationQuestion[] }
  export type ClarificationAnswer = { kind: "option"; value: string } | { kind: "freeform"; value: string } | { kind: "skipped"; default: string };
  export interface OpenClarification { turnId: string; parts: readonly ChatClarificationPart[] }
  export function openClarification(transcript: readonly TranscriptMessage[]): OpenClarification | null;
  export function composeClarificationReply(items: ReadonlyArray<{ part: ChatClarificationPart; answers: ReadonlyMap<string, ClarificationAnswer> }>): { text: string; contextRefs: TurnContextReference[] };
  ```
- `openClarification`: the LAST assistant message in the transcript (by order) whose `parts` contain clarification parts AND whose turn is terminal (`state` in awaiting_input/completed) AND no later message exists → its turn id and parts in order; otherwise `null`.

- [ ] **Step 1: Wire + parse** — schema with `partBase`, `kind: z.literal("clarification")`, `document_id`, `document_title`, `doc_kind`, `account_name` nullable optional, `run_id`, `questions: z.array(z.object({ id, question, why_it_matters: z.string().default(""), options: z.array(z.string()).default([]), default: z.string(), allow_freeform: z.boolean().default(true) }))`; parser case mapping to camelCase.

- [ ] **Step 2: `clarification.ts`** — the two functions above. The reply text must match the Global Constraints format exactly; a `freeform` answer renders `— something else: <text>`, `skipped` renders `— use your default (<default>)`, `option` renders `— <value>`. Context refs: `{ objectId: part.documentId, objectType: "design_document", version: null }` per part.

- [ ] **Step 3: Tests** — parse a wire part; `openClarification` returns the latest terminal design turn's parts and `null` when a later message exists or the turn is running; `composeClarificationReply` produces the exact text for one document with three answer kinds and for two documents (blank line between), with two refs in order.

- [ ] **Step 4: Run, lint, commit** — `npx tsx --test` the two test files; eslint; `git commit -m "feat(chat): the clarification part on the client, and the reply it composes"`.

---

### Task 5: The card

**Files:**
- Create: `apps/frontend/src/features/chat-shell/components/clarification-card.tsx`, `apps/frontend/src/features/chat-shell/components/clarification-card.module.css`
- Modify: `apps/frontend/src/features/projects/components/chat-message-part.tsx` (case `"clarification"` → the read-only `ClarificationHistoryCard`, exported from the same component file)
- Modify: `apps/frontend/src/features/chat-shell/components/chat-surface.tsx` (mount above `<ProjectComposer` ~line 1055, beside the queue controls)
- Test: `apps/frontend/src/features/chat-shell/components/clarification-card.test.tsx` is NOT required (no DOM test runner in this repo); the pure logic lives in Task 4's model and its tests. Run `src/design-system-tokens.test.ts`.

**Interfaces:**
- Consumes: Task 4's `openClarification`, `composeClarificationReply`, `ChatClarificationPart`.
- Produces: `<ClarificationCard parts={…} onSubmit={(text, contextRefs) => …} onDismiss={() => …} />` and `<ClarificationHistoryCard part={…} />`.

- [ ] **Step 1: Component behaviour** — state: `{ documentIndex, questionIndex, answers: Map<`${documentId}:${questionId}`, ClarificationAnswer>, collapsed: boolean, freeform: string }`. Header `<title> · <account>` + pager `{i} of {n}` over the CURRENT document's questions with ‹ › buttons + ✕ (sets `collapsed`). Body: question, `why_it_matters` in the subtle colour, numbered option buttons (digit keys, ↑↓ focus, Enter selects), the free-text row (placeholder `Something else…`, Enter submits it), `Skip — use {default}`. Selecting/typing/skipping records the answer and advances; after the last question of the last document, call `onSubmit(composeClarificationReply(...))`. A strip above the card when `parts.length > 1`: `{k} designs have questions`. Collapsed state renders the chip `{n} question{s} from {title} — answer` (click expands). Hint line beneath the card. `aria-live="polite"` on the question text; buttons are real `<button type="button">`.

- [ ] **Step 2: Stylesheet** — CSS module using ONLY: `--clue-ds-color-bg-page` (card), `--clue-ds-color-bg-subtle` (selected option), `--clue-ds-color-bg-neutral-hover` / `-pressed`, `--clue-ds-color-border-subtle` (rows), `--clue-ds-color-border-neutral` (card), `--clue-ds-color-border-brand-default` (focused option), `--clue-ds-color-content-neutral`, `--clue-ds-color-content-subtle` (why line, hint, pager), `--clue-ds-color-content-disabled`, `--clue-ds-shadow-card-subtle`, `--clue-ds-product-component-button-sm-radius` (option/skip buttons), `--clue-ds-product-component-button-md-radius` (card), `--clue-ds-product-motion-duration-fast` + `--clue-ds-product-motion-easing-standard` (hover/expand), `--clue-ds-typography-text-default-font-family`. Verify every one exists with `rg -c "<name>:" packages/design-system/generated/tokens.css` before use; if one is missing, pick the nearest existing semantic token and note it in the report — never add a variable.

- [ ] **Step 3: Mount** — in `chat-surface.tsx`, `const clarification = useMemo(() => openClarification(chat.transcript), [chat.transcript]);` and render `<ClarificationCard parts={clarification.parts} onSubmit={(text, contextRefs) => void chat.submitMessage(text, { contextRefs })} … />` directly above `<ProjectComposer` when `clarification !== null && chat.runningTurn === null`. Dismiss state is component-local (a reload reopens the card; acceptable).

- [ ] **Step 4: History rendering** — `chat-message-part.tsx` gains `case "clarification": return <ClarificationHistoryCard part={part} />;` — the document title, each question with its default, and the line `answered in your next message`.

- [ ] **Step 5: Run, lint, commit** — eslint on the four files; `npx tsx --test src/design-system-tokens.test.ts src/features/projects/model/clarification.test.ts`; `npx tsc --noEmit -p tsconfig.json | rg "clarification|chat-message-part|chat-surface"` (expect nothing); `git commit -m "feat(chat-shell): the clarification card — a design document's questions above the composer, answered as one message"`.

---

### Task 6 (controller): stack, records, live proof

- [ ] Restart the platform APIs and the fleet workers via the runbook (bounded with `timeout 40`).
- [ ] Records: `_memory/2026-09-20-design-clarification-cards.md`; CLAUDE.md `[design×legs]` addendum; the web-path guard residual.
- [ ] Owed live proof (founder-triggered): a deliberately under-specified ad brief → the card; answer it → the run designs from the answer; on a batch, one asking document.
