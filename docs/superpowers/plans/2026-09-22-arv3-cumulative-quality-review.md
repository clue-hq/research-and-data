# Cumulative research-quality review: Premier v1 and Probook/Zafran v3

**Status:** discussion and design recommendations, not an approved implementation spec.
**Date:** 2026-09-22. **Code inspected:** `62736c8a8` / implementation `5c0b9b912`.
No application changes, paid research, service restarts or database writes in this review.

The founder supplied the side-agent's Premier audit to compare with the completed v3 experiment.
The evidence supports improving the existing v3 lane: its new acquisition capabilities work,
while several older extraction and presentation weaknesses survive. Moving to a Deep Agent
can give an account a clearer owner and specialists with useful correction tools; changing the
framework alone does not repair the observed data or context contracts.

## Evidence and comparison limits

- [Premier historical audit](../../../.context/arv2-premier-comparison-2026-09-22/REPORT.md):
  retained v1 requests/responses, plus two modified PoC-style extraction experiments. The latter
  are not an unchanged historical PoC or a controlled framework comparison.
- [Probook/Zafran v3 live comparison](2026-09-22-arv3-live-poc-comparison.md): two accounts,
  eleven people, four separate recovery repeats, durable claims/provider receipts and exported
  job-attributed traces. The display worker and browser pages were not exercised by that test.
- These are different sellers, accounts, dates and evidence sets. Comparing failure mechanisms
  is justified. A numerical v1-to-v3 quality uplift or complete information-loss percentage is not.
- Historical PoC rows can themselves be wrong. Reproducing every PoC claim is not the target.

### Additional read-only verification in this review

The Premier side audit could not connect to the database. This review successfully read the
exact workspace database `clue_jerusalem-v1`, without changing it:

- Run `0168a8c9-5634-56f7-a05f-70a0c274a1c4`; account job
  `3af5ab7a-7c46-5e79-978d-eaff79263626`. Both are completed.
- Profile digest `24fdd66515ff10f2ec4b9334b0999830541eb515362ed283f4d5e8823e67dd20`
  exactly matches the account **v1** resources. The model ledger identifies `x-ai/grok-4.6`.
- The Exa call joins this exact job: internal call `3311bf8b-bdb2-4763-996a-90118af72c6c`,
  provider request `576e5baeca33843c3a35894e20d381a1`. The ledger records trace
  `df7996c92dd5967aeffbce75cb3b57f3` and observation `4b69d8c3daf6d850`.
  This closes the database join; this review did not re-export the remote Langfuse trace.
- The account has 81 workspace-scoped stored claims: 77 from this historical run and four from
  another run. None has `superseded_by` set in the captured snapshot.
- The incorrect Klara claim `6269a76e-f7ac-4dfb-86cb-8d00cfdd35a4` remains unsuperseded,
  `outreach_safe=true`, with `evidence_verbatim=NOT_FOUND`. The agent did write a correction
  `dd44dc49-7bf6-4192-9950-7a4a1b2b2cf8`, explicitly saying not to treat Klara as evidenced.
  That correction carries only `corrects_claim_id`; both rows remain live. This does not prove
  both are currently displayed, but does establish the same ineffective supersession as in v3.
- The misfiled physician certification, Newsweek ranking and charity committee examples also
  remain stored and unsuperseded. Their exact quotations do not establish their assigned meaning.

Private evidence: `.artifacts/arv3-cumulative-quality-20260922/premier-readonly-db.json`.
The supplied `.context/` audit remains untouched.

## What the current pipeline actually does

1. The account agent plans research, creates Exa's charter/probes, reads the returned report,
   selects additional sources and chooses the material to extract. It currently uses
   [`create_agent`](../../../platform/api/clue_api/arv2/account_research_agent.py#L406).
2. [`research_deep`](../../../platform/api/clue_api/arv2/account_research_tools.py#L1859)
   calls Exa deep-reasoning with identity and evidence instructions. Its report is synthesized
   research, not a claim-store insert or automatically verified primary evidence.
3. [`structure_material`](../../../platform/api/clue_api/arv2/account_research_tools.py#L1936)
   supplies the parent-selected source blocks to a separate model call. The observed model is
   GPT-5-mini. Parsed drafts are written by code. This is a leaf call, not a specialist agent
   with its own investigation loop. The parent can also write claims directly. Deterministic
   provider mapping is another claim-producing path and should remain code.
4. Display runs separately after account settlement or on demand. Its section recipes select
   claims; Luna writes concise page copy. The historical Premier model is `openai/gpt-5.6-luna`.
   It is not the claim extractor. The current scheduler also preserves independent page work;
   person-job completion itself does not enqueue contact pages.
5. The onboarding synthesis Deep Agent is a different stage: it produces ICP/persona documents.
   Its [prompt](../../../platform/agents/catalog/prompts/onboarding-synthesis/v2/SYSTEM.md#L12)
   names the seller through its knowledge files. Premier's pinned ICP has the right products;
   the demonstrated wrong seller proposition enters later, in display context assembly.

### Full Exa report versus extraction input

This review inspected the original v3 provider artifacts, including saved request bodies,
rather than relying on truncated trace payloads.

| Account / version | Exa report characters / results | Source blocks per extraction call | Ordinary extractor rows |
| --- | --- | --- | --- |
| Premier v1 | 14,304 / 19 | 12 + 12 + 5 | 34 |
| Probook v3 | 14,932 / 20 | 12 + 4 | 19 |
| Zafran v3 | 15,131 / 20 | 12 + 4 | 27 |

None of these account extraction requests contains the complete Exa report; for the v3 requests
this was checked with both literal and whitespace-normalized matching. The parent selected source
blocks instead. This is not itself an extraction defect: quoting the underlying page is often
better than quoting Exa's synthesis. The missing contract is a record of which relevant findings
were processed, left unresolved, deliberately excluded or never handed off. Additional direct
agent writes and deterministic mapping mean these extractor counts are not total claims or recall.

Private analysis: `.artifacts/arv3-cumulative-quality-20260922/v3-exa-to-structuring-summary.json`.

## Combined finding register

| ID / area | Premier v1 evidence | v3 evidence / limit | Conclusion |
| --- | --- | --- | --- |
| CQ01 — Committee discovery | This audit is account extraction/display, not a controlled committee benchmark. | Company-bound SMART searches worked; Probook found all five historical people. Zafran selected three historical people plus a useful new member. | Preserve v2 discovery inside v3; no claim of universal coverage. |
| CQ02 — Media use | Modified Premier PoC experiment did not test media. | Eight transcripts; native video/audio, embeddings, hybrid retrieval and reuse worked. No substantive transcript-linked account claims, and no safe person transcript claims in the original run. | Acquisition improved relative to the earlier missing integration; usable evidence conversion remains open. |
| CQ03 — Evidence coverage | Full Exa report absent from three extractor inputs; richer findings not all represented there. | Same selected-source handoff in four account extractor calls; important person findings sometimes missed or represented weakly. | Make complete artifacts available with explicit processing coverage; do not force every sentence into a claim. |
| CQ04 — Catalog contamination | Klara field description became quoted evidence. | George's founded-company wording entered the shared catalog, then appeared on other people, including after identity-corrected recovery. | Shared product defect. Neutral definitions; observations stay in subject-scoped evidence. |
| CQ05 — Field/entity meaning | Ranking/certification → accreditation; charity committee → ACE membership; vendor/customer direction reversed. | LinkedIn post → X URL; work tradition → hobby; degree → high school; another person's business → founded companies. | Exact substring checks are insufficient. Review entity, relationship direction, field meaning and time. |
| CQ06 — Effective corrections | Klara error and correction both remain live in today's read-only snapshot. | Wrong founded-company rows remain unsuperseded; stale headcount remains the current scalar despite prose warnings. | A correction must change the applicable read result and invalidate affected summaries. |
| CQ07 — Seller context and presentation | Correct clinical ICP but ABM-platform pitch sent to Luna; fit assessments routed to watch-outs; fixed recipes omit detail. | Display pages were not tested; the inspected shared context/recipe code still has these mechanisms. | Confirmed Premier failure and current shared-code exposure, not a measured v3 screen result. |
| CQ08 — Insight selection | Fresh PoC-style extraction also had joined quotes and wrong mappings. | Generic certifications/headlines selected despite stronger available evidence. | Better task judgment is needed; neither full-report transfer nor reverting to the PoC is sufficient. |
| CQ09 — Runtime and observability | Historical job/Exa join now verified. | Pacing deadlock fixed; long histories, 900s structuring timeouts, final-attempt-only latency and trace-environment drift measured. | Preserve the pacing fix; add bounded specialist work and complete attempt/parent-child tracing. |

## Prompt implications

The [extractor prompt](../../../platform/api/clue_api/arv2/structuring_client.py#L424) already
requires exact contiguous evidence, correct fields, no invented positive “NOT FOUND” claims,
and appropriate use classes. Repeating these instructions is unlikely to repair the complete
problem. The source/caller-notes/catalog distinction needs to survive the tool contract; errors
need actionable feedback and a correction path that really affects stored truth.

The [display prompt](../../../platform/api/clue_api/arv2/display/prompts.py#L55) explicitly asks
for a short page, while several section instructions assume ABM-tooling concerns. In Premier's
actual requests, `client.name=Insight Health AI` was paired with the platform's ABM pitch.
The current [`client_context`](../../../platform/api/clue_api/arv2/display/gather.py#L237)
still uses the workspace's first brand name plus a global configured pitch. It must instead
resolve the intended seller, selected products and applicable ICP/personas with exact versions.
Changing the model or moving the same malformed input into a subagent would preserve this error.

The [why-fit recipe](../../../platform/api/clue_api/arv2/display/recipes.py#L162) does not include
`account.icp_fit_verdict`; Premier's saved watch-outs inputs do. Values are also flattened and
[clipped at 1,200 characters](../../../platform/api/clue_api/arv2/display/render.py#L29).
Concise summaries are desirable, but significant supported facts must remain inspectable with
their disposition. Accuracy, relevance, internal visibility and outreach eligibility are distinct.

## Architectural direction for discussion

**Support the founder's three-role direction, with the following responsibilities.**

| Role | Responsibility and durable return |
| --- | --- |
| Per-account research Deep Agent | Own the adaptive brief, account research, ICP/persona context, committee coordination, follow-up decisions and final coverage assessment. Delegate and inspect the specialists' receipts. |
| Claim specialist | Read canonical reports/pages/transcripts and field definitions; identify supported facts; validate subject/meaning/evidence; write or correct through governed tools. Return claim references, conflicts, exclusions and unprocessed material. Reuse the same capability for person jobs. |
| Narrative specialist | Read current applicable claims and exact seller/product/ICP/persona context; produce a durable cited value narrative and the page sections it owns. Return missing-claim requests to the parent instead of inventing support. |

The useful change is giving specialists evidence-reading and repair tools, with bounded loops,
rather than renaming the two existing model calls. Exa's complete report should be available as
research context and a coverage guide; primary pages and transcript versions supply their own
evidence. Exa narration must not silently become an original-source or personal spoken quote.

Parent briefs guide priorities but do not replace the originals. Canonical material travels
through read-only artifact references/files; domain results remain claims and cited narrative
references. The existing [delegation contract](../../architecture/clue-hq-platform-agent-runtime.md#23-subagent-contract-revised-2026-07-18)
already forbids a paraphrase substituting for available original material. A compact returned
receipt must not become the only surviving research output.

LangChain supports specialist instructions/tools/models and context isolation
([official documentation](https://docs.langchain.com/oss/python/deepagents/subagents)). The repo
already has a [governed Deep Agent runtime](../../../platform/agents/clue_agents/runtime.py#L331)
and deliberately suppresses the framework's unrestricted default `task` tool in favor of
`delegate_specialist`. Reuse those platform contracts; preserve the detached per-account fleet
job, durable operations, artifact ownership, replay, erasure, model gateway, spend receipts and
parent/child tracing. Exact API choices must match the pinned Deep Agents version (0.6.12),
not be copied unreviewed from newer documentation.

Narrative work must remain independently refreshable after late person results, corrected claims
or changed seller selections. The parent may supervise initial synthesis, while later updates
invoke the same specialist against versioned inputs. Replace the Luna responsibilities it takes
over; do not run a second competing narrative writer. Presentation remains a projection of
claims/cited narrative, not a private prose handoff that bypasses the store.

## Decisions and proof needed before implementation

1. **Quality policy:** ARV2's current [master plan](../../specs/ARV2-MASTER-PLAN.md#2-principles-that-govern-every-task-non-negotiable)
   intentionally makes quality checks annotations, not store/page blockers. Retaining failed
   extraction attempts for audit while excluding them from ordinary current facts would be a
   policy change requiring an explicit ruling. It must not be introduced accidentally as part
   of the Deep Agent migration. Privacy and outreach restrictions remain separate.
2. **Ownership and correction:** define how a specialist retires/replaces a wrong claim,
   resolves competing values and invalidates summaries, including failure and replay behavior.
   Neutralizing the catalog and correcting seller context do not depend on a framework migration.
3. **Coverage and evidence:** record source/report-section disposition with claim references or
   reasons such as duplicate, irrelevant, insufficient evidence, restricted or unprocessed.
   Do not promise every retrieved sentence will be displayed or retained contrary to privacy policy.
4. **Bounded runtime:** allocate specialist rounds and time inside an account job's overall
   execution envelope; record every attempt and resume/reuse result. Context isolation can reduce
   parent history, but extra calls can increase latency and cost. Measure rather than assume.
5. **Matched evaluation:** a fresh Premier v3 run under the exact Insight Health product selection
   and pinned ICP v4 is still missing. Use a clean isolated account identity without PoC or old
   target claims, and inspect account/person outputs through the actual display worker and UI.
   Preserve the current baseline, then evaluate proposed repairs separately.
6. **Separate retrieval from conversion:** replay frozen evidence through the current and proposed
   extraction/narrative paths, then run live acquisition separately. Keep seller inputs and catalog
   versions explicit. This reveals whether an improvement comes from new sources, a repaired
   catalog/context, a stronger model, or the specialist workflow. No invented aggregate score.

Success criteria should include correct entity/field relationships, supported novel facts retained,
effective correction, correct seller relevance, qualified usable media evidence, visible reasons
for omissions, and end-to-end latency/cost. More claims, more agents or a green job status are not
acceptance criteria. No new Premier research or architecture implementation was launched here.
