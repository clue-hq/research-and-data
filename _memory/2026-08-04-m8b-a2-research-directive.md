# M8B A2 — durable research directive and context binding

## Scope

- Implemented Slice A2 only: the provider-free research-directive contract, persistence,
  draft/confirm tools, preview, exact run pins, memory submission, and agent context propagation.
- Left the `resolvers/exa` E0 ownership boundary untouched for the parallel implementation lane.
- Made no provider request, credential read, contact reveal, or paid call.

## Implementation

- Added bounded immutable directive, account-override, effective composition, and content-digest
  models in `clue_core.research_directive`.
- Added Alembic revision `8f44b739674c` for append-only directives/overrides/events, human
  confirmation receipts, exact draft-request fingerprints, and immutable pre-start `account_run`
  directive pins.
- Added the research directive store/service with project, product, ICP, source, account, and
  workspace lineage validation; exact idempotent replay; advisory-lock convergence; confirmation;
  supersession; account composition; and `AccountSpec` compilation.
- Added zero-spend `draft_account_research_directive@1` and human-only
  `confirm_account_research_directive@1`, the directive preview projection, production memory
  wiring, and Head-of-ABM profile v15.
- Propagated the exact directive pin through account specifications, research plans, scheduler,
  account runs, account profiling, committee eligibility, and Sumble acquisition authorization.
- Materialized the effective directive as `context/project/research-directive.json`; delegated
  research specialists receive the exact file and typed domain reference automatically.

## Decisions preserved

- User-stated preferences live in scoped memory; executable research intent lives in the typed,
  confirmed directive. The two representations remain separate and referenceable.
- Confirmation is a human transition over an exact digest. Agent profiles can draft but cannot
  confirm.
- A directive pin is attached before account execution begins and cannot be retrofitted or mutated
  afterward. A later confirmed version supersedes future selection only; existing pinned replay
  may still resolve its exact superseded version.
- Provider request/authorization checks compare the exact directive ref and digest rather than a
  loose project-level direction identifier.
- Legacy A1 callers that have no A2 pin retain their former call shape; the orchestrator supplies
  the new argument only when a directive is present.

## Verification

- One Alembic head: `8f44b739674c`; the isolated Roseau database is at that head after clean
  migration smoke.
- A2 plus adjacent A1, account-deep, committee, Sumble preparation/acquisition/source/eligibility,
  and durable-orchestrator regression suite passes.
- Ruff check, scoped Ruff format check, full mypy, and all 24 import-linter contracts pass.
- A broader repository run still contains a pre-existing frozen Head-of-ABM v1 tool-schema digest
  drift for `evaluate_stage0_readiness@1`; A2 does not modify that frozen profile or unrelated tool.

## Next boundary

- E0 may proceed independently in `resolvers/exa`.
- Subsequent account-deep work can consume the A2 exact directive pin without introducing a
  mechanical discovery-to-deep transition or bypassing the user's conversational go-ahead.

## Critical-review remediation — P1/P2

- Reopened A2 after review. Root causes were authority represented as caller-shaped strings rather
  than durable relational membership, launch paths treating pins as optional compatibility data,
  source validation treating registry presence as authorization, a caller-authored human receipt,
  and presentation/context/artifact lifecycle contracts narrower than the executable directive.
- Added revision `5330703a78a3`: exact immutable directive-account membership, override and
  account-run membership FKs, and reverse project bindings for agent artifacts. A strict discovery
  seal resolves against the exact workspace/project/ICP manifest lineage at draft time. Production
  DEEP and Sumble preparation now fail closed unless the exact confirmed account pin is present.
- Directive sources now compile against the pinned ICP's canonical effective field-source plans;
  contact-yielding committee sources are the only separate enumeration allowance. Overrides can
  narrow but cannot widen the project source set.
- Added the v2 draft/confirm tool contracts and active Head-of-ABM profile v16. V2 draft returns the
  complete typed preview plus its digest and explicit `persisted`/`memory_disabled` outcome. V2
  confirmation accepts no attribution fields and derives the human id/action ref from `ToolContext`;
  missing ambient receipt fails closed. Historical v1 stays replayable but is not active/default.
- Added canonical UTF-8 ceilings: 48 KB directive body, 64 KB effective account directive, and 8 KB
  user instruction. Account research context policy v2 gives required L3 project artifacts 128 KB
  and L4 memory 16 KB under the existing UTF-8 byte counter.
- Account-research artifacts now carry account and project reverse bindings. Project deletion is
  restricted until `AgentPrivacyService.erase_project` tombstones/purges exclusively owned CAS
  bodies and releases the project binding.

## Remediation verification

- Focused A2 plus adjacent account-deep/S2B/S2C/S2D/O2/toolbelt/catalog/turn regression matrix:
  passed after final formatting and typing fixes.
- Ruff format/check on every changed Python file: passed. Full mypy: 506 source files passed.
  Import-linter: 24 contracts kept, 0 broken.
- Disposable database `clue_a2_smoke_20260804`: full Alembic head -> base -> head passed and ended at
  single head `5330703a78a3`.
- No provider request, credential read, contact reveal, or spend occurred. `resolvers/exa` remains
  untouched for the parallel E0 lane.
