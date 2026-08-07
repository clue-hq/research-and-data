# Project Memory

This directory is the durable collaboration log for agents working on this repository.

At the start of each session:

1. Read this file.
2. Read the newest session note(s).
3. Read any topic note that matches the current task.
4. Verify memory-derived facts against the current workspace before editing.

During and at the end of each coding or goal session, update `_memory/` with:

- progress made;
- files changed;
- decisions and accepted assumptions;
- failures, blocked attempts, or commands/tests that did not work;
- verification performed;
- unresolved follow-ups.

Keep notes concise and operational. Do not store secrets, API keys, credentials, customer data, or raw proprietary source excerpts here.

## Repository Role

This repository is the data and research subsystem for the larger AI-native ABM orchestration platform. Its job is to turn client ICPs and client knowledge into canonical account/contact entities, typed claims with provenance, explainable fit/intent scores, and persona-keyed buying-committee research that downstream content and design systems can trust.

The central architecture bet is that verification must be modeled at the claim/data layer. LLM research is a last-resort tier-4 source, not the foundation. The product should prefer empty, flagged fields over fabricated fields.

## Topic notes
- `2026-08-08-part2-d22-documents-history-port.md` — **Part II D2.2 done:** documents+history
  on Postgres behind `HybridRepository` (scene CAS added; legacy asset-metadata 410s per O3);
  migration `7a9881f9717a` — workspace-local PKs extended to all client-supplied/content-hash
  id namespaces (**needs founder ratification**), account FK deferred to D2.4; design suite
  487/0 green after harness adaptation + merge-fallout repairs (fixtures, npm). jsonb does NOT
  preserve object key order — never select nodes by dict position. Opus-implements/Fable-reviews
  process now binding.
- `2026-08-07-part2-d21-dal-foundation.md` — **Part II D2.1 done:** `lumen-api` packaged +
  explicit uv-workspace member (agent-runtime deps deliberately excluded; dead `pypdf` pin
  dropped over a real lockfile conflict; py_lumen_* stay PYTHONPATH until Step-2);
  `clue_design` gains errors + parent-row-lock sequence allocators (O5 one-transaction rule
  binding); 10/10 design DB tests incl. an observed lock-blocking concurrency proof.
- `2026-08-07-part2-d1-design-schema.md` — **Part II D1 done:** six `design_*` migrations off
  `c6d84aa84b79` (head `e79f192828b1`), 11 package-local enums + parity, immutability triggers,
  structural tenancy; db-smoke + 6/6 design tests green. Env gotcha: localhost:5432 = Homebrew
  PG17, NOT the docker container. Pre-existing DB-suite failures (waterfall et al.) proven
  D1-independent by A/B. Next: D2 after O6b ratification.
- `2026-08-07-part2-o1-o6-ratified.md` — **O1–O6 RATIFIED (founder); D1 unblocked.** Key
  refinements: `design_brand_kit` promoted to THE platform versioned brand-kit payload (brand
  studio vision); `asset_descriptions` ported with full behavior; O5 atomicity rule binding;
  fleet-for-design-deepagent uncertain but concurrent multi-session runs binding; O6 slugs
  workspace-local with O6b (interim `/p/{slug}` rule) open for D2; append-only design history
  is a preserved principle — no destructive compaction ever.
- `2026-08-07-part2-d0-preflight.md` — **Part II slice D0 done:** contract doc
  `docs/specs/PD-part2-design-substrate.md` (slice map, 22-table `design_*` map, rules, open
  decisions O1–O6 — **unratified, gate D1**); `subsystems/design/clue_design` scaffold under all
  gates incl. new Rule-S4 contract; clue-design logging-guard carve-out. Pre-existing red found:
  23-file ruff-format drift at `origin/main` fails `make lint` — ruling pending.
- `2026-08-07-alembic-single-head-c6d84aa84b79.md` — **Alembic has ONE head: `c6d84aa84b79`**;
  all new (incl. Part-II `design_*`) migrations chain off it. A 4-head report was false (it
  counted Phase-C branch tips already joined by `fc1f3d22a167`). Verify with
  `uv run alembic heads`, never by eyeballing the versions dir.
- `2026-08-07-design-subsystem-monorepo-merge.md` — Design-integration **Part I / Step 1** done:
  `clue-design`/*havana* merged into `subsystems/clue-design/` (full history preserved; on
  `origin/main` via PR #40; design-only ancestry = 2nd parent of `3ab4a750`), excluded from the
  uv workspace + ruff pending Step-2 hygiene. Parts II–IV (substrate / agent / surface) not
  started. Authoritative plan: `docs/specs/design-integration-master-plan.md`.
- `2026-08-06-m8d-r9-parallel-execution.md` — R9 accepted: exact-wave dependency checks,
  atomic budget/provider admission, concurrent Exa/Sumble execution, partial-result joining,
  callback-race-safe composite waits, cold-resume/crash replay, DSAR, and isolated-DB evidence.
- `2026-08-06-m8d-r0-r4-adversarial-fixes.md` — closes every reviewed R0-R4 P1/P2:
  exact field/source authority, full legacy quarantine, globally scoped checkpoints, immutable
  state/finalization history, provider-neutral causation/results, multi-contact projections,
  bounded follow-up context, lossless UTF-8 reads, checkpoint-aware DSAR, and fresh-DB gates.
- `2026-08-06-m8d-r4-governed-tools-persisted-results.md` — R4 accepted: exact semantic tool
  authority, provider-operation causation before dispatch, complete lossless persisted results,
  Exa contact composition, replay/follow-up lineage, DSAR reach, isolated-DB regression evidence,
  and the retained R5/R9/R10 boundaries.
- `2026-08-05-m8c-v0-offline-database-acceptance.md` — M8C V0 complete mechanically: frozen
  55-gate C0–C7 matrix, prerequisite-populated synthetic database and zero-call fresh replay,
  provider-id/count isolation repairs, clean 3,412-test full suite, migration/static gates,
  categorized failure ledger, and the separate V1 live-provider boundary.
- `2026-08-05-m8c-c5-selected-contact-channel-enrichment.md` — C5 mechanically complete:
  exact selected-contact/channel authority, Exa one-person acquisition, independent validation,
  atomic split spend, governed identity promotion, replay, DSAR/retention, clean database
  verification, and the separately authorized paid-canary/C6 handoff.
- `2026-08-05-m8c-c4-exa-contact-acquisition-materialization.md` — C4 complete mechanically:
  transaction-free exact-contact Exa dispatch, immutable snapshots and honest one-time cost
  settlement, exact-target replay through governed `fill_contact_field`, crash/same-name/malformed
  defenses, clean database verification, and the separately authorized live-canary/C5-C6 handoff.
- `2026-08-05-m8c-c3-contact-exa-compiler.md` — C3 complete mechanically: exact-contact/employer
  Exa Deep compiler, registry/source-plan authority, directional structured output, fail-closed
  same-name parser, content-addressed fixtures, clean full-suite verification, and the C4 handoff.
- `2026-08-05-m8c-c2-atomic-lineage-remediation.md` — closes both audited C2 blockers:
  the public reserve API solely owns semantic reuse serialization/capacity reservation, every
  Exa claim requires exact operation/snapshot/request/result-artifact lineage, provider doubles
  use honest fixture source identities, and clean full-suite/migration verification is green.
- `2026-08-05-m8c-c1-selection-lineage-remediation.md` — closes both audited C1 findings:
  bounded strong-first People/Teams union selection preserves organization-map representation;
  typed immutable claim provenance plus exact database-enforced Sumble operation/snapshot/
  artifact/account/contact lineage; clean full-suite and migration-smoke verification.
- `2026-08-04-m8b-v0-offline-database-acceptance.md` — V0 complete mechanically: frozen
  32-case fault manifest, Sumble response-before-normalization durability and charged-drift
  quarantine, disposable migration/concurrency/fresh-process inspection, clean 3,337-test suite,
  static/import/one-head gates, and the separately authorized V1 live boundary.
- `2026-08-04-m8b-o3-main-agent-steering.md` — O3 complete mechanically: non-linear Head-of-ABM
  account-deep steering, exact current directive/launch/account L3 context, truthful governed tool
  descriptions, pre-launch research-specialist behavior, scripted conversation gates, and
  provider-free real-Postgres verification; V0/V1 remain.
- `2026-08-04-m8b-o2-account-deep-composition.md` — O2 complete mechanically: explicit immutable
  exact-set launch after the conversational/tier pause, account budget/pin propagation, canonical
  Exa preparation and snapshot replay, durable S1/A2-backed no-reveal Sumble committee inputs,
  existing fleet/orchestrator composition, real-Postgres acceptance, and O3/V0/live handoff.
- `2026-08-04-m8b-e0-a2-integration.md` — merged the complete E0 request/response branch into the
  A2 account-profiling integration branch; reconciled roadmap state, isolated the negative Exa
  credential test from local environment configuration, and verified the combined E0/A2/deep/
  Sumble seams without provider traffic.
- `2026-08-04-m8b-a2-research-directive.md` — M8B A2 plus critical-review remediation:
  immutable research direction, exact sealed membership and production launch pins, canonical
  source authority, trusted human confirmation receipts, complete previews, explicit memory
  outcomes, bounded context, project-artifact erasure, and provider-free verification.
- `2026-07-28-phase-c7-8-closeout.md` — C7.8 and C7 complete: 18-case executable
  adversarial matrix, 10-surface DSAR matrix, breadth-batched/capped derivation reads, six
  independent default-off activation controls, operations/runbook/status closeout, clean full
  verification, and the single remaining C8 legacy-write hard-fence handoff.
- `2026-07-28-phase-c7-7-product-serving.md` — C7.7 complete: exact reference-only tools,
  account/contact and legacy-alias HTTP surfaces, body-free status projections, transactional
  canonical/SSE event aggregation, live C6 fetch authority, clean full verification, and C7.8
  adversarial/DSAR/performance closeout.
- `2026-07-28-phase-c7-6-production-committee-handoff.md` — C7.6 complete: one run/product-bound
  governed contact resolver, production C7/M12 adapters, exact product lineage, real
  retention-wrapped materialize/outbox HANDOFF, run-keyed composition isolation, adversarial
  eligibility/crash coverage, and the C7.7 serving cutover.
- `2026-07-28-phase-c7-5-governed-recheck.md` — C7.5 complete: strict additive re-check contract,
  immutable reference-only change reports/events, deterministic crash replay, reverse-reference
  section staleness, governed tool delegation, full isolated verification, and the C7.6 handoff.
- `2026-07-28-phase-c7-4-reference-snapshots-evidence-access.md` — C7.4 complete: append-only
  body-free snapshot receipts, current-policy live resolution, exact-scope evidence actions,
  legacy handoff subject indexing/purge/no-resurrection, full isolated verification, and the
  bounded C7.6/C7.7 payload cutover.
- `2026-07-27-phase-c7-3-research-view-composition.md` — C7.3 complete: injected owner
  seams, deterministic account/contact composition, nine-block reference adapter, adversarial
  state coverage, isolated full-suite verification, and the exact C7.4 handoff.
- `2026-07-27-phase-c7-2-derivation-entailment.md` — C7.2 complete: derived claim flavor,
  append-only ordered support graph and entailment ledger, strict no-rationale judge, conservative
  API-root promotion, bounded live dependency invalidation, transitive DSAR reachability,
  migration/full-suite verification, and the exact C7.3 handoff.
- `2026-07-27-phase-c7-1-prerequisite-hardening.md` — C7.1 complete: shared equality
  consumer parity, fail-closed retention-aware live selection, one-way faithfulness-rationale
  DSAR redaction, evidence-access authorization/service seams, product-exact score claims, optional
  registered contact class, isolated-DB migration smoke, and the exact C7.2 handoff.
- `2026-07-27-phase-c7-0-contract-fixtures.md` — C7.0 complete: frozen account/contact
  research-view contracts and protocols, executable source-species/nine-block ownership map,
  sanitized frontend/adversarial fixture manifests, fail-closed contract tests, full tracked-scope
  verification, and the exact C7.1 boundary.
- `2026-07-27-phase-c7-planning.md` — C7 planning checkpoint on
  `platform/c7-research-views`: founder-ratified dossier-as-structured-research-view ruling,
  account/contact frontend contract, derivation/entailment and reference-only snapshot decisions,
  C8 prerequisite placement, C7.0–C7.8 slices, verification gates, and next implementation entry.
- `2026-07-26-phase-c6-8-production-closeout.md` — C6.8 and C6 complete: prepared account
  turn composed in the existing DEEP slot; immutable one-owner routing; default-off flags;
  body-free read API; cache/context/workspace/delegation/finalization telemetry; secure cold
  workspace resume; retention cleanup; canary comparator; full operational runbook, verification,
  and C7.0 handoff.
- `2026-07-26-phase-c6-7-account-research-agent.md` — C6.7 complete: governed per-account
  deepagent inside the existing fleet slot; one replay-safe C5 gap-research operation; sole C1
  evaluator ownership with append-only non-authoritative advice; terminal-coverage finalization
  guard; no double spend; full DB-enabled verification; and C6.8 handoff.
- `2026-07-26-phase-c6-6-specialist-subagents.md` — C6.6 complete: governed fresh-wake research,
  content-drafter, and reviewer children; exact task/artifact/ref transfer; isolated execution and
  empty-history context; role-specific resources, tools, budgets, outputs, durable receipts; skill
  authoring guide; full DB-enabled verification; and C6.7 handoff.
- `2026-07-26-phase-c6-5-head-of-abm-stage0.md` — C6.5 complete: real Head-of-ABM
  Stage-0 deepagent, additive exact resources, exhaustive unavailable-capability map, nine-tool
  allowlist, progressive Stage-0 skill, C5/Recipe-0 pin parity, replay-certified proposal and
  ingestion paths, human readiness/confirmation authority, full verification, and C6.6 handoff.
- `2026-07-26-phase-c6-4-governed-agent-runtime.md` — C6.4 complete: whole-proposal C5 compiler,
  exact governed framework tools, real deepagents loop, async-Postgres checkpoints, artifact-backed
  model receipts, durable fresh-wake delegation, honest finalization authority, complete crash
  matrix, full DB-enabled verification, and the C6.5 handoff.
- `2026-07-26-phase-c6-3-durable-turns-context-replay.md` — C6.3 complete: reversible normalized
  durable turn/context/history/model/finalization receipts, deterministic budgeted L1–L7 context,
  append-only artifact-backed history, body-free cold replay, subject-indexed DSAR and workspace
  purge, no-resurrection tombstones, full DB-enabled verification, and the C6.4 handoff.
- `2026-07-26-phase-c6-2-catalogs-profiles-model.md` — C6.2 complete: immutable V1 folder
  resources, strict provider-neutral catalogs, four active role profiles plus planned
  account-research, exact effective/delegated tool authority, progressive skill disclosure,
  governed OpenRouter tool-calling/fallback/streaming attribution, deterministic model fake,
  full verification, and the C6.3 handoff.
- `2026-07-26-phase-c6-0-contract-freeze.md` — C6.0 complete: strict agent/resource/plan/context/
  delegation/finalization contracts and injected ports; exact deepagents/model dependencies; real
  fresh-wake, OpenRouter tool-call, async-Postgres resume, artifact-workspace, and honest-finalize
  spikes; 32-tool replay/authority audit; stock-filesystem rejection; C6.1 handoff.
- `2026-07-26-phase-c6-planning.md` — binding C6 child spec and cross-session implementation plan:
  real Doc-A deepagent; external per-execution `virtual_mode=True` workspace; relative paths only;
  no application code or execution tools in the runtime workspace; folder-backed prompts, skills,
  and profiles; C5 durability; C1 evaluator ownership; C6.0–C6.8 sequencing and gates.
- `2026-07-25-phase-c5-6-recipe1-cutover.md` — C5.6 and C5 complete: promoted executable Recipe #1
  phase graph, lineage-validated Stage-0 pre-satisfaction, feature-gated new-run routing with
  legacy fallback, retryable external waits, full historical views, canonical parity fingerprints,
  scripts 01–06 locality repair, complete repository verification, and the C6 handoff.
- `2026-07-25-phase-c5-5-supervisor-controls.md` — C5.5 implemented: run-scoped source telemetry,
  deterministic aggregate supervision, bounded durable diagnosis, replay-safe enforced controls,
  canary-gated deep execution, exact ICP-policy validation, full repository verification, and the
  C5.6 cutover handoff.
- `2026-07-25-phase-c5-5-repository-verification.md` — C5.5 repository verification checkpoint:
  clean DB-enabled full suite (2,432 passed, 20 skipped), lint/type/import-contract gates,
  migration head→base→head smoke, the required project-run aggregate test correction, and the
  untracked local skill-directory lint caveat.
- `2026-07-25-phase-c5-4-recipe0-migration.md` — C5.4 implemented: promoted executable Recipe #0
  v2, bounded durable Stage-0 interaction children, exact resource pins, direct-vs-durable parity,
  four-boundary crash recovery, tombstone/memory/locality enforcement, and the honest C5.5/C5.6
  handoff.
- `2026-07-24-phase-c5-3-durable-executor.md` — C5.3 implemented: generic generated-lease fleet,
  deterministic crash-resumable recipe executor, bounded maps and human gates, typed/audited
  controls, single-owner routing, real SIGKILL recovery evidence, full verification, and C5.4
  handoff.
- `2026-07-24-phase-c5-2-recipes-compatibility.md` — C5.2 implemented: append-only immutable
  recipe lifecycle, closed typed graph/bindings, exact all-error compatibility loader, API-root
  production adapters, promoted non-runnable Recipe-#0/#1 identity seeds, full verification, and
  the C5.3 handoff.
- `2026-07-24-phase-c5-1-execution-journal.md` — C5.1 implemented: full append-only execution
  schema, journal/cursor/outbox transaction, governed parameter artifacts and erasure tombstones,
  mandatory production ToolInvoker, durable replay/retry/blocking, read views, verification, and
  the C5.2 handoff.
- `2026-07-24-phase-c5-0-contract-freeze.md` — C5.0 implemented: exact-version descriptors and
  recipe steps, strict typed outputs, stable operation identities, executable Recipe-#0/#1 replay
  audit, honest provider/recon residuals, verification, and the C5.1 handoff.
- `2026-07-24-phase-c1-c3-integration.md` — C1–C3 integration checkpoint: central 24-tool and
  projection aggregation, cross-lane proposal/ingestion wiring, authoritative contact governance,
  exact-source erasure, Alembic merge head, spend-path inventory, verification, and C4 handoff.
- `2026-07-24-phase-c3-ingestion.md` — C3 implementation state: durable ingestion jobs/segments,
  stable document adapters, governed claim routing, tool/projection surfaces, concurrency and DSAR
  hardening, verification evidence, and integration-owned follow-ups.
- `2026-07-24-phase-c-c1-coverage-goal-judge.md` — C1 implementation handoff:
  bounded coverage attempts, append-only attempt/decision ledgers, goal judge,
  gap-research tool/projections, waterfall observation hook, and verification.
- `2026-07-24-phase-c-c0-contract-freeze.md` — C0 executed: exact C1–C4 shared types,
  schema/tool/projection ownership, fixtures, governance-prerequisite disposition, safe parallel
  wave, integration order, and later Phase-C concurrency ruling.
- `2026-07-24-phase-c-plan.md` — ratified Phase C parent plan: Stage-0 product model, C0–C8
  sequencing, C1–C4 worktree treaty, fixed decisions, prerequisites, and the required next-session
  contract freeze before implementation.
- `2026-06-25-m10-m11-m12-integration-plan.md` — how to integrate the M10/M11/M12 parallel worktrees: data-flow sequencing (M12 last), the as-yet-unbuilt VERIFICATION/HANDOFF runtime spine, the alembic 2-head merge, and the most-important invariant (tombstone-before-merge-read).
- `2026-06-26-m13-parallelisation.md` — the M13 Wave-1 (M13.1/M13.2/M13.4 parallel) + Wave-2 (M13.3) plan, the 4 load-bearing decisions, and the per-workspace briefs.
- `2026-06-26-m134-observability-surface.md` — M13.4 (cost & progress surface) complete: the read-only `ObservabilitySurface`, its api-root wiring, the `cost_estimate` migration, the coverage/verification-health/pre-run-estimate decisions, and the integration follow-ups.

- **2026-08-01 — Stage-0 acceptance run PASSED** (`2026-08-01-stage0-acceptance-run.md`): structured-output repair plan + F6/F7/F8 landed; live Terra interview → grounded confirmed ICP; entailment-strictness product finding; Sumble canary is next.
