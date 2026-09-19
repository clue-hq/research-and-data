# PR #62 (`codex/design-agent-v1` → `research-streaming`) — merge context (2026-09-17)

Analysis-only session; no code changed, nothing committed. A changelog comment was posted on
PR #62 (files by area, feature changes, migrations, env keys, merge status).

## Shape of the branch
- Merge-base `00f510f38` (2026-08-31). Branch: 479 commits ahead, 920 behind. `git cherry` shows all
  473 non-merge commits are patch-unique — nothing double-landed.
- Two lines on the branch: akeshri003's scene-ad/web-editor line (2026-08-24→09-08: rich text,
  clipboard, selection v2, live streaming, web annotations, F5 publishing, logo family, fonts) and
  Shashank's design-agent-v1 line (2026-09-07→09-16: 18-family scene skill catalog, reference-led
  delivery, ABM identity composition, solo scene mode, scoped design preferences, Brandfetch).
- Design-side bulk (`subsystems/clue-design/*`, `apps/frontend/src/features/design-editor`) merges
  clean; the target barely touched it.

## Dry merge result (scratch worktree, since removed)
- 37 conflicting files, all content conflicts. Real head count after merge = 2 Alembic heads
  (`fa0b41b0ffdc` branch, `f74cbccd3200` target) → needs `alembic merge`.
- Duplicate-feature conflicts (hardest; pick one implementation, retire the other's setting):
  - Fleet multi-slot worker: branch `max_concurrency`/`CLUE_FLEET_MAX_CONCURRENCY` (05e615eb0)
    vs target `concurrency`/`CLUE_FLEET_WORKER_CONCURRENCY` (ff4cfd657, founder ruling 2026-09-10).
    Both settings exist in settings.py after merge. Target also carries slot traceparent (609e67a9f).
  - Gateway transient retry: branch `_TRANSIENT_RETRIES`/`_is_transient_provider_error` (ca765d4d5)
    vs target `_MAX_TRANSIENT_ATTEMPTS`/`_transient_retry_backoff_s` + public metadata keys.
    `tests/gateway/test_agent_model.py` is one 724-line hunk.
- Both-survive conflicts (additive): `ContextRef.note` (branch) + `.title` (target);
  `design_run_purger` (branch) + `ProjectLibraryRefresher` (target) in agent_turn/platform wiring;
  `chat/schemas.py` object_type adds `project_document` (target) + note docs (branch);
  `composer_context.py` imports; `lumen_api/main.py` imports (`SetWorkspaceHandleRequest` +
  `RenameDocumentRequest`); `.gitignore`; `_memory/README.md`.
- Frontend: chat-surface (annotation chips + clone text commit vs research card/stop control/
  target-accounts/document tabs), project-composer (`submittableWithoutPrompt` vs `hasComposerDraft`
  + stop action), use-project-chat-controller (stream cursor/anchor reload vs plan-write tracker),
  brand-context (assets/uploads + registry records vs MDX knowledge editor + platform folders),
  session establish route + app-sidebar (local workspace cookie vs Settings `WORKSPACE_COOKIE`/
  profile menu), design-leg/chat-transcript tests, package-lock (regenerate).
- Config: `.env.example` (Clerk parties list, fleet block, parity sweep vs product-path block),
  `subsystems/clue-design/.env.example`, `apps/frontend/.env.example` (fixture-mode flag on target),
  `scripts/dev_stack.sh` (7 hunks: local workspace/IPv4 vs restart verbs/pkill anchoring/port knobs).

## Open decisions for the founder before resolving
1. Which fleet concurrency implementation wins (target's is the ruled one; branch's has the
   claim-while-slots-remain loop and `drain_once` split).
2. Which gateway retry policy wins (target's has backoff + public metadata keys).
3. Local workspace instances (branch) vs Settings session model (target) for the workspace cookie.
4. Brand-context: keep branch's assets/uploads listing on top of target's MDX editor.

## Execution record (same day, later session) — merge landed locally, NOT pushed

Founder rulings (2026-09-17): merge, not rebase; fleet worker = target's implementation wholesale
(drop `fleet_max_concurrency`/`CLUE_FLEET_MAX_CONCURRENCY` everywhere, map the dev-stack recipe onto
`CLUE_FLEET_WORKER_CONCURRENCY`); gateway retry = target's, with the branch's in-body 502 shape as a
follow-up; everything else both-survive as proposed; local-instance workspace cookie layered over
the Settings session model.

Commits on `codex/design-agent-v1` (local only — the user pushes and merges the PR):
- `5d92bddb9` Merge origin/research-streaming into codex/design-agent-v1 — all 37 conflicts,
  plus the semantic fixes the gates surfaced: composer_context import block (my first union broke
  it), a duplicate `designRefreshForEvent` import in the chat controller, both `_NoMemoryContext`
  stubs grown to the branch's `ContextAssembly.select/resolve` protocol (mypy), the
  generating-motion stylesheet's local tokens renamed `--clue-gen-*` → `--gen-*` (the target's
  design-system token guard reserves `--clue-*`), the local-workspace integration test given a
  `Request` and an `INVITATIONS_UNCONFIGURED` stub for the merged establish route, three
  pre-existing ruff findings in empty Alembic merge revisions auto-fixed, Alembic join
  `be968ae45500` (fa0b41b0ffdc + f74cbccd3200), `apps/frontend/package-lock.json` regenerated.
- `5b8803425` contract_v1: `zod-fields.json` regenerated + accounts.md E5 `customFields` row.
  Target-side drift; only visible once `apps/frontend/node_modules` exists (the Zod half skips
  without it).
- `1a7ba4c91` gateway: the ruled follow-up. `transient_upstream_failure` now reads a NUMERIC
  in-body `code` (OpenRouter relaying the upstream status: `{"message": "Auth context expired",
  "code": 502}`) through the status rule; enum strings unchanged; three classifier cases pinned.

Verification (all on the merged tree): ruff check + format, mypy (858 files), lint-imports (27
kept), frontend gate (design-system build, lint — 2 pre-existing branch warnings —, build) and
3163/3164 frontend unit tests (1 skipped); focused backend suites green; migration smoke
up→down→up green on a fresh throwaway DB `clue_papeete_pr62` (left in place for re-runs; drop at
leisure).

Broad backend pass (`tests/api tests/fleet tests/agents tests/gateway tests/memory tests/design
tests/auth`, no live): everything green except 7 tests, triaged as follows —
- 5 DB-flavoured (`test_account_entity_research_r5_db` ×2, `test_pilot_budget_controls` ×3):
  they reach a database WITHOUT the `CLUE_DATABASE_URL` gate (`tests/durable/conftest.rollback_conn`
  / `tests/profiling/conftest.rollback_conn` open `db_lifespan()` on the DEFAULT DSN, i.e. the
  local `clue` DB, which sits at `63294c3ce019`, far behind head). All five PASS against the
  migrated throwaway DB. They use rolled-back transactions; the `clue` DB shows zero rows created
  in the window. Pre-existing target-side test hygiene, not a merge defect.
- 2 code-level, REPRODUCED ON THE TARGET ITSELF (scratch checkout of origin/research-streaming
  with PYTHONPATH pinned to it, imports verified): `test_agent_registry_wiring::
  test_design_profile_resolves_with_the_full_granted_write_surface` expects the design profile on
  `openai/gpt-5.6-terra` while the catalog (both sides) pins `openai/x-ai/grok-4.6`; and
  `test_client_knowledge_privacy_s4e::test_frozen_contracts_and_current_skill_both_state_the_
  untrusted_evidence_boundary` pins `head-of-abm@v56` while the catalog is at v57. Left untouched:
  research-streaming's debt, out of this merge's scope. **Follow-up for the target lane.**

Not done / owed: no `git push` (rule); PR #62 still shows CONFLICTING until pushed; the design
subsystem's own suite (`subsystems/clue-design`) was not run (only 12 files there changed, all
env/docs/imports; the >1h rule applies).
