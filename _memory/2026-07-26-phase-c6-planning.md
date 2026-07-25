# 2026-07-26 — Phase C6 engineering plan

## Branch and durable plan

- Opened `platform/c6-deepagent-runtime` from completed C5 checkpoint
  `f25e9b5 feat(execution): adopt Recipe 1 with reproducible run views`.
- Binding child spec:
  `docs/specs/PC-C6-platform-deepagent-and-skills.md`.
- Detailed cross-session plan:
  `docs/superpowers/plans/2026-07-26-phase-c6-platform-deepagent.md`.
- This is a technical/senior-engineering plan. No product-management skill was used.

## Founder decisions recorded

- Every deepagent execution receives a dedicated runtime workspace under an explicitly configured
  production root outside and unrelated to the repository/source tree.
- The filesystem backend always uses `virtual_mode=True`.
- Model-visible paths are normalized paths relative to the virtual root; host paths are never
  exposed.
- No application code, package, migration, executable skill, shell, subprocess, or arbitrary-code
  tool exists inside the runtime workspace.
- The runtime workspace contains only immutable agent resources/context/inputs and role-governed
  work/delegation/output files.
- V1 prompt, skill, and profile management is folder-backed. LangSmith/Langfuse prompt hubs are a
  future adapter and are out of C6 scope.
- Exact resource versions and SHA-256 digests are materialized read-only and pinned through C5.

## Engineering decisions

- Use the real Doc-A `deepagents`/LangGraph runtime; no hand-written model loop or fake agent.
- C5 remains the durable tool/plan/replay spine; deepagent checkpoint state is only the mind's
  conversational state.
- `clue_agents` receives tools, projections, model, storage/workspace, and journal capabilities
  through narrow injected contracts and may not import concrete gateway/storage/execution/API or
  subsystem implementations.
- C1 `GoalJudge` remains the sole independent advisory coverage evaluator. The agent plans;
  evaluator challenges; engine alone enforces terminal state.
- C6 routing is default-off with workspace/canary controls. C4/C5 fallback behavior remains until
  separately retired.

## Planned implementation order

1. C6.0 contract freeze and executable framework/model/workspace/checkpoint spikes.
2. C6.1 isolated virtual workspace and immutable resource materialization.
3. C6.2 folder catalogs, profiles, role registry, and tool-calling model seam.
4. C6.3 typed turns, seven-layer context, append-only history, and durable receipts.
5. C6.4 governed tool bridge, plan compiler, delegation, and honest finalize.
6. C6.5 Head-of-ABM Stage-0 vertical.
7. C6.6 research/content/review fresh-wake subagents.
8. C6.7 governed per-account research-agent unit and evaluator-owner closure.
9. C6.8 API composition, canary, hardening, full verification, and C7 handoff.

Do not parallelize C6.0–C6.4. Limited profile/eval work may parallelize only after the common
runtime, journal, delegation, and authority contracts are green.

## Closing state

- Planning documents only; no C6 runtime code, dependency, migration, or production routing was
  added.
- The next implementation session is C6.0 only.
