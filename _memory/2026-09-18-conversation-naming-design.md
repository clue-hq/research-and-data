# 2026-09-18 — conversation naming (chat titles + project names): design session

Branch `research-streaming-v3` (trenton lane). Purpose of the branch per the founder: replace
"Untitled project" / "New chat" / the 80-character first-message prefix with generated names, the
way ChatGPT names chats (a separate cheap model call over the opening exchange).

Spec: `docs/superpowers/specs/archive/2026-09-18-conversation-naming-design.md` — awaiting founder review
of the written spec; the implementation plan comes after that.

Rulings taken in discussion: project named after the FIRST AGENT REPLY (not the first message);
chat title at the same moment (one call, both names on the Home path); hook inside the fleet turn
worker (engine turn-close path), no new task kind / SSE event / migration; generate once, manual
rename always wins (conditional `UPDATE … WHERE title IS NULL` / `name='Untitled project'`);
"first completed turn" so existing untitled rows name themselves on their next turn (no backfill);
model env knob default `openai/gpt-5.6-luna`; timeout 60 s ("which LLM responds in 5 s"); switch
defaults on.

Design consequence the founder should confirm at spec review: because the composer unlocks only
on the terminal turn event, the namer must not sit on the critical path — it starts when the reply
is known, the terminal event waits at most a 3 s grace, a slow call finishes detached, and the
frontend adds a bounded catch-up poll (every 5 s, ≤ 60 s) only while a placeholder is visible.

Verified facts that shaped it: `rename_thread`/`rename_project` are granted to no agent role;
`_first_thread_title` is the R0 rule in `chat/router.py`; the bootstrap idempotency check compares
the thread title (must drop that or replays 409 after naming); the ARV2 display's
`LunaSectionRunner` + `ProviderCaller` is the metered one-shot-call precedent; the engine reads the
reply back before `_project_turn_close` emits `turn_finished`.

## Implementation

Implemented on branch `research-streaming-v3` (trenton lane, worktree
`/Users/aryankeshri/conductor/workspaces/research-and-data/trenton`) on 2026-09-18, driven by
`docs/superpowers/plans/2026-09-18-conversation-naming.md` (Tasks 1–10). Base of the feature work
is the plan commit `9ac2208da`. The spec is approved; its status line now records the
implementation.

### Commits (in order)

| Task | Commit | Subject |
| --- | --- | --- |
| 1 | `1f183eb73` | feat(spine): untitled-project sentinel and conditional generated rename |
| 2 | `32d392923` | feat(thread-store): conditional generated thread title |
| 3 | `cfa0b186a` | feat(config): conversation naming settings — enabled, model, timeout |
| 4 | `f8ab306b1` | feat(naming): conversation naming pure half — normaliser, prompt, request types |
| 5 | `a5e9f9898` | feat(naming): OpenRouterConversationNamer — one metered call, conditional writes |
| 6 | `9fb1db42f` | feat(naming): name the chat and project at the end of the first completed turn |
| 6 (fix) | `cfa420b96` | fix(naming): a failed user-message read skips naming instead of failing the turn |
| 7 | `d7f2c3eab` | feat(chat): Home births an untitled thread; replay ignores generated or manual names |
| 8 | `ffb42345d` | feat(frontend): Home bootstrap thread title is nullable |
| 9 | `cccf7a072` | feat(frontend): reload the thread list on terminal turns and poll briefly for late names |
| 10 | this commit | docs: conversation naming — contract §4 rewritten, spec status, session record |

### Verification performed (first-hand, all green unless noted)

Backend focused suites:

- `tests/clue_spine/test_project_naming_db.py` — 2 passed
- `tests/api/test_thread_naming_store_db.py` — 1 passed
- `tests/api/test_conversation_naming.py` — 22 passed
- `tests/api/test_conversation_naming_db.py` — 9 passed
- `tests/api/test_o6_conversation_composition_db.py` — the new namer end-to-end test plus the
  file's existing tests, all passed
- `tests/api/test_lane_d5_gate_read_and_rich_parts_db.py` — 15 passed
- `tests/api/test_home_project_bootstrap_db.py` — 5 passed
- `tests/api/test_project_read_surfaces_db.py` — 4 passed with `CLUE_BRANDFETCH_CLIENT_ID` unset.
  One test in that file is pre-existing and env-driven: it fails whenever that variable IS set.
  Predates this branch; not ours.

Static checks: `ruff` and `mypy` clean on every touched backend module.

Frontend: `project-home.repository.test.ts` (4), `use-naming-catch-up.test.ts` +
`use-project-chat-controller-lock.test.ts` (6) — all passed. `npm run lint` 0 errors (2
pre-existing warnings in `design-editor/engine/scene/canvasOperations.ts`). `npx tsc --noEmit`
reports no errors in the touched files (68 pre-existing errors elsewhere).

**Done after the note was first written:** `npm run build` (exit 0, dev server down) and the
whole-branch review (controller, no Critical/Important findings). **Owed:** the founder-triggered
live acceptance below.

### Decisions taken during execution

- The naming settings/env block sits at the END of the ARV2 group in `settings.py` and
  `.env.example`, keeping the ARV2 group contiguous.
- The engine's grace wait is guarded `if naming_task is not None`, so the D5 tests that call
  `_project_turn_close` with no namer bound stay green.
- The user-message artifact read in the engine is inside its own `try`/`except` with skip reason
  `user_message_unreadable` — a naming input that cannot be read skips naming instead of failing
  the turn. (Found in a fix round; commit `cfa420b96`.)
- `LedgerStamp.job_id` (the turn id) lands in `provider_call_ledger.entity_research_job_id` — the
  existing precedent for non-research jobs, so the cost read attributes the naming call without a
  schema change.
- The frontend catch-up hook writes `tickRef.current` inside an effect, never during render
  (react-hooks/refs).

### Owed live acceptance — founder-triggered, spends money

Spec §6 items 1–8, on the lane stack: bring it up with `./scripts/dev_stack_trenton.sh up` and a
real `CLUE_OPENROUTER_API_KEY`, then:

1. First message from Home → sidebar and header rename after the reply (2–5 words each, neither
   the old 80-character prefix).
2. New chat inside a named project → only the chat title is generated.
3. Manual rename mid-turn survives (log shows `lost_to_manual_rename`).
4. Bad key → turn completes, placeholder stays, `skipped{reason=provider_error}` increments, the
   next completed turn names the chat.
5. A call slower than the grace → terminal event is not delayed; names appear within the poll
   window without navigation.
6. `POST /projects` replayed with the same key after naming → 200, not 409.
7. `CLUE_CONVERSATION_NAMING_ENABLED=false` (workers restarted) → placeholders stay and no
   `provider_call_ledger` row with `label = 'conversation_naming'` appears.
8. `GET /cost/report` attributes the naming rows to the turn's project.

### Docs closed out in this task

- `apps/frontend/docs/api-contracts/projects.md` §4 rewritten from "Deterministic first-thread
  title" (the retired R0 80-code-point rule) to "Generated names (since 2026-09-18)"; §5 gained one
  sentence noting `title` reads `"Untitled project"` until the first completed turn names it.
- The spec status line now reads approved + implemented.
