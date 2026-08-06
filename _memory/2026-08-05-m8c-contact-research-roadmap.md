# 2026-08-05 — M8C contact research roadmap

## Session intent

Persist the technical design for contact-level research following M8B account profiling
and Sumble no-reveal committee discovery. This was a planning/documentation session; no product
code, migration, provider call, credential access, or spend occurred.

## Decisions recorded

- Added `docs/specs/M8C-contact-deep-research-and-selected-contact-enrichment-roadmap.md` as a
  companion to M8B instead of rewriting M8B's implementation history.
- Reuse the existing detached account fleet, `AccountDeepOrchestrator`, committee worker,
  `profile_contact` fan-out, claim store, verification/use gates, and handoff surfaces. Do not build
  a second contact fleet or provider-specific orchestrator.
- Preserve harness-first, non-linear user control. Contact research is launched from a confirmed
  directive and an immutable selected-contact receipt; it is not an automatic phase transition.
- Materialize Sumble-returned title/function/level/team/location/relationship data as professional-
  public claims before spending again.
- Extend the generic external-research substrate to exact contact subjects and add an external
  preparation/wait seam outside claim transactions for contact-targeted Exa and optional reveals.
- Separate channel observation, identity corroboration, deliverability validation, use permission,
  and verified-identity promotion. Email and phone require separate approvals and budgets.
- Keep the content boundary clean: M8C emits an `account x contact x persona` claim-ref bundle;
  later content scaling consumes it and does not call research providers.

## Provider-document finding

Current public Sumble documentation reviewed on 2026-08-05 describes the v3 People endpoint and a
response with professional profile fields but no documented email/phone. The repository also has a
pinned and live-exercised M8B v9 contract. Public v3 docs do not invalidate that working contract;
M8C C0 must capture both and determine which entitled contract applies to each new operation before
adapter or paid reveal work. Current Exa Search docs support deep/deep-reasoning and JSON output
schemas; current Websets docs support person entities, imports, and email/phone enrichment formats,
but deliverability and permission remain separate platform decisions.

## Planned slices

- C0 contract/field/policy freeze
- C1 Sumble snapshot-backed professional facts
- C2 exact contact-subject durability
- C3 contact-targeted Exa compiler
- C4 durable Exa contact acquisition/materialization
- C5 selected-contact reveal and independent validation
- C6 provider-neutral wait/resume and production composition
- C7 handoff/content-consumption bridge
- V0 offline/database acceptance
- V1 bounded live-provider acceptance with explicit authorization

## Closing state and verification

- Confirmed every local Markdown target referenced by M8C exists.
- `git diff --cached --check` passed after staging the four scoped files.
- The M8B pointer and specs index resolve to the new M8C filename.
- No code test was run because the change is documentation-only; no product code, schema, or runtime
  configuration changed.
- All unrelated modified and untracked files were preserved and excluded from the scoped commit.
