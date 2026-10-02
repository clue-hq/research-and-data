# The projection-replay loop + cross-job fold visibility — diagnosis and fix lane (2026-08-20, ~04:00 IST)

Session context: founder shared the background session's observations on the Millennium re-wedge
and asked how relevant its first-write-wins fix (`c7d6da82`) is. Verified against the live DB
(`clue@localhost:5432/clue`), then dispatched two Opus fix lanes. Companion note:
`2026-08-20-grok-account-run-results.md` (the original forensics).

## The closed loop, proven from `entity_research_job_event` / `entity_research_agent_event` (job `eea48931`)

| time (IST) | error | layer |
|---|---|---|
| 02:14 | `projected evidence span is absent from retained artifact` | span-fidelity guard `entity_research_tools.py:2123` |
| 03:17 | `Sumble projection replay changed` | replay-identity guard, after `aa88e0b0` changed projection composition |
| 03:46 | `projected evidence span is absent from retained artifact` — **same error_message_sha256 as 02:14** (`17a1edb3…` vs 03:17's `2e1163fb…`) | span guard again, 9s after the `c7d6da82` fleet boot, <1s after claim |

Chain: pre-`aa88e0b0` code projected a conflict contender's span from a FOREIGN source's artifact
(employee_count conflict: Sumble 955 vs Websets 819) → span guard refused (02:14) → `aa88e0b0`
fixed composition → replay recompute mismatched the stored row (03:17) → `c7d6da82` served the
stored projection → the stored projection IS the defective draft → span guard refused it again
(03:46). The checkpoint replays the poisoned `enrich_account` call before the model gets a turn,
so the job re-dies identically on every resume.

## Operation state (queried live)

`sumble-account-operation:7e29c0bf-3923-4031-96ff-6db243f769f0` (sumble_organizations,
employee_count/hq_location): dispatched=t, **result=f, fold=f** — real spend, retained snapshot,
projection never once admitted. Same job also carries the ORIGINAL cross-job fold wedge:
`sumble-account-operation:89f64be2…` (tech stack 402) has a fold under Terra job `298f3dec`, and
the committee op `74d51ae8…` (sumble_people 402) folded under this job. Two independent wedges.

## Verdict on `c7d6da82` (ratified in-session)

Right principle, over-applied: first-write-wins protects **admitted history**. A stored
projection whose operation has NO `entity_research_result` row anywhere is a failed draft, not
history — serving it faithfully just re-presents un-verifiable evidence to the anti-fabrication
guard, which correctly refuses. `entity_research_sumble_projection` is append-only (UPDATE/DELETE
trigger-rejected), so supersession is by NON-ADOPTION: serve the fresh recomputation (the code has
already recomputed it from the retained snapshots by the time the mismatch branch runs); the
stored row stays as the immutable first-draft audit record.

## The two fix lanes (Opus agents, dispatched ~04:05)

1. **fold-visibility** — drop the fold `job_id` equality in the four *disposition* readers ONLY:
   `account_entity_research.py` `pending_provider_operations_sql` (~:164) + completeness
   terminal_rows (~:330); `contact_entity_research.py` `_pending_refs` (~:899) + finalization
   pending count (~:1183). A fold is a property of the operation, not the asker. Spend sums
   (contact ~:1164, account ~:2005) stay job-scoped — a replaying job spent nothing. Result
   clauses stay job-scoped too (cross-job results ARE repairable via zero-spend replay; folds are
   not — the re-call path ends in ON CONFLICT DO NOTHING).
2. **reprojection** — in both `sumble_entity_research_tools.py` mismatch branches (account ~:770,
   committee ~:1593): if an `entity_research_result` exists for the operation → keep serving
   stored (c7d6da82 stands); if none → return the fresh recomputation.

Both TDD (red-proof required), focused suites only, no commits by agents — orchestrator reviews
the combined diff, commits in two slices, runs full `make check` once.

## Lane 2 (reprojection) — DONE, uncommitted (agent close-out ~04:45)

Shipped in `platform/api/clue_api/sumble_entity_research_tools.py`: one new module-private helper
`_operation_result_admitted(conn, *, operation_ref)` (`SELECT 1 FROM entity_research_result WHERE
provider_operation_ref=… LIMIT 1`), and both mismatch branches (account `_persist_projection`,
committee `_persist_committee_projection`) now hoist their comparison into a `replay_differs` bool
and only serve the stored payload when `replay_differs and await _operation_result_admitted(...)`.
No result → falls through to the fresh recomputation already computed from the durable snapshots.
Nothing else in the file touched; the stored-contract fail-closed checks are unchanged.

Tests (TDD, red-proven on `c7d6da82`) appended to `tests/api/test_evidence_span_provenance_db.py`:
- `_PreFixAccountProjection` (subclass re-adding the pre-`aa88e0b0` contender-evidence) drives one
  REAL enrichment so the stored draft is genuinely the wedged shape; `_wedge_a_stored_projection`
  is the shared fixture.
- `test_a_never_admitted_stored_projection_is_recomputed_on_replay` — red on HEAD with
  `assert {'exa_websets','sumble_organizations'} == {'sumble_organizations'}`; green after. Also
  asserts the 02:14 refusal on the stored draft, that `_validate_artifacts`/`_validate_fields` now
  admit the replay, and that the append-only first draft is untouched at rest (audit).
- `test_an_admitted_result_still_replays_its_stored_first_projection` — plants the whole
  run→job→turn→event→tool_request→observation→result FK chain (helper `_admit_one_result`, scope
  read back off the real provider-operation row so the authority triggers pass) and asserts the
  served field is byte-identical to the stored first write. Passed before AND after: it is the
  `c7d6da82` guard.
- `test_a_never_admitted_committee_projection_is_recomputed_on_replay` — committee branch covered
  via two direct `_persist_committee_projection` calls (first through a subclass whose
  `_committee_evidence_ref` mints legacy refs); red on HEAD, green after.

Verification: `tests/api/test_evidence_span_provenance_db.py` (5 passed) plus
`test_account_entity_research_r5_db.py` + `test_sumble_account_gaps_s1.py` +
`test_committee_agent_inference_acceptance_db.py` (20 passed) and
`test_comprehensive_account_execution_db.py` (12 passed) on throwaway DB
`clue_missoula_reproj`; `ruff format`/`ruff check` clean on both edited files; `mypy` reports zero
errors in either (tests/ is outside the gate's `files`). Full `make check` NOT run (orchestrator
owns it). No commit made.

Note for whoever resumes job `eea48931`: this fixes the loop for the *account* operation
`7e29c0bf…`. The stored defective row stays in `entity_research_sumble_projection` forever by
design — do not "clean it up".

## LIVE PROOF — job `eea48931` settled (2026-08-20 05:20 IST)

Committed as `5dd1b3f8` (fold visibility) + `15f27702` (reprojection) + `55ed419d` (this note);
strict review passed (red-proofs independently re-run by the orchestrator; 41-test regression net
incl. the 5×3 harness green; full-gate triage: 56/58 failures byte-identical at HEAD =
pre-existing/environmental, 1 suite-order artifact, 1 load-flaky 30s-subprocess test — none ours).
Fleet restarted on the fixed code (worker `018f8a47`, 05:19 IST), `eea48931` resumed via the
governed path. **28 seconds later: terminal / needs_review.** The four-times-lethal replayed
`enrich_account` ADMITTED (result `c8be9969…`: `core.employee_count` found/accepted — the tier-1
955; `core.hq_location` conflict/conflicting, projected with same-source evidence only), assess
wrote coverage `5d94747d…` with no phantom pending-work refusal, finalize settled. Zero new spend
(2.50 total, unchanged — the replay served retained snapshots).

Committee: `needs_review`, zero members — CORRECT: this job's `sumble_people` op is terminally
402-folded (an honest attempt from the paywall era). Getting real members now that the founder's
new key returns 200 requires a FRESH Millennium attempt (fresh job → fresh committee operation) —
i.e. a relaunch through the deepagent thread + the founder's approval gate. That is the third
consecutive instance of the retry-after-remediation gap; see the design thread below.

## Full-gate pre-existing failures (recorded 2026-08-20, NOT ours, NOT triaged further)

56 failures on hermetic `make check` (clean env, throwaway `clue_missoula_reproj` DB) are
byte-identical at HEAD `c7d6da82` before either fix: waterfall(7), stage0 recipe0(6), tier
checkpoint(9), lane-E acceptance(6), fi2(4+3), db migrations(3), production-context(4), misc.
Likely environmental to that DB or genuinely pre-existing on the branch after the 08-19 merge day
(yesterday's "green gate 2,855 passed" vs today's 5,327 collected also needs explaining). Founder
directive 05:0x: do not chase failures unrelated to our changes. Whoever next needs a green full
gate should triage these against the default dev DB first.

## The v6 committee relaunch (05:38–05:41 IST) — two new facts

Directive v6 confirmed (founder gate) → fresh job `3cc0a4f2` launched with `sumble_people` in
committee scope, on the fixed fleet. Committee ops are **per-call fresh ids**
(`new_committee_acquisition_operation_id()`, `sumble_entity_research_tools.py:510`) — verified
before sending: four distinct ids across four jobs, zero cross-job replays — so a fresh job
genuinely re-attempts committee (unlike the content-keyed account-gap ops).

1. **Sumble people 402 is CREDIT ECONOMICS, not the key.** The cap-200 sweep reserved **1,709
   provider units** (`committee_acquisition_operation` `cb393d9d…`: reserved 1709, charged 109,
   `sumble_people_provider_rejected_http_402`) against a free tier holding ~500→391 credits. The
   raw 3-credit probe succeeding ≠ the pipeline's 200×(1+attrs) request fitting. ~8.5 units per
   candidate. Every 402'd attempt still charges ~109 units — never retry committee under a cap-200
   directive on the free tier. **Founder decision 05:5x: committee cap 7 for the v7 relaunch.**
2. **New defect (paused `3cc0a4f2` at 05:40:51): raw trigger escape on subset-field re-buy.**
   `enrich_account([core.hq_location])` alone, when an earlier operation (7e29c0bf, cross-job
   window) already acquired employee_count+hq_location: `find_account_gap_operation_for_fields`
   matches by EXACT field-set, misses the owning op, the create path fires the per-field
   window-uniqueness trigger → raw `asyncpg RaiseError: account-gap field already acquired in this
   observation window` → `worker_error:DBAPIError` pause. NOT caused by tonight's two fixes —
   pre-existing trigger, first reachable now that the upstream wedges are gone. Fix lane
   (Opus, in flight): narrow-catch/pre-check → governed recoverable refusal steering the agent to
   read the existing result; trigger stays as backstop; no blanket DBAPIError conversion.

Sequence to finish: fix lands → review/commit → roll fleet → v7 relaunch message (cap 7, founder
approves) → resume `3cc0a4f2` to settle honestly.

## Lane 2 amendment — the admitted case reads the RESULT, not the row (uncommitted, ~07:15)

`15f27702` worked once live and armed the next wedge. Live (job 3cc0a4f2, 06:37:33): eea48931's
resume replayed `7e29c0bf` with no result → served fresh → admitted result `c8be9969` built FROM
the fresh projection. A second job then replays: recompute differs, a result now exists, and
`15f27702` served the STORED row — still the pre-aa88e0b0 draft (append-only, never updated) — so
the span guard killed the job with the 02:14 error again, raw `execution_failed`. **"A result was
admitted for this operation" ≠ "the stored row is what was admitted"**, and after a
never-admitted→fresh settle they diverge permanently.

Ratified rule now in code: **an operation with an admitted result serves the projection its FIRST
ADMITTED RESULT recorded.** Correct in both worlds — an old-code admission recorded the stored
draft (c7d6da82's case, behaviour unchanged), a new-code admission recorded the fresh projection
(tonight's case, and its spans passed the guard at admission, so the replay passes by
construction). No admitted result → fresh, unchanged.

Implementation (`sumble_entity_research_tools.py`): `_operation_result_admitted` is replaced by
`_first_admitted_projection(conn, storage, *, operation_ref)` → `_AdmittedProjection(snapshot_ref,
result)`. It reads the earliest `entity_research_result` for the operation_ref
(`ORDER BY created_at, result_id LIMIT 1`) and reuses the established admitted-result reader
primitives — `read_verified_artifact` + `content_address` vs `result_sha256`, then
`PersistedResearchToolResult.model_validate_json` (the same three-step read as
`EntityResearchResultStore._load_existing`, `read_result`, and the follow-up parent read; none of
those three is callable from a provider action because each enforces the *asker's* job scope, so
the minimal reader lives next to the branch). **Note for anyone re-reading the mandate:**
`entity_research_result_evidence` stores only `evidence_span_sha256`, never the span text, so the
rows alone cannot reconstruct a projection — the digest-pinned result artifact is the content and
the rows are the index. Both are used: every reconstructed span must hash to an evidence row of
that result, and an indexed (`value_ref`) field is rehydrated from the exact `value_artifact_key`
its field row names (same shape as `read_result`'s rehydration). Account branch returns
`result.fields` (plus a fail-closed check that they index the request's exact field set); committee
branch returns `result.discovered_subjects`.

Tests: `_wedge_a_stored_projection` gained a `first_write` action-type parameter; admissions now go
through the REAL `EntityResearchResultStore.persist` (helper `_plant_governed_causation` plants the
causation chain from the request's own ids and returns the observation `persist` admits against).
- NEW `test_the_next_job_replays_the_fresh_projection_its_admitted_result_recorded` — the 06:37:33
  shape. Red on `15f27702` with the literal live error `EntityResearchResultIntegrityError:
  projected evidence span is absent from retained artifact` out of `_validate_fields`.
- UPDATED (was `..._still_replays_its_stored_first_projection`) →
  `test_an_admitted_result_replays_exactly_what_that_result_recorded`, now driven by
  `_LegacyEvidenceRefAccountProjection` (a superseded composition that is *admissible*, so it can
  be admitted through `persist`); asserts the served field is the admitted record and disjoint from
  what today's `_EVIDENCE_NAMESPACE` would mint. Docstring states why the pin moved.
- Committee: the no-result→fresh test stands. The committee ADMITTED path is not covered by a test
  (a committee admission needs a governed `discover_buying_committee` request chain + lineage the
  R5 acceptance suite owns); its only delta from the account path is which collection of the same
  reconstructed result is returned, and that reconstruction is covered in both worlds by the
  account tests.

Verification (throwaway `clue_missoula_reproj`): provenance suite 6 passed; mandated regression
`test_sumble_account_gap_window_reacquisition.py` + `test_sumble_account_gaps_s1.py` +
`test_comprehensive_account_execution_db.py` 24 passed; extra `test_account_entity_research_r5_db`
+ `test_committee_agent_inference_acceptance_db` + `test_entity_research_tools_r4_db` 18 passed;
ruff clean, mypy clean on the source. No commit.

## Design thread this feeds (discussion earlier this session)

Second instance in one night of the missing "fresh attempt after the cause changed" primitive
(first: Sumble 402 folds after the plan upgrade; now: defective draft after a code fix). Ratified
direction: minimal governed supersession (epoch/window bump or non-adoption), NOT the heavy
parent/reason retry-lineage design. Full assessment in the conversation; keep this in mind when
the retry-after-remediation item is next raised.

## Still true regardless of these fixes

- Job `16e846d6` is relaunch-only (Grok encrypted-reasoning checkpoint; OpenRouter 404 on resume).
- Sumble people/tech were 402 until the founder's key change; raw calls now succeed (free tier,
  credits tight: one unbounded tech call cost 47 credits).
- Another session was concurrently active in this workspace (subsystems/clue-design/* edits,
  uncommitted) — do not sweep those files into research-lane commits.
