# V3 live research versus the saved PoC

September 23 follow-up: a fresh Zafran run of the subsequent research-quality implementation is
tracked in [the quality-flow live record](2026-09-23-zafran-quality-live.md). Its first attempt
failed, runtime fixes were verified, and a corrected fresh attempt is in progress. The historical
v3 results below remain unchanged and do not certify the new implementation.

**Status: live run finished; quality acceptance not granted.** Two account jobs and eleven person jobs completed through the real v3 agents. The measured run lasted 14:15:37–14:55:55 UTC on September 22, 2026 (40m 19s including person queues); both isolated workers exited cleanly afterward. These are live-provider results, not fixtures. Four Probook person enrichment outcomes were compromised by a corrected test-harness identity error. A separate four-person recovery run also completed, with emails and phones returned for all four; its results are reported separately. Both recovery workers stopped cleanly at 15:14:54 UTC. No full A01–A20 acceptance or deployment approval is claimed.

The run establishes that SMART committee discovery, both contact channels, native YouTube/audio acquisition, embedding, hybrid retrieval and transcript reuse execute live. It also exposes serious output-quality issues: subject facts entering shared field descriptions, prose corrections not repairing stored/current claims, and very little usable transcript-grounded output. Completion status alone is insufficient for acceptance.

## Scope and reproducibility

- User requested latest v3 only, using the platform's own agents on Probook and Zafran, compared with Shank's saved PoC. No fresh v2 control and no additional paid-provider test cap.
- Implementation: `56f612b33`, followed by live-discovered pacing fix `5c0b9b912`. v3 selected only in isolated workers; the shared lane retains its v2 setting.
- Isolated database: `clue_arv3_live_20260922_fed26981`. Private evidence: `.artifacts/arv3-live-20260922-fed26981/` (manifest, raw artifacts, durable snapshots, Langfuse exports and action timelines). Shared Jerusalem databases/services were not migrated or restarted.
- Real launch seam, Postgres fleet queue/leases, account and person graphs, model gateway, provider clients, claim writer and production observability installers. Research models: `x-ai/grok-4.6`; full effort, normal job bounds. Initially two worker slots, expanded to four when person jobs queued.
- Only seller/project context and bare account identities were copied. Historical target examples and contact-source URLs were removed from the seller ICP/persona copies, with both source and test digests retained. Initial claims, contacts, jobs, provider ledger and media tables were empty. PoC findings were not agent input.
- Baselines: `.context/arv2-clue-sample-v3/claims.json` plus account/person dossiers; `.context/arv2-one-account-aiark/claims_zafran.json` and dossiers; the three Zafran people in `.context/arv2-person-depth/claims_people.json`. PoC dates differ from the September 22 live run; changes in current facts are not automatically regressions.
- Autonomous account/person run: `55658adb-41ca-5c83-842b-86a55e71b0e4`. Supplementary person run: `1ff22f7e-0765-5b9a-87a3-b5f98a42afbd` (Sanaz Yashar and Ben Seri only, identity inputs without PoC findings). The eight other historical committee members were already selected autonomously; Kelly W. is an additional live selection.

## Completed account runs

| Measure | Probook | Zafran |
| --- | --- | --- |
| Runtime | 10m 51s | 9m 38s |
| Model rounds / runtime tool calls | 15 / 60 | 16 / 57 |
| Completion | Finalized | Finalized |
| Autonomous person jobs | 5 | 4 |
| Media acquired | George Eliadis YouTube interview, 2,034 seconds | Boardroom Club CEO podcast audio, 2,569 seconds |
| Transcript size | 30,794 characters | 37,028 characters |
| Transcript searches | 2 hybrid searches | 2 hybrid searches |
| Raw account claims / distinct field-value-source tuples | 146 / 81 | 232 / 106 |
| Structured PoC comparison: exact + partial | 11 / 24 | 27 / 67 |
| Known recorded USD subtotal | $1.078238 | $1.220963 |
| AI Ark credits | 7.6 | 6.6 |

USD is not a complete bill: Probook's native YouTube generation is explicitly unpriced. Credits are separate. Counts refer to settled account jobs, not their later person jobs. The 10.5-second AI Ark pacing interval was retained.

The mechanical comparison uses the repository's field/leaf-value matcher, reading the PoC offline. It is a diagnostic for same-field factual overlap, **not an accuracy or overall quality score**. It misses differently represented facts and treats changed facts as disagreements. It also does not measure the full prose dossiers. Final review must interpret each important difference.

Both accounts used Exa deep research, live Ashby evidence, SMART AI Ark searches with exact company binding, media discovery/acquisition, embedding and transcript retrieval. The account deep calls took approximately 40 and 44 seconds; they were not the dominant end-to-end wait. Both accounts supplied source-linked ICP gate rationales.

Probook's selected committee matched all five historical PoC people: George Eliadis, Mark Hoffman, Kate Blumberg, Aaron Churba and Lewis Zhang. Zafran selected Nick Fisher, Vari Kaur, Tom Anthony and Kelly W.; its fifth proposed seat was vacant. The separate historical-person comparison preserves Sanaz and Ben without pretending the account agent selected them.

## Account comparison beyond field matching

**Probook:** the live dossier recovered the PoC’s core product, New York location,
$34M Series A / $40M total funding and GTM expansion theme. It added a concrete seller-relevant
account-research brief from SDR hiring, the growth-lead reporting line, and founder-led sales
handoff to the CRO. The pain narrative focuses more clearly on Probook’s own GTM capacity than
some PoC rows describing pain experienced by Probook’s customers. It reports 12 current openings
versus the earlier PoC’s 14, which is a dated snapshot difference. However, its stored headcount
regressed: the old PoC had 52, the new prose argues roughly 60–65, and the current-value reader
still returns the repeatedly written provider value 30. The PoC also incorrectly encoded
“14 open positions” as an employee range; reproducing that would not be an improvement.

**Zafran:** the live dossier recovered the major funding, product, customer-logo and ABM-building
story, with the open ABM role tied to Head of Growth and related field/marketing/sales hiring.
It explicitly qualifies job-stated tools instead of certifying them as installed software, and
separates strategic investment from acquisition rumors. The PoC has a more complete structured
round history and richer hiring-velocity aggregation: department totals, recently published
counts and age of the oldest marketing requisition. The new typed funding fields often collapse
to the latest round/total; new hiring-velocity objects are inconsistent in shape. Thus the new
prose is useful, but not every richer PoC detail survives as a reusable structured fact.

Both live outputs connect evidence to the seller’s ICP gates and select plausible buying roles.
Neither account produces a substantive structured claim with a valid transcript reference.
This does not establish that reading the recordings had no effect on their narrative; it
establishes that the durable evidence link is missing from the substantive account claims.

## Findings

| Finding | Evidence and implication | State |
| --- | --- | --- |
| AI Ark pacing deadlock | Token-wide transaction used the driver's serialized connection; the provider hop tried to reacquire it for authority/receipt work. Both first tool waves stalled before AI Ark dispatch. | Fixed in `5c0b9b912`; bounded v2/v3 driver regression and successful live rerun. |
| Unsupported seniority filters | Both agents supplied values such as `c_level`; tool rejected them and the agents retried without the filter. The published argument schema accepts arbitrary strings while validation uses a closed vocabulary. | Open; avoidable reasoning/tool round trips. |
| Repeated company claims | `company_lock()` replays the paid company operation but writes its company claims on each role search. Account rows substantially exceed distinct field-value-source tuples. | Open; this is repeated materialization, not evidence of repeated company purchases. |
| Large contexts | Account inputs grew from about 17k tokens to over 130k. Model completions and drafting consume substantial wall time alongside media and provider pacing. | Measured in the timing tables below. Histories reached 143k tokens; cached input reduces billed cost, not the need to process and act on the history. |
| Media acquisition works, account evidence use remains weak | Both transcripts were embedded/searched. Final account claims contain one structured transcript citation on Probook's media index and none on substantive Zafran account claims. Zafran's manually written index lacks a valid transcript reference and is marked unsafe. | Open quality gap; successful tool execution does not establish useful media-grounded output. |
| Narrative and current values diverge | Probook summary explicitly flags provider headcount 30 as stale against roughly 60–65. The shared current-value seam still returns 30, marked fresh, without conflict. Founding-year uncertainty is also described in prose while the scalar read returns 2022. | Open; downstream consumers can see different facts from the narrative. |
| Quote audit failures persist | Final account receipts include `NOT_FOUND/not_on_page` (14 Probook, 22 Zafran), plus partial matches and a missing legacy transcript reference. At least one quote-mismatch claim per account still has `outreach_safe=true`. | Current settings have verification disabled. The normal read gate admitted 66 of 73 final NOT_FOUND quote-audit rows. Across 515 audit rows: 365 EXACT, 70 PARTIAL, 73 NOT_FOUND and 7 fetch_failed. Thirty-three NOT_FOUND rows are requisition records. This follows the master plan’s annotation-only policy; it is a quality/repair gap, not proof of a policy bypass. |
| Trace environment changes on completion | Exact live trace IDs remain readable, but their environment became `default` and they disappeared from the test-environment filter. Child jobs share account trace ancestry. | Open telemetry issue; collect by exact IDs and attribute through job/observation lineage. |

The initial Boardroom source returned `no_supported_recording_link`. Zafran recovered an audio path autonomously and completed transcription. The NYSE clip remained ambiguous/unacquired. Probook's founder video was also found autonomously. Neither transcript reported a detected repetition loop, but coverage remains `unknown`; generated timestamps and speaker labels are qualified rather than certified.

## Critical accuracy finding: facts entering the shared catalog

At 14:38:25, George’s structuring pass proposed `contact.founded_companies` and stored `[Eliadis Numismatics, Probook]`. The dynamic field writer registered this description verbatim:

> Bundle shows he founded Eliadis Numismatics and co-founded Probook; a dedicated field for founded companies would capture entrepreneurship history.

That is subject evidence inside a shared field definition. Later person catalogs expose the definition. At 14:44:25 the structurer wrote Eliadis Numismatics onto Aaron, and at 14:44:47 it wrote Eliadis Numismatics / Probook co-founder onto Kate. Aaron’s tool input source blocks did not contain Numismatics. Both agents noticed the unsupported attribution. Aaron appended a correction (`410d433d…` correcting `0bbfa385…`), while Kate warned about it in her final gaps. The original erroneous rows still have `superseded_by=NULL`.

This supports a cross-subject catalog-contamination diagnosis, separate from the test harness’s duplicate identities. The field was created during this run (`proposed_field=true` on George’s first row), not copied from the PoC. Proposed-field descriptions need entity-neutral definitions; descriptions must not become evidence. Corrections must be understood by downstream reads without assuming a final prose warning repairs stored claims.

Code anchors: [`_register_proposed_field`](../../../platform/api/clue_api/arv2/claim_writer.py#L262), [`read_person_catalog`](../../../platform/api/clue_api/arv2/account_research_store.py#L590), [catalog menu rendering](../../../platform/api/clue_api/arv2/structuring_client.py#L212), and [proposed-field / correction mapping](../../../platform/api/clue_api/arv2/account_research_claims.py#L1325). The incorrect Aaron claim is still marked `outreach_safe=true`; his correction is unsafe and does not retire the original. No catalog or claim repair has been applied during the measured run.

## Recorded decisions and timing

The trace records useful, explicit role hypotheses. Probook connected the recent raise and founder-led sales transition to CEO/CRO budget ownership, the Director of Growth to SDR/events execution, and the CTO to CRM/data evaluation. Zafran connected its open ABM role to Head of Growth as champion, VP Marketing/SVP Sales to sponsorship, and marketing operations to tooling evaluation. These were model assessments, not facts certified by AI Ark. SMART company-bound searches followed the completed deep-research call.

| Completed job | Agent model wall time | Largest model input | Other measured stages |
| --- | --- | --- | --- |
| Probook account | 291s | 139,944 tokens | Exa deep 44s; media read 109s; longest role-search tool 72s |
| Zafran account | 271s | 142,966 tokens | Exa deep 40s; successful media read 128s; longest role-search tool 53s |
| Vari | 294s | 108,403 tokens | Exa deep 38s; structure 29s; unique-insight 4s |
| Kelly | 309s | 102,762 tokens | Exa deep 30s; structure 35s; unique-insight 5s |
| Mark | 249s | 96,419 tokens | Exa deep 42s; structure 32s; unique-insight 7s |
| George | 297s | 115,094 tokens | Exa deep 44s; one failed media read 68s; structure 28s |

Model wall time is the union of generation intervals; it excludes separate leaf structuring calls. Parallel tool durations cannot be added to infer total runtime. Maximum token figures combine uncached and cached input from actual model observations. There are 573 runtime tool calls and 575 tool observations: the trace additionally includes one rejected argument-validation call each for Probook and Nick.

AI Ark token pacing is visible rather than hidden in network latency: summed acquisition waits were 101.8s across seven Zafran account calls and 97.4s across six Probook calls; the largest wait was 59.5s. These waits overlap within tool waves and across jobs. The configured cooldown remains 10.5s. This is throughput limiting by design; reducing it requires a provider contract decision, not simply increasing concurrency.

George reused the account’s saved YouTube transcript and hybrid index. One exact transcript quote was stored, but remained outreach-unsafe because speaker identity was not verified. Its scalar `media_timestamp` says 00:00 while the qualified source segment starts around 190 seconds—another reason consumers must use the canonical media markers rather than trusting generated display values.

Person-output quality issues already visible: Vari’s LinkedIn post was placed in `contact.x_url`; Mark’s workplace deal-bell tradition was placed in a personal-hobby field; Kelly and Vari received generic certificate facts as “unique insight.” Their final prose recognizes several of these limits, but typed claims still carry the misclassification. No recordings found for a thin-footprint subject is an honest outcome; the semantic field mistakes are separate.

Nick and Tom’s structuring requests remained in flight for over fifteen minutes. Stack sampling showed network reads with a healthy event loop and no Postgres blockers. This leaf uses `openai/gpt-5-mini`, a 900s timeout and the shared default of four attempts. Both calls recovered on attempt 2 around 14:45:30. The successful-attempt ledger latencies were only 25.494s (Tom) and 28.448s (Nick), masking the roughly 15-minute earlier wait. No billed-cost receipt exists for the timed-out attempt, so the known USD subtotal is not a complete billing reconciliation. Its estimates and raw result are buffered until the provider hop drains, so durable SQL alone does not expose the in-flight attempt.

## Media and telemetry caveats from the live path

- George’s failed public download remains a reserved binding with `download=unknown/ReadTimeout` and no transcript. His receipt says `recording_count=2` although only one recording has a transcript. The state helper counts every non-released binding, including reserved ones. Report resolved, acquired and usable counts separately; recovery of a failed free download should not be conflated with uncertain paid transcription.
- The three principal bottlenecks are model generation over growing histories, model-provider timeout/retry, and shared AI Ark pacing. Exa deep research and transcript embedding are smaller stages in these measured jobs.
- Langfuse exports include actual tool/leaf-provider observations; private payloads retain the configured masking. Parent traversal is required because children inherit account trace ancestry and root job metadata is mutable. Some in-flight enclosing spans appear only at completion.
- A Langfuse export timeout was logged during the run. Exact-ID exports and SQL receipts are preserved; do not claim the external trace stream is lossless. The environment-filter defect further means “no trace in the test filter” is not proof that no work ran.
- The provider ledger’s final-attempt latency is not end-to-end call latency. The timed-out-attempt charge and native Gemini video pricing remain unknown; completed subtotals are not a reconciled vendor invoice.

## Excluded attempts and harness corrections

- `d6403dc1-044a-515c-adfe-50aab24f01ab`: harness used `GatewayConfig()` instead of production `default_gateway_config()`. Model construction refused before spend. Corrected before evaluation.
- `253a5544-2b48-5bb4-9949-39f960544489`: genuine pacing deadlock. Forced isolated-worker termination after preserving traces. Completed model and Exa calls total $0.071542 in trace-derived costs; the lock blocked buffered ledger/raw drains. Jobs are marked needs-review, not successful research.
- `ef6a3f85-73be-574e-8e2e-708a84d0f33d`: comparison harness initially failed to normalize LinkedIn URL variants. All ten supplemental tasks were cancelled while unstarted, before any provider spend. The corrected launch queued only Sanaz and Ben. The duplicate contact rows later interfered with Probook provider binding (`MultipleResultsFound` at the canonical LinkedIn lookup). Those enrichment failures are **harness contamination**, not provider-quality failures. At 14:42:32 UTC, the eight duplicate anchors belonging only to cancelled jobs were quarantined by clearing their LinkedIn fields; the before-image is retained privately. The actual selected contacts and Sanaz/Ben cohort anchors were unchanged. Affected person runs must be qualified in the comparison.

## Person comparison

These are qualitative comparisons of the underlying facts, not just string-match scores:

| Person | Live result relative to the PoC | Material limitation |
| --- | --- | --- |
| Nick Fisher | Independently recovered Cocktail Chemistry / book linkage from his own LinkedIn; added ZafranGPT, AI-first GTM hiring and product-marketing writing. Acquired a healthcare interview audio source. | Audio speaker identity remained unknown; some combined-source quotes failed audit. |
| Vari Kaur | Recovered ABM hiring ownership, certifications, career and tool familiarity. Refused to invent a reporting line or accept an aggregator-only board role. | Generic certificate selected as unique insight; LinkedIn post wrongly filed as X URL. |
| Tom Anthony | Recovered career and current role; surfaced a recurring people-first hiring thesis from first-person posts. | Unique-insight chose a standard appointment release; no verified recording found. |
| George Eliadis | Recovered pressure-washing background, coins business, Penn education, founder sales and CRO transition; reused account video. | Four-person Probook seed/enrichment comparison affected by harness identities; transcript voice remained unsafe. |
| Mark Hoffman | Recovered VTS/Tennr→Probook transition, founder handoff and current GTM expansion; found an older sales-team interview. | Workplace deal bell misclassified as a personal hobby; seed/enrichment affected by harness. |
| Kate Blumberg | Recovered ABM/growth career and current account-list/deal-size hiring brief; found BuildOps webinar and candle side project. | False founded-company row from catalog; unverified spoken attribution; seed/enrichment affected by harness. |
| Aaron Churba | Recovered the decade-later Hoffman reunion, current seller-team growth and career. | LinkedIn About selected as unique insight; false founded-company row corrected only by annotation; seed/enrichment affected by harness. |
| Lewis Zhang | Recovered co-founder/Roblox/Berkeley background and distinctive YC founder-matching story; continued after thin Exa deep output. | Unique-insight selected an old GitHub project; no recording of Lewis speaking found. |
| Sanaz Yashar | Recovered career, Boardroom appearance, MTTR/customer-growth theme and current product positioning; reused podcast and acquired NYSE video. | Missed PoC hobby posts (Thai boxing/Breaking Bad); education lost degree/year detail; no valid transcript-linked factual claim. |
| Ben Seri | Recovered Armis→Zafran leadership, security talks, music and current technical writing; acquired three recordings. | All recorded speech attribution uncertain; one transcript quote only partially matches. Work email succeeded; phone honestly empty. |

The normal selected-profile path successfully bound five unaffected autonomous members (four Zafran members plus Lewis): four work-email results, one honest empty email, five phone results. No repeated named-person lookup was needed for those seeded profiles. The two identity-only supplemental jobs performed the expected named lookup: both emails succeeded, Sanaz’s phone succeeded and Ben’s phone was empty. Across seven valid channel tests, there were six emails and six phones, with one empty result in each channel. “Succeeded” is the provider/identity-check outcome, not a claim that every email passed SMTP—Lewis’s email was catch-all.

Do not extrapolate the four contaminated Probook channel failures into AI Ark coverage conclusions. George, Mark, Kate and Aaron still ran web/person depth, but their missing deterministic profiles can also affect richness. Their result comparisons remain qualified, not clean seeded-person acceptance.

The old PoC is not an infallible answer key: for example, its Sanaz person-depth file puts company funding in `contact.facet.recent_award`. That should not be counted as a desirable personal fact to reproduce. Mechanical matching also undercounts reordered career structures: Sanaz scores 0/13 exact+partial while the live output plainly recovers her career, universities, Boardroom appearance and MTTR theme. Real misses include particular hobbies, posts and degree details; fresh facts and differently shaped values require separate judgment.

## Completed recovery after the harness identity correction

Run `d5838fad-4276-5e47-9853-8eb15727e4bd` independently launched George, Mark, Kate and Aaron
through the production **on-demand person** seam, using their correct original contact identities.
All four completed. This isolates the contact-identity correction, but uses existing live claims,
catalog and transcripts: it is not a fresh blind benchmark or a replay of the original seeded
committee handoff. Each made one expected named-profile lookup. No PoC findings were supplied.

| Person | Runtime | Email outcome | Phone outcome | Known USD | AI Ark credits |
| --- | --- | --- | --- | --- | --- |
| George | 8m 14s | SMTP verified | Returned | $1.137734 | 6.5 |
| Mark | 8m 43s | Catch-all | Returned | $0.771330 | 6.5 |
| Kate | 8m 12s | SMTP verified | Returned | $0.976887 | 6.5 |
| Aaron | 7m 12s | Catch-all | Returned | $0.867168 | 6.5 |

Recovery totals: **$3.753119 known USD, 26 AI Ark credits, 247 raw claims, 57 model rounds,
158 tool calls and 223 settled provider rows**. All 223 rows join exported trace observations;
all 57 model rounds are present, with no unmatched estimates. There were no retried provider
calls, newly transcribed seconds or new transcript versions. George and Kate reused saved
transcripts and produced two more exact, but speaker-unverified and outreach-unsafe, voice claims.
The roughly three-minute pre-start queue interval came from restarting the test workers; it is
not a measured production queue bottleneck.

Across the eleven evaluated people, combining the seven unaffected original channel tests with
these four valid recovery tests yields **10 email results and 10 phone results**, with Kelly’s
email and Ben’s phone honestly empty. This is observed cohort yield, not a provider-wide coverage
estimate. Catch-all results are not SMTP-confirmed deliverability.

The recovery also reproduced the catalog defect: new incorrect founded-company rows appeared
for Aaron and Kate, and a qualified incorrect row for Mark. The agents noticed; appended
correction markers still did not retire the originals. This persistence after correcting
identities strengthens the diagnosis that the shared field description is a separate product
issue. Kate’s degree also appeared in a high-school field. Weak insight selection persisted:
Aaron received certifications, Kate a generic headline, and Mark the work close-bell as a hobby.
George’s coin-collecting selection was more useful.

The original benchmark totals below remain unchanged. Combined completed-run known USD is
$18.127018 plus 77.2 AI Ark credits; the separate aborted deadlock attempt adds $0.071542 in
trace-derived known cost. Unpriced video and unknown timed-out-attempt charges still prevent
calling this a complete vendor bill.

## Verification and remaining work

- Pacing fix: two real-Postgres, scripted-provider v2/v3 account→person regressions passed; 163 account-tool/driver tests passed; touched Ruff and format checks passed. No full-suite repetition was required.
- Actual Langfuse generations/tool observations and HTTP-200 trace retrieval verified. The recorded analysis separates generations, provider latency, pacing, retries, extraction, media stages, queue waits and evidence yield. Only explicit recorded actions/rationales and usage counts enter the report; private reasoning text is not reproduced.
- Identical completed account launch replay passed: same run and jobs, zero queue offers accepted, 11 jobs and 377 account-ledger rows unchanged. No new provider purchases. This proves launch/queue replay, not every crash-recovery or privacy scenario.
- All thirteen original jobs finished; both original workers exited with `worker.stop` and `tracing.stopped`. Two isolated workers were restarted only for the four recovery jobs and then exited cleanly too. Shared services were not restarted. The database and private evidence remain for inspection.
- Final reconciliation: all 192 runtime model rounds appear in exported job-attributed traces; all 885 settled provider rows join their exact trace/observation IDs. One failed free-media download retains an unmatched estimate and an `unknown` operation; it is not a paid unpriced success. Every settled ledger outcome is `ok`, which would hide this failure if monitoring ignored unmatched estimates, tool errors and operation state.
- Not tested/accepted here: three unseen A06 subjects, independently annotated 30-question Recall@8, live privacy/erasure/crash scenarios, a fresh v2 control, frontend page quality, or vendor-invoice reconciliation. Fresh on-demand recovery validates the four Probook contact-channel outcomes, but does not retroactively validate their original seeded handoffs. These limits prevent claiming complete plan acceptance.

## Final cohort metrics

Raw claims include duplicates, unsafe context and corrections; volume is not verified yield. USD excludes unpriced native-video charges and unknown charges on timed-out requests. Queue wait is separate from agent runtime.

| Subject | Queue wait | Runtime | Rounds / tools | Claims | Known USD | AI Ark credits |
| --- | --- | --- | --- | --- | --- | --- |
| zafran.io | 0m 00s | 9m 38s | 16 / 57 | 232 | $1.2210 | 6.6 |
| probook.ai | 0m 00s | 10m 51s | 15 / 60 | 146 | $1.0782 | 7.6 |
| Kelly W. | 1m 11s | 6m 43s | 14 / 34 | 58 | $0.8829 | 5 |
| Tom Anthony | 1m 13s | 21m 03s | 13 / 35 | 49 | $1.2043 | 6 |
| Nick Fisher | 0m 00s | 22m 39s | 17 / 51 | 58 | $1.3546 | 6 |
| Vari Kaur | 1m 11s | 6m 21s | 10 / 32 | 54 | $0.7692 | 6 |
| Mark Hoffman | 6m 41s | 5m 47s | 12 / 34 | 48 | $0.8629 | 0 |
| George Eliadis | 6m 19s | 7m 42s | 17 / 48 | 56 | $1.4048 | 0 |
| Lewis Zhang | 19m 57s | 7m 42s | 14 / 43 | 68 | $1.1501 | 6 |
| Kate Blumberg | 12m 28s | 8m 01s | 20 / 53 | 55 | $1.4983 | 0 |
| Aaron Churba | 14m 02s | 5m 56s | 12 / 30 | 43 | $0.7190 | 0 |
| Sanaz Yashar | 18m 20s | 7m 00s | 16 / 48 | 55 | $1.0997 | 6.5 |
| Ben Seri | 18m 55s | 8m 24s | 16 / 48 | 47 | $1.1290 | 1.5 |

Final totals: **969 raw claims, $14.373899 known recorded USD, 51.2 AI Ark credits, 10,470 newly acquired media seconds, eight transcripts and four explicitly unpriced native-video calls**. The separate aborted deadlock attempt recorded $0.071542 via preserved traces. These sums are not a vendor invoice. Person runtime median was 7m 42s; Nick and Tom were outliers at 22m 39s and 21m 03s due to their 934s/944s structuring steps. Lewis waited almost 20 minutes for a slot because two worker slots were occupied by those long requests.

Agents processed 14,776,741 cumulative prompt tokens, including 12,204,416 cached tokens, and emitted 229,492 completion tokens. Repeated history contributes to processing time; these are cumulative requests, not distinct source text.

Media yield: sixteen hybrid transcript searches and eight immutable transcripts produced four structured transcript-linked claims: one account media index plus three person claims (George, Kate and Ben). None of those three is outreach-safe. There are no substantive structured transcript-linked account facts. This is the main remaining v3 value gap: ingestion and retrieval succeeded, but their evidence did not reliably become usable research claims. Unverified speakers must stay qualified; improving yield requires correct evidence/attribution handling, not removing that protection.

## Recommended next work, in order

1. **Prevent incorrect entity facts.** Make proposed-field definitions entity-neutral; keep examples separate from evidence; inspect existing definitions and impacted claims. Make explicit corrections effective for current-value and research readers. Resolve stale-value/prose divergence.
2. **Improve evidence conversion.** Preserve canonical transcript references through every structuring/write path; repair legacy-style media references, false timestamps and off-target field mappings. Improve unique-insight selection using the richer material already found. Establish a supported speaker-attribution workflow before treating inferred voice as personal evidence.
3. **Remove avoidable latency.** Publish valid seniority enums, materialize replayed company facts once, reduce repeated context, and make model timeout/retry behavior observable across all attempts. Preserve quality and provider pacing contracts while measuring alternatives.
4. **Close telemetry and lifecycle gaps.** Propagate environment/job scope through fleet and gateway spans; record total call duration and live attempt state; settle failed public downloads and distinguish reserved recordings from acquired evidence.
5. **Repeat only the affected acceptance cases.** After the quality repairs, rerun the impacted claim/evidence cases and complete the independently annotated transcript-retrieval set and other explicitly outstanding media gates. The four identity-corrected on-demand channel repeats are complete; a fresh seeded-handoff test remains distinct if per-subject proof is required. Do not use a fully green terminal status as the quality criterion.

## Evidence navigation

Private bundle: `.artifacts/arv3-live-20260922-fed26981/`. Start with `manifest.json`, then `snapshots/metrics.json`, `activity-timeline.json`, `bottlenecks.json`, `recall.json`, `read-gate-audit.json`, `trace-reconciliation.json` and `evidence.json`. `snapshots/recovery/` contains the separate recovery evidence, metrics and reconciliation. `harness/` preserves the scripts used, including corrections. Raw sources/contact details stay in this private bundle and are not committed to the report.

| Scope | Trace ID |
| --- | --- |
| Zafran account and four autonomous people | `21500cdac11d10e1360ac7530cdb15da` |
| Probook account and five autonomous people | `2421c6b1a66b80aa852a542d8b258ba8` |
| Sanaz identity-only supplement | `53037750d167aafe113d0d983cc34402` |
| Ben identity-only supplement | `f7977c7f2a1e697c6c3ffc9d2f3746b9` |
| George recovery | `b7adb278c910050a16db7d18c4f9975b` |
| Mark recovery | `fdcd88a4a3ca53020b0b2e4add426297` |
| Kate recovery | `a3cc89b891301e095f4db8022af05d74` |
| Aaron recovery | `72d97161ca0e32a0848ef7782d59c518` |

Within shared traces, locate the enclosing `arv2.account_research` agent observation by `metadata.job_id` (that name is also used for person jobs), then follow its descendants. The exported activity timeline contains explicit tool rationales and choices, with timings and IDs. It does not reproduce private model reasoning. IDs for every job and selected identity are in the manifest/snapshot; use the exact IDs because the environment filter is unreliable for these traces.

## Cumulative review with Premier v1

The [cumulative quality review](2026-09-22-arv3-cumulative-quality-review.md) retains this report
as the v3 baseline and compares it with the founder-supplied Premier audit. A new read-only
database join confirms Premier's exact v1 profile and Exa call, and shows its incorrect Klara
claim and correction both remain unsuperseded. This independently reproduces the correction
failure seen here. The proposed Deep Agent/claim-specialist/narrative-specialist architecture
is discussion only, not an implemented or approved redesign.

Additional inspection of this run's saved provider requests found 14,932 report characters / 20
Exa results for Probook and 15,131 / 20 for Zafran. Each account's two extraction calls received
12 + 4 source blocks, not the complete report. This identifies a coverage-accounting boundary,
not a measured loss percentage: the parent can also use the report in direct claim writes.
The v3 test did not exercise display pages; Premier's display defects must not be presented as
measured v3 UI results. All original run/recovery totals and exclusions above remain unchanged.

## Premier follow-up

The subsequently authorized same-account Premier v3 run is tracked separately in
[Premier v3 live comparison](2026-09-22-arv3-premier-live-comparison.md). Its records and costs
are separate from every Probook/Zafran total above.
