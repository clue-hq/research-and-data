# 2026-08-09 — E2E demo unblock: Clerk auth contract rewrite + first chat-enabled fleet boot

Session goal: the founder's first live end-to-end demo (projections API + fleet worker + frontend,
full Clerk auth) hit two blockers. Both are now fixed; this note records what was durable.

## 1. Sign-in 401 `SESSION_INVALID` → **auth contract ratified: session-token-native** (commit `7940ecb2`)

**Root cause (verified against the live Clerk instance, not inferred).** The Lane B contract
required claims `iss/sub/sid/iat/nbf/exp/aud/azp` and verified `aud` against
`CLUE_AUTH_CLERK_AUDIENCE`, with the frontend minting via JWT template `clue-api`. Minted a real
template token via the Clerk backend API and decoded it: claims were
`aud,exp,iat,iss,jti,nbf,sub` — **no `sid`, no `azp`**. Clerk docs confirm: session-bound claims
(`sid`, `v`, `pla`, `fea`) *cannot* be included in template tokens, and `azp` is reserved
(populated from browser Origin; absent on server-minted template tokens). The default session
token conversely has `sid`/`azp` but no `aud`. **Neither Clerk token shape could ever satisfy the
required-claims list** — the passing tests minted synthetic 8-claim tokens no real Clerk token
matches. The contract had never been validated live.

**Founder ratified option (a), session-token-native** (Clerk's own SDK model):
- Backend (`clue_auth/providers/clerk.py`): `required` drops `aud`; `verify_aud: False`;
  `ClerkJwtConfig.audience` and `Settings.auth_clerk_audience` **removed**; `auth_wiring` no
  longer demands `CLUE_AUTH_CLERK_AUDIENCE`. Authenticity = RS256 signature + `iss` + `azp ∈
  authorized_parties`; `sid` still required (stored as `provider_session_subject`); `sts=pending`
  rejection retained.
- Frontend: `getToken()` with **no template**; `clerkJwtTemplate()` and the
  `CLUE_CLERK_JWT_TEMPLATE` config requirement deleted.
- `session/establish/route.ts` now routes through `getProtectedSession` (401 → `/sign-in`
  redirect instead of a 500 page).
- Contract recorded in `apps/frontend/docs/api-contracts/session.md` (dated supersession note);
  runbook + `.env.example`s swept. Dead env lines removed from live `.env`/`.env.local`.
- Tests: fixture tokens now mirror the real default-session-token shape (no `aud`); new cases pin
  missing-`sid`/missing-`azp` fail-closed and `aud` non-participation (incl. list-valued `aud`).
- Gates: runbook matrix `pytest tests/auth tests/test_config_settings.py
  tests/api/test_projections_app.py` = 75 passed (DB-gated included); frontend 108 tests + lint +
  build green. NOTE: sourcing the dev `.env` into a pytest run breaks settings tests
  (`CLUE_CHAT_REASONING_TRACE_MODE=raw` + `auth_environment` leak into `load_settings`) — export
  only `CLUE_DATABASE_URL` for test runs.

## 2. Fleet `FieldRedefinitionError: account.value_narrative` → **dev-DB row patched**

The known unowned hub-side gate-debt instance (Lane D close-out flagged it). The stored
`field_definition.value_schema` predated commit `5fa0403c` (FI-2 slice3 T1), which added
`project_id` to `_VALUE_NARRATIVE_SCHEMA`; `register_field` correctly refused the semantic diff.
Applied (after a rolled-back dry-run proving it makes the **full** `load_research_packs` clean —
it was the only stale row among 65):
`UPDATE field_definition SET value_schema = jsonb_set(value_schema,'{properties,project_id}','{"type":"string"}'::jsonb) WHERE field_key='account.value_narrative';`
Zero claims existed on the field; the `research_view_field_route` FK child made UPDATE (not
delete/reinsert) the right shape. This is dev-DB hygiene, not a code fix — the underlying
shared-DB pack-loader drift class remains unowned (hub side).

## 3. First chat-enabled fleet boot — **C6 audit ordering defect fixed** (commit `5ed1278a`)

`fleet_main` composed the agent turn handler (→ `build_agent_profile_registry` → C6 audit) *after*
`register_execution_control_tools` widened the shared registry with 9 run-control tools →
`AgentCatalogError ... extra=[9 tools]` at every chat-enabled boot. The audit's reviewed surface
is exactly `build_toolbelt()` names (53, pinned by `tests/agents/test_tool_authority_audit.py`),
so the fix is the reorder (agent-turn composition first), with a loud ORDERING IS LOAD-BEARING
comment. This path had never run: Lane D's flag-on pass was honestly handed back (no `.env` on
the agent machine).

## 4. Env/config findings during boot iteration (live `.env` now correct)

- `CLUE_CONTACT_CHANNEL_ENRICHMENT_ENABLED=true` → boot refusal
  `EntityResearchProductionCompositionError: channel enrichment is enabled without an independent
  validator-backed coordinator`. **Flipped to `false`.** Real composition gap:
  `build_production_contact_channel_coordinator` has **zero production callers**
  (`fleet_main` never passes `channel_coordinator`) — same "awaiting composition" class as the
  2026-08-07 audit backlog. Add to the composition to-do list; do NOT re-enable the flag until an
  owner wires transport+validator.
- `CLUE_AGENT_WORKSPACE_ROOT` was empty → `WorkspaceConfigurationError`. Set to
  `/private/var/tmp/clue-agent-workspace` (macOS: must be the `/private/...` form — the policy
  refuses symlink traversal, and `/var` is a symlink; must be outside repo and `$HOME`, parent
  must exist). Fine for local dev; production wants a dedicated non-shared-tmp root per the
  `.env.example` guidance.

## 5. Dev-queue state + residuals

- 100 stale `entity_research_job` rows (pre-launch-authority-contract) now terminally `failed` —
  the worker's per-job fail-closed refusals ("lacks one exact subject-specific launch authority"),
  correct over synthetic data. Not boot errors.
- `tests/api/test_agent_registry_wiring.py::test_resolved_snapshot_materializes_through_c61_backend`
  fails **identically on the unmodified tree** (`WorkspaceSecurityError: workspace parent
  directory does not exist`) — pre-existing baseline-failure class from the Lane D merge memo;
  unowned, not touched.

## Final state

Both commits local (never push without instruction). All three processes verified bootable:
projections API (was already fine), fleet worker (boots, polls, executes), frontend (build green).
Next step is the founder's live browser pass: sign-in should now produce a default session token
that verifies; first conversation exercises streaming + raw reasoning trace + inspector live.
