# Premier Gastroenterology: live v3 versus retained v1

**Status: all six research jobs and seven display tasks completed; quality acceptance not granted.**
Research ran 15:47:17–16:07:14 UTC (19m 57s). The final display refresh completed afterward. All six
isolated workers exited with code zero; no shared-runtime changes were made.

The founder authorized Premier account research with the latest v3 implementation, then requested
five additional fleet workers at concurrency three. This experiment uses the platform's real
launch, research, provider, claim-store, leased-fleet and display paths. No architecture redesign
or prompt/model repair is part of the experiment.

## Reproducibility and comparison boundaries

- Code at launch: `1c68ad8b5`, including v3 and the prior provider-pacing correction.
- Isolated database: `clue_arv3_premier_20260922_9a32cb42`.
- Private evidence and runnable harness: `.artifacts/arv3-premier-live-20260922-9a32cb42/`.
- Run: `5d1f5f8e-b6b8-578c-9002-09c9b1ae371e`; account job:
  `b505b6ca-5dad-5c18-86d6-581787b1cbcf`; domain: `pgalr.com`.
- Started: September 22, 2026, 15:47:17 UTC. Full effort; normal committee/job/provider limits.
- Six workers: base concurrency two, five added workers at three, **17 task slots**. Account
  decisions remain sequential; independent person/display jobs can occupy the additional slots.
- Exact historical ICP artifact retained: `e9f167a70eaa7be6d07b4ec69f29bc0fa3e82ab156c0202f658df9c7af27a036`.
  Selected products remain MagicDocs, Intake AI Agent and Direct access colonoscopy AI intake.
- No historical target claims, contacts, jobs, media or display blocks seeded. Current source
  global field definitions were deliberately retained, including existing factual descriptions.
  Thus this tests the current platform/catalog configuration, not discovery with a clean catalog.
- Source database was read-only; fresh migrations applied only to the isolated database. Shared
  services, environment settings and the v2 shared default were unchanged.
- Historical baseline: [Premier side audit](../../../.context/arv2-premier-comparison-2026-09-22/REPORT.md),
  with its missing database join completed in the [cumulative review](2026-09-22-arv3-cumulative-quality-review.md).
  Same account/seller/ICP makes comparison more direct than Probook/Zafran, but live source changes,
  model variability, current catalog and different persona handling prevent a controlled uplift score.

## Observations during execution

1. **Persona lineage mismatch.** The pinned ICP artifact declares version 4, while the confirmed
   knowledge-document row is version 5. The GI persona declares `icp_version: 5`. Current v3
   records `lineage_mismatch` and gives the agent the confirmed ICP plus a persona-context gap.
   Historical persona behavior must not be assumed equivalent. No version was silently rewritten.
2. **Expected committee sequence executes.** Exa deep research completed before the first company-ID-bound
   AI Ark SMART search. Searches covered leadership, operations, clinical coordination and physician
   partners. Candidate quality and final selections remain to be assessed.
3. **Raw claim counts inflate.** Four committee searches plus the initial company lookup produced
   five copies of each of fifteen company facts by the 15:51:56 snapshot. Only one company-provider
   lookup was charged; the repeat writes occur while reusing its result. Count distinct facts separately.
4. **Growing context.** The account agent's eleventh observed model call received approximately
   83,000 prompt tokens. Additional workers do not shorten this agent's serial model/provider work.

## Completed verification and remaining limits

- Real account and five person agents, normal provider pacing, and two account/five contact display tasks.
- 399 stored claims, 34 live display sections, five superseded sections retained; final account and
  all five contact projections have no stale/pending sections. No application code was changed.
- All 311 distinct ledger-referenced artifacts passed SHA-256 verification.
- 408 provider result receipts joined to exported observations across six Langfuse traces. Job attribution
  uses the nearest enclosing agent span, not the mutable trace-root job metadata.
- Database rows, raw provider requests/responses, model/tool activity, initial/refreshed display,
  frontend read projections and a readable copy of generated pages are retained privately.
- Shared database was read-only. Final isolated fleet queue: six research tasks done, seven display
  tasks done, none queued/running. All six workers stopped gracefully and flushed tracing.
- This verifies generated display plus the backend's real frontend-read composition. A browser was
  not exercised, no shared app data was replaced, and the full media A01–A20 acceptance matrix was
  not run. Model/provider outputs remain subject to the quality findings below.

## Settled account findings

The account job finalized in **8m 21s**, with 18 model rounds and 67 tool calls. The historical
Premier account job took 9m 51s, with 20 rounds and 70 tools. These are observations from two live
runs, not an isolated benchmark of the worker expansion. The five child jobs started 0.45–0.90s
after creation; that is the clear scheduling benefit of the added capacity.

| Measure | Historical Premier v1 | Current Premier v3 account |
| --- | --- | --- |
| Raw account claims from the run | 77 | 123 |
| Distinct field/value/source tuples | 76 | 63 |
| Account Exa report | 14,304 characters / 19 results | 16,747 characters / 20 results |
| Extraction calls / ordinary rows | 3 / 34 | 2 / 19 |
| Source blocks supplied | 12 + 12 + 5 | 12 + 6 |
| Full Exa report supplied to extractor | No | No |
| Selected/researched committee | Todd Greer, Terence Angtuaco, Dhaval Patel | Those three plus Beth Smith and Anna Ruth Tribble |
| Account transcript acquisition | Not exercised by this historical audit | Zero; two discovery calls, 40 candidate rows |

Raw counts are not quality or recall scores. Sixty of the current account rows are repeat writes
of already-written company facts. The v3 account research ledger subtotal, excluding display,
is **$1.304679 plus 6.1 AI Ark credits**. The first nine display calls add $0.017473. Person
research and later display refreshes are separate and will be included in the final total.

### What was retained or improved

- The research preserves Open Access colonoscopy eligibility, referral fax/online pathways,
  multiple locations, physician ownership, operating pressures, facility history and culture.
- EHR and patient-portal vendor remain explicitly unknown. The old fabricated Klara claim was
  **not reproduced**. The old self-customer and charity-committee-as-ACE fields were also not emitted.
- Four SMART searches used the resolved exact AI Ark company ID. They returned 2 leadership,
  3 operations, 1 clinical-coordination and 6 physician-partner candidates, with overlaps.
  Beth Smith adds a substantively relevant operations/integrations background.
- The current account output distinguishes Todd Greer from stale Bill Greene CEO copy. It keeps
  historical development financing separate from venture funding and names its EHR fit gap.

### Defects reproduced in current v3 output

1. **Caller context became evidence.** Claim `62650344-572d-4d6a-af39-9bd8f16596fe`
   asserts headcount 64 with the agent's “AI Ark already wrote…” note as its evidence, while
   citing `https://pgalr.com/`. The writer correctly marks `evidence_verbatim=NOT_FOUND`, but
   the row remains live and outreach-safe. The initial **why-they-fit** display directly cites
   this row. The underlying number is separately provider-backed; the defect is false provenance
   and acceptance into displayed evidence, not proof that the number itself is false.
2. **Field meaning remains unreliable.** The extractor files MedEvolve RCM and a fax referral
   process as `account.gtm_tooling_stack`, defined as CRM/outbound/ABM tools. A direct agent write
   files NPI taxonomy and CLIA laboratory credentials under `account.endoscopy_accreditation`;
   its quoted NPI registration does not establish endoscopy-center accreditation. This differs
   from v1's specific ranking/board-certification error but preserves the underlying semantic failure.
3. **Seller proposition is still wrong in live display calls.** Saved requests pair
   `client.name=Insight Health AI` with the ABM platform pitch. Generated **buying-signals**
   consequently recommends Insight Health's account/committee research and content around clinical
   workflows. The **why-they-fit** page includes “A 64-person account is suited to focused account
   research” and an ABM-maturity caveat. No inference from old code is needed: these are fresh outputs.
4. **Fit and detailed findings are selectively routed.** All five ICP-gate claims are unsafe/internal
   and enter **watch-outs**, not **why-they-fit**. Dedicated Open Access, location, ASC-project,
   Open Access email and culture keys do not reach any of the initial nine display requests under
   their own keys. Some facts survive through broader operational/strategic claims; this is not a
   claim that all their content disappeared. The overview suppresses watch-outs by its existing UI contract.
5. **Hiring freshness is overstated.** Retrieved job pages include closing/“available before” dates
   already past at research time for scheduling and billing. The final claim drops those dates and
   labels the listings `still_listed=true`; display turns that into active hiring and a reason to act
   now. An accessible aggregator page does not by itself prove the role remains open.
6. **No effective correction of the bad headcount provenance.** At account settlement no account
   claim was superseded. The flagged row survives into actual display, despite the separate link audit.

The literal extraction diagnostic finds 16/19 current ordinary quotes in the supplied source
bodies versus 25/34 historically. This is not an accuracy score: URL/header text and normalization
can fail literal matching, while an exact span can still be assigned the wrong field or subject.
Production audit results and semantic review must accompany that count.

### Media and runtime observations

The account agent did call media discovery twice. Its final free-text gap saying YouTube/podcasts
were “unsearched” conflicts with that durable activity; the structured media summary correctly says
`discovery=searched`. Broad results included unrelated vendor podcasts and generic GI recordings.
No account recording was acquired. Do not count candidate rows as verified appearances.

Account model time sums to 283.7 seconds out of 500.6 seconds elapsed, and its largest prompt was
124,058 tokens (1,301,720 input tokens across 18 rounds, including cache). Extra fleet slots do not
remove that serial work. Provider pacing stayed enabled; account pacing waits totaled 12.3 seconds.

## Relation to the side-agent's modified PoC experiment

The retained modified PoC trial is an account-only extraction comparison, not an unchanged Shank
pipeline or a controlled v1/v3 test. Its fresh Exa report has 12,748 characters and 19 results. The
fresh PoC extractor returned 25 ordinary rows, 14 with an exact span somewhere in its whole input
bundle, and five empty values. Replaying the historical evidence through that PoC prompt returned
29 ordinary rows, 14 whole-bundle matches and four empty values. Both retained joined quotes and
questionable mappings, as documented in the side audit.

Current v3's account report is richer in length and its extractor emitted 19 ordinary rows, with
16 literal source-body matches. Those numbers do **not** establish greater recall or accuracy:
whole-bundle versus source-body matching differs, live evidence and prompts differ, and v3 also
writes direct and deterministic claims. The important shared result is that original-report access
alone did not fix semantic extraction. V3 adds committee discovery, actual person jobs and media
execution, but still exhibits the evidence/context errors proved above. No additional paid PoC
replay was run in this test.

## Completed person research and final presentation

| Person | Time / rounds / tools | Outcome and limits |
| --- | --- | --- |
| Beth Smith | 5m 24s / 10 / 25 | Relevant administrator with GI endoscopy and multi-entity anesthesia integration experience. Verified-SMTP work email and provider phone. Unique-insight output chose her generic LinkedIn About rather than the stronger integration detail; some “NOT FOUND” report lines became claims. |
| Dhaval Patel | 6m 09s / 14 / 38 | Physician/founding-partner identity, training, clinical role and limited first-person material recovered. Verified-SMTP email and provider phone. No long-form recording; clinical role does not establish ownership of EHR/RCM procurement. |
| Todd Greer | 6m 11s / 15 / 35 | CEO/COO history, operating priorities and first-person MedEvolve KPI/board-meeting material. Verified-SMTP email and provider phone. Two invalid structuring calls were corrected; unique-insight result was dropped as off-target, but useful voice claims were written separately. |
| Terence Angtuaco | 11m 36s / 14 / 46 | Founder/board role, clinical publications, operating views and a self-written taekwondo testimonial recovered. Verified-SMTP email and provider phone. Acquired a podcast video; two transcript-linked claims remain unsafe due to unverified speaker identity. |
| Anna Ruth Tribble | 6m 22s / 23 / 42 | Employer association unresolved: provider/company-page linkage points to Little Rock, but her own older hiring posts point to Katy, Texas. Work-email outcome empty; phone returned. Eight attempts reused a nonexistent transcript version, preventing successful structuring; the later unique-insight request was refused. |

The three historical people match the same canonical LinkedIn identities, not merely similar names.
The new operations coverage is useful, but **five selections are not five verified account memberships**.
Anna's possible association with the target remains unresolved. A returned phone does not resolve it.

### The unresolved identity actually reaches the refreshed page

Anna's finished research explicitly says not to approach her as a confirmed Little Rock champion
without re-verifying employment. Nevertheless, the final account API still lists her as **Practice
Manager / Champion**. Her contact page has an internal warning about weak aggregator evidence, yet
ordinary sections still describe committee influence and long tenure at Premier, generate openers
about the Katy practice, and combine those with Little Rock fax/referral workflows. An **angles**
section additionally offers Insight Health's supposed account/committee-research capability.

Thus the issue is not failure to discover the contradiction. The contradiction is discovered,
stored and mentioned, while the membership and synthesis paths continue treating the earlier
association as usable. A warning in restricted notes is not an effective committee correction.

### Media execution and usable output are separate

Terence's agent acquired YouTube `XSxC3HsSiGE`, an appearance on *What Really Matters* with Kris
Kohlstedt, titled “Find Out What Matters Most in Your Life in Just 5 Minutes.” The resolved video
is 5,218 seconds; the title is not its duration. Native Gemini video processing, six embedding
batches, two query embeddings, two hybrid searches and eight passage opens all executed.

The transcript carries `coverage=unknown` and `repetition_detected` (447 unique lines out of 820).
These are quality warnings, not proof that every passage is false. Its speaker labels remain
model-inferred, with no verified entity binding. Both linked claims are therefore
`outreach_safe=false`; **zero safe transcript-derived claims** resulted. Other useful personal
material came from written sources. This reproduces the earlier v3 distinction between functioning
acquisition/retrieval and usable, attributed output.

## Final costs, tracing and bottlenecks

- Known recorded total: **$6.441192 plus 35.1 AI Ark credits**. This includes 39 display calls:
  nine initial account sections, five account refreshes and 25 contact sections. Display subtotal:
  $0.094192. Native Gemini video has no priced USD receipt, so the total is incomplete, not a full bill.
- Six jobs completed through 94 model rounds and 253 runtime tool calls. Provider results: 405 `ok`,
  three careers-page `client_error`; no provider retries were recorded. No runtime deadlock recurred.
- Every person job started within 0.90s of queuing. The account and Terence's later serial work
  remained the critical path. Terence spent 396.2s in model calls; two late calls each took about
  91s over growing histories. His largest prompt was 123,703 tokens.
- Shared AI Ark pacing remained effective. Cumulative per-job waits were roughly 25–224s across
  the person jobs. These can overlap and must not be added as elapsed run time.
- The final trace contains 17 structured tool refusals/errors: eight Anna transcript-reference
  failures, two Todd missing-source argument failures, one unique-insight precondition refusal,
  five unavailable pages and one unavailable ATS board. Several return with wrapper status
  `success`, so audits must inspect the structured rejection payload rather than count only ERROR spans.
- Seven prose correction markers exist, but **zero claims are actually superseded** across this run.
  This reinforces the correction-state gap already demonstrated in the prior comparisons.

## Implications for the next design

This run supports preserving AI Ark committee discovery and v3 media tools, while repairing the
contracts around them before relying on richer output:

1. Supply versioned seller/product/ICP context to display, and reconcile ICP/persona version semantics.
2. Give evidence and claim correction an effective write/read contract; distinguish source text,
   caller context, schema meaning and entity relationships. Preserve original artifacts and finding disposition.
3. Reconcile finished person findings with committee membership and page generation. Exact company-ID
   queries do not make every returned employment association true.
4. Make ordinary page-source and transcript-reference inputs unambiguous and recoverable; never
   encourage a retry loop on invented references. Keep quality and identity qualifications through display.
5. Reduce repeated context and duplicate fact writes. Measure any proposed parent/specialist architecture
   against these concrete failures; framework migration alone does not fix them.

These are findings for the next specification, not changes implemented by this live test.


## Evidence pointers

- Private manifest and reproducible harness: `.artifacts/arv3-premier-live-20260922-9a32cb42/manifest.json` and `harness/`.
- Final database/metric snapshot: `snapshots/evidence.json`, `snapshots/metrics.json`.
- Original Exa/extraction/display requests and responses: `materials/` (including report Markdown).
- Actual final frontend-read projections: `pages/account-latest.json`; first account output preserved
  under `baseline-account-display/` and the timestamped page files.
- [Readable generated research output](../../../.artifacts/arv3-premier-live-20260922-9a32cb42/pages/research-output.md).
- Tool activity/refusals: `tool-timeline.json`, `trace-tool-rejections.json`; exact trace join:
  `trace-export-status.json`; retained-artifact verification: `artifact-integrity.json`.

Private artifacts are local, excluded from git, and have not been published. The source-side audit
and an unrelated concurrent edit to the cumulative review were left untouched.
