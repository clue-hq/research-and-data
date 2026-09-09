# ARV2 R3 — the committee step and the person agent (close-out, 2026-09-09)

Branch `track-r3`. Plan `docs/superpowers/plans/2026-09-09-arv2-r3-person-agent.md`; substance
`…-substance.md` (rev 2, approved 2026-09-09); SDD ledger
`.superpowers/sdd/2026-09-09-arv2-r3-person-agent/progress.md`. Eleven tasks, executed by Opus
implementers with the controller reviewing every task first-hand.

R3 turns an account job's confirmed buying committee into people the platform can research,
address and govern: a candidate becomes a contact entity with a committee seat and a job of its
own, and that job runs a second agent — the person agent — under the same lane, the same fleet kind
and the same failure law. The lane-facing documentation is
`platform/api/clue_api/arv2/README.md` § "R3 — the committee step and the person agent"; the live
record is `.context/arv2-r3-acceptance/acceptance.md`.

## Commits (base `d907efdcc`)

| commit | what |
| --- | --- |
| `ec2a12817` | T1 — job rows carry a subject; migration `60e51eba0123`; the two new settings |
| `f922a5001` | T2 — the `arv2-person/v1` catalog (5 files), catalog loading generalised to two agents |
| `53ac32fbd` → `53ae5f01a` | T3 — person subject in the claim path, AI Ark person/email mappers, committee-member claims, unique-insight mode, person catalog (+ one fix round) |
| `4013af9d6` | T4 — the person toolbelt: `lookup_person`, person structuring, `unique_insight`, media cap, person finalize |
| `82fca9261` | T5 — `person_compliance.py`, the coded floor |
| `2ce5f81bc` | T6 — the committee step; the on-demand person launch (service, CLI, ungranted tool) |
| `93632965e` | T7 — `Arv2CommitteeReferenceSource` first in the eligibility chain; coverage read removed from `committee_members` |
| `04229ac79` | T8 — the driver composes person jobs; account jobs fan the committee out |
| `8ec7de851` | T9 — answer-key recall per person (`--people`), insight from the marker |
| `2f5a00712` | final-review fix wave (C1, I2–I6, M1, M2, M4–M7) |
| `be560aeab` | live fix wave 1 — L1, L2, C1b, the repair script |
| `0e79ead4a` | T10 acceptance evidence |
| `353b55bcd` | live fix wave 2 — W1–W4, repair hardening, migration `7c4f1a2b9d63` |
| `0d4e20e01` | acceptance evidence re-dumped after wave 2 |
| this commit | T11 — README R3 section, master-plan row, this note, the carried lint/matrix items |

## Rulings taken (from the ledger, in order)

1. **One fleet kind carries both subjects** (`arv2_account_research`); the handler dispatches on
   `job.subject_type`. Avoids an enum migration and a second handler. Cost if wrong: person jobs
   compete for the same per-kind worker slots as account jobs — acceptable at this scale.
2. **The person profile pin lives on the job row** (`profile_sha256`), not a second run column: a
   run created by the account launch owns account jobs and person jobs with different pins. Account
   jobs copy the run's pin, so nothing is lost.
3. **`PERSON_REFUSAL_CODES` and the five person REACTIONS rows moved from T4 into T2**, so the
   catalog tests (manual names every code; manual ↔ REACTIONS word for word) are self-contained the
   moment T2 lands.
4. **T3 F1/F2 (controller review):** `ai_ark_person_claims` must not write `contact.linkedin_url`
   (no pack registers it; the LinkedIn URL is the contact entity's strong-key column, which the
   read surface uses) — the mapping was dropped. And `read_person_catalog` must not offer the seven
   `account.*` keys as writable, or a person job would write account facts onto the contact — the
   person catalog is `contact.*` + `core.work_email` only, and account facts reach the agent
   through the already-established block. Kept deliberately:
   `contact.role_on_committee.influence` (undeclared but read by `frontend_read`),
   `network_statistics.connections`, and namespace-less proposed keys folding to `contact.*`.
5. **`write_each` returns `list[(draft, result)]`** — a positional zip would raise on the first
   redacted or dropped draft once the compliance floor could remove one. Five call sites updated.
6. **`person_not_admitted` removed** from REACTIONS, `PERSON_REFUSAL_CODES` and the manual
   together: no tool emits it, and T6 decided the launch would not either.
7. **Confirmed candidates are read from the finalize call held in memory** (`runtime.finalization`),
   not from `finalization_json`: the `account.committee_candidate` claims already hold the names at
   rest, and the model's order — which `committee_cap` truncates — is not recoverable from rows. A
   job replayed after a crash between finalize and settle re-runs finalize anyway.
8. **The ARV2 committee is per ACCOUNT, not per project run.** Every project targeting the account
   sees the same seated people. Per-project scoping, if ever wanted, is a filter on
   `arv2_research_run.project_run_id` — recorded, not built.
9. **Final-review fix wave scope:** C1 (phone-merge regex), I2 (lock anchored on
   `scope.person_linkedin_url` before the hop), I3 (`compliance_log` from the runtime on the
   receipt), I4 → option (a): additive optional `rationale`/`influence` on `CommitteeCandidate`
   mapped into `contact.role_on_committee`, I5 → the unevidenced rule is an **OR** (no span **or**
   no URL) with rule 6 exempting API-method drafts and `contact.facet.hooks`, I6 (contact details
   dropped whole; wholly-sensitive values dropped; else redacted by sentence), M1 (street pattern
   needs a comma or postcode neighbour), M2 (record claims written before the export hop), M4–M7.
   Left for T11: M8/M10 and the `_MATRIX` names. Left as parked: a currency figure with three
   thousands separators can still read as a phone (a drop is logged, no answer-key value has that
   shape); I5 implemented as a full rule-6 skip for API/hooks drafts, no `unevidenced` marker on
   them — intended.
10. **Founder, mid-run (2026-09-09):** stop the remaining jobs; fix the defects found so far; test
    the remaining people on the fixed code.
11. **Founder, superseding:** re-test the **same five** people on the fixed code (an earlier ruling
    had said "2–3 people only" and kept Chonoles / Kaur / Fisher). Vari Kaur and Nick Fisher were
    dequeued; Tyler Chonoles was left to finish on the new code.
12. **Founder ruling on the on-demand seat (wave 2):** the seating claims are
    `ExtractionMethod.HUMAN` (tier 1, no URL required) — a human's own statement, not model
    synthesis. Stamping them `LLM_SYNTHESIS` would have tripped the writer's `source_missing`
    marker on a claim that is honestly unevidenced-by-URL.
13. **Founder ruling:** the answer-key loader's `core.work_email` rows carry the provider's raw
    block, so they now read `schema_valid=false` — a loader (D1) follow-up, not R3's.
14. **Task 10 complete by ruling** — partial acceptance: six people on the fixed code plus the two
    live fix waves and two repair runs; the remaining people are re-offerable, not run.

## Live defects and their fixes

| id | found | fix |
| --- | --- | --- |
| **L1** | `lookup_person` refused `subject_lock_failed` "employer not stated" on all three Cogent people: `_current_company_domain` trusted the record's company block only when its name equalled the position's (`"Cogent Security"` vs `"Cogent"`), so the employer came back unknown and the lock failed closed — no provider claims, no email export | the client resolves the employer by a ladder (fold-equal LinkedIn **company URL** first, folded-name **containment** second, else unknown); the tool now **corroborates** rather than gates — a different resolvable employer refuses, an unknown one proceeds with marker `employer_unverified` |
| **L2** | the unique-insight pass wrote its row to `contact.facet.hooks`, a derived outreach list | `UNIQUE_INSIGHT_TARGET_KEYS` (fact facets only); off-target rows dropped, named in `dropped_off_target`, cap applied after the filter |
| **C1b** | the phone scan still dropped legitimate claims — four talk lists and one career history, where whitespace-separated years and dates merged into 9–15 digit runs | a phone match must carry a phone **signal** (leading `+`, parenthesised area code, dash/dot tail, UK 5+6) or a phone word in the sentence; the scan reads one sentence at a time |
| **W1** | `core.work_email` written as a bare string; `email_facts` reads `{address, status}` → the Email chip was empty for everyone | the mapper writes `{address, status, checked_at}`; migration `7c4f1a2b9d63` moves the registry row to the object shape |
| **W2** | a person launched on demand got no persona/role claim, and the ARV2 committee source requires the persona claim → Coles, Corio and Chonoles were researched at full cost and invisible on their account's contact list | the launch seats them (`--persona`, default `user`; rationale "launched on demand by `<user>`") through `seat_person_on_committee`, as `ExtractionMethod.HUMAN` |
| **W3** | `current_position_start` reads `date.start`/`date.end`; the mapper wrote flat `start`/`end` → tenure empty | the mapper nests under `date`; migration swaps the registry row; the identity lock's employment lines read both spellings, because rows at rest are immutable |
| **W4** | the AI Ark title carried the company (`"Head of Growth \| Cogent"`) | a trailing `" \| <x>"` / `" at <x>"` is cut only when `<x>` folds **equal** to the record's company or the job's account name; raw title kept as marker `title_raw` |
| **W5** | `overviewParagraphs` is 0 | not R3's — `contact.overview` belongs to the old prose tool |
| repair | `scripts/arv2_repair_person_lookups.py` was not idempotent — the Harmonic pair, whose lookup had succeeded, was billed again and got duplicate rows | idempotent by default (`skipped_already_looked_up`), `--force` overrides, `--persona` seats a finished person |

## Acceptance numbers (`.context/arv2-r3-acceptance/`)

- **What ran:** run `ba43bd2f` (Zafran, account path, cap 5) — the account job took 12 rounds, 113
  claims, $0.94, and its committee step admitted 4 candidates, skipped 1 vacant seat, created 1 new
  contact (Rotem Peled-Dvir) and reused 3 by LinkedIn URL: **4 person jobs = 4 fleet tasks**. Runs
  `1e2edb26` / `4900b571` (on demand) and `edb52ad3` (the same five re-run on the fixed code).
- **Six people on the fixed code** (Semien, Coles, Edupuganti, Paterson, Corio, Chonoles): the
  identity lock verified on all six, provider claims native on all six (0 → 6–7 for the three the
  L1 defect had cost), insight 6/6 on fact facets, zero phone-drops, EXACT audits up for everyone,
  emails 4/5 (Semien's export returns nothing — the provider's own 404 case). Cost per person
  **$0.67–1.25 + 1.5 AI Ark credits**; model spend ≈ 80 % of it; ~60k prompt tokens per round, ~85 %
  cached.
- **Answer-key recall** (leaf-value grading): Paterson 0.19 → 0.12, Semien 0.33 → 0.33, Corio
  0.07 → 0.29, Coles 0.11 → 0.22, Edupuganti 0.27 → 0.20, Chonoles 0.62 (fixed code only). Almost
  every miss is `field_only`; field-found coverage is ≈ 0.9 on every person.
- **Parallelism:** one worker process drives one job at a time; the driver's
  `CLUE_ARV2_ACCOUNT_MAX_PARALLEL_JOBS=4` never binds under that loop, and its single DB connection
  per process would serialise store writes anyway. Three workers on the last three re-runs: per-job
  wall 6:00 / 8:46 / 13:03 vs ~5:00 sequential; three finished in ~13 min where sequential would be
  ~15–16 — about **+25 % throughput, not 3×**. Four transient 429s (OpenRouter ×2, Gemini ×1,
  Exa ×1), all retried; no lease loss, no tracebacks. The bottleneck under load is the shared
  providers and the model, not the fleet.
- **Pages (after wave 2):** Zafran's contacts list shows 6 members from ARV2 rows in persona order;
  Cogent's shows 3 (Coles economic_buyer, Edupuganti economic_buyer, Semien champion) with emails
  for two; Coles's page reads `cameron@cogent.com` verified 2026-09-09, tenure 10 months, title
  `VP of Marketing`.

## Follow-ups (owned by nobody yet unless named)

1. **A facet-text recall grader.** Person facets are prose; exact leaf agreement is the wrong
   grader, so the R3 recall number understates the run and is *not* the number the master plan's
   exit gate means. A semantic or containment mode is needed before that gate is read literally.
2. **Account finalize writes committee candidates twice** — once through `write_claims`, once by
   finalize. A dedupe for the account finalize is owed (harmless today: append-only rows, same
   values).
3. **Loader (D1) data change:** the answer key's `core.work_email` rows carry the provider's raw
   block (`status: "VALID"`), so those rows now load `schema_valid=false` and the Zafran list's
   email chips stay empty for loader-seeded people. Fixing them is an answer-key data change, not
   a code one.
4. **Per-process concurrency > 1 is a fleet-loop + driver-DB-lock change, not an ARV2 setting.**
   The `max_parallel_jobs` semaphore cannot bind while the fleet loop claims → drives → claims.
5. **M10 data change — legacy-only committees now read empty by design.** `committee_members` no
   longer reads `entity_research_account_coverage`; an account only the old lane ever researched
   falls through `Arv2CommitteeReferenceSource` (which returns `None` when no contact holds a
   `contact.persona` claim) to the legacy sources, but those sources are now mostly unreachable
   through the default chain and their suites were re-pointed explicitly. Six legacy expectations
   were retired with dated reasons. This is the founder's 2026-09-09 "ARV2 schema is the only
   truth" ruling landing as a behaviour change, not a defect.
6. **Not run, and how to re-offer them.** Zafran's four committee person jobs (Vari Kaur, Sanaz
   Yashar, Ben Seri, Rotem Peled-Dvir), Mandar Marathe, Nick Fisher and Tom Anthony were dequeued
   by ruling — the **fleet tasks were deleted; the `arv2_research_job` rows remain `not_started`**.
   Re-offer them by replaying the same launch: the run id is `uuid5` over the request digest, so
   the relaunch returns the same run, writes no second job row, and `to_enqueue` names *every* job
   of the run (the queue's dedup key makes re-offering a live one a no-op).
7. **Deferred minors carried from the task reviews:** `subject_entity_id` carries no FK to
   `contact_entity` (plain uuid + CHECK, per the brief); `contact.role_on_committee.influence` is
   an undeclared key the frontend reads — a registry decision for a later pack pass; the compliance
   keyword lists are a founder dial (known safe-direction over-fires: "born in", "election",
   "married", "gay" as a surname; lower-case street addresses missed by design); the
   pre-composition containment receipt names the account model for a person job (no job row exists
   at that point); the established block is capped per section, so a person job may see up to 120
   lines; `contact_ids_for_account(include_merged=False)` is an additive param forced by the
   DSAR/merge test; the recall report's person display name is title-cased from the slug (exact for
   every manifest person, imperfect for O'Brien-style names).
8. **Residuals recorded in wave 2, unchanged:** `resolvers/{apollo,clay,zoominfo}` still map
   `core.work_email` to a bare address (no production callers — they are unregistered in every
   entrypoint); `tests/claimstore/test_merge.py::test_batch_scales_to_1k_entities` fails on the
   *shared lane DB* because it counts every `account.recent_funding` claim in the database and the
   live acceptance rows are in there (pre-existing pollution; passes on a clean DB); `mypy` reports
   a handful of errors in the touched ARV2 modules, all on lines these waves did not change.

## Carried lint/test items paid off in this commit

- `tests/api/test_toolbelt_wiring.py::test_build_toolbelt_registers_the_full_set` was red before R3
  and stayed red through it (the no-old-lane-gate rule): its `_MATRIX` missed
  `launch_arv2_account_research`, `read_arv2_account_research_run` (R2),
  `launch_arv2_person_research` (R3) and `design_set_web_noindex`. All four are now in the matrix
  with their bodies and their fail-closed reason codes, and the two count assertions were corrected
  to the measured tree (118 → 123 names, 136 → 140 addresses). This is a **name-matrix update**;
  no old-lane behaviour was touched.
- The two `SIM300` Yoda conditions introduced by Task 6 in
  `tests/agents/test_tool_authority_audit.py` (lines 120 and 127) are rewritten as
  `set(design_grants) >= …`.

## Verification (this commit)

Offline, **no `.env` sourced**, no `*_live.py` test, no `make check`:
`uv run pytest tests/arv2 tests/api/test_toolbelt_wiring.py tests/agents/test_tool_authority_audit.py
--ignore-glob='*_live.py' -p no:cacheprovider -q`; `ruff format --check` and `ruff check` on the two
touched test files.
