# 2026-08-08 — Lane D contract amendments after founder review

## Scope

Documentation-only amendment to `docs/specs/FI-lane-D-production-chat-and-launch.md`.
No runtime, database, frontend, or API implementation changed.

## Founder ruling

- Lane D decision §6-D2 is ratified: the initial production path must include genuine,
  complete token streaming. Part-only streaming followed by a later token extension, or a
  post-hoc typing animation over a completed message, is not acceptable.
- The under-specified implementation recommendations discussed in the Lane D review were
  requested to be recorded in the charter. D1/D3/D4/D5/D6 remain pending explicit choices.

## Contract additions

- Kept Clue turn/message/SSE events as the canonical backend contract; local AI Elements
  primitives remain presentation behind the project repository/adapter seam.
- Added the complete part mapping for text, reasoning, safe agent activity, tools, aggregate
  tasks, plans, durable gates, sources, and navigation actions.
- Specified a provider-neutral incremental extractor for streamed
  `finalize_turn.user_message`, which is currently carried inside required tool-call arguments.
  It must emit only safe text deltas, persist/replay them, and reconcile byte-identically to the
  durable assistant message.
- Added generation-attempt identity, reset/retry behavior, event envelope/vocabulary, full
  snapshot replacement semantics, cold rehydration, `Last-Event-ID`, backpressure, and error
  behavior.
- Made `action_ref` an opaque, server-derived `turn-action:<turn_id>` receipt; artifact/capture
  identity is validation evidence and never caller-authored authority.
- Defined gate clicks as structured human turns, per-thread single-flight/visible queueing,
  distinct stop-turn vs suspend-run controls, and retry-as-new-attempt semantics.
- Expanded D1–D5 acceptance criteria and the streaming/adversarial test matrix.

## Verification

- `git diff --check` passed.
- Reviewed the charter for stale “nothing ratified,” part-only-first, optional-token-streaming,
  and gate-vs-action wording; no stale instances remain.
- The unrelated untracked `.playwright-mcp/` directory was left untouched.

## Remaining decisions

- D1 async worker execution vs gateway-in-HTTP.
- D3 durable `agent_gate` table vs flavored refs.
- D4 production actor identity.
- D5 dedicated estimate tool vs un-reserving `estimate_project`.
- D6 dev-trial disposition.
