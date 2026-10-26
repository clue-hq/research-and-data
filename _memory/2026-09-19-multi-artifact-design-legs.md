# 2026-09-19 — Multi-artifact design legs (design session; no plan, no code)

Founder asked how the platform can make MANY design artifacts from one message (twenty tagged
accounts → twenty 1:1 ads; "five variants" → five ads), in parallel, each opening its own tab.

## What was verified first-hand (base `21e3ef1e9`, PR #67 merged)
- One turn → one leg → one document by derivation (`design_leg_tools.py`); one open leg per
  thread (`design_leg_one_open_per_thread`, PD-part3 D4); one turn per thread (single-flight);
  a leg turn runs ONE design run inline on the chat slot (`design_fleet.InlineDesignLaneDriver`).
- The exit judge v2 already closes on "two or more accounts" and hands the message to
  Head-of-ABM, which can open only one leg → the other accounts are dropped today.
- The parallel machinery exists below: `design_job` tasks drained by every design-capable slot,
  frozen envelopes, claim CAS + lease-generation fence, reaper re-offer. The design runtime is
  one-scene-per-run and one-session-per-document — the right unit to parallelize, unchanged.
- Frontend auto-open (`artifact-auto-open.ts`) opens the single newest artifact per feed refresh.
- `design_document.account_id` references `design_account` (design plane), joined to the research
  spine via `design_account.account_entity_id`; the artifacts page renders it, the gallery card
  wire does not carry it.

## Approach chosen (founder-approved)
One open leg per thread holding a SET of documents (`open_design_leg@5` takes `artifacts:
[{title, note, account_id?}]` + shared brief); N births + leg insert in one transaction; document
ids derived from (leg, position) with position 0 = today's id; new table `design_leg_document`,
`design_leg.document_id` kept = position 0. Execution: N run rows + N `design_job` tasks, then
`drive_batch` = the inline driver's rule across siblings (drive what nobody holds, wait only on a
live foreign lease); parallelism = free slots, no new knob; progress-based join window; one
hand-back with a per-document summary. Rejected: many legs per thread, fan-out inside the design
agent, one thread per artifact.

## Rulings (founder, 2026-09-19)
1. Shape as above — approved.
2. Follow-up routing by judgement, never mechanical: the EXIT JUDGE (v3) decides which documents a
   message addresses (numbered artifact list in, `addressed_artifacts` + `clarifying_question`
   out); tagged doc / named in words / general = all / qualified subset; when torn it ASKS the user
   and nothing is dispatched. Head-of-ABM is NOT in the loop while a leg is open (corrected the
   founder's assumption). Fail-safe on a multi-doc leg = engine asks, never dispatches N.
3. A born scene ad for a tagged account carries the account (stamp `design_document.account_id`
   via a resolve-or-create `design_account` for the entity) — AMENDS ruling 3 of the 2026-09-19
   account-context note: the id is for the link/gallery, never the design agent's input.
4. No confirmation at any batch size; Stop cancels every non-terminal run of the batch.

## Artifacts
- Spec: `docs/superpowers/specs/archive/2026-09-19-multi-artifact-design-legs-design.md` (for founder
  review before any plan).
- Transcript of the preceding research-branch session attached at
  `.context/attachments/5I4icP/` (untracked).

## Next
Founder reviews the spec → `superpowers:writing-plans` → SDD with Opus implementers. Skill/prompt
text (judge v3, Head-of-ABM v10) is founder-reviewed before landing.

## Plan written (same day)
`docs/superpowers/plans/2026-09-19-multi-artifact-design-legs.md` — 12 tasks: (1) `design_leg_document`
migration + `add_leg_documents`/`list_leg_documents`; (2) `ensure_web_account_for_entity` +
`runs_for_execution`; (3) `open_design_leg@5` (`artifacts: [{title, note, account_id?}]`, N births,
`derive_leg_document_id(leg_id, position)` with position 0 = @4's id, the account stamp, cap
`24_000 + 1_500*(N-1)`); (4) Head-of-ABM v58 / prompt v11 / recipe0-stage0@29 / manual v5 — prompt
text is a founder gate; (5) `render_leg_turn_prompt` renders the item's THIS ARTIFACT lines; (6)
`InlineDesignLaneDriver.drive_batch` (progress-based join window); (7) the runner fans out N runs +
N `design_job` tasks (multi-doc only), `design_leg_run_id(turn_id, position)`, `batch_summary`,
`_finalize_awaiting_input`, Stop over `runs_for_execution`; (8) exit judgment v3 —
`addressed_artifacts` + `clarifying_question`, `decide_exit(artifact_count=)`, multi-doc fail-safe
= ask, golden `addressing-*` fixtures — prompt text is a founder gate; (9) composer tags over the
document set; (10) gallery/library derive from `design_leg_document`, feed wire `account`, close
records `document_versions`; (11) frontend `artifactsToAutoOpen` list + account on the card wire;
(12) records, offline gate with no keys, the six live proofs handed to the founder.
Single-document legs stay byte-identical (one-envelope batches call `drive`, no enqueue).
Execution: SDD, Opus implementers only, Fable reviews each task first-hand.

## Task 8 landed — exit judgment v3 (which documents, or ask)
- `clue_design/exit_judgment.py`: `EXIT_JUDGMENT_PROMPT_VERSION = "v3"`, `DEFAULT_ADDRESS_QUESTION`,
  `ExitJudgment.{addressed_artifacts, clarifying_question}` (strict: ints or the exact string
  `"all"`; `extra="forbid"` unchanged), `ExitDecision.{addressed, ask}`,
  `decide_exit(judgment, *, artifact_count=1)`, and `render_exit_judgment_prompt(artifacts=…)`
  rendering `<<<ARTIFACTS …>>>` (v2's `artifact=` kwarg kept — it becomes the one-item list).
  Close decisions are untouched and never carry an address.
- Decision rule: stay + non-blank question → `ask` (not fail-safe). Stay on one artifact, or
  `"all"` → `addressed=None` (= the whole set). In-range non-empty list → deduped/sorted tuple.
  Anything else on N>1 (absent/malformed/empty/out-of-range) → `fail_safe=True` +
  `ask=DEFAULT_ADDRESS_QUESTION`. N==1 behaves exactly as v2.
- Runner: `_exit_judge_artifact_line` → `_exit_judge_artifact_lines` (numbered, account resolved
  via `design_accounts.get_web_account`; a row with no `document_id` contributes no line, so the
  document-less legacy leg still reaches the prompt's "(unknown …)" fallback);
  `_exit_judge_tag_lines` now takes `leg_documents` and marks a tagged leg document `(artifact N)`;
  `_judge_exit` lost its `pinned_document` param and calls `decide_exit(artifact_count=max(1, N))`.
  `run_leg_turn` returns `_finalize_awaiting_input` with the question (no run rows, no fleet tasks,
  leg stays `open_awaiting_user`, log `design_leg.addressing_asked`) and otherwise narrows
  `addressed`. NOTE: when the address narrows to ONE document the turn takes the shipped
  single-run seam (`lane.drive`, no `design_job` enqueue) — the batch branch is `len(documents) > 1`.
- Judge builder (`agent_turn_fleet_wiring`): `artifacts=` kwarg, in the prompt and the Langfuse
  observation input; output-token floor 400 → 600 (the answer can now carry a question).
- Golden set: kind `"addressing"` + six `addressing-0*.json` fixtures (tagged-one, named-two,
  general-all, judge's own ask, null-judgment fail-safe, out-of-range fail-safe). `_score` now
  compares `addressed` and ask-PRESENCE; `score_judge` stands the canned judgment in for any
  fixture whose expected decision is the fail-safe (not just `kind == "fail_safe"`), so the
  unusable-address negatives stay comparable kind-for-kind. `test_a_judge_that_never_exits…` now
  expects `addressing` in the regressed set — a judge that names no documents on a 3-doc leg makes
  the engine ask instead of dispatching, which IS a v3 regression.
- Gates: ruff check+format, mypy (4 files), `lint-imports` 28/0, and
  `pytest tests/design/test_exit_judgment_golden.py tests/api/test_p37_exit_judge_unit.py
  tests/api/test_p37_exit_bridge_db.py tests/api/test_multi_artifact_leg_engine_db.py
  tests/api/test_p34_design_leg_engine_db.py` → 88 passed.
- Open: the v3 prompt text was written under the founder's approval of the SUBSTANCE (step-1 gate
  reported satisfied by the orchestrator); the exact wording is in the task-8 report for review.

## Execution (same day, SDD on `project-home`, Opus implementers, controller reviews first-hand)
Commits: 4b221beb0 (T1 `design_leg_document`, migration `b9c5e4829868`; `leg_id uuid`) · 03cca44d4 (T2
`ensure_web_account_for_entity`, `runs_for_execution`) · b4121acd1 (T3 `open_design_leg@5`) ·
fdc5fd583 (T4 head-of-abm v58 / prompt v11 / recipe0-stage0@29 / manual v5) · 4e93376cf (T5 THIS
ARTIFACT lines in the brief fence, 0-based position on the wire) · eb48a3473 (T6 `drive_batch`) ·
46641c7a7 (T7 runner fan-out/join/`batch_summary`/batch Stop; also cleared the pre-existing duplicate
import in `design_leg_wiring.py`) · 3c585910a (T8 exit judgment v3, 6 `addressing-*` fixtures) ·
f468cebbe (T9 composer tags over the set) · d2191b259 + 6339c4c3e (T10 set-derived gallery/library,
feed `account`, close `document_versions`; five DAL-opened test seeds given their position-0 row) ·
57f059685 (T11 frontend: `artifactsToAutoOpen`, account on the card wire). Ledger:
`.superpowers/sdd/2026-09-19-multi-artifact-design-legs/progress.md` (git-ignored).

Rulings taken during execution (full text in the ledger): T1 `leg_id` is uuid; T4 the prompt/judge
texts were founder-reviewed via the approved plan/spec and re-surfaced in the final report; T6 stack
down for the lease/task suites; T6→T7 the duplicate-import ruff red fixed in passing; T7 the
`artifact` key is omitted for a one-document leg with no note; T7 per-document waits run before the
one creation transaction; T12 the controller ran the gate itself.

Verified first-hand: every task's diff read; each task's suites re-run; repo-wide ruff/format/mypy
(875 files)/lint-imports (28 kept) green; `.env.example` untouched; frontend `npm test`
(3197 pass) + design-system build + lint + build green. Offline gate (`tests/design` + `tests/api`,
keys unset, stack down, lane DB): 47 reds → A/B on throwaway DBs (head vs base worktree at
af0b68f9b): 45 reproduce on the base and are NOT this branch's (old-lane suites: sumble/fi2/c7
readers/frontend_read live-zafran/lane_d joins/production_context; lane-DB leftovers, e.g.
`agent_gate_answer` count in `test_chat_gate_answers_o6_db`; lane `.env` lacks the three
`CLUE_CONVERSATION_NAMING_*` knobs; `test_projections_app` Settings validation; langfuse/r10/extractor
env-shape tests). Two were ours (stale DAL-opened leg seeds) and are fixed in 6339c4c3e.

Process incident: the Task 1 implementer ran `tests/db/test_db_migrations.py` (destructive
down-to-base) against the LIVE lane DB; Alembic's transactional DDL rolled it back and the DB was
verified intact. Every later brief carried "never run tests/db/test_db_migrations.py".

Deferred minors (ledger): the v58 profile comment claims "@4 stays registered" (false — the tool's
version is edited in place; pre-existing pattern for @2–@4); `manual-siblings@v5` is a verbatim copy;
`lane_lease_held_elsewhere` logs once per poll; foreign lease renewals do not extend the batch
window; a leg without a `design_leg_document` row drops silently from the gallery (a DB invariant
would make it structural); `ensure_web_account_for_entity` has no unique index; a follow-up narrowed
to one document runs inline with no `design_job`; focus lands on the FIRST-born tab; no test drives
the router's set read on a real multi-document leg.

**OWED — founder-triggered, spends money:** the six live proofs of spec §7 (twenty tagged accounts;
five variants; the four follow-up routings incl. a clarifying question; Stop mid-batch; a worker
killed mid-batch; a single-artifact ask byte-identical). Log lines to watch: `design_job.started`
(several worker ids), `design_leg.lane_drive_finished`, `design_leg.exit_judgment` (with
`addressed`), `design_leg.addressing_asked`, `design_leg.waiting_for_document`;
`SELECT run_id, status, document_id FROM design_agent_run WHERE execution_id = '<execution>' ORDER BY created_at`.

## 2026-09-20 — live walk findings and rulings
Live walk on thread `thr_91f106db…`: exit judge v3 closed the Borland leg on the three-account
ask (correct), Head-of-ABM opened ONE leg with three documents (accounts stamped), "go" fanned
out three runs across three processes (inline lane, fleet worker 4, the design API's embedded
worker), all three succeeded — then the chat turn FAILED at the hand-back:
`agent_model_call_sequence` unique violation, because `_record_design_receipts` records each
run's calls numbered from 1 onto ONE turn. Leg left `running`, no summary. FIX OWED (Task 7 code):
offset each run's sequence by the calls already recorded, in position order; then repair the
stuck leg (`open_awaiting_user` + hand-back frame). Founder ordered the engine work FIRST.
Also shipped today: Brandfetch Logo API mark on gallery cards (`4d8d6d710`, `27dfdb730`).

Engine residual surfaced by the walk (freeze-on-grab, ruling C-9): the Stack solve and the Free
solve disagree on `fill` — nested children are built with `parent_size=None` (`layout.rs:313`)
so a cross-axis `fill` on a nested container solves as hug, while Free mode gives `fill` the
parent's FULL outer box (padding included); `baked_container_size` keeps `fill` on containers on
purpose. Result: containers stretch to the artboard edge at the first click. Founder rulings
2026-09-20: **C-9 stands; items 3 (defer freeze to drag threshold) and 4 (freeze scope / telling
the agent) are NOT changed for now; items 1 and 2 are to be fixed thoroughly, covering every
exception** (fill containers, padded parents, nested fill under hug/fill, weighted fill, main-axis
fill fallback, wrapped hug-width text, token dims, locked/absolute/rotated children, convert-of-one,
the real ads as fixtures). All three new ads are now fully Free (6/6, 4/4, 7/7 containers).

## 2026-09-20 (later) — batch receipt collision FIXED, stuck leg REPAIRED
- `0601e837c` — `_dispatch_batch` records every run's receipts at the END, in position order,
  each run offset by the highest sequence already on the turn (`receipts_from_design_run(...,
  sequence_offset=)`, `_record_design_receipts` returns the next offset). A one-run turn records
  from 0 → byte-identical rows; a retry re-joining the same terminal runs recomputes the same
  numbers and converges on the rows already written. Three tests in
  `tests/api/test_design_leg_receipts_db.py` (red on the old wiring; 11/11 green with p32).
- Leg `e1b29465…` repaired by a one-off script (`/tmp/legrepair/repair.py`, not committed): dry
  run showed run 0's 31 rows agree with the recomputed numbering (0 drift); runs 1 and 2 recorded
  as 32..66 and 67..107 (107 receipts on turn `fe8c521b…`); leg `running` → `open_awaiting_user`
  with the `leg.awaiting_user` frame on that turn. The crashed turn itself stays unfinalized
  (no summary was ever written — honest); the next message on the thread works as normal.
- Fleet workers restarted via the runbook (`restart-workers`; its trailing `status` still
  hangs — bounded with `timeout`); 4 processes × 3 slots up, logs clean. The runner is composed
  in `fleet_main` only, so the platform APIs needed no restart.
- Residual CLOSED the same day (founder go): `_contain_crash` now also calls
  `_leg_back_to_awaiting` (suppressed on its own failure; only moves a `running` leg), so a crash
  between `mark_leg_running` and the normal hand-back no longer strands the leg. Test:
  `test_a_crashed_dispatch_hands_the_leg_back_instead_of_leaving_it_running` (red on the old
  containment). Workers restarted again after it.
- Also fixed today on the frontend (`e710e2d88`): a person's own edit no longer re-opens the
  active tab / drops edit mode / reloads the chat (see `2026-09-20-freeze-bake-fill-parity.md`
  addendum 2).

## Addendum 2026-09-21 — versions after the research-streaming merge
The base had its own v58/v11/29/v5 (run_python). Our layer is now head-of-abm **v59** / prompt
**v12** / recipe **30** / manual **v6** (see `_memory/2026-09-20-derived-design-turns.md`, addendum
2026-09-21). The v58/v11/29/v5 named above in this note are the pre-merge lane versions.
