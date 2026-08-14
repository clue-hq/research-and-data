# 2026-08-14 — Superseded provisional L3 card discussion

> Superseded later the same day by
> `docs/specs/FI-production-deepagent-context-composition.md`. Retained as the discussion trail.

## Founder direction

- Keep `project_conversation_card` as the always-present L3 conversation envelope. It tells the
  main platform deepagent where it is and continues to support pre-RECON conversations.
- When a valid workspace-scoped Client-KB binding exists, attach `Stage0ProjectCard` as an
  additional `constitution.project_context_artifacts` L3 artifact. It tells the agent what is
  known, unresolved, and ready; it does not replace the conversation envelope.
- Do not dump all Client-KB facts into opening context. Claim refs must carry enough bounded,
  interpretable metadata for the agent to select the relevant product/competitor/positioning/etc.
  reference.
- A governed path to discover omitted Client-KB refs and dereference exact claims remains required.
  `inspect_statement_history` and `inspect_readiness_history` do not provide that capability.
- This two-artifact proposal was subsequently refined into independently owned brand/product,
  conversation-envelope, account-wide Client-KB, and active-project Stage-0 artifacts. See the
  binding production spec above.

## Change and verification

- Added the highlighted provisional decision and future checkpoint to root `CLAUDE.md`.
- Confirmed the current L3 loader already accepts the base `project_card_ref` plus additional
  `project_context_artifacts`.
- No production code, schema, runtime configuration, or tests changed in this documentation-only
  checkpoint.
