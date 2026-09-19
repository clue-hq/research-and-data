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
- Spec: `docs/superpowers/specs/2026-09-19-multi-artifact-design-legs-design.md` (for founder
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
