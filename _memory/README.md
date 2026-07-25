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
