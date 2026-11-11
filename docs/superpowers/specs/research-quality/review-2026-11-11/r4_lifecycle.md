# R4: run lifecycle review, trial/research-quality (dd9a7d74a..HEAD)

Scope: account_research_driver (review then pages, no-progress cap, crash final step), quality_review, quality_generation (stall, review waits), quality_committee_tool (cap bypass, roles), page_writer*, the review-turn wiring in quality_research_wiring, job_resume, quality_markdown_dossier, the display diffs, and the trial harness.
Method: I read the code. The only test I ran was `uv run pytest tests/arv2/test_page_writer.py -q` (offline), which passed (24). I ran no DB tests. Each finding below was traced through the code paths cited.

---

## F1. IMPORTANT: recipe 44 is now the production default, but its review brief is dropped unless the env selects guide v3 or v4

- `platform/api/clue_api/arv2/quality_catalog.py:14`: `CURRENT_RECIPE_VERSION = 44`, so every new launch gets recipe 40+ behaviour (review turn, deferred pages).
- `page_writer.py:108` `uses_page_brief()` is true only for `v3` and `v4`. `page_writer_runtime.py:567` passes the brief to the writer only then.
- The guide version is a global env setting that is not tied to the job's recipe. `settings.py:704` defaults to `"v2"`, and `.env.example:373` says `v2`. The local `.env` says `v3`, which also breaks the env parity rule: the `.env` value should win and the example should say the same.
- **Failure:** a production deployment that merges this branch with the documented default (v2) works like this:
  - every account pays for a full review turn whose only required output is `/outputs/page-brief.md`;
  - the page writer never sees that brief;
  - the `needs_review = not brief_written` logic still runs on a brief nobody reads.
  - Nothing checks this at startup or at launch. The recipe-to-guide coupling exists only in people's heads. This is the same class of problem as the v4 seller-brief crash, but silent.
- **Fix direction:** pin the guide version with the job's recipe (e.g. in input_refs at launch), or refuse to start or launch when a recipe of 40 or more meets a guide of v2 or lower.
- Confidence: high.

## F2. IMPORTANT: the review turn's completion guard skips the dossier handoff check, so an open dossier revision wipes out the account pages

- `quality_research_wiring.py:1349-1358`: when `self.review is not None`, the guard checks only that `outputs/page-brief.md` is not empty and then returns. It returns before the `uses_json_dossier` / `validate_dossier_handoff` branch that every other completed turn goes through.
- The review runs with the full account profile (v42 grants `begin_dossier_revision`, `update_dossier_findings`, `finish_dossier`).
  - The v42 SYSTEM prompt (lines 156-173) tells a continuation to `begin_dossier_revision ... then finish_dossier` when facts change.
  - account-review v2 tells it to act on "someone has left the company".
- `read_json_dossier` returns the newest reference, draft included (`quality_json_dossier.py:62-71`). `_final_page_step` (`page_writer_runtime.py` ~964) then sets `imported = own.get("state") == "complete"`, which is False, so it skips the account pages and settles the generation `needs_review`.
- **Failure:** under recipe 40, account pages are only ever written at this step (`_write_pages` defers `insights` and `overview`). Here is how it plays out:
  - The review starts a revision, finishing it fails validation (or the agent stops), and the agent finalizes with a brief.
  - The account ends with **no account pages at all**.
  - The generation lands `needs_review` with no recovery path (see F3).
- Confidence: high on the code path; medium on how often the agent does this.

## F3. IMPORTANT: a failed page step leaves a dead end that no automatic path and no runbook can re-run (the root behind the trial's stuck generation)

- `account_research_driver.py:1056-1073` (`_rewrite_account`): any exception calls `reconcile_generation(..., processed_snapshot=True, needs_review=True)` and then returns `WorkResult(outcome="failed")` with **no requeue**. This includes transient provider or timeout errors in the page writer models, a lost storage read, and the trial's missing guide file.
  - `reconciled_revision` is now R.
  - The fleet dedup key `arv2:quality-editorial:{gen}:{R}` is terminal.
  - The sweep only offers when `input_revision > reconciled_revision`.
- The recipe-40 initial account job settled `completed` before the review, so:
  - `list_stuck_jobs` never lists it (`job_resume.py:304`, `status IN ('needs_review','suspended','in_progress')`);
  - `resume_research_job` refuses it as `job_completed` (`job_resume.py:252`).
- The generation moves again only if an unrelated signal arrives (a person result or a claim change).
- **Failure:** a transient model or network error while writing pages permanently leaves the account without pages and throws away the review that was just paid for. There is no operator command to re-run "pages for revision R". The CLAUDE.md runbook only covers jobs.
- Confidence: high. This is distinct from the FileNotFoundError itself: any page-step exception lands here.

## F4. IMPORTANT: a person parked by a deploy or lease loss counts as "will never settle", so the paid review and pages run without them, and then run again

- `quality_generation.py:467`: the final-step CASE treats `child.status='suspended'` as not blocking.
- `_suspend` (`account_research_driver.py`, CancelledError path) and `account_research_store.suspend_job:393-407` use `'suspended'` for a **transient** park on lease loss or a stop request.
- The clause is older (recipe 26), but under recipe 40 the consequence is now a full agent review turn plus the pages. The new stall clause's own comment ("one not started is never skipped") shows the intended semantics: wait for anyone who will still run.
- **Failure:**
  1. A deploy parks person A while person B settles. The signal from B makes the generation pending.
  2. The review runs without A's findings and pages are written.
  3. A is reclaimed and settles, which brings a new revision, a second review and the pages again.
  4. The first brief can call A's seat a gap.
- Confidence: high on the logic.

## F5. MINOR/IMPORTANT: the "verdict summary" fallback and "never continue from a failed review" claims are false, so stale or failed briefs reach the pages

- `account_research_driver.py:911-915` says that after the last attempt "the pages are written from the verdict summary". But `page_brief()` (`page_writer_runtime.py:497-518`) returns the newest brief from **any** account-research execution of the job. It falls back to the summary only when none exists.
- `latest_review_before()` (`:477-495`) says "the runtime refuses to finish a review without it, so a failed review is never continued from". In fact a failed or stopped turn still saves its snapshot (`clue_agents/workspace.py:2178` `release_saved` saves best-effort when the turn did not finalize). The completion guard runs only on a COMPLETED finalization.
- **Failures:**
  - (a) A review at revision R+1 fails 3 times. The pages (flagged needs_review) are written from revision R's brief, which predates the new people's results. It can say a seat is empty that is now filled, or name someone who has left.
  - (b) A review that wrote a brief and then ran out of budget or ended itself `failed` becomes the conversation the `:retry-1` review continues from. Its unvalidated brief is also used for pages.
- No test covers a failing review that left a brief: `test_review_failure_retries_then_falls_back`'s fake runner raises before saving anything.
- Confidence: high.

## F6. MINOR: reviews break permanently across an instruction change and after a restart-fresh

- (a) The review execution goes through `_refuse_changed_instructions` (`quality_research_wiring.py:1052,1075`), which raises `ResearchRestartRequired("instructions_changed")` when a redelivered review's recorded recipe or profile differs. `_review_then_pages` catches it as a plain `Exception`.
  - It retries the **same** unit key (`review_unit_key` only advances on a *finalized* non-completed turn, `quality_review.py:93`).
  - It raises identically three times, then writes the pages `needs_review`. Only `_run` knows how to restart.
- (b) `latest_review_before` ignores `restart_count`, and review unit ids ignore it too (`job_resume.research_execution_id` with a unit key). After an operator `--restart-fresh`, the next review continues from the newest **pre-restart** review conversation, which is exactly the conversation the restart was meant to abandon.
- Confidence: medium.

## F7. MINOR: claims the review writes trigger another review round

- `signal_subject_change` (`quality_generation.py`) exempts only `account.value_narrative`. When a review imports a dossier revision (`finish_dossier`) or writes other account claims, each assessment emits a `claim_quality_event`. The sweep turns that into a `claim_changed` revision, so after the pages, revision R+1 is pending and a second full review runs.
- This is bounded (the second review usually changes nothing), but the paid review is doubled whenever the first one edits. `test_one_review_with_no_new_input_causes_no_other` does not cover it.
- Confidence: medium-high.

## F8. MINOR: an exception in `_final_step_after_crash` rolls back the containment itself

- `account_research_driver.py:1253-1278`: `_final_step_after_crash` runs inside `_contain`'s `async with self._connection()` transaction.
  - Any exception there (for example a lock timeout or deadlock on `read_generation(lock=True)` FOR NO KEY UPDATE) rolls back the `finish_job(... needs_review)` too.
  - The broad `except` then returns `"needs_review"`, so the fleet closes the task.
- The job stays `in_progress` with no queued task. The stuck script lists it as stalled, so it is recoverable by hand, but the containment is reported as done when it is not.
- Fix: run it in its own transaction after the landing.
- Confidence: medium (it needs an error in the signal).

## F9. MINOR: off-by-one in the no-progress cap, and bookkeeping in input_refs

- `account_research_driver.py:1395-1399` together with `quality_generation.no_progress_attempts`: the claim that brings the count to `arv2_job_max_attempts_no_progress` (3) is never executed. So 2 executions run, while the message says "Stopped after 3 attempts in a row without progress".
- The counter is written into `arv2_research_job.input_refs` (launch input) on every recipe-40 claim. Nothing hashes input_refs today (checked: the store and launch do no fingerprint compare, and the turn input does not include it), so this is a smell, not a bug.

## F10. MINOR: `brief_of_execution` reads snapshot blobs around the snapshot store

- `page_writer_runtime.py:456-474`: it reads the manifest and file with raw `storage.get`, skipping all of these:
  - the hash and size verification;
  - the `expired_at` check;
  - the Phase-1 bare-key fallback (`SnapshotStore.read_file` / `_read_verified`).
- It is safe today because `outputs/` never expires and these threads are new. The tests write a hand-rolled manifest (`test_quality_review_db._save_brief`), so drift from `encode_manifest` would go unnoticed. If a best-effort snapshot save fails, `brief_written` is False after a completed review and the pages take an older brief (see F5).

## F11. MINOR: an error in the awaiting-people branch on attempt 3 or later writes the pages before the nominee is researched

- `_review_then_pages`: if `reconcile_generation` or `review_waits_for_people` raises on attempt ≥ `arv2_job_max_attempts_no_progress`, control falls through to `_rewrite_account(needs_review=True)` although the agent has just nominated someone.

## F12. MINOR: trial harness

- `trial/launch.py` has no database guard. `trial/worker.py` refuses any database except `clue_research_trial`, but the launcher will start paid research against whatever `CLUE_DATABASE_URL` names.
- The trial flags themselves do not leak (see below). Note that with `TRIAL_HOLD_PERSON_JOBS=1` a held person stays `not_started`, and `pending_continuations` never skips a not-started person. So held trials can never reach the review or page step for an account that nominated anyone.

---

## Checked and fine
- Trial-only behaviour: `TRIAL_HOLD_PERSON_JOBS`, `TRIAL_RELEASE_PERSON_WORKSPACE` and `TRIAL_RELEASE_PERSON_JOBS` exist only in `trial/worker.py` as monkeypatches. No production module reads them. The local imports in the driver pick up the patch at call time.
- Continuation redelivery guards: a reconciled revision gives `superseded`, and a non-current revision without a retained snapshot gives `superseded`. The `review_waits_for_people` event id is deterministic per (generation, revision), so a duplicate delivery cannot double-bump.
- Review unit keys: a crashed, unfinalized review resumes the same checkpoint. A completed review replays from its committed outcome without being paid for again. A self-ended failed review gets `:retry-N`. This matches `load_committed_outcome`'s join.
- The nomination cap bypass applies only at recipe 40 or later and only while the parent job is `completed` or `needs_review`. The first turn still respects the cap. Renomination reuses the deterministic `quality_person_job_id`. Person jobs nominated during a review are released by the sweep (`ready_person_jobs`: parent not `not_started`).
- New roles (`executive_sponsor`, `user`) are added consistently to the tool inputs, `CommitteeAssessment` and display labels and ranks. Downstream maps (`INFLUENCE_DEFAULTS`, `PERSONA_TONES`, HubSpot) use `.get` with defaults.
- The stall clause: `started_at` is reset on every claim (`begin_job`), so GREATEST never sees NULL for an in-progress job. Gated at recipe 40+, not-started people are never skipped, and privacy-stopped people are skipped.
- `_retries_exhausted` records the child result, and `sweep_quality`'s `missing` query recovers it if the worker dies in between. `_final_step_after_crash` makes a crashed account with nominees still reach the final step.
- The markdown dossier is gated to recipes 32–36 and v4 account jobs only, so new launches (44) cannot reach it. It checks shape only, by founder ruling. Versions are zero-padded, so lexical DESC ordering is correct.
- All guide files `skills/{research-page-writing,account-pages,contact-page,seller-brief}/v1..v4` exist, and `test_guide_v4_is_v3_plus_the_recording_quote_line` loads every one (passes).
- The new settings (`CLUE_ARV2_PERSON_STALL_WAIT_S`, `CLUE_ARV2_JOB_MAX_ATTEMPTS_NO_PROGRESS`, the speaker-check pair) are present in `.env.example`.
- AW-8: the review input is written into the turn's own workspace (snapshotted). Source files are copied from the source snapshot, never from local disk. Nothing depends on running on the same machine.
- `resume_research_job` clears `no_progress`.
