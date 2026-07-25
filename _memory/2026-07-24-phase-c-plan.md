# 2026-07-24 — Phase C parent plan ratified

## Outcome

Added `docs/specs/PC-phase-c-agentic-layer.md`, the authoritative parent execution plan for
Phase C. Documentation only; no Phase C implementation started.

The plan reconciles:

- harness steps 4–7 and the original C1–C8 division;
- the founder's Stage-0 clarification (three product loops and three research speeds);
- B4's toolbelt/run-entry findings;
- B3's workspace-local accounts, multi-brand workspace, brand-neutral targets, and required
  project/brand run context;
- Doc A's no-fake-agency taxonomy;
- Doc M's claims/memory species split;
- the current cross-milestone backlog.

## Binding plan decisions

1. Stage 0 is a product boundary spanning initial onboarding recon and project kickoff, not the
   old fixed `REVERSE_PROFILING → ICP_CONFIRMED` run sequence.
2. Onboarding input must be durable and brand-aware; a workspace singleton is invalid in the
   multi-brand model. Raw material bodies live in artifact storage.
3. Product context must become reproducible/pinned before product-conscious Stage 0 is complete.
4. The harness path may not reverse-profile after confirming an ICP derived from an older
   Client-KB version. The C4 child spec chooses the compatible entry-phase/start-surface shape.
5. Recipe #0's C4 runner must sit behind a seam C5 can generalize, not be throwaway orchestration.
6. The toolbelt remains the single domain write path for humans and every mind.
7. C1–C4 may develop after a serial contract freeze; integration order is C1 → C2 → C3 → C4
   because C4 consumes coverage, proposals, and ingestion.
8. C1's goal judge is a bounded leaf call; C4 builds governed Stage-0 substrate; the real
   platform deepagent arrives in C6.

## Execution shape

- **C0 serial:** child-spec/contract freeze + all-path pre-spend and identity-binding prerequisite
  dispositions.
- **C1:** coverage ledger + bounded goal-judge loop.
- **C2:** `propose_field` / `propose_source` + tier-3 generic web resolver.
- **C3:** upload ingestion → snapshots/segments/claims.
- **C4:** onboarding input, fast/background recon, interview source, readiness, override,
  Recipe #0, minimal skill loader; integrates last.
- **C5:** run-graph journal, versioned recipes, durable graph executor, supervisor; formalizes
  Recipe #0 and Recipe #1.
- **C6:** actual Doc-A platform deepagent, skills, profiles, subagents, plan validation, context
  assembly, honest finalize.
- **C7:** derivations, dossier/block projections, re-check, production handoff reader.
- **C8:** prerequisites land before their consumers (pre-spend, identity binding, merge
  equality/retention, rationale redaction, presign policy, production fencing, product fit).

## Documentation consistency repaired

- `docs/specs/README.md`: Phase B/B2/B3 marked executed/integrated; Phase C plan indexed.
- `docs/specs/PB-phase-b-platform-infra-core.md`: historical Phase-B treaty marked executed.
- `AGENTS.md`: stale “brand_id remains” B3 residual replaced with the completed multi-brand,
  brand-neutral account, and project-run brand-context state already present in `CLAUDE.md`.

## Verification / final state

No schema, runtime, API, or test behavior changed. Baseline entering the session was clean with
`make check` green (2254 passed / 20 skipped) and one Alembic head `b366c985ca12`.
Documentation verification: `git diff --check`; link-target existence check for the parent spec;
Phase-C terminology/decision grep; stale B3-brand-residual grep; CLAUDE/AGENTS Phase-C/B3/B4
backlog parity check. Full `make check` with the local Postgres URL passed after the documentation
changes: ruff, mypy (327 files), 23 import contracts, 2254 tests passed / 20 skipped.

## Next session

Do not open implementation worktrees immediately. First execute C0 by drafting/reviewing the four
child specs and freezing shared contracts/fixtures. Then create the C1–C4 worktrees from that same
reviewed head.
