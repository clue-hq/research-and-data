# ARV3 research quality — ordered implementation and acceptance plan

> **September 23 founder supersession:** New quality runs use [advisory research revision six](2026-09-23-arv3-advisory-research.md). Relationship verification and presentation withholding are deferred; findings remain visible with uncertainty. Earlier strict requirements below describe the historical implementation.


**Status, 2026-09-23:** Q1–Q7 implementation completed and checkpointed locally. Q8 offline
verification, including the 100-account/200-person load, migration, storage, browser-component and
telemetry proofs, is recorded in the [acceptance report](2026-09-23-arv3-quality-acceptance.md), with
test failures and measurement limitations retained. The founder authorized a fresh paid Zafran run
on September 23, followed by five additional workers at concurrency three. The paid attempts have settled;
the corrected continuation used ten workers at concurrency three and the founder-authorized
200-turn reset. It ended needs_review with four contact pages, missing account pages, relationship
validation and finalization failures. Q24 quality acceptance is not granted. Q23 matched comparison
and default-profile promotion remain pending. See the
[live record](2026-09-23-zafran-quality-live.md). Public launch default remains v2;
the new quality composition is internally v4.

Implementation was authorized on 2026-09-22, including the proposed context, membership and
presentation contracts. Before implementation, latest origin was fetched; feature upstream and
`origin/research-streaming` were contained in local base `a14ccbee0`; fast-forward pull needed no merge.
**Design:** [research quality, evidence access and specialist ownership](../specs/archive/2026-09-22-arv3-research-quality-design.md).
**Inspected base:** `2dd07c55f`, `codex/ai-ark-committee-discovery-spec`, 2026-09-22.

## 1. Delivery rules

- Preserve v3 source/media capabilities and v2 AI Ark committee discovery. Change ownership and
  data contracts incrementally; do not create a parallel research pipeline.
- Design §1.2 item 1's factual-visibility policy is adopted: invalid observations remain auditable,
  are excluded from ordinary factual summaries, and unresolved findings stay visible. Do not request
  that approval again. The subsequent implementation instruction approves the proposed contract
  details, including §10.2 presentation, for development.
  Existing annotation-only runtime behavior continues until implementation and explicit activation.
- User asked to synchronize latest origin before implementation. At that point inspect branch,
  upstream and concurrent/uncommitted work, fetch, and integrate the intended remote base without
  overwriting local work. Record the resulting base and reassess this file's code pointers.
- Commit completed coherent units locally. Never push, publish a PR, change shared runtime defaults,
  run historical repairs or start live paid research without corresponding authorization.
- Do not repeatedly run the complete suite between intermediate edits. Use final contract scenarios
  per completed slice, required migration/seam checks when applicable, then the combined affected
  suite. Investigate suspicious failures; don't modify assertions to legitimize temporary behavior.
- Track runtime/offline/live/browser acceptance separately. A successful queue or paid call proves
  execution, not factual quality. Keep baseline artifacts immutable and private.

## 2. Q0 — Baseline, authority and contract decisions

**Outcome:** a reproducible implementation starting point and explicit policy changes.

1. Verify the actual checkout after upstream synchronization and read relevant `_memory` updates.
   Preserve unrelated cumulative-review edits and side-audit attachments.
2. Freeze source/context/catalog/model manifests for Premier, Probook and Zafran from retained
   artifacts. Prepare redacted regression fixtures; do not commit contact channels/raw private data.
3. Inventory active account/person/display profiles and entry points. Record the single owner of
   each new-profile operation and legacy behavior. Do not silently bump a live default.
4. Carry the recorded factual-visibility adoption into the assessment/current-read implementation.
   Resolve remaining membership/project-context presentation details. The master-plan amendment
   already records policy approval; update implementation/activation status only when it happens.
5. Prepare canonical accounts/projects contract amendments for founder review: contextual reads,
   provisional membership, visible non-sensitive gaps and refresh semantics. Avoid component work
   until payload and presentation decisions are resolved.

**Exit:** Q01–Q24 are mapped to fixtures/proofs and policy decisions have explicit status. No
production behavior has changed. This phase must not become another broad research exercise.

## 3. Q1 — Context pins and neutral catalog

**Outcome:** every stage has the right seller, selected products and exact ICP/persona documents.

**Primary seams:** `arv2/account_research_launch.py`, `research_context.py`, `account_research_store.py`,
`icp_authoring.py`, `icp_confirmation.py`, onboarding lineage/document readers, project-product
readers, `display/gather.py`, and the shared field registry.

1. Add the context-pin schema, composite scope constraints and artifact manifest using existing
   storage. Reuse exact project pin/product selection; snapshot required seller capability refs.
2. Record source ICP document ID/digest on new persona synthesis/authoring. Implement legacy
   lineage resolution without conflating row revision and content version.
3. Implement brand/project/variant persona selection, explicit-pin precedence, ambiguity and gap
   outcomes. Pin once per run; all children and refreshes consume the same context reference.
4. Remove first-brand/configured-pitch fallback for new-profile synthesis. Keep old-profile replay
   intact. Missing seller support permits neutral research but cannot manufacture value arguments.
5. Prevent subject-specific runtime field descriptions from entering the global catalog. Use existing
   workspace-scoped proposed definitions, neutral descriptions and pinned catalog revisions.
6. Produce a dry-run contamination inventory; do not execute blanket historical correction.

**Proof:** Q01–Q05, two-project isolation and catalog contamination fixtures. Check actual generated
model request inputs, not only resolver return types. Reversible migration smoke on isolated DB.

## 4. Q2 — Evidence descriptors and governed access

**Outcome:** originals survive delegation and are selectively readable on any worker.

**Primary seams:** `clue_storage`, `arv2/research_operations.py`, `provider_ledger.py`, media
store/retrieval, `platform/agents/clue_agents/workspace.py`, `platform/api/clue_api/specialist_wiring.py`.

1. Define SourceRef, manifest, typed locators and scope/grant contracts. Reuse existing operation,
   ledger and transcript IDs; descriptors distinguish URL/time attribution even for identical blobs.
2. Persist/verify source artifacts before returning durable handles to parent or child. Adapt any
   end-of-hop-only drain that currently cannot provide that guarantee; retain one spend ledger.
3. Add paginated source listing, bounded text search/read, JSON-value resolution and transcript
   passage reads. Every truncated response carries a continuation; errors offer valid recovery.
4. Materialize granted originals read-only behind virtual paths. Secure default filesystem tools
   as well as named evidence tools; authorize each read and invalidate files on revocation.
5. Persist source/unit processing dispositions. Extend artifact reference accounting, cleanup and
   erasure for all new manifests, descriptors and task results.
6. Test fresh-worker reconstruction and storage outage behavior with both filesystem development
   and the existing shared S3-compatible backend configuration used by the test environment.

**Proof:** Q06–Q07, Q19, Q21. Confirm no source body copies in job/queue JSON and no foreign-account
or foreign-workspace access by guessed ID/path. No new vector service is required.

## 5. Q3 — Claims, effective correction and applicable reads

**Outcome:** source identity and semantic assessment affect real stored/read behavior.

**Primary seams:** `arv2/claim_writer.py`, `account_research_claims.py`, `structuring_client.py`,
`subsystems/research/clue_research/claimstore/`, registry, ARV2 annotations, research/display readers.

1. Implement typed proposal/support contracts for source spans, provider JSON and transcript
   segments. Trusted runtime supplies scope; code resolves actual source identity.
2. Add assessment/correction operation lineage and context/support associations. Keep lifecycle,
   evidence quality, use-class and outreach eligibility separate.
3. Expose one applicable-claim policy for new-profile consumers, including generic current-answer
   paths. Keep explicit raw/history reads. Legacy unassessed data is not automatically supported.
4. Implement scoped, locked, idempotent correction/withdrawal/conflict tools using shared helpers.
   Handle same-field replacement, different-field reclassification and no-replacement withdrawal.
5. Add durable invalidation delivery and a dependency revision. Test concurrent corrections and
   crash windows before wiring model-driven correction loops.
6. Make deterministic provider mappings idempotent on saved evidence/mapping version. Ensure direct
   agent writes cannot bypass evidence/assessment contracts.

**Proof:** Q07–Q11. Inspect underlying rows, applicable reads and invalidation receipts. Prove the
headcount repair preserves the valid API fact while retiring false provenance. Do not treat a model's
semantic approval as proof of deterministic reference integrity.

## 6. Q4 — Governed account Deep Agent and claim specialist

**Outcome:** real evidence-reading and correction agency with one claim-writing contract.

**Primary seams:** `arv2/account_research_agent.py`, `account_research_driver.py`, tools/catalog,
governed Deep Agent runtime, specialist wiring, immutable role/skill/prompt resources, model settings.

1. Verify adapters against installed/pinned Deep Agents interfaces. Reuse governed delegation and
   role tooling; do not enable the framework's unrestricted default task/subagent or shell tools.
2. Define account and claim-specialist instructions, grants, exact adaptive task/return shapes and
   resource pins. Bind original evidence, catalog definitions and context manifest through Q1/Q2.
3. Adapt the detached ARV2 fleet job as parent execution. Specialist model usage contributes to
   existing accumulated execution bounds; no per-child resetting of allowances.
4. Replace new-profile `structure_material` leaf ownership with the specialist capability, shared
   by person jobs. Keep deterministic provider mapping in code and old profiles replayable.
5. Parent examines correction/coverage receipts and issues focused follow-up. Missing source support
   produces research gaps or acquisition requests; specialist cannot invent a primary source.
6. In-slot child execution consumes the parent's allocated capacity; do not block a leased parent
   while queueing its awaited child onto the same saturated pool. Test concurrency one explicitly.
7. Persist resume state/task results and trace parent-child attempts, refusals and tool effects.

**Proof:** Q06–Q11, Q19, Q22. Replay a complete account and person claim workflow; then compare with
the repaired leaf baseline on identical evidence. Record model/token/latency differences honestly.

## 7. Q5 — Contextual identity, membership and reconciliation

**Outcome:** person findings change the actual committee and trigger the parent's next decision.

**Primary seams:** `committee_discovery.py`, `committee_step.py`, account/person claims and driver,
provider identity, fleet queue, account-generation/progress projection, committee reader.

1. Register typed employment and project committee assessments. Preserve canonical people and
   distinguish identity, current employment and buying remit.
2. Add adaptive location/organization scope to role and person briefs. Use supported provider
   filters only; verify account/parent/subsidiary relationship without industry-wide hard rules.
3. Replace legacy contact-parent-plus-any-claim membership inference for new generations with the
   assessed committee reader; contact counts/statuses must use this same source.
4. Add generation coordination and durable child-result receipts/completion signals. Initial
   account-job terminal records stay history; reconciliation is a resumable account continuation.
5. Release capacity while waiting for detached people. Coalesce late/duplicate events, preserve
   suspension/privacy stops, and reconcile partial results without claiming missing jobs succeeded.
6. Invalidating employment immediately prevents committee/outreach assumptions; refreshed prose
   must not be the only mechanism that removes an invalid member.

**Proof:** Q12–Q14, including Anna-like conflicting employers, a remote hospital-system decision
owner and multinational remit. Prove safe behavior before, during and after display refresh.

## 8. Q6 — Narrative specialist and contextual pages

**Outcome:** one seller-specific, cited narrative owner with reliable independent refresh.

**Primary seams:** new narrative specialist profile; existing narrative claim types and shared
write helpers; `arv2/display/{gather,runner,page,blocks,fleet_handler,recipes,evidence}.py`;
frontend-read composition and approved frontend contract/repository/schema changes.

1. Define claim-backed value narrative and page-level section output. Cite both target claims and
   exact seller capabilities. Missing support becomes a parent/claim task, never prose fabrication.
2. Replace Luna ownership for new-profile sections, preserving legacy replay. Do not wire the old
   M8D/Stage-0 narrative composition into ARV2 to achieve this.
3. Migrate display live identity, queue dedup and cache keys to include project/context/generation.
   Store full dependency revision; atomically refuse obsolete generated writes.
4. Refresh after new people, claim corrections, context changes or transcript repairs. Suppress
   invalid statements immediately; allow unaffected safe sections to remain visible.
5. Implement approved provisional/needs-verification/gap/citation presentation through repository
   schemas and adapters. Keep source excerpts, primary quotes and inferences distinct.
6. Resolve context-less account reads explicitly; never guess the first brand or an arbitrary
   project's selected products. Keep historical unscoped output labelled legacy.

**Proof:** Q05, Q13, Q15–Q16, actual generated account/contact output and frontend read responses.
Run the repository's frontend gates for changed frontend work, then browser verification with exact
runtime handles. Backend-only payload tests do not count as browser acceptance.

## 9. Q7 — Usable media, hiring freshness and runtime recovery

**Outcome:** richer evidence retains attribution and temporal meaning through final output.

**Primary seams:** existing media acquisition, resolution, claims, retrieval and speaker binding;
ATS/provider mappers, source dates, agent tools and refusal receipts.

1. Make speaker-attribution evidence and quality qualifications readable to the specialist; preserve
   original transcript/version/segment support through claims, corrections and display.
2. Add targeted repair/recheck flow through existing transcript versioning. Unverified voices stay
   qualified/ineligible where required; do not remove safeguards to increase usable-claim counts.
3. Preserve job closing/status/observation dates; assess open/closed/historical/unknown and stop
   expired accessible listings becoming current urgency.
4. Make identical invalid-reference attempts cheap, typed and recoverable. Tool success envelopes
   must expose domain refusals; final coverage derives from durable activity.
5. Review growing parent/child histories and redundant reads. Tune progressive reads/compaction
   after final behavior works, retaining original references and unresolved questions.

**Proof:** Q17–Q19 and cross-layer media/hiring citations in generated pages. No broad new ingestion
provider, social crawler or media-agent subsystem is part of this phase.

## 10. Q8 — Combined proof and rollout record

1. Run the affected final-contract suite and required repository checks. Run migration up/down/up
   only on an isolated throwaway DB and confirm one Alembic head. Do not repair unrelated failures
   by changing shared runtime state.
2. Run Q20/Q21 with two isolated workspaces and at least 50 accounts each, realistic child fan-out,
   real DB/storage/fleet and deterministic external substitutes. Measure active capacity, queue
   fairness, storage/context memory, restart recovery and access isolation.
3. Run Q23 frozen-source comparison with baseline context/catalog repair isolated from specialist
   orchestration and model changes. Report missed useful findings and false assertions separately.
4. After authorization, run fresh Premier, Probook and Zafran research, actual display generation
   and browser review. Confirm jobs, claims, corrections, membership and displayed citations agree.
5. Audit Q22 telemetry/spend joins and ensure no unpriced calls are silently included as zero cost.
6. Record accepted/failed scenarios and remaining limitations. Add a fresh-account generalization
   check when the matched baseline passes; do not claim representative acceptance from three accounts.
7. Only after review, promote the launch profile. Preserve pinned old jobs and the prior selector
   for rollback of future launches. Existing corrections and privacy enforcement stay effective.

**Deliverable:** a single acceptance report linking offline/migration/load/replay/live/browser proofs,
configuration/profile identities, timings, costs, screenshots where useful and unresolved defects.

## 11. Completion definition

The phase is complete when the agreed acceptance cases demonstrate correct project context,
inspectable original evidence, effective corrections, reconciled committee membership, cited
seller-specific narratives and qualified media/hiring use through the actual application, with
replay/isolation/telemetry intact. More claims, additional agents and green jobs alone do not pass.

Local commits should follow coherent slices; documentation and `_memory` should state implemented,
tested and live-accepted status separately. Historical repairs and production scale tuning remain
separate scoped actions, not hidden post-implementation side effects.
