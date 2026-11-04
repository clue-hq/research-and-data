# Account brief after person research: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** From recipe 40, the account agent writes one brief after its people's research, then account pages, then contact pages, and every account ends in pages or a clear `needs_review`.

**Architecture:** No new job status. The account's first turn finishes and frees its slot; its generation waits. The existing continuation resumes the agent for a review turn on its saved conversation, then runs the existing final page step. Research decisions live in a new `account-review` skill; code only runs the machinery.

**Tech Stack:** Python, asyncpg/SQLAlchemy, deepagents turn runner, fleet queue, pytest.

**Spec:** `docs/superpowers/specs/research-quality/2026-11-05-brief-after-person-research-design.md`

## Global Constraints

- Everything is gated on `at_least(scope, BRIEF_AFTER_PEOPLE)`, where `BRIEF_AFTER_PEOPLE = 40`. Recipes below 40 behave exactly as today.
- Never use `suspended` for the wait. No task holding `self._jobs` may wait for another job.
- No code limit or refusal on a research decision: replacements, gaps, leads and verdicts belong to the agent.
- Wait: 30 minutes without progress on a started person (`CLUE_ARV2_PERSON_STALL_WAIT_S`, default `1800`). Not-started people are never skipped. The stuck job is not killed.
- Crash limit: 3 attempts in a row without progress (`CLUE_ARV2_JOB_MAX_ATTEMPTS_NO_PROGRESS`, default `3`), failure code `retries_exhausted`.
- Every new setting goes in `.env.example` with its default and in the local `.env`.
- Commit locally, never push, no AI attribution. Prompts and skills stay seller-agnostic, in plain language, with generic examples. New catalog text is exactly the founder-approved wording below.
- Run tests with `--ignore-glob='*_live.py'`, one named file at a time, with `CLUE_DATABASE_URL` pointing at `clue_addis_sdd` (`alembic upgrade head` first). Never on `clue_research_trial`.
- Live runs need the founder's go, with the cost stated.

## Review Focus

1. A person finishes while a review is running: their result must not be lost. Next revision reviews again. Test in Task 5.
2. A review ends without writing the brief: pages fall back to the verdict summary, `needs_review`. Test in Task 5.
3. A person is privacy-stopped during the wait: never held for, no page written. Test in Task 3.
4. A worker dies mid-review: the same revision is retried, with no second brief from a stale turn. Test in Task 5.
5. A review nominates someone and then crashes: the nominee still runs, and the flow continues when they settle. Test in Task 6.

---

### Task 1: Recipe 40 catalog and first-turn wording

**Files:**
- Create: `platform/agents/catalog/research-quality/prompts/quality-account-research/v39/SYSTEM.md`, `profiles/quality-account-research/v39/profile.yaml`, `prompts/quality-person-research/v29-person/SYSTEM.md`, `profiles/quality-person-research/v29-person/profile.yaml`, `skills/claim-ready-person-dossier/v5/SKILL.md`, `skills/account-review/v1/SKILL.md`, `recipe-v40.json`, `launch-v4-r40.json`
- Modify: `platform/api/clue_api/arv2/quality_catalog.py` (`CURRENT_RECIPE_VERSION = 40`), `platform/api/clue_api/quality_research_wiring.py` (profile mapping `version >= 40` → `v39` / `v29-person`), `platform/api/clue_api/arv2/quality_generation.py` (`BRIEF_AFTER_PEOPLE = 40`)
- Test: `tests/arv2/test_quality_recipe_40.py`

**Interfaces:**
- Produces: `BRIEF_AFTER_PEOPLE: int`; skill `account-review` readable at `{{skills.account_review.path}}`.

- [ ] **Step 1: Write the failing test**

`test_recipe_40_pins_match_files`: every path in `launch-v4-r40.json` exists and its sha256 matches. `test_recipe_40_selects_new_profiles`: `quality_profiles(..., version=40)` selects `v39` and, with `person=True`, `v29-person`; version 39 still selects `v38` and `v28-person`.

- [ ] **Step 2: Run it and see it fail**

Run: `uv run pytest tests/arv2/test_quality_recipe_40.py -v`. Expected: FAIL, files missing.

- [ ] **Step 3: Write the catalog**

Build from v38 and v28-person, and bump versions, shas and pins as recipe 39 did.

**Account prompt v39, after the "Then, once your research…" passage, add (approved):**
> If a slot is free, do not leave it empty because someone has little public presence. Give it to the person whose role most likely owns what the seller's product touches, and say what you could not confirm about them.

**Account prompt v39, replace the "What you hand over" section's page-brief instructions up to and including the sections list with:**
> You will write the page brief later, after your people's research comes back. For now, put your provisional verdict and its main reason in the summary of /outputs/research.json: pursue, pursue with conditions, or not now.

Keep "Be realistic…", the brief's section list and its Message/Why/Evidence/Do-not-say format by moving them into `account-review/v1`, after the approved instruction below. Tell the prompt to read that skill when asked to review.

**`account-review/v1`, exact approved instruction:**
> Your people's research is finished, or as finished as it will get. Read /work/review/input.json. It tells you, for each person, what was found, what could not be reached, and whether they are still running or failed. Decide what this changes about your verdict and your approach, then write /outputs/page-brief.md as your only brief. Treat a failed or unfinished person as a gap, not as nothing to find.
>
> If someone has left the company, look for whoever holds that responsibility now, check where they work today, and nominate them, saying who left and why. If that person turns out to have left too, decide again: look further, or name the seat as a gap. Check a lead only if it could change your verdict or approach; do not repeat your research. If your research was blocked, say so plainly instead of writing a confident verdict.

**Person prompt v29 career paragraph and claim-ready skill v5 career row: add (approved):** credentials and certifications go in the one job-history finding, unless they bear on what the seller sells.

- [ ] **Step 4: Run it and see it pass**, using the same command.

- [ ] **Step 5: Commit**

`git commit -m "Trial recipe 40: brief after people, free-slot wording, credentials rule"`

---

### Task 2: An honest blocked report does not crash the job

**Files:**
- Modify: `platform/api/clue_api/arv2/quality_results.py:17`
- Test: `tests/arv2/test_quality_recipe_40.py`

- [ ] **Step 1: Write the failing test**

`test_report_accepts_blocked_status`: `ResearchUnitReport.model_validate` with `status="blocked"` and `next_actions=["Restore acquisition"]` succeeds and keeps both. `test_saved_report_without_them_still_loads`: both default to `None` and `()`.

- [ ] **Step 2: Run it and see it fail.** Expected: `extra_forbidden`.

- [ ] **Step 3: Add `status: str | None = None` and `next_actions: tuple[str, ...] = ()`**

Keep `extra="forbid"`. No behaviour depends on these fields; the agent's words simply survive.

- [ ] **Step 4: Run it and see it pass, then commit**

`git commit -m "Research reports can say they were blocked"`

---

### Task 3: Pages wait, and the wait rule

**Files:**
- Modify: `platform/api/clue_api/arv2/account_research_driver.py` (`_write_pages`, `_settle_quality`, `sweep_quality`, `_offer_display_page` call), `platform/api/clue_api/arv2/quality_generation.py` (`pending_continuations`), settings file holding `arv2_account_max_runtime_s` (find with `grep -rn arv2_account_max_runtime_s platform subsystems`), `.env.example`, `.env`
- Test: `tests/arv2/test_quality_generation_db.py`

**Interfaces:**
- Produces: `pending_continuations(conn, *, limit=100, generation_id=None, stall_after: timedelta | None = None)`. With `stall_after`, a recipe-40 child counts as settled for waiting when it is `in_progress` and `coalesce(max(arv2_quality_activity.created_at), started_at) < now() - stall_after`.
- Produces: `arv2_person_stall_wait_s: int = 1800`.

- [ ] **Step 1: Write the failing tests** (seed with `finish_seeded_job`, as this file does)

- `test_account_waits_for_person_in_progress`: child active 29 minutes ago → `pending_continuations(stall_after=30m)` returns nothing.
- `test_account_stops_waiting_after_stall`: child active 31 minutes ago → returns the generation; the child's status is still `in_progress`.
- `test_not_started_person_is_never_skipped`: child `not_started`, created 3 hours ago → returns nothing.
- `test_privacy_stopped_person_is_not_waited_for` → returns the generation.
- `test_recipe_39_ignores_stall`: same as the stall case with recipe 39 → returns nothing.
- `test_write_pages_defers_at_40`: `_write_pages` returns `deferred_pages=("insights","overview")` for an account and `("contact",)` for a person with an imported parent, without calling the writer; `coverage` does not report them missing.

- [ ] **Step 2: Run them and see them fail.**

Run: `uv run pytest tests/arv2/test_quality_generation_db.py -v -k "stall or waits or never_skipped or privacy_stopped_person or defers"`.

- [ ] **Step 3: Implement**

Extend the SQL's unsettled-child condition. `_write_pages` returns early at recipe 40. `sweep_quality` passes `stall_after` from settings. `_offer_display_page` is skipped at recipe 40. `_settle_quality` is otherwise unchanged, which is what frees the slot.

- [ ] **Step 4: Run them and see them pass, then commit**

`git commit -m "Recipe 40: pages wait for people, and the wait ends on a stalled person"`

---

### Task 4: Crash limit

**Files:**
- Modify: `platform/api/clue_api/arv2/account_research_driver.py` (`_run`, after `begin_job`), settings, `.env.example`, `.env`
- Test: `tests/arv2/test_quality_driver_db.py`

**Interfaces:**
- Produces: `arv2_job_max_attempts_no_progress: int = 3`; `no_progress_attempts(conn, job) -> int` in `quality_generation.py`.

- [ ] **Step 1: Write the failing tests**

`test_job_stops_after_three_attempts_without_progress`: three claims with no new activity rows; the third lands `needs_review` with `failure_code="retries_exhausted"`, runs no agent, and records a child result. `test_progress_resets_the_count`: an activity row between claims means the count restarts at 1. `test_recipe_39_has_no_limit`.

- [ ] **Step 2: Run them and see them fail.**

- [ ] **Step 3: Implement**

At each claim, read the job's activity count and compare it with `input_refs.no_progress = {"activity_count", "attempts"}`. Same count → attempts + 1; otherwise reset to 1. Write it back on the claiming connection. Land through the existing `needs_review` helper used by `_run`'s failure path.

- [ ] **Step 4: Run them and see them pass, then commit**

`git commit -m "Recipe 40: a job that keeps crashing without progress lands needs_review"`

---

### Task 5: The review turn

**Files:**
- Create: `platform/api/clue_api/arv2/quality_review.py`
- Modify: `platform/api/clue_api/quality_research_wiring.py` (`ResearchUnitRuntime`, `run`), `platform/api/clue_api/arv2/quality_results.py` (`QualityJobRunner`), `platform/api/clue_api/arv2/account_research_driver.py` (`_focused_reconciliation`, new `_review_then_pages`)
- Test: `tests/arv2/test_quality_review_db.py`

**Interfaces:**
- Produces: `async def review_input(conn, storage, scope, context_id) -> dict[str, JsonValue]` returning `{"research_date", "people": [{"contact_id", "name", "title", "status", "still_running", "failure_code", "summary", "gaps", "findings"}]}`.
- Produces: runner parameter `review: dict[str, Any] | None = None`. When set: resume on the source thread as `reconciliation` does, copy source files, write `work/review/input.json`, `required_output_path="outputs/page-brief.md"`, **no tool filter**, and no `owner.report`.
- Consumes: `pending_continuations`, `_rewrite_account`, `page_brief` (Task 3 and existing).

- [ ] **Step 1: Write the failing tests** (fake `quality_runner`; real database and generation)

- `test_review_input_reports_every_person`: completed, failed and still-running people appear with the right flags.
- `test_review_runs_before_pages`: call order is review, then account pages, then contact pages; generation ends reconciled.
- `test_one_review_with_no_new_input_causes_no_other`: after settling, `pending_continuations` is empty.
- `test_person_finishing_during_review_triggers_next_review`: a child result signalled mid-review leaves a pending revision.
- `test_review_without_brief_falls_back`: the runner succeeds with no brief → pages come from the job summary, and the generation is `needs_review`.
- `test_review_failure_retries_then_falls_back`: failures on attempts 1 and 2 requeue the same revision; attempt 3 writes fallback pages, `needs_review`.
- `test_stale_review_does_not_settle`: a redelivered review for an older revision writes nothing.
- `test_page_brief_reads_the_review_turn`: `page_brief` returns the review execution's file, not an older one.

- [ ] **Step 2: Run them and see them fail.**

Run: `uv run pytest tests/arv2/test_quality_review_db.py -v`.

- [ ] **Step 3: Implement `_review_then_pages(self, work, composition, generation_id, revision, assert_lease) -> WorkResult`**

Branch at the top of `_focused_reconciliation` when `at_least(scope, BRIEF_AFTER_PEOPLE)`. Hold `self._jobs` only around the runner call and release it before anything else. Objective: "Your people's research is ready. Read the account-review skill and follow it." `unit_key=f"review:{generation_id}:{revision}"`. Retry from `work.task_attempt`: below 3 requeue, at 3 fall through to pages with `needs_review`. Then call `_rewrite_account`, which already takes its own slot and settles the revision.

- [ ] **Step 4: Run them and see them pass, then commit**

`git commit -m "Recipe 40: the account agent reviews people's findings and writes the one brief"`

---

### Task 6: Replacements can be nominated

**Files:**
- Modify: `platform/api/clue_api/arv2/quality_committee_tool.py:111`, `platform/api/clue_api/arv2/account_research_driver.py` (`_review_then_pages`)
- Test: `tests/arv2/test_quality_review_db.py`

- [ ] **Step 1: Write the failing tests**

- `test_review_can_nominate_past_the_cap`: parent job finished, committee full → nomination succeeds and a child is registered.
- `test_first_turn_still_respects_the_cap`: parent job in progress, committee full → refused as today.
- `test_review_that_nominates_writes_no_pages`: the revision settles without a page write; pending stays empty until the nominee settles; then a new review runs.
- `test_nominee_survives_a_crashed_review`: runner nominates then raises → the nominee is released by the sweep and the flow continues when they settle.
- `test_renominating_someone_reuses_their_job`.

- [ ] **Step 2: Run them and see them fail.**

- [ ] **Step 3: Implement**

Apply the cap check only while the parent job is not finished. It stays the setting for the first turn. In `_review_then_pages`, after the runner returns, if any child is unsettled under the wait rule, reconcile this revision with `processed_snapshot=True` and return without pages. Confirm `resolve_authority` accepts a finished parent, and fix it only if the test shows it refuses.

- [ ] **Step 4: Run them and see them pass, then commit**

`git commit -m "Recipe 40: a review can nominate replacements"`

---

### Task 7: Forced failures, then the real run

**Files:**
- Modify: `trial/worker.py` (test-only failure switches, off by default), `docs/superpowers/specs/research-quality/ledger.md`, `docs/superpowers/specs/research-quality/roadmap.md`
- Test: `tests/arv2/test_quality_review_db.py`, then live trial runs

- [ ] **Step 1: Write the scenario test**

`test_whole_flow_with_one_slot`: with `self._jobs` set to 1, an account and three people run through the real driver with a fake runner, to reconciled pages, under a 60-second timeout. This is the direct deadlock proof.

- [ ] **Step 2: Run it, plus the existing generation and driver suites**

Run, one at a time: `uv run pytest tests/arv2/test_quality_review_db.py -v`, `tests/arv2/test_quality_generation_db.py`, `tests/arv2/test_quality_driver_db.py`. Expected: PASS, apart from failures you can show also occur on the base commit.

- [ ] **Step 3: Ask the founder for a go, with the cost, then run the forced failures**

On one trial account, using `trial/worker.py` switches: kill a person job; hang one with a short stall setting, then let it finish late; crash a job repeatedly; fail the review; refuse Exa; `CLUE_ARV2_ACCOUNT_MAX_PARALLEL_JOBS=1`. Each must end in pages or a clear `needs_review`. Record each result in the ledger.

- [ ] **Step 4: Ask for a go, then run NTG and Nav on recipe 40**

Compare with recipe 39. Report: does Drew Herpich's Vooma role reach the verdict and the pages; is Brian Miller nominated; how many briefs and account page writes per account (expect one each); the review turn's cost.

- [ ] **Step 5: Commit the ledger and roadmap**

`git commit -m "Research quality: ledger — recipe 40 results"`
