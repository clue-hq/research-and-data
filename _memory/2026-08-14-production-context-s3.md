# 2026-08-14 — Production deepagent context S3

## Scope

- Completed only S3 from `docs/specs/FI-production-deepagent-context-composition.md`.
- S4 governed claim discovery/inspection, S5 product-catalog selection, and S6 live browser/provider
  acceptance remain intentionally unstarted.
- No database migration was required for S3; the existing S0-S2 contracts and bindings were the
  composition prerequisites.

## Changes and decisions

- The real production `AGENT_TURN` fleet worker now resolves one immutable scope before execution,
  loads the real brand and confirmed product through L2, and persists three L3 inputs: the v2
  conversation envelope, the account-wide `ClientKnowledgeCard`, and exactly the active project's
  `Stage0ProjectStateCard`.
- Client-KB and Stage-0 artifacts are all-or-nothing conditional context. Pre-recon remains an
  honest empty pair; post-recon compilation/persistence must succeed before the envelope advertises
  availability or a model request exists.
- The constitution carries typed `client_knowledge` and `stage0_project_state` domain refs. Contract
  validators fence the client ID, exact non-null KB version, active project ID, workspace, names,
  and pair cardinality.
- The shared Client-KB artifact is subject-bound but deliberately not project-bound. Its
  content-addressed ref is reusable across Projects A and B; each project gets a distinct
  project-bound Stage-0 artifact.
- Account-wide and product-scoped KB marker/read sequences now filter with exact null-safe product
  equality. A newer product KB can no longer replace or contaminate the shared onboarding KB.
- Committed fleet retries now replay before recipe startup, scope reload, or card composition. This
  preserves the original durable context receipt and vN artifact refs even after recon publishes
  vN+1, while idempotently repairing any missing history/stream/recipe-close projection.
- Added the privacy-safe `agent_turn.context_composed` and `agent_turn.context_replayed` events.
  They include only operational IDs, availability, version, and content hashes—never bodies,
  claims, artifact keys, email, credentials, or tokens.
- Repaired the stale C6.3 database fixture identified during S2: its synthetic L7 input now uses
  the request's actual user-message artifact and required `current_user_instruction` origin.

## Verification

- Complete S3/adjacent production selection: 119 passed across contracts, L1-L7 assembly,
  projection compilers, PostgreSQL/artifact composition, fleet submission/replay, streaming,
  journaling, DSAR, and legacy compatibility.
- Added S3 DB acceptance proves pre-recon honesty, post-recon composition, real L2 brand/product,
  Project-A/B isolation, shared content-addressed Client-KB reuse, exact receipts/hashes/paths,
  vN/vN+1 turn pinning, missing-artifact refusal, foreign-workspace refusal, and body-free logs.
- Additional account/product scope regression: 36 passed across S3, reverse-profile, and dynamic
  Client-KB suites; product-scoped v2 coexists with and cannot displace account-wide v1.
- Combined final database regression selection: 151 passed.
- Full repository mypy: 660 source files, zero issues.
- Import-linter: 25 contracts kept, zero broken.
- Ruff and `git diff --check`: clean.
- Alembic: one head, `b2f815da0f31`.
- Retained isolated PostgreSQL database: `clue_context_s3_20260814`.

## Follow-up

- Begin S4 only when requested: add governed, pinned-version Client-KB list/inspect tools and wire
  them end-to-end into the production profile, toolbelt, surface policy, recipe pins, and skill.
- S6 must later perform the real browser/provider acceptance; S3 evidence is provider-free
  production composition and must not be described as live E2E proof.
