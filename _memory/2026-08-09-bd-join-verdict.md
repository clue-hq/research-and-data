# 2026-08-09 — B↔D join verdict (Fable review): ACCEPTED. Lane D runs on real auth.

## What happened (sequence)

1. Founder directed: merge the hub (`platform/frontend-integration`, now carrying Lane B's full
   B2/B3/B4 auth + FI-2 slice 3) into this Lane D worktree BEFORE D5; then swap the injected
   test principal for the real `RequestPrincipal` and re-prove D1–D4 (the B↔D join); D5 builds
   on top; the lane later merges back whole.
2. Hub merge landed: `4c58d4db` (14 conflicts resolved — notably the executor.py D1×B4
   synthesis: agent nodes = service principal (`principal_kind="service"`,
   `actor_id="svc_execution_worker"`) + turn-derived ambient `action_ref`; human-authority
   nodes keep the turn's human actor_id in legacy kind) + `faa1030b` (alembic 3-heads→1
   `18541ff11335`, db-smoke green). FI-2's gross-estimate decision comment preserved verbatim
   in the launcher merge. Set-aside artifact: `/tmp/test_lens_isolation.py.local-backup`
   (local draft DIFFERS from hub's tracked version — owner should reconcile).
3. Join agent (Opus) delivered in 3 commits (`9dd07083`, `6708df23`, `c6963801`), reviewed and
   verified by me: **118/118 green** on the join acceptance + all D4 suites + chat + D1 +
   isolation guard + executor + tests/auth, run by my own hand.

## Join facts (for every future session)

- **One principal type:** Lane D's placeholder `RequestPrincipal` is DELETED;
  `chat/principal.py` re-exports `clue_auth.RequestPrincipal`. Auth-enabled path adapts Lane
  B's `PrincipalService` into the same `chat_principal_resolver` dependency (no route changes);
  dev path only reachable when auth is off; contradictory config (auth_enabled+local_header,
  or two identity sources wired) fails startup.
- The chat router's ToolContext is built by Lane B's `tool_context_for_principal` — without
  `principal_kind`/`membership_id`, B4's `require_human_authority` refuses the confirm tool.
  `PrincipalError` mapped in the chat envelope (was 500ing correct 403s).
  `create_thread@1` now stamps `created_via_membership_id` (the c4ccc7b11810 FK's waiter).
- **Executor synthesis ACCEPTED by the independent reviewer** with the right reasoning: the
  receipt (action_ref → submitter+membership+capture+gate) is stronger authority than an
  actor_id string; human `principal_kind` is unrepresentable at the C5 seam (needs membership);
  receipt-bearing gates correctly enter at the HTTP boundary only.
- **Real defect caught by the join:** `ResearchSelectionContract.confirmed_by` was written from
  the launching INVOKER — a model-planned launch would have recorded `svc_execution_worker` as
  "who approved this spend". Fixed: reads `directive.confirmed_by` (the human), with
  all-three-halves-or-none validation. This is exactly why the join test exists.
- Two merge breaks repaired: `create_workspace_membership` export removed in `64518cab` (both
  callers now use the `clue_auth.store` primitive, Lane B files untouched); Lane D's
  `actor_id=` kwarg on `tool_context_for_internal_service` (TypeError on every planned tool).
- Join acceptance: real `PrincipalService`, zero injected resolvers; approval refs RESOLVED
  back to U/membership/gate (never string-compared); V (real operator with `gate.respond`)
  → `GATE_FORBIDDEN`, gate unanswered; X (no membership) → `WORKSPACE_FORBIDDEN`, zero writes.
- Failure attribution MEASURED: baseline worktree at `faa1030b` fails 70 in tests/api; this
  tree 69 (5 pre-existing fixed, 4 "new" = the new file which passes in isolation). 68/69
  share one root cause: **`account.value_narrative` field-registry process-global pollution**
  via `register_narrative_wiring` appending to global `RESEARCH_PACK_LOADERS` — same CLASS as
  the hub's `4b7e09ea` gate-debt memo, DISTINCT instance. **Unowned; needs the same owner.**

## Push posture

NOT pushed. The branch now contains Lane B + FI-2 commits merged from the hub; publishing
other lanes' work to origin is the founder's call, not covered by the earlier Lane-D-only push
instruction. Awaiting explicit word.

## Next

D5 (frontend rebuild) builds HERE on real auth (B3 session/BFF is in-tree). Then the lane
merges back into the hub whole (one alembic merge if heads split again). Open items riding
forward: registry-pollution owner; C5-seam membership for human nodes (future); service-auth
adapter to replace the `svc_*` literals; lens-isolation backup reconciliation.
