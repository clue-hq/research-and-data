# ARV2 R3 task 6 — the committee step and the person launch paths (2026-09-09)

## What landed

- **`platform/api/clue_api/arv2/committee_step.py`** — `run_committee_step(conn, *, job, run, scope,
  candidates, writer, person_profile_sha256) -> CommitteeStepResult(contacts_created, jobs,
  skipped, linkedin_missing)`. Per candidate, in the model's own order, up to `run.committee_cap`:
  resolve the person (LinkedIn strong key workspace-wide → exact name under the account → create),
  `create_job(subject_type="person", …)`, and write the three `committee_member_claims` **only when
  that call inserted the job row**. Skip reasons: `vacant_seat`, `unconfirmed`, `committee_cap`,
  `ambiguous_name`, `member_not_written`.
- **Driver** — `_settle` runs the step inside the settling transaction after `finish_job`, for
  `subject_type == "account"` only, and offers the resulting `QueuedJob`s **after** the transaction
  closes (`enqueue_launched_jobs`). New `queue: WorkQueue | None` constructor parameter, threaded
  from `build_arv2_account_research_handler` and `fleet_main`; `queue=None` still writes rows and
  logs `arv2.committee_jobs_not_enqueued`.
- **`launch_arv2_person_research`** + `Arv2PersonLaunchRequest` — a run of its own (`effort="full"`,
  `committee_cap=len(contacts)`, `profile_ref=ARV2_PERSON_PROFILE_REF`), resolving its ICP pin from
  the project's brand's newest confirmed `icp-definition` and its product pin from the current
  confirmed set. Refusals: `lane_disabled`, `no_contacts`, `project_not_found`,
  `contact_not_found:<id>` (unknown **or** foreign), `contact_merged:<id>`,
  `contact_without_account`, `icp_artifact_not_found`, `icp_front_matter_invalid`,
  `product_set_not_confirmed`.
- `launch_arv2_person_research@1` toolbelt tool (SPEND, action-ref gated), registered **ungranted**;
  `scripts/launch_arv2_person_research.py` (`--contacts` = contact ids or LinkedIn URLs, mixed).

## Decisions worth remembering

- **The receipt did not carry the committee.** `_finalize_research` recorded only summary /
  fit_verdicts / gaps, so there was nothing for the step to read. Fix: it now also puts
  `committee_candidates` on `runtime.finalization` (**in memory only**) — deliberately NOT copied
  into `finalization_json` by `_receipt`, because a second at-rest copy of a person's name/title is
  one no DSAR erasure would reach. Reading the claim rows instead was rejected: they carry every
  field but no order, and order is what the cap truncates.
- **`person_not_admitted` removed** from `REACTIONS`, `_PERSON_ONLY_CODES` and the person
  `manual.md`. It had no emitter (Task 4's `structure_material` refuses `invalid_arguments`), and
  the person launch's refusals are `Arv2LaunchRefused` codes — a different namespace from the
  model-facing reaction table.
- **New `arv2/fleet_task.py`** holds `ARV2_ACCOUNT_DEDUP_PREFIX` / `ARV2_ACCOUNT_TASK_PRIORITY` /
  `arv2_account_work_id`. The driver now imports the launch (for `enqueue_launched_jobs`), and the
  launch already imported the driver for those three constants — a cycle. The driver re-exports
  them, so every existing import site is unchanged.
- **Idempotency** rests on the derived person job id (`arv2_job_id(run, contact)`, shared by all
  three job writers) plus per-member `begin_nested()` atomicity: a job row that exists is a member
  whose claims are already written, so a re-settle writes nothing and only re-offers.
- A member resolved through the workspace-wide LinkedIn key keeps **their own** account on the job
  row (the entity layer decides where a person works), matching the person launch.

## Known / recorded, not fixed

- `tests/api/test_toolbelt_wiring.py::test_build_toolbelt_registers_the_full_set` was **already red
  at HEAD `82fca9261`**: its `_MATRIX` predates `launch_arv2_account_research`,
  `read_arv2_account_research_run` and `design_set_web_noindex`. My tool makes it a fourth extra
  name. Not fixed (three of the four rows are not this lane's to write; standing rule 2026-09-07).
- The job's durable receipt records nothing about the fan-out (it is written before the step runs).
  If the run-overview projection ever wants "2 launched, 1 vacant seat", it needs a second write —
  and must keep names out of it.
- The committee's contact claims do not go through the §5 person compliance floor (neither do the
  account job's own `account.committee_candidate` claims). Persona/role/title are professional
  facts; if the floor should cover them, that is a Task 5 owner's call.
