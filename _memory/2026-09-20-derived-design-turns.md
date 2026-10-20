# 2026-09-20 — Derived design turns: no repeated message, no "go" (SDD on `project-home`)

Spec `docs/superpowers/specs/archive/2026-09-20-derived-design-turns-design.md`; plan
`docs/superpowers/plans/2026-09-20-derived-design-turns.md`; ledger
`.superpowers/sdd/2026-09-20-derived-design-turns/progress.md`. Opus implementers, every review
the controller's own.

## What shipped (commits after 7a2f7d3a3)
- `cc266d888` T1 — migration `c937a6b69e8a`: `agent_turn_submission.derivation` (text, CHECK in
  {design_leg_redelivery, design_leg_first_turn}) + `derived_from_turn_id` (uuid), both-or-neither;
  `AgentTurnSubmissionRow` + `insert_submission(derivation=, derived_from_turn_id=)`; the leg's
  out-of-scope redelivery stamps itself.
- T2 REMOVED by ruling (see below).
- `e20ebfc69` T3 — the turn list (`GET …/turns`) carries `derivation`; the transcript composer
  renders NO user bubble for a derived turn (durable row, submission_message or optimistic);
  notices: "Design session opened — generating now." / "…reopened — generating now."
- `caa894aee` T4 — `open_design_leg` queues the leg's FIRST design turn in the opening (or
  reopening) transaction: a derived submission of the opening turn's own message, key
  `design-leg-first-turn:<leg_id>:<opening turn_id>`, context refs copied, `dispatch_next_thread_turn`
  offered; a turn with no submission queues nothing (`design_leg.first_turn_skipped_no_submission`).
  Tool references/output model unchanged (ruling: the profile pins the output schema digest).
- `a910b7049` T5 — the leg runner skips the exit judge for a `design_leg_first_turn` submission and
  addresses every document (`design_leg.first_turn`).
- `e16f32201` T6 — prompt head-of-abm v12 (one sentence: generation starts at once), profile v59
  (v58 + prompt pin + manual pins), manual re-minted at `manual-*@v6` (chapters carry the profile
  version in their title), registry default + `PROJECT_CONVERSATION_AGENT_PROFILE_ID` → v59.

## Rulings (controller, 2026-09-20)
1. **Derived turns KEEP their user row.** T2's first cut dropped it; `load_head_of_abm_history`
   filters by turn role and the leg loader by leg, so the derived turn's row is the only copy of the
   question each role's later history (and the exit judge) can see. Reset to T1, hidden at the
   display only.
2. **No `first_turn_id` reference** on `open_design_leg` — `OpenDesignLegOutput` is the tool's
   output_model and the profile pins its schema digest; a new reference forces `@6` + recipe 30 +
   a manual re-mint. Logged instead.
3. **Manual re-mints at v6** on a profile bump (the v57 precedent) — the plan's "stays at v5" was
   the controller's error.

## Verified first-hand
Every task's diff read; tests re-run by the controller per task (T1 21, T3 102 fe + 5 be, T4 14 +
24 neighbouring, T5 26, T6 40 catalog/pin); full frontend `npm test` at the end (see ledger);
migration applied/downgraded/re-applied on the lane DB (head `c937a6b69e8a`); platform APIs +
fleet workers restarted on the finished branch, all UP, logs clean.

## Owed — founder-triggered live proof
One ask for two tagged accounts → the transcript shows the ask ONCE, the notice "Design session
opened — generating now.", two runs start with no further message, the per-document summary lands;
a later out-of-scope message closes the leg and shows once (Head-of-ABM's answer follows the
closing summary).

## Residuals / deferred minors
- Other lanes on this machine need `alembic upgrade head` (c937a6b69e8a) before running this branch.
- A reopen-path first-turn assertion (the reopen path is exercised by test_p35's reopen test but
  the derived submission is not asserted there).
- The manual chapter titles carry the profile version, so EVERY head-of-abm mint re-mints fifteen
  chapters (~3,600 lines for two header lines here); drop the version from the title at the next
  substantive bump.
- Attachments never ride a derived turn (redelivery precedent; leg turns carry no attachment_refs).
- Points 3 and 4 of the 2026-09-20 discussion (per-document clarification questions; routing a
  reply to the asking document) — next spec, after the founder's go.

## Addendum 2026-09-21 — merged with research-streaming; catalog re-minted
`research-streaming` had minted its OWN head-of-abm v58 / prompt v11 / recipe 29 / manual v5 for
`run_python@1` + the attachments folder. Merge `a5a91155b` kept the base's versions verbatim and
our two layers were re-minted on top (`bbd29f954`, `5b9037d43`): **v59** = base v58 +
`open_design_leg@5` + prompt **v12** (the multi-artifact paragraph) + recipe **30** + manual **v6**;
**v60** = v59 + prompt **v13** (generation starts at once) + manual **v7**. Active pins: v60 / 30 /
v7. Two alembic heads (`5358a2422cb2` from the base, `fc9580642b71` ours) joined by `5cac3234cfb3`
(`ac9c9e2e8`). Verified after the merge: 263 backend tests across the design-leg/turn/stream/feed
suites, frontend 3236/3237, catalog + pin suites. The lane `.env` gained the base's 16 new keys
at example defaults (attachments, conversation naming, sandbox).
