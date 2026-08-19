# G9 wave — leg-brief injection into web turns + the author-delegation cap

Date: 2026-08-19. Branch `integration/frontend-design-part-iv-v2` (worked directly).
Founder-ordered backend wave between G6 and slice 4. Brief:
`.superpowers/sdd/2026-08-19-chat-driven-website-generation/g9-wave-brief.md`.

## Part 1 — G9: a leg-dispatched web turn now carries its brief and history

**Defect (found by the G6 trace analysis).** `execute_web_turn_job`
(`subsystems/clue-design/apps/api/lumen_api/main.py`) consumed only
`envelope.config["request"]` (+ `account_card`). The leg envelope has carried
`config.delegation_bundle` (the §2.3 bundle whose `brief` is the delegation's actual
charter), `config.history` (the leg's prior conversation) and `config.leg` since slice 1,
and the SCENE executor has composed the first two into its prompt since P3.7 — the web
executor dropped them. So a chat-born generation ran on the raw text of the user's latest
message alone: a bare "go ahead" second message generated from almost nothing, and every
iteration turn lost the standing brief.

**Fix (commit `96fe927a`).** The web executor applies the SAME
`clue_design.leg_context.render_leg_turn_prompt` the scene executor does, with the same
block order (brief fence, history oldest-first, user message last — the prefix-stable
order that keeps the reassembled session cacheable). No new mechanism, no envelope change:
the config already carried everything.

Decisions taken inside the fix:
- **`intent` stays the user's words.** The durable edit envelope's `intent` (the
  human-facing checkpoint label) was `prompt[:120]`; with composition that would have
  become "DELEGATION BRIEF (from the strategy conversation…". It now reads
  `user_message[:120]`. Pinned by a test.
- **No cap / truncation.** The scene path has none, so this takes none (brief per the
  wave brief: mirror the scene path, do not invent a policy). The bundle is capped at 24KB
  upstream; history is the leg's own textual turns.
- **Untouched:** the scene executor, the CAS re-check (still before the runtime — a
  conflicted turn never reaches the runner), the failure diagnostics, and the P3.7c brand
  pin. Note the web executor never read `config.leg` at all (web documents are themed by
  the kit stamped at document birth), so there was nothing to disturb there.

**Tests** (`subsystems/clue-design/apps/api/tests/test_web_turns.py`, 4 new, driving the
REAL `execute_web_turn_job` with a capturing runner + the embedded worker's host):
brief/history/message present and in order for a leg-shaped envelope; a route-shaped
envelope's prompt is the raw prompt byte-for-byte; a stale-base-version leg turn still
conflicts before the runner; an applied leg turn's persisted envelope `intent` is the
user's message.

## Part 2 — the author-delegation cap (G6 next-lever ruling)

`WebReviewDelegationCap` generalized into **`WebDelegationCap`** (commit `d37b5792`): ONE
middleware instance per turn holding a frozen `WEB_DELEGATION_BUDGETS` tuple — author 4
(`WEB_AUTHOR_DELEGATION_CAP`, new), reviewer 6 (`WEB_REVIEW_DELEGATION_CAP`, unchanged) —
with independent per-subagent counters. Still a dict of integers and one branch; still a
tool-level ToolMessage REFUSAL rather than an exception; still turn-scoped by construction
(fresh instance per `create_web_deepagent`).

Prompt teaching (`prompts_web.py`, orchestrator only — reviewer untouched): "PLAN THE
WHOLE PAGE INTO ONE AUTHOR BRIEF" (every section/copy angle/image/CTA in the FIRST
delegation), both budget numbers interpolated from the harness constants (`author_cap` is
now a required kwarg beside `review_cap`, so the prompt cannot promise a number the
runtime does not enforce), and the view-discipline line: view each render's three widths
once, never re-view unchanged pixels.

**Deviation from the wave brief, deliberate and flagged.** The brief's refusal wording
said the orchestrator "holds `design_apply_web_operations` for scoped fixes". It does not:
the web orchestrator's tool list is view / fetch_page / search_assets / provenance /
list+inspect custom components / render_web_preview / finalize_web_run — no editing tool
at all (`design_apply_web_operations` is the platform-governed write the EXECUTOR makes
when it persists the turn, not an agent tool). `harness_web.py` itself records the
2026-07-29 live failure where a refusal naming an uncallable tool sent a role into blind
edit churn, so the author refusal names only what the orchestrator can actually call:
render if the last change is not on screen, judge with its own `view` calls, then
`finalize_web_run` (`completed_with_warnings` naming every fix it could not make). A test
asserts the refusal mentions none of `web_ops` / `author_web_page` / `author_web_subtree`
/ `patch_web_page`. If the founder wants the director to hold an edit tool, that is a
separate one-line change to `orchestrator_tools` plus prompt teaching — not assumed here.

**Tests** (`apps/agent_runtime/tests/test_web_review_cap.py`, rewritten to cover both
budgets, 10 tests): 6 reviewer / 7th refused (all original G4 assertions kept); 4 author /
5th refused; the refusal names no uncallable tool; the two budgets are independent;
ordinary tools and unknown subagents pass through; per-turn scoping; the harness installs
exactly one cap with both counters fresh; prompt asserts both cap numbers, both subagent
names, "one author brief", "never re-view".

## Verification

No live generation (founder ruling: slice 4's walk is the live proof, and it follows).
Run WITHOUT the platform root `.env` sourced, from `subsystems/clue-design` with
`PYTHONPATH=.:apps/api:apps/agent_runtime` and the repo-root `.venv`:
- `pytest apps/agent_runtime/tests` → 578 passed, 2 skipped.
- `pytest apps/api/tests/test_web_turns.py` → 26 passed (22 pre-existing + 4 new).
- Full `pytest apps/api/tests` is NOT a gate here: already red (the 16 standing reds
  recorded in `_memory/2026-08-19-genweb-g7-tailwind-runtime.md` — missing
  `apps/custom-component-compiler/node_modules` → compile 503) and it runs at ~1 test/s
  in this checkout (>1h). The touched surface is entirely inside `execute_web_turn_job`,
  which `test_web_turns.py` covers end to end including the real governed persist.

## Follow-ups / notes

- The web harness's `brief.md` scaffold and the `web_turn_started` trace summary now
  carry the COMPOSED prompt for leg turns (they take the same string the runtime does).
  That is the honest artifact — the workspace brief is now the delegation brief — but it
  means trace `input_summary` for a leg turn opens with the fence, not the user's message.
- Nothing in the platform (`platform/`, `subsystems/design/`) changed; the envelope
  contract was already sufficient.
