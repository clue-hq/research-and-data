# 2026-09-28 — Custom-domain publishing × F5 multi-page: one hosting design

Branch `website/custom-domain`, worktree `addis-ababa`, lane DB `clue_addis-ababa@55040` (recreated
empty by the merge task, migrated to head `770bf20802e1` by Task 1's fixtures).
Plan (with the ruling and the seven decisions): `docs/superpowers/plans/2026-09-28-custom-domain-f5-reconciliation.md`.
Per-task briefs, reports and the ruling ledger: `.superpowers/sdd/2026-09-28-custom-domain-f5-reconciliation/progress.md`.
Spec (binding for our side): `docs/superpowers/specs/2026-09-17-custom-domain-publishing-design.md`.
Predecessors: `_memory/2026-09-17-custom-domain-publishing-s1.md`, `_memory/2026-09-17-custom-domain-publishing-s2.md`,
and F5's own record `_memory/2026-09-03-f5-multipage-build-close.md` (arrived with the merge).

## Why two designs existed

Two lanes built `<label>.pages.cluehq.ai` independently:

- **F5 multi-page** (`design/website-multi-page`, 2026-09-03, ruling R-F5-5): a `design_workspace_handle`
  table (migration `5456c0770de8`), the handle locked at the first publish, a Host-routed sub-app
  inside the design API behind `LUMEN_PUBLIC_PAGES_HOST_SUFFIX` / `LUMEN_PUBLIC_PAGES_SCHEME`, the
  `/w/` interim routes kept, custom domains left as a future seam. Multi-page sites: per-page
  publish rows (migration `6893f29b6973`), `page_urls` on publish responses, links `/{slug}{route}`.
- **Custom-domain S1/S2** (this branch, 2026-09-17/18): the `workspace_hostname` registry in
  `clue_spine`, the separately deployable `clue_page_origin` service behind the `pages-edge`
  Cloudflare Worker, the `/w/` routes deleted, custom domains built end to end.

This lane never saw F5 because `research-streaming-v3` (renamed `website/custom-domain`) never
received it; F5 arrived in `codex/ai-ark-committee-discovery-spec-v1` together with the settings
slice.

## The ruling (founder, 2026-09-28, verbatim)

"ours for storage and serving, because it was built to be deployed and it carries custom domains,
while adopting two things from F5: their multi-page routes and their rule that the label locks after
the first publish. Then their handle table and in-API server get removed, and existing handles become
our labels."

This supersedes spec assumption A1 (label change with a warning): after the first publish the label
is locked. Spec A6 stands (no `canonical`, no `og:url`; `og:image` is the one absolute URL).

## What landed (`8ab2780d4..de80c454d`)

| Commit | What |
| --- | --- |
| `6cc3648a5` | the plan |
| `22a581ea4` | merge of `codex/ai-ark-committee-discovery-spec-v1` (head `44fbc3e8b`, 946 commits) — **43 conflicts**, resolved by the plan's table: theirs verbatim (T) for the settings slice's shell, their design API files (`main.py`, `public_pages.py`, `toolbelt/publishes.py`, `web_export.py`), the share menu, `confirmation-card.tsx`, `frontend-mutation.ts`, `clue_auth/policy.py`, their four design-API test files and `uv.lock`; a hand union (U) for `.env.example`, `DEV_STACK.md`, `Makefile`, `_memory/README.md`, `settings.md`, `secrets.py`, `clue_spine/__init__.py`, `auth_wiring.py`, `frontend_read/app.py`, `projections_app.py`, `provisioning.py`, root `pyproject.toml`, `scripts/dev_stack.sh`, the design API's `pyproject.toml`; ours (O) for `pages-settings.tsx` (add/add). The F5 `LUMEN_PUBLIC_PAGES_*` block left `.env.example`. |
| `1aae24fcd` | Alembic join `c16e1ae684b3` (parents `aaff3d831895` + `97427f8eb3d6`, made with `alembic merge`); revision `770bf20802e1`: `workspace_hostname.locked_at`, every F5 handle becomes the workspace's system label `<handle>.<suffix>` (lock carried over), `design_workspace_handle` dropped; `alembic/env.py` passes `CLUE_PAGES_SYSTEM_SUFFIX` to SQL as `clue.pages_system_suffix`; `clue_spine.lock_system_hostname`; `replace_system_label` refuses `label_locked`; `clue_design/workspace_handles.py` deleted |
| `b84dc742f` | design API re-homed on the registry: `PublicSiteAddress` kept as a plain dataclass, built by `public_pages.site_address` / `custom_site_address`; `build_publish_package(site_address=…)` required; the four `/w/` routes, the `Host(...)` mount, `GET/PUT /workspace/handle`, `public_site_address` and the env constants deleted; publish responses carry `url`, `custom_url`, `public_origin`, `custom_origin`, `page_urls`, `custom_page_urls`; the toolbelt publish locks the label right after the revision is registered |
| `9bad6e892` | fix round: the PDF export embeds custom-component runtimes (`embed_runtime_assets=True`); stale `public_base` dropped from `tests/api/test_toolbelt_wiring.py` |
| `e705840e7` | page origin serves `/{slug}/{route}` (`PageReads.active_page`, `ServedPage`), with the pre-F5 fallback (a publish with no page rows serves `/` from its own html) |
| `de80c454d` | frontend: `customPageUrls` on the engine types; the share menu prefers `customUrl` / `customPageUrls`; Settings → Pages bound through the slice's `readSettingsSection` (`settings-read.ts` `"pages"` case); `static-sections.ts` loses its dummy Pages; Pages fields on the slice's `useAutosaveField`; `settings-autosave-input.tsx` deleted; custom-domain card CSS restored |

## The seven plan decisions (reversible)

1. The lock lives on `workspace_hostname.locked_at` (nullable timestamp), set by the design API at
   first publish through the spine DAL `lock_system_hostname`; the spine never reads design tables.
2. The merge commit takes THEIR design API and share menu wholesale; our S1/S2 changes are re-applied
   by Tasks 2 and 4. Our `lumen_api/public_pages.py` is recreated under the same name.
3. `PublicSiteAddress` survives; `public_site_address()` does not — the address comes from the registry.
4. Custom hostnames get `custom_page_urls` beside `page_urls` (one map per origin), so the share menu
   builds no URLs itself.
5. Settings → Pages plugs into the slice's `readSettingsSection` seam (a `"pages"` case), not a
   parallel loader.
6. Autosave convergence: Pages uses the slice's `useAutosaveField`; our `SettingsAutosaveInput` is
   deleted (Task 4 took this branch).
7. `.context/attachments` stays tracked as their branch made it; our untracked copies were restored
   only where a path was absent.

## Rulings (every ledger ruling line)

- **Task 0:** our `data/settings.fixture.ts` + `data/settings.repository.ts` deleted — the slice's
  `static-sections.ts` + `settings-read.ts` own that role. `pages-settings.tsx` add/add → ours kept.
- **Task 1 (accepted):** the downgrade's `CREATE TABLE` is copied verbatim from `5456c0770de8`; the
  downgrade writes back EVERY on-suffix system label, not only locked ones; `replace_system_label`
  takes `FOR UPDATE` against a concurrent first publish; `tests/design/test_workspace_handle_dal_db.py`
  deleted with its module.
- **Task 2 (concerns ruled):** A — design-API suites run with `LUMEN_INGESTION_DESCRIBE=0
  LUMEN_INGESTION_VISION=0` (the lane `.env` has both on plus a real key, so asset uploads make paid
  calls; `.env` is never edited). B — the helper binary predated F5's `add_page`, so
  `subsystems/clue-design/target/release/lumen-api-helper` was rebuilt from the merged Rust source
  (2026-09-28 23:28). C — the route-table and write-path-governance reds are inherited (their branch
  added `/assets/upload-capabilities` and `design_enrich_assets` without updating those tests).
  D — `tests/api/test_toolbelt_wiring.py` still passed `public_base` → fixed in the fix round.
  E — the PDF lost custom-component runtimes (root-relative `/p-assets` under `set_content`) →
  `build_publish_package(embed_runtime_assets=)`, and `web_pdf` passes `True` (cost if wrong: larger
  PDF HTML).
- **Task 3 (accepted):** `/{slug}/` reuses the root handler; a non-dict manifest means
  `noindex = false`. Route shape: F5 stores the page's own `route` (starting with `/`); the origin
  normalises `"/" + route.strip("/")` exactly as F5's deleted serving body did.
- **Task 4:** the attestation marker (`custom_url` count 0) was wrong — the merge kept our engine
  fields — so the base was attested by HEAD + clean tree and only `customPageUrls` was added to the
  engine. Accepted beyond the brief: the custom-domain card CSS classes restored in
  `settings.module.css` (the merge dropped them); a workspace `key` on `<PagesSettings>`;
  `settings-autosave-input.tsx` deleted in favour of `useAutosaveField`.

## Tests run (from the task reports)

- **Task 0:** no test run; baselines measured on the merged tree — `uv run mypy` 1 error
  (`platform/api/clue_api/design_leg_wiring.py:1627`, theirs), `lint-imports` 29 kept, `alembic heads`
  2 until Task 1. `uv sync --all-packages` and `npm install` done.
- **Task 1:** lane DB `tests/clue_spine tests/db/test_hostname_lock_migration_db.py
  tests/db/test_db_migrations.py` → 88 passed, 1 skipped (the round-trip test runs only on a `smoke`
  DB); scratch DB `clue_pages_smoke` → 89 passed; `make db-smoke` on the scratch DB → exit 0 (285
  upgrades, 285 downgrades), then dropped. ruff clean, mypy 1 (baseline), lint-imports 29, one head.
- **Task 2** (design API, from `subsystems/clue-design/apps/api`, ingestion flags off, rebuilt helper):
  `test_web_export` 32, `test_web_pdf_export` 7, `test_custom_component_publish` 4,
  `test_public_pages` 8, `test_abm_batch_publish` 35, `test_web_batches` 8,
  `test_web_fragment_export` 16, `test_workspace_seam` 8, `test_design_toolbelt` 12,
  `test_api -k build_info` 1; root `tests/api/test_toolbelt_wiring.py` 8. Inherited reds:
  `test_workspace_seam_route_table` 1 passed / 1 failed, `test_write_path_governance` 6 passed / 2 failed.
- **Task 3:** `tests/page_origin` → 25 passed (18 + 7 new). ruff clean, mypy 1, lint-imports 29.
- **Task 4:** `npm test` → 3261 tests: 3255 pass, 5 fail, 1 skipped; `npm run lint` 0 errors,
  2 warnings (pre-existing `canvasOperations.ts`); `npx tsc --noEmit` 74 → 71 errors (three
  pre-existing errors fixed, none new). `npm run build` NOT run (port 3020 busy).

**Inherited reds (not this work's):** the route table (1) and write-path governance (2) — their
asset-enrichment lane; five Zafran account-research frontend fixture tests
(`features/accounts/data/zafran/*`), failing identically at `e705840e7`.

## Deferred minors (from the ledger)

- A handle whose hostname another workspace already holds is skipped by the backfill; that workspace
  has no system row until `make pages-backfill-hostnames` runs.
- Backfilled hostnames take the `CLUE_PAGES_SYSTEM_SUFFIX` in force when the migration runs.
- `DbPageReads.active_page` has no DB test (the origin suite is fakes-only).
- `npm run build` not run; no live UI check with a real custom hostname.

## Owed (honest list)

- `cd apps/frontend && npm run build` — port 3020 was busy through the whole reconciliation.
- The dev-stack walk: publish a two-page site, open both routes at
  `http://<label>.pages.localhost:8040/<slug>[/route]`, the share menu showing the host and per-page
  links, `/settings/pages` working, and a label change refused after publish with the lock message.
- The hosted S0 acceptance walk (`docs/specs/pages-hosting-runbook.md` section 7) — nothing hosted
  exists yet.
- The live Cloudflare S2 walk (spec §10, a founder-owned hostname).
- The co-founder's frames for the connection card and the Clue-address row (re-lift).
- The plan's Task 6 exit gate runs after this record.
- Done today, not owed: the helper binary `subsystems/clue-design/target/release/lumen-api-helper`
  was rebuilt from the merged Rust source (`cargo build --release -p lumen-api-helper`).

## Addendum 2026-09-29 — second pull of the LOCAL `codex/ai-ark-committee-discovery-spec-v1` (`658b7becb`)
- 40 local commits (research-model evaluation, Head-of-ABM v66/v67 + research at 350 rounds, ad-harvest
  auto-onboarding, self-serve provisioning ON by default, focused account reconciliation migrations)
  merged in; one conflict (`settings.py`: theirs `self_serve_provisioning_enabled = True` + our pages
  block). None of the reconciled hosting files changed on their side except `lumen_api/main.py`
  (ad-library onboarding; auto-merged).
- Alembic: their `d9f29ca9ca66` / `5e1c0a9d7b24` + our `770bf20802e1` → join `6eb27d45f570` (one head);
  lane DB upgraded to it.
- Gates: imports ok; ruff clean on the touched files; lint-imports 29 kept; mypy 6 errors — the 5 new
  ones are in files that arrived with this merge (`openrouter_chat.py`, `arv2/quality_*`), inherited;
  custom-domain Python suites green (59); npm test 3259 pass / 5 inherited Zafran fails; lint 0 errors.
- **Owed:** the lane `.env` is far from key parity with `.env.example` (~110 keys arrived with the two
  merges; left untouched because several — the `DEV_STACK_*` block, `CLUE_SANDBOX_ENABLED=true` — would
  change this lane's runtime; the founder decides the values). Everything owed before stays owed.

## Addendum 2026-09-29 — lane `.env` rebuilt from dubai's
- `.env` copied from `../dubai/.env` (the founder's current keys) and re-pointed for this lane:
  `clue_addis-ababa@55040`, this checkout's `.artifacts` / helper binary / font manifest,
  `CLUE_AGENT_WORKSPACE_ROOT=/private/tmp/clue-agent-workspaces-addis-ababa`, Sentry/Langfuse env
  `lane-addis-ababa`, and NEW lane ports **3021 / 8011 / 8021 / 8031** (frontend / design API /
  platform API / twin) in `CLUE_APP_ORIGIN`, the Clerk authorized parties, `LUMEN_API_CORS_ORIGINS`,
  `CLUE_DESIGN_API_BASE_URL`, `LUMEN_API_ORIGIN`, the `DEV_STACK_*` block and
  `apps/frontend/.env.local`; the `CLUE_PAGES_*` / `CLUE_CLOUDFLARE_*` block re-appended; the retired
  `LUMEN_PUBLIC_PAGES_*` lines dropped. Key parity with `.env.example` is now exact both ways.
- Consequences to know: `CLUE_SANDBOX_ENABLED=true` and self-serve provisioning ON now apply here
  (the dev stack refuses `up` without the sandbox image — `make sandbox-image`); `scripts/dev_stack.sh`
  reads `DEV_STACK_*` from the SHELL env at script start, so start the stack with
  `set -a; source .env; set +a; ./scripts/dev_stack.sh up` (or a lane wrapper) for the ports to apply;
  the page origin stays on 8040.

## Addendum 2026-09-29 — stack first UP on this lane; two defects found and fixed
- Ports: 8021 turned out to be held by macOS `launchd` (unbindable; invisible to unprivileged
  `lsof`) — the platform API moved to **8022** (`DEV_STACK_PLATFORM_PORT`, `apps/frontend/.env.local`).
  Final lane map: 3021 frontend / 8011 design API / 8022 platform / 8031 twin / 8040 page origin.
- **Fleet workers crashed at boot** with `tool 'design_publish_web@1' schema digest changed`: removing
  `public_base` from the tool input (S1/reconciliation) changed the input schema digest pinned by the
  design profiles. Re-pinned in place on v1/v2/v3 with a dated comment (`63f582967`, `aa11a5f1d`),
  the F5 output-re-pin precedent; catalog + registry-wiring tests green (51). No other pin drifted.
- Stack verified: all five ports listening, `/healthz` on 8040 = 200, 4 lane workers alive without
  the crash, frontend restarted on the updated env. `up` / `restart-api` hang in their trailing
  `sleep; status` — run under `timeout`; the detached processes survive.

## Addendum 2026-09-29 (later) — third pull of the LOCAL ai-ark branch (`4297b0648`)
- 7 commits (AI Ark contact-email lookup on by default, Head of ABM v68 dropping three retired-lane
  tools, legacy research-lane sweep, design-leg retry fix, refused-tool recipe guard). Clean merge:
  no conflicts, no migrations, nothing in the hosting/settings files; `.env` parity intact.
- Gates: imports ok; catalog + registry-wiring + custom-domain suites green. One setup error
  (`test_toolbelt_wiring::test_quarantined_profile_contact_never_reaches_legacy_contact_scope`) seen
  once — CORRECTED: it was transient/environmental, not inherited; it passes alone and in the batch on
  re-run. Both runs that errored happened while this lane's fleet workers were live against the lane
  DB (the known "DB suites need the stack down" class), so the "errors on their tip too" check proved
  nothing. mypy 7 (the new one, `arv2/read_tools.py:533`, arrived
  with this merge); lint-imports 29 kept; one alembic head; npm test 3249 pass / 5 inherited fails;
  lint 0 errors. Platform API twins + workers restarted on the merged code (design API untouched by
  this merge); all five lane ports up, 4 workers clean.
