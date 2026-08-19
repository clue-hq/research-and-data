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
