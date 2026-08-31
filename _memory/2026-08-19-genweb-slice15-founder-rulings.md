# 2026-08-19 — genweb slice 1.5: the founder-rulings wave (G1, G2, G4)

Branch `integration/frontend-design-part-iv-v2`, worked directly. Plan:
`docs/superpowers/plans/2026-08-19-chat-driven-website-generation.md` (the "Founder rulings
— G1–G4" block + the Slice 1.5 section). Brief:
`.superpowers/sdd/2026-08-19-chat-driven-website-generation/slice1_5-brief.md`.
Report: `…/slice1_5-report.md`. G3 was registration-only — no code.

Commits (local only, never pushed):

- `55982a32` — `feat(genweb): leg turns refuse finalized documents and freeze the account card (G1, G2)`
- `a50e81f0` — `perf(design): web review loop capped at 6 with minimum-turns prompting (G4)`

## What changed

- **`clue_design.documents.is_finalized_document`** — the platform-side mirror of the design
  API's predicate (`lumen_api/main.py:6594`): row `status == "finalized"` OR a finalized scene
  status. `published` is NOT finalized, and that is load-bearing (founder G1: a draft with an
  older published version stays editable). Publishing in fact writes `design_web_publish` and
  never touches `design_document.status`, so a published web doc's row still reads `draft`.
- **`DesignLegTurnRunner.run_leg_turn` gained two pre-dispatch gates** (both after the exit
  judgment, before `_dispatch`):
  - G1 — a finalized pinned document fails the turn with `design_leg_document_finalized`.
    Placed after the judge deliberately: closing a leg is not a mutation, so "lock it in"
    still works on a finalized document.
  - G2 — a **web** pinned document carrying `account_id` resolves the account in the SAME
    workspace (`clue_design.accounts.get_web_account`, which is workspace-scoped, so a foreign
    account reads as absent) and freezes the card by value into `config["account_card"]`, key
    for key with the design route (`name, domain, logo_asset_id, data, notes`). Unresolvable →
    `design_leg_account_unresolved`, never a silent generic page. No account stamp → no
    `account_card` key at all (byte-identical slice-1 envelope).
  - Both refusals reuse the new `_fail_turn` helper, which the failed-design-run branch now
    also uses, so the three non-crash failures cannot drift.
- **Design runtime `WebReviewDelegationCap`** (`lumen_agent/harness_web.py`) — tool-call
  middleware on the orchestrator counting `lumen-web-reviewer` delegations; the 7th gets an
  honest `ToolMessage` refusal telling the director to finalize with its standing critique.
  Never raises. One integer on a per-turn instance (a fresh `create_web_deepagent` = a fresh
  budget, which matches the runtime's resume-as-restart checkpoint semantics).
- **`prompts_web.py`** — minimum-turns pressure up front (ONE author pass + 1–2 review rounds
  for a simple landing page), the hard cap stated (passed in as `review_cap`, so the prompt
  cannot promise a number the runtime does not enforce), no review round for a cosmetic-only
  fix, advisories go to the finalize summary; reviewer prompt taught the same boundary. The
  old "no fixed number of rounds" line was removed — it is no longer true. Scene prompts
  untouched.

## Facts worth keeping

- **`design_document.status` is free text derived from the scene** (`scene_status`), and web
  writes never touch it. Publish → `design_web_publish` rows. So "published but editable" is
  the normal state, not an exotic one.
- **`design_document_account_fk` is `ON DELETE SET NULL (account_id)`**, so an unresolvable
  account stamp is structurally near-unreachable in production; the G2 refusal is a
  fail-closed backstop. Its test reaches the state by dropping the constraint inside the
  rolled-back transaction.
- **The design `task` tool is `name="task"` with `args.subagent_type`** — that is the whole
  interception surface for a per-subagent cap. Only the orchestrator has `task`, so
  orchestrator-side middleware is sufficient.
- **`create_deep_agent(middleware=[…])` appends user middleware after `SubAgentMiddleware`**,
  and langchain composes `wrap_tool_call` around the ToolNode, so the cap wraps `task`
  execution. Sync only: the web turn runs `agent.invoke`; an async invocation would raise
  LangChain's own "sync implementation only" error rather than skipping the cap silently.
- **The istanbul stack from slice 1 was gone** (only the tunis worker `clue_d5_live` and a
  missoula worker remained, both on OTHER databases — no double-claim risk with the istanbul
  dev DB on `localhost:55040/clue`). Relaunched only a fleet worker:
  `/tmp/slice15_fleet_worker.sh` (root `.env` + `CLUE_DESIGN_RUNTIME_ENABLED=1`,
  `OPENROUTER_API_KEY`/`LUMEN_AGENT_API_KEY` from `CLUE_OPENROUTER_API_KEY`,
  `LUMEN_AGENT_BASE_URL`, `LUMEN_AGENT_MODEL`, `LUMEN_CORE_HELPER`).
  **New trap:** `CLUE_AGENT_WORKSPACE_ROOT` must be `/private/tmp/...` on macOS —
  `/tmp/...` is a symlink and the workspace policy refuses "paths that traverse links".
- `agent_turn` has no status column: turn outcomes live in `agent_turn_event(status,
  reason_code, seq)`. `design_agent_run` stores its result in `result_json`, and
  `design_leg` has no `opened_at` (use `created_at`).

## Live verification (dev data, left in place)

Thread `thr_genweb_slice1_g1`, leg `4092181d-d588-4f68-be51-4cc35a7a3b2f`, document
`doc_feb8f81a6d2642ec82224b6d1610a49c`.

1. Document SQL-marked `finalized` → turn `8c8de1b1…`: `requested → running → failed
   (design_leg_document_finalized)` in **34 ms**, **0** `design_agent_run` rows, thread holds
   the user message only, leg still `open_awaiting_user`. G1 proven live.
2. Document reverted to `draft` → turn `f4620eeb…` on the same leg dispatched
   `run_9c01494c01a05371a2068d73ecab9075` (`kind=web_turn`, request
   `{"prompt": …, "base_version": 2}`, **no `account_card` key** — the doc carries no account),
   ran to `applied/accepted`, document **v2 → v3**, assistant message on the thread.
   **Zero reviewer delegations** and ~3m28s wall (08:34:16 → 08:37:44 UTC) — the new prompt's
   "a cosmetic-only fix is not re-reviewed" behaviour, though this was a small scoped edit and
   is NOT a controlled comparison against slice 1's ~13 min. The cap's refusal branch was
   never reached live; the unit test covers it.
   No account-stamped design account exists in the dev data, so the G2 card freeze has DB-test
   proof only.

## Open items / concerns

- **Retry window:** the gates run before `_dispatch`'s terminal-run re-join, so a crash-retry
  of a turn whose design run already succeeded would refuse if the document was finalized in
  between (the applied version stays, but the turn reports failed and writes no summary).
  Requires a human finalize inside a crash window; recorded, not fixed.
- **The G1 refusal has no user-visible sentence.** Like every other failed leg turn, it lands
  a typed failure code and no assistant message. Whether the chat surface should say "this
  page is finalized — make a new revision" is a slice-3 UX question.
- `subsystems/clue-design/apps/api/tests` is slow/hangs in this environment (killed one run
  after ~25 min at 45 s CPU); `apps/api/tests/test_web_turns.py` alone is 21/21 green and the
  whole `apps/agent_runtime/tests` suite is green.
