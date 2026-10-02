# Insight Health → Premier Gastroenterology: comparative research review

28 September 2026. This is a retained-evidence audit, not another research run. It covers five research attempts plus three Muse setup failures. All initial findings and narrative paths, exact times, costs, model receipts and trace IDs are in [premier-model-evaluation.json](premier-model-evaluation.json); the workbook can consume [premier-runs.json](premier-runs.json) and [premier-jobs.json](premier-jobs.json).

**Grok 4.6 medium is the most balanced completed-research baseline here: materially richer operating voice than Muse medium/high, much faster than Grok 4.7 high, and both researcher-owned pages survived. Grok 4.7 high has the deepest directly sourced account record, but also overclassification, peripheral material and a missing researcher-written account page. Muse xhigh is a promising fast account result; its person job is not a quality test because storage failed before dossier formation.** None completed the full account-plus-person lifecycle cleanly. None justifies a universal model ranking from finding count or nominal effort.

## Comparability and boundaries

These are actual platform outcomes, not identical-input replay experiments. The seller is Insight Health and the target is Premier Gastroenterology of Little Rock. Subsequent Muse/Grok4.7 runs reused the same Head briefing and six retained seller/product/ICP/persona documents, revision24, one worker/two slots and one-person cap. The pinned persona lineage remained advisory. Grok4.6 r24 generated a fresh Head briefing and ran before the focused reconciliation implementation; its final account dossier has material added by continuations.

Muse original run04 was often called “default,” but the outgoing SDK request explicitly contains **medium reasoning**. High and xhigh are requested settings, not proof of a measured quantity of hidden reasoning. Provider compatibility adapters differ: Muse required automatic tool selection and reduced nested schema exposure, with validation retained locally. The narrative-version error fix landed before Grok4.7/high and Muse/xhigh; its absence in earlier Muse is a lifecycle confound. Live Exa discovery differs between runs. Muse medium/high selected Beth Smith; Grok runs and Muse xhigh selected Todd Greer. Those person results cannot be scored as the same task.

Grok4.6 started 27 September UTC, which was already **28 September in Asia/Kolkata**. It belongs in the user's “today” comparison, with that date qualification. Its initial52 findings must be compared with other initial dossiers, not its later60-findings reconciled state. The JSON preserves both counts.

## Time, cost and delivered output

| Run | Account elapsed / findings | Person elapsed / findings | Researcher pages | Recorded total USD | AI Ark credits |
|---|---|---|---|---:|---:|
|Grok4.6 medium r24|16m31.16s /52initial,60latest|Todd13m54.83s /37|Account and Todd|12.513690|3.1|
|Muse medium run04|7m38.65s /19|Beth cancelled; no dossier|Account only|2.544894 known subtotal|2.1|
|Muse high run05|7m05.39s /26|Beth9m11.28s /19|Account; Beth draft unpublished|4.187004|2.1|
|Grok4.7 high run06|29m40.26s /68|Todd24m55.29s /46|Todd; account later supplied by Muse reconciliation|10.747615|0.1|
|Muse xhigh run07|7m31.45s /30|Todd infrastructure failure after4m41.49s; no dossier|Account only|2.797811|1.6|

Elapsed includes investigation, JSON assembly/import, narrative and finalization recovery. Account/person overlap: do not add their durations. Grok4.6 reaches last person terminal at27m57.66s but continues until operator worker shutdown around31m22s; Muse high14m32.44s; Grok4.7 reaches person terminal at51m38.81s, with final no-op reconciliation about7seconds later. Muse medium was cancelled25m48.54s after account start; this is not a completed end-to-end duration. Muse xhigh reaches failure11m03.17s after account start, not a successful latency benchmark.

Grok4.6's total includes account model$4.802460, Todd model$3.272500, old account continuations$4.125880, fresh Head$0.104850 and Exa$0.208. Excluding the old continuations leaves$8.387810 recorded across other categories; this does not imply every Exa cent was exclusively initial research. Muse-high total comprises researcher models$3.905629, Exa$0.180, focused reconciliation$0.100531 and preflight$0.00084375. Grok4.7 comprises models$10.384506, Exa$0.206, Muse reconciliation$0.15531075 and preflight$0.0017984. Muse-xhigh includes$0.1167012 in two model calls recovered only from Langfuse after DB recording failed, counted once.

Muse-medium's pending person Exa request has unknown final billing; its total is a recorded lower-bound subtotal. Setup01 separately spent$0.118116 generating the reusable Head briefing; that should be counted once in experiment overhead, not once per reused run. Setup01–03 did not execute research tools: provider age-attestation403, unsupported tool-choice mode, then excessive nested-schema depth. Unreported model charges are unknown, not asserted free. No run exercised Deepgram/transcription; AI Ark credits have not been converted into dollars. Grok4.7's low credits partly reflect a refused person lookup, not more efficient successful enrichment.

## Account quality: evidence that changes the comparison

| Substance | Grok4.6 medium | Muse medium | Muse high | Grok4.7 high | Muse xhigh |
|---|---|---|---|---|---|
|Official Open Access, referral/fax and24–48h callback workflows|Strong detail|Core retained|Core retained|More separately attributable detail|Core retained|
|Todd MedEvolve operating voice|Multiple useful quotations|Not substantive in dossier|Acquired but omitted|Rich direct-source quotations|Recovered with direct references|
|Greene2019 productivity/access quotation|Retained F043|Acquired but omitted|Retained F061 via Exa-report reference|Retained F091 direct original source|Not retained|
|Recent jobs and operating duties|July hiring plus procedural detail|Bundled summer hiring|Three useful scheduling/endoscopy/billing roles|Equivalent summer-role detail not found in targeted acquired-record scan|Scheduling/endoscopy roles separated; billing absent|
|Patient anecdote: repeated reminders/delayed portal results|Not established in this audit|Not highlighted|Retained with individual-report caveat|Equivalent acquired passage not found by targeted scan|Not retained|
|External-record abstraction into EMR|Not established in this audit|Not highlighted|Not found in targeted acquired scan|F064 useful, affiliation/date uncertainty retained|Not highlighted|
|Coverage/insurance and medical-record policy|Useful prep/admin detail|Lighter|Lighter|Expanded, sometimes overflagged as conflict|Coverage retained, some bundling|
|Identity/history/property|Meaningful current/stale leadership distinction|Compressed estimates|Compressed estimates|Most detailed; excess peripheral history|Useful namesake caveats but weak statuses|

“Not retained” is not automatically an extraction omission: the run may not have acquired that source. The high-confidence loss case is **Muse-high MedEvolve**: the exact provider excerpt exists, but its operating voice does not appear in authored findings or initial/final account narrative. [Evidence card](../research-model-comparison-20260928/evidence/muse-high-medevolve.md). Likewise, original Muse-medium's selected-source audit found Greene's quotation available but absent. These are stronger model-selection findings than comparing what separate web searches happened to return.

Conversely, Muse-high discovered valuable summer hiring and patient-experience evidence that Grok4.7 did not preserve because a targeted exact-phrase scan did not find it in the acquired account corpus. This is a discovery difference, not proven Grok extraction loss. [Scheduling evidence](../research-model-comparison-20260928/evidence/muse-high-scheduling-job.md), [patient report](../research-model-comparison-20260928/evidence/muse-high-patient-review.md). Neither an old third-party job listing nor a single patient review establishes a live vacancy or systemic operational failure.

Grok4.6's actual initial dossier retains unusually useful wording: Todd describes analytics avoiding paralysis, comparing workload with professional standards, showing physicians anticipated Medicare revenue pressure, and using KPI reports in recruiting. Greene's2019 observation links demographics and encounter-based delivery to productivity pressure. These support concrete seller discussion, with historical dates, beyond generic “GI practice has paperwork.” Some records bundle unrelated details: F025 combines prep, transport, cancellation, visit length and author metadata; F032 aggregates several MedEvolve measures; F043 combines quote and redevelopment history. These survived but are not ideal independently correctable units.

Grok4.7 strengthens original-source navigation: none of its68 account findings uses the Exa-report artifact as its authored reference. Muse-high uses that report in11of26 findings, leaving key hiring/patient/Greene narrative points without direct outward URLs. This is a researcher reference-selection problem, not an importer loss. Grok4.7 also discovers an explicit external-record abstraction workflow, appropriately insufficient-context pending affiliation/date confirmation. That is richer seller-relevant investigation, although it cannot establish current software deployment or purchase intent.

Muse-xhigh improves the most consequential Muse-high weakness: F020/F023 retain MedEvolve voice directly, F015/F016 separate job evidence, and F017 finds a referral specialist. But it loses some different useful findings, including Greene's quotation and the patient anecdote. It is not “high plus everything”: the evidence trade-off persists. Account-model cost$1.544780 and7m31s are attractive, but quality still needs semantic revision and a clean person test.

## Classification, unsupported meaning and granularity

All three Muse account dossiers mark every finding supported:19/26/30. That is not evidence of superior certainty. Muse-medium F011,F018,F019, Muse-high F031,F040,F071 and Muse-xhigh F008,F021,F026,F028,F029 include research non-discovery or completeness assessments in factual account records. “We did not find the EHR” should be a research limitation, not a supported claim that the account lacks one. Muse-high F072 places product-coexistence reasoning inside factual text. Xhigh F025 infers committee responsibilities and F022 adds a BAA/legal inference. These fail the agreed observation/reported-statement versus optional-interpretation boundary.

Grok4.7 uses38supported/21potential_conflict/7insufficient_context/2wrong_entity. This shows more visible qualification, but excessive conflicts are a problem: planned versus completed buildings, clinic area versus entire plaza area, changing lenders, and clinical eligibility versus insurance coding can coexist. F013 links its development-cost conflict to unrelated F021staff/revenue estimates. Grok4.6 also needs restraint about stale leadership versus distinct roles, but its initial/current-source treatment is generally more useful than blanket qualification.

Bundling occurs across models: Muse-medium F017 merges jobs and chamber activity; Muse-high F030 merges three jobs and F012 combines differing scale estimates without relationships; Grok4.7 F021combines estimates/technologies, F030locations/hours, F060multiple executive points; xhigh F013policy material andF017multiple people. Model/schema validity does not establish atomicity.

Grok4.7 F034 consumes AIArkSEO prose. Both Muse-high and Grok-high projected enrichment artifacts expose `summary.seo`, so this is a **shared input-filter leak plus a model-use lapse**. Do not misclassify it solely as a Grok skill-reading issue. Imported text/attribution/review/source fields matched authored findings in all45 Muse-high and114 Grok-high records checked. That verifies faithful import, not factual correctness or source completeness.

## Person depth: preserve the different-subject distinction

Grok4.6 and Grok4.7 both investigated Todd. Grok4.6's37 findings include five rich operating-voice records around analytics, physician reporting, reimbursement pressure and hiring. Grok4.7's46 retain six individually organized MedEvolve passages plus a2024program listing,2025lease association and2026ribbon-cutting mention. They distinguish some namesakes and uncertain background. Neither demonstrated a reliable outside-work/hobby discovery or independent long-form media beyond the historical testimonial. A program listing is evidence of being listed, not what Todd said or whether he attended.

Grok4.7's additional count partly represents irrelevant person ownership: company boilerplate, property records about other speakers and someone else's retirement comment enter Todd's dossier. Grok4.6 also bundles multiple metrics/quotations in a single voice record. More findings therefore do not directly establish better person understanding.

Muse-high's19 Beth findings preserve genuine specificity—prior scope of18entities/100+providers,15physicians/45FTEs, policy/quality duties and substantial endoscopy administration experience. That is useful operational context. But F031duplicatesF010; F040repeats a broad career summary; F003company intake andF042another person's role are not Beth claims. The account's nomination overstates direct ownership of front-door operations. No strong independent voice or outside-work depth was established, but her public footprint may be thinner; we cannot attribute the difference solely to model capability.

Muse-medium has no authored Beth dossier because the user cancelled a long-running Exa call. Muse-xhigh has no authored Todd dossier because Postgres volume exhaustion interrupted processing after Exa returned. Do not evaluate raw Exa content as the person agent's finished work or label either missing dossier a model semantic failure.

## Narrative quality and completion are separate

Muse-medium/high/xhigh all wrote initial account narratives quickly. They explain the clinical practice and map intake/referral processes to Insight Health's three products, often more readably than an exhaustive facts dump. High's weaknesses include repeating workflows, burying Greene's voice in Miscellaneous and unsupported suggestions that every channel converges on physician review. Xhigh sometimes describes expired hiring evidence as current, loses the historical-use qualification around MedEvolve and packs Miscellaneous into a large paragraph.

Grok4.6 produced both account and Todd pages, preserving more public voice but adding lengthy caveats and repeated operational detail. Its final account page also reflects old continuations; use `account-initial/page.md` when scoring the initial agent.

Grok4.7 wrote Todd's narrative, not the initial account narrative. Its final account page was created by the separate **Muse focused-reconciliation model** because no prior page existed. It must not be credited to Grok4.7's writing quality. Todd's published page keeps source dates and useful quotations but includes repeated caveats and company-level material. Muse-high Beth's draft never published because the narrative tool required an account dossier version; old feedback described the missing argument as a changed parent. Grok4.7 repaired that error with improved feedback, then corrected an invalid retry reference.

Grok4.6 and Grok4.7 Todd jobs finally failed with committee references belonging to the parent account, despite saved research and narrative. Grok4.7 account failed finalization because `/outputs/research.json` was absent. These are delivery/recovery defects; they do not erase valid output, and successful output does not mean the lifecycle succeeded. Both recent focused reconciliations used one paid call then a no-op settlement, not repeated paid research. Grok4.6's older reconciliation behaved differently and inflated cost.

## Where extra time went

Grok4.7 used89account/82person model calls compared with Muse-high55/61; model-latency sums were1642/1335seconds versus315/444seconds. Grok performed164/128file reads and39/37local evidence searches versus Muse50/49reads and no local evidence search. Most additional reads were distinct pages or pagination rather than identical rereads. Both used parallel batches: Grok61of86 account batches and44of80 person batches had multiple tools; Muse20of54 and20of60. This does not show that batching degraded quality.

Grok4.6 spent7m41.76 between first formation marker and account import, then1m53.80 to narrative. Its person formation/import2m43.51 and narrative4m41.54. Muse-high account1m19.92 and1m19.00; person2m00.83 then failed narrative recovery. Xhigh account1m13.78 and40.02seconds. Dossier assembly, navigation and repeated repair are real costs; import itself was only seconds in r24. Do not treat all job elapsed as provider research or sum overlapping model/tool times as an exact decomposition.

The17-minute pending Exa call was specific to original Muse-medium Beth. Later deep calls completed on their first attempts in roughly35–54seconds. Those later timing improvements cannot be attributed to model reasoning alone.

## What this comparison supports doing next

1. Use the existing shared standard; do not write a different complete skill for every model based on one sample.
2. Evaluate source-to-finding public-voice retention on the **same retained corpus**, particularly MedEvolve/Greene and the hiring/patient evidence. This distinguishes selection weakness from live-search variance.
3. Correct research-gap records, wrong-subject findings, overbroad bundles and non-conflicting historical variants. Valid JSON and high counts are inadequate acceptance criteria.
4. Ensure direct source references and preserve date/attribution qualification into the page. Compare initial researcher narrative separately from Muse reconciliation.
5. Repair lifecycle completion/version/subject-reference handling before measuring “cost to a complete result.” Do not spend more research merely to replace missing finalization.
6. Complete a storage-healthy Muse-xhigh person test before drawing person-quality conclusions; its partial run cannot serve that purpose.

The strongest evidence for Muse remains account speed/cost and useful discovery breadth. The strongest evidence for Grok remains operating-voice detail and original-source handling. The most practical baseline across these historical trials is Grok4.6medium, with Muse-xhigh account deserving further controlled evaluation—not a claim that every Grok4.6 run is better or that xhigh has solved completeness.

## Evidence and trace entry points

- [Earlier detailed high-versus-high comparison](../research-model-comparison-20260928/COMPARISON.md), [xhigh audit](../research-model-comparison-20260928/XHIGH.md).
- [Grok4.6 initial account dossier](../arv4-insight-premier-20260928-r24/account-initial/dossier.json), [initial page](../arv4-insight-premier-20260928-r24/account-initial/page.md), [original report](../arv4-insight-premier-20260928-r24/REPORT.md).
- [Muse-medium account dossier](../arv4-insight-premier-muse-20260928-run04/review/c80f26cc-33e8-5529-b018-84f06ccbb325/dossier.md), [cancellation](../arv4-insight-premier-muse-20260928-run04/CANCELLED.md).
- [Muse-high account dossier](../arv4-insight-premier-muse-high-20260928-run05/review/c80f26cc-33e8-5529-b018-84f06ccbb325/dossier.md), [Beth dossier](../arv4-insight-premier-muse-high-20260928-run05/review/ce2ce4f1-ab74-5f41-b739-6dd5a201088e/dossier.md).
- [Grok4.7 account dossier](../arv4-insight-premier-grok47-high-20260928-run06/review/c80f26cc-33e8-5529-b018-84f06ccbb325/dossier.md), [Todd dossier](../arv4-insight-premier-grok47-high-20260928-run06/review/6bc03f41-fd75-5ce8-998d-6ec983efd86c/dossier.md).
- [Muse-xhigh account dossier](../arv4-insight-premier-muse-xhigh-20260928-run07/review/c80f26cc-33e8-5529-b018-84f06ccbb325/dossier.md).

Every job's trace ID and raw model-receipt path is in the JSON. Remote audits matched116/116Muse-high researcher observations and23/23provider attempts;171/171Grok-high and27/27providers;106/106persisted xhigh model observations plus2remote-only and23/23providers. These establish the checked records, not universal callback completeness. This report summarizes observable activity, prompts, queries, evidence and outputs; it does not expose or reconstruct private chain-of-thought.
