# 2026-08-09 — Lane B ⇄ Lane D join: the chat surface consumes the real authenticated principal

Branch `platform/platformlane-d-chat-launch`, on the merged head (`4c58d4db` + alembic merge
`faa1030b`, single head `18541ff11335`). DB: `localhost:55040/clue` (workspace-private; **never**
`:5432`). Commits: `9dd07083` (the swap), `6708df23` (the acceptance), plus the executor/pin test
updates.

**No new migration.** None was needed; `alembic heads` stayed at `18541ff11335`.

## What the swap is

- **One principal type.** `clue_api.chat.principal.RequestPrincipal` (the D0 dataclass placeholder)
  is deleted; the module now imports and re-exports `clue_auth.RequestPrincipal`. The contract said
  Lane B's chain "replaces [the placeholder] outright at the B2 join" — it does. Consequences:
  `authenticated_at` is now required at every construction site, `.allows(p)` is gone (callers use
  `p in who.permissions`), and `role_key`/`permissions` are Lane B's Literals.
- **`CHAT_PERMISSIONS` = `permissions_for_role(DEV_ROLE_KEY)`**, not a hand-rolled subset. D0's
  narrower set predated gate answering; a dev principal whose permission set differs from
  production's for the same role stops being a fixture *of* the real substrate.
- **`bind_authenticated_principal(service)`** (in `chat/router.py`) adapts Lane B's async
  `PrincipalService` chain into the same `chat_principal_resolver` dependency the routes already
  declared — no route changed. It reuses `principal_from_request(request)` when Lane B's workspace
  resolver already ran (cache coherence), and re-checks the workspace selector against the
  authorized workspace (ruling 6).
- **Precedence, made explicit.** `install_chat_surface(auth_service=…, principal_resolver=…)`:
  auth service > injected resolver > guarded dev resolver, and **both wired raises
  `ProductionPrincipalRequired` at composition**. `projections_main` builds the dev
  `StartupDevPrincipalResolver` only when `not auth_enabled`, and refuses at startup when
  `chat_enabled and auth_enabled and projections_auth_mode == "local_header"` (or the mirror case).
- **The ToolContext is Lane B's.** `chat/router._invoke` now calls `tool_context_for_principal`, so
  it carries `principal_kind="human"` + `membership_id`. **This was load-bearing**: without it, B4's
  `require_human_authority(action_ref_required=True)` refuses
  `confirm_account_research_directive@2` and the entire D4 gate→confirm path 422s.
- `gate.respond` is now required on the gate-response path (§3.5), checked before any write.
- `PrincipalError` is mapped in `_EnvelopeRoute` — Lane B's 401/403 codes are raised during
  *dependency* resolution, which happens inside the route handler, so without the clause the
  generic catch turned every correct 403 into a 500.
- `create_thread@1` stamps `created_via_membership_id=ctx.membership_id` — the seam migration
  `c4ccc7b11810` explicitly said it "remains unwritten until Lane B's B4 carries membership through
  the ToolContext seam". It does now.

## Two genuine merge breaks (textually clean, semantically broken)

1. **`create_workspace_membership` was no longer exported from `clue_auth`** — Lane B's `64518cab`
   narrowed the public API to the permission-checked `create_workspace_member`. `clue_api.chat` and
   `tests/_identity` imported the old name, so **`import clue_api` raised ImportError** and all of
   `tests/api` failed to collect. Both callers are workspace-*owner bootstraps* with no acting
   membership — the same case Lane B's own `provision_workspace_owner` /
   `accept_workspace_invitation` solve with that primitive — so they now import it from
   `clue_auth.store`. No Lane B file was edited.
2. **`agent_execution_wiring` pin resolution** kept Lane D's `actor_id=` kwarg on Lane B's
   `tool_context_for_internal_service(...)` → `TypeError` on every model-planned plan
   (`pin_resolution_failed`). Fixed by dropping `actor_id` (pin resolution is the execution
   *service's* own read) and keeping `action_ref`.

## Verdict on the merge's executor synthesis — ACCEPTED

The merge resolved D1's identity threading against B4's stamping at the three C5 `ToolContext`
sites as: agent nodes → `principal_kind="service"`, `actor_id="svc_execution_worker"` + the
turn-derived ambient `action_ref`; human-authority nodes → the turn's human `actor_id`, legacy kind.

- **Agent half: right.** The executor is a detached worker. Ruling 8 is explicit ("may execute an
  agent turn that carries a persisted human approval receipt, but may not synthesize a human
  `actor_id` from its own service credential") and §7 says the receipt is the evidence. The human's
  authority is not lost — `turn-action:<turn_id>` resolves to the submitter, their membership, the
  capture digest and (for a gate answer) the exact gate, which is *stronger* than an actor_id
  string. Proven end to end by the D4 model-planned kickoff.
- **Human half: right, and necessarily incomplete.** `principal_kind="human"` is *unrepresentable*
  at the C5 seam — `ToolContext.__post_init__` requires a `membership_id` for a human principal and
  `executor.execute()` takes a bare `actor_id` string. `None` (legacy) is the honest shape.
  Fail-closed consequence, and correct: a receipt-bearing human-only tool still cannot be entered
  through the executor, which is why D4 runs confirmation at the HTTP boundary instead.
- **Follow-up (not blocking):** when the C5 seam can carry a membership (or takes a
  `RequestPrincipal`/`ServicePrincipal` instead of a string), the human-authority node should become
  a real `principal_kind="human"` context. Until then, a human-authority *node* cannot carry a
  receipt-bearing gate.

## One real defect the join exposed (fixed)

`ResearchSelectionContract.confirmed_by` was written from the **launching invoker**
(`ctx.actor_id or ctx.actor`) while its pair `confirmed_at` came from the directive row. They
agreed only while the launcher's caller happened to be the human. Once a model-planned launch runs
as a service principal it would have written `svc_execution_worker` into a field meaning "who
approved this spend", beside a timestamp of when the human did. `account_research_fleet_launch` now
reads `directive.confirmed_by` (and requires it non-NULL alongside the other two receipt halves).

## The join acceptance — `tests/api/test_lane_bd_join_acceptance_db.py`

Builds the projections app with the **real** `PrincipalService` (`LocalFixtureAuthenticator` over
the real `auth_identity` → `platform_user` → `workspace_membership` chain) and **no**
`chat_principal_resolver` at all. Headers a browser would send: `X-Clue-Local-Auth-Subject` +
`X-Clue-Workspace-Id`. Four tests:

1. **The flow.** authenticate as U → `POST /threads` → `POST /turns` → gate → structured
   `gate_response` → confirm → launch. Asserts on real rows: `agent_thread.created_by_user_id` **and**
   `created_via_membership_id`; `agent_turn_submission.submitted_by_user_id`/`_via_membership_id`;
   the gate's `addressee_user_id`; the answer's `answered_by_user_id` and `action_ref`;
   `account_research_directive.confirmed_by`/`confirming_turn_ref`; the run's
   `selection.confirmed_by` and `approval_refs` — and each approval ref is **resolved back** through
   `resolve_gate_answer_action` to U, U's membership and that gate, not merely string-compared.
2. **V** (a second real member, provisioned through the *governed* `create_workspace_member` with
   U's owner membership as the acting admin, role `operator` so it *holds* `gate.respond`) submits
   turns of their own fine and gets `403 GATE_FORBIDDEN` on U's gate; the gate stays unanswered and
   the directive stays `draft`; V's own turn receipt refuses as `gate_answer_not_found`.
3. **X** (real, authenticated, member of nowhere) gets `403 WORKSPACE_FORBIDDEN` on write *and*
   read, with submission/thread counts unchanged across the refusal.
4. **Selector ≠ credential**: U naming another workspace, and U naming none, are both
   `WORKSPACE_FORBIDDEN`.

Red-proofed: reverting `_invoke` to the hand-built legacy `ToolContext` fails test 1.

Fixture note: `tests/_identity.fixture_membership_id(workspace_id, user_id)` makes the seeded
membership id deterministic, so a test principal can be built without a DB round trip and the new
composite ownership FK can never drift from the seed.

## Test results

All green, per-suite and in one 296-test batch: D1 turn-action, D2 submission + gateway isolation,
D3 extractor + stream, D4's four suites, chat surface, B1-join, the new join acceptance,
`tests/auth`, `tests/execution`, `test_agent_execution_wiring`, `test_stage0_routing_honesty`.
`make lint`, `make typecheck`, `lint-imports` (25/25) all clean. Single alembic head.

**Full `tests/api` batch: 69 failures, all pre-existing pollution — measured, not assumed.** A
baseline worktree at `faa1030b` (with only the 2-line import repair, without which nothing
collects) fails **70**. Diff of the two failure sets:
- **fixed by this work (5):** the `pin_resolution_failed` cascade in `test_agent_execution_wiring`
  (3) and `test_stage0_routing_honesty` (2) — merge break #2.
- **"new" (4):** only the new join-acceptance file, which passes in isolation and in the 296-test
  batch and fails in the big batch for the same reason as the other 64.

Root cause of 68/69: `field_key 'account.value_narrative' is already registered with a different
definition` — a **process-global field-registry** poisoned when many suites load research packs in
one process (`register_narrative_wiring` appends to the global `RESEARCH_PACK_LOADERS`). This is the
same *class* as the `SourceManifestRedefinitionError: 'apollo' already registered` in the
`4b7e09ea` memo, but a **distinct, additional** instance: `4b7e09ea`'s cascade starts with
`tests/db/test_db_migrations.py` downgrading the shared DB mid-suite, which does not run here.

## Open items

1. **[unowned, pre-existing] `account.value_narrative` global-registry pollution** poisons ~64
   `tests/api` tests in a single-process batch. Needs the same owner as the `4b7e09ea` full-suite
   gate debt. Make the pack registration idempotent-by-definition or reset the registry per module.
2. **[C5 seam] human-authority executor nodes cannot carry a closed human principal** (no
   membership at the seam) — see the verdict above. Blocks nothing today.
3. **`svc_execution_worker` / `svc_agent_execution` are literals**, not configured service ids and
   not `platform_user`-backed (correctly — they are services). If a service-auth adapter lands they
   should come from it.
4. **D5 (frontend flip) is not started**; `apps/frontend/**` untouched, as instructed.
