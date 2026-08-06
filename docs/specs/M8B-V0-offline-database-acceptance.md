# M8B V0 — Offline and database acceptance

- **Parent roadmap:** `M8B-exa-sumble-account-deep-integration-roadmap.md`, Slice V0
- **Executable matrix:** `tests/fixtures/account_deep/v0_fault_matrix.json`
- **Recorded:** 2026-08-04
- **Status:** accepted mechanically with recorded provider fixtures; no live provider call made

V0 proves that the composed Exa Deep and Sumble account-deep capability remains governed,
durable, inspectable, and replay-safe under faults. Provider HTTP is replaced only at the external
transport boundary. The tests retain the real Postgres stores, migrations, filesystem artifact
store, claims, verification gates, identity/target-lock logic, operation receipts, run projections,
and account-deep composition.

V0 does not prove live credentials, provider entitlement, current production response behavior,
or successful paid traffic. Those remain the separately authorized V1 canaries.

## 1. Production correction found by the matrix

The pre-V0 Sumble coordinator normalized team/person rows before durably recording the raw response.
A syntactically valid, charged provider response containing an unknown or drifted row could fail the
normalizer first. The operation was quarantined as spend-unknown, but its raw response artifact,
reported credits, provider request id, and observed minimum cost were absent. That violated the
evidence and settlement boundary for the exact failure case V0 was intended to exercise.

The coordinator now uses two durable steps:

1. capture and subject-bind the immutable raw response, then terminally update the attempt with
   provider id, status, credits, remaining balance, and response artifact;
2. revalidate and normalize that stored response before folding it into the mutable source
   snapshot.

If the process dies between those steps, a new process reads and hash-verifies the stored response,
revalidates provider/request identity, reruns normalization, and folds it without another provider
call. If normalization or recovery fails, the snapshot and operation become terminal
`spend_outcome_unknown`, preserve the response evidence and known charge, and never retry. A death
before dispatch remains safely resumable; a death after possible dispatch but before a recorded
response remains quarantined.

## 2. Frozen fault matrix

The JSON manifest is an executable coverage inventory: its companion test requires the complete V0
case-id set, unique ids, existing test files, and real test functions. The behavioral tests—not the
manifest—are the acceptance authority.

| V0 requirement | Executable evidence |
|---|---|
| Every S2 eligibility condition false | Parameterized real-DB gate test independently rejects sealed-batch membership, Pass A, must-haves, human tier approval, committee plan, personal-data permission, jurisdiction, use class, identity acquisition, budget, and fresh-snapshot conditions before a paid operation exists |
| Duplicate/concurrent launch | Two separate child processes race the exact immutable O2 launch and both replay its one durable id and request digest |
| Crash matrix | Explicit tests cover before dispatch, after possible dispatch, committed response before snapshot fold, ready snapshot before snapshot-only materialization, and claim write before reference/cost fold |
| People lifecycle | Recorded Teams/People fixtures cover pending, running, succeeded, failed, repeated successful poll, exact credit/cost settlement, and terminal zero-call replay |
| Exa failure matrix | Frozen A0/E0/E1 tests cover absent grounding, additive response members, timeout, hard 4xx, 429, 5xx, malformed success, and active-dispatch spend-unknown quarantine |
| Charged Sumble schema drift | A charged response with a malformed team row retains the verified raw response, provider status/id, 12 credits, six-cent observed cost, terminal quarantine, and zero-call replay |
| Freshness and contradiction | E2/S2D tests reject stale snapshots and reuse fresh ones; the S1 real-DB conflict case preserves both disagreeing sources and replays without acquisition |
| Identity drift/collision | Cross-account Exa snapshots fail closed; same-name contact evidence is born weak and remains unpromotable |
| Governance rejection | Budget, jurisdiction, personal-data, identity-acquisition, and professional-public use-class denials create no paid operation |
| DSAR | Account-subject artifacts enumerate, tombstone, and remain absent after terminal replay; replay never resurrects a subject edge |
| Fresh-process replay/inspection | A disposable migrated database is seeded in one process, launched concurrently in two more, then replayed and inspected in a final process whose transport throws on every method |

## 3. Fresh-process database acceptance

`test_v0_fresh_process_replay_inspects_complete_durable_state` owns a regex-bounded disposable
database. Before seeding it runs `upgrade head -> downgrade base -> upgrade head`. It then:

1. creates one exact O2 launch and an eligible, sealed account;
2. runs the real S2D gate and recorded Teams/People lifecycle to a ready snapshot;
3. materializes the snapshot through `SumbleCommitteeSource` and the existing provider-neutral
   committee worker;
4. writes three committee claims and folds claim/operation/snapshot/receipt references into the
   account-run projection;
5. hash-verifies every live account artifact through the production artifact reader;
6. races two new processes against the immutable launch; and
7. starts another new process with a forbidden transport, proves zero provider calls, and compares
   every stable durable value with the seed-process report.

The inspection report asserts one ready operation, four attempts, 28 credits, 14 cents, one receipt,
three live claims, eligibility and pre-spend decisions, at least eight verified artifacts, the
`committee_discovered` account-run projection, all folded run references, and one immutable launch
digest.

## 4. Exit-gate evidence

The focused new V0 set passes 31 tests. The complete frozen V0 matrix passes 110 tests. Canonical
mypy passes all 515 configured source files; import-linter keeps all 24 dependency contracts; Ruff
passes over every tracked Python file; Alembic reports the single `a83e52bebc7c` head; and the
fresh-process acceptance performs the isolated migration round trip described above. The complete
suite passes on an untouched disposable database: 3,337 passed and 11 skipped. The only warning is
the existing Starlette `httpx` compatibility deprecation from the installed test client.

The local worktree contains user-owned, untracked `.claude/` and `.codex/` skill copies whose
command-line scripts intentionally print. They are not repository files and are excluded from the
tracked-file Ruff assertion; V0 neither edits nor commits them.

## 5. Remaining release boundary

V0 closes recorded-fixture and database acceptance only. V1 still requires separate explicit
authorization and hard caps for successful Exa Deep, Sumble Teams/People, combined account-deep,
and zero-spend fresh-process live canaries. Contact email/phone reveal remains outside both this
slice and the first account-deep release.
