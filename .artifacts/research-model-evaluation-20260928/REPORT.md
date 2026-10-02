# Research model evaluation — 28 September 2026

**My recommendation is to retain Grok 4.6 at medium as the current quality baseline. Muse deserves further evaluation, especially xhigh for account work and max for person depth. The evidence does not justify switching the full pipeline to DeepSeek or GLM yet, or paying for Grok 4.7 high as the default.** This is a conclusion about these runs, not a universal model ranking.

The workbook now covers **13 research attempts across Insight Health → Premier Gastroenterology and Clue → Zafran**, plus three Muse setup failures. The latest addition includes a full [Muse xhigh versus Grok quality review](MUSE-XHIGH-QUALITY.md) and GLM retry final status/artifacts. GLM selected Tom/Sanaz instead of Nick/Vari; its different-person output has not received the same semantic comparison. The runs used isolated databases and workers in the Jerusalem checkout; these are two seller/account contexts, not two different production deployments. The earlier Grok 4.6 Premier run began September 27 UTC, already September 28 in India.

Known recorded spend is **$86.984282 plus 32.3 AI Ark credits**, including the shared Muse Head-brief setup once and both latest retries. This is not a final invoice total: the cancelled Exa request, an interrupted legacy continuation, and failed/unpriced Grok requests leave billing uncertainty. No research or model calls were purchased to prepare this report.

## Deliverables and how to inspect them

The accompanying workbook has Runs, Jobs, Costs, Quality, Failures, Outputs, Trace metrics and Method sheets. It provides job timestamps, phase timing, model calls/tokens, cost components, failure evidence, and direct links to saved JSON dossiers, readable dossiers, published narratives, raw-source manifests and Langfuse executions. Missing outputs are explicitly marked. Local links require the artifact directories on this Mac; Langfuse links require project access.

- [Premier detailed quality review](PREMIER-QUALITY.md): five attempts, account workflow/voice/identity evidence, person comparisons and narrative fidelity.
- [Zafran detailed quality review](ZAFRAN-QUALITY.md): 20 substantive probes across Grok 4.6, Muse max and DeepSeek, with exact finding IDs.
- [Exact Zafran evidence](quality-evidence.json) and [Premier evidence observations](premier-quality-observations.json): acquired passages, authored findings and source locations.
- [Zafran failure analysis](FAILURES-ZAFRAN.md): provider, runtime, model-behavior and operator causes kept separate.
- [Latest Muse xhigh quality review](MUSE-XHIGH-QUALITY.md): all 109 authored findings, 20 comparative probes, wrong-employer attribution, source omissions and citation support. [Exact evidence](muse-xhigh-quality-evidence.json).
- [Latest GLM final status](../zafran-muse-xhigh-glm-retry-20260928/glm53-medium/FINAL-STATUS.md): saved outputs and final failures; different-person quality not fully graded.

The trace material exposes observable requests, research assignments, source choices, tool calls, corrections, milestones and costs. Reasoning effort is recorded, but private chain-of-thought is neither reproduced nor inferred. Requesting “max” does not establish an equivalent reasoning budget across providers.

## Run outcomes, duration and recorded cost

“Research wall” runs from the first account job start to the last research-job outcome, including dossier assembly, import, narrative and recovery. “Total observed” adds subsequent reconciliation or operator termination. These are elapsed durations, **not sums of overlapping account and person jobs**, and a failure endpoint is not successful completion.

| ID | Scenario and model | Effort | Research wall | Total observed | Known USD | Saved result |
|---|---|---|---:|---:|---:|---|
| P1 | Premier — Grok 4.6 | medium | 27m58s | ~31m22s | $12.513690 | Account and Todd dossiers/pages; Todd completion error; old continuations |
| P2 | Premier — Muse 1.3 | medium | 25m49s | 25m49s | $2.544894 subtotal | Account dossier/page; Beth cancelled during pending Exa |
| P3 | Premier — Muse 1.3 | high | 14m32s | 14m32s | $4.187004 | Account and Beth dossiers; account page; Beth page unpublished |
| P4 | Premier — Grok 4.7 | high | 51m39s | ~51m46s | $10.747615 | Account/Todd dossiers, Todd page; account page later written by Muse |
| P5 | Premier — Muse 1.3 | xhigh | 11m03s to storage failure | 11m03s | $2.797811 | Account dossier/page; Todd interrupted before dossier |
| Z1 | Zafran — Grok 4.6 | medium | 30m13s | 30m16s | $12.653226 | Account, Nick and Vari dossiers/pages; person finalization errors |
| Z2 | Zafran — Grok 4.7 | medium | 26m37s | 26m37s | $4.088172 | 30 draft findings; provider capacity failure; no import or pages |
| Z3 | Zafran — GLM 5.3 initial | medium | 3m42s | 3m42s to natural failure | $1.261587 | Sources/Exa report only; wrong nominations; no authored dossier |
| Z4 | Zafran — GLM 5.3 untouched retry | medium | 2m21s | 2m22s | $0.794624 | Sources/Exa report only; output truncated; no authored dossier |
| Z5 | Zafran — DeepSeek v4 Pro 0813 | high | 56m21s | 57m55s | $8.413757 | Account and Nick dossiers; Vari incomplete; no pages |
| Z6 | Zafran — Muse 1.3 | max | 34m20s | 36m03s | $13.141414 | All three dossiers; account page; contact pages unpublished |
| Z7 | Zafran — Muse 1.3 retry | xhigh | 16m11s | 18m45s | $6.540534 | All jobs and pages complete; reconciliation recovered; attribution and coverage defects remain |
| Z8 | Zafran — GLM 5.3 retry | medium | 38m23s | 39m57s | $7.181837 | Account/Tom/Sanaz dossiers and pages; account/reconciliation need review; wrong comparison people |

Separate setup01 Head-brief cost: **$0.118116**, counted once. Setup01–03 failed before research tools because of age attestation, unsupported tool-choice mode and nested tool-schema depth respectively. No priced research usage was recorded for those attempts; that does not certify a zero provider invoice.

These cost totals are not interchangeable workload prices. Premier requested one person; Zafran requested Nick and Vari. P1 includes **$4.125880** of old account continuations and **$0.104850** of fresh Head briefing. Removing only its old continuation model cost leaves **$8.387810** in other recorded categories. Later runs reused a brief and used a separate focused reconciler. Z2, Z4 and Z5 did not finish comparable work, so their low totals cannot establish cost efficiency.

## What the finished research actually looks like

### Grok 4.6 medium: strongest balanced baseline

For Premier, the initial account dossier preserved Todd's concrete operating voice about analytics, workload visibility, physician reporting, reimbursement pressure and recruiting. It also retained the older Greene productivity/access quotation. Todd's own dossier expanded that material rather than merely repeating his title. Account research took **16m31s**, Todd **13m55s**; both researcher-written pages survived.

For Zafran, Grok retained the complete Monday BDR automation chain, Vari's ABM mandate, lean execution requirements, “shipping real workflows,” hackathon speed, and specific Exposure Gateway/Zero Day Agent mechanisms. Nick's research added both distinctive field-marketing concepts, the concrete AI-control warning, Cocktail Chemistry/book/audience evidence and an actual transcribed interview. Account **15m45s**, Vari **13m24s**, Nick **19m11s** overlap within the roughly30-minute run.

This is not a clean pass. Some acquired statements only reappear in the person dossier, some never appear; independent facts are still bundled; company/colleague facts enter person records; and narratives are too long in places. Internal ICP scoring labels leak into display prose. Both person jobs formally failed because their completion reports included account-owned claim references, even though dossiers, imports and pages were saved.

### Muse medium/high: fast and useful, but selective in the wrong places

Premier Muse medium/high quickly captured the important Open Access, referral, fax, intake and callback workflows. High also retrieved useful recent hiring and a qualified patient-experience anecdote that Grok 4.7 did not find in the inspected corpus. Its initial account page was concise and commercially understandable.

The strongest negative evidence is **not** its lower finding count: Muse high had Todd's MedEvolve excerpt available and omitted the substantive executive voice from both dossier and account narrative. Some findings cited the Exa report instead of the original page, reducing direct source access. All account findings were marked supported despite research gaps and interpretive statements being mixed into factual records.

Beth's high-effort dossier had valuable prior operational scope—18 entities,100+ providers,15 physicians/45 FTEs—but remained primarily a profile expansion, without strong independent public voice or outside-work depth. Beth and Todd are different people with different public footprints, so this does not isolate model capability.

The original run was **medium on the actual request**, not an unspecified default. Its prolonged Exa wait and user cancellation are separate from dossier-selection quality. High's missing Beth page also involved an inadequate narrative-version tool contract and misleading feedback.

### Muse xhigh: promising account economics, incomplete evidence on people

The Premier account result recovered important MedEvolve operating voice with direct references, in **7m31s** at **$1.544780 account-model cost**. It also separated useful hiring evidence more clearly. That is an attractive result relative to both Groks.

It did not preserve every benefit of high: Greene's quotation and the patient anecdote were absent, and unsupported gap/role/legal statements still entered findings. Live search results and runtime fixes also changed, so this cannot be attributed entirely to reasoning effort. Todd's job stopped when the Postgres Docker volume filled; it supplies **no completed person-quality comparison**.

### Muse max: genuinely strong person discoveries, without a demonstrated cost advantage

Muse max's Nick dossier followed older authored product-marketing work into distinctive principles about empathy, storytelling, technical curiosity and credibility. It explored CocktailGPT beyond a profile listing. Vari's investigation followed credential-validation pages and preserved employer-specific tooling history. Those are real strengths missing from the other saved dossiers.

Its account investigation was less dependable on broad coverage and freshness: no specific Gateway/Zero Day findings, missing contrary finance/departure reporting, a stale CPO claim, and an unsupported implication that hiring argues against retrenchment. The account page described manual BDR research, while later Nick research showed existing automation. That makes correct reconciliation consequential, not cosmetic.

Account **15m07s**, Nick **15m46s**, Vari **23m07s**; total recorded cost **$13.14**, slightly above Grok4.6's Zafran run. Neither contact narrative published. A confirmed person-lookup backend bug overwrote parent references for both contacts; failed narrative and reconciliation contracts compounded the outcome. This is not proof that Muse cannot write those pages, but it also is not a cheaper complete result.

### Grok 4.7: more detail did not consistently mean more value

Premier high produced the deepest directly referenced operating record: richer MedEvolve quotations, original policy details and a useful external-record-abstraction lead. None of its68 account findings used the Exa report as its authored source reference. However, extensive property history diluted relevance,21 potential-conflict tags included compatible historical facts, and some relationship targets were wrong. Todd's46 findings also included company and other-person material.

The account took **29m40s** and Todd **24m55s**, with more source navigation, evidence searches and drafting work. The account researcher never saved its own narrative; a separate Muse reconciliation call later supplied the account page. That final page is not evidence of Grok4.7's narrative quality.

The Zafran medium draft contained promising ABM, BDR, Outreach and public-statement details, but capacity failure stopped it before final review. The later availability check also failed. It cannot be scored as a finished research result.

### DeepSeek high and GLM medium: insufficient completed delivery

DeepSeek produced useful account and Nick material, including the automation chain, product changes, finance counterevidence and book/hobby detail. But it compressed concrete AI-risk wording into generic guardrails despite having acquired the passage, mixed tool requirements with deployment, and reconstructed an unsupported reporting hierarchy. Vari never produced a dossier, and no narratives were saved. Its roughly58-minute overall result is neither a faster alternative nor proof of cheaper equivalent quality.

GLM retrieved useful sources, but neither attempt produced an authored claim dossier. The first nominated the wrong people concurrently. The fresh untouched retry hit a16,384-token output truncation, followed by missing-output finalization handling. Exa's intermediate report is available, but it is not the agent's finished dossier. These runs establish delivery/contract failures, not a fair verdict on finished prose quality.

## Findings that matter across models

1. **Public wording remains a substantive differentiator.** Grok Nick preserved the two specific harms in the AI warning. Muse retained one more clearly; DeepSeek retained the general theme. A correct topic label is not equivalent to preserving the useful signal.
2. **All three major Zafran dossiers omitted Sanaz's acquired “5X in new $$$$$” wording.** Its metric is ambiguous and should stay attributed, but ambiguity does not justify silently losing the statement. No model solved coverage.
3. **Person research can recover an account gap.** Nick restored material omitted or undiscovered at account stage. Initial account pages and reconciled pages must therefore be judged separately.
4. **JSON validity and exact import are mechanical successes, not semantic guarantees.** Bundling, wrong ownership, research gaps as facts, exaggerated conflict and interpretation leakage remain across models.
5. **One model's extra sources do not prove another discarded them.** The review labels acquired-but-omitted separately from not-found-in-acquired-material and incomplete output. The20-probe comparison is targeted, not a claimed exhaustive loss percentage.

## What the traces say about time

Grok4.7 Premier used89account/82person calls,164/128file reads and39/37local evidence searches, compared with Muse-high55/61calls and50/49reads. Most extra reads were different pages or pagination, not identical repeated requests. Both batched tools. There is no evidence here that batching itself caused poorer quality.

Dossier formation and completion are material: Grok4.6 Premier account spent **7m42s** from its first observed formation call to import, then **1m54s** to saved narrative. Muse-high account took **1m20s** and **1m19s** for those boundaries; xhigh about**1m14s** and**40s**. The import transaction itself was much shorter. These boundaries are not a measure of hidden thinking or an exclusive split of model versus tools.

DeepSeek Nick's long finish involved source navigation, dossier writes and failed completion work; its last stretch did not represent continuous new provider research. Conversely, original Muse Beth really was waiting on a long provider call. Later Premier deep calls completed in roughly35–54seconds on their first attempts. Treat those as different latency problems.

## Decision and next work

**Keep Grok4.6medium as the baseline today.** Its combination of public voice, useful specifics, source handling and delivered artifacts is the most convincing across both scenarios. This is a quality baseline, not a claim that all lifecycle defects are resolved.

**Keep Muse in contention.** Premier xhigh deserves a storage-healthy person evaluation; Muse max deserves a fixed-evidence fidelity comparison because its unique person discoveries are valuable. The latest max run does not demonstrate a lower total cost.

**Do not buy another broad benchmark merely to replace missing completion.** First repair or replay the deterministic failures against saved state: completion ownership, parent-reference preservation, missing-output recovery, narrative contracts and reconciliation response validation. Separate provider capacity/truncation behavior from semantic quality. Then use the same retained sources to compare public-statement preservation, factual units, uncertainty and attribution. Fresh runs remain necessary later to assess discovery, but they should not be the first way to test these existing failures.

The current evidence supports a focused next comparison, not another wholesale rewrite of the shared skills or a separate full prompt for every model.
