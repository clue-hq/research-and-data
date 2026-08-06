# M8B V1 — Live account-deep acceptance

- **Parent roadmap:** `M8B-exa-sumble-account-deep-integration-roadmap.md`, Slice V1
- **Run date:** 2026-08-05
- **Branch:** `platform/c8-account-profiling-integration`
- **Status:** **PARTIAL PASS — live Exa, live Sumble, durable wait/wake, snapshot
  materialization, live model inference, verification, detached fleet execution, and zero-provider
  replay are proved. The full conversational O3 entry and promoted-output gate remain open.**

This record supersedes the earlier credential-blocked attempt. A successful HTTP response or green
test suite is not counted as live acceptance by itself; the evidence below is the persisted
operation, snapshot, receipt, claim, checkpoint, task, and replay state produced by real endpoints.

## 1. Correct synthetic input boundary

The source database was `clue_d6_acceptance_20260803`. It contains the synthetic Stage-0/Client-KB,
ICP, and sealed account-discovery handoff—not precomputed account profiles or committees. Its
discovery list is:

| Account | Domain |
|---|---|
| Michigan Head and Spine Institute | `mhsi.com` |
| New Jersey Brain and Spine | `njbrainspine.com` |

The source seal is generation 1, contains exactly those two account ids, and has SHA-256
`08de49006f1c352762d44acffc5c3136a066ab7afcdaa80df6a578f056bd8625`. The live fixture added the
minimum deep-run governance state and selected New Jersey Brain and Spine; it did not seed Exa
claims, Sumble committee snapshots, contacts, roles, or provider receipts.

## 2. Live provider acquisition

### 2.1 Exa Search Deep-Reasoning

- One real `POST /search` used `type="deep-reasoning"`, `numResults=50`, and one closed structured
  bundle for `account.operational_pain` and `account.strategic_moves`.
- Durable operation `ef813fa2-feb9-49a1-ad64-23caaf0ec5cb` is `ready`, with provider request id
  `deb08be7dcfe7393f52099ee69bcc280` and exactly one attempt.
- The immutable request, response, normalization, receipt, and 13 result artifacts are retained.
- Provider-reported and settled cost are both USD 0.018 (1.800 cents). No duplicate operation or
  settlement appeared during fleet replay.
- E2 materialized two target-locked, cited, artifact-backed tier-4 account claims. Verification
  correctly left `operational_pain` flagged (`partial`) and rejected `strategic_moves`
  (`unsupported`) rather than promoting weak evidence.

### 2.2 Sumble Teams and People

- The selected account first had a real S1 Organizations/Jobs identity operation; S2 then passed
  the complete eligibility gate for exact account, seal, tier, directive, policy, and budget.
- Durable S2 operation `2a15b718-61f9-4db2-9665-a6e92eaad87f` is `ready` and charged exactly 63
  credits: Teams 15, People submit 0, People successful poll 48.
- The three immutable attempts preserve the Teams response, pending People response, successful
  People response, provider request id, two ready snapshots, and one receipt manifest.
- Actual live request artifacts prove a one-team/six-person bound. People selected only name,
  LinkedIn URL, title, function, level, location, country, and current employer. Teams related
  people used the same professional identity fields. Neither request selected email, phone,
  `"all"`, or a reveal operation.
- Six contacts were admitted under the exact account, all six with LinkedIn identity and none with
  verified email. Six role and six persona claims were produced by live model inference; no
  contact-facet profiling or reveal occurred because the confirmed directive disabled it.
- S2 now pins the current v9 OpenAPI digest already reviewed by S1,
  `c6f1324366a94844932ee3522caee6aa9f428f7d958a9956bea3425d18e2811c`. Re-review confirmed that
  the bounded `/v9/teams` and `/v9/people` subset used here remains present. Historical operation
  metadata remains immutable and retains its originally persisted digest.

## 3. Durable wait, fleet, and live-model proof

The first live pass exposed a missing production wake path after the People operation entered
`waiting_external`. The implementation now has a durable due-operation query and
`SumbleCommitteeWakeWorker`; the fleet polls due work and re-enqueues the owning project run. A
pending People operation therefore resumes the same account run and operation without a second
submit.

The detached production fleet was then exercised in a fresh database clone with the stored live
provider snapshots:

- `drive_run` completed after three durable attempts and `account_job` completed once;
- the account run is `done / contacts_complete` with 2 account references, 18 committee references,
  and 6 committee-contact references;
- live OpenRouter traffic used `openai/gpt-5.6-terra` for six role-inference calls and fourteen
  verification judgments (two account plus twelve role/persona claims);
- DEEP committed with one processed account and zero failures;
- VERIFICATION committed with one processed account and zero failures;
- REVIEW opened one session and left the project deliberately `review / paused`, which is the
  expected human-review boundary rather than a worker failure.

The verification outcome is intentionally conservative: the two Exa claims are flagged/rejected,
and the role/persona hypotheses are flagged/rejected rather than silently promoted from titles
alone. This proves the verification plumbing but does not yet satisfy a promoted-output quality
gate.

## 4. Defects found and corrected by the live run

1. **No provider wake after Sumble pending:** added durable due-work selection, fleet wake worker,
   and typed setting/binding.
2. **Committee role model absent in production composition:** the run driver now binds the
   deployment synthesis model; a ready Sumble snapshot no longer fails at role materialization.
3. **Directive candidate cap exceeded by combined People and Teams rows:** the snapshot source now
   caps the combined candidates by the stricter directive/provider limit.
4. **Contact-profiling prohibition ignored:** the effective directive privacy policy is now carried
   on `AccountSpec`; the orchestrator skips contact fan-out when disabled while retaining committee
   identities and claims.
5. **New contacts invisible to pre-spend role gates:** the gate now supports transaction rebinding,
   so contact admission, gate receipt, model call, and committee claim writes share the short
   committee transaction instead of rejecting every new contact through a second connection.
6. **S2 contract digest lagged S1:** S2 now uses the current reviewed v9 digest and a regression
   asserts both Sumble lanes share the same accepted contract.

Each correction has a focused regression test. None introduces a Sumble-specific branch into
`AccountDeepOrchestrator`.

## 5. Replay and database evidence

The original live-acquisition database and the fresh-process fleet replay clone have identical paid
provider state:

| Surface | Original live DB | Fleet replay DB |
|---|---:|---:|
| Exa operations / attempts | 1 / 1 | 1 / 1 |
| Exa settled cents | 1.800 | 1.800 |
| Sumble S2 operations / attempts | 1 / 3 | 1 / 3 |
| Sumble charged credits | 63 | 63 |

There was no second Exa request, Sumble Teams request, People submit, People poll, provider receipt,
or provider charge. All inspected request/response/normalization/receipt artifact references resolve
to non-empty content whose SHA-256 matches the artifact ledger. The deep selection seal remained
generation 1 with the selected account unchanged.

## 6. Verification rerun

- Complete repository suite: **3,332 passed, 23 expected skips, 0 failures** on a newly created,
  empty, migrated acceptance database.
- Focused S2/O2/orchestrator regression after the digest correction: pass.
- V0 fresh-process database harness: pass, including `head -> base -> head`, concurrent launch, and
  forbidden-transport replay.
- Alembic: one head, `a83e52bebc7c`.
- Mypy: 516 source files, no issues.
- Import-linter: 24 contracts kept, 0 broken.
- Ruff: all implementation-owned changed Python files pass.

## 7. Remaining V1 release conditions

The account-deep orchestrator and detached fleet are now live-proven. The umbrella V1 gate remains
open for three narrower reasons:

1. the live run began from the already confirmed durable directive/launch and did not execute a
   user-facing Head-of-ABM O3 conversation that drafts, confirms, and invokes the launch through one
   production-composed turn surface;
2. the canary produced honest flagged/rejected evidence, not a promoted account profile or promoted
   role/persona claim set suitable for handoff; and
3. Sumble money conversion and OpenRouter per-model prices were configured as zero. Exact Sumble
   credits and Exa dollars are durable, but an honest combined monetary total is therefore absent.

Closing V1 requires one bounded conversational launch with a configured pricing policy and at least
one claim that survives verification, followed by the same zero-provider replay check. These are
not failures of the detached account-deep orchestration run recorded above; they are the remaining
full-product entry, output-quality, and accounting gates.
