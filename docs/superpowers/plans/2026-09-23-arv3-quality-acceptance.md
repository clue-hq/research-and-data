# Research quality implementation and acceptance record

**Status, September 23:** Q1–Q7 implemented and checkpointed locally; Q8's offline verification is
recorded below, with limitations. Paid model/provider comparison, fresh live research, authenticated production
browser acceptance and default-profile promotion have **not** run. The founder explicitly requested
the pause before paid testing. No historical catalog/claim repair or remote publication is included.

Canonical scope: [implementation plan](2026-09-22-arv3-research-quality.md) and
[approved design](../specs/2026-09-22-arv3-research-quality-design.md).

## Delivered behavior and ownership

- A research generation pins the project's exact brand or project ICP/persona variant, selected
  products, seller-document bytes and catalog. Missing/incompatible context is a gap; the configured
  generic ABM pitch cannot substitute for the selected seller's product evidence.
- Complete reports, pages, provider records and transcripts persist as originals in the existing
  artifact substrate, with scoped descriptors/grants and selective bounded reading. Queue and
  delegation messages carry references. Postgres remains authoritative; worker files are views.
- Typed claim proposals, assessments, withdrawal/correction and support lineage share one write
  contract. Invalid observations remain auditable and disappear from ordinary factual reads.
  Semantic assessments are explicit judgments, not a deterministic guarantee of factual truth.
- The governed account Deep Agent delegates claim and narrative work in its leased slot. Person
  jobs run separately; parents release capacity while waiting. Model/tool/delegation/runtime
  allowances accumulate across children, retries and continuations. Old jobs keep their pins.
- AI Ark SMART discovery remains first, with exact company identity, saved-profile reuse and
  independent email/phone enrichment. Web nominations cover documented discovery gaps through the
  same provisional-member/person-job contract. Identity, employment and buying remit are separate.
  Geographic relevance is reasoned per organization, including local namesakes and distributed remit.
- Child results and corrections drive durable account reconciliation. Unsupported employment
  immediately prevents an established buying role/outreach. Independent person generations also
  retain refreshable scoped pages.
- The narrative specialist owns new-profile pages and two-sided seller arguments. It replaces Luna
  for those generations. Distinct project/context/generation identities prevent page mixing; stale
  drafts are refused and invalid supported text is suppressed before refresh.
- Transcript/version/speaker/timing qualifications and hiring dates survive through claims/pages.
  Invalid-reference retries are cheap durable refusals. Coverage comes from saved activity and
  current outputs, not the agent's self-reported success.
- Agent tasks/results/workspace files/tool parameters inherit evidence privacy lineage. Revoked or
  erased originals cannot be resurrected through derived artifacts. Unpriced calls remain explicit.

## Local checkpoints and profile boundary

| Commit | Coherent checkpoint |
| --- | --- |
| `5f1658b7d` | Exact context and neutral field-registration foundations |
| `6eb163c5e` | Durable originals and scoped evidence access |
| `9c0261beb` | Claim assessment, correction and applicable-read contracts |
| `df73e4a2e` | Shared accumulated execution bounds |
| `a4950b435` | Governed evidence/claim tools and views |
| `ac347a887` | Parent/specialist runtime and deterministic provider mappings |
| `69b4c213e` | Launch, fleet, membership and reconciliation |
| `6541ecc6d` | Contextual narratives, pages and frontend seam |
| `82eb90faf` | Media/hiring qualification and measured coverage |
| `2ae21f6e2` | Privacy lineage and independent-contact lifecycle closure |
| `3584f8d1b` | Final membership presentation, continuation trace context and load harness |

The internal composition is `v4`, immutable quality resources revision 5. Revisions 2–4 remain
replayable. Public runtime settings still admit v1/v2/v3 and default to **v2**; this work does not
quietly select v4 for new user launches. Quality model settings use the consolidated role settings.
No additional provider/vector service was introduced. Migration head: `16bfa50620f4` (one head).

## Offline acceptance matrix

“Offline contract passed” means the real database/storage/runtime/read behavior was exercised with
scripted decisions. It does not claim that a live model will make every semantic judgment correctly.
Paths below are repository-relative test entry points.

| Cases | Proof and state |
| --- | --- |
| Q01–Q04 | Offline contract passed: `tests/arv2/test_quality_context_db.py`; exact bytes, project variants, specialization/ambiguity and confirmation-vs-content lineage. Driver checks the actual context delivered to its model factory. |
| Q05 | Offline contract passed: `test_quality_pages_db.py`, `test_quality_runtime_db.py`; exact seller passages and target support produce governed narratives/pages. Real clinical model quality awaits Q23/Q24. |
| Q06–Q07 | Offline contract passed: `test_quality_evidence_db.py`, `test_quality_workspace_db.py`, `test_quality_claims_db.py`; full report beyond excerpts, bounded reads/continuations, forged span/pointer/context rejection and replay. |
| Q08 | Integrity/assessment contract passed: joined quotes and supplied semantic invalidity are excluded. Whether a live specialist detects every NPI/accreditation or relationship mistake remains a Q23 measurement. |
| Q09–Q10 | Offline contract passed: `tests/claimstore/test_quality.py`, quality tools/pages; concurrent correction, replay, withdrawal without a replacement, crash-window invalidation and immediate current-read changes. |
| Q11 | Offline contract passed: `test_quality_provider_db.py`; repeated company mapping returns the same claims without another provider purchase. |
| Q12–Q13 | Offline contract passed: `test_quality_relationships_db.py`, nomination and page tests; local/remote/global scopes, employment conflict, safe membership before refresh. Synthetic browser confirmed Candidate/Unverified and no opener. |
| Q14 | Offline contract passed: `test_quality_generation_db.py`, execution/driver tests and leased-fleet load; late/duplicate results, privacy stops, durable revision reconciliation and unchanged initial-job history. |
| Q15–Q16 | Offline contract passed: two projects retain separate pages; stale publish refused; corrected text immediately suppressed while safe content stays visible. Verified through real read API and actual UI components. |
| Q17 | Offline contract passed: `test_quality_media_db.py`; typed segment/version support, attributed/unverified speakers, qualifications and repair invalidation. No new live transcript-quality claim. |
| Q18 | Offline contract passed: hiring/provider/page checks distinguish elapsed closing, unknown and open; closed/undated hiring cannot be ordinary current-urgency prose. |
| Q19 | Offline contract passed: repeated invalid transcript reads and provider refusals retain typed recovery results without transport. |
| Q20 | See the measured load record below. This is deterministic capacity/recovery proof, not provider throughput. |
| Q21 | Offline contract passed: real filesystem and local MinIO S3, missing blob/outage, reconstructed grants, revocation, erased source and derived finalization/tool-input artifacts. |
| Q22 | Durable local joins/cost/refusal contracts passed; continuation payload now carries run/job/project/account IDs. External exporter/paid-provider trace completeness still awaits the live gate. |
| Q23 | Prepared, not executed: [frozen-source comparison protocol](2026-09-23-arv3-quality-frozen-comparison.md). Paused before paid model calls. |
| Q24 | Not executed. Fresh Premier/Probook/Zafran, authenticated browser and stranger-account generalization remain outstanding. |

## Measured load and storage

All load evidence is synthetic and private under `.runtime/quality-load-*`. The command is
`python -m tests.arv2.quality_load_harness --output <private-directory> --accounts 50 --workers 5
--concurrency 3`, against a newly created database whose name starts `clue_arv3_quality_load_`.
The harness refuses other database names and provider factories raise if called.

The capacity-one run completed four accounts across two workspaces/four projects, eight detached
people and all sixteen pages in **67.683 seconds**. Maximum active research units: **1**. All
generations reconciled, no failed agent units, twelve cross-workspace reads refused, zero provider
ledger calls. Recorded artifacts: 5,161,732 bytes; process peak RSS: 338,247,680 bytes.

The first 100-account attempt exposed two harness problems rather than silently receiving a pass:
five logical workers shared a single handler's default four-unit cap, and the scripted narrative
ignored correct stale-publication refusals. All 300 jobs terminated and all generations reconciled,
but only 382/400 pages existed. The page assertion correctly failed. The revised harness uses the
aggregate fifteen-unit capacity and follows the specialist's bounded reread/revise/retry contract.
The final run completed **100 accounts, 200 people and all 400 current pages**, across two workspaces
and four projects, using five logical workers with three slots each. Every generation reconciled;
all 519 fleet tasks drained and all 978 governed agent executions finalized successfully. Person
jobs intentionally ended `needs_review` for fixture evidence gaps; none were passed off as verified
contacts. All 20 reconstructed cross-workspace evidence reads were refused.

The fleet ran from 02:47:09 to 02:55:39 IST (approximately **8 minutes 30 seconds**, rounded log
timestamps), including a cold worker replacement at 02:47:52. Each project completed 25 account and
50 person jobs. Initial account-job start-delay medians were 71.29/71.93 seconds for the two tenants,
with p95 168.67/169.88 seconds; person medians were 180.44/179.35 seconds, p95 190.10/195.01 seconds.
These measure enqueue-to-first-job-start, not per-attempt queue latency or guaranteed fairness.

All 4,738 scripted model calls joined their research execution, all 300 proposals joined their job,
and all 3,868 retained display blocks joined their writer. Model receipts remain explicitly
**unpriced**; zero provider ledger calls were made. Artifact footprint: **140,947,275 bytes**.
Largest fleet payload: **376 bytes**, containing only approved references/trace context.

After the workload completed, the metrics collector queried `payload` instead of `payload_json`.
The process exited before saving its final report. The collector is fixed, its database assertions
were rerun against the completed database, and process metrics now save before report collection.
No research workload was rerun for this repair. Final process peak RSS and the in-memory maximum
active-unit counter were not retained: they are **unavailable**, not zero. Durable model intervals
show seven overlapping scripted calls; that is not equivalent to active research units. Execution
and finalization timestamps are not a reliable substitute for that counter. The earlier four-slot
100-account attempt recorded 351,535,104 bytes peak RSS; it is not a fifteen-slot memory result.

Recovered results: `.runtime/quality-load-final-100/recovered-report.json`; scope/join audit:
`.runtime/quality-acceptance/load-audit.json`; access proof: `load-isolation.json`. A private dump of
the completed synthetic database is retained as `final-load-database.dump` before service cleanup.

Limitations: logical workers share one Python process, each with real independent leases/slots;
this does not prove multiprocess provider saturation. Cold recovery deliberately discards warm
model/workspace state at committed unit boundaries; interruption/crash windows have separate
runtime/transaction tests. Fixture sources are small. RSS/artifact bytes are observed footprints,
not a capacity guarantee for fifty long customer transcripts. Actual model quality is not measured.

Storage was exercised against both filesystem and a task-owned, volume-free MinIO container. The
full migration chain upgraded, downgraded and upgraded a clean throwaway database; exactly one head
was verified. Initial parallel migrations exhausted a shared local server's lock table, so subsequent
load and regression work used a dedicated task-owned Postgres container. No shared server settings
were changed. Failed setup attempts are not counted as acceptance.

## Browser and frontend

Synthetic preview: `http://127.0.0.1:59273/quality-proof`, actual read API on `127.0.0.1:59272`;
dedicated database `clue_arv3_quality_browser_20260923`. The preview copied the real frontend sources
into `.runtime/quality-browser/frontend`, injected the real read API into existing repositories,
and rendered actual schemas/components. It did not disturb the user's running application.
Private exact workspace/project/account/contact/context handles: `.runtime/quality-browser/handles.json`.

Verified in the browser:

- Exact citation popup included the synthetic original quote and source link.
- Account/contact/Insights links retained project and context IDs.
- Candidate status and human-readable employment gap were visible; no established champion was
  asserted. Influence rendered **Unverified**, not the legacy default Medium.
- Openers showed the evidence gap rather than outreach for the provisional person.
- Withdrawing the synthetic claim through the real assessment store removed its statement from
  the next account read **before** any narrative refresh and showed Updated synthesis pending.

This is component/repository/API browser proof. It does not cover Clerk login, the full authenticated
application shell or real customer reports; those belong to Q24. Browser findings fixed internal
reason-code/duplicate gap copy and default influence on unverified membership. API/field tables and
the checked-in Zod shape snapshot were amended together.

Frontend: 179 account tests passed; token generation, lint and production build passed. Lint retains
two pre-existing unused design-editor helper warnings. No new frontend type/build failure remains.

## Regression and repository gates

- Combined affected run: **2,041 passed, 30 skipped**, with 29 failures/one setup error investigated.
  Live fixture modules were subsequently excluded as modules, in addition to the initial
  `live_secrets`/marker exclusion; their external sockets were blocked throughout.
- Fixed final-contract failures: legacy no-SQL failure fixtures now supply the measured spend
  reader; unknown-version test no longer treats registered v4 as invalid; import guard explicitly
  admits only the approved shared narrative/compliance/platform seams and still rejects legacy
  narrative orchestration. Final driver/read/schema guard run: **155 passed**.
- Final contextual page cases: **3 passed**. Focused earlier checkpoints include **103** runtime/
  workspace/page/lifecycle passes, **10** privacy/storage edge passes and **38** media/hiring/runtime
  passes. These overlap; they are not added into an invented unique total.
- Changed production typing: **32 files passed**. Final changed-file formatting/lint and whitespace
  checks passed. All **28** package dependency contracts passed.
- Full default offline run: **4,678 passed, 3,415 skipped**, 35 failed/one setup error before the
  targeted repairs. This is recorded honestly; the entire repository is **not** claimed green.
- Reproduced on archived pre-implementation base `a14ccbee0` with its own migrated disposable DB:
  two old agent-runtime assertions; two recipe-19 promotion fixtures; three C7 query ceilings
  (33 vs 31); extractor composition; reference-image runner fixture; old product-tool visibility;
  HTTPX span-install test; and the separate R5 fixture's missing `updated_at` projection.
- Five remaining suspicious cases passed on the current migrated disposable DB with explicit
  verification settings. Their earlier failures involved an unmigrated default database or the
  local verification-disabled setting. Broad Langfuse callback tests also exhibited shared-state
  ordering behavior; focused archived cases pass. No live Langfuse acceptance is claimed.
- Existing root gate failures were checked against the base: format/import issues in
  `frontend_read/project_memory.py`, its DB test, and `projections_app.py`; typing in
  `design_leg_wiring.py`; the workspace-rename guard flags existing Brandfetch `client_id` names.
  These unrelated files were not modified to manufacture a green global gate.

Detailed raw logs remain private under `/private/tmp/quality-*`; final evidence copies/digests are
retained under `.runtime/quality-acceptance/`. No provider tokens or customer source bodies belong
in tracked acceptance files.

The preview API/frontend and task-owned Postgres/MinIO services are stopped at closeout. Evidence
and synthetic artifacts remain local for inspection; no test service needs to remain running.

## Frozen evidence and catalog review

The private frozen inventory covers 1,830 retained files; see the Q23 protocol for its digest and
comparison arms. The historical Premier catalog dry run inspected **83 fields**, flagging **25**
for review due to source-specific wording or named subjects/observed values. Examples include
patient-portal technology, ASC partnership detail and an observed ATS count. This is a conservative
review inventory, not a proven count of erroneous definitions. It is scoped to retained evidence,
not a full live global-database audit. No field or historical claim was repaired automatically.
Input digest and individual candidates are in `.runtime/quality-acceptance/catalog-dry-run.json`.

## Remaining boundary

Resume only on the founder's instruction: execute matched Q23 model calls, inspect semantic quality,
then run Q24 fresh research and the authenticated application. Record actual provider quotas,
attempts, unknown costs and trace joins; review false assertions and missed useful findings
separately. Only after that review consider promoting the new profile. Preserve prior pins and
roll back future launches via the selector, never by erasing correction/privacy history.
