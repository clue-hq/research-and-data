# Zafran quality-flow live verification — September 23

Status: both attempts settled; corrected continuation ended `needs_review` at 02:28 UTC.
All ten workers stopped cleanly. End-to-end quality acceptance is not granted.

The founder authorized fresh end-to-end Zafran research after the paid-test pause, then requested
five more workers with concurrency at least three. The fleet expanded from five to ten actual
processes, each with concurrency three. This does not change provider pacing or create parallel
initial account jobs. Person jobs follow the account unit's release.

## Inputs and isolation

- Internal quality profile v4, resources revision five; shared launch default remains v2.
- Real launch, queue, leases, agents, model gateway, providers, claim store and contextual page
  composition; configured model roles unchanged. No PoC target facts seed either attempt.
- Isolated Postgres on local port 59274. First database: `clue_zafran_quality_20260923`.
  Corrected fresh database: `clue_zafran_quality_retry_20260923`. Separate workspace and blob roots.
- Private originals, receipts, logs, snapshots and scripts live under
  `.artifacts/arv4-zafran-live-20260923/` and `.artifacts/arv4-zafran-retry-20260923/`.
- Both use the retained sanitized ICP/persona documents from the earlier v3 experiment. The
  importer explicitly pairs their lineage and supplies a retained sourced seller product brief.
  These disclosed input repairs mean comparison against historical v3 is not architecture-only.
- Identical approved research inputs produce the same deterministic research run ID in separate
  databases: `873d9115-297a-5b69-b7e3-9367acfface3`. Distinguish attempts by database, experiment
  path and actual trace IDs. Failed terminal jobs retain their history. The explicit founder-authorized
  allowance reset below is separately audited; it does not erase prior usage or claims.

## First-attempt failures and corrections

The first account unit failed during parallel claim writes; no account/contact narrative page
was published. Person attempts then exposed recoverable tool-argument failures. Two remaining
person jobs were suspended while draining the fleet. Original evidence and failure history remain
available; this attempt is not a completed research result.

| Failure | Correction in `99f51f511` | Focused verification |
| --- | --- | --- |
| Shared source readers upgraded artifact retention locks and deadlocked | Retention uses a compatible shared lock that still excludes erasure | Three concurrent readers retain one original; retained evidence cannot be erased as unreferenced |
| Claim-next returned multiple tasks under concurrency | Materialized single candidate before update | Thirty concurrent claimers receive ninety distinct tasks over three waves |
| Separate slots of one worker reacquired an active work lease | Guard active work IDs within the worker; retain durable cross-process leases | Same-work second slot requeues; later work proceeds after release |
| Invalid acquisition arguments/subject operations consumed infrastructure failure budget | Durable typed refusals before provider dispatch; authority checks remain hard failures | Invalid calls and replay buy no transport; specialist acquisition remains forbidden |

All 59 storage/fleet/acquisition tests and 16 quality claim/evidence/execution/driver/correction
tests passed on a separate disposable regression database. Changed-file Ruff and diff checks passed.
These are offline regression proofs, not live acceptance.

## Observation and comparison requirements

Preserve the complete Exa report, provider originals, transcripts, assessments, correction history,
source dispositions, committee state and platform-generated pages. Compare with the saved Zafran
PoC and September 22 v3 findings, distinguishing dated source differences from extraction loss.
Same-field matching is diagnostic; it is not an accuracy score or a measure of the whole dossier.

The initial oversized Langfuse trace exceeded the full-trace API's 100 MB response limit. Its
observations were exported through the documented paginated API; original local model/event logs
and artifacts remain retained. First export joins 203 of 204 model observation receipts. Do not
claim complete cloud delivery until the remaining observation is verified. Reference:
[Langfuse observation pagination](https://langfuse.com/docs/api-and-data-platform/features/observations-api).

Avoidable evidence-read argument retries and growing model contexts remain latency observations
to assess in the corrected run. Thirty fleet slots do not remove sequential account work, shared
provider pacing, model latency, or dependency waits.


## Resuming the corrected attempt

Two further integration defects were fixed without buying a third fresh account report:

- `0d70895de`: a delegation that names virtual `/research` views as files now receives actionable
  feedback. Specialists already have authorized views; physical copying these paths previously
  killed the account unit. Three focused delegation tests passed. Two unrelated Stage-0
  expectations in the broad runtime module also failed against the unchanged pre-fix module.
- `a5855d6f8`: virtual evidence/research views honor native Deep Agents line pagination. Previously,
  ordinary `read_file(limit=100)` calls often returned no data and nonzero offsets were refused.
  Six focused tests passed, including the real framework read tool and revocation during pagination.

On September 23 at 01:57 UTC the founder explicitly requested resetting the current run and
increasing its turn allowance to 200, then continuing it. Ten workers checkpointed cleanly before
this operator action. Durable run-event sequence **1883** records before/after counters for all six
jobs, with the original model/provider/activity/finalization ledgers preserved. Each job has a fresh
shared allowance of 200 model dispatches, 10,000 tool calls, 200 delegations and a 30-minute runtime
window. This is an isolated experiment amendment, not an unrecorded crash-recovery reset.
Manual-refresh revision 92 schedules another account continuation while person checkpoints resume.

`47b3106a3` supports this requested allowance across the runtime, execution policy and trusted
specialist bindings. The former hard ceiling was 128. Other agents retain their profile defaults;
only the isolated harness sets 200. Ten focused execution/specialist/allowance tests passed.
All ten processes started with concurrency three and effective limit 200; new calls were verified
for the account and each of the five people.

At 02:00 UTC the run remained provisional: 93 stored claims and no published narrative pages.
The initial account failure remains in history. New research-derived claim assessments are now
being written, but end-to-end output and quality acceptance remain outstanding. Model contexts
have reached 195,138 input tokens; repeated evidence/catalog navigation remains a measured
latency and cost concern. Final accounting must include the costs before and after the reset.


## Settled outcome after the 200-turn continuation

The six jobs and final generation are `needs_review` (input/reconciled revision 137). The 200-call
ceiling was effective: account/Nick/Tom consumed 127/107/118 model calls after the reset. Nick and
the later account continuation reached the separate 30-minute runtime boundary; earlier specialist
failures also include absent required output files, failed delegation and missing finalization.
More turns alone did not fix those contracts. No subsequent paid retry was launched.

| Final measured item | Result |
| --- | --- |
| Raw claims | 129: 104 supported, 19 qualified, 5 unresolved, 1 invalid |
| Ordinary factual-reader claims | 104; all 129 remain in the audit appendix |
| Account claims | 56; exact + partial PoC field overlap 23/67, versus 27/67 in historical v3 |
| Published pages | Four contacts: Vari, Sanaz, Ben, Tom |
| Missing pages | Account overview, account insights, Nick contact |
| Employment assessments | Zero accepted; 49 relationship-assessment refusals |
| Effective corrections | One withdrawal; audit history preserved |
| Sources | 69 provider records, 282 web snapshots, 4 research reports, 5 gaps, 1 transcript |
| Model receipts | 1,031; recorded USD 62.401836 |
| Provider result receipts | 78; separately recorded USD 0.272668 and 35.1 AI Ark credits |
| Unpriced provider USD outcomes | One; receipt totals are not a complete invoice |
| Artifact integrity | All 6,800 retained artifacts passed size/hash verification |
| Cloud model-observation join | 1,031/1,031 joined by exact recorded observation ID |

The cloud export uses paginated observations, excluding IO/prompt field groups; original local
model/event logs and durable artifacts retain those bodies. A successful model-observation join
is not a claim that every ancillary span was exported. Export timeouts were observed during the
run; final model receipts were nevertheless all recoverable. A 42 MB private database backup and
both live databases are retained. Workers exited zero; the read-only monitor stopped.

### Quality implications

- Acquisition remains substantial: the unchanged account Exa report is 17,422 characters, and
  AI Ark autonomously selected all five historical comparison people. The full report's presence
  does not mean all its findings were converted into claims after the initial account failure.
- The relationship catalog hides nested/enum constraints later enforced by the writer; generic
  refusals cause expensive guessing. Zero accepted employment assessments prevent reconciliation.
- Vari's published page demonstrates an overbroad presentation consequence: it withholds even
  title/career/operational findings while membership is candidate. Blocking outreach is effective;
  the resulting gap-only profile is not the desired useful qualified research output.
- Person narrative work attempted account-owned value-narrative writes and was refused. No value
  narrative claim was accepted. Several specialists also failed at finalization; missing files
  currently become hard runtime failures instead of a successful durable partial handoff.
- Native source navigation and large contexts consume many turns. Extra workers do not reduce
  these sequential loops. Reconciliation of an aborted initial account task needs to explicitly
  recover unfinished report extraction, not only reassess committee membership.

Private deliverables, under `.artifacts/arv4-zafran-retry-20260923/`:
`ZAFRAN-RESEARCH.md`, `COMPARISON.md`, `EXA-ACCOUNT-REPORT.txt`,
`CLAIM-EVIDENCE-APPENDIX.md`, `snapshots/`, `trace-model-join-final.json`,
`tool-activity-audit.json`, `allowance-reset-200.json` and `final-database.dump`.
These artifacts expose the incomplete result; they do not substitute a manually rewritten dossier
for the platform output. Q23 matched comparison and Q24 quality acceptance remain unfulfilled.
