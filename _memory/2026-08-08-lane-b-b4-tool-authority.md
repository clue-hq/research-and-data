# Lane B B4 — principal-to-tool authority and durable audit

Date: 2026-08-08
Branch: `platform/platformlane-b-auth`

## Shipped

- Added a closed provider-neutral `ServicePrincipal` species beside the human `RequestPrincipal`;
  neither accepts provider fields or allows human/service actor-class substitution.
- Added the API composition helpers `tool_context_for_principal` and
  `tool_context_for_service`. They inject internal ids, workspace, membership, and Lane-D-supplied
  `action_ref` as ambient `ToolContext` authority rather than model/client tool arguments.
- Extended `ToolContext` with the principal-kind and membership axes while retaining an explicit
  legacy-null shape until B5 removes old trusted-header surfaces.
- Added reversible migration `abbacac4df1f`: one immutable `execution_node_authority` row per tool
  node records actor class, human/service kind, authority workspace, internal actor id, human
  membership, and action reference. Composite FKs prove that a human actor and membership belong
  together and that the membership belongs to the execution workspace.
- The invocation journal inserts authority before its first attempt and includes the exact authority
  tuple in replay compatibility. Replaying one operation under another user/membership/action is an
  `OperationConflict`; historical nodes cannot be relabelled.
- Execution views now expose the durable authority row. No Clerk/provider type enters toolbelt,
  execution, fleet, research, or domain packages.

## Verification

- Fresh isolated Postgres schema upgraded to the sole head; B4 downgrade to the B1 head and re-
  upgrade passed.
- Focused auth/journal/executor set: 14 passed, including human audit durability, service separation,
  cross-user replay refusal, malformed user/membership FK refusal, and ordinary predeclared C5 node
  execution.
- Final auth/execution/projections regression: 109 passed on the Honiara-only Postgres container.
- Whole-repo Ruff lint passed; mypy passed across 590 source files; all 25 import-linter contracts
  were kept. The changed Python scope is Ruff-formatted. A whole-repo format check still reports 21
  pre-existing unchanged files outside Lane B; they were not reformatted in this lane.
- Final frontend gate: ESLint, 32 recursively discovered tests, design-system build, and Next.js
  production build passed; every application route is request-rendered and the proxy compiled.

## Diagnostic resolved

- The first implementation attempted to bind authority by updating a predeclared `execution_node`.
  The existing append-only trigger correctly refused it and an executor retry loop exposed the
  error. B4 now uses the separate append-only authority record; no update/trigger exception remains.

## Join / follow-up

- Lane D owns `turn-action:<turn_id>` derivation and its C5 executor call sites. It should consume
  these helpers after resolving its persisted turn; Lane B does not derive or accept action refs.
- B5 remains separate: legacy-null contexts and trusted-header routes are not removed here.
- No service credential issuer/adapter or Clerk credential was available, so no live human/service
  provider acceptance is claimed.

## Session closeout

- B2 commit: `870fadfa`.
- B3 commit: `68dbfd04`.
- B4 commit was amended with this final verification note after all gates passed.
- Worktree is clean apart from the unrelated pre-existing untracked `.playwright-mcp/` directory.
- No branch merge, cherry-pick, push, provider call, or credential mutation was performed.
