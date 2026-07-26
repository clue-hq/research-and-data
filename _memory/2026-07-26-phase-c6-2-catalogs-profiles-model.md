# 2026-07-26 — C6.2 catalogs, profiles, registry, and model seam

## Outcome

C6.2 is complete on `platform/c6-deepagent-runtime`. It adds the production resource/profile/tool
authority inputs and governed model provider required by later runtime construction. It adds no
database migration, durable turn/history/context record, deepagent construction, executor, route,
or feature flag. C6.3 is next.

## Implemented

- Added canonical folder resources:
  - Head-of-ABM, research-specialist, content-drafter, and reviewer V1 prompts;
  - additive `stage0-interview@v2`;
  - one active V1 profile for each initial role.
- Preserved the previously used flat Stage-0 V1 skill bytes at SHA-256
  `15576f389fb328dfc519d3b497584581181df281f80c9c6ef66cd2acd7e65461`.
- Added strict provider-neutral prompt/skill/profile catalog protocols and eager folder adapters.
  They reject mutable aliases, bad schemas/frontmatter, unknown metadata, folder/header mismatch,
  missing/extra files, links, executable resources, invalid UTF-8, and wrong expected hashes.
- Added `AgentProfileRegistry` with four required active roles, a projection-visible but planned
  account-research role, exact live tool-schema validation, replay/steering checks, engine
  ceilings, distinct delegation grants, child tool/workspace intersection, derived resource
  manifests/snapshots, and body-free/host-free projections.
- Added progressive skill disclosure: metadata and materialized path are projected first; a body
  opens only through an exact disclosed immutable address.
- Moved the C6.0 32-tool authority audit into production API composition. Human steering and seven
  replay-uncertified operations remain structurally absent.
- Added a deterministic scripted provider-neutral `BaseChatModel`.
- Added the production OpenRouter `BaseChatModel` wrapper/provider with standard tool binding,
  sync/async and streaming execution, primary/fallback handling, truthful requested/answering
  model metadata, usage and configured cost, gateway timeout/retry ceilings, and shared
  model-call tracing/events.
- Added the exact API composition exception required for
  `clue_api.agent_model_wiring -> clue_gateway`; direct provider-SDK imports outside the gateway
  remain forbidden.
- Updated the binding C6 spec, cross-session plan, and package README with the C6.2 close-out.

## Decisions

- Direct Head tools and delegated specialist grants are separate authority envelopes. Permission
  to delegate research does not expose research tools directly to the Head.
- `account_research` stays planned until C6.7; no active profile is created early.
- The C4 flat skill remains immutable. Semantic correction and strict metadata live in V2.
- Folder catalogs are the V1 provider, not the consumer contract. A future hub implements the same
  catalog protocols.
- Catalog/profile composition fails before model spend on any resource/tool drift.

## Verification

- Focused C6 agent/registry/model suite: 89 passed, 1 skipped.
- Ruff format/lint over all 820 tracked Python files plus 9 new C6.2 Python files: green.
- Mypy: 406 source files, green.
- Import-linter: 24 contracts kept, 0 broken.
- Repository pytest: 1,481 passed, 1,070 skipped.
- `git diff --check`: green.

The first import-linter run correctly rejected the new API-to-gateway composition edge. The
contract was fixed with one exact ignored transitive edge, matching the existing gateway factory
composition; the rerun passed all contracts.

Literal `make check` remains obstructed only by the preserved unrelated untracked `.claude/` and
`.codex/` structural-humanizer CLI copies. The equivalent complete source-controlled gate,
including all new C6.2 files, passed explicitly.

## Next

Proceed with C6.3: schema-first durable agent turns and receipts, seven independently budgeted
context layers, append-only history refs, body-free replay receipts, privacy/DSAR behavior, and
cold replay. Build against the exact C6.2 resource/profile/model contracts. Do not start C6.4
governed tool execution, plan compilation, delegation records, or finalization runtime early.
