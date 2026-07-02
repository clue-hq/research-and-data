# Increment 0b — continuation mode: what shipped and why

Date: 2026-07-03. Branch: `agents/editing-roundtrip-v0`. Scope: the 4 items from
`FINDINGS.md` ("Decision for 0b"). All changes are seeded-gated: unseeded runs
(design generation from scratch, the eval harness) behave exactly as before.

## Item 1 — fresh authoring is unavailable on a seeded run (guarantee)

- `loop.py`: `SEEDED_FORBIDDEN_ACTION_MODES = {new_artifact, full_page_rewrite,
  replace_artboard_subtree}`. Right after `director.decide(...)`, a seeded run
  coerces those to `targeted_patch`, prepends a why-note to the author
  instructions, and records `seeded_mode_coerced`. The 0a e2e showed the
  director already *tends* to choose targeted_patch; this makes it a contract.
- `tools.py`: `start_fresh_rewrite_scene` REFUSES on a seeded scene (records
  `seeded_scene_wipe_blocked`, leaves the scene untouched) — belt-and-suspenders
  for any caller that bypasses the loop. A successful structural rewrite would
  otherwise replace the user's document wholesale (0a finding).
- Director steering (soft layer above the hard guarantee): `curated_context`
  now carries `seeded_from_initial_scene`; the director system prompt
  (providers.py) explains continuation turns and that out-of-scope quality
  complaints are advisory.

## Item 2 — author recipe + deterministic re-author reroute

- `prompts.py`: `SEEDED_CONTINUATION_RECIPE` — injected into EVERY seeded-turn
  author instruction (same mechanism as the poster/imagery recipes, deduped by
  substring). Front-loads exactly what 0a showed the author gets wrong:
  modify-line properties are parenthesized CALLS (`#headline text("…")`, not
  `#headline text "…"` → the LUMD0210 that burned iteration 1 in BOTH e2e
  runs), never re-declare existing ids/pages, fresh ids for new content,
  structural changes via replace()/clone()/parent().
- Author system prompt gains the same grammar rule permanently (the existing
  element-line example actively misled modify lines).
- `loop.py` guardrail (never rely on the model behaving): `reauthor_correction`
  keys off `halted_at.code` ∈ {LUMD0401, LUMA0200} — the one place the code
  survives the known diagnostics_from mangling — regexes the offending id out
  of the diagnostic text, and reroutes the failure as corrective feedback:
  for a node it forces `surgical_repair` + `surgical_target` + structured_ops
  (so `is_surgical_dsl` mechanically rejects a repeat re-author), prepends the
  imperative instruction to the authoring constraints, stores
  `reauthor_correction` in the repair context, records `reauthor_rerouted`.

## Item 3 — edit-scoped acceptance + return contract

The 0a lesson: `agent_response_from_trace` stripped ops unless the run was
`accepted`, and the reviewer judges the WHOLE artifact — so a perfect targeted
edit on an imperfect human document could return `failed` with zero ops (run 1),
rescued only by director judgment (run 2). Now it's a contract:

- The loop tracks the run's edit scope from APPLIED core operations
  (`_track_edited_ids`: update/insert/remove node ids, add/update page ids),
  plus current DESCENDANTS of edited nodes (`_edited_scope_node_ids`) — an edit
  to a container owns critique on what it contains; ancestors/siblings stay out
  of scope (ancestor inclusion would let any pre-existing page complaint block
  every edit).
- After a rejected critique on a seeded turn (compile + preflight already
  clean at that point), if NO issue targets the edit scope
  (`issue_in_edit_scope`): finalize immediately as status `edit_applied`,
  stop_reason `edit_scoped_acceptance` (new enum member), critique attached,
  `ops_valid_through_iteration` = current iteration. Issues that DO target the
  scope block and repair exactly as before.
- Budget exhaustion on a seeded run with a preflight-clean best draft and a
  non-empty edit scope → `edit_applied` + stop_reason max_iterations_reached
  (run 1's failure mode, fixed deterministically).
- **Ops-window correctness** (new-found flaw, fixed): the keep-best snapshot
  can restore an EARLIER iteration's scene while the response used to
  concatenate ops from ALL ok iterations — a replay/draft mismatch.
  `finalize_run` now records `ops_valid_through_iteration` (the best/live
  iteration) and `agent_response_from_trace` collects ops only from iteration
  dirs within the window (`iteration_in_ops_window`); later DSL blocks stay as
  informational history.
- `main.py` maps `edit_applied` → `"proposed"` (the editor applies ops
  unchanged), adds `acceptance_scope: "edit" | "design"`, and surfaces the
  attached critique as ADVISORY `warning` diagnostics
  (`agent_runtime.visual_critique_advisory`, never error) with node/page
  subjects — this is what makes 0c's Accept/Reject gate meaningful.

## Item 4 — regression fixtures

`apps/agent_runtime/tests/test_seeded_continuation.py` (13 tests):

- REAL engine (actual Rust helper, no fakes): seeded `#headline font(...)` and
  `#cta fill(...)` modifies leave every untouched node **byte-identical**
  (probe 1 pinned); a mixed block re-authoring an existing id halts LUMD0401
  with the ENTIRE scene byte-identical — atomic rejection, no partial leak
  (probe 2 pinned).
- Loop-level (FakeCoreClient): new_artifact coercion + recipe injection;
  unseeded runs untouched; scripted full_page_rewrite never wipes; direct
  `start_fresh_rewrite_scene` refusal; LUMD0401 reroute end-to-end into the
  next author request; `reauthor_correction` parsing (both codes, mangled and
  flat shapes); edit-scoped acceptance fires on out-of-scope critique in one
  iteration; in-scope critique still blocks/repairs and returns `edit_applied`
  at budget with the ops window pointing at the kept (earlier) draft;
  descendant scope; `issue_in_edit_scope` rules.

Plus 2 response-contract tests in `apps/api/tests/test_api.py` (edit_applied →
proposed with advisory diagnostics; ops-window truncation).

Suite totals: 188 passed, 1 skipped (was 173).

## Notes / deferred

- `diagnostics_from` mangling itself left as-is (0a finding); the guardrail
  deliberately keys off `halted_at.code`. Unwrapping the session shape is a
  small, separate cleanup.
- `eval_traces.py` counts only `accepted` — unaffected (evals are unseeded).
- PNG↔SVG fit disparity is unchanged by 0b (tracked separately in FINDINGS).
- E2E validation: see E2E-RESULT.json / e2e-trace-0b/ (run 3).

## E2E validation (real LLM, same GTM seed + targeted headline edit)

**Run 3** (`e2e-trace-0b/`, before the severity refinement):
- Iteration 1 emitted CORRECT modify grammar (`#headline text("…")`) — the
  recipe eliminated the LUMD0210 burn that cost iteration 1 in both 0a runs.
  One DSL block total, zero diagnostics.
- The critic rejected with errors on `hero`/`canvas` (out-of-scope) plus a
  WARNING on the edited `headline` ("could dominate more" — pre-existing;
  the turn only changed text). In-scope-by-id blocked → the director resolved
  it on the next round (`accepted`, scope-aware rationale). Right outcome,
  one needless LLM round → refinement: in-scope issues block only at
  error/blocker severity.

**Run 4** (`e2e-trace-0b-final/`, with the refinement) — the exit criterion:
- Event stream: seeded → targeted_patch → correct-grammar block → 1 op →
  preflight clean → previews → critique rejected (whole-design) →
  **edit_scoped_acceptance** → finalized. ONE iteration, no director round
  needed to resolve scope.
- Response: `status: "proposed"`, `acceptance_scope: "edit"`,
  `stop_reason: "edit_scoped_acceptance"`, 1 update_node op, all 6 node ids +
  page preserved, and 5 advisory `agent_runtime.visual_critique_advisory`
  warnings with node subjects + actionable hints (placeholder hero, dead
  bands, margins) — the exact payload 0c's Accept/Reject gate will render.
