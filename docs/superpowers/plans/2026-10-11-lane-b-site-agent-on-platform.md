# Lane B: the Puck site agent on the platform — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Head of ABM website leg on a site-engine workspace runs the Puck page agent (the spike
in `trials/puck-spike/agent/`) as a real design turn on the fleet: it reads the workspace's brand,
clones, research, cited claims, seller files and project context from the database, builds and
edits the site with its tools, writes agent sections when a clone is not enough, and saves one
undo step per request through the governed site write.

**Architecture:** A new runtime package `lumen_agent/site/` carries the spike's harness, tools,
workspace logic, prompt and skills (prompt and skills verbatim). The design API builds everything
the turn reads from the database into one by-value `SiteTurnInputs` plus four capabilities (asset
bytes, section compile, document versions, renderer); the runtime never opens the database. A new
executor `execute_site_turn_job` runs it under the turn's spend scope and model-call collector,
persists through Lane A's `design_write_site` under CAS, syncs the session folder, and emits
`site_document_saved`, which the platform forwards to the chat as `design.checkpoint`.

**Tech Stack:** Python 3.12, FastAPI, Alembic/Postgres, deepagents 0.6.12 + LangChain
`create_agent`, LangGraph `PostgresSaver`; Node 24 + tsx + esbuild + TypeScript + Tailwind 4
(`@tailwindcss/node` 4.3.3, `@tailwindcss/oxide` 4.3.3) inside `apps/frontend/packages/site-kit`.

**Spec:** `docs/superpowers/plans/2026-10-09-website-agent-on-puck-integration.md` — sections
"Global constraints", "Review focus", "D2", and "Wave 2: rulings and cross-lane contracts
(2026-10-11)". This plan implements Contracts 4 (storage, compile, schema read, section links), 5
and 7, and consumes Contracts 1–3 from Lane A. The spike being ported is `trials/puck-spike/agent/`
(`run_agent.py`, `trials_puck_agent/{harness,tools,workspace}.py`, `system_prompt.md`, `skills/`,
`skills-e5/`, `SKILLS-CHANGELOG.md`, `tests/`), with its findings in `trials/puck-spike/ISSUES.md`,
`AGENT-FINDINGS.md` and `RUNTIME-SECTIONS.md`.

---

## Open questions for the founder

Each has a recommendation; the plan is written to the recommendation and names the task that
changes if the answer differs.

1. **ANSWERED 2026-10-12: (b) — the clause is dropped; the three wordings below (T6e, T16) are
   approved.** **`render_page`'s "console errors" fact.** The production render is static and script-free, so
   no console error can occur. Broken images (checked against the workspace's blobs) and
   horizontal overflow (the screenshot is wider than the viewport) are still measured.
   - (a) keep the spike's sentence word for word, with `console errors: 0` always;
   - (b) drop the clause from the tool output, its description and `page-review` (three
     wording changes).
   **Recommendation: (a)** — true, and it changes no skill. Task 9 is written to (a).
2. **ANSWERED 2026-10-12: (a) — list everything the registry lists; the agent judges (the
   building-with-puck skill already says the header and footer live in `shell.json` and to leave out
   navigation clones that do not help the reader). No `CATALOG_SKIP_ROLES` filter.** **Nav, footer and campaign-shell clones in the agent's catalog.** The ruling took the
   registry's rules (approved, lineage-resolved, degraded listed with its note). The registry
   also lists the seller's own `nav`/`footer` sections and the two composed ABM campaign shells;
   the spike left `nav`/`footer` out because a site's header and footer come from `shell.json`.
   - (a) list everything the registry lists;
   - (b) leave out `section_role in {"nav", "footer"}` and `composed` shells.
   **Recommendation: (b).** Task 8 is written to (b) with one constant
   (`CATALOG_SKIP_ROLES`); (a) is deleting that filter and its test.
3. **ANSWERED 2026-10-12: (a) — save it as one undo step and say it stopped (Task 7 as written).**
   **A request that stops at its limit (100 model calls or 30 minutes) with a valid page.**
   - (a) save it (one undo step), and the chat summary says it stopped;
   - (b) save nothing unless the agent finished on its own.
   **Recommendation: (a)** — the work is valid and undoable. Task 7 is written to (a).
4. **ANSWERED 2026-10-12: T3 approved (the line names all six skills, the last two "for new
   sections").** **The prompt's "Your four skills" line.** E5 is on by default (ruling), so six skills ride
   below the prompt. Text T3 in Task 0 proposes the change; if the founder keeps the line as is,
   skip T3 (the spike ran E5 with the old line).

## Contract conflicts

These are places where the code makes a contract as written impossible or ambiguous. Each one
needs the Wave 2 section amended (or Lane A's agreement) before the named task lands.

1. **Contract 1, `theme.brand_kit` key.** The example shows
   `{"brand_kit_id": "…", "version": 2}`, but the design DAL stamps `{"id": …, "version": …}`
   (`subsystems/design/clue_design/brand.py:299` returns `{"id", "version"}`, stamped at
   `subsystems/design/clue_design/documents.py:85`), and `resolve_web_turn_brand_kit` reads
   `ref["id"]` (`subsystems/clue-design/apps/api/lumen_api/main.py:11801-11806`). Lane B reads `id`
   (the code's truth). Amend the example.
2. **Contract 1 vs the site-kit image rule — resolved in Lane A's plan; recorded so it stays
   resolved.** `validateSite` accepts an image only when it is a `file` of `brand.assets`
   (`apps/frontend/packages/site-kit/src/validate.ts:89-91,138,158,180`), but generated images,
   library images found by `search_assets` and account logos are workspace blobs, not kit assets.
   Lane A's plan (its Tasks 2 and 11) adds `validateSite`'s fourth argument
   `images: {siteImages, accountLogos}` and has `design_write_site` pass every custody-held
   `/asset-store/<sha256>` the site names as `siteImages`. Lane B relies on exactly that: inside the
   turn it adds these images to the brand it validates with (so the catalog lists them), and its
   persist passes Lane A's write validation because the workspace holds each blob. If Lane A drops
   the `images` argument, Task 12's persist test fails.
3. **Contract 5 says `design@v5`.** The authority audit
   (`tests/agents/test_tool_authority_audit.py:310-314`) requires every registered `design_*`
   tool to be granted to `AgentRole.DESIGN`, and a grant requires the design profile to pin it or
   the registry refuses to compose (`platform/api/clue_api/agent_registry_wiring.py:325,335`).
   Lane A's plan (its Task 12 Step 9) grants `design_write_site`, `design_undo_site` and
   `design_redo_site` to the design role but mints no design profile, so as written
   `build_agent_profile_registry` would refuse to compose ("profile 'design' differs from reviewed
   authority", `agent_registry_wiring.py:1027-1040`) from the moment Lane A's Task 12 lands until a
   profile pins them. Either Lane A mints `design@v5` with its three tools (then Lane B's Task 14
   takes `v6`), or Lane B's Task 14 pins all five in one profile. Task 14 is written to "the next
   version" and pins whatever the design role is granted but not yet pinned.
4. **Contract 4, "bytes live in DesignBlobStore" and "never served through /asset-store".**
   Every live design blob is readable through `GET /asset-store/{digest}`
   (`subsystems/design/clue_design/storage.py:210-252`, workspace-unscoped by ruling R-D4-7).
   Lane B makes the public read skip rows whose `source_key` is `design_site_section` (Task 2).
   This is a change to a shared read, not a contract change; listed so Lane A and C know.
5. **Contract 4, the section-links response.** Contract 6's `init` needs each section's
   `propsSchema`. Lane B's response adds `props_schema` to each item:
   `[{name, digest, token, expires_at, props_schema}]` (additive).
6. **Contract 2, `409 document.agent_run_active` — resolved in Lane A's plan.** The refusal lives
   in the site ROUTES (Lane A Task 13), not in the governed `design_write_site`, so the site turn's
   own persist (through the tool, `actor="agent"`) is admitted while its run is active. Lane A's tool
   refuses an invalid site with `SiteDocumentInvalid(errors)` rather than `PreconditionFailed`; Task
   12's persist handles both.
7. **Contract 3, `capture_site_screenshot` returns bytes only.** Overflow is derived from the
   PNG's width; console errors are not measurable (open question 1). It also runs with JavaScript
   off and the network blocked, so `/asset-store/` images must be inlined as `data:` URIs first
   (`web_pdf.inline_asset_store_refs`); Task 9's render port does that.
8. **The section compiler needs a Node toolchain in the backend image.** Contract 4's compile
   (tsc with the react and zod types, esbuild, tsx) runs at request time, but Lane A's image change
   (its Task 15) ships only site-kit's built bundles and states the runtime has no
   `apps/frontend/node_modules`. Task 15 Step 11 adds
   `COPY --from=sitekit /src/apps/frontend/node_modules /app/apps/frontend/node_modules` to Lane A's
   `sitekit` stage output (a large layer). Lane A owns the Dockerfile and must agree first; the
   alternative is a pruned install of only the compile toolchain in that stage.
### Controller review rulings (2026-10-11) — already applied to the tasks below

- **Conflict 1 → Contract 1 amended:** the stored kit ref is `{"id", "version"}`.
- **Conflict 3 → ruling R6:** Lane A registers its four site tools (`design_write_site`,
  `design_undo_site`, `design_redo_site`, `design_publish_site`) **ungranted**, on the ad-assets
  lane's footing (no model names them; the routes and this lane's executor call them). Lane A mints
  no design profile, so Task 14 is deterministic: it mints `design@v5` pinning
  `read_cited_claims@1` and `design_record_site_section@1` (Contract 5's `design@v5`).
- **Conflict 5 + Lane C's K1/K2 → rulings R1/R2:** the section-links response is
  `{"links": [{name, digest, token, expires_at, props_schema}]}` (the same wrapper as Lane A's
  `{"versions": [...]}`), and Task 16 serves the module as `GET /site-sections/{digest}.mjs?t=` and
  its stored CSS as `GET /site-sections/{digest}.css?t=`, both answering
  `X-Clue-Workspace-Id: <workspace>` so the editor server can check the module belongs to the
  workspace in its `Host`.
- **Conflict 8 → ruling R7:** Task 15 Step 11's whole `node_modules` copy is accepted as written
  (the image already ships the editor's `node_modules` the same way, `docker/backend/Dockerfile:53`,
  and it keeps the lockfile's versions). Residual for the deploy owner: prune it to site-kit's own
  dependencies before the first production deploy.
- **Conflict 9 → ruling R8:** Lane A Task 9 owns the labels, summaries and account card; Task 13
  needs Lane A Task 9 landed and does only the refusal removal, the envelope and the forwarder.
- **Ruling R9 (a gap no conflict named):** nothing carried the marketer's selected parts (Lane C's
  annotation chips, `site:<route>#<id>[.<field>]`) to the site agent. New **Task 13a** adds them to
  the site request and appends a short block to the agent's message; its wording is **T15** in
  Task 0.

9. **Two lanes plan the same `design_leg_wiring.py` label and summary edits.** Contract 7 gives
   "`design_leg_wiring` treats `doc_kind == "site"` like web in its labels and summaries" to Lane B,
   but Lane A's plan (its Task 9) also changes `:338`, `:408`, `:869`, `:972` and the account card at
   `:1516-1520` (adding `design_kind_label` and `_card_account_id`). Not a contract impossibility, but
   one of the two must not land. Task 13 checks for Lane A's helpers first and, when they are there,
   keeps only the envelope, the refusal removal and the forwarder.

## Cross-lane interfaces this plan consumes

Verify each name against the merged code before the task that uses it; if a name differs, change
only the call site and record the real name in the task's commit message. "A0", "A2" and "A5" in this
plan are the master plan's Lane A step ids (`2026-10-09-website-agent-on-puck-integration.md:1143-1145`:
A0 site-kit catch-up, A2 writes/undo/redo/versions, A5 the hardened renderer); Lane A's own plan
(`docs/superpowers/plans/2026-10-11-lane-a-site-backend-and-publishing.md`) numbers them as its
Tasks 1–3 (A0), 4–7 (A9 brand fidelity), 8–10 (A1 kind branches), 11–13 (A2), 14 (A3 targets) and
15–17 (A5). The table names Lane A's task numbers.

| From | Name and shape Lane B uses | Used in |
|---|---|---|
| Lane A Task 3 | `apps/frontend/packages/site-kit/dist/validate-site.mjs` (stdin `{"files": {"pages": {route: page or text}, "shell": shell or text or null}, "brand": BrandData, "agentSectionSchemas": {"<Name>": <JSON Schema>}, "images": {"siteImages": [...], "accountLogos": [...]}}` → `{"valid", "errors"}`) and `dist/build-catalog.mjs` (stdin `{"brand", "seller"}` → `{relativePath: markdown}`), built by `npm run build -w @clue/site-kit` | Tasks 3, 6, 8 |
| Lane A A9 rewrite (`2026-10-12-lane-a-a9-brand-fidelity-rewrite.md`) Tasks 4 and 6b | site-kit `src/theme.ts`: `tailwindThemeCss(brand)`; `src/check-section.ts`: `lintOptionsFor(brand)` | Task 15 |
| Lane A Task 6 | site-kit `src/check-section.ts`: `lint(source, { extraSurfaces })` (banned names, links, brand colour classes) and `typeCheck(file)` | Task 15 |
| Lane A Task 11 | `lumen_api/site_doc_validate.py`: `run_site_validator(site, brand, *, section_schemas, site_images, node_bin="node") -> list[str]`, `SiteValidatorUnavailable`, `VALIDATOR_TIMEOUT_S`; `lumen_api/site_render.py` (first half): `site_kit_dist()`, `SectionModule(name, digest, module_js, css, props_schema)`, `SiteRenderError(code, message)`, `SECTION_MODULE_MISSING`, `pinned_modules`; `lumen_api/site_doc_inputs.py`: `load_section_modules`, `brand_loader_not_composed`, `sections_not_stored`; test helper `site_kit_support.ensure_site_kit_dist()` | Tasks 3, 12, 15 |
| Lane A Task 12 | governed `design_write_site@1`, input `{"document_id", "site", "intent", "checkpoint_label", "actor_kind", "source", "expected_base_version"}`; raises `WebDocumentVersionConflict(expected, current)` on CAS loss and `SiteDocumentInvalid(errors)` on a contract refusal; `HybridRepository.update_site_document(...)`; the seams `app.state.site_brand_loader` / `app.state.site_section_loader` and `design_tool_host(..., site_brand_loader=, site_section_loader=)` that Lane B fills | Tasks 12, 15 |
| Lane A Task 17 | `lumen_api/site_render.py`: `render_site(site, brand, sections, *, base_path, routes=None, timeout_s=20.0, ...) -> SiteRender(pages, css, warnings)`, `RenderedPage(route, html)`, `read_section_schema(module_js, *, timeout_s=10.0) -> dict` (refuses a non-zod schema, missing `id`/`surface`, `className`/`style`, no `render`), `capture_site_screenshot(page, css, *, width, full_page=True, ...) -> bytes` (JavaScript off, network blocked); `web_export.compile_tailwind_css(html, input_css, node_bin, timeout_seconds=120)` | Tasks 9, 14, 15, 18 |
| Lane A Task 15 | the backend image's `sitekit` stage (site-kit `dist/`); Lane B adds the compile toolchain to it (contract conflict 8) | Task 15 |

**Cross-lane coordination (no contract change):**
- `design_leg_wiring.py`: Contract 7 gives Lane B the site labels and summaries
  (`_exit_judge_artifact_lines` `:338`, the G2 account card `:1519`, `_assistant_summary` `:869`,
  `batch_summary` `:972`) and `_envelope` (`:2635-2826`); Lane A's plan also edits the first four
  (contract conflict 9), so Task 13 skips them when Lane A's helpers exist. Lane A owns `:408`,
  `:737` and the gallery/wire mappings.
- `lumen_api/site_kit_cli.py` (Task 3) is the one Node runner for site-kit's CLIs; Task 3 moves
  Lane A's `run_site_validator` onto it (same function, same exception) so no second runner exists.
- `lumen_api/site_brand.py` (Task 8) is the one `BrandData` builder (the Wave 2 brand split gives
  "turning the stored kit into BrandData" to Lane B). Lane B fills Lane A's
  `app.state.site_brand_loader` with it (Task 12) and `app.state.site_section_loader` with the
  section store (Task 15), on the app and on the worker's design tool host; Lane C's editor read
  calls the same builder.
- The editor's server route for agent modules (Lane C) calls the design API's
  `GET /site-sections/{digest}.mjs?t=<token>` and `.css?t=<token>` without a workspace header, and
  checks the `x-clue-workspace-id` they answer against its `Host` (Task 16, ruling R2).

## Global Constraints

- **Git:** never push; commit locally at the end of each task; no AI attribution or
  `Co-Authored-By` lines; work on the feature branch (`puck/integration-wave1` or a branch off
  it), never `main`.
- **Env parity:** every new setting goes into `.env.example` with its default at introduction;
  a design-API setting also goes into `subsystems/clue-design/.env.example`; the local `.env`
  gets the same key (secrets: a local value in `.env`, a placeholder in the examples).
- **Alembic:** `alembic revision -m "<slug>"` (generated id, never hand-picked); every
  `upgrade()` has a `downgrade()`; exactly one head; `make db-smoke` only against
  `clue_trenton_wave1`.
- **WebDoc stays untouched:** with the workspace flag off every existing path is byte-identical;
  no old-lane gate may block the new lane.
- **Agent-written code never runs on app.cluehq.ai or in a platform process (D2):** Node only
  transforms or scans it (esbuild, tsc, the lint, Tailwind); the props schema is read only inside
  Lane A's hardened render page.
- **Never serve agent modules through `/asset-store`.**
- **Agent-facing text** (system prompt, skills, tool descriptions, tool result sentences the model
  reads, code-written workspace files, chat summaries) is shown to the founder before it is
  written. Task 0 collects every such change; the prompt and skills are carried verbatim first.
- **Founder rulings applied here (2026-10-11):** fresh session per request (`thread_id` = the run
  id); code writes `site.md` before and `history.md` after each request; `plan.md`,
  `history.md` and `fetched/` persist with the document's session storage
  (`lumen_agent/session_sync.py`); turn limits 100 rounds, 50 calls per round, 30 minutes, with
  no total-call or zero-yield caps (the spike's 40-call stop is dropped); no `read_claims` or
  `read_project_accounts` live tools (`research/claims.md` is the standard); the model is the
  orchestrator model (`LUMEN_AGENT_MODEL`), no new model env; agent sections are per workspace;
  E5 tools and skills are on by default; a new design tool updates all four registries.
- **Tests:** never assert which model a setting names; never run `*_live.py` or broad suites with
  real keys; database suites only on `clue_trenton_wave1` with the design stack down; agent
  runtime and design API suites in separate pytest sessions (their `conftest` modules collide);
  never the whole design suite.
- **Live model runs spend money and need the founder's go** (Task 18 Step 9 is the only one).

**Test command forms** (copy exactly; `<file>` is the test file named in the step):

```bash
# Agent runtime (from subsystems/clue-design)
cd subsystems/clue-design && set -a; source ../../.env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_trenton_wave1"; LUMEN_INGESTION_DESCRIBE=0 LUMEN_INGESTION_VISION=0 PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/agent_runtime/tests/<file> -q -o addopts="" --ignore-glob='*_live.py'

# Design API (from subsystems/clue-design, a separate session)
cd subsystems/clue-design && set -a; source ../../.env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_trenton_wave1"; LUMEN_INGESTION_DESCRIBE=0 LUMEN_INGESTION_VISION=0 PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/api/tests/<file> -q -o addopts="" --ignore-glob='*_live.py'

# Platform (from the repo root)
set -a; source .env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_trenton_wave1"; .venv/bin/python -m pytest tests/<file> -q -o addopts="" --ignore-glob='*_live.py'

# site-kit (from apps/frontend)
cd apps/frontend && npx tsx --test packages/site-kit/test/<file>
```

In the steps below these are written as **RT**, **API**, **PLATFORM** and **SITE-KIT** followed
by the file; expand them with the forms above. Before any RT or API test that validates a site or
builds a catalog, build site-kit once: `cd apps/frontend && npm run build -w @clue/site-kit`
(Lane A Task 3). A test marked `needs_node` skips without the build; a skip is not a pass.

## Review Focus

The five input classes no task's main tests exercise that are most likely to bite a person, most
likely first. Each line names the test that pins it and the task that owns it.

1. **The site changes while the agent's request runs.** Lane A's routes refuse a manual save
   during a running site turn, but a write can still land between the turn's read and its persist
   (a save that raced the run's start, an undo, a restore). The request must end `conflicted`, keep
   the other version, write nothing, emit no `site_document_saved`, and record "Saved: no, the site
   changed while this request ran" in `history.md`.
   Test: `test_a_site_turn_that_loses_the_version_race_saves_nothing` (Task 12).
2. **The research cites a claim held back by a real rule** (a contact's reputation risk or
   biography). The statement resting on it must leave the research files, while a statement
   resting on a finding held back only because nobody verified it stays.
   Tests: `test_cited_claims_say_why_each_id_was_held_or_missing` (Task 1, database) and
   `test_held_dispositions_drop_only_statements_resting_on_a_real_rule` (Task 5).
3. **A section link used by another workspace, after it expired, or for a digest it was not minted
   for.** Each must be refused, and the module must never be readable through `/asset-store`.
   Tests: `test_a_token_for_another_digest_or_after_expiry_is_refused` and
   `test_a_site_section_module_is_not_served_by_the_public_asset_store` (Tasks 16, 2).
4. **The user presses Stop mid-request.** Nothing is persisted, no event is emitted, the summary
   says it was stopped, and `history.md` says so.
   Test: `test_a_cancelled_site_turn_saves_nothing_and_says_so` (Task 12).
5. **The next request lands on a worker that never ran this document.** `plan.md`,
   `history.md` and `fetched/` come back from the session manifest; research, catalog, brand and
   the page files are rebuilt from the database, never restored from a stale snapshot.
   Test: `test_the_session_snapshot_keeps_memory_and_leaves_out_regenerated_inputs` (Task 12).

---

## File Structure

**Platform (`platform/`, `tests/`):**
- Modify `platform/api/clue_api/arv2/read_tools.py` — `claim_gate_reason`, `read_cited_claims`,
  `ReadCitedClaimsTool`, the service seam, `build_arv2_read_tools`.
- Modify `platform/api/clue_api/design_platform_reads.py` — `DesignPlatformReads.read_cited_claims`.
- Modify `platform/api/clue_api/agent_registry_wiring.py` — C6 entries, `AgentRole.DESIGN` pin.
- Create `platform/agents/catalog/profiles/design/v<N>/profile.yaml` — the next design profile.
- Modify `platform/api/clue_api/design_leg_wiring.py` — site turn envelope, account card, labels,
  summaries; remove the Wave 1 refusal.
- Modify `platform/api/clue_api/design_event_forwarder.py` — forward `site_document_saved`.
- Modify `libs/clue-config/clue_config/secrets.py`, `.env.example`,
  `subsystems/clue-design/.env.example` — `CLUE_SITE_SECTION_LINK_SECRET` (a secret).
- Modify `docker/backend/Dockerfile`, `docker/backend/smoke.sh` — the section compile toolchain
  (contract conflict 8).
- Tests: `tests/api/test_arv2_read_tools.py`, `tests/arv2/test_read_tools_db.py`,
  `tests/api/test_design_platform_reads_db.py`, `tests/api/test_toolbelt_wiring.py`,
  `tests/agents/test_tool_authority_audit.py`, `tests/api/test_agent_registry_wiring.py`,
  `tests/agents/test_catalog.py`, `tests/api/test_site_leg_birth_db.py`,
  `tests/api/test_site_turn_summaries.py` (new), `tests/api/test_site_checkpoint_forwarding.py` (new),
  `tests/design/test_site_sections_dal_db.py` (new), `tests/test_site_section_link_settings.py` (new),
  `tests/deploy/test_backend_image.py`.

**Design substrate (`subsystems/design/`, `alembic/`):**
- Create `alembic/versions/<generated>_design_site_section.py`.
- Create `subsystems/design/clue_design/site_sections.py` — the DAL.
- Modify `subsystems/design/clue_design/storage.py` — `SOURCE_KEY_SITE_SECTION`; the public read
  skips it.

**Design API (`subsystems/clue-design/apps/api/lumen_api/`):**
- Create `site_kit_cli.py` — the Node runner for site-kit CLIs (and move Lane A's
  `site_doc_validate.run_site_validator` onto it).
- Create `site_brand.py` — the one `BrandData` builder.
- Create `site_turn_ports.py` — asset, section, version and renderer capabilities; the persist
  outcome.
- Create `site_workspace_view.py` — builds `SiteTurnInputs` from the database.
- Create `site_section_links.py` — HMAC tokens and the two routes.
- Create `toolbelt/site_sections.py` — `design_record_site_section`.
- Modify `toolbelt/factory.py`, `design_store.py`, `models.py`, `main.py`, `fleet_handler.py`.
- Tests: `apps/api/tests/test_site_kit_cli.py`, `test_site_brand.py`, `test_site_workspace_view.py`,
  `test_site_turn_ports.py`, `test_site_turn_executor.py`, `test_site_section_tool.py`,
  `test_site_section_links.py`, `test_site_fleet_dispatch.py` (all new); `test_write_path_governance.py`,
  `test_workspace_seam_route_table.py`, `test_design_job_trace.py` (modified).

**Agent runtime (`subsystems/clue-design/apps/agent_runtime/lumen_agent/`):**
- Create `site/__init__.py`, `site/inputs.py`, `site/workspace.py`, `site/tools.py`,
  `site/harness.py`; copy `site/system_prompt.md`, `site/skills/`, `site/skills-e5/`,
  `site/SKILLS-CHANGELOG.md` verbatim from the spike.
- Modify `session_sync.py` — `snapshot_session(..., exclude=...)`.
- Modify `tools/asset_catalog.py` and `tools/substrate.py` — one shared hybrid search.
- Tests (new): `apps/agent_runtime/tests/site_fixtures.py`, `test_site_package.py`,
  `test_site_workspace.py`, `test_site_tools.py`, `test_site_harness.py`,
  `test_site_render_tool.py`, `test_site_images.py`, `test_site_search_assets.py`,
  `test_site_sections_tool.py`, `test_site_clone_rebuild.py`, `test_site_cost_and_tracing.py`.

**site-kit (`apps/frontend/packages/site-kit/`):**
- Create `bin/compile-section.ts`, `test/compile-section.test.ts`.
- Modify `src/clone.ts` (optional `degraded_note`), `src/catalog.ts` (render it),
  `test/catalog.test.ts`.

**Order:** Task 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13 → 13a → 14 → 15 → 16
→ 17 → 18 → 19. Task 13 needs Lane A's Task 9 (labels and summaries, ruling R8); Task 13a's live
use needs Lane A's Task 14 (the composer accepts site targets). Tasks 0, 1, 2, 4 and 5 depend on no other lane. From Task 3 on, Lane A's Tasks 3 and 11
must have landed (site-kit's bundles, the validator call, the first half of `site_render.py`);
Tasks 9, 14, 15 and 18 also need Lane A's Task 17 (the hardened renderer, `read_section_schema`,
`compile_tailwind_css`); Task 12 needs Lane A's Task 12 (`design_write_site` and the two loader
seams); Task 15 needs Lane A's Tasks 4 and 6 (theme and lint). Task 2 lands early because Lane A's
write validation reads agent sections' stored schemas through its DAL.

---
### Task 0: Founder review of every agent-facing text change in Lane B

No code. The prompt and skills are carried verbatim first (Task 4); these are the only wording
changes Lane B proposes, each needed because production differs from the spike. Each implementing
task repeats its text and has a "confirm approved" step.

**Status (2026-10-12): every row is APPROVED.** T3, T6e, T16a, T16b and T-A9-5 were approved
explicitly; the founder approved the rest as shown in the review sheet
(`docs/superpowers/plans/2026-10-11-wave2-founder-review.md`, Part 2) by ruling "I have cleared enough
doubts" when asking for the plan to be completed. Steps 1 and 2 are done; Step 3 still records it.

**Files:** none (the founder's answers are recorded in `_memory/` in Step 3).

**Interfaces:** Produces the approved texts T1–T15 used by Tasks 4, 6, 7, 8, 9, 10, 11, 12, 13a, 15.

- [x] **Step 1: Show the founder this table, exactly as written, and ask for approval or edits (DONE 2026-10-12).**

| # | Where | Today (spike, verbatim) | Proposed |
|---|---|---|---|
| T1 | `system_prompt.md`, "Your workspace", new line after the `fetched/` line | (none) | ``- `project-context/`: the project's own instructions and decisions, as they stood when this site was asked for.`` |
| T2a | `system_prompt.md`, "Your tools" | ``- `validate_page`: checks `page.json` and `shell.json`. It saves a version when the page is valid.`` | ``- `validate_page`: checks `page.json` and `shell.json`.`` |
| T2b | same | ``- `restore_version`: brings back a saved version.`` | ``- `restore_version`: brings back an earlier saved version of the site (`site.md` lists them).`` |
| T2c | same, new line after the `view_asset` line | (none) | ``- `search_assets`: finds the seller's other images (uploads, and images made for earlier pages) by what they show.`` |
| T3 | `system_prompt.md`, "How to work" step 1 | ``1. Your four skills are below this prompt: `account-page-copy`, `building-with-puck`,`` / `` `images-and-logos` and `page-review`. Follow them.`` | ``1. Your skills are below this prompt: `account-page-copy`, `building-with-puck`,`` / `` `images-and-logos` and `page-review`, and for new sections `writing-a-section` and`` / `` `rebuilding-a-section`. Follow them.`` (open question 4) **Approved 2026-10-12.** |
| T4 | `skills/building-with-puck/SKILL.md:112` | ``If a change made the page worse, `restore_version` brings back the last good version.`` | ``If a change made the page worse, fix it, or bring back an earlier saved version with `restore_version` (`site.md` lists them).`` |
| T5 | `skills/images-and-logos/SKILL.md`, §1, new last bullet | (none) | ``- The seller's other images (uploads, and images made for earlier pages) are not in `brand/brand.md`. Find them with `search_assets`, and look at one with `view_asset` before you use it.`` |
| T6a | tool description `validate_page` | "Check page.json and shell.json against the components, the catalog, the brand and the evidence. Returns VALID (and saves a version) or INVALID with each error and its fix." | "Check page.json and shell.json against the components, the catalog, the brand and the evidence. Returns VALID or INVALID with each error and its fix." |
| T6b | tool description `restore_version` | "Bring back a version saved by validate_page into page.json, shell.json and pages/." | "Bring back the site as it was at an earlier saved version (site.md lists them) into page.json, shell.json and pages/." |
| T6c | tool description `view_asset` | "Look at up to four images (files from brand/brand.md, or images you generated), each with its description, before you choose one for a section." | "Look at up to four images (files from brand/brand.md, images you generated, or images search_assets found), each with its description, before you choose one for a section." |
| T6d | tool description `search_assets` (new) | (none) | "Search the seller's images by what they show and how they look. Write what you need in plain words, for example \"calm classroom, morning light\" or \"product dashboard screenshot\". Returns the best matches first (up to limit, 1 to 20), each with its file, type, title and a one-line description. Look at one with view_asset before you use it. kind narrows to image or logo." |
| T6e | tool description `render_page` | "Publish the site and return a desktop (1440 wide) and a mobile (375 wide) full-page screenshot of one page, with facts about broken images, overflow and console errors. route is …" | **Approved 2026-10-12:** "Render the site and return a desktop (1440 wide) and a mobile (375 wide) full-page screenshot of one page, with facts about broken images and overflow. route is \"/\" for page.json or \"/<name>\" for pages/<name>.json. Refuses while the site is invalid." |
| T7 | `validate_page` result when valid | "VALID. Saved as version {n} (restore_version can bring it back)." | "VALID." |
| T8a | `render_page` result, appended to the 1440 facts line when the renderer warns | (none) | " Render notes: {first three warnings joined by '; '}." |
| T8b | `render_page` result when the renderer fails | (none) | "NOT RENDERED: the page could not be drawn ({code}). Validate it and try again; if this repeats, say so in your report." |
| T9 | `site.md` (code-written), new last section, the 10 newest versions | (none) | "## Saved versions" / "Each request and each save in the editor is one version; `restore_version` brings one back." / `- version 4: "Make the hero warmer" (by the agent, 2026-10-11 14:02 UTC)` — the author is "the agent", "a person", or "an undo or redo" |
| T10 | `history.md` (code-written), new line after "- The reply:" | (none) | "- Saved: as version {n}" / "- Saved: nothing to save" / "- Saved: no, the site changed while this request ran" / "- Saved: no, the page was still invalid" / "- Saved: no, it was stopped" / "- Saved: no, the save was refused" / "- Saved: no, the request did not finish" |
| T11 | `catalog/index.md` line and `catalog/clones/<id>.md` (site-kit `catalog.ts`) | (none) | index line ends with " · degraded"; the clone card gets, after the "Source page:" line, a blank line and "Degraded: {the registry's degraded note}" |
| T12a | final message when the round limit stops a request | the spike's "Stopped: 40 model calls in one turn (safety stop)." | "Stopped: this request reached its limit of 100 model calls." |
| T12b | final message when the time limit stops a request | (none) | "Stopped: this request reached its limit of 30 minutes." |
| T12c | tool result for the 51st+ call of one response | (none) | "Not run: this was call {n} in one response, and only the first 50 run. Make it again in your next step." |
| T12d | chat summary when the user stops a request | (none) | "Stopped at your request. Nothing was saved." |
| T12e | chat summary when the page is still invalid after two reminders | (none) | "The page was still invalid, so nothing was saved: {first error}" |
| T12f | chat summary when the runtime crashed | (none) | "The website turn stopped because of an error, and nothing was saved." |
| T12g | chat summary when the governed write refused the site | (none) | "The website could not be saved: {reason}" |
| T12h | `generate_image` result when the image was made but could not be stored | (none) | "The image was made but could not be saved ({error}). Try once more, or choose a section without an image." |
| T13 | `write_section` error item when the props schema cannot be read in the render page | (none) | "the section could not be loaded to read its props ({code}: {the render page's reason}); check that it exports `schema` (a zod object with `id` and `surface`) and `render`" |
| T14 | FYI, no wording | — | The platform's compaction adds deepagents' `compact_conversation` tool to the agent's tools (as on the scene agent). Its description is deepagents' own. |
| T16a | `render_page` result facts line (open question 1, answer (b)) | "1440 wide: page height …px, broken images: N, horizontal overflow: no, console errors: N (…). Shown at …" | **Approved 2026-10-12:** "1440 wide: page height 3120px, broken images: 0, horizontal overflow: no. Shown at half size in 4 parts, top to bottom." (the console clause removed) |
| T16b | `skills/page-review/SKILL.md`, first paragraph | "`render_page` gives you two pictures: desktop (1440 wide) and mobile (375 wide), with facts about broken images, overflow and console errors. Look at them as the reader would, then go through this list." | **Approved 2026-10-12:** "`render_page` gives you two pictures: desktop (1440 wide) and mobile (375 wide), with facts about broken images and overflow. Look at them as the reader would, then go through this list." |
| T-A9-5 | `skills-e5/writing-a-section/SKILL.md` (the A9 rewrite's text, carried here by Task 4) | the spike's kit list and `surface: z.enum([...six])` example | **Approved 2026-10-12** — exactly the wording in `docs/superpowers/plans/2026-10-12-lane-a-a9-brand-fidelity-rewrite.md`, section T-A9-5 (the kit list with `look`, `kit.Link`, `kit.Card`, motion classes; `surface: z.string()`; the spacing bullet). Task 4 copies the spike's skill verbatim, then applies T-A9-5 as one edit with a dated SKILLS-CHANGELOG entry. |
| T15 | the agent's message for a request where the person pointed at parts of the site (Task 13a), appended after their words | (none) | ``The person also pointed at parts of the site:`` / one line per part, in their order: ``- Page /analysis, the section with id "analysis-hero", its "title" field. Their note: "1. Make it warmer."`` (the header or footer reads ``- The header.`` / ``- The footer, its "ctaLabel" field.``; no note reads `` (No note.)``) / ``Work through these in the order listed. Change only these parts, unless their message asks for more. If a part is no longer on the site, say so in your report and use your judgement. In your report, say what you did for each part, or why you did not.`` |

Code-written files whose only change is a path (`brand/brand.md`'s account-logo section now lists
`/asset-store/<sha256>` instead of `/accounts/<site>/…`; `generate_image` returns
`/asset-store/<sha256>` instead of `/generated/<site>/…`) are not wording changes.

- [x] **Step 2: Wait for the founder's answer (DONE 2026-10-12: all approved).** Do not start Task 4 Step 6, Task 6 Step 3 or any
  step marked "approved text" until the founder has approved or edited each row. A row the founder
  edits is implemented with the founder's words, not the table's.

- [ ] **Step 3: Record the answer.** Append to `_memory/2026-10-11-lane-b-site-agent.md` (create
  it with a one-line title if missing) a section "Founder text review" listing each T-number (T1–T15) as
  approved, edited (with the new words) or declined. Commit:

```bash
git add _memory/2026-10-11-lane-b-site-agent.md
git commit -m "memory: Lane B agent-facing text review (T1-T15)"
```

---

### Task 1: `read_cited_claims@1`, the governed read of the claims a research page cites (B0)

Contract 5: input `{entity_id, claim_ids: [≤ 200]}`, output `{claims: [AccountClaimView],
dispositions: {claim_id: "served" | "held:<reason>" | "not_found"}}`, built from
`inspectable_claims_by_ids` then the display gate. Registered here, **ungranted**; Task 14 grants
it to `AgentRole.DESIGN` with the profile bump.

Disposition rules (the spike's `run_agent.cited_claims`, made per id):
- not in this workspace, superseded, invalid or erased support (`inspectable_claims_by_ids` drops
  it), or not a UUID → `not_found`;
- held by the gate → `held:sensitive`, `held:unverified` or `held:outreach_unsafe`, except a held
  claim whose field is `contact.research_finding`, `account.research_finding` or
  `account.value_narrative` and whose reason is not `sensitive` → `held:unverified_finding` (the
  spike did not treat those holds as "a real rule");
- servable but about another entity than `entity_id` (a contact the account's research cites) →
  `held:other_entity`;
- otherwise `served`, and the claim is in `claims`.

**Files:**
- Modify: `platform/api/clue_api/arv2/read_tools.py` (gate `:1011-1057`, service seam
  `:1714-1873`, tools after `ReadClaimsTool` `:2532-2603`, `build_arv2_read_tools` `:2606-2629`,
  `__all__` `:79-135`)
- Modify: `platform/api/clue_api/design_platform_reads.py` (after `read_claims`, `:224-247`)
- Modify: `platform/api/clue_api/agent_registry_wiring.py` (C6 map, beside `"read_claims"` `:336`)
- Test: `tests/api/test_arv2_read_tools.py`, `tests/arv2/test_read_tools_db.py`,
  `tests/api/test_design_platform_reads_db.py`, `tests/api/test_toolbelt_wiring.py`,
  `tests/agents/test_tool_authority_audit.py`, `tests/api/test_agent_registry_wiring.py`

**Interfaces:**
- Consumes: `clue_research.claimstore.quality.inspectable_claims_by_ids(conn, *, workspace_id,
  claim_ids: Sequence[UUID]) -> dict[ClaimId, Claim]`; existing `_entity_in_workspace`,
  `_claim_view`, `gate_claims`, `UNVERIFIED_ONLY_UNSAFE_FIELDS`.
- Produces:
  - `MAX_CITED_CLAIMS = 200`, `UNVERIFIED_FINDING_FIELDS: frozenset[str]`
  - `claim_gate_reason(claim: Claim, *, settings: Settings) -> str | None`
  - `CitedClaimsPage(entity_id: str, claims: tuple[AccountClaimView, ...], dispositions: dict[str, str])`
  - `async read_cited_claims(conn, *, workspace_id: str, entity_id: str, claim_ids: Sequence[str], settings: Settings) -> CitedClaimsPage`
  - `ReadCitedClaimsInput(entity_id: str, claim_ids: list[str])`, `ReadCitedClaimsOutput(entity_id, claims, dispositions)`, `ReadCitedClaimsTool` (`read_cited_claims@1`)
  - `Arv2ReadService.read_cited_claims(*, workspace_id, entity_id, claim_ids) -> CitedClaimsPage`
  - `DesignPlatformReads.read_cited_claims(*, entity_id: str, claim_ids: list[str]) -> dict[str, Any]`
    returning `{"entity_id": str, "claims": [AccountClaimView as dict], "dispositions": {id: str}}`

- [ ] **Step 1: Write the failing skin tests** in `tests/api/test_arv2_read_tools.py`.

Add to the import block: `CitedClaimsPage`, `MAX_CITED_CLAIMS`, `ReadCitedClaimsInput`,
`ReadCitedClaimsOutput`, `ReadCitedClaimsTool`. Add two fields and one method to `_FakeService`
(after `claims_reads`):

```python
    cited: CitedClaimsPage | None = None
    #: ``(workspace, entity, claim ids)`` — the ambient workspace and the exact ids asked for.
    cited_reads: list[tuple[str, str, tuple[str, ...]]] = field(default_factory=list)

    async def read_cited_claims(
        self, *, workspace_id: str, entity_id: str, claim_ids: Sequence[str]
    ) -> CitedClaimsPage:
        self.cited_reads.append((workspace_id, entity_id, tuple(claim_ids)))
        if self.refusal is not None:
            raise self.refusal
        assert self.cited is not None
        return self.cited
```

(add `from collections.abc import Sequence` to the imports). Then append these tests:

```python
def _cited_page() -> CitedClaimsPage:
    return CitedClaimsPage(
        entity_id=ACCOUNT_ID,
        claims=(
            AccountClaimView(
                claim_id=CLAIM_ID,
                field_key="account.research_finding",
                value={"finding": "Healthcare up $4.2 million"},
                source_url="https://alpha.example/budget.pdf",
                evidence="Healthcare increase of $4.2 million",
                evidence_truncated=False,
                tier=2,
                verification_status="unverified",
                outreach_safe=False,
                collected_at="2026-09-12T12:00:00+00:00",
            ),
        ),
        dispositions={
            CLAIM_ID: "served",
            "66666666-6666-5666-8666-666666666666": "held:outreach_unsafe",
            "77777777-7777-5777-8777-777777777777": "not_found",
        },
    )


def test_the_cited_claims_read_asks_about_the_ambient_workspace_and_serves_dispositions() -> None:
    async def scenario() -> None:
        service = _FakeService(cited=_cited_page())
        tool = ReadCitedClaimsTool(service)
        ids = [CLAIM_ID, "66666666-6666-5666-8666-666666666666", "77777777-7777-5777-8777-777777777777"]

        result = await tool.invoke(
            ReadCitedClaimsInput(entity_id=ACCOUNT_ID, claim_ids=ids), _context()
        )

        assert service.cited_reads == [(WORKSPACE, ACCOUNT_ID, tuple(ids))]
        assert result.references["entity_id"] == ACCOUNT_ID
        assert [claim["claim_id"] for claim in result.references["claims"]] == [CLAIM_ID]
        assert result.references["dispositions"] == {
            CLAIM_ID: "served",
            "66666666-6666-5666-8666-666666666666": "held:outreach_unsafe",
            "77777777-7777-5777-8777-777777777777": "not_found",
        }
        canonical = validate_tool_output_references(ReadCitedClaimsOutput, result.references)
        assert canonical["dispositions"][CLAIM_ID] == "served"

    run_async(scenario())


def test_the_cited_claims_read_is_bounded_and_refuses_by_name() -> None:
    with pytest.raises(ValueError):
        ReadCitedClaimsInput(entity_id=ACCOUNT_ID, claim_ids=[])
    with pytest.raises(ValueError):
        ReadCitedClaimsInput(
            entity_id=ACCOUNT_ID, claim_ids=[CLAIM_ID] * (MAX_CITED_CLAIMS + 1)
        )

    async def scenario() -> None:
        tool = ReadCitedClaimsTool(
            _FakeService(refusal=Arv2ReadRefused("entity_not_found", "no such entity"))
        )
        with pytest.raises(PreconditionFailed) as refused:
            await tool.invoke(
                ReadCitedClaimsInput(entity_id=ACCOUNT_ID, claim_ids=[CLAIM_ID]), _context()
            )
        assert [f.reason_code for f in refused.value.failures] == ["entity_not_found"]
        uncomposed = ReadCitedClaimsTool(None)
        failures = await uncomposed.preconditions(
            ReadCitedClaimsInput(entity_id=ACCOUNT_ID, claim_ids=[CLAIM_ID]), _context()
        )
        assert [f.reason_code for f in failures] == ["arv2_reads_not_composed"]

    run_async(scenario())


def test_the_cited_claims_read_declares_its_classification() -> None:
    tool = ReadCitedClaimsTool(_FakeService())
    assert (tool.name, tool.version) == ("read_cited_claims", "1")
    assert tool.effect_class is ToolEffectClass.READ
    assert tool.replay.policy is ReplayPolicy.EFFECT_FREE
    assert tool.pin_requirements == ("project",)
    assert tool.descriptor.recipe_safe
```

In `test_the_builder_yields_the_four_reads_and_an_uncomposed_one_refuses_by_name`, add
`"read_cited_claims"` as the fifth name in the expected list, add
`"read_cited_claims": ReadCitedClaimsInput(entity_id=ACCOUNT_ID, claim_ids=[CLAIM_ID]),` to
`inputs`, and pass `cited=_cited_page()` to the composed `_FakeService`. Rename the test to
`test_the_builder_yields_the_five_reads_and_an_uncomposed_one_refuses_by_name`.

- [ ] **Step 2: Run them and watch them fail.**

Run: PLATFORM `tests/api/test_arv2_read_tools.py`
Expected: FAIL at import — `ImportError: cannot import name 'CitedClaimsPage'`.

- [ ] **Step 3: Write the gate reason, the read, the tool and the seam** in
`platform/api/clue_api/arv2/read_tools.py`.

Add to the imports: `from clue_research.claimstore.quality import inspectable_claims_by_ids`.
Add to `__all__`: `"MAX_CITED_CLAIMS"`, `"UNVERIFIED_FINDING_FIELDS"`, `"CitedClaimsPage"`,
`"ReadCitedClaimsInput"`, `"ReadCitedClaimsOutput"`, `"ReadCitedClaimsTool"`,
`"claim_gate_reason"`, `"read_cited_claims"`.

Replace the body of `gate_claims` (keep its signature and docstring) and add `claim_gate_reason`
just above it:

```python
def claim_gate_reason(claim: Claim, *, settings: Settings) -> str | None:
    """Why the display gate holds ``claim`` back — ``sensitive``, ``unverified`` or
    ``outreach_unsafe`` — or ``None`` when a read may serve it.

    The one decision :func:`gate_claims` counts and :func:`read_cited_claims` reports per id, so
    the two can never disagree about a claim.
    """

    if _is_sensitive(claim):
        return "sensitive"
    if settings.verification_enabled and _is_unverified_synthesis(claim):
        return "unverified"
    if not claim.outreach_safe and not _unsafe_only_until_verified(claim, settings):
        return "outreach_unsafe"
    return None
```

```python
    excluded = {"sensitive": 0, "unverified": 0, "outreach_unsafe": 0}
    servable: list[Claim] = []
    for claim in claims:
        reason = claim_gate_reason(claim, settings=settings)
        if reason is None:
            servable.append(claim)
        else:
            excluded[reason] += 1
    return servable, excluded
```

Add after `read_claims` (before the "service seam" banner):

```python
#: The most claim ids one cited-claims read takes (Contract 5, plan 2026-10-09 Wave 2).
MAX_CITED_CLAIMS = 200

#: Findings whose outreach-unsafe flag says only "nobody has verified this yet". A research
#: statement resting on one stays in the design agent's research files; a statement resting on a
#: claim held back by a real rule (a reputation risk, a biography, a sensitive fact) does not.
#: The Puck spike's rule (`trials/puck-spike/agent/run_agent.py:93`), now reported per id.
UNVERIFIED_FINDING_FIELDS = frozenset({"contact.research_finding", *UNVERIFIED_ONLY_UNSAFE_FIELDS})


@dataclass(frozen=True, slots=True)
class CitedClaimsPage:
    """The claims an entity's research cites: the served ones, and what happened to every id."""

    entity_id: str
    claims: tuple[AccountClaimView, ...]
    #: One entry per requested id, in request order: ``served``, ``held:<reason>`` or
    #: ``not_found``. ``<reason>`` is ``sensitive``, ``unverified``, ``outreach_unsafe``,
    #: ``unverified_finding`` or ``other_entity``.
    dispositions: dict[str, str]


async def read_cited_claims(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    entity_id: str,
    claim_ids: Sequence[str],
    settings: Settings,
) -> CitedClaimsPage:
    """The claims an account's research pages cite, by id, gated as the account pages gate them.

    Read through :func:`inspectable_claims_by_ids` — the source drawer's read — so a qualified
    finding the research cites is readable here although ``read_claims`` (which serves only
    supported claims) would drop it. Every id gets a disposition, because the design agent's
    research files must leave out a statement that rests on a claim held back by a real rule, and
    keep one that rests on a finding held back only because nobody verified it yet.

    Unpaged by contract (at most :data:`MAX_CITED_CLAIMS` ids): it is called through the design
    read seam, which records no 16 KiB receipt, and each served claim's evidence is clipped.
    """

    entity_uuid, _entity_type = await _entity_in_workspace(
        conn, workspace_id=workspace_id, entity_id=entity_id
    )
    requested = list(dict.fromkeys(str(claim_id) for claim_id in claim_ids))
    parsed: dict[str, UUID] = {}
    for raw in requested:
        try:
            parsed[raw] = UUID(raw)
        except ValueError:
            continue
    found = (
        await inspectable_claims_by_ids(
            conn, workspace_id=workspace_id, claim_ids=list(parsed.values())
        )
        if parsed
        else {}
    )
    by_id = {str(claim.id): claim for claim in found.values()}
    served: list[AccountClaimView] = []
    dispositions: dict[str, str] = {}
    for raw in requested:
        claim = by_id.get(str(parsed[raw])) if raw in parsed else None
        if claim is None:
            dispositions[raw] = "not_found"
            continue
        reason = claim_gate_reason(claim, settings=settings)
        if reason is not None:
            if reason != "sensitive" and str(claim.field_key) in UNVERIFIED_FINDING_FIELDS:
                reason = "unverified_finding"
            dispositions[raw] = f"held:{reason}"
            continue
        if claim.entity_id != entity_uuid:
            dispositions[raw] = "held:other_entity"
            continue
        dispositions[raw] = "served"
        served.append(_claim_view(claim))
    return CitedClaimsPage(
        entity_id=str(entity_uuid), claims=tuple(served), dispositions=dispositions
    )
```

Add to the `Arv2ReadService` protocol (after `read_claims`):

```python
    async def read_cited_claims(
        self, *, workspace_id: str, entity_id: str, claim_ids: Sequence[str]
    ) -> CitedClaimsPage: ...
```

Add to `DbArv2ReadService` (after `read_claims`):

```python
    async def read_cited_claims(
        self, *, workspace_id: str, entity_id: str, claim_ids: Sequence[str]
    ) -> CitedClaimsPage:
        async with self._conn_factory() as conn:
            return await read_cited_claims(
                conn,
                workspace_id=workspace_id,
                entity_id=entity_id,
                claim_ids=claim_ids,
                settings=self._settings,
            )
```

Add after `ReadClaimsTool`:

```python
class ReadCitedClaimsInput(ToolInput):
    #: The account (or contact) whose research cites these claims.
    entity_id: str
    #: The ids the research's statements cite, at most :data:`MAX_CITED_CLAIMS`.
    claim_ids: list[str] = Field(min_length=1, max_length=MAX_CITED_CLAIMS)


class ReadCitedClaimsOutput(ToolOutput):
    entity_id: str
    #: The served claims about ``entity_id`` (``AccountClaimView`` is the shape for any entity).
    claims: tuple[AccountClaimView, ...]
    #: Every requested id: ``served``, ``held:<reason>`` or ``not_found``.
    dispositions: dict[str, str]


class ReadCitedClaimsTool(Tool):
    """Read the claims a research page cites, with what happened to each id."""

    name = "read_cited_claims"
    version = "1"
    model_description = (
        "Read the claims a research page cites, by id, gated as the account pages gate them: "
        "each id comes back served, held back (with the reason) or not found. Effect-free."
    )
    input_model: ClassVar[type[ToolInput]] = ReadCitedClaimsInput
    output_model: ClassVar[type[ToolOutput]] = ReadCitedClaimsOutput
    effect_class = ToolEffectClass.READ
    replay = ReplaySafety(
        policy=ReplayPolicy.EFFECT_FREE,
        durable_identity="the cited claims' live rows",
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(safe_display_fields=("entity_id",))
    #: ``project`` is the spine row the execution is bound to — a replay identity, as for the
    #: other ARV2 reads.
    pin_requirements = ("project",)

    def __init__(self, service: Arv2ReadService | None) -> None:
        self._service = service

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        del inputs, ctx
        return _not_composed() if self._service is None else ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ReadCitedClaimsInput)
        assert self._service is not None
        try:
            page = await self._service.read_cited_claims(
                workspace_id=ctx.workspace_id,
                entity_id=inputs.entity_id,
                claim_ids=list(inputs.claim_ids),
            )
        except Arv2ReadRefused as refused:
            raise PreconditionFailed([PreconditionFailure(refused.code, str(refused))]) from refused
        tag_entities([page.entity_id])
        output = ReadCitedClaimsOutput(
            entity_id=page.entity_id, claims=page.claims, dispositions=page.dispositions
        )
        return ToolResult(tool=self.name, version=self.version, references=output.model_dump())
```

In `build_arv2_read_tools`, append `ReadCitedClaimsTool(service),` after `ReadClaimsTool(service),`
and add one sentence to its docstring: "``read_cited_claims`` (2026-10-11) is the fifth: the
design agent's cited-claims read (Contract 5); it holds the name-only alias, being the only
version of itself."

- [ ] **Step 4: Give the tool its C6 decision (ungranted for now).** In
`platform/api/clue_api/agent_registry_wiring.py`, after the `"read_claims"` entry add:

```python
    # The design agent's cited-claims read (Contract 5, plan 2026-10-09 Wave 2): the claims an
    # account's research pages cite, by id, each with its disposition. Registered UNGRANTED;
    # the reviewed design profile bump (Lane B Task 14) grants it to the DESIGN role.
    "read_cited_claims": (),
```

- [ ] **Step 5: Add the seam method** to `DesignPlatformReads` in
`platform/api/clue_api/design_platform_reads.py`, after `read_claims`:

```python
    def read_cited_claims(self, *, entity_id: str, claim_ids: list[str]) -> dict[str, Any]:
        """The claims an account's research cites, by id, each with its disposition.

        ``read_cited_claims@1`` (Contract 5): ``served`` claims come back in ``claims``; every id
        gets ``served``, ``held:<reason>`` or ``not_found`` in ``dispositions``. At most 200 ids
        per call; the caller chunks.
        """

        return self._invoke(
            "read_cited_claims", {"entity_id": entity_id, "claim_ids": list(claim_ids)}
        )
```

- [ ] **Step 6: Run the skin tests and watch them pass.**

Run: PLATFORM `tests/api/test_arv2_read_tools.py`
Expected: PASS.

- [ ] **Step 7: Write the database test** in `tests/arv2/test_read_tools_db.py` (it reuses that
file's `_seed_account`, `_seed_claim`, `_seed_contact`, `_seed_contact_claim`, `PERMISSIVE`,
`VERIFYING`). Add `read_cited_claims` to the `clue_api.arv2.read_tools` import, then append:

```python
def test_cited_claims_say_why_each_id_was_held_or_missing() -> None:
    """Review focus 2: the design agent drops a research statement only when the claim under it
    is held back by a real rule, so the read must say which rule, per id."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project = await seed_project(conn, WORKSPACE, name="Read tools")
            account = await _seed_account(conn, project, "Alpha Health")
            contact = await _seed_contact(
                conn, account, name="Nalisa Clark", linkedin="https://www.linkedin.com/in/nclark"
            )
            claims: dict[str, str] = {}
            await _seed_claim(
                conn, claims, project, account, label="plain",
                field_key="account.open_requisitions", value=[{"title": "ABM Manager"}],
            )
            await _seed_claim(
                conn, claims, project, account, label="finding",
                field_key="account.research_finding",
                value={"topic": "Budget", "finding": "Healthcare up $4.2 million"},
                outreach_safe=False,
            )
            await _seed_claim(
                conn, claims, project, account, label="risk",
                field_key="account.reputation_risk",
                value={"what": "An unresolved customer dispute"}, outreach_safe=False,
            )
            await _seed_claim(
                conn, claims, project, account, label="sensitive",
                field_key="account.resonance.buying_culture",
                value="A fact about the founder's health", use_class=UseClass.SENSITIVE,
            )
            await _seed_contact_claim(
                conn, claims, project, contact, label="contact_finding",
                field_key="contact.research_finding",
                value={"topic": "Role", "finding": "Leads benefits"}, outreach_safe=False,
            )
            await _seed_contact_claim(
                conn, claims, project, contact, label="contact_plain",
                field_key="contact.current_title", value="Chief Human Capital Officer",
            )
            missing = str(uuid4())
            ids = [claims[label] for label in (
                "plain", "finding", "risk", "sensitive", "contact_finding", "contact_plain"
            )] + [missing, "not-a-uuid"]

            page = await read_cited_claims(
                conn, workspace_id=project.workspace_id, entity_id=str(account),
                claim_ids=ids, settings=PERMISSIVE,
            )

            assert page.dispositions == {
                claims["plain"]: "served",
                claims["finding"]: "served",  # verification off: findings pass the gate
                claims["risk"]: "held:outreach_unsafe",
                claims["sensitive"]: "held:sensitive",
                claims["contact_finding"]: "held:unverified_finding",
                claims["contact_plain"]: "held:other_entity",
                missing: "not_found",
                "not-a-uuid": "not_found",
            }
            assert [c.claim_id for c in page.claims] == [claims["plain"], claims["finding"]]

            verifying = await read_cited_claims(
                conn, workspace_id=project.workspace_id, entity_id=str(account),
                claim_ids=[claims["finding"], claims["risk"]], settings=VERIFYING,
            )
            # Under verification the finding is held, but only as an unverified finding.
            assert verifying.dispositions == {
                claims["finding"]: "held:unverified_finding",
                claims["risk"]: "held:outreach_unsafe",
            }

            with pytest.raises(Arv2ReadRefused) as refused:
                await read_cited_claims(
                    conn, workspace_id=project.workspace_id, entity_id=str(uuid4()),
                    claim_ids=ids, settings=PERMISSIVE,
                )
            assert refused.value.code == "entity_not_found"

    run_async(scenario())
```

`contact.current_title` is seeded exactly as `test_the_claims_query_reads_a_contact_and_says_it_read_one`
seeds it in the same file; `uuid4` is already imported there.

- [ ] **Step 8: Run the database test.**

Run: PLATFORM `tests/arv2/test_read_tools_db.py -k cited_claims`
Expected: PASS.

- [ ] **Step 9: Add the seam test** in `tests/api/test_design_platform_reads_db.py` (its
`_seeded` registry already registers `build_arv2_read_tools`, so the new tool is there):

```python
def test_the_cited_claims_read_reaches_the_design_side(tmp_path: Path, migrated_db: bool) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")
    from clue_api.design_platform_reads import build_design_platform_reads_factory

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seeded(conn, tmp_path, label="cited")
            factory = build_design_platform_reads_factory(
                invoker=seeds["invoker"], storage=seeds["storage"],
                conn_factory=seeds["conn_factory"],
            )
            envelope = _leg_envelope(
                seeds["workspace_id"], seeds["project"].project_id, seeds["opening_turn"]
            )
            reads = await asyncio.to_thread(factory, envelope)
            assert reads is not None
            missing = str(uuid4())
            answer = await asyncio.to_thread(
                reads.read_cited_claims,
                entity_id=str(seeds["account_id"]),
                claim_ids=[missing],
            )
            assert answer == {
                "entity_id": str(seeds["account_id"]),
                "claims": [],
                "dispositions": {missing: "not_found"},
            }

    run_async(scenario())
```

Run: PLATFORM `tests/api/test_design_platform_reads_db.py -k cited`
Expected: PASS.

- [ ] **Step 10: Move the inventory counts.** Run:

```bash
set -a; source .env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_trenton_wave1"; .venv/bin/python -m pytest tests/api/test_toolbelt_wiring.py tests/agents/test_tool_authority_audit.py tests/api/test_agent_registry_wiring.py -q -o addopts="" --ignore-glob='*_live.py' 2>&1 | grep -E "assert|FAILED" | head -20
```

Expected failures, each one more than the number written (at `d723a17ae`: names 144, addresses
169, C6 144, head-of-abm `by_address` 169; if Lane A's A2 landed first the written numbers are
three higher — use whatever the assertion prints):
- `tests/api/test_toolbelt_wiring.py:1472` and `:1563` `len(registry.names()) == 144` → `145`;
- `tests/api/test_toolbelt_wiring.py:1518` and `:1596` `len(registry) == 169` → `170`;
- `tests/agents/test_tool_authority_audit.py:170` `len(C6_AGENT_TOOL_AUTHORITY) == 144` → `145`;
- `tests/api/test_agent_registry_wiring.py:317` and `:439` `len(by_address) == 169` → `170`;
- the toolbelt matrix: a missing expectation for `read_cited_claims`.

Change each number to the printed value and append to the comment above it:
"`read_cited_claims@1` (2026-10-11, Lane B) is a new name at one address (+1), ungranted until the
design profile bump." In `tests/api/test_toolbelt_wiring.py` add, beside `"read_claims"` in the
expectation map (`:284`):

```python
    "read_cited_claims": ("precondition", ("arv2_reads_not_composed",)),
```

and beside `"read_claims"` in the input map (`:709`):

```python
        "read_cited_claims": {"entity_id": _UUID(), "claim_ids": [_UUID()]},
```

In `tests/agents/test_tool_authority_audit.py`, after the `read_claims` assertions (`:205-212`)
add `assert C6_AGENT_TOOL_AUTHORITY["read_cited_claims"] == ()`.

- [ ] **Step 11: Run the three files again.**

Run: the command in Step 10 without the `grep`.
Expected: PASS.

- [ ] **Step 12: Commit.**

```bash
git add platform/api/clue_api/arv2/read_tools.py platform/api/clue_api/design_platform_reads.py platform/api/clue_api/agent_registry_wiring.py tests/api/test_arv2_read_tools.py tests/arv2/test_read_tools_db.py tests/api/test_design_platform_reads_db.py tests/api/test_toolbelt_wiring.py tests/agents/test_tool_authority_audit.py tests/api/test_agent_registry_wiring.py
git commit -m "read_cited_claims@1: the claims a research page cites, by id, with a disposition per id (registered, ungranted)"
```

---
### Task 2: `design_site_section` — the table, the DAL, and a public read that never serves agent code (B6, storage half)

Contract 4: table `design_site_section` with primary key `(workspace_id, digest)`, bytes in
`DesignBlobStore`, never served through `/asset-store`. Lands early: A2's write validation reads
agent sections' stored props schemas through `get_site_sections`.

**Files:**
- Create: `alembic/versions/<generated>_design_site_section.py`
- Create: `subsystems/design/clue_design/site_sections.py`
- Modify: `subsystems/design/clue_design/storage.py:50-66` (source keys) and `:210-252`
  (`read_public_design_blob`)
- Test: `tests/design/test_site_sections_dal_db.py` (new)

**Interfaces:**
- Consumes: `clue_design._codec.{dump_json, load_json, iso}`; `register_design_bytes`,
  `read_design_blob`, `read_public_design_blob` in `clue_design.storage`.
- Produces:
  - `clue_design.storage.SOURCE_KEY_SITE_SECTION = "design_site_section"`
  - `async record_site_section(conn, *, workspace_id: str, digest: str, name: str, source_sha256: str, css_sha256: str, props_schema: dict, created_by_run_id: str | None) -> dict`
  - `async get_site_sections(conn, *, workspace_id: str, digests: Sequence[str]) -> list[dict]` (input order, missing digests left out)
  - `async list_latest_site_sections(conn, *, workspace_id: str) -> list[dict]` (one row per name, the newest)
  - row dict keys: `workspace_id, digest, name, source_sha256, module_sha256, css_sha256, props_schema, created_at (ISO string), created_by_run_id`

- [ ] **Step 1: Write the failing tests** in `tests/design/test_site_sections_dal_db.py`:

```python
"""design_site_section (Lane B, Contract 4): agent-written Puck sections, per workspace."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan
from clue_design import site_sections
from clue_design.errors import DesignNotFoundError
from clue_design.storage import (
    SOURCE_KEY_ASSET,
    SOURCE_KEY_SITE_SECTION,
    read_design_blob,
    read_public_design_blob,
    register_design_bytes,
)
from clue_storage import FsStorage
from clue_storage.protocol import content_address
from tests.design.conftest import run_async

SCHEMA = {"type": "object", "properties": {"id": {"type": "string"}, "surface": {"type": "string"}}}


async def _seed_ws(conn: AsyncConnection) -> str:
    ws = f"ws_test_sections_{uuid4().hex[:12]}"
    await conn.execute(text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"), {"w": ws})
    return ws


async def _record(conn: AsyncConnection, ws: str, digest: str, name: str = "StepsBand", run: str = "run_1") -> dict:
    return await site_sections.record_site_section(
        conn, workspace_id=ws, digest=digest, name=name, source_sha256="b" * 64,
        css_sha256="c" * 64, props_schema=SCHEMA, created_by_run_id=run,
    )


def test_a_section_is_recorded_once_and_read_back_only_in_its_workspace(require_design_db: None) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            first = await _record(conn, ws, "a" * 64)
            again = await _record(conn, ws, "a" * 64, run="run_2")
            assert again == first  # content-addressed: a repeat records nothing new
            assert first["module_sha256"] == "a" * 64 and first["props_schema"] == SCHEMA
            assert first["created_by_run_id"] == "run_1"
            rows = await site_sections.get_site_sections(conn, workspace_id=ws, digests=["f" * 64, "a" * 64])
            assert [row["digest"] for row in rows] == ["a" * 64]
            other = await _seed_ws(conn)
            assert await site_sections.get_site_sections(conn, workspace_id=other, digests=["a" * 64]) == []
            await txn.rollback()

    run_async(_check())


def test_the_newest_section_of_each_name_is_listed(require_design_db: None) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            await _record(conn, ws, "1" * 64, name="StepsBand")
            await _record(conn, ws, "2" * 64, name="QuoteBand")
            await _record(conn, ws, "0" * 64, name="StepsBand")  # written later, sorts first
            latest = await site_sections.list_latest_site_sections(conn, workspace_id=ws)
            assert {row["name"]: row["digest"] for row in latest} == {
                "QuoteBand": "2" * 64,
                "StepsBand": "0" * 64,
            }
            await txn.rollback()

    run_async(_check())


def test_rows_are_immutable_and_shaped(require_design_db: None) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            await _record(conn, ws, "a" * 64)
            with pytest.raises(DBAPIError):
                async with conn.begin_nested():
                    await conn.execute(
                        text("UPDATE design_site_section SET name = 'Other' WHERE workspace_id = :w"),
                        {"w": ws},
                    )
            with pytest.raises(DBAPIError):
                async with conn.begin_nested():
                    await _record(conn, ws, "d" * 64, name="lowercase")
            await txn.rollback()

    run_async(_check())


def test_a_site_section_module_is_not_served_by_the_public_asset_store(
    require_design_db: None, tmp_path: Path
) -> None:
    """Review focus 3 / Contract 4: agent code is reachable only through a short-lived link."""

    async def _check() -> None:
        storage = FsStorage(tmp_path / "blobs")
        module = b"export const schema = 1;\n//# clue-section StepsBand\n"
        image = b"\x89PNG\r\n\x1a\nnot really"
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            await register_design_bytes(
                conn, storage, workspace_id=ws, data=module,
                media_type="text/javascript", source_key=SOURCE_KEY_SITE_SECTION,
            )
            await register_design_bytes(
                conn, storage, workspace_id=ws, data=image,
                media_type="image/png", source_key=SOURCE_KEY_ASSET,
            )
            with pytest.raises(DesignNotFoundError):
                await read_public_design_blob(conn, storage, sha256=content_address(module))
            _, served = await read_public_design_blob(conn, storage, sha256=content_address(image))
            assert served == image
            # The workspace-scoped read (the renderer, the link verifier) still reads it.
            media_type, data = await read_design_blob(
                conn, storage, workspace_id=ws, sha256=content_address(module)
            )
            assert (media_type, data) == ("text/javascript", module)
            await txn.rollback()

    run_async(_check())
```

- [ ] **Step 2: Run them and watch them fail.**

Run: PLATFORM `tests/design/test_site_sections_dal_db.py`
Expected: FAIL at import — `ImportError: cannot import name 'site_sections' from 'clue_design'`.

- [ ] **Step 3: Generate the migration.**

```bash
set -a; source .env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_trenton_wave1"; .venv/bin/alembic revision -m "design site section"
```

Expected: `Generating …/alembic/versions/<hash>_design_site_section.py ... done`. Replace the
generated body below the `Create Date` line (keep the generated `revision` value; set
`down_revision` to the current head printed by `.venv/bin/alembic heads`, `b4bff1ecca97` at
`d723a17ae`, or whatever single head the branch has):

```python
"""design site section

Lane B, Contract 4 of docs/superpowers/plans/2026-10-09-website-agent-on-puck-integration.md:
one immutable row per compiled agent-written Puck section, keyed by the sha256 of its compiled
module, per workspace. The source, module and CSS bytes live in DesignBlobStore under
source_key 'design_site_section', which the public /asset-store read never serves.

``created_at`` defaults to ``clock_timestamp()`` rather than ``now()`` so two sections written in
one transaction still order by when each was written (the newest-per-name read depends on it).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "<keep the generated id>"
down_revision: str | None = "b4bff1ecca97"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE design_site_section (
            workspace_id      text        NOT NULL REFERENCES workspace (workspace_id),
            digest            text        NOT NULL,
            name              text        NOT NULL,
            source_sha256     text        NOT NULL,
            module_sha256     text        NOT NULL,
            css_sha256        text        NOT NULL,
            props_schema_json jsonb       NOT NULL,
            created_at        timestamptz NOT NULL DEFAULT clock_timestamp(),
            created_by_run_id text,
            CONSTRAINT design_site_section_pkey PRIMARY KEY (workspace_id, digest),
            CONSTRAINT design_site_section_digest_shape CHECK (digest ~ '^[0-9a-f]{64}$'),
            CONSTRAINT design_site_section_module_is_digest CHECK (module_sha256 = digest),
            CONSTRAINT design_site_section_source_shape CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT design_site_section_css_shape CHECK (css_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT design_site_section_name_shape CHECK (name ~ '^[A-Z][A-Za-z0-9]{2,40}$')
        )
        """
    )
    op.execute(
        "CREATE INDEX design_site_section_newest_by_name "
        "ON design_site_section (workspace_id, name, created_at DESC)"
    )
    op.execute(
        """
        CREATE FUNCTION design_site_section_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'design_site_section is immutable (content-addressed)';
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER design_site_section_no_update BEFORE UPDATE ON design_site_section "
        "FOR EACH ROW EXECUTE FUNCTION design_site_section_immutable()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER design_site_section_no_update ON design_site_section")
    op.execute("DROP FUNCTION design_site_section_immutable()")
    op.execute("DROP TABLE design_site_section")
```

- [ ] **Step 4: Write the DAL** `subsystems/design/clue_design/site_sections.py`:

```python
"""Agent-written Puck sections (Lane B, Contract 4): one immutable row per compiled module.

A section is per WORKSPACE (founder ruling 2026-10-11): a section compiled for one site may be
placed on any site of the same workspace. The row is keyed by the sha256 of the compiled module,
so a repeat compile of the same code records nothing new. Bytes live in DesignBlobStore
(``SOURCE_KEY_SITE_SECTION``) and are never served by the public asset read.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_design._codec import JsonObject, dump_json, iso, load_json

__all__ = ["get_site_sections", "list_latest_site_sections", "record_site_section"]

_COLUMNS = (
    "workspace_id, digest, name, source_sha256, module_sha256, css_sha256, "
    "props_schema_json, created_at, created_by_run_id"
)


def _row(row: Any) -> JsonObject:
    return {
        "workspace_id": row.workspace_id,
        "digest": row.digest,
        "name": row.name,
        "source_sha256": row.source_sha256,
        "module_sha256": row.module_sha256,
        "css_sha256": row.css_sha256,
        "props_schema": load_json(row.props_schema_json),
        "created_at": iso(row.created_at),
        "created_by_run_id": row.created_by_run_id,
    }


async def record_site_section(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    digest: str,
    name: str,
    source_sha256: str,
    css_sha256: str,
    props_schema: JsonObject,
    created_by_run_id: str | None,
) -> JsonObject:
    """Record one compiled section, or return the row already holding this digest."""

    await conn.execute(
        text(
            "INSERT INTO design_site_section (workspace_id, digest, name, source_sha256, "
            "module_sha256, css_sha256, props_schema_json, created_by_run_id) "
            "VALUES (:w, :d, :n, :s, :d, :c, CAST(:p AS jsonb), :r) "
            "ON CONFLICT (workspace_id, digest) DO NOTHING"
        ),
        {
            "w": workspace_id,
            "d": digest,
            "n": name,
            "s": source_sha256,
            "c": css_sha256,
            "p": dump_json(props_schema),
            "r": created_by_run_id,
        },
    )
    rows = await get_site_sections(conn, workspace_id=workspace_id, digests=[digest])
    return rows[0]


async def get_site_sections(
    conn: AsyncConnection, *, workspace_id: str, digests: Sequence[str]
) -> list[JsonObject]:
    """This workspace's rows for ``digests``, in the order asked; a missing digest is left out."""

    wanted = list(dict.fromkeys(digests))
    if not wanted:
        return []
    rows = await conn.execute(
        text(
            f"SELECT {_COLUMNS} FROM design_site_section "
            "WHERE workspace_id = :w AND digest = ANY(:d)"
        ),
        {"w": workspace_id, "d": wanted},
    )
    by_digest = {row.digest: _row(row) for row in rows}
    return [by_digest[digest] for digest in wanted if digest in by_digest]


async def list_latest_site_sections(conn: AsyncConnection, *, workspace_id: str) -> list[JsonObject]:
    """The newest section of each name in this workspace, sorted by name."""

    rows = await conn.execute(
        text(
            f"SELECT DISTINCT ON (name) {_COLUMNS} FROM design_site_section "
            "WHERE workspace_id = :w ORDER BY name, created_at DESC, digest"
        ),
        {"w": workspace_id},
    )
    return [_row(row) for row in rows]
```

- [ ] **Step 5: Keep section bytes off the public read.** In
`subsystems/design/clue_design/storage.py`, after `SOURCE_KEY_WEB_FRAGMENT` add:

```python
#: Lane B (Contract 4) — an agent-written Puck section's source, compiled module and CSS, cited by
#: ``design_site_section`` rows. NEVER public: :func:`read_public_design_blob` skips this key, so
#: ``/asset-store/{digest}`` and the page origin cannot serve agent code. The editor gets a module
#: through a short-lived signed link; the renderer reads it with the workspace-scoped read.
SOURCE_KEY_SITE_SECTION = "design_site_section"
```

In `read_public_design_blob`, change the query's `WHERE` clause and parameters to:

```python
            "SELECT storage_key, media_type FROM artifact "
            "WHERE content_sha256 = :sha AND split_part(storage_key, '/', 2) = :segment "
            "AND erased_at IS NULL AND purged_at IS NULL "
            "AND source_key IS DISTINCT FROM :site_section "
            "ORDER BY created_at, storage_key LIMIT :limit"
        ),
        {
            "sha": sha256,
            "segment": DESIGN_KEY_SEGMENT,
            "site_section": SOURCE_KEY_SITE_SECTION,
            "limit": _PUBLIC_READ_CANDIDATES,
        },
```

and add one sentence to its docstring: "It never serves an agent-written section's bytes
(``SOURCE_KEY_SITE_SECTION``, Contract 4)."

- [ ] **Step 6: Migrate the lane test database and prove reversibility.**

```bash
set -a; source .env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_trenton_wave1"
.venv/bin/alembic heads
.venv/bin/alembic upgrade head && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head
make db-smoke
```

Expected: exactly one head (the new revision); the three-step round trip succeeds; `db-smoke`
finishes with `upgrade head` succeeding (it targets `clue_trenton_wave1` through the exported URL).

- [ ] **Step 7: Run the tests.**

Run: PLATFORM `tests/design/test_site_sections_dal_db.py`, then PLATFORM
`tests/design/test_design_schema_db.py` (the schema suite must stay green).
Expected: PASS, PASS.

- [ ] **Step 8: Commit.**

```bash
git add alembic/versions/*_design_site_section.py subsystems/design/clue_design/site_sections.py subsystems/design/clue_design/storage.py tests/design/test_site_sections_dal_db.py
git commit -m "design_site_section: immutable per-workspace agent sections, and the public asset read never serves their bytes"
```

---

### Task 3: `lumen_api/site_kit_cli.py`, the one Node runner for site-kit's tools (needs Lane A Tasks 3 and 11)

site-kit's validator, catalog builder and (Task 15) section compiler are TypeScript. Lane A builds
the first two as single-file bundles (`dist/validate-site.mjs`, `dist/build-catalog.mjs`, Lane A
Task 3) and runs the validator from Python in `site_doc_validate.run_site_validator` (Lane A Task
11). This task adds ONE runner for every site-kit CLI — the bundles with `node <dist file>`, the
section compiler with `node --import tsx bin/<script>` — moves Lane A's validator call onto it, and
gives the site agent its two calls: validate (through Lane A's function) and build the catalog.
Node only transforms or scans agent code here (esbuild, tsc, the lint, Tailwind) and gets a
stripped environment.

**Files:**
- Create: `subsystems/clue-design/apps/api/lumen_api/site_kit_cli.py`
- Modify: `subsystems/clue-design/apps/api/lumen_api/site_doc_validate.py` (`run_site_validator`'s
  body only; Lane A Task 11 created it)
- Test: `subsystems/clue-design/apps/api/tests/test_site_kit_cli.py` (new)

**Interfaces:**
- Consumes: Lane A's `dist/validate-site.mjs` (stdin `{"files": {"pages", "shell"}, "brand",
  "agentSectionSchemas": {"<Name>": <JSON Schema>}, "images": {"siteImages": [...], "accountLogos": [...]}}`
  → `{"valid", "errors"}`) and `dist/build-catalog.mjs` (stdin `{"brand", "seller"}` →
  `{relativePath: markdown}`); `lumen_api.site_render.site_kit_dist()`;
  `lumen_api.site_doc_validate.run_site_validator(site, brand, *, section_schemas, site_images, node_bin="node") -> list[str]`,
  `SiteValidatorUnavailable`, `VALIDATOR_TIMEOUT_S`; the test helper
  `site_kit_support.ensure_site_kit_dist()` (Lane A).
- Produces:
  - `SITE_KIT_DIR: Path` (`<repo>/apps/frontend/packages/site-kit`)
  - `class SiteKitCliError(RuntimeError)` with `.code: str` and `.detail: str`
  - `site_kit_toolchain_missing(node_bin: str = "node") -> str | None` (node and the validator bundle)
  - `section_toolchain_missing(node_bin: str = "node") -> str | None` (node, tsx, typescript, esbuild)
  - `run_site_kit_bundle(bundle: str, payload: Mapping, *, timeout_s: float = 120.0, node_bin: str = "node", what: str | None = None) -> dict`
  - `run_site_kit_script(script: str, payload: Mapping, *, timeout_s: float = 180.0, node_bin: str = "node") -> dict`
  - `validate_site_files(files: Mapping, brand: Mapping, section_schemas: Mapping[str, dict], site_images: Sequence[str] = ()) -> dict` → `{"valid": bool, "errors": [str]}`
  - `build_site_catalog(brand: Mapping, seller: str) -> dict[str, str]`

- [ ] **Step 1: Check Lane A's names.**

```bash
grep -n "def run_site_validator\|class SiteValidatorUnavailable\|^VALIDATOR_TIMEOUT_S" subsystems/clue-design/apps/api/lumen_api/site_doc_validate.py
grep -n "def site_kit_dist" subsystems/clue-design/apps/api/lumen_api/site_render.py
grep -n "def ensure_site_kit_dist" subsystems/clue-design/apps/api/tests/site_kit_support.py
ls apps/frontend/packages/site-kit/bin/
```

Expected: all four exist; `bin/` holds `validate-site.ts`, `build-catalog.ts` and
`build-bundles.mjs`. If a name differs, use the real one below and say so in the commit message.

- [ ] **Step 2: Write the failing tests** in `subsystems/clue-design/apps/api/tests/test_site_kit_cli.py`:

```python
"""lumen_api.site_kit_cli: one runner for site-kit's CLIs, JSON in, JSON out (Lane B Task 3)."""

from __future__ import annotations

import json

import pytest

from lumen_api.site_kit_cli import (
    SITE_KIT_DIR,
    SiteKitCliError,
    _child_env,
    build_site_catalog,
    run_site_kit_bundle,
    site_kit_toolchain_missing,
    validate_site_files,
)
from site_kit_support import ensure_site_kit_dist

FIXTURES = SITE_KIT_DIR / "test" / "fixtures"


def _brand() -> dict:
    return {
        "slug": "garner",
        "kit": json.loads((FIXTURES / "kit.json").read_text()),
        "fonts": [],
        "assets": {},
        "clones": {},
    }


def test_the_validator_answers_with_its_own_errors() -> None:
    ensure_site_kit_dist()
    result = validate_site_files({"pages": {}, "shell": None}, _brand(), {})
    assert result["valid"] is False
    assert any(error.startswith("page.json: does not exist yet") for error in result["errors"])


def test_the_validator_reads_page_files_given_as_text() -> None:
    ensure_site_kit_dist()
    result = validate_site_files({"pages": {"/": "{ not json"}, "shell": "{}"}, _brand(), {})
    assert result["valid"] is False and result["errors"]


def test_the_catalog_comes_back_as_files() -> None:
    ensure_site_kit_dist()
    files = build_site_catalog(_brand(), "Garner Health")
    assert {"catalog/index.md", "catalog/sections.md", "brand/brand.md"} <= set(files)
    assert files["brand/brand.md"].startswith("# Brand: Garner Health")


def test_a_missing_node_and_a_missing_bundle_are_typed(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SiteKitCliError) as missing_node:
        run_site_kit_bundle("validate-site.mjs", {}, node_bin="definitely-not-node")
    assert missing_node.value.code == "site_kit.toolchain_missing"
    monkeypatch.setenv("LUMEN_SITE_KIT_DIST", str(tmp_path))
    with pytest.raises(SiteKitCliError) as missing_bundle:
        run_site_kit_bundle("validate-site.mjs", {}, what="the site validator")
    assert missing_bundle.value.code == "site_kit.cli_missing"
    assert missing_bundle.value.detail.startswith("the site validator is not built")
    assert site_kit_toolchain_missing() is not None


def test_node_runs_with_a_stripped_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLUE_OPENROUTER_API_KEY", "secret")
    env = _child_env()
    assert set(env) <= {"PATH", "HOME", "TMPDIR"}
    assert "secret" not in json.dumps(env)


def test_lane_as_validator_runs_through_the_shared_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    from lumen_api import site_doc_validate

    seen: list[tuple[str, str]] = []

    def fake_bundle(bundle, payload, *, timeout_s, node_bin, what):
        seen.append((bundle, what))
        return {"valid": False, "errors": ["page.json: x"]}

    monkeypatch.setattr(site_doc_validate, "run_site_kit_bundle", fake_bundle)
    errors = site_doc_validate.run_site_validator({"pages": {}, "shell": None}, {}, section_schemas={}, site_images=[])
    assert errors == ["page.json: x"] and seen == [("validate-site.mjs", "the site validator")]
```

Run: API `test_site_kit_cli.py`
Expected: FAIL at import — `ModuleNotFoundError: No module named 'lumen_api.site_kit_cli'`.

- [ ] **Step 3: Write the module** `subsystems/clue-design/apps/api/lumen_api/site_kit_cli.py`:

```python
"""site-kit's command-line tools, called from Python (Wave 2: one runner for every caller).

The Puck site's validator, catalog builder and section compiler are TypeScript in
``apps/frontend/packages/site-kit``. Two kinds of entry exist:

* **bundles** — ``dist/<name>.mjs``, single files Lane A builds (``npm run build -w @clue/site-kit``)
  so the backend image needs no ``node_modules`` for them: the validator and the catalog;
* **scripts** — ``bin/<name>.ts`` run with ``node --import tsx``, for the one tool that needs the
  whole toolchain at run time (the section compiler: tsc, esbuild, Tailwind's inputs).

Each reads ONE JSON request on stdin and prints ONE JSON answer (the last line of stdout). Node
only transforms or scans agent-written code here — never imports or runs it (D2) — and it gets a
stripped environment so no platform secret is visible to the toolchain. Every failure to answer is
a typed ``SiteKitCliError``, never a crash, so a caller can turn it into an honest sentence.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

__all__ = [
    "SITE_KIT_DIR",
    "SiteKitCliError",
    "build_site_catalog",
    "run_site_kit_bundle",
    "run_site_kit_script",
    "section_toolchain_missing",
    "site_kit_toolchain_missing",
    "validate_site_files",
]

#: lumen_api/site_kit_cli.py -> parents[5] is the repository root.
SITE_KIT_DIR = Path(__file__).resolve().parents[5] / "apps" / "frontend" / "packages" / "site-kit"
#: npm hoists the frontend workspace's dependencies to apps/frontend/node_modules.
_NODE_MODULES = SITE_KIT_DIR.parent.parent / "node_modules"
#: What the section compiler needs installed (Task 15; contract conflict 8 for the image).
_SECTION_TOOLCHAIN = ("tsx", "typescript", "esbuild", "zod", "react")


class SiteKitCliError(RuntimeError):
    """A site-kit CLI could not answer: ``code`` is machine-readable, ``detail`` is for a human."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _dist() -> Path:
    from .site_render import site_kit_dist

    return site_kit_dist()


def site_kit_toolchain_missing(node_bin: str = "node") -> str | None:
    """Why the site-kit bundles cannot run here, or ``None`` when they can."""

    if shutil.which(node_bin) is None:
        return f"node is not on PATH (looked for {node_bin!r})"
    if not (_dist() / "validate-site.mjs").is_file():
        return f"site-kit is not built (no {_dist() / 'validate-site.mjs'}; run `npm run build -w @clue/site-kit` in apps/frontend)"
    return None


def section_toolchain_missing(node_bin: str = "node") -> str | None:
    """Why the section compiler cannot run here, or ``None`` when it can."""

    if shutil.which(node_bin) is None:
        return f"node is not on PATH (looked for {node_bin!r})"
    for package in _SECTION_TOOLCHAIN:
        if not (_NODE_MODULES / package).is_dir():
            return f"the section toolchain is not installed (no {_NODE_MODULES / package}; run npm ci in apps/frontend)"
    return None


def _child_env() -> dict[str, str]:
    """The only environment Node gets: enough to find binaries, a home and a temp folder."""

    return {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR") if key in os.environ}


def _run_node(argv: list[str], payload: Mapping[str, Any], *, cwd: Path, timeout_s: float, what: str) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=_child_env(),
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise SiteKitCliError("site_kit.timeout", f"{what} did not run: it ran past {timeout_s:.0f}s") from error
    except OSError as error:
        raise SiteKitCliError("site_kit.toolchain_missing", f"{what} did not run: {error}") from error
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[-2000:]
        raise SiteKitCliError("site_kit.crashed", detail or f"{what} exited {completed.returncode}")
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    try:
        answer = json.loads(lines[-1]) if lines else None
    except json.JSONDecodeError:
        answer = None
    if not isinstance(answer, dict):
        raise SiteKitCliError("site_kit.bad_output", f"{what} printed no JSON: {completed.stdout[:200]!r}")
    return answer


def run_site_kit_bundle(
    bundle: str,
    payload: Mapping[str, Any],
    *,
    timeout_s: float = 120.0,
    node_bin: str = "node",
    what: str | None = None,
) -> dict[str, Any]:
    """Run ``dist/<bundle>`` (built by Lane A) with ``payload`` on stdin; return its JSON answer."""

    label = what or bundle
    if shutil.which(node_bin) is None:
        raise SiteKitCliError("site_kit.toolchain_missing", f"node is not on PATH (looked for {node_bin!r})")
    path = _dist() / bundle
    if not path.is_file():
        raise SiteKitCliError(
            "site_kit.cli_missing",
            f"{label} is not built ({path} is missing): run `npm run build -w @clue/site-kit` in apps/frontend",
        )
    return _run_node([node_bin, str(path)], payload, cwd=path.parent, timeout_s=timeout_s, what=label)


def run_site_kit_script(
    script: str, payload: Mapping[str, Any], *, timeout_s: float = 180.0, node_bin: str = "node"
) -> dict[str, Any]:
    """Run ``bin/<script>`` with tsx (the whole toolchain) and return its JSON answer."""

    missing = section_toolchain_missing(node_bin)
    if missing is not None:
        raise SiteKitCliError("site_kit.toolchain_missing", missing)
    path = SITE_KIT_DIR / "bin" / script
    if not path.is_file():
        raise SiteKitCliError("site_kit.cli_missing", f"{script} is not in {SITE_KIT_DIR / 'bin'}")
    return _run_node([node_bin, "--import", "tsx", str(path)], payload, cwd=SITE_KIT_DIR, timeout_s=timeout_s, what=script)


def validate_site_files(
    files: Mapping[str, Any],
    brand: Mapping[str, Any],
    section_schemas: Mapping[str, Mapping[str, Any]],
    site_images: Sequence[str] = (),
) -> dict[str, Any]:
    """The site-kit validator over the agent's files (contracts only), through Lane A's call.

    ``files`` is ``{"pages": {route: page JSON or text}, "shell": shell JSON, text or None}`` — the
    validator parses text itself and reports a file that is not JSON. Agent sections are checked
    against their STORED props JSON Schema, never by importing a module. ``site_images`` are the
    ``/asset-store/<sha256>`` images this workspace holds that the brand does not list.
    """

    from .site_doc_validate import SiteValidatorUnavailable, run_site_validator

    try:
        errors = run_site_validator(
            {"pages": dict(files.get("pages") or {}), "shell": files.get("shell")},
            brand,
            section_schemas={name: dict(schema) for name, schema in section_schemas.items()},
            site_images=list(site_images),
        )
    except SiteValidatorUnavailable as error:
        raise SiteKitCliError("site_kit.validator_unavailable", str(error)) from error
    return {"valid": not errors, "errors": errors}


def build_site_catalog(brand: Mapping[str, Any], seller: str) -> dict[str, str]:
    """The agent's catalog for ``brand``: ``{relative path: markdown}`` (catalog/*, brand/brand.md)."""

    answer = run_site_kit_bundle("build-catalog.mjs", {"brand": dict(brand), "seller": seller}, what="the catalog builder")
    return {str(path): str(markdown) for path, markdown in answer.items()}
```

- [ ] **Step 4: Move Lane A's validator onto the runner.** In `site_doc_validate.py`, add
`from .site_kit_cli import SiteKitCliError, run_site_kit_bundle` to the imports and replace the
body of `run_site_validator` (everything from `bundle = site_kit_dist() / "validate-site.mjs"`
to its `return`) with:

```python
    payload = {
        "files": {"pages": site["pages"], "shell": site["shell"]},
        "brand": brand,
        "agentSectionSchemas": dict(section_schemas),
        "images": {"siteImages": list(site_images), "accountLogos": []},
    }
    try:
        result = run_site_kit_bundle(
            "validate-site.mjs", payload, timeout_s=VALIDATOR_TIMEOUT_S, node_bin=node_bin, what="the site validator"
        )
    except SiteKitCliError as error:
        raise SiteValidatorUnavailable(error.detail) from error
    return [str(error) for error in result.get("errors") or []]
```

Remove the imports that only the old body used (`subprocess`, `os`, `json` if nothing else in
the module uses them — check with `grep -n "subprocess\.\|os\.\|json\." site_doc_validate.py`).

- [ ] **Step 5: Run the tests, then Lane A's validator tests.**

Run: API `test_site_kit_cli.py`, then API `test_site_doc_validate.py` (Lane A's file; use the real
name `ls subsystems/clue-design/apps/api/tests | grep site_doc`).
Expected: PASS for both (Lane A's tests only assert the exception type and the errors).

- [ ] **Step 6: Commit.**

```bash
git add subsystems/clue-design/apps/api/lumen_api/site_kit_cli.py subsystems/clue-design/apps/api/lumen_api/site_doc_validate.py subsystems/clue-design/apps/api/tests/test_site_kit_cli.py
git commit -m "site_kit_cli: one Node runner for site-kit's bundles and scripts (stripped env, typed failures); Lane A's validator runs through it"
```

---

### Task 4: The `lumen_agent/site/` package: the spike's prompt and skills verbatim, and the turn's inputs (B1)

**Files:**
- Create: `subsystems/clue-design/apps/agent_runtime/lumen_agent/site/__init__.py`
- Create: `subsystems/clue-design/apps/agent_runtime/lumen_agent/site/inputs.py`
- Copy (verbatim): `site/system_prompt.md`, `site/SKILLS-CHANGELOG.md`, `site/skills/**`,
  `site/skills-e5/**` from `trials/puck-spike/agent/`
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_site_package.py` (new)

**Interfaces:**
- Produces (used by every later runtime task and by the design API):
  - `SiteSection(name: str, digest: str, props_schema: dict, module_js: str, css: str)` (frozen)
  - `AccountLogo(cell: str, file: str, content_type: str, label: str | None = None, alternative: bool = False)` (frozen)
  - Protocols `SiteAssetPort`, `SiteSectionPort`, `SiteVersionPort`, `SiteRenderPort` (signatures below)
  - `SiteTurnInputs` (frozen dataclass, fields below)

- [ ] **Step 1: Copy the spike's agent-facing files verbatim.**

```bash
S=trials/puck-spike/agent; D=subsystems/clue-design/apps/agent_runtime/lumen_agent/site
mkdir -p $D
cp $S/system_prompt.md $S/SKILLS-CHANGELOG.md $D/
cp -R $S/skills $D/skills
cp -R $S/skills-e5 $D/skills-e5
find $D -name '.DS_Store' -delete
diff -r $S/skills $D/skills && diff -r $S/skills-e5 $D/skills-e5 && cmp $S/system_prompt.md $D/system_prompt.md && echo "verbatim"
```

Expected: `verbatim`.

- [ ] **Step 2: Write the failing package test** `apps/agent_runtime/tests/test_site_package.py`:

```python
"""The site agent's package: prompt and skills carried from the Puck spike (Lane B Task 4)."""

from __future__ import annotations

from pathlib import Path

from lumen_agent.site import inputs
from lumen_agent.site.inputs import AccountLogo, SiteSection, SiteTurnInputs

SITE = Path(inputs.__file__).resolve().parent
SPIKE = Path(__file__).resolve().parents[5] / "trials" / "puck-spike" / "agent"
UNCHANGED = [
    "skills/account-page-copy/SKILL.md",
    "skills/page-review/SKILL.md",
    "skills-e5/rebuilding-a-section/SKILL.md",
    "skills-e5/writing-a-section/SKILL.md",
]


def test_the_untouched_skills_are_the_spikes_word_for_word() -> None:
    for relative in UNCHANGED:
        assert (SITE / relative).read_bytes() == (SPIKE / relative).read_bytes(), relative


def test_the_package_ships_its_prompt_and_six_skills() -> None:
    assert (SITE / "system_prompt.md").is_file()
    assert sorted(p.parent.name for p in (SITE / "skills").glob("*/SKILL.md")) == [
        "account-page-copy", "building-with-puck", "images-and-logos", "page-review",
    ]
    assert sorted(p.parent.name for p in (SITE / "skills-e5").glob("*/SKILL.md")) == [
        "rebuilding-a-section", "writing-a-section",
    ]


def test_the_inputs_default_to_an_empty_turn() -> None:
    section = SiteSection(name="StepsBand", digest="a" * 64, props_schema={}, module_js="", css="")
    logo = AccountLogo(cell="light_lockup", file="/asset-store/" + "b" * 64, content_type="image/svg+xml")
    turn = SiteTurnInputs(
        document_id="doc_1", workspace_id="ws_1", brief="b", account_name="Acme",
        seller="Garner Health", brand={"assets": {}, "clones": {}}, catalog={},
        agent_sections={"StepsBand": section}, account_logos=[logo],
    )
    assert turn.overview == [] and turn.claims == [] and turn.held_claim_ids == frozenset()
    assert turn.assets is None and turn.renderer is None and logo.alternative is False
```

- [ ] **Step 3: Run it and watch it fail.**

Run: RT `test_site_package.py`
Expected: FAIL at import — `ModuleNotFoundError: No module named 'lumen_agent.site'`.

- [ ] **Step 4: Write `site/__init__.py`:**

```python
"""The Puck site agent (website agent on Puck, Lane B): harness, tools, workspace, prompt, skills.

Ported from the spike in trials/puck-spike/agent/. The runtime never reads the database: the
design API builds a `SiteTurnInputs` (inputs.py) and hands it to `harness.run_site_turn`.
"""
```

- [ ] **Step 5: Write `site/inputs.py`:**

```python
"""What one site turn reads, by value, plus the four capabilities it may call (Lane B).

The design API builds this from the database (lumen_api/site_workspace_view.py); the runtime
only reads it — the rule `AgentRuntimeConfig` follows for brand kits and asset libraries. The
four ports are capabilities rather than values for the reason the cloned-section registry is: a
byte read, a governed write, a document-history read and a hardened render each happen at the
moment the agent asks, through the API's own seams.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

__all__ = [
    "AccountLogo",
    "SiteAssetPort",
    "SiteRenderPort",
    "SiteSection",
    "SiteSectionPort",
    "SiteTurnInputs",
    "SiteVersionPort",
]


@dataclass(frozen=True)
class SiteSection:
    """One compiled agent-written section (Contract 4), as the turn may place and render it."""

    name: str
    digest: str
    props_schema: dict
    module_js: str
    css: str


@dataclass(frozen=True)
class AccountLogo:
    """One of the target account's logos, fetched at the start of the request and stored."""

    cell: str
    file: str
    content_type: str
    label: str | None = None
    alternative: bool = False


class SiteAssetPort(Protocol):
    def read(self, digest: str) -> tuple[str, bytes]:
        """``(media_type, bytes)`` of one of this workspace's blobs; raises when absent."""

    def exists(self, digest: str) -> bool:
        """Whether this workspace durably holds readable bytes for ``digest``."""

    def register_generated(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        prompt: str,
        model: str | None,
        license: dict | None,
        provenance: dict,
    ) -> dict:
        """Store a generated image as an AI-generated library asset: ``{asset_id, digest, file}``."""


class SiteSectionPort(Protocol):
    def compile(self, *, name: str, source: str) -> dict:
        """Check, compile, read the props schema, store and record one section.

        ``{"ok": True, "section": SiteSection}`` or ``{"ok": False, "errors": [str]}``.
        """


class SiteVersionPort(Protocol):
    def list_versions(self, limit: int) -> list[dict]:
        """The newest ``limit`` saved versions: ``[{version, actor, intent, created_at}]``."""

    def site_at(self, version: int) -> dict | None:
        """The whole site as it was at ``version``, or ``None``."""


class SiteRenderPort(Protocol):
    def render(
        self, site: dict, brand: dict, sections: list[SiteSection], *, route: str
    ) -> tuple[str, str, list[str]]:
        """``(sanitized html of route, css, warnings)``; raises with a ``code`` attribute."""

    def screenshot(self, html: str, css: str, *, width: int) -> bytes:
        """A full-page PNG of rendered HTML at ``width``, network blocked."""


@dataclass(frozen=True)
class SiteTurnInputs:
    """Everything one site turn reads. Built by the design API; read-only to the runtime."""

    document_id: str
    workspace_id: str
    #: brief.md: the delegation brief plus "THIS ARTIFACT: <json>" (the spike's format).
    brief: str
    account_name: str
    #: The seller's name, the title of brand/brand.md.
    seller: str
    #: site-kit BrandData (lumen_api/site_brand.py); every file is /asset-store/<sha256>.
    brand: dict
    #: {relative path: markdown} from site-kit's catalog CLI: catalog/* and brand/brand.md.
    catalog: dict[str, str]
    overview: list[dict] = field(default_factory=list)
    insights: list[dict] = field(default_factory=list)
    #: Served AccountClaimView dicts about the account (read_cited_claims@1).
    claims: list[dict] = field(default_factory=list)
    #: Cited ids held back by a real rule: statements citing them leave the research files.
    held_claim_ids: frozenset[str] = frozenset()
    #: [{path, body_text}] — the opening turn's pinned instructions.md and decisions.md.
    project_files: list[dict] = field(default_factory=list)
    account_logos: list[AccountLogo] = field(default_factory=list)
    #: Sections the turn may place: the document's own pins plus the newest of each name.
    agent_sections: dict[str, SiteSection] = field(default_factory=dict)
    #: {asset_id: {"record": AssetRecord, "description"?, "title"?, "tags"?, "origin": str}}.
    asset_candidates: dict = field(default_factory=dict)
    #: {asset_id: [512 floats]} CLIP vectors, or None when visual search is off.
    asset_embeddings: dict | None = None
    #: The platform reads (web_search, seller_knowledge), or None outside a leg.
    platform_reads: Any = None
    assets: SiteAssetPort | None = None
    sections: SiteSectionPort | None = None
    site_versions: SiteVersionPort | None = None
    renderer: SiteRenderPort | None = None
    #: Test seam for image generation; None means lumen_api.image_provider.generate.
    image_generate: Any = None
```

- [ ] **Step 6: Run the test.**

Run: RT `test_site_package.py`
Expected: PASS.

- [ ] **Step 7: Apply the founder-approved prompt and skill changes (T1, T2a–c, T3, T4, T5, T-A9-5).**
Only the rows the founder approved in Task 0, with the founder's words. With the table's words:

In `site/system_prompt.md`:
- after the line ``- `fetched/`: pages you opened with `fetch_page`.`` add
  ``- `project-context/`: the project's own instructions and decisions, as they stood when this site was asked for.`` (T1);
- replace ``- `validate_page`: checks `page.json` and `shell.json`. It saves a version when the page is valid.``
  with ``- `validate_page`: checks `page.json` and `shell.json`.`` (T2a);
- replace ``- `restore_version`: brings back a saved version.`` with
  ``- `restore_version`: brings back an earlier saved version of the site (`site.md` lists them).`` (T2b);
- after ``- `view_asset`: shows you one image.`` add
  ``- `search_assets`: finds the seller's other images (uploads, and images made for earlier pages) by what they show.`` (T2c);
- replace the two lines of "How to work" step 1 with
  ``1. Your skills are below this prompt: `account-page-copy`, `building-with-puck`,`` /
  `` `images-and-logos` and `page-review`, and for new sections `writing-a-section` and`` /
  `` `rebuilding-a-section`. Follow them.`` (T3, three lines, three-space indent on lines 2–3).

In `site/skills/building-with-puck/SKILL.md:112` replace
``If a change made the page worse, `restore_version` brings back the last good version.`` with
``If a change made the page worse, fix it, or bring back an earlier saved version with `restore_version` (`site.md` lists them).`` (T4).

In `site/skills/images-and-logos/SKILL.md`, after the last bullet of section 1 add
``- The seller's other images (uploads, and images made for earlier pages) are not in `brand/brand.md`. Find them with `search_assets`, and look at one with `view_asset` before you use it.`` (T5).

In `site/skills-e5/writing-a-section/SKILL.md`, apply T-A9-5 (approved 2026-10-12) exactly as written
in `docs/superpowers/plans/2026-10-12-lane-a-a9-brand-fidelity-rewrite.md`, section "T-A9-5": the
example's `surface: z.enum(["page", "card", "muted", "brandSubtle", "brand", "inverse"]),` becomes
`surface: z.string(),`, the "The kit gives you these pieces" list is replaced by T-A9-5's list, and
the Rules bullet's spacing phrase becomes T-A9-5's. (It names `look`, `kit.Link`, `kit.Card` and the
brand's motion classes, which the A9 rewrite's site-kit tasks provide; the skill is only read by the
agent, so it can land before them.)

Append to `site/SKILLS-CHANGELOG.md` one line per applied row, in the file's format, for example:
``- 2026-10-11 · system prompt, tools: validate_page no longer saves versions; restore_version brings back a saved document version (production versions are the document's history, founder-approved). No failing case: production differs from the spike.``

- [ ] **Step 8: Pin the applied text in the package test.** Append to `test_site_package.py`
(drop a pair for any row the founder declined):

```python
def test_the_approved_prompt_and_skill_changes_are_in_place() -> None:
    prompt = (SITE / "system_prompt.md").read_text()
    assert "- `project-context/`: the project's own instructions and decisions" in prompt
    assert "It saves a version when the page is valid." not in prompt
    assert "brings back an earlier saved version of the site (`site.md` lists them)." in prompt
    assert "- `search_assets`: finds the seller's other images" in prompt
    assert "and for new sections `writing-a-section` and" in prompt
    building = (SITE / "skills/building-with-puck/SKILL.md").read_text()
    assert "brings back the last good version." not in building
    assert "bring back an earlier saved version with `restore_version`" in building
    images = (SITE / "skills/images-and-logos/SKILL.md").read_text()
    assert "Find them with `search_assets`" in images
```

Run: RT `test_site_package.py`
Expected: PASS.

- [ ] **Step 9: Commit.**

```bash
git add subsystems/clue-design/apps/agent_runtime/lumen_agent/site subsystems/clue-design/apps/agent_runtime/tests/test_site_package.py
git commit -m "lumen_agent.site: the Puck spike's prompt and skills (founder-approved production deltas) and the site turn's inputs"
```

---

### Task 5: `lumen_agent/site/workspace.py` — the files the agent works in (B1/B2, runtime half)

The spike's `workspace.py` ported: research markdown, claim labels, the claims file, the site
summary, change notes and history are the spike's functions; inputs arrive by value; every image
is `/asset-store/<sha256>`; nothing reads `trials/puck-spike/data/` or writes `public/`.

**Files:**
- Create: `subsystems/clue-design/apps/agent_runtime/lumen_agent/site/workspace.py`
- Create: `subsystems/clue-design/apps/agent_runtime/tests/site_fixtures.py` (shared test helpers)
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_site_workspace.py` (new)

**Interfaces:**
- Consumes: `SiteTurnInputs`, `SiteSection`, `AccountLogo` (Task 4);
  `lumen_agent.platform_reads.write_seller_knowledge(workspace, reads, *, record) -> bool`.
- Produces:
  - constants `SITE_DIR`, `REGENERATED`, `SESSION_REGENERATED: frozenset[str]`, `REAL_HOLD_REASONS`, `LOGO_CELLS`
  - spike functions unchanged: `research_markdown`, `cited_claim_ids`, `claim_labels`,
    `claims_markdown`, `research_people`, `read_research(reads, account_entity_id, section)`,
    `site_changes(before, after)`
  - `held_claim_ids(dispositions: Mapping[str, str]) -> set[str]`
  - `account_logo_section(logos: Sequence[AccountLogo]) -> str`
  - `turn_brand(brand: Mapping, logos: Sequence[AccountLogo]) -> dict`
  - `site_pages_of(site: Mapping) -> dict[str, dict]`, `site_pages(workspace: Path) -> dict[str, dict]`
  - `write_site_files(workspace: Path, site: Mapping) -> None`
  - `read_site_files(workspace: Path, base: Mapping, sections: Mapping[str, SiteSection]) -> dict`
  - `site_summary(workspace: Path, brand: Mapping, versions: Sequence[Mapping] | None = None) -> str`
  - `history_count(workspace: Path) -> int`
  - `append_history(workspace, number, request, changes, shell_changed, reply, saved=None) -> None`
  - `saved_line(*, status: str, stop_reason: str | None, outcome_status: str | None, version: int | None) -> str`
  - `seller_components_markdown(schemas: Mapping[str, Mapping]) -> str`, `record_component(workspace, name, props_schema) -> None`
  - `materialize_workspace(workspace: Path, inputs: SiteTurnInputs, *, site: Mapping, record=None) -> dict`

- [ ] **Step 1: Write the shared test helpers** `apps/agent_runtime/tests/site_fixtures.py`
(the spike's tests read the gitignored `trials/puck-spike/data/brands/`; these read the tracked
site-kit fixtures, built the way `site-kit/test/fixtures/garner.ts` builds them):

```python
"""Shared helpers for the site agent's tests: site-kit's tracked fixtures, fakes for the ports,
and the spike's scripted model (Lane B). Not a conftest, so each test file imports what it uses."""

from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

from lumen_agent.site.inputs import SiteSection, SiteTurnInputs

FIXTURES = Path(__file__).resolve().parents[5] / "apps" / "frontend" / "packages" / "site-kit" / "test" / "fixtures"
_CLONE_IMAGE = re.compile(r'<img[^>]*?src="([^"]+\.(?:png|jpe?g|webp|avif))"[^>]*?(?:alt="([^"]*)")?')


def read_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def garner_brand() -> dict:
    """BrandData for Garner, exactly as site-kit's `brandData()` builds the test fixture."""

    clones = read_fixture("clones.json")
    captured: dict[str, dict] = {}
    for clone in clones:
        for match in _CLONE_IMAGE.finditer(clone["html"]):
            file = match.group(1)
            if not file.startswith("/brands/") or file in captured:
                continue
            captured[file] = {
                "kind": "captured_image", "label": clone["label"],
                "description": match.group(2) or f'From the seller\'s section "{clone["label"]}"',
                "mime": None, "file": file, "logo": None,
            }
    return {
        "slug": "garner", "kit": read_fixture("kit.json"),
        "fonts": read_fixture("fonts.json"), "assets": {**read_fixture("assets.json"), **captured},
        "clones": {clone["id"]: clone for clone in clones},
    }


def garner_site(document_id: str = "doc_garner") -> dict:
    """The phase-1 Garner page as a stored site document (Contract 1)."""

    stored = read_fixture("garner-syracuse.json")
    return {"id": document_id, "title": "Syracuse City School District", "theme": {},
            "pages": stored["pages"], "shell": stored["shell"], "agent_sections": {}}


def png(colour: str = "white", size: tuple[int, int] = (32, 18)) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


@dataclass
class FakeAssets:
    """SiteAssetPort over a dict of digest -> (media type, bytes)."""

    blobs: dict[str, tuple[str, bytes]] = field(default_factory=dict)
    generated: list[dict] = field(default_factory=list)
    fail_register: bool = False

    def read(self, digest: str) -> tuple[str, bytes]:
        if digest not in self.blobs:
            raise KeyError(digest)
        return self.blobs[digest]

    def exists(self, digest: str) -> bool:
        return digest in self.blobs

    def register_generated(self, *, image_bytes, mime_type, prompt, model, license, provenance) -> dict:
        import hashlib

        if self.fail_register:
            raise RuntimeError("storage down")
        digest = hashlib.sha256(image_bytes).hexdigest()
        self.blobs[digest] = (mime_type, image_bytes)
        self.generated.append({"prompt": prompt, "model": model, "digest": digest})
        return {"asset_id": f"asset_gen_{digest[:12]}", "digest": digest, "file": f"/asset-store/{digest}"}


@dataclass
class FakeVersions:
    """SiteVersionPort over a dict of version -> site."""

    sites: dict[int, dict] = field(default_factory=dict)

    def list_versions(self, limit: int) -> list[dict]:
        return [{"version": v, "actor": "agent", "intent": f"request {v}", "created_at": "2026-10-11T14:02:00+00:00"}
                for v in sorted(self.sites, reverse=True)[:limit]]

    def site_at(self, version: int) -> dict | None:
        return self.sites.get(version)


@dataclass
class FakeRenderer:
    """SiteRenderPort: records what it was asked to draw; answers with fixed HTML and PNGs."""

    html: str = '<main><img src="/asset-store/' + "a" * 64 + '"></main>'
    warnings: list[str] = field(default_factory=list)
    shot: bytes = b""
    fail_code: str | None = None
    calls: list[tuple] = field(default_factory=list)

    def render(self, site, brand, sections, *, route):
        self.calls.append(("render", route, [s.name for s in sections]))
        if self.fail_code:
            error = RuntimeError(self.fail_code)
            error.code = self.fail_code  # type: ignore[attr-defined]
            raise error
        return self.html, ".x{}", list(self.warnings)

    def screenshot(self, html, css, *, width):
        self.calls.append(("screenshot", width))
        return self.shot or png("white", (width, 2000))


@dataclass
class FakeSections:
    """SiteSectionPort: compiles nothing; answers with a canned section or errors."""

    errors: list[str] = field(default_factory=list)
    calls: list[tuple[str, str]] = field(default_factory=list)

    def compile(self, *, name: str, source: str) -> dict:
        self.calls.append((name, source))
        if self.errors:
            return {"ok": False, "errors": list(self.errors)}
        schema = {"type": "object", "properties": {"id": {"type": "string"}, "surface": {"type": "string"}, "quote": {"type": "string"}}}
        return {"ok": True, "section": SiteSection(name=name, digest="e" * 64, props_schema=schema, module_js="export {}", css="")}


def inputs_for(brand: dict | None = None, **overrides: Any) -> SiteTurnInputs:
    values: dict[str, Any] = {
        "document_id": "doc_garner", "workspace_id": "ws_test", "brief": "For the page\n",
        "account_name": "Syracuse City School District", "seller": "Garner Health",
        "brand": brand if brand is not None else garner_brand(),
        "catalog": {"catalog/index.md": "# Sections you can use\n", "brand/brand.md": "# Brand: Garner Health\n"},
    }
    values.update(overrides)
    return SiteTurnInputs(**values)


class ScriptedModel(GenericFakeChatModel):
    """Answers with the next scripted message; tools are accepted and ignored (the spike's)."""

    def bind_tools(self, tools, **kwargs):
        return self


def call(name: str, args: dict, n: int) -> dict:
    return {"name": name, "args": args, "id": f"call_{n}", "type": "tool_call"}
```

- [ ] **Step 2: Write the failing workspace tests** `apps/agent_runtime/tests/test_site_workspace.py`.
The research, label and claims tests are the spike's (`trials/puck-spike/agent/tests/test_workspace.py:12-209`)
with the import changed; the rest are new:

```python
"""The site agent's workspace (Lane B Task 5); research tests ported from the Puck spike."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from lumen_agent.site import workspace as ws
from lumen_agent.site.inputs import AccountLogo, SiteSection
from site_fixtures import FakeVersions, garner_brand, garner_site, inputs_for

WHY_NOW = {
    "section_key": "why-now",
    "body_text": json.dumps({
        "h1": "Why now",
        "intro": [{"claimIds": ["61ba3351-157f-53c9-a6e4-7ee89856b693"], "kind": "inference",
                   "text": "A new CHCO and cost testimony make a first call timely."}],
        "items": [{
            "h2": "Healthcare cost is on the record",
            "body": [{"claimIds": ["87b908a3-e799-5ee6-8b39-175a98e55ea9"], "kind": "quote",
                      "text": "Costs “will rise 8% in the coming school year.”"},
                     {"claimIds": ["cc0805bc-da90-57c5-b90b-785e98bee92a"], "kind": "fact",
                      "text": "The budget added $4.2 million for healthcare."}],
            "contactRefs": [{"contactId": "e78569d2", "name": "Nalisa Clark"},
                            {"contactId": "fbde4757", "name": "Michael Puntschenko"}],
        }],
    }),
    "cited_claim_ids": ["61ba3351-157f-53c9-a6e4-7ee89856b693"],
}
RESTRICTED = {"section_key": "private", "body_text": json.dumps({"h1": "Private", "restricted": True})}
TRUNCATED = {"section_key": "long", "body_text": '{"h1": "Long", "intro": [{"text": "cut off'}
QUOTE_ID = "87b908a3-e799-5ee6-8b39-175a98e55ea9"
BUDGET_ID = "cc0805bc-da90-57c5-b90b-785e98bee92a"
INFERENCE_ID = "61ba3351-157f-53c9-a6e4-7ee89856b693"
CLAIMS = [
    {"claim_id": BUDGET_ID, "field_key": "account.research_finding",
     "value": {"topic": "Budget", "finding": "Healthcare up $4.2 million", "notes": ["The reporter's estimate."],
               "review": {"status": "supported"}},
     "source_url": "https://example.org/budget.pdf", "evidence": "", "evidence_truncated": False},
    {"claim_id": QUOTE_ID, "field_key": "account.employee_count", "value": 4108,
     "source_url": "https://example.org/nces", "evidence": "Total staff FTE 4,108.72 for the district",
     "evidence_truncated": True},
]


def test_research_becomes_plain_markdown_without_claim_ids() -> None:
    text = ws.research_markdown("SCSD: overview", [WHY_NOW, RESTRICTED, TRUNCATED])
    assert "## Why now" in text and "### Healthcare cost is on the record" in text
    assert "- (inference) A new CHCO" in text and "- (quote) Costs" in text
    assert "61ba3351" not in text and "claimIds" not in text
    assert "## Private (background only, never on the page)" in text
    assert "cut off" in text


def test_claim_labels_skip_claims_not_served_and_the_claims_file_says_what_each_says() -> None:
    labels = ws.claim_labels([WHY_NOW], served={QUOTE_ID, BUDGET_ID})
    assert labels == {QUOTE_ID: "c1", BUDGET_ID: "c2"}
    text = ws.claims_markdown("Syracuse City School District", labels, CLAIMS)
    assert "Says: Healthcare up $4.2 million\nTopic: Budget\nNotes: The reporter's estimate.\n" in text
    assert "Quote (shortened): “Total staff FTE 4,108.72 for the district”" in text
    assert QUOTE_ID not in text


def test_held_dispositions_drop_only_statements_resting_on_a_real_rule() -> None:
    """Review focus 2: a real rule drops the statement; an unverified finding or another
    entity's claim does not."""

    held = ws.held_claim_ids({
        QUOTE_ID: "served",
        BUDGET_ID: "held:outreach_unsafe",
        INFERENCE_ID: "held:unverified_finding",
        "x": "held:other_entity",
        "y": "not_found",
        "z": "held:sensitive",
    })
    assert held == {BUDGET_ID, "z"}
    text = ws.research_markdown("SCSD: overview", [WHY_NOW], {QUOTE_ID: "c1"}, held=held)
    assert "Costs “will rise 8% in the coming school year.” [c1]" in text
    assert "The budget added $4.2 million" not in text
    assert "A new CHCO" in text  # rests on an unverified finding: kept


def test_materialize_writes_the_workspace_the_prompt_describes(tmp_path: Path) -> None:
    seller = SimpleNamespace(
        documents=[SimpleNamespace(path="product/garner-core.md", kind="product", version=1,
                                   status="active", body_text="Garner Core")],
        documents_sha256="f" * 64, confirmed_icp_path=None, product_set=None,
    )
    reads = SimpleNamespace(seller_knowledge=lambda: seller)
    inputs = inputs_for(
        overview=[WHY_NOW], claims=CLAIMS, platform_reads=reads,
        project_files=[{"path": "instructions.md", "body_text": "Lead with cost."},
                       {"path": "decisions.md", "body_text": "No video."}],
    )
    workspace = tmp_path / "workspace"
    summary = ws.materialize_workspace(workspace, inputs, site=garner_site())
    for path in ["brief.md", "research/overview.md", "research/insights.md", "research/claims.md",
                 "seller/index.md", "seller/product/garner-core.md", "catalog/index.md",
                 "brand/brand.md", "skills/building-with-puck/SKILL.md",
                 "skills-e5/writing-a-section/SKILL.md", "project-context/instructions.md",
                 "project-context/decisions.md", "page.json", "pages/analysis.json", "shell.json",
                 "site.md"]:
        assert (workspace / path).exists(), path
    assert (workspace / "fetched").is_dir()
    assert summary["claims_labelled"] == 2 and summary["people_in_research"] == 2
    assert "## The account's logo (header only)\n\nNone was found." in (workspace / "brand/brand.md").read_text()


def test_materialize_rebuilds_inputs_but_keeps_memory(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    ws.materialize_workspace(workspace, inputs_for(overview=[WHY_NOW]), site=garner_site())
    (workspace / "plan.md").write_text("my plan")
    (workspace / "history.md").write_text("# history")
    (workspace / "fetched" / "story.md").write_text("Source: x")
    (workspace / "research" / "stale.md").write_text("old research")
    ws.materialize_workspace(workspace, inputs_for(), site=garner_site())
    assert not (workspace / "research" / "stale.md").exists()
    assert "no written research" in (workspace / "research" / "README.md").read_text()
    assert (workspace / "plan.md").read_text() == "my plan"
    assert (workspace / "history.md").read_text() == "# history"
    assert (workspace / "fetched" / "story.md").exists()
    assert {"research", "catalog", "brand", "page.json", "pages", "shell.json", "work"} <= ws.SESSION_REGENERATED
    assert "plan.md" not in ws.SESSION_REGENERATED and "fetched" not in ws.SESSION_REGENERATED


def test_the_account_logos_are_listed_in_brand_md_and_join_the_turn_brand(tmp_path: Path) -> None:
    light = AccountLogo(cell="light_lockup", file="/asset-store/" + "1" * 64, content_type="image/svg+xml")
    other = AccountLogo(cell="unclassified", file="/asset-store/" + "2" * 64, content_type="image/png",
                        label="Dana.AI logo (site: light lockup, header)", alternative=True)
    workspace = tmp_path / "workspace"
    ws.materialize_workspace(workspace, inputs_for(account_logos=[light, other]), site=garner_site())
    brand_md = (workspace / "brand/brand.md").read_text()
    assert f"- `{light.file}`: the full logo, for light backgrounds" in brand_md
    assert brand_md.index(light.file) < brand_md.index("Other logos found for the account")
    assert f"- `{other.file}`: Dana.AI logo (site: light lockup, header)" in brand_md
    files = {a["file"] for a in ws.turn_brand(garner_brand(), [light, other])["assets"].values()}
    assert {light.file, other.file} <= files


def test_site_files_round_trip_and_agent_sections_follow_the_content(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    site = garner_site()
    ws.write_site_files(workspace, site)
    page = json.loads((workspace / "page.json").read_text())
    page["content"].append({"type": "QuoteBand", "props": {"id": "q", "surface": "muted", "quote": "A line."}})
    (workspace / "page.json").write_text(json.dumps(page))
    sections = {
        "QuoteBand": SiteSection(name="QuoteBand", digest="e" * 64, props_schema={}, module_js="", css=""),
        "Unused": SiteSection(name="Unused", digest="d" * 64, props_schema={}, module_js="", css=""),
    }
    read = ws.read_site_files(workspace, site, sections)
    assert read["id"] == site["id"] and read["title"] == site["title"]
    assert set(read["pages"]) == {"/", "/analysis"} and read["shell"] == site["shell"]
    assert read["agent_sections"] == {"QuoteBand": "e" * 64}


def test_the_site_summary_names_pages_sections_images_and_saved_versions(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ws.write_site_files(workspace, garner_site())
    versions = FakeVersions(sites={3: {}, 4: {}}).list_versions(10)
    text = ws.site_summary(workspace, garner_brand(), versions)
    assert "## / (page.json)" in text and "## /analysis (pages/analysis.json)" in text
    assert "Lower medical spend for SCSD" in text and "Prepared for: Syracuse City School District" in text
    assert "StatsBand on the brandSubtle surface" in text
    assert "## Saved versions" in text
    assert '- version 4: "request 4" (by the agent, 2026-10-11 14:02 UTC)' in text


def test_a_generated_image_is_described_by_its_prompt(tmp_path: Path) -> None:
    brand = garner_brand()
    file = "/asset-store/" + "9" * 64
    brand["assets"]["asset_gen_x"] = {"kind": "generated_image", "label": "A calm school scene",
                                      "description": "generated: A calm school scene", "mime": "image/png",
                                      "file": file, "logo": None}
    site = garner_site()
    site["pages"]["/"]["content"].append({"type": "FeatureSplit", "props": {
        "id": "gen", "surface": "page", "heading": "H", "body": "B", "image": file}})
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ws.write_site_files(workspace, site)
    assert f"{file} (generated: A calm school scene)" in ws.site_summary(workspace, brand)


def test_site_changes_and_history_say_what_happened_and_whether_it_was_saved(tmp_path: Path) -> None:
    before = {"/": {"content": [{"type": "A", "props": {"id": "hero", "x": 1}}, {"type": "B", "props": {"id": "proof"}}]}}
    after = {"/": {"content": [{"type": "B", "props": {"id": "proof"}}, {"type": "A", "props": {"id": "hero", "x": 2}}]},
             "/analysis": {"content": []}}
    notes = ws.site_changes(before, after)
    assert "added the page /analysis" in notes and "/: changed hero (x)" in notes
    ws.append_history(tmp_path, number=1, request="Warmer hero", changes=notes, shell_changed=False,
                      reply="Done.", saved=ws.saved_line(status="applied", stop_reason=None,
                                                         outcome_status="saved", version=5))
    ws.append_history(tmp_path, number=2, request="Add a page", changes=[], shell_changed=False,
                      reply="Stopped.", saved=ws.saved_line(status="failed", stop_reason="cancelled_by_request",
                                                            outcome_status=None, version=None))
    history = (tmp_path / "history.md").read_text()
    assert "## 1. Warmer hero\n- What changed: " in history and "- Saved: as version 5\n" in history
    assert "## 2. Add a page\n- What changed: nothing changed\n- The reply: Stopped.\n- Saved: no, it was stopped\n" in history
    assert ws.history_count(tmp_path) == 2
    assert ws.saved_line(status="applied", stop_reason=None, outcome_status=None, version=None) == "nothing to save"
    assert ws.saved_line(status="applied", stop_reason=None, outcome_status="conflicted", version=7) == (
        "no, the site changed while this request ran")
    assert ws.saved_line(status="failed", stop_reason="site_invalid", outcome_status=None, version=None) == (
        "no, the page was still invalid")


def test_seller_components_list_each_section_with_its_props(tmp_path: Path) -> None:
    ws.record_component(tmp_path, "QuoteBand", {"properties": {"attribution": {"type": "string"}}})
    ws.record_component(tmp_path, "StepsBand", {"properties": {}})
    text = (tmp_path / "catalog" / "seller-components.md").read_text()
    assert text.startswith("# The seller's components on this site")
    assert "## QuoteBand" in text and '"attribution"' in text and "## StepsBand" in text
```

- [ ] **Step 3: Run them and watch them fail.**

Run: RT `test_site_workspace.py`
Expected: FAIL at import — `ModuleNotFoundError: No module named 'lumen_agent.site.workspace'`.

- [ ] **Step 4: Confirm T9 and T10 were approved** (Task 0). If the founder edited either, use the
founder's words in `site_summary` and `saved_line` below, and in the two tests above.

- [ ] **Step 5: Write `site/workspace.py`.** Create the file with the module docstring, imports
and constants below, then **copy these spike functions verbatim** from
`trials/puck-spike/agent/trials_puck_agent/workspace.py`: `_claim_ids` (`:22-23`), `_statements`
(`:26-41`), `_section_body` (`:44-51`), `research_markdown` (`:54-75`), `_section_statements`
(`:78-85`), `cited_claim_ids` (`:88-94`), `claim_labels` (`:97-104`), `_plain` (`:107-112`),
`_claim_lines` (`:115-133`), `claims_markdown` (`:136-150`), `research_people` (`:153-163`),
`read_research` (`:166-176`), `LOGO_CELLS` (`:199-204`), `_short` (`:291-293`), `site_changes`
(`:359-381`). Then add the new functions:

```python
"""The site agent's workspace: the plain files it works in, written by code (Lane B).

Ported from the Puck spike (`trials/puck-spike/agent/trials_puck_agent/workspace.py`). The research
markdown, claim labels, claims file, site summary, change notes and history are the spike's
functions; what changed is where the inputs come from (by value, from the design API — this module
never reads a database) and that every image is `/asset-store/<sha256>`.

Under the session folder's `workspace/`:
- brief.md, research/, seller/, project-context/, catalog/, brand/brand.md, skills/, skills-e5/:
  rebuilt for every request, never restored from the session snapshot;
- page.json, pages/<name>.json, shell.json: the stored site, written at the start of a request and
  read back at its end;
- site.md: written by code at the start of a request when the site has content;
- plan.md, history.md, fetched/: the agent's memory across requests, synced with the session.
"""

from __future__ import annotations

import copy
import json
import shutil
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .inputs import AccountLogo, SiteSection, SiteTurnInputs

SITE_DIR = Path(__file__).resolve().parent

#: Rebuilt from the database at the start of every request.
REGENERATED = (
    "brief.md", "site.md", "research", "catalog", "brand", "project-context", "skills",
    "skills-e5", "page.json", "pages", "shell.json",
)
#: Left out of the session snapshot: everything rebuilt per request, plus `seller/` (rewritten per
#: pin by `write_seller_knowledge`) and `work/` (one request's compaction offloads).
SESSION_REGENERATED = frozenset({*REGENERATED, "seller", "work"})
#: The display gate's real rules (read_cited_claims@1). A research statement citing a claim held
#: for one of these leaves the research files; one citing an unverified finding or another
#: entity's claim stays (the spike's rule, `run_agent.py:93-94`).
REAL_HOLD_REASONS = frozenset({"sensitive", "unverified", "outreach_unsafe"})
_AUTHORS = {"agent": "the agent", "human": "a person", "system": "an undo or redo"}
_COMPONENTS_HEADER = (
    "# The seller's components on this site\n\n"
    "Written for you as each one is written. Use them like any section.\n"
)
```

```python
def held_claim_ids(dispositions: Mapping[str, str]) -> set[str]:
    """The cited ids held back by a real rule, from read_cited_claims@1's dispositions."""

    return {
        claim_id
        for claim_id, disposition in dispositions.items()
        if disposition.startswith("held:") and disposition.removeprefix("held:") in REAL_HOLD_REASONS
    }


def account_logo_section(logos: Sequence[AccountLogo]) -> str:
    """brand.md's account-logo section: the recommended logos first, then the alternatives (the
    spike's text; files are now /asset-store/<sha256>)."""

    out = ["", "## The account's logo (header only)", ""]
    if not logos:
        return "\n".join(out + ["None was found. Leave `accountLogo` empty.", ""])
    recommended = [logo for logo in logos if not logo.alternative]
    others = [logo for logo in logos if logo.alternative]
    for logo in recommended:
        out.append(f"- `{logo.file}`: {LOGO_CELLS.get(logo.cell, logo.cell)}")
    if others:
        out += ["", "Other logos found for the account. Use one only when none of the above fits the header:"]
        for logo in others:
            out.append(f"- `{logo.file}`: {logo.label or 'another logo of the account'}")
    return "\n".join(out + [""])


def turn_brand(brand: Mapping[str, Any], logos: Sequence[AccountLogo]) -> dict:
    """The brand the turn validates with: the stored brand plus this request's account logos."""

    merged = copy.deepcopy(dict(brand))
    assets = merged.setdefault("assets", {})
    for number, logo in enumerate(logos):
        assets[f"account_logo_{number}"] = {
            "kind": "account_logo", "label": logo.label,
            "description": logo.label or LOGO_CELLS.get(logo.cell, logo.cell),
            "mime": logo.content_type, "file": logo.file, "logo": None,
        }
    return merged


def site_pages_of(site: Mapping[str, Any]) -> dict[str, dict]:
    """A stored site's pages by route ("/" is the home page)."""

    return {route: page for route, page in (site.get("pages") or {}).items() if isinstance(page, dict)}


def site_pages(workspace: Path) -> dict[str, dict]:
    """The workspace's pages by route: page.json is "/", pages/<name>.json is "/<name>"."""

    pages = {"/": json.loads((workspace / "page.json").read_text())} if (workspace / "page.json").exists() else {}
    folder = workspace / "pages"
    for file in sorted(folder.glob("*.json")) if folder.exists() else []:
        pages[f"/{file.stem}"] = json.loads(file.read_text())
    return pages


def write_site_files(workspace: Path, site: Mapping[str, Any]) -> None:
    """Write a stored site as the agent's files, replacing whatever site files were there."""

    for name in ("page.json", "shell.json"):
        (workspace / name).unlink(missing_ok=True)
    shutil.rmtree(workspace / "pages", ignore_errors=True)
    for route, page in site_pages_of(site).items():
        if route == "/":
            target = workspace / "page.json"
        else:
            target = workspace / "pages" / f"{route.strip('/')}.json"
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(page, indent=2))
    if site.get("shell") is not None:
        (workspace / "shell.json").write_text(json.dumps(site["shell"], indent=2))


def read_site_files(
    workspace: Path, base: Mapping[str, Any], sections: Mapping[str, SiteSection]
) -> dict:
    """The site as the agent left it: ``base``'s id, title and theme, the workspace's pages and
    shell, and ``agent_sections`` = the sections its pages place (Contract 1)."""

    pages = site_pages(workspace)
    if "/" not in pages:
        pages = {**site_pages_of(base), **pages}
    shell_file = workspace / "shell.json"
    shell = json.loads(shell_file.read_text()) if shell_file.exists() else base.get("shell")
    used = {
        str(item.get("type"))
        for page in pages.values()
        for item in page.get("content") or []
        if isinstance(item, dict)
    }
    return {
        **dict(base),
        "pages": pages,
        "shell": shell,
        "agent_sections": {name: sections[name].digest for name in sorted(used) if name in sections},
    }


def _when(value: object) -> str:
    try:
        return datetime.fromisoformat(str(value)).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return str(value or "")
```

`site_summary` is the spike's (`:296-356`) with three changes — clones and descriptions come from
`brand`, generated images are described from `brand` too, and the saved-versions section (T9) is
appended:

```python
def site_summary(
    workspace: Path, brand: Mapping[str, Any], versions: Sequence[Mapping[str, Any]] | None = None
) -> str:
    """site.md: what is on every page now, in a few lines per section, and the saved versions."""

    clones = brand.get("clones") or {}
    described = {
        asset["file"]: asset.get("description") or ""
        for asset in (brand.get("assets") or {}).values()
        if isinstance(asset, dict) and asset.get("file")
    }

    def image(file: object) -> str:
        return f"{file}" + (f" ({_short(described.get(str(file), ''), 120)})" if described.get(str(file)) else "")

    out = ["# The site as it is now", "",
           "Written for you at the start of this request. The page files are the truth; this is a summary.", ""]
    # From here to the end of the pages loop: the spike's lines 312-355 unchanged.
    ...
    if versions:
        out += ["## Saved versions",
                "Each request and each save in the editor is one version; `restore_version` brings one back."]
        for item in versions:
            out.append(
                f'- version {item.get("version")}: "{_short(item.get("intent") or "", 80)}" '
                f'(by {_AUTHORS.get(str(item.get("actor")), "a person")}, {_when(item.get("created_at"))})'
            )
        out.append("")
    return "\n".join(out)
```

Replace the `...` with the spike's lines 312–355 verbatim (from `if (workspace / "shell.json").exists():`
to the final `out.append("")` of the pages loop), changing only the one call `_site_pages(workspace)`
(line 319) to `site_pages(workspace)`.

```python
def history_count(workspace: Path) -> int:
    """How many requests history.md records (the spike's `run_agent.history_count`)."""

    path = workspace / "history.md"
    return path.read_text().count("\n## ") if path.exists() else 0


def append_history(
    workspace: Path,
    number: int,
    request: str,
    changes: list[str],
    shell_changed: bool,
    reply: str | None,
    saved: str | None = None,
) -> None:
    """history.md, written after each request (the spike's, plus whether it was saved — T10)."""

    path = workspace / "history.md"
    text = path.read_text() if path.exists() else "# Earlier requests in this project\n\nOldest first. Written after each request.\n"
    what = "; ".join(changes + (["changed the header or footer"] if shell_changed else [])) or "nothing changed"
    text += f"\n## {number}. {request}\n- What changed: {what}\n- The reply: {_short(reply or '', 500)}\n"
    if saved is not None:
        text += f"- Saved: {saved}\n"
    path.write_text(text)


def saved_line(
    *, status: str, stop_reason: str | None, outcome_status: str | None, version: int | None
) -> str:
    """history.md's "Saved:" text for one request (T10)."""

    if outcome_status == "saved":
        return f"as version {version}"
    if outcome_status == "conflicted":
        return "no, the site changed while this request ran"
    if outcome_status == "refused":
        return "no, the save was refused"
    if status == "applied":
        return "nothing to save"
    if stop_reason == "site_invalid":
        return "no, the page was still invalid"
    if stop_reason == "cancelled_by_request":
        return "no, it was stopped"
    return "no, the request did not finish"


def _component_entry(name: str, props_schema: Mapping[str, Any]) -> str:
    return f"Use it with `\"type\": \"{name}\"` and these props:\n\n```json\n{json.dumps(props_schema, indent=1)}\n```\n"


def seller_components_markdown(schemas: Mapping[str, Mapping[str, Any]]) -> str:
    """catalog/seller-components.md for the sections the turn may place (the spike's format)."""

    return _COMPONENTS_HEADER + "".join(f"\n## {name}\n{_component_entry(name, schema)}" for name, schema in schemas.items())


def record_component(workspace: Path, name: str, props_schema: Mapping[str, Any]) -> None:
    """Add or replace one section in catalog/seller-components.md (the spike's `_record_component`)."""

    path = workspace / "catalog" / "seller-components.md"
    entries: dict[str, str] = {}
    if path.exists():
        for chunk in path.read_text().split("\n## ")[1:]:
            entries[chunk.split("\n", 1)[0].strip()] = chunk.split("\n", 1)[1] if "\n" in chunk else ""
    entries[name] = _component_entry(name, props_schema)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_COMPONENTS_HEADER + "".join(f"\n## {n}\n{body}" for n, body in entries.items()))


def materialize_workspace(
    workspace: Path,
    inputs: SiteTurnInputs,
    *,
    site: Mapping[str, Any],
    record: Callable[..., Any] | None = None,
) -> dict:
    """Write the whole workspace for one request (the spike's `assemble`, by value).

    Rebuilds every input folder from ``inputs`` and the site files from ``site``; keeps
    plan.md, history.md and fetched/ (the agent's memory). Returns a summary for the run record.
    """

    from lumen_agent.platform_reads import write_seller_knowledge

    workspace.mkdir(parents=True, exist_ok=True)
    for name in REGENERATED:
        path = workspace / name
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    (workspace / "brief.md").write_text(inputs.brief)

    research = workspace / "research"
    research.mkdir()
    labels = claim_labels(inputs.overview + inputs.insights, {str(c.get("claim_id")) for c in inputs.claims})
    if inputs.overview or inputs.insights:
        held = set(inputs.held_claim_ids)
        (research / "overview.md").write_text(research_markdown(f"{inputs.account_name}: overview", inputs.overview, labels, held))
        (research / "insights.md").write_text(research_markdown(f"{inputs.account_name}: insights", inputs.insights, labels, held))
        if labels:
            (research / "claims.md").write_text(claims_markdown(inputs.account_name, labels, inputs.claims))
    else:
        (research / "README.md").write_text(f"# {inputs.account_name}\n\nThere is no written research for this account yet.\n")

    if inputs.platform_reads is not None:
        write_seller_knowledge(workspace, inputs.platform_reads, record=record or (lambda *a, **k: None))
    if inputs.project_files:
        context = workspace / "project-context"
        context.mkdir()
        for item in inputs.project_files:
            name = Path(str(item.get("path") or "")).name
            if name:
                (context / name).write_text(str(item.get("body_text") or ""))

    root = workspace.resolve()
    for relative, text in inputs.catalog.items():
        target = workspace / relative
        if not target.resolve().is_relative_to(root):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    brand_file = workspace / "brand" / "brand.md"
    brand_file.parent.mkdir(parents=True, exist_ok=True)
    existing = brand_file.read_text() if brand_file.exists() else ""
    brand_file.write_text(existing.rstrip() + "\n" + account_logo_section(inputs.account_logos))
    if inputs.agent_sections:
        components = workspace / "catalog" / "seller-components.md"
        components.parent.mkdir(parents=True, exist_ok=True)
        components.write_text(seller_components_markdown({n: s.props_schema for n, s in inputs.agent_sections.items()}))

    shutil.copytree(SITE_DIR / "skills", workspace / "skills")
    shutil.copytree(SITE_DIR / "skills-e5", workspace / "skills-e5")
    (workspace / "fetched").mkdir(exist_ok=True)
    write_site_files(workspace, site)
    if any(page.get("content") for page in site_pages_of(site).values()):
        versions = inputs.site_versions.list_versions(10) if inputs.site_versions is not None else []
        (workspace / "site.md").write_text(site_summary(workspace, turn_brand(inputs.brand, inputs.account_logos), versions))
    return {
        "research_blocks": len(inputs.overview) + len(inputs.insights),
        "claims_labelled": len(labels),
        "people_in_research": len(research_people(inputs.overview + inputs.insights)),
        "clones": len(list((workspace / "catalog" / "clones").glob("*.md"))),
    }
```

(`Iterable` is used by the copied `_statements`; keep the import.)

- [ ] **Step 6: Run the tests.**

Run: RT `test_site_workspace.py`
Expected: PASS. (`test_materialize_writes_the_workspace_the_prompt_describes` checks
`summary["claims_labelled"] == 2`: `WHY_NOW` cites three ids and `CLAIMS` serves two.)

- [ ] **Step 7: Commit.**

```bash
git add subsystems/clue-design/apps/agent_runtime/lumen_agent/site/workspace.py subsystems/clue-design/apps/agent_runtime/tests/site_fixtures.py subsystems/clue-design/apps/agent_runtime/tests/test_site_workspace.py
git commit -m "lumen_agent.site.workspace: the spike's research, claims, site summary and history, by value, with /asset-store files"
```

---
### Task 6: `lumen_agent/site/tools.py` — validate, restore, view, search the web, fetch a page (B3, part 1)

The spike's `PageTools` on production seams: the validator is site-kit's CLI with stored schemas
(Task 3), versions are the document's history (a port), images are workspace blobs read through a
port, `fetch_page` goes through the platform's SSRF/size/time guard, `web_search` is the platform
read. Methods the later tasks add (`render_page`, `generate_image`, `search_assets`,
`write_section`, `view_clone`, `compare_section`) are listed in `TOOL_DESCRIPTIONS` now and join the
tool set the moment their method exists.

**Files:**
- Create: `subsystems/clue-design/apps/agent_runtime/lumen_agent/site/tools.py`
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_site_tools.py` (new)

**Interfaces:**
- Consumes: `lumen_api.site_kit_cli.validate_site_files`, `SiteKitCliError` (Task 3);
  `SiteTurnInputs` (Task 4); `turn_brand`, `write_site_files`, `site_pages`, `read_site_files`
  (Task 5); `lumen_agent.tools.view._image_bytes_block(raw, max_px)`;
  `lumen_agent.tools.web_substrate._fetch_grounded_page(url) -> dict` (keys `text`,
  `http_status`, …); `lumen_ingestion.capture.net.CaptureError`.
- Produces:
  - `class SiteTools(*, workspace: Path, inputs: SiteTurnInputs, base_site: dict, event_sink=None, retry_delay_s: float = 1.0)`
    with attributes `workspace`, `inputs`, `base_site`, `brand` (dict), `sections: dict[str, SiteSection]`,
    `events: list[dict]`, and methods `_validate_raw() -> dict`, `site_unchanged() -> bool`,
    `validate_page() -> str`, `restore_version(version: int) -> str`,
    `view_asset(files: list[str]) -> list[dict] | str`,
    `web_search(query: str, include_domains: list[str] | None = None, num_results: int = 8) -> str`,
    `fetch_page(url: str) -> str`, `_record(kind: str, **data) -> None`, `_asset_by_file() -> dict`
  - `TOOL_DESCRIPTIONS: dict[str, str]` (ordered), `site_tool_set(tools: SiteTools) -> list[StructuredTool]`
  - helper `digest_of_file(file: str) -> str | None`

- [ ] **Step 1: Write the failing tests** `apps/agent_runtime/tests/test_site_tools.py`. The
validator tests are the spike's (`trials/puck-spike/agent/tests/test_tools.py:78-160`), on the
site-kit fixture:

```python
"""The site agent's core tools (Lane B Task 6); validator tests ported from the Puck spike."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lumen_agent.site import tools as site_tools
from lumen_agent.site.tools import SiteTools, site_tool_set
from lumen_agent.site.workspace import materialize_workspace
from lumen_api.site_kit_cli import site_kit_toolchain_missing
from site_fixtures import FakeAssets, FakeVersions, garner_brand, garner_site, inputs_for, png

needs_node = pytest.mark.skipif(site_kit_toolchain_missing() is not None, reason="site-kit toolchain missing")
PHOTO = "f" * 64


def _tools(tmp_path: Path, **overrides) -> SiteTools:
    workspace = tmp_path / "workspace"
    inputs = inputs_for(**overrides)
    site = garner_site()
    materialize_workspace(workspace, inputs, site=site)
    return SiteTools(workspace=workspace, inputs=inputs, base_site=site, retry_delay_s=0)


def _edit(tools: SiteTools, change) -> None:
    page = json.loads((tools.workspace / "page.json").read_text())
    change(page)
    (tools.workspace / "page.json").write_text(json.dumps(page, indent=2))


def _section(page: dict, section_id: str) -> dict:
    return next(item for item in page["content"] if item["props"]["id"] == section_id)


@needs_node
def test_the_phase1_page_validates_clean(tmp_path: Path) -> None:
    assert _tools(tmp_path).validate_page() == "VALID."


@needs_node
def test_schema_errors_pass_through_with_the_allowed_choices(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    _edit(tools, lambda p: _section(p, "proof")["props"].update(surface="green"))
    result = tools.validate_page()
    assert result.startswith("INVALID") and "surface" in result and "brandSubtle" in result


@needs_node
def test_an_unknown_slot_is_refused_listing_the_clone_slots(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    _edit(tools, lambda p: _section(p, "hero")["props"]["slots"].update(subheadline="x"))
    result = tools.validate_page()
    assert "subheadline" in result and "headline" in result and "cta_href" in result


@needs_node
def test_an_image_must_come_from_the_turns_brand(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    _edit(tools, lambda p: p["content"].append({"type": "FeatureSplit", "props": {
        "id": "extra", "surface": "page", "heading": "H", "body": "B", "image": "https://example.com/stock.jpg"}}))
    result = tools.validate_page()
    assert "stock.jpg" in result and "brand/brand.md" in result


@needs_node
def test_the_same_error_three_times_triggers_the_loop_guard(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    _edit(tools, lambda p: _section(p, "proof")["props"].update(surface="green"))
    first, second, third = tools.validate_page(), tools.validate_page(), tools.validate_page()
    assert "third time" not in first and "third time" not in second and "third time" in third


def test_a_validator_that_cannot_run_reads_as_an_invalid_page(tmp_path: Path, monkeypatch) -> None:
    from lumen_api.site_kit_cli import SiteKitCliError

    def broken(*args, **kwargs):
        raise SiteKitCliError("site_kit.toolchain_missing", "node is not on PATH")

    monkeypatch.setattr(site_tools, "validate_site_files", broken)
    result = _tools(tmp_path).validate_page()
    assert result.startswith("INVALID (1 error):") and "validator crashed: node is not on PATH" in result


def test_restore_version_brings_back_a_saved_version_of_every_page(tmp_path: Path) -> None:
    earlier = garner_site()
    del earlier["pages"]["/analysis"]
    tools = _tools(tmp_path, site_versions=FakeVersions(sites={3: earlier}))
    (tools.workspace / "pages" / "extra.json").write_text("{}")
    assert tools.restore_version(3) == "restored version 3 into page.json, shell.json and pages/."
    assert not (tools.workspace / "pages").exists() or not list((tools.workspace / "pages").glob("*.json"))
    assert json.loads((tools.workspace / "page.json").read_text()) == earlier["pages"]["/"]
    assert tools.restore_version(9) == "No version 9. Saved versions: [3]."


def test_view_asset_shows_a_turn_image_and_refuses_others(tmp_path: Path) -> None:
    brand = garner_brand()
    brand["assets"]["asset_photo"] = {"kind": "raster_image", "label": "Hallway", "description": "A school hallway",
                                      "mime": "image/png", "file": f"/asset-store/{PHOTO}", "logo": None}
    tools = _tools(tmp_path, brand=brand, assets=FakeAssets(blobs={PHOTO: ("image/png", png())}))
    blocks = tools.view_asset([f"/asset-store/{PHOTO}", "/asset-store/" + "0" * 64])
    assert blocks[0] == {"type": "text", "text": f"/asset-store/{PHOTO}: A school hallway"}
    assert blocks[1]["type"] == "image"
    assert "not one of this site's images" in blocks[2]["text"]


def test_fetch_page_saves_the_text_as_evidence_through_the_guard(tmp_path: Path, monkeypatch) -> None:
    from lumen_agent.tools import web_substrate

    monkeypatch.setattr(web_substrate, "_fetch_grounded_page",
                        lambda url: {"text": "Saved 12% in year one.", "http_status": 200})
    tools = _tools(tmp_path)
    result = tools.fetch_page("https://garnerhealth.com/story")
    assert result.startswith("Saved to fetched/") and "(status 200)" in result and "Saved 12%" in result
    saved = list((tools.workspace / "fetched").glob("*.md"))
    assert saved and "Source: https://garnerhealth.com/story" in saved[0].read_text()


def test_fetch_page_reports_a_refused_url_without_retrying(tmp_path: Path, monkeypatch) -> None:
    from lumen_agent.tools import web_substrate
    from lumen_ingestion.capture.net import CaptureError

    calls = []

    def refused(url):
        calls.append(url)
        raise CaptureError("LUMI0501", "blocked address")

    monkeypatch.setattr(web_substrate, "_fetch_grounded_page", refused)
    assert _tools(tmp_path).fetch_page("http://127.0.0.1/x").startswith("FETCH FAILED:")
    assert len(calls) == 1


def test_web_search_retries_a_transient_failure(tmp_path: Path) -> None:
    class FlakyReads:
        calls = 0

        def web_search(self, **kwargs):
            FlakyReads.calls += 1
            if FlakyReads.calls == 1:
                raise RuntimeError("timeout")
            return {"results": [{"title": "Aon study", "url": "https://garnerhealth.com/blog/aon"}]}

        def seller_knowledge(self):
            raise RuntimeError("no pin")

    tools = _tools(tmp_path, platform_reads=FlakyReads())
    assert "Aon study" in tools.web_search("Aon study", include_domains=["garnerhealth.com"])
    assert FlakyReads.calls == 2


def test_the_tool_set_holds_only_the_methods_that_exist_and_events_carry_no_operations(tmp_path: Path) -> None:
    received: list[tuple[str, dict]] = []
    tools = _tools(tmp_path)
    tools.event_sink = lambda event_type, data: received.append((event_type, data))
    names = [tool.name for tool in site_tool_set(tools)]
    assert {"validate_page", "restore_version", "view_asset", "web_search", "fetch_page"} <= set(names)
    assert all(name in site_tools.TOOL_DESCRIPTIONS for name in names)
    tools._record("valid")
    assert received == [("site_valid", {})]
    assert all("operations" not in data for _, data in received)
```

- [ ] **Step 2: Run them and watch them fail.**

Run: RT `test_site_tools.py`
Expected: FAIL at import — `ModuleNotFoundError: No module named 'lumen_agent.site.tools'`.

- [ ] **Step 3: Confirm T6a–T6e and T7 were approved** (Task 0). Use the founder's words where
they differ.

- [ ] **Step 4: Write `site/tools.py`:**

```python
"""The site agent's tools (Lane B): the Puck spike's PageTools on the platform's seams.

Plain methods on one object bound to the request's workspace; the harness wraps them as LangChain
tools. Each returns text (or text and image blocks) the agent can act on, never a raised exception.

- validate_page    site-kit's validator (contracts only), agent sections by stored schema
- render_page      Lane A's hardened renderer + screenshots at 1440 and 375 (Task 9)
- restore_version  the site as it was at a saved document version
- view_asset       up to four of this turn's images, with their descriptions
- search_assets    the workspace's images by words and by look (Task 11)
- generate_image   a new image, stored as an AI-generated library asset (Task 10)
- web_search       the platform's open-web search, retried on a transient failure
- fetch_page       a public page through the platform's guard, saved under fetched/
- write_section, view_clone, compare_section   agent sections and rebuilding a clone (Tasks 15, 18)
"""

from __future__ import annotations

import copy
import hashlib
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from lumen_api.site_kit_cli import SiteKitCliError, validate_site_files

from .inputs import SiteSection, SiteTurnInputs
from .workspace import turn_brand, write_site_files

FETCH_LIMIT = 12_000
VIEW_ASSET_MAX = 4
VIEW_ASSET_PX = 1024
RETRIES = 2
LOOP_GUARD_AT = 3
_ASSET_FILE = re.compile(r"^/asset-store/([0-9a-f]{64})$")

#: Tool name -> the description the model reads, in the order the model sees them (the spike's
#: order, `search_assets` after `view_asset`). A name joins the tool set when its method exists.
TOOL_DESCRIPTIONS: dict[str, str] = {
    "write_section": (
        "Write a new section as one React file (see the writing-a-section skill). It is checked for "
        "brand tokens and types; if it passes, place it in a page by its name."
    ),
    "view_clone": (
        "Look at one of the seller's captured sections on its own: a desktop (1440 wide) and a "
        "mobile (375 wide) picture, plus its catalog card (words, images, links)."
    ),
    "compare_section": (
        "Show a seller's section (fragment_id) and your component (name, filled with props) side by "
        "side at 1440 and 375 wide, with the share of the area that differs, both heights, and the "
        "original's words that yours is missing."
    ),
    "validate_page": (
        "Check page.json and shell.json against the components, the catalog, the brand and the "
        "evidence. Returns VALID or INVALID with each error and its fix."
    ),
    "render_page": (
        "Render the site and return a desktop (1440 wide) and a mobile (375 wide) full-page "
        "screenshot of one page, with facts about broken images and overflow. route "
        "is \"/\" for page.json or \"/<name>\" for pages/<name>.json. Refuses while the site is invalid."
    ),
    "restore_version": (
        "Bring back the site as it was at an earlier saved version (site.md lists them) into "
        "page.json, shell.json and pages/."
    ),
    "view_asset": (
        "Look at up to four images (files from brand/brand.md, images you generated, or images "
        "search_assets found), each with its description, before you choose one for a section."
    ),
    "search_assets": (
        "Search the seller's images by what they show and how they look. Write what you need in "
        "plain words, for example \"calm classroom, morning light\" or \"product dashboard "
        "screenshot\". Returns the best matches first (up to limit, 1 to 20), each with its file, "
        "type, title and a one-line description. Look at one with view_asset before you use it. "
        "kind narrows to image or logo."
    ),
    "generate_image": (
        "Make a new image for this site in the brand's style (see the images-and-logos skill). "
        "prompt says what it shows; aspect_ratio is the section's shape, such as \"16:9\", \"4:3\" or "
        "\"1:1\"; style_references are one to three of the brand's own photos from brand/brand.md. "
        "Returns the image's path and shows it to you."
    ),
    "web_search": (
        "Search the web. Set include_domains to the seller's domain to find its own published case "
        "studies and customer stories."
    ),
    "fetch_page": (
        "Open a page and save its text under fetched/ as evidence. Use it before you put a number or "
        "a quote from that page on the page."
    ),
}


def digest_of_file(file: str) -> str | None:
    """The sha256 an /asset-store/<sha256> file names, or None."""

    match = _ASSET_FILE.match(file or "")
    return match.group(1) if match else None


class SiteTools:
    def __init__(
        self,
        *,
        workspace: Path,
        inputs: SiteTurnInputs,
        base_site: dict,
        event_sink: Callable[[str, dict], Any] | None = None,
        retry_delay_s: float = 1.0,
    ) -> None:
        self.workspace = Path(workspace)
        self.inputs = inputs
        self.base_site = copy.deepcopy(base_site)
        self.event_sink = event_sink
        self.retry_delay_s = retry_delay_s
        #: The brand this turn validates with: the stored brand, the account's logos, and every
        #: image the turn generates or finds (Contract 1: a blob of this workspace).
        self.brand = turn_brand(inputs.brand, inputs.account_logos)
        #: Sections the pages may place: the workspace's, plus any written this turn.
        self.sections: dict[str, SiteSection] = dict(inputs.agent_sections)
        self._seen: Counter[str] = Counter()
        self._initial_files = self._site_files()
        self.events: list[dict] = []

    # --- helpers ---------------------------------------------------------------------------

    def _record(self, kind: str, **data: Any) -> None:
        self.events.append({"kind": kind, "at": time.time(), **data})
        if self.event_sink is not None:
            try:
                self.event_sink(f"site_{kind}", {key: value for key, value in data.items() if key != "operations"})
            except Exception:  # noqa: BLE001 - progress events are best-effort
                pass

    def _retry(self, operation: Callable[[], Any], what: str) -> Any:
        last: Exception | None = None
        for attempt in range(RETRIES + 1):
            try:
                return operation()
            except Exception as error:  # transient failures are retried, then reported
                last = error
                self._record("retry", what=what, attempt=attempt + 1, error=str(error)[:200])
                if attempt < RETRIES:
                    time.sleep(self.retry_delay_s * (attempt + 1))
        raise RuntimeError(f"{what} failed after {RETRIES + 1} attempts: {last}")

    def _site_files(self) -> dict:
        """The site's files as the validator reads them: page text by route, and shell.json."""

        pages: dict[str, str] = {}
        if (self.workspace / "page.json").exists():
            pages["/"] = (self.workspace / "page.json").read_text()
        folder = self.workspace / "pages"
        for file in sorted(folder.glob("*.json")) if folder.exists() else []:
            pages[f"/{file.stem}"] = file.read_text()
        shell = self.workspace / "shell.json"
        return {"pages": pages, "shell": shell.read_text() if shell.exists() else None}

    def site_unchanged(self) -> bool:
        """True while the agent has not touched the site's files this request."""

        return self._site_files() == self._initial_files

    def _asset_by_file(self) -> dict[str, dict]:
        return {
            asset["file"]: asset
            for asset in (self.brand.get("assets") or {}).values()
            if isinstance(asset, dict) and asset.get("file")
        }

    # --- validate ------------------------------------------------------------------------------

    def _validate_raw(self) -> dict:
        try:
            return validate_site_files(
                self._site_files(), self.brand, {name: s.props_schema for name, s in self.sections.items()}
            )
        except SiteKitCliError as error:
            return {"valid": False, "errors": [f"validator crashed: {error.detail[-500:]}"]}

    def validate_page(self) -> str:
        """Check page.json and shell.json. Returns VALID or INVALID with each error and its fix."""

        result = self._validate_raw()
        if result["valid"]:
            self._seen.clear()
            self._record("valid")
            return "VALID."
        errors = list(result["errors"])
        lines = [f"INVALID ({len(errors)} error{'s' if len(errors) != 1 else ''}):"]
        repeated = []
        for error in errors:
            self._seen[error] += 1
            lines.append(f"- {error}")
            if self._seen[error] == LOOP_GUARD_AT:
                repeated.append(error)
        if repeated:
            self._record("loop_guard", errors=repeated)
            lines.append(
                "\nNOTE: this has failed for the third time: "
                + "; ".join(repeated)
                + ". Try a different approach (another section or slot), or leave that part out and"
                " record why in plan.md."
            )
        self._record("invalid", errors=errors)
        lines.append("\nFix these in page.json / shell.json, then call validate_page again.")
        return "\n".join(lines)

    def restore_version(self, version: int) -> str:
        """Bring back the site as it was at a saved version into page.json, shell.json and pages/."""

        port = self.inputs.site_versions
        snapshot = port.site_at(int(version)) if port is not None else None
        if snapshot is None:
            saved = sorted(item["version"] for item in (port.list_versions(50) if port is not None else []))
            return f"No version {version}. Saved versions: {saved or 'none yet'}."
        write_site_files(self.workspace, snapshot)
        self._record("restore", version=int(version))
        return f"restored version {version} into page.json, shell.json and pages/."

    # --- images --------------------------------------------------------------------------------

    def view_asset(self, files: list[str]) -> list[dict] | str:
        """Look at up to four of this site's images, with their descriptions."""

        from lumen_agent.tools.view import _image_bytes_block  # the platform's provider-safe image block

        if not files:
            return "Give one to four image files from brand/brand.md or ones you generated."
        known = self._asset_by_file()
        blocks: list[dict] = []
        for file in files[:VIEW_ASSET_MAX]:
            asset = known.get(file)
            digest = digest_of_file(file)
            if asset is None or digest is None or self.inputs.assets is None:
                blocks.append({"type": "text", "text": f"{file}: not one of this site's images; use a file from "
                               "brand/brand.md or one you generated"})
                continue
            try:
                mime, data = self.inputs.assets.read(digest)
            except Exception as error:  # an unreadable file is an answer, not a crash
                blocks.append({"type": "text", "text": f"{file}: could not be opened ({error})"})
                continue
            if (mime or "").startswith("video/"):
                blocks.append({"type": "text", "text": f"{file}: a video; it cannot be shown as a picture"})
                continue
            try:
                image = _image_bytes_block(data, max_px=VIEW_ASSET_PX)
            except Exception as error:  # an unreadable file is an answer, not a crash
                blocks.append({"type": "text", "text": f"{file}: could not be opened ({error})"})
                continue
            description = asset.get("description") or asset.get("label") or ""
            blocks.append({"type": "text", "text": f"{file}" + (f": {description[:300]}" if description else "")})
            blocks.append(image)
        self._record("view_asset", files=list(files[:VIEW_ASSET_MAX]))
        if files[VIEW_ASSET_MAX:]:
            blocks.append({"type": "text", "text": f"Showed the first {VIEW_ASSET_MAX}; ask again for the rest."})
        return blocks

    # --- research ------------------------------------------------------------------------------

    def fetch_page(self, url: str) -> str:
        """Open a page, save its text under fetched/ as evidence, and return the text."""

        from lumen_agent.tools import web_substrate
        from lumen_ingestion.capture.net import CaptureError

        def get() -> dict:
            return web_substrate._fetch_grounded_page(url)

        try:
            page = get()
        except CaptureError as error:  # a refused or failed URL is deterministic: no retry
            return f"FETCH FAILED: {error}"
        except Exception:  # noqa: BLE001 - a network blip is retried, then reported
            try:
                page = self._retry(get, f"fetch {url}")
            except RuntimeError as error:
                return f"FETCH FAILED: {error}"
        text = str(page.get("text") or "")
        status = page.get("http_status")
        name = re.sub(r"[^a-z0-9]+", "-", url.lower()).strip("-")[:80]
        digest = hashlib.sha1(url.encode()).hexdigest()[:8]
        saved = self.workspace / "fetched" / f"{name}-{digest}.md"
        saved.parent.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        saved.write_text(f"Source: {url}\nFetched: {stamp}\nStatus: {status}\n\n{text}\n")
        self._record("fetch", url=url, status=status)
        return f"Saved to fetched/{saved.name} (status {status}).\n\n{text[:FETCH_LIMIT]}"

    def web_search(self, query: str, include_domains: list[str] | None = None, num_results: int = 8) -> str:
        """The platform's web search. Set include_domains to the seller's domain for its case studies."""

        import json

        reads = self.inputs.platform_reads
        if reads is None:
            return "SEARCH UNAVAILABLE in this run."
        try:
            result = self._retry(
                lambda: reads.web_search(query=query, num_results=num_results, include_domains=include_domains),
                f"search {query!r}",
            )
        except RuntimeError as error:
            return f"SEARCH FAILED: {error}"
        self._record("search", query=query)
        return json.dumps(result, ensure_ascii=False)[:FETCH_LIMIT]


def site_tool_set(tools: SiteTools) -> list:
    """The tools the model sees: every described tool whose method exists, in the described order."""

    from langchain_core.tools import StructuredTool

    return [
        StructuredTool.from_function(getattr(tools, name), name=name, description=description)
        for name, description in TOOL_DESCRIPTIONS.items()
        if callable(getattr(tools, name, None))
    ]
```

- [ ] **Step 5: Run the tests.**

Run: RT `test_site_tools.py`
Expected: PASS (the `needs_node` tests skip only where the toolchain is absent).

- [ ] **Step 6: Commit.**

```bash
git add subsystems/clue-design/apps/agent_runtime/lumen_agent/site/tools.py subsystems/clue-design/apps/agent_runtime/tests/test_site_tools.py
git commit -m "lumen_agent.site.tools: validate (site-kit, stored schemas), restore a saved version, view, search, fetch through the guard"
```

---

### Task 7: `lumen_agent/site/harness.py` — the agent and one request (B1)

The spike's `create_agent` composition, with the platform's model, compaction, cancellation,
receipts, checkpoint seam and the founder's turn limits.

**Files:**
- Create: `subsystems/clue-design/apps/agent_runtime/lumen_agent/site/harness.py`
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_site_harness.py` (new)

**Interfaces:**
- Consumes: `SiteTools`, `site_tool_set` (Task 6); `materialize_workspace`, `read_site_files`
  (Task 5); `lumen_agent.harness._instrument(runtime_config, tools, model_id, role, budget=None, *, cancel_probe=None)`;
  `clue_agents.compaction.build_compaction_middleware(model, backend, settings, *, history_under_work)`;
  `clue_agents.compaction_config.compaction_for(model_id) -> CompactionSettings`;
  `lumen_agent.usage_collector.turn_collector(callbacks) -> (ModelCallCollector, list)`;
  `lumen_agent.checkpoint.invoke_turn_graph(agent, initial_state, *, invoke_config, checkpointer, thread_id, run_id)`,
  `RUN_ID_KEY`; `lumen_agent.cancellation.TurnCancelled`, `CANCELLED_STOP_REASON`.
- Produces:
  - `TurnLimitsConfig(max_rounds: int = 100, max_calls_per_round: int = 50, max_seconds: float = 1800.0)` with `.recursion_limit`
  - middleware classes `SupersededResults`, `OrderedToolCalls`, `WholeFileReads`, `FinishGuard(tools)`,
    `TurnLimits(*, max_rounds, max_seconds, clock=time.monotonic)`, `RoundShape(*, limit)`;
    `clear_superseded_results(messages) -> list`
  - `system_prompt_with_skills(workspace: Path, *, allow_new_sections: bool = True) -> str`
  - `build_site_agent(tools, *, model, model_id: str, checkpointer=None, limits=TurnLimitsConfig(), compaction=None, allow_new_sections=True) -> tuple[agent, FinishGuard, TurnLimits]`
  - `SiteTurnResult(status: str, summary: str, site: dict, stop_reason: str | None, errors: list[str], model_calls: list[dict])`
  - `run_site_turn(prompt, *, config, inputs, workspace, site, run_id, checkpointer=None, thread_id=None, cancel_requested=None, callbacks=None, event_sink=None, limits=TurnLimitsConfig(), model=None) -> SiteTurnResult`
  - text constants `ROUND_LIMIT_NOTE`, `TIME_LIMIT_NOTE`, `ROUND_REFUSAL`, `CANCELLED_SUMMARY`,
    `CRASHED_SUMMARY`, `INVALID_SUMMARY` (T12a–f)

- [ ] **Step 1: Write the failing tests** `apps/agent_runtime/tests/test_site_harness.py`. The
clearing tests are the spike's (`trials/puck-spike/agent/tests/test_harness.py:142-266`) with the
import changed; the composition tests adapt the spike's to a workspace that already holds
`page.json` (a stored site always has a home page, and deepagents' `write_file` refuses to
overwrite, so changes are edits or new files):

```python
"""The site agent's harness (Lane B Task 7), driven by a scripted model (no model spend)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from lumen_agent.config import AgentRuntimeConfig
from lumen_agent.site import harness
from lumen_agent.site.harness import (
    CANCELLED_SUMMARY,
    CLEAR_FROM_TOKENS,
    ROUND_LIMIT_NOTE,
    SupersededResults,
    TurnLimitsConfig,
    build_site_agent,
    clear_superseded_results,
    run_site_turn,
    system_prompt_with_skills,
)
from lumen_agent.site.tools import SiteTools
from lumen_agent.site.workspace import materialize_workspace
from lumen_api.site_kit_cli import site_kit_toolchain_missing
from site_fixtures import ScriptedModel, call, garner_site, inputs_for, read_fixture

needs_node = pytest.mark.skipif(site_kit_toolchain_missing() is not None, reason="site-kit toolchain missing")
SITE = read_fixture("garner-syracuse.json")


def _empty_site() -> dict:
    return {"id": "doc_new", "title": "New", "theme": {}, "pages": {"/": {"root": {"props": {"title": "New"}}, "content": []}},
            "shell": None, "agent_sections": {}}


def _run(tmp_path: Path, script: list, *, site: dict | None = None, **kwargs):
    return run_site_turn(
        "build", config=AgentRuntimeConfig.from_env(), inputs=inputs_for(), workspace=tmp_path / "workspace",
        site=site or garner_site(), run_id="run_test", model=ScriptedModel(messages=iter(script)), **kwargs,
    )


def _agent(tmp_path: Path, script: list, *, site: dict | None = None, limits: TurnLimitsConfig = TurnLimitsConfig()):
    workspace = tmp_path / "workspace"
    inputs = inputs_for()
    site = site or garner_site()
    materialize_workspace(workspace, inputs, site=site)
    tools = SiteTools(workspace=workspace, inputs=inputs, base_site=site, retry_delay_s=0)
    agent, guard, limits_mw = build_site_agent(
        tools, model=ScriptedModel(messages=iter(script)), model_id="openai:x-ai/grok-4.6", limits=limits)
    return agent, guard, limits_mw, tools


def _invoke(agent) -> list:
    state = agent.invoke({"messages": [{"role": "user", "content": "build"}]},
                         {"configurable": {"thread_id": "t"}, "recursion_limit": 200})
    return state["messages"]


def _results(messages: list) -> dict[str, str]:
    return {m.tool_call_id: str(m.content) for m in messages if isinstance(m, ToolMessage)}


@needs_node
def test_a_scripted_build_reads_a_skill_edits_the_page_and_validates(tmp_path: Path) -> None:
    content = json.dumps(SITE["pages"]["/"]["content"])
    agent, guard, _, _ = _agent(tmp_path, [
        AIMessage(content="", tool_calls=[call("read_file", {"file_path": "/skills/building-with-puck/SKILL.md", "limit": 1000}, 1)]),
        AIMessage(content="", tool_calls=[
            call("edit_file", {"file_path": "/page.json", "old_string": '"content": []', "new_string": f'"content": {content}'}, 2),
            call("write_file", {"file_path": "/shell.json", "content": json.dumps(SITE["shell"])}, 3),
            call("write_file", {"file_path": "/pages/analysis.json", "content": json.dumps(SITE["pages"]["/analysis"])}, 4),
            call("validate_page", {}, 5),
        ]),
        AIMessage(content="Built the page."),
    ], site=_empty_site())
    results = _results(_invoke(agent))
    assert "Reuse first" in results["call_1"]
    assert results["call_5"] == "VALID.", results["call_5"]
    assert guard.status == "completed"


def test_the_agent_cannot_write_its_inputs(tmp_path: Path) -> None:
    agent, _, _, tools = _agent(tmp_path, [
        AIMessage(content="", tool_calls=[call("edit_file", {"file_path": "/brief.md", "old_string": "For", "new_string": "x"}, 1)]),
        AIMessage(content="", tool_calls=[call("write_file", {"file_path": "/skills/new/SKILL.md", "content": "x"}, 2)]),
        AIMessage(content="Done."),
    ])
    results = _results(_invoke(agent))
    assert (tools.workspace / "brief.md").read_text().startswith("For")
    assert not (tools.workspace / "skills" / "new").exists()
    assert "denied" in results["call_1"].lower() or "permission" in results["call_1"].lower()


@needs_node
def test_tool_calls_run_in_the_order_the_model_wrote_them(tmp_path: Path) -> None:
    broken = {"root": {"props": {"title": "x"}}, "content": [{"type": "CtaBand", "props": {
        "id": "cta", "surface": "green", "heading": "H", "body": "B", "buttonLabel": "Go", "buttonHref": "https://x.example"}}]}
    agent, _, _, _ = _agent(tmp_path, [
        AIMessage(content="", tool_calls=[
            call("write_file", {"file_path": "/shell.json", "content": json.dumps(SITE["shell"])}, 1),
            call("write_file", {"file_path": "/pages/analysis.json", "content": json.dumps(broken)}, 2),
            call("validate_page", {}, 3),
        ]),
        AIMessage(content="Done."), AIMessage(content="Done."), AIMessage(content="Done."),
    ], site=_empty_site())
    result = _results(_invoke(agent))["call_3"]
    assert "content.0(cta).surface" in result and "does not exist" not in result


@needs_node
def test_a_turn_cannot_finish_on_an_invalid_page(tmp_path: Path) -> None:
    broken = {"root": {"props": {"title": "x"}}, "content": [{"type": "NoSuchSection", "props": {"id": "a"}}]}
    agent, guard, _, _ = _agent(tmp_path, [
        AIMessage(content="", tool_calls=[call("write_file", {"file_path": "/pages/broken.json", "content": json.dumps(broken)}, 1)]),
        AIMessage(content="All done."), AIMessage(content="All done."),
        AIMessage(content="All done, but the page is not finished."),
    ], site=_empty_site())
    messages = _invoke(agent)
    reminders = [m for m in messages if isinstance(m, HumanMessage) and "still invalid" in m.content]
    assert len(reminders) == 2 and "shell.json: does not exist yet" in reminders[0].content
    assert guard.status == "completed with errors"


def test_a_turn_that_leaves_the_site_alone_is_not_pushed(tmp_path: Path) -> None:
    """A turn that only builds a component (or only answers) is not pushed to make a page."""

    agent, guard, _, _ = _agent(tmp_path, [AIMessage(content="Rebuilt the hero as a component.")], site=_empty_site())
    messages = _invoke(agent)
    assert not [m for m in messages if isinstance(m, HumanMessage) and "still invalid" in m.content]
    assert guard.status == "completed (site unchanged)"


def test_the_round_limit_ends_a_runaway_request(tmp_path: Path) -> None:
    script = [AIMessage(content="", tool_calls=[call("ls", {"path": "/"}, n)]) for n in range(10)]
    agent, _, limits_mw, _ = _agent(tmp_path, script, limits=TurnLimitsConfig(max_rounds=3))
    messages = _invoke(agent)
    assert limits_mw.rounds == 3 and limits_mw.stop_reason == "round_limit"
    assert messages[-1].content == ROUND_LIMIT_NOTE.format(limit=3)


def test_one_response_runs_at_most_its_per_round_limit(tmp_path: Path) -> None:
    agent, _, _, _ = _agent(tmp_path, [
        AIMessage(content="", tool_calls=[call("ls", {"path": "/"}, 1), call("ls", {"path": "/"}, 2)]),
        AIMessage(content="Done."),
    ], limits=TurnLimitsConfig(max_calls_per_round=1))
    results = _results(_invoke(agent))
    assert not results["call_1"].startswith("Not run")
    assert results["call_2"].startswith("Not run: this was call 2 in one response, and only the first 1 run.")


def test_the_time_limit_stops_before_a_model_call(tmp_path: Path) -> None:
    result = _run(tmp_path, [], limits=TurnLimitsConfig(max_seconds=0.0))
    assert result.model_calls == [] and result.stop_reason == "time_limit"
    assert result.status == "applied" and result.site == garner_site()  # nothing changed, nothing lost


@needs_node
def test_a_valid_change_stands_when_the_round_limit_stops_the_request(tmp_path: Path) -> None:
    """Open question 3 (a): valid work done before the limit is saved, and the stop is reported."""

    result = _run(tmp_path, [
        AIMessage(content="", tool_calls=[call("edit_file", {
            "file_path": "/page.json", "old_string": "Lower medical spend for SCSD",
            "new_string": "Lower medical spend for Syracuse"}, 1)]),
        AIMessage(content="", tool_calls=[call("ls", {"path": "/"}, 2)]),
        AIMessage(content="", tool_calls=[call("ls", {"path": "/"}, 3)]),
    ], limits=TurnLimitsConfig(max_rounds=2))
    assert result.status == "applied" and result.stop_reason == "round_limit"
    assert "Lower medical spend for Syracuse" in json.dumps(result.site["pages"]["/"])


def test_a_cancelled_request_never_calls_the_model(tmp_path: Path) -> None:
    result = _run(tmp_path, [], cancel_requested=lambda: True)
    assert result.status == "failed" and result.stop_reason == "cancelled_by_request"
    assert result.summary == CANCELLED_SUMMARY and result.model_calls == []


def test_the_requests_model_calls_ride_back_and_an_untouched_site_is_returned_as_stored(tmp_path: Path) -> None:
    result = _run(tmp_path, [
        AIMessage(content="", tool_calls=[call("ls", {"path": "/"}, 1)]),
        AIMessage(content="Looked around; nothing to change."),
    ])
    assert len(result.model_calls) == 2
    assert result.status == "applied" and result.summary == "Looked around; nothing to change."
    assert result.site == garner_site()


def test_compaction_is_the_platforms_sized_from_the_model(tmp_path: Path, monkeypatch) -> None:
    from clue_agents import compaction_config
    from clue_agents.compaction import CompactionSettings

    asked: list[str] = []

    def recording(model_id: str) -> CompactionSettings:
        asked.append(model_id)
        return CompactionSettings.fallback()

    monkeypatch.setattr(compaction_config, "compaction_for", recording)
    _agent(tmp_path, [AIMessage(content="ok")])
    assert asked == ["openai:x-ai/grok-4.6"]


def _ai(calls: list[dict]) -> AIMessage:
    return AIMessage(content="", tool_calls=calls)


def _result(name: str, n: str, content) -> ToolMessage:
    return ToolMessage(name=name, tool_call_id=n, content=content)


def _render(n: str) -> ToolMessage:
    return _result("render_page", n, [{"type": "text", "text": f"1440 wide: render {n}"},
                                      {"type": "image", "source_type": "base64", "mime_type": "image/png", "data": "AAAA"}])


def test_only_the_newest_render_keeps_its_screenshots() -> None:
    messages = [HumanMessage(content="build"), _ai([call("render_page", {}, 1)]), _render("call_1"),
                _ai([call("render_page", {}, 2)]), _render("call_2")]
    cleared = clear_superseded_results(messages)
    assert isinstance(cleared[2].content, str) and "render call_1" in cleared[2].content
    assert cleared[4] is messages[4]
    assert clear_superseded_results(cleared)[2].content == cleared[2].content


def test_clearing_waits_until_the_session_passes_the_threshold() -> None:
    messages = [HumanMessage(content="build"), _ai([call("render_page", {}, 1)]), _render("call_1"),
                _ai([call("render_page", {}, 2)]), _render("call_2")]
    small = list(messages)
    SupersededResults().apply(small, count_tokens=lambda m: CLEAR_FROM_TOKENS - 1)
    assert small[2].content == messages[2].content
    large = list(messages)
    SupersededResults().apply(large, count_tokens=lambda m: CLEAR_FROM_TOKENS)
    assert isinstance(large[2].content, str) and "cleared" in large[2].content


def test_the_skills_ride_in_the_system_prompt_with_the_e5_skills_by_default(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    materialize_workspace(workspace, inputs_for(), site=garner_site())
    prompt = system_prompt_with_skills(workspace)
    assert "## Your skills" in prompt and "### Skill: building-with-puck" in prompt and "Reuse first" in prompt
    assert "### Skill: images-and-logos" in prompt and "Generate only a scene or a mood" in prompt
    assert "### Skill: writing-a-section" in prompt and "### Skill: rebuilding-a-section" in prompt
    assert "### Skill: writing-a-section" not in system_prompt_with_skills(workspace, allow_new_sections=False)


def test_the_prompt_names_the_claims_file_only_when_the_workspace_has_one(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    materialize_workspace(workspace, inputs_for(), site=garner_site())
    without = system_prompt_with_skills(workspace)
    assert "research/claims.md" not in without and "[c4, c9]" not in without
    (workspace / "research" / "claims.md").write_text("# Claims\n")
    with_claims = system_prompt_with_skills(workspace)
    assert "`research/claims.md` lists each claim with what it" in with_claims
    assert "check its claim in `research/claims.md`" in with_claims
```

Port the spike's remaining clearing tests unchanged (only the import line differs):
`test_only_the_newest_comparison_keeps_its_pictures` (`test_harness.py:167-179`),
`test_planning_reads_clear_once_the_plan_is_written_and_building_starts` (`:182-196`) and
`test_an_old_read_of_a_site_file_clears_only_after_a_newer_render` (`:199-207`), and add the
whole-file read:

```python
def test_a_read_without_a_limit_gets_the_whole_file(tmp_path: Path) -> None:
    agent, _, _, tools = _agent(tmp_path, [
        AIMessage(content="", tool_calls=[call("read_file", {"file_path": "/research/long.md"}, 1)]),
        AIMessage(content="Done."),
    ])
    (tools.workspace / "research" / "long.md").write_text("\n".join(f"line {n}" for n in range(1, 251)))
    assert "line 250" in _results(_invoke(agent))["call_1"]
```

- [ ] **Step 2: Run them and watch them fail.**

Run: RT `test_site_harness.py`
Expected: FAIL at import — `ModuleNotFoundError: No module named 'lumen_agent.site.harness'`.

- [ ] **Step 3: Confirm T12a–T12f were approved** (Task 0).

- [ ] **Step 4: Write `site/harness.py`.** Create the file with the docstring, imports and
constants below; then **copy verbatim** from `trials/puck-spike/agent/trials_puck_agent/harness.py`:
the clearing block (`:56-171`: `_PLANNING_PREFIXES`, `_PLANNING_TOOLS`, `_SITE_FILES`,
`_WRITERS`, `_calls_by_id`, `_is_site_file`, `_stub`, `clear_superseded_results`,
`SupersededResults`), `OrderedToolCalls` (`:176-201`), `WholeFileReads` (`:242-250`), and the
prompt block (`:388-411`: `CLAIMS_RESEARCH_LINE`, `PLAIN_RESEARCH_LINE`, `CLAIMS_RULE`,
`_base_prompt`), changing `_base_prompt`'s `AGENT_DIR / "system_prompt.md"` to
`SITE_DIR / "system_prompt.md"`. Then add:

```python
"""The site agent's harness (Lane B): the Puck spike's lean agent on the platform's seams.

LangChain's `create_agent` with the deepagents middleware the spike chose — file tools over the
request's workspace with writes denied on its inputs, patched tool calls, the spike's context
clearing (from 60k tokens) and ordered tool calls, whole-file reads, and the finish guard (a
request cannot end on an invalid page; after two reminders it ends with errors) — plus:
- the model through `lumen_agent.harness._instrument` (the governed gateway, role
  `design_site`, trace capture and the cancellation probe);
- compaction through `clue_agents.compaction`, sized by `compaction_for` (the scene harness's
  way), replacing the spike's fixed 300k/60k summariser;
- the founder's turn limits (100 model rounds, 50 tool calls per round, 30 minutes), replacing the
  spike's 40-call stop; no total-call or zero-yield caps;
- receipts through `usage_collector.turn_collector`; the invoke through
  `checkpoint.invoke_turn_graph` on a fresh thread per request (thread id = the run id).
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from ..config import AgentRuntimeConfig
from .inputs import SiteTurnInputs
from .tools import SiteTools, site_tool_set
from .workspace import SITE_DIR, materialize_workspace, read_site_files

#: Context clearing starts only once a session passes this many tokens (founder, 2026-10-08).
CLEAR_FROM_TOKENS = 60_000
FINISH_REMINDERS = 2
READ_ONLY = [
    "/brief.md", "/site.md", "/history.md", "/skills/**", "/skills-e5/**", "/catalog/**", "/brand/**",
    "/research/**", "/seller/**", "/fetched/**", "/project-context/**", "/work/**",
]
#: T12a–T12f (founder-approved, Task 0).
ROUND_LIMIT_NOTE = "Stopped: this request reached its limit of {limit} model calls."
TIME_LIMIT_NOTE = "Stopped: this request reached its limit of {minutes} minutes."
ROUND_REFUSAL = "Not run: this was call {n} in one response, and only the first {limit} run. Make it again in your next step."
CANCELLED_SUMMARY = "Stopped at your request. Nothing was saved."
CRASHED_SUMMARY = "The website turn stopped because of an error, and nothing was saved."
INVALID_SUMMARY = "The page was still invalid, so nothing was saved: {error}"
```

```python
class FinishGuard(AgentMiddleware):
    """A request cannot end on an invalid page (the spike's RunRecorder.after_model).

    A request that never touched the site's files (it only wrote a section, or only answered) is
    not checked. After two reminders the request ends "completed with errors".
    """

    def __init__(self, tools: SiteTools) -> None:
        super().__init__()
        self.tools = tools
        self.reminders: list[str] = []
        self.errors: list[str] = []
        self.status = "running"

    @hook_config(can_jump_to=["model"])
    def after_model(self, state, runtime):
        latest = state["messages"][-1]
        if not isinstance(latest, AIMessage) or latest.tool_calls or self.status != "running":
            return None
        if self.tools.site_unchanged():
            self.status = "completed (site unchanged)"
            return None
        check = self.tools._validate_raw()
        if check["valid"]:
            self.status = "completed"
            self.errors = []
            return None
        self.errors = list(check["errors"])
        if len(self.reminders) >= FINISH_REMINDERS:
            self.status = "completed with errors"
            return None
        errors = "\n".join(f"- {error}" for error in check["errors"])
        self.reminders.append(errors)
        return {
            "messages": [HumanMessage(content=(
                "The page is still invalid, so this turn cannot finish yet:\n" + errors
                + "\nFix these and validate again. If one cannot be fixed, leave that part out and "
                "say why in plan.md and in your report."
            ))],
            "jump_to": "model",
        }


class TurnLimits(AgentMiddleware):
    """The founder's limits on one request (2026-09-08): model rounds and wall clock."""

    def __init__(self, *, max_rounds: int, max_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        super().__init__()
        self.max_rounds = max_rounds
        self.max_seconds = max_seconds
        self._clock = clock
        self.started = clock()
        self.rounds = 0
        self.stop_reason: str | None = None

    @hook_config(can_jump_to=["end"])
    def before_model(self, state, runtime):
        if self.rounds >= self.max_rounds:
            self.stop_reason = "round_limit"
            return {"messages": [AIMessage(content=ROUND_LIMIT_NOTE.format(limit=self.max_rounds))], "jump_to": "end"}
        if self._clock() - self.started >= self.max_seconds:
            self.stop_reason = "time_limit"
            minutes = round(self.max_seconds / 60)
            return {"messages": [AIMessage(content=TIME_LIMIT_NOTE.format(minutes=minutes))], "jump_to": "end"}
        self.rounds += 1
        return None


class RoundShape(AgentMiddleware):
    """At most ``limit`` tool calls of one response run; the rest are refused, each with a result
    (the ARV2 account agent's rule, `clue_api/arv2/account_research_agent.py:293-347`)."""

    def __init__(self, *, limit: int) -> None:
        super().__init__()
        self.limit = limit

    def wrap_tool_call(self, request, handler):
        call = request.tool_call
        messages = (request.state or {}).get("messages", [])
        latest = next((m for m in reversed(messages) if isinstance(m, AIMessage) and m.tool_calls), None)
        ids = [str(item.get("id") or "") for item in (latest.tool_calls if latest else [])]
        position = ids.index(str(call.get("id"))) if str(call.get("id")) in ids else None
        if position is not None and position >= self.limit:
            return ToolMessage(
                content=ROUND_REFUSAL.format(n=position + 1, limit=self.limit),
                tool_call_id=str(call.get("id")),
                name=str(call.get("name")),
                status="error",
            )
        return handler(request)


@dataclass(frozen=True)
class TurnLimitsConfig:
    max_rounds: int = 100
    max_calls_per_round: int = 50
    max_seconds: float = 1800.0

    @property
    def recursion_limit(self) -> int:
        """Covers every round's model call, its tool wave and the middleware hops (the ARV2 rule)."""

        return self.max_rounds * (self.max_calls_per_round + 2) + 4


def system_prompt_with_skills(workspace: Path, *, allow_new_sections: bool = True) -> str:
    """The system prompt with the skills after it, read from the package so every call and every
    session sends the same text (the spike's, E5 on by default)."""

    folders = ["skills", *(["skills-e5"] if allow_new_sections else [])]
    skills = [
        f"### Skill: {path.parent.name} ({'/' + folder + '/' + path.parent.name}/SKILL.md)\n\n{path.read_text().strip()}"
        for folder in folders
        for path in sorted((SITE_DIR / folder).glob("*/SKILL.md"))
    ]
    return _base_prompt(workspace).rstrip() + "\n\n## Your skills\n\n" + "\n\n".join(skills) + "\n"


def build_site_agent(
    tools: SiteTools,
    *,
    model: Any,
    model_id: str,
    checkpointer: Any = None,
    limits: TurnLimitsConfig = TurnLimitsConfig(),
    compaction: Any = None,
    allow_new_sections: bool = True,
):
    """Returns ``(agent, finish_guard, turn_limits)``."""

    from clue_agents import compaction_config
    from clue_agents.compaction import build_compaction_middleware
    from deepagents import FilesystemPermission
    from deepagents.backends import FilesystemBackend
    from deepagents.middleware.filesystem import FilesystemMiddleware
    from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
    from langchain.agents import create_agent
    from langchain.agents.middleware import ContextEditingMiddleware
    from langgraph.checkpoint.memory import InMemorySaver

    backend = FilesystemBackend(root_dir=tools.workspace, virtual_mode=True)
    guard = FinishGuard(tools)
    turn_limits = TurnLimits(max_rounds=limits.max_rounds, max_seconds=limits.max_seconds)
    # Offloaded history lands under /work/ (history_under_work=True), which the session snapshot
    # leaves out: a fresh session per request has no use for the previous request's offloads.
    summariser, compact_tool = build_compaction_middleware(
        model, backend, compaction or compaction_config.compaction_for(model_id), history_under_work=True
    )
    middleware = [
        FilesystemMiddleware(
            backend=backend,
            _permissions=[FilesystemPermission(operations=["write"], paths=READ_ONLY, mode="deny")],
        ),
        PatchToolCallsMiddleware(),
        summariser,
        compact_tool,
        ContextEditingMiddleware(edits=[SupersededResults()]),
        WholeFileReads(),
        OrderedToolCalls(),
        RoundShape(limit=limits.max_calls_per_round),
        turn_limits,
        guard,
    ]
    agent = create_agent(
        model,
        tools=site_tool_set(tools),
        system_prompt=system_prompt_with_skills(tools.workspace, allow_new_sections=allow_new_sections),
        middleware=middleware,
        checkpointer=checkpointer if checkpointer is not None else InMemorySaver(),
        name="clue-site-agent",
    )
    return agent, guard, turn_limits


@dataclass(frozen=True)
class SiteTurnResult:
    #: "applied" (the site is valid or untouched) or "failed".
    status: str
    summary: str
    site: dict
    stop_reason: str | None
    errors: list[str]
    model_calls: list[dict]


def _final_text(messages: list) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not message.tool_calls:
            content = message.content
            text = content if isinstance(content, str) else " ".join(
                block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"
            )
            if text.strip():
                return text.strip()
    return ""


def run_site_turn(
    prompt: str,
    *,
    config: AgentRuntimeConfig,
    inputs: SiteTurnInputs,
    workspace: Path,
    site: dict,
    run_id: str,
    checkpointer: Any = None,
    thread_id: str | None = None,
    cancel_requested: Any = None,
    callbacks: Any = None,
    event_sink: Any = None,
    limits: TurnLimitsConfig = TurnLimitsConfig(),
    model: Any = None,
) -> SiteTurnResult:
    """Write the workspace, run one request, and read the site back. Never raises.

    ``model`` is a test seam; production builds the orchestrator model through ``_instrument``
    with the run's cancellation probe attached.
    """

    from ..cancellation import CANCELLED_STOP_REASON, TurnCancelled
    from ..checkpoint import RUN_ID_KEY, invoke_turn_graph
    from ..harness import _instrument
    from ..usage_collector import turn_collector

    materialize_workspace(workspace, inputs, site=site)
    tools = SiteTools(workspace=workspace, inputs=inputs, base_site=site, event_sink=event_sink)
    if model is None:
        cancel_kwargs = {} if cancel_requested is None else {"cancel_probe": cancel_requested}
        model = _instrument(config, tools, config.orchestrator_model, "site", **cancel_kwargs)
    agent, guard, turn_limits = build_site_agent(
        tools, model=model, model_id=config.orchestrator_model, checkpointer=checkpointer, limits=limits
    )
    collector, handlers = turn_collector(callbacks)
    invoke_config = {
        "recursion_limit": limits.recursion_limit,
        "configurable": {"thread_id": thread_id or run_id},
        "callbacks": handlers,
    }
    initial = {"messages": [HumanMessage(content=prompt, additional_kwargs={RUN_ID_KEY: run_id})]}

    def calls() -> list[dict]:
        return [item.as_json() for item in collector.calls]

    try:
        if cancel_requested is not None and cancel_requested():
            raise TurnCancelled()
        state = invoke_turn_graph(
            agent, initial, invoke_config=invoke_config, checkpointer=checkpointer,
            thread_id=thread_id, run_id=run_id,
        )
    except TurnCancelled:
        tools._record("cancelled")
        return SiteTurnResult("failed", CANCELLED_SUMMARY, dict(site), CANCELLED_STOP_REASON, [], calls())
    except Exception as error:  # noqa: BLE001 - an honest failure, recorded verbatim
        detail = f"{type(error).__name__}: {error}"[:500]
        tools._record("crashed", error=detail)
        return SiteTurnResult("failed", CRASHED_SUMMARY, dict(site), "crashed", [detail], calls())

    summary = _final_text((state or {}).get("messages") or [])
    if guard.status == "completed with errors":
        first = guard.errors[0] if guard.errors else ""
        return SiteTurnResult("failed", INVALID_SUMMARY.format(error=first), dict(site), "site_invalid",
                              list(guard.errors), calls())
    if tools.site_unchanged():
        return SiteTurnResult("applied", summary, dict(site), turn_limits.stop_reason, [], calls())
    if turn_limits.stop_reason is not None:
        check = tools._validate_raw()
        if not check["valid"]:
            errors = list(check["errors"])
            return SiteTurnResult("failed", INVALID_SUMMARY.format(error=errors[0] if errors else ""),
                                  dict(site), "site_invalid", errors, calls())
    try:
        site_after = read_site_files(workspace, site, tools.sections)
    except json.JSONDecodeError as error:
        return SiteTurnResult("failed", INVALID_SUMMARY.format(error=f"a page file is not valid JSON ({error})"),
                              dict(site), "site_invalid", [str(error)], calls())
    return SiteTurnResult("applied", summary, site_after, turn_limits.stop_reason, [], calls())
```

(`threading` is used by the copied `OrderedToolCalls`.)

- [ ] **Step 5: Run the tests.**

Run: RT `test_site_harness.py`
Expected: PASS. If `test_the_time_limit_stops_before_a_model_call` reports a non-empty
`model_calls`, `TurnLimits` was built before the clock it reads was meant to start: it is built in
`build_site_agent`, after `materialize_workspace`, so check the call order in `run_site_turn`.

- [ ] **Step 6: Commit.**

```bash
git add subsystems/clue-design/apps/agent_runtime/lumen_agent/site/harness.py subsystems/clue-design/apps/agent_runtime/tests/test_site_harness.py
git commit -m "lumen_agent.site.harness: the spike's agent with the platform's model, compaction, limits, receipts and checkpoint seam"
```

---
### Task 8: The workspace view from the database: `BrandData`, clones, sections, research, claims, logos (B2)

**Files:**
- Create: `subsystems/clue-design/apps/api/lumen_api/site_brand.py`
- Create: `subsystems/clue-design/apps/api/lumen_api/site_workspace_view.py`
- Modify: `subsystems/clue-design/apps/api/lumen_api/design_store.py` (two read methods beside
  `list_envelopes`, `:2245`)
- Modify: `apps/frontend/packages/site-kit/src/clone.ts:12-23` (`Clone.degraded_note`),
  `apps/frontend/packages/site-kit/src/catalog.ts` (`cloneFile`'s return array and the index line
  in `buildCatalog`)
- Test: `apps/frontend/packages/site-kit/test/catalog.test.ts`,
  `subsystems/clue-design/apps/api/tests/test_site_brand.py` (new),
  `subsystems/clue-design/apps/api/tests/test_site_workspace_view.py` (new)

**Interfaces:**
- Consumes: `DesignBlobStore.register/read`, `HybridRepository._bridge._run`,
  `DurableAgentClonedSectionRegistry(blobs=, cache_dir=).list_sections()` rows (`fragment_id`,
  `section_role`, `label`, `page_url`, `section_index`, `composed`, `superseded_by`,
  `degraded_note`), `lumen_api.fragments.{read_web_fragment, FragmentRefused}`,
  `lumen_api.fragments.refs.fragment_wrapper_class`, `clue_design.site_sections` (Task 2),
  `build_site_catalog` (Task 3), `SiteTurnInputs`, `SiteSection`, `AccountLogo` (Task 4),
  `cited_claim_ids`, `held_claim_ids`, `read_research` (Task 5),
  `DesignPlatformReads.read_account_research / read_cited_claims / project_design_context`
  (Task 1), `lumen_agent.tools.logo_fetch.fetch_logo_family(url_or_domain, *, company_name, cache)`.
- Produces:
  - `site_brand.asset_store_file(digest: str) -> str`
  - `site_brand.site_brand_data(*, slug: str, kit: dict, kit_assets: dict, font_faces: list[dict], clones: list[dict], library_assets: dict) -> dict` — the one BrandData builder
  - `site_brand.clone_from_fragment(section: dict, loaded) -> dict` (a site-kit `Clone` plus `degraded_note`)
  - `HybridRepository.get_site_sections(digests) -> list[dict]`, `HybridRepository.list_latest_site_sections() -> list[dict]`
  - `site_workspace_view.research_account_id(bundle, document_id) -> str | None`,
    `brief_text(bundle) -> str`, `read_research_pages(reads, account_entity_id) -> tuple[list, list, dict]`,
    `cited_claims(reads, account_entity_id, sections) -> tuple[list[dict], frozenset[str]]`,
    `project_files_from(reads) -> list[dict]`, `fetch_account_logos(blobs, account_card, *, fetcher=None, cache=None) -> list[AccountLogo]`,
    `list_site_clones(blobs, cache_dir) -> list[dict]`, `pinned_site_clones(site, blobs, *, listed: set[str]) -> list[dict]` (the page's own sections the catalog no longer offers, `in_catalog: False`; founder ruling Q5), `read_section_bytes(blobs, row) -> tuple[str, str]`,
    `site_sections_for_turn(store, blobs, site) -> dict[str, SiteSection]`,
    `site_brand_for(site, blobs, *, cache_dir, brand_kit, kit_assets, font_spec, library_assets) -> dict`,
    `site_brand_loader_for(cache_dir_for: Callable[[str], Any]) -> Callable[[repo, blobs, document], dict]` (Lane A's `site_brand_loader` seam; composed in Task 12),
    `referenced_digests(site) -> set[str]`, `referenced_library_assets(asset_library, digests) -> dict`,
    `seller_name(store, kit_ref, kit) -> str`,
    `build_site_turn_inputs(*, document, store, blobs, cache_dir, platform_reads, account_card, delegation_bundle, brand_kit, kit_assets, font_spec, asset_library, assets=None, sections=None, site_versions=None, renderer=None, logo_cache=None) -> SiteTurnInputs`

- [ ] **Step 1: Write the failing site-kit test** (T11). Append to
`apps/frontend/packages/site-kit/test/catalog.test.ts`:

```ts
test("a degraded clone says so in the index and on its card", () => {
  const degradedBrand = garner();
  const first = Object.values(degradedBrand.clones)[0];
  degradedBrand.clones[first.id] = { ...first, degraded_note: "the band lost its images when it was captured." };
  const degradedFiles = buildCatalog(degradedBrand, "Garner Health");
  const line = degradedFiles["catalog/index.md"].split("\n").find((l) => l.includes(`\`${first.id}\``)) ?? "";
  assert.ok(line.endsWith(" · degraded"), line);
  assert.match(degradedFiles[`catalog/clones/${first.id}.md`], /\n\nDegraded: the band lost its images when it was captured\.\n/);
  const healthy = files["catalog/index.md"].split("\n").find((l) => l.includes(`\`${first.id}\``)) ?? "";
  assert.ok(!healthy.includes("degraded"), healthy);
});

test("a section the page already uses but the catalog no longer offers is kept out of the catalog", () => {
  // Founder ruling Q5 (2026-10-12): the brand data carries every section the page itself uses,
  // whatever its status, so the page still draws, saves and publishes; the catalog (what the agent
  // may newly place) stays current-only.
  const pinnedBrand = garner();
  const first = Object.values(pinnedBrand.clones)[0];
  pinnedBrand.clones[first.id] = { ...first, in_catalog: false };
  const pinnedFiles = buildCatalog(pinnedBrand, "Garner Health");
  assert.ok(!pinnedFiles["catalog/index.md"].includes(`\`${first.id}\``));
  assert.equal(pinnedFiles[`catalog/clones/${first.id}.md`], undefined);
});
```

Run: SITE-KIT `catalog.test.ts`
Expected: FAIL — the index line does not end with " · degraded", the `in_catalog: false` clone is
still listed (and `tsc` flags `degraded_note` and `in_catalog` as unknown when type-checked).

- [ ] **Step 2: Confirm T11 was approved** (Task 0), then add the note. In `src/clone.ts`, add to
the `Clone` type after `slots`:

```ts
  /** The registry's sentence when this captured section is marked broken (degraded); absent otherwise. */
  degraded_note?: string | null;
  /** false: a section the page already uses that the catalog no longer offers (superseded by a
   * repair, or retired). It still draws, validates and publishes; the agent is not offered it anew. */
  in_catalog?: boolean;
```

In `src/catalog.ts` `buildCatalog`, change `const clones = Object.values(brand.clones);` to

```ts
  const clones = Object.values(brand.clones).filter((clone) => clone.in_catalog !== false);
```

In `src/catalog.ts` `cloneFile`, change the returned array's first lines from

```ts
    `Source page: ${clone.page_url} · role: ${clone.role} · position on the page: ${clone.section_index ?? "?"}`,
    "",
    "Use it as:",
```

to

```ts
    `Source page: ${clone.page_url} · role: ${clone.role} · position on the page: ${clone.section_index ?? "?"}`,
    ...(clone.degraded_note ? ["", `Degraded: ${clone.degraded_note}`] : []),
    "",
    "Use it as:",
```

and in `buildCatalog` change the index line to

```ts
      index.push(
        `- \`${clone.id}\` · ${clone.role} · ${clone.label} · ${Object.keys(clone.slots).length} slots · catalog/clones/${clone.id}.md` +
          (clone.degraded_note ? " · degraded" : ""),
      );
```

Run: SITE-KIT `catalog.test.ts`, then `cd apps/frontend && npm run typecheck -w @clue/site-kit`
Expected: PASS; no type errors.

- [ ] **Step 3: Write the failing BrandData tests** `apps/api/tests/test_site_brand.py`:

```python
"""lumen_api.site_brand: the one BrandData builder (Lane B Task 8)."""

from __future__ import annotations

from types import SimpleNamespace

from lumen_api.site_brand import asset_store_file, clone_from_fragment, site_brand_data

D1, D2, D3, D4 = "1" * 64, "2" * 64, "3" * 64, "4" * 64


def _record(asset_id: str, digest: str | None, **extra) -> dict:
    media = {"mime_type": "image/png"} | ({"digest": {"algorithm": "sha256", "value": digest}} if digest else {})
    return {"id": asset_id, "kind": "raster_image", "label": asset_id, "media": media, **extra}


def test_every_file_is_a_workspace_blob_and_generated_images_say_so() -> None:
    clone = {"id": "frag_a", "label": "Hero", "html": f'<img src="/asset-store/{D4}" alt="A team">', "css": "",
             "slots": {}, "role": "hero", "page_url": "https://x.example/", "section_index": 1,
             "wrapper_class": "lumen-frag-a", "degraded_note": None}
    brand = site_brand_data(
        slug="kit_1",
        kit={"name": "Garner"},
        kit_assets={"asset_logo": {"record": _record("asset_logo", D1), "description": "The mark"},
                    "asset_nobytes": {"record": _record("asset_nobytes", None)}},
        font_faces=[{"digest": D2, "family": "Open Sans", "weight": 400}, {"digest": D3, "family": None}],
        clones=[clone],
        library_assets={"asset_gen_1": {"record": _record("asset_gen_1", D3, label="A calm classroom",
                                                          source={"kind": "generated"})}},
    )
    # The A9 rewrite (2026-10-12): BrandData has no `measured`; every value reaches site-kit in `kit`.
    assert "measured" not in brand and brand["slug"] == "kit_1" and brand["kit"] == {"name": "Garner"}
    assert brand["assets"]["asset_logo"] == {"kind": "raster_image", "label": "asset_logo", "description": "The mark",
                                             "mime": "image/png", "file": asset_store_file(D1), "logo": None}
    assert "asset_nobytes" not in brand["assets"]
    assert brand["assets"]["asset_gen_1"]["kind"] == "generated_image"
    assert brand["assets"]["asset_gen_1"]["description"] == "generated: A calm classroom"
    assert brand["assets"][asset_store_file(D4)] == {"kind": "captured_image", "label": "Hero", "description": "A team",
                                                     "mime": None, "file": asset_store_file(D4), "logo": None}
    assert brand["fonts"] == [{"family": "Open Sans", "weight": 400, "style": "normal", "file": asset_store_file(D2)}]
    assert brand["clones"] == {"frag_a": clone}


def test_a_registry_row_and_its_payload_become_a_site_kit_clone() -> None:
    section = {"fragment_id": "frag_95041c54da629d99", "section_role": "hero", "label": "Hero — Top Providers",
               "page_url": "https://garnerhealth.com/", "section_index": 1,
               "degraded_note": "this clone is marked broken, with no reason recorded."}
    loaded = SimpleNamespace(html="<section>Hi</section>", css=".x{}",
                             slot_manifest={"headline": {"kind": "text", "fallback": "Hi", "selector": "h1"}, "junk": 3})
    clone = clone_from_fragment(section, loaded)
    assert clone == {
        "id": "frag_95041c54da629d99", "role": "hero", "label": "Hero — Top Providers",
        "page_url": "https://garnerhealth.com/", "section_index": 1,
        "wrapper_class": "lumen-frag-95041c54da629d99", "html": "<section>Hi</section>", "css": ".x{}",
        "slots": {"headline": {"kind": "text", "fallback": "Hi"}},
        "degraded_note": "this clone is marked broken, with no reason recorded.",
    }
```

Run: API `test_site_brand.py`
Expected: FAIL at import — `ModuleNotFoundError: No module named 'lumen_api.site_brand'`.

- [ ] **Step 4: Write `lumen_api/site_brand.py`:**

```python
"""The Puck site's BrandData, built from the stored brand kit (Lane B; the Wave 2 brand split).

ONE builder for every consumer of a site's brand: the site agent's workspace (Lane B), the
renderer, the write validator and publish (Lane A), and the editor read (Lane C). Every image and
font is named ``/asset-store/<sha256>``, a blob of this workspace (Contract 1); nothing names
``/brands/…``. There is no ``measured`` key: what the extraction measured reaches site-kit inside
``kit`` (its minted tokens, ``tokens.styles`` and ``measured_components``; Lane A's A9 rewrite), so
``kit`` is the stored ``brand_kit_json`` passed WHOLE — ``brief``, ``grammar_audit``,
``measured_components`` and ``tokens.styles`` included.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

__all__ = ["asset_store_file", "brand_asset", "clone_from_fragment", "clone_images", "site_brand_data"]

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
#: A captured section's own image, already rehosted to the asset store at capture.
_CLONE_IMAGE = re.compile(r'<img[^>]*?src="(/asset-store/[0-9a-f]{64})"[^>]*?(?:alt="([^"]*)")?')


def asset_store_file(digest: str) -> str:
    return f"/asset-store/{digest}"


def _record_digest(record: Mapping[str, Any]) -> str | None:
    value = ((record.get("media") or {}).get("digest") or {}).get("value")
    return value if isinstance(value, str) and _DIGEST.fullmatch(value) else None


def brand_asset(record: Mapping[str, Any], *, description: str | None) -> dict | None:
    """One engine asset record as a site-kit BrandAsset, or None when it names no bytes."""

    digest = _record_digest(record)
    if digest is None:
        return None
    return {
        "kind": record.get("kind") or "other",
        "label": record.get("label"),
        "description": description,
        "mime": (record.get("media") or {}).get("mime_type"),
        "file": asset_store_file(digest),
        "logo": record.get("logo"),
    }


def clone_images(clones: list[Mapping[str, Any]]) -> dict[str, dict]:
    """Photos and graphics captured with the seller's own sections (site-kit's `cloneImages`)."""

    found: dict[str, dict] = {}
    for clone in clones:
        for match in _CLONE_IMAGE.finditer(str(clone.get("html") or "")):
            file = match.group(1)
            if file in found:
                continue
            label = clone.get("label")
            found[file] = {
                "kind": "captured_image", "label": label,
                "description": match.group(2) or f'From the seller\'s section "{label}"',
                "mime": None, "file": file, "logo": None,
            }
    return found


def site_brand_data(
    *,
    slug: str,
    kit: Mapping[str, Any],
    kit_assets: Mapping[str, Mapping[str, Any]],
    font_faces: list[Mapping[str, Any]],
    clones: list[Mapping[str, Any]],
    library_assets: Mapping[str, Mapping[str, Any]],
) -> dict:
    """BrandData: the kit, its assets and fonts, the released clones and their images, and the
    workspace library assets the site already uses (a generated image is described by its prompt)."""

    assets: dict[str, dict] = {}
    for asset_id, entry in kit_assets.items():
        record = entry.get("record") or {}
        built = brand_asset(record, description=entry.get("description") or record.get("description"))
        if built is not None:
            assets[asset_id] = built
    for asset_id, entry in library_assets.items():
        if asset_id in assets:
            continue
        record = entry.get("record") or {}
        generated = (record.get("source") or {}).get("kind") == "generated"
        description = f"generated: {record.get('label') or ''}" if generated else (
            entry.get("description") or record.get("description"))
        built = brand_asset(record, description=description)
        if built is not None:
            if generated:
                built["kind"] = "generated_image"
            assets[asset_id] = built
    for file, asset in clone_images(clones).items():
        assets.setdefault(file, asset)
    fonts = [
        {"family": face["family"], "weight": face.get("weight"), "style": face.get("style") or "normal",
         "file": asset_store_file(str(face["digest"]))}
        for face in font_faces
        if isinstance(face.get("family"), str) and face.get("family") and _DIGEST.fullmatch(str(face.get("digest") or ""))
    ]
    return {
        "slug": slug,
        "kit": dict(kit),
        "fonts": fonts,
        "assets": assets,
        "clones": {str(clone["id"]): dict(clone) for clone in clones},
    }


def clone_from_fragment(section: Mapping[str, Any], loaded: Any) -> dict:
    """A released clone (a registry row and its payload) as a site-kit Clone, with its degraded note."""

    from .fragments.refs import fragment_wrapper_class

    fragment_id = str(section["fragment_id"])
    slots = {
        str(key): {"kind": entry.get("kind"), "fallback": entry.get("fallback")}
        for key, entry in (loaded.slot_manifest or {}).items()
        if isinstance(entry, dict)
    }
    return {
        "id": fragment_id,
        "role": section.get("section_role") or "section",
        "label": section.get("label") or fragment_id,
        "page_url": section.get("page_url") or "",
        "section_index": section.get("section_index"),
        "wrapper_class": fragment_wrapper_class(fragment_id),
        "html": loaded.html,
        "css": loaded.css,
        "slots": slots,
        "degraded_note": section.get("degraded_note"),
    }
```

Run: API `test_site_brand.py`
Expected: PASS.

- [ ] **Step 5: Add the two section reads** to `HybridRepository` in `design_store.py`, after
`require_envelope`:

```python
    def get_site_sections(self, digests: List[str]) -> List[JsonObject]:
        """This workspace's agent-written sections for ``digests`` (Contract 4), in order."""
        return self._bridge._run(
            lambda conn: design_site_sections.get_site_sections(
                conn, workspace_id=self.workspace_id, digests=digests
            )
        )

    def list_latest_site_sections(self) -> List[JsonObject]:
        """The newest agent-written section of each name in this workspace."""
        return self._bridge._run(
            lambda conn: design_site_sections.list_latest_site_sections(
                conn, workspace_id=self.workspace_id
            )
        )
```

and add `from clue_design import site_sections as design_site_sections` to its imports (beside the
other `clue_design` module imports).

- [ ] **Step 6: Write the failing view tests** `apps/api/tests/test_site_workspace_view.py`:

```python
"""lumen_api.site_workspace_view: one site turn's inputs from the database (Lane B Task 8)."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from conftest import make_blob_store
from lumen_api import site_workspace_view as view
from lumen_api.main import create_app


def test_the_research_account_is_this_documents_artifact() -> None:
    bundle = {"artifacts": [{"document_id": "doc_a", "account_id": "acc_a"},
                            {"document_id": "doc_b", "account_id": "acc_b"}]}
    assert view.research_account_id(bundle, "doc_b") == "acc_b"
    assert view.research_account_id(bundle, "doc_c") is None
    assert view.research_account_id({"artifacts": [{"document_id": "doc_x", "account_id": "acc_x"}]}, "doc_y") == "acc_x"
    assert view.research_account_id({}, "doc_a") is None


def test_the_brief_carries_this_artifact_like_the_spike() -> None:
    bundle = {"brief": "Build a 1:1 page.", "artifact": {"position": 0, "count": 2, "title": "SCSD page", "note": ""}}
    assert view.brief_text(bundle) == (
        'Build a 1:1 page.\n\nTHIS ARTIFACT: {"position": 0, "count": 2, "title": "SCSD page", "note": ""}')
    assert view.brief_text({"brief": "Only a brief."}) == "Only a brief."


def test_research_pages_follow_the_paged_contract_and_a_missing_page_is_an_error_not_a_crash() -> None:
    class Reads:
        def read_account_research(self, *, account_entity_id, section, offset):
            if section == "insights":
                raise RuntimeError("refused:insights_not_written")
            pages = {0: {"overview": [{"section_key": "a"}], "next_offset": 1}, 1: {"overview": [{"section_key": "b"}], "next_offset": None}}
            return pages[offset]

    overview, insights, errors = view.read_research_pages(Reads(), "acc_1")
    assert [s["section_key"] for s in overview] == ["a", "b"] and insights == []
    assert "insights_not_written" in errors["insights"]


def _section(*ids: str) -> dict:
    return {"section_key": "s", "body_text": json.dumps({"h1": "S", "intro": [{"text": "t", "claimIds": list(ids)}]})}


def test_cited_claims_are_read_in_chunks_and_real_holds_are_kept() -> None:
    ids = [f"{n:08d}-0000-5000-8000-000000000000" for n in range(250)]
    asked: list[int] = []

    class Reads:
        def read_cited_claims(self, *, entity_id, claim_ids):
            asked.append(len(claim_ids))
            return {"entity_id": entity_id,
                    "claims": [{"claim_id": claim_ids[0]}],
                    "dispositions": {cid: ("held:outreach_unsafe" if cid == ids[3] else "served") for cid in claim_ids}}

    claims, held = view.cited_claims(Reads(), "acc_1", [_section(*ids)])
    assert asked == [200, 50] and len(claims) == 2 and held == frozenset({ids[3]})


def test_a_failed_cited_read_holds_every_cited_claim() -> None:
    class Reads:
        def read_cited_claims(self, **kwargs):
            raise RuntimeError("read_failed")

    claims, held = view.cited_claims(Reads(), "acc_1", [_section("c1", "c2")])
    assert claims == [] and held == frozenset({"c1", "c2"})


def test_project_files_are_the_pinned_instructions_and_decisions() -> None:
    reads = SimpleNamespace(project_design_context=lambda: {
        "status": "available", "files": [{"path": "instructions.md", "body_text": "Lead with cost."},
                                         {"path": "decisions.md", "body_text": "No video."}]})
    assert view.project_files_from(reads) == [{"path": "instructions.md", "body_text": "Lead with cost."},
                                             {"path": "decisions.md", "body_text": "No video."}]
    assert view.project_files_from(SimpleNamespace(project_design_context=lambda: {"status": "not_pinned", "files": []})) == []


def test_account_logos_are_stored_as_blobs_and_listed_with_their_alternatives(tmp_path, design_storage) -> None:
    blobs = make_blob_store(create_app(tmp_path / "engine-cache", storage=design_storage))
    light = SimpleNamespace(cell="light_lockup", body=b"<svg viewBox='0 0 1 1'/>", content_type="image/svg+xml", label="Acme")
    other = SimpleNamespace(cell="unclassified", body=b"\x89PNGother", content_type="image/png", label="Acme (site header)")
    asked: list[tuple] = []

    def fetcher(domain, *, company_name, cache):
        asked.append((domain, company_name))
        return SimpleNamespace(prepared=[light], alternatives=[other])

    logos = view.fetch_account_logos(blobs, {"name": "Acme", "domain": "acme.example"}, fetcher=fetcher)
    assert asked == [("acme.example", "Acme")]
    assert [(logo.cell, logo.alternative, logo.label) for logo in logos] == [
        ("light_lockup", False, None), ("unclassified", True, "Acme (site header)")]
    digest = hashlib.sha256(light.body).hexdigest()
    assert logos[0].file == f"/asset-store/{digest}" and blobs.read(digest) == light.body
    assert view.fetch_account_logos(blobs, {"name": "Acme"}, fetcher=fetcher) == []

    def broken(*args, **kwargs):
        raise RuntimeError("blocked")

    assert view.fetch_account_logos(blobs, {"name": "Acme", "domain": "acme.example"}, fetcher=broken) == []


def test_the_catalog_lists_every_released_clone_and_flags_degraded_ones(monkeypatch) -> None:
    """Open question 2 (a): nav, footer and campaign-shell clones are offered like any other; only a
    superseded row gives way to its repair."""
    rows = [
        {"fragment_id": "frag_hero", "section_role": "hero", "label": "Hero", "superseded_by": None, "degraded_note": None},
        {"fragment_id": "frag_old", "section_role": "hero", "label": "Old hero", "superseded_by": "frag_hero"},
        {"fragment_id": "frag_nav", "section_role": "nav", "label": "Nav", "superseded_by": None},
        {"fragment_id": "frag_shell", "section_role": "header", "label": "Shell", "superseded_by": None, "composed": "campaign_shell"},
        {"fragment_id": "frag_broken", "section_role": "proof", "label": "Proof", "superseded_by": None,
         "degraded_note": "this clone is marked broken, with no reason recorded."},
    ]

    class Registry:
        def __init__(self, *, blobs, cache_dir):
            pass

        def list_sections(self):
            return {"sections": rows}

    monkeypatch.setattr(view, "DurableAgentClonedSectionRegistry", Registry)
    monkeypatch.setattr(view, "read_web_fragment", lambda storage, *, workspace_id, fragment_id: SimpleNamespace(
        html=f"<p>{fragment_id}</p>", css="", slot_manifest={}))
    clones = view.list_site_clones(SimpleNamespace(storage=None, workspace_id="ws"), "/tmp/cache")
    assert [clone["id"] for clone in clones] == ["frag_hero", "frag_nav", "frag_shell", "frag_broken"]
    assert clones[3]["degraded_note"] == "this clone is marked broken, with no reason recorded."


def test_the_brand_keeps_every_section_the_page_uses_outside_the_catalog(monkeypatch) -> None:
    """Founder ruling Q5 (2026-10-12): a section the page already uses stays in the brand data whatever
    its status (superseded by a repair, retired, not yet approved), so the page still draws, saves and
    reaches publish; it is marked out of the catalog. A section that no longer exists at all is left
    out, so the save check and publish refuse it honestly."""

    loaded = {
        "frag_old": SimpleNamespace(html="<p>old</p>", css="", slot_manifest={},
                                    row={"fragment_id": "frag_old", "label": "Old hero", "section_role": "hero"}),
    }

    def read(storage, *, workspace_id, fragment_id):
        if fragment_id not in loaded:
            raise view.NotFoundError("web fragment", fragment_id)
        return loaded[fragment_id]

    monkeypatch.setattr(view, "read_web_fragment", read)
    site = {"pages": {"/": {"content": [
        {"type": "ClonedSection", "props": {"id": "a", "fragmentId": "frag_hero"}},
        {"type": "ClonedSection", "props": {"id": "b", "fragmentId": "frag_old"}},
        {"type": "ClonedSection", "props": {"id": "c", "fragmentId": "frag_gone"}},
        {"type": "CtaBand", "props": {"id": "d"}},
    ]}}}
    pinned = view.pinned_site_clones(site, SimpleNamespace(storage=None, workspace_id="ws"), listed={"frag_hero"})
    assert [(clone["id"], clone["label"], clone["in_catalog"]) for clone in pinned] == [("frag_old", "Old hero", False)]


def test_sections_for_a_turn_keep_the_documents_pins_and_add_the_newest_of_each_name() -> None:
    rows = {
        "a" * 64: {"name": "StepsBand", "digest": "a" * 64, "module_sha256": "a" * 64, "css_sha256": "c" * 64, "props_schema": {"v": 1}},
        "b" * 64: {"name": "StepsBand", "digest": "b" * 64, "module_sha256": "b" * 64, "css_sha256": "c" * 64, "props_schema": {"v": 2}},
        "d" * 64: {"name": "QuoteBand", "digest": "d" * 64, "module_sha256": "d" * 64, "css_sha256": "c" * 64, "props_schema": {"v": 3}},
    }
    store = SimpleNamespace(
        get_site_sections=lambda digests: [rows[d] for d in digests if d in rows],
        list_latest_site_sections=lambda: [rows["b" * 64], rows["d" * 64]],
    )
    blobs = SimpleNamespace(read=lambda digest: f"bytes {digest[:1]}".encode())
    sections = view.site_sections_for_turn(store, blobs, {"agent_sections": {"StepsBand": "a" * 64}})
    assert sections["StepsBand"].digest == "a" * 64  # the document's own pin wins
    assert sections["QuoteBand"].digest == "d" * 64 and sections["QuoteBand"].module_js == "bytes d"


def test_library_assets_join_only_when_the_site_already_uses_them() -> None:
    site = {"pages": {"/": {"content": [{"props": {"image": "/asset-store/" + "1" * 64}}]}}}
    library = {
        "asset_used": {"record": {"media": {"digest": {"value": "1" * 64}}}},
        "asset_unused": {"record": {"media": {"digest": {"value": "2" * 64}}}},
    }
    assert view.referenced_digests(site) == {"1" * 64}
    assert set(view.referenced_library_assets(library, view.referenced_digests(site))) == {"asset_used"}


def test_the_turn_inputs_put_it_together(monkeypatch) -> None:
    monkeypatch.setattr(view, "list_site_clones", lambda blobs, cache_dir: [])
    monkeypatch.setattr(view, "build_site_catalog", lambda brand, seller: {"brand/brand.md": f"# Brand: {seller}\n"})
    monkeypatch.setattr(view, "fetch_account_logos", lambda blobs, card, cache=None: [])
    monkeypatch.setattr(view, "seller_name", lambda store, ref, kit: "Garner Health")
    monkeypatch.setattr(view, "site_sections_for_turn", lambda store, blobs, site: {})

    class Reads:
        def read_account_research(self, *, account_entity_id, section, offset):
            return {"overview": [_section("c1")], "next_offset": None}

        def read_cited_claims(self, *, entity_id, claim_ids):
            return {"entity_id": entity_id, "claims": [{"claim_id": "c1"}], "dispositions": {"c1": "served"}}

        def project_design_context(self):
            return {"status": "not_pinned", "files": []}

    document = {"id": "doc_a", "scene": {"id": "doc_a", "title": "T", "theme": {"brand_kit": {"id": "kit_1", "version": 2}},
                                          "pages": {"/": {"content": []}}, "shell": None, "agent_sections": {}}}
    inputs = view.build_site_turn_inputs(
        document=document, store=SimpleNamespace(), blobs=SimpleNamespace(workspace_id="ws_1"), cache_dir="/tmp",
        platform_reads=Reads(), account_card={"name": "Syracuse City School District", "domain": "syracusecityschools.com"},
        delegation_bundle={"brief": "B", "artifacts": [{"document_id": "doc_a", "account_id": "acc_1"}]},
        brand_kit={"name": "kit"}, kit_assets={}, font_spec=None, asset_library={},
    )
    assert inputs.document_id == "doc_a" and inputs.workspace_id == "ws_1" and inputs.brief == "B"
    assert inputs.account_name == "Syracuse City School District" and inputs.seller == "Garner Health"
    assert inputs.catalog == {"brand/brand.md": "# Brand: Garner Health\n"}
    assert inputs.brand["slug"] == "kit_1" and "measured" not in inputs.brand
    assert len(inputs.overview) == 1 and len(inputs.insights) == 1  # both sections read through the same fake
    assert inputs.claims == [{"claim_id": "c1"}] and inputs.held_claim_ids == frozenset()


def test_the_brand_loader_lane_a_validates_with_is_the_same_builder(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from lumen_api import main as api_main

    monkeypatch.setattr(api_main, "resolve_web_turn_brand_kit",
                        lambda site, blobs: ({"name": "Garner"}, "document", {}, {"faces": []}))
    monkeypatch.setattr(view, "list_site_clones", lambda blobs, cache_dir: [])
    asked: list[str] = []
    load = view.site_brand_loader_for(lambda workspace_id: asked.append(workspace_id) or tmp_path)
    document = {"id": "doc_a", "scene": {"id": "doc_a", "theme": {"brand_kit": {"id": "kit_1", "version": 2}}, "pages": {}}}
    brand = load(None, SimpleNamespace(workspace_id="ws_b"), document)
    assert brand["slug"] == "kit_1" and brand["clones"] == {} and asked == ["ws_b"]
```

Run: API `test_site_workspace_view.py`
Expected: FAIL at import — `ModuleNotFoundError: No module named 'lumen_api.site_workspace_view'`.

- [ ] **Step 7: Write `lumen_api/site_workspace_view.py`:**

```python
"""Everything one site turn reads, built from the database (Lane B, B2).

The runtime never reads the database (`lumen_agent/config.py`'s rule), so this module — on the
design API side, in the turn's worker thread — reads the stored kit (resolved by the executor),
the released clones, the workspace's agent sections and the library assets the site already uses,
the account's research and the claims it cites (through the platform's governed reads), the
project's pinned instructions and decisions, and the target account's logos, and hands the
runtime one by-value `SiteTurnInputs`. The seller's pinned files are written by the runtime
itself through the same platform reads (`write_seller_knowledge`).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from clue_design.storage import SOURCE_KEY_ASSET
from py_lumen_obs import get_logger
from sqlalchemy import text

from .agent_cloned_sections import DurableAgentClonedSectionRegistry
from .database import NotFoundError
from .fragments import FragmentRefused, read_web_fragment
from .site_brand import _record_digest, asset_store_file, clone_from_fragment, site_brand_data
from .site_kit_cli import build_site_catalog

logger = get_logger("lumen_api.site_workspace_view")

#: read_cited_claims@1 takes at most 200 ids (Contract 5).
CITED_CLAIMS_CHUNK = 200
_ASSET_REF = re.compile(r"/asset-store/([0-9a-f]{64})")


def research_account_id(bundle: Mapping[str, Any], document_id: str) -> str | None:
    """The research account this document was born for: its artifact's `account_id`."""

    artifacts = [item for item in bundle.get("artifacts") or [] if isinstance(item, dict)]
    for item in artifacts:
        if str(item.get("document_id") or "") == document_id and item.get("account_id"):
            return str(item["account_id"])
    named = [item for item in artifacts if item.get("account_id")]
    return str(named[0]["account_id"]) if len(artifacts) == 1 and named else None


def brief_text(bundle: Mapping[str, Any]) -> str:
    """brief.md: the delegation brief, then this artifact's line (the spike's `run_agent.py:139`)."""

    brief = str(bundle.get("brief") or "")
    artifact = bundle.get("artifact")
    return brief + ("\n\nTHIS ARTIFACT: " + json.dumps(artifact) if isinstance(artifact, dict) else "")


def read_research_pages(reads: Any, account_entity_id: str) -> tuple[list[dict], list[dict], dict[str, str]]:
    """The account's overview and insights pages, every block; a page not written is an error."""

    from lumen_agent.site.workspace import read_research

    pages: dict[str, list[dict]] = {}
    errors: dict[str, str] = {}
    for section in ("overview", "insights"):
        try:
            pages[section] = read_research(reads, account_entity_id, section)
        except Exception as error:  # noqa: BLE001 - a page not written yet is a fact, not a crash
            pages[section], errors[section] = [], str(error) or type(error).__name__
    return pages["overview"], pages["insights"], errors


def cited_claims(reads: Any, account_entity_id: str, sections: Sequence[dict]) -> tuple[list[dict], frozenset[str]]:
    """The served claims the research cites, and the cited ids held back by a real rule.

    Fail-closed: a cited read that fails holds every cited id, so no statement whose claim could
    not be checked reaches the research files (statements with no citation stay).
    """

    from lumen_agent.site.workspace import cited_claim_ids, held_claim_ids

    ids = cited_claim_ids(list(sections))
    claims: list[dict] = []
    dispositions: dict[str, str] = {}
    try:
        for start in range(0, len(ids), CITED_CLAIMS_CHUNK):
            answer = reads.read_cited_claims(entity_id=account_entity_id, claim_ids=ids[start : start + CITED_CLAIMS_CHUNK])
            claims += list(answer.get("claims") or [])
            dispositions.update(answer.get("dispositions") or {})
    except Exception:  # noqa: BLE001 - logged; the research keeps only uncited statements
        logger.warning("site_turn.cited_claims_unavailable", account_entity_id=account_entity_id, exc_info=True)
        return [], frozenset(ids)
    return claims, frozenset(held_claim_ids(dispositions))


def project_files_from(reads: Any) -> list[dict]:
    """The opening turn's pinned instructions.md and decisions.md, as plain markdown."""

    try:
        context = reads.project_design_context()
    except Exception:  # noqa: BLE001 - unavailable context is no context
        return []
    if context.get("status") != "available":
        return []
    return [
        {"path": str(item.get("path") or ""), "body_text": str(item.get("body_text") or "")}
        for item in context.get("files") or []
        if isinstance(item, dict)
    ]


def fetch_account_logos(blobs: Any, account_card: Mapping[str, Any] | None, *, fetcher: Any = None, cache: Any = None) -> list:
    """The target account's logo family (the spike's `fetch_account_logo`), stored as design blobs:
    the recommended logos, then every other real logo found, each named /asset-store/<sha256>."""

    from lumen_agent.site.inputs import AccountLogo

    card = account_card or {}
    domain = card.get("domain")
    if not domain:
        return []
    if fetcher is None:
        from lumen_agent.tools.logo_fetch import fetch_logo_family as fetcher
    try:
        outcome = fetcher(str(domain), company_name=card.get("name"), cache=cache)
    except Exception:  # noqa: BLE001 - a blocked site or a vendor miss: the header goes without a logo
        logger.info("site_turn.account_logo_unavailable", domain=str(domain), exc_info=True)
        return []
    logos = []
    for prepared, alternative in [*((p, False) for p in outcome.prepared), *((a, True) for a in outcome.alternatives)]:
        blobs.register(prepared.body, media_type=prepared.content_type, source_key=SOURCE_KEY_ASSET)
        digest = hashlib.sha256(prepared.body).hexdigest()
        logos.append(AccountLogo(
            cell=prepared.cell, file=asset_store_file(digest), content_type=prepared.content_type,
            label=prepared.label if alternative else None, alternative=alternative,
        ))
    return logos


def list_site_clones(blobs: Any, cache_dir: Any) -> list[dict]:
    """The released clones the catalog offers: approved, lineage-resolved (a superseded row gives way
    to its repair), degraded ones listed WITH their note. Every role is offered, the seller's nav and
    footer bands and the composed ABM campaign shells included (founder answer, open question 2 (a),
    2026-10-12): which ones fit a page is the agent's judgement, guided by its skill."""

    registry = DurableAgentClonedSectionRegistry(blobs=blobs, cache_dir=cache_dir)
    clones: list[dict] = []
    for section in registry.list_sections().get("sections") or []:
        if section.get("superseded_by"):
            continue
        try:
            loaded = read_web_fragment(blobs.storage, workspace_id=blobs.workspace_id, fragment_id=str(section["fragment_id"]))
        except (NotFoundError, FragmentRefused):
            continue
        clones.append(clone_from_fragment(section, loaded))
    return clones


def pinned_site_clones(site: Mapping[str, Any], blobs: Any, *, listed: set[str]) -> list[dict]:
    """The sections this site's pages already use that the catalog no longer offers (founder ruling
    Q5, 2026-10-12): a section superseded by a repair, retired, or not yet approved. Each is loaded by
    id whatever its status and marked ``in_catalog: False``, so the page still draws, saves and
    reaches publish (which applies its own rule) while the agent is not offered it anew. A section
    that no longer exists is left out, so the save check and publish refuse it honestly."""

    pinned: list[dict] = []
    seen: set[str] = set(listed)
    for page in (site.get("pages") or {}).values():
        for item in (page or {}).get("content") or []:
            if item.get("type") != "ClonedSection":
                continue
            fragment_id = str((item.get("props") or {}).get("fragmentId") or "")
            if not fragment_id or fragment_id in seen:
                continue
            seen.add(fragment_id)
            try:
                loaded = read_web_fragment(blobs.storage, workspace_id=blobs.workspace_id, fragment_id=fragment_id)
            except (NotFoundError, FragmentRefused):
                continue
            pinned.append({**clone_from_fragment({**loaded.row, "fragment_id": fragment_id}, loaded), "in_catalog": False})
    return pinned


def site_sections_for_turn(store: Any, blobs: Any, site: Mapping[str, Any]) -> dict:
    """The sections a turn may place: each name the document pins at its pinned digest, plus the
    newest section of every other name in the workspace (sections are per workspace)."""

    from lumen_agent.site.inputs import SiteSection

    pinned = {str(name): str(digest) for name, digest in (site.get("agent_sections") or {}).items()}
    pinned_rows = {row["digest"]: row for row in store.get_site_sections(list(pinned.values()))}
    chosen = {name: pinned_rows[digest] for name, digest in pinned.items() if digest in pinned_rows}
    for row in store.list_latest_site_sections():
        chosen.setdefault(str(row["name"]), row)
    sections = {}
    for name, row in chosen.items():
        try:
            module_js, css = read_section_bytes(blobs, row)
        except NotFoundError:
            continue
        sections[name] = SiteSection(name=name, digest=row["digest"], props_schema=row["props_schema"], module_js=module_js, css=css)
    return sections


def read_section_bytes(blobs: Any, row: Mapping[str, Any]) -> tuple[str, str]:
    """A recorded section's compiled module and CSS (raises NotFoundError when either is gone).
    The one read of section files: the turn's sections here, Lane A's loader in Task 15."""

    return blobs.read(row["module_sha256"]).decode("utf-8"), blobs.read(row["css_sha256"]).decode("utf-8")


def site_brand_for(
    site: Mapping[str, Any],
    blobs: Any,
    *,
    cache_dir: Any,
    brand_kit: Mapping[str, Any] | None,
    kit_assets: Mapping[str, Any] | None,
    font_spec: Mapping[str, Any] | None,
    library_assets: Mapping[str, Any],
) -> dict:
    """The site's BrandData: its pinned kit, the released clones plus every section its pages already
    use (marked out of the catalog), and the library images given."""

    kit_ref = (site.get("theme") or {}).get("brand_kit")
    listed = list_site_clones(blobs, cache_dir)
    pinned = pinned_site_clones(site, blobs, listed={str(clone["id"]) for clone in listed})
    return site_brand_data(
        slug=str((kit_ref or {}).get("id") or blobs.workspace_id),
        kit=dict(brand_kit or {}),
        kit_assets=dict(kit_assets or {}),
        font_faces=list((font_spec or {}).get("faces") or []),
        clones=listed + pinned,
        library_assets=dict(library_assets),
    )


def site_brand_loader_for(cache_dir_for: Any) -> Any:
    """Lane A's ``site_brand_loader(repo, blobs, document) -> BrandData`` (its write validation,
    render and publish call it). ``cache_dir_for(workspace_id)`` names the engine cache the clone
    registry reads. Library images are left out: a save validates the images the workspace holds
    as ``siteImages`` (contract conflict 2), so only the turn needs them in the brand."""

    def load(repo: Any, blobs: Any, document: Mapping[str, Any]) -> dict:
        from .main import resolve_web_turn_brand_kit

        site = document["scene"]
        brand_kit, _source, kit_assets, font_spec = resolve_web_turn_brand_kit(site, blobs)
        return site_brand_for(
            site, blobs, cache_dir=cache_dir_for(blobs.workspace_id), brand_kit=brand_kit,
            kit_assets=kit_assets, font_spec=font_spec, library_assets={},
        )

    return load


def referenced_digests(site: Mapping[str, Any]) -> set[str]:
    return set(_ASSET_REF.findall(json.dumps(site)))


def referenced_library_assets(asset_library: Mapping[str, Mapping[str, Any]], digests: set[str]) -> dict:
    """The workspace library assets the site already shows (generated images included)."""

    return {
        asset_id: entry
        for asset_id, entry in asset_library.items()
        if _record_digest(entry.get("record") or {}) in digests
    }


def seller_name(store: Any, kit_ref: Mapping[str, Any] | None, kit: Mapping[str, Any] | None) -> str:
    """The seller's name for brand/brand.md: the brand the kit belongs to, else the kit's own name."""

    if isinstance(kit_ref, Mapping) and kit_ref.get("id") and kit_ref.get("version") is not None:
        async def read(conn: Any) -> str | None:
            row = (await conn.execute(
                text("SELECT b.name FROM design_brand_kit k JOIN brand b ON b.brand_id = k.brand_id "
                     "WHERE k.workspace_id = :w AND k.brand_kit_id = :id AND k.version = :v"),
                {"w": store.workspace_id, "id": str(kit_ref["id"]), "v": int(kit_ref["version"])},
            )).first()
            return None if row is None else str(row.name)

        try:
            name = store._bridge._run(read)
        except Exception:  # noqa: BLE001 - the kit's own name is the honest fallback
            name = None
        if name:
            return name
    return str((kit or {}).get("name") or "the seller")


def build_site_turn_inputs(
    *,
    document: Mapping[str, Any],
    store: Any,
    blobs: Any,
    cache_dir: Any,
    platform_reads: Any,
    account_card: Mapping[str, Any] | None,
    delegation_bundle: Mapping[str, Any] | None,
    brand_kit: Mapping[str, Any] | None,
    kit_assets: Mapping[str, Any] | None,
    font_spec: Mapping[str, Any] | None,
    asset_library: Mapping[str, Any] | None,
    assets: Any = None,
    sections: Any = None,
    site_versions: Any = None,
    renderer: Any = None,
    logo_cache: Any = None,
):
    """One site turn's inputs. Raises only on a broken toolchain (the catalog CLI)."""

    from lumen_agent.site.inputs import SiteTurnInputs

    site = document["scene"]
    document_id = str(document["id"])
    kit_ref = (site.get("theme") or {}).get("brand_kit")
    brand = site_brand_for(
        site, blobs, cache_dir=cache_dir, brand_kit=brand_kit, kit_assets=kit_assets, font_spec=font_spec,
        library_assets=referenced_library_assets(asset_library or {}, referenced_digests(site)),
    )
    seller = seller_name(store, kit_ref, brand_kit)
    bundle = delegation_bundle or {}
    card = account_card or {}
    overview: list[dict] = []
    insights: list[dict] = []
    claims: list[dict] = []
    held: frozenset[str] = frozenset()
    account_entity_id = research_account_id(bundle, document_id)
    if platform_reads is not None and account_entity_id:
        overview, insights, _errors = read_research_pages(platform_reads, account_entity_id)
        claims, held = cited_claims(platform_reads, account_entity_id, overview + insights)
    artifact = bundle.get("artifact") if isinstance(bundle.get("artifact"), dict) else {}
    return SiteTurnInputs(
        document_id=document_id,
        workspace_id=blobs.workspace_id,
        brief=brief_text(bundle),
        account_name=str(card.get("name") or artifact.get("title") or "the account"),
        seller=seller,
        brand=brand,
        catalog=build_site_catalog(brand, seller),
        overview=overview,
        insights=insights,
        claims=claims,
        held_claim_ids=held,
        project_files=project_files_from(platform_reads) if platform_reads is not None else [],
        account_logos=fetch_account_logos(blobs, card, cache=logo_cache),
        agent_sections=site_sections_for_turn(store, blobs, site),
        platform_reads=platform_reads,
        assets=assets,
        sections=sections,
        site_versions=site_versions,
        renderer=renderer,
    )
```

- [ ] **Step 8: Run the tests.**

Run: API `test_site_workspace_view.py`, then API `test_site_brand.py`
Expected: PASS, PASS.

- [ ] **Step 9: Commit.**

```bash
git add subsystems/clue-design/apps/api/lumen_api/site_brand.py subsystems/clue-design/apps/api/lumen_api/site_workspace_view.py subsystems/clue-design/apps/api/lumen_api/design_store.py subsystems/clue-design/apps/api/tests/test_site_brand.py subsystems/clue-design/apps/api/tests/test_site_workspace_view.py apps/frontend/packages/site-kit/src/clone.ts apps/frontend/packages/site-kit/src/catalog.ts apps/frontend/packages/site-kit/test/catalog.test.ts
git commit -m "site turn inputs from the database: the one BrandData builder, released clones with degraded notes, sections, research, cited claims, logos"
```

---
### Task 9: `render_page` on Lane A's hardened renderer (B3, part 2; needs A5)

**Files:**
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/site/skills/page-review/SKILL.md` (T16b) and `lumen_agent/site/SKILLS-CHANGELOG.md`
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/site/tools.py` (add `render_page`,
  `_tiles`, `_broken_images`, `_png_size`, constants)
- Create: `subsystems/clue-design/apps/api/lumen_api/site_turn_ports.py` (`PlatformSiteRenderer`,
  `SiteRenderPortError`; later tasks add the other ports)
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_site_render_tool.py` (new),
  `subsystems/clue-design/apps/api/tests/test_site_turn_ports.py` (new)

**Interfaces:**
- Consumes: A5's `lumen_api.site_render` (`render_site`, `SectionModule`, `RenderedPage`,
  `capture_site_screenshot`, `SiteRenderError` with `.code`); `SiteRenderPort` (Task 4);
  `read_site_files`, `site_pages` (Task 5).
- Produces:
  - `SiteTools.render_page(route: str = "/") -> list[dict] | str`
  - `site_turn_ports.SiteRenderPortError(code: str, detail: str)` with `.code`
  - `site_turn_ports.PlatformSiteRenderer(read_blob=None)` implementing `render(site, brand, sections, *, route) -> (html, css, warnings)` and `screenshot(html, css, *, width) -> bytes`; `read_blob(digest) -> (media_type, bytes)` inlines `/asset-store/` images and fonts as `data:` URIs first (Lane A's screenshot runs with the network blocked)

- [ ] **Step 1: Write the failing tool tests** `apps/agent_runtime/tests/test_site_render_tool.py`:

```python
"""render_page (Lane B Task 9): Lane A's renderer through the render port, no dev server."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from lumen_agent.site.tools import SiteTools
from lumen_agent.site.workspace import materialize_workspace
from lumen_api.site_kit_cli import site_kit_toolchain_missing
from site_fixtures import FakeAssets, FakeRenderer, garner_site, inputs_for, png

needs_node = pytest.mark.skipif(site_kit_toolchain_missing() is not None, reason="site-kit toolchain missing")
HELD = "a" * 64


def _tools(tmp_path: Path, renderer: FakeRenderer, assets: FakeAssets | None = None) -> SiteTools:
    workspace = tmp_path / "workspace"
    inputs = inputs_for(renderer=renderer, assets=assets or FakeAssets(blobs={HELD: ("image/png", png())}))
    materialize_workspace(workspace, inputs, site=garner_site())
    return SiteTools(workspace=workspace, inputs=inputs, base_site=garner_site(), retry_delay_s=0)


@needs_node
def test_render_page_refuses_an_unknown_page(tmp_path: Path) -> None:
    result = _tools(tmp_path, FakeRenderer()).render_page("/pricing")
    assert isinstance(result, str) and "no page /pricing" in result and "/analysis" in result


@needs_node
def test_render_page_refuses_an_invalid_page(tmp_path: Path) -> None:
    tools = _tools(tmp_path, FakeRenderer())
    page = json.loads((tools.workspace / "page.json").read_text())
    next(i for i in page["content"] if i["props"]["id"] == "proof")["props"]["surface"] = "green"
    (tools.workspace / "page.json").write_text(json.dumps(page))
    result = tools.render_page()
    assert isinstance(result, str) and result.startswith("NOT RENDERED: the site is invalid.")


@needs_node
def test_render_page_returns_desktop_and_mobile_pictures_with_facts(tmp_path: Path) -> None:
    renderer = FakeRenderer(html=f'<img src="/asset-store/{HELD}"><img src="/asset-store/{"b" * 64}">')
    blocks = _tools(tmp_path, renderer).render_page("/analysis")
    texts = [b["text"] for b in blocks if b.get("type") == "text"]
    images = [b for b in blocks if b.get("type") == "image"]
    assert texts[0].startswith("1440 wide: page height 2000px, broken images: 1, horizontal overflow: no. Shown at")
    assert "console" not in " ".join(texts)  # founder 2026-10-12: no fact that can never change
    assert texts[1].startswith("375 wide: page height 2000px, broken images: 1")
    assert "top to bottom" in texts[0] and len(images) >= 3  # tall pages arrive in parts
    widths = {base64.b64decode(b["data"])[16:20] for b in images}
    assert len(widths) == 2  # 720 (desktop at half size) and 375 (mobile at full size)
    assert renderer.calls[0] == ("render", "/analysis", [])


@needs_node
def test_overflow_render_notes_and_a_failing_renderer_are_reported(tmp_path: Path) -> None:
    wide = FakeRenderer(shot=png("white", (2000, 400)), warnings=["clone frag_x has no CSS"])
    text = _tools(tmp_path / "a", wide).render_page()[0]["text"]
    assert "horizontal overflow: yes" in text and text.endswith(" Render notes: clone frag_x has no CSS.")
    failing = _tools(tmp_path / "b", FakeRenderer(fail_code="render.timeout")).render_page()
    assert failing == ("NOT RENDERED: the page could not be drawn (render.timeout). Validate it and try again; "
                       "if this repeats, say so in your report.")
```

Run: RT `test_site_render_tool.py`
Expected: FAIL — `AttributeError: 'SiteTools' object has no attribute 'render_page'`.

- [ ] **Step 2: Confirm T8a and T8b were approved** (Task 0). T6e, T16a and T16b were approved on
2026-10-12 (open question 1, answer (b): the console clause is dropped). Apply T16b to the copied
skill: in `subsystems/clue-design/apps/agent_runtime/lumen_agent/site/skills/page-review/SKILL.md`
replace the first paragraph's
`with facts about broken images, overflow and console errors.` with
`with facts about broken images and overflow.`, and append to `lumen_agent/site/SKILLS-CHANGELOG.md`
a dated entry: `2026-10-12 page-review: render_page no longer reports console errors (the production
screenshot runs no script, so the count could never change); section crashes arrive as render notes
or NOT RENDERED instead.`

- [ ] **Step 3: Add `render_page` to `SiteTools`.** Add constants after `LOOP_GUARD_AT`:

```python
#: Screenshots keep their width: desktop at half size (720 px wide), mobile at full size (375 px),
#: cut into pieces of at most TILE_PX tall so a model never shrinks a tall page into a sliver.
SCALE_BY_WIDTH = {1440: 0.5, 375: 1.0}
TILE_PX = 1600
_SOURCES = re.compile(r'\bsrc="([^"]*)"|url\(\s*[\'"]?([^\'")\s]+)[\'"]?\s*\)')
```

Copy the spike's `_tiles` static method verbatim into `SiteTools` (`trials/puck-spike/agent/trials_puck_agent/tools.py:182-201`,
with its `base64`, `io` imports) and add:

```python
    @staticmethod
    def _png_size(png: bytes) -> tuple[int, int]:
        import io

        from PIL import Image

        with Image.open(io.BytesIO(png)) as image:
            return image.width, image.height

    def _broken_images(self, html: str) -> int:
        """Images the rendered page names that this workspace cannot serve (the sanitizer strips any
        source that is not /asset-store/<sha256> or data:, so those count as broken too)."""

        broken = 0
        for match in _SOURCES.finditer(html):
            source = match.group(1) or match.group(2) or ""
            if not source or source.startswith("data:"):
                continue
            digest = digest_of_file(source)
            if digest is None or self.inputs.assets is None or not self.inputs.assets.exists(digest):
                broken += 1
        return broken

    def render_page(self, route: str = "/") -> list[dict] | str:
        """Screenshot one page at 1440 and 375 wide ("/" is page.json, "/analysis" is
        pages/analysis.json). Refuses while the site is invalid."""

        from .workspace import read_site_files, site_pages

        check = self.validate_page()
        if not check.startswith("VALID"):
            return "NOT RENDERED: the site is invalid.\n" + check
        route = "/" + route.strip("/") if route.strip("/") else "/"
        pages = site_pages(self.workspace)
        if route not in pages:
            return f"NOT RENDERED: no page {route}. Pages: {', '.join(pages)}."
        renderer = self.inputs.renderer
        site = read_site_files(self.workspace, self.base_site, self.sections)
        sections = [self.sections[name] for name in site["agent_sections"]]

        def refused(error: Exception) -> str:
            code = getattr(error, "code", None) or type(error).__name__
            return (f"NOT RENDERED: the page could not be drawn ({code}). Validate it and try again; "
                    "if this repeats, say so in your report.")

        if renderer is None:
            return refused(RuntimeError("render.unavailable"))
        try:
            html, css, warnings = renderer.render(site, self.brand, sections, route=route)
        except Exception as error:  # noqa: BLE001 - a refused render is an answer, not a crash
            return refused(error)
        broken = self._broken_images(html)
        blocks: list[dict] = []
        for width in (1440, 375):
            try:
                png = renderer.screenshot(html, css, width=width)
            except Exception as error:  # noqa: BLE001
                return refused(error)
            shot_width, height = self._png_size(png)
            scale = SCALE_BY_WIDTH.get(width, 1.0)
            tiles = self._tiles(png, scale)
            size = "half size" if scale < 1 else "full size"
            notes = f" Render notes: {'; '.join(warnings[:3])}." if warnings and width == 1440 else ""
            blocks.append({
                "type": "text",
                "text": (
                    f"{width} wide: page height {height}px, broken images: {broken}, "
                    f"horizontal overflow: {'yes' if shot_width > width + 1 else 'no'}. "
                    f"Shown at {size} in {len(tiles)} part{'s' if len(tiles) != 1 else ''}, top to bottom.{notes}"
                ),
            })
            blocks.extend(tiles)
        self._record("render", route=route)
        return blocks
```

Run: RT `test_site_render_tool.py`
Expected: PASS. (No console fact: Lane A's screenshot runs no script, so a section crash arrives
as "Render notes" or "NOT RENDERED" instead — open question 1, answer (b).)

- [ ] **Step 4: Write the failing adapter test** `apps/api/tests/test_site_turn_ports.py`:

```python
"""lumen_api.site_turn_ports: the site turn's capabilities (Lane B Tasks 9, 10, 12, 15)."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from types import ModuleType

import pytest

import lumen_api
from lumen_agent.site.inputs import SiteSection
from lumen_api.site_turn_ports import PlatformSiteRenderer, SiteRenderPortError


@dataclass
class RenderedPage:
    route: str
    html: str


@dataclass
class SectionModule:
    name: str
    digest: str
    module_js: str
    css: str
    props_schema: dict


@dataclass
class SiteRender:
    pages: list
    css: str
    warnings: list = field(default_factory=list)


def _fake_site_render(monkeypatch: pytest.MonkeyPatch, calls: list) -> None:
    module = ModuleType("lumen_api.site_render")
    module.RenderedPage = RenderedPage
    module.SectionModule = SectionModule

    def render_site(site, brand, sections, *, base_path, routes=None, timeout_s=20.0):
        calls.append(("render_site", base_path, routes, [s.name for s in sections]))
        return SiteRender(pages=[RenderedPage(route=r, html=f"<main>{r}</main>") for r in routes or ["/"]], css="b{}", warnings=["w"])

    def capture_site_screenshot(page, css, *, width, full_page=True):
        calls.append(("capture", page.html, css, width, full_page))
        return b"png"

    module.render_site = render_site
    module.capture_site_screenshot = capture_site_screenshot
    monkeypatch.setitem(sys.modules, "lumen_api.site_render", module)
    monkeypatch.setattr(lumen_api, "site_render", module, raising=False)


def test_the_renderer_port_drives_lane_as_render_and_screenshot(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list = []
    _fake_site_render(monkeypatch, calls)
    section = SiteSection(name="StepsBand", digest="a" * 64, props_schema={}, module_js="export {}", css=".s{}")
    renderer = PlatformSiteRenderer()
    assert renderer.render({"pages": {}}, {"assets": {}}, [section], route="/analysis") == ("<main>/analysis</main>", "b{}", ["w"])
    assert renderer.screenshot("<main/>", "b{}", width=375) == b"png"
    assert calls == [("render_site", "/", ["/analysis"], ["StepsBand"]), ("capture", "<main/>", "b{}", 375, True)]


def test_the_screenshot_gets_images_and_fonts_inlined_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lane A's screenshot runs with the network blocked, so /asset-store/ references become data:
    URIs before it (contract conflict 7)."""

    calls: list = []
    _fake_site_render(monkeypatch, calls)
    digest = "a" * 64
    renderer = PlatformSiteRenderer(read_blob=lambda d: ("image/png", b"\x89PNG"))
    renderer.screenshot(f'<img src="/asset-store/{digest}">', f"@font-face{{src:url(/asset-store/{digest})}}", width=1440)
    (_, html, css, width, _) = calls[-1]
    assert "/asset-store/" not in html and "data:image/png;base64," in html
    assert "/asset-store/" not in css and width == 1440


def test_a_route_the_renderer_did_not_return_is_a_typed_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list = []
    _fake_site_render(monkeypatch, calls)
    module = sys.modules["lumen_api.site_render"]
    module.render_site = lambda *a, **k: SiteRender(pages=[], css="")
    with pytest.raises(SiteRenderPortError) as refused:
        PlatformSiteRenderer().render({}, {}, [], route="/")
    assert refused.value.code == "render.failed"
```

Run: API `test_site_turn_ports.py`
Expected: FAIL at import — `ModuleNotFoundError: No module named 'lumen_api.site_turn_ports'`.

- [ ] **Step 5: Create `lumen_api/site_turn_ports.py`** with the renderer port:

```python
"""The site turn's capabilities (Lane B): what the runtime may call back into while it runs.

The runtime never reads the database or imports a renderer's internals; it calls these four
objects through the protocols in `lumen_agent/site/inputs.py`:
- PlatformSiteRenderer — Lane A's hardened headless-Chromium renderer (Contract 3);
- DurableSiteAssetPort — this workspace's blobs, and generated images into the library (Task 10);
- DurableSiteVersionPort — the document's saved versions (Task 12);
- DurableSiteSectionPort — compile, read the props schema, store and record a section (Task 15).
"""

from __future__ import annotations

from typing import Any

__all__ = ["PlatformSiteRenderer", "SiteRenderPortError"]


class SiteRenderPortError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class PlatformSiteRenderer:
    """SiteRenderPort over `lumen_api.site_render` (Lane A, Contract 3). Agent sections are only
    ever imported inside Lane A's hardened render page.

    ``read_blob(digest) -> (media_type, bytes)`` is the workspace's blob read: Lane A's screenshot
    runs with JavaScript off and the network blocked, so every ``/asset-store/<sha256>`` in the page
    and its CSS is inlined as a ``data:`` URI first (``web_pdf.inline_asset_store_refs``, the PDF
    export's own helper). A digest the workspace cannot serve is left as is and shows broken, which
    is what the agent should see."""

    def __init__(self, read_blob: Any = None) -> None:
        self.read_blob = read_blob
        self._inlined: dict = {}

    def render(self, site: dict, brand: dict, sections: list, *, route: str) -> tuple[str, str, list[str]]:
        from . import site_render

        modules = [
            site_render.SectionModule(name=s.name, digest=s.digest, module_js=s.module_js, css=s.css, props_schema=s.props_schema)
            for s in sections
        ]
        result = site_render.render_site(site, brand, modules, base_path="/", routes=[route])
        page = next((item for item in result.pages if item.route == route), None)
        if page is None:
            raise SiteRenderPortError("render.failed", f"the renderer returned no page {route}")
        return page.html, result.css, list(result.warnings)

    def screenshot(self, html: str, css: str, *, width: int) -> bytes:
        from . import site_render

        if self.read_blob is not None:
            from .web_pdf import inline_asset_store_refs

            html, _missing = inline_asset_store_refs(html, self.read_blob, cache=self._inlined)
            css, _missing = inline_asset_store_refs(css, self.read_blob, cache=self._inlined)
        return site_render.capture_site_screenshot(site_render.RenderedPage(route="/", html=html), css, width=width, full_page=True)
```

Run: API `test_site_turn_ports.py`
Expected: PASS.

- [ ] **Step 6: Commit.**

```bash
git add subsystems/clue-design/apps/agent_runtime/lumen_agent/site/tools.py subsystems/clue-design/apps/agent_runtime/lumen_agent/site/skills/page-review/SKILL.md subsystems/clue-design/apps/agent_runtime/lumen_agent/site/SKILLS-CHANGELOG.md subsystems/clue-design/apps/agent_runtime/tests/test_site_render_tool.py subsystems/clue-design/apps/api/lumen_api/site_turn_ports.py subsystems/clue-design/apps/api/tests/test_site_turn_ports.py
git commit -m "render_page on Lane A's hardened renderer: screenshots at 1440 and 375, broken images from custody, overflow from width"
```

---

### Task 10: `generate_image` into the workspace library, and the asset port (B3, part 3)

A generated image is stored durably and registered through the governed
`design_register_asset_record` as a library asset whose `source.kind` is `generated` — the asset
library's "AI-generated images" category (`apps/frontend/src/features/brand-context/model/brand-context-mapping.ts`
maps `source.kind === "generated"`). The page names it `/asset-store/<sha256>`. The provider call
runs inside the turn's spend scope (Task 17 proves the scope reaches the tool thread).

**Files:**
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/site/tools.py` (add `generate_image`, `_reference`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/site_turn_ports.py` (add `DurableSiteAssetPort`, `SiteAssetError`)
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_site_images.py` (new),
  `subsystems/clue-design/apps/api/tests/test_site_turn_ports.py`

**Interfaces:**
- Consumes: `lumen_api.image_provider.generate(*, prompt, aspect_ratio, reference_images, …) -> ImageGenerationResult(image_bytes, mime_type, model, provenance, license, width, height)`;
  `CoreClient.ingest_asset(store_root, bytes_base64, asset_id, label, declared_mime_type, kind, license, provenance, source, raise_on_error)`;
  `asset_custody.register_engine_write(blobs, cache_dir, *, source_key, record)`;
  `DesignBlobStore.read_blob/custody_states`; `CustodyState.READABLE`;
  `DesignToolInvocations.invoke("design_register_asset_record", {"record": …}, workspace_id=, actor="agent", actor_id=)`.
- Produces:
  - `SiteTools.generate_image(prompt: str, aspect_ratio: str = "16:9", style_references: list[str] | None = None) -> list[dict] | str`
  - `DurableSiteAssetPort(*, blobs, cache_dir, core, invocations, run_id)` with `read(digest) -> (media_type, bytes)`, `exists(digest) -> bool`, `register_generated(*, image_bytes, mime_type, prompt, model, license, provenance) -> {"asset_id", "digest", "file"}`
  - `SiteAssetError(code, detail)`

- [ ] **Step 1: Write the failing tool tests** `apps/agent_runtime/tests/test_site_images.py`
(the spike's `test_tools.py:405-460`, on `/asset-store` files and the asset port):

```python
"""generate_image (Lane B Task 10): the platform's image provider, stored as a library asset."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from lumen_agent.site.tools import SiteTools
from lumen_agent.site.workspace import materialize_workspace
from site_fixtures import FakeAssets, garner_brand, garner_site, inputs_for, png

PHOTO, MARK = "1" * 64, "2" * 64


class FakeImages:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("provider down")
        return SimpleNamespace(image_bytes=png("green", (32, 18)), mime_type="image/png", width=32, height=18,
                               model="test-image-model", license=None, provenance={"source": "test"})


def _tools(tmp_path: Path, images: FakeImages, assets: FakeAssets | None = None) -> SiteTools:
    brand = garner_brand()
    brand["assets"]["asset_photo"] = {"kind": "raster_image", "label": "Hallway", "description": "A school hallway",
                                      "mime": "image/png", "file": f"/asset-store/{PHOTO}", "logo": None}
    brand["assets"]["asset_mark"] = {"kind": "vector", "label": "Mark", "description": "The logo",
                                     "mime": "image/svg+xml", "file": f"/asset-store/{MARK}", "logo": None}
    assets = assets or FakeAssets(blobs={PHOTO: ("image/png", png()), MARK: ("image/svg+xml", b"<svg/>")})
    inputs = inputs_for(brand=brand, assets=assets, image_generate=images)
    workspace = tmp_path / "workspace"
    materialize_workspace(workspace, inputs, site=garner_site())
    return SiteTools(workspace=workspace, inputs=inputs, base_site=garner_site(), retry_delay_s=0)


def test_generate_image_stores_it_as_a_library_asset_and_shows_it(tmp_path: Path) -> None:
    images, assets = FakeImages(), FakeAssets(blobs={PHOTO: ("image/png", png())})
    tools = _tools(tmp_path, images, assets)
    blocks = tools.generate_image("A calm school-district scene at dusk", "16:9", [f"/asset-store/{PHOTO}"])
    text = blocks[0]["text"]
    file = text.split()[0]
    assert file.startswith("/asset-store/") and "32x18" in text and blocks[1]["type"] == "image"
    assert assets.generated[0]["prompt"] == "A calm school-district scene at dusk"
    call = images.calls[0]
    assert call["aspect_ratio"] == "16:9" and len(call["reference_images"]) == 1
    assert call["reference_images"][0][1] == "image/png"
    placed = {a["file"]: a for a in tools.brand["assets"].values()}[file]
    assert placed["kind"] == "generated_image" and placed["description"] == "generated: A calm school-district scene at dusk"
    assert tools.view_asset([file])[0]["text"].startswith(file)  # the turn can look at what it made


def test_generate_image_refuses_bad_references_and_reports_failures(tmp_path: Path) -> None:
    tools = _tools(tmp_path / "a", FakeImages())
    photo = f"/asset-store/{PHOTO}"
    assert "at most three" in tools.generate_image("x", "16:9", [photo] * 4)
    assert "not one of this brand's images" in tools.generate_image("x", "16:9", ["/asset-store/" + "9" * 64])
    assert "a photo or picture" in tools.generate_image("x", "16:9", [f"/asset-store/{MARK}"])
    failing = _tools(tmp_path / "b", FakeImages(fail=True))
    assert "could not make the image" in failing.generate_image("x", "16:9", [])
    unsaved = _tools(tmp_path / "c", FakeImages(), FakeAssets(blobs={PHOTO: ("image/png", png())}, fail_register=True))
    assert unsaved.generate_image("x", "1:1", []).startswith("The image was made but could not be saved (storage down).")
```

Run: RT `test_site_images.py`
Expected: FAIL — `AttributeError: 'SiteTools' object has no attribute 'generate_image'`.

- [ ] **Step 2: Confirm T12h was approved** (Task 0).

- [ ] **Step 3: Add `generate_image` to `SiteTools`.** Constants after `TILE_PX`:

```python
STYLE_REFERENCES_MAX = 3
REFERENCE_PX = 1024
#: Kinds that are not the brand's own photos: never a style reference.
_NOT_REFERENCES = frozenset({"generated_image", "account_logo"})
```

Methods:

```python
    def _reference(self, file: str) -> tuple[bytes, str] | str:
        """One brand image as a PNG reference for the image model, or the reason it cannot be one."""

        import io

        from PIL import Image

        asset = self._asset_by_file().get(file)
        digest = digest_of_file(file)
        if asset is None or digest is None or asset.get("kind") in _NOT_REFERENCES or self.inputs.assets is None:
            return f"{file}: not one of this brand's images; use a file from brand/brand.md"
        try:
            mime, data = self.inputs.assets.read(digest)
        except Exception as error:  # an unreadable file is an answer, not a crash
            return f"{file}: could not be opened ({error})"
        if "svg" in (mime or "") or (mime or "").startswith("video/"):
            return f"{file}: a style reference must be a photo or picture, not a logo file or a video"
        try:
            image = Image.open(io.BytesIO(data))
            image.thumbnail((REFERENCE_PX, REFERENCE_PX))
            buffer = io.BytesIO()
            image.convert("RGBA" if image.mode in ("RGBA", "LA", "P") else "RGB").save(buffer, format="PNG")
        except Exception as error:  # an unreadable file is an answer, not a crash
            return f"{file}: could not be opened ({error})"
        return buffer.getvalue(), "image/png"

    def generate_image(
        self, prompt: str, aspect_ratio: str = "16:9", style_references: list[str] | None = None
    ) -> list[dict] | str:
        """Make a new image for this site, in the brand's style (see the images-and-logos skill)."""

        from lumen_agent.tools.view import _image_bytes_block

        references = list(style_references or [])
        if len(references) > STYLE_REFERENCES_MAX:
            return f"Give at most three style references (you gave {len(references)})."
        prepared: list[tuple[bytes, str]] = []
        for file in references:
            reference = self._reference(file)
            if isinstance(reference, str):
                return reference
            prepared.append(reference)
        generate = self.inputs.image_generate
        if generate is None:
            from lumen_api.image_provider import generate  # the platform's image provider, spend-scoped
        try:
            result = generate(prompt=prompt, aspect_ratio=aspect_ratio, reference_images=prepared or None)
        except Exception as error:  # the provider failing is an answer, not a crash
            self._record("generate_image", ok=False, error=str(error)[:200])
            return (f"The image model could not make the image ({str(error)[:200]}). Try once more with a shorter "
                    "prompt, or choose a section without an image.")
        try:
            stored = self.inputs.assets.register_generated(
                image_bytes=result.image_bytes, mime_type=result.mime_type, prompt=prompt,
                model=getattr(result, "model", None), license=getattr(result, "license", None),
                provenance=dict(getattr(result, "provenance", None) or {}),
            )
        except Exception as error:  # noqa: BLE001 - storage failing is an answer, not a crash
            self._record("generate_image", ok=False, error=str(error)[:200])
            return (f"The image was made but could not be saved ({str(error)[:200]}). Try once more, or choose a "
                    "section without an image.")
        file = stored["file"]
        self.brand.setdefault("assets", {})[stored["asset_id"]] = {
            "kind": "generated_image", "label": prompt[:80], "description": f"generated: {prompt}",
            "mime": result.mime_type, "file": file, "logo": None,
        }
        self._record("generate_image", ok=True, file=file, model=getattr(result, "model", None))
        size = f"{result.width}x{result.height}" if result.width and result.height else "size unknown"
        return [
            {"type": "text", "text": f"{file} ({size}). Look at it before you use it: put this path in an image "
             "slot or image prop, or leave it out if it breaks the images-and-logos rules."},
            _image_bytes_block(result.image_bytes, max_px=VIEW_ASSET_PX),
        ]
```

Run: RT `test_site_images.py`
Expected: PASS.

- [ ] **Step 4: Write the failing port tests** (append to `apps/api/tests/test_site_turn_ports.py`):

```python
import base64
import hashlib

from conftest import make_blob_store
from lumen_api.asset_custody import write_cache_blob
from lumen_api.main import create_app
from lumen_api.site_turn_ports import DurableSiteAssetPort, SiteAssetError


class FakeCore:
    """The engine's ingest, minus the engine: writes the cache blob and returns a record."""

    def __init__(self, ok: bool = True) -> None:
        self.ok = ok

    def ingest_asset(self, *, store_root, bytes_base64, asset_id, label, declared_mime_type, kind, license,
                     provenance, source, raise_on_error):
        if not self.ok:
            return {"ok": False, "error": {"message": "not an image"}}
        data = base64.b64decode(bytes_base64)
        digest = hashlib.sha256(data).hexdigest()
        write_cache_blob(store_root, digest, data)
        return {"ok": True, "asset": {"record": {
            "id": asset_id, "kind": kind, "label": label, "status": "ready", "source": source, "provenance": provenance,
            "media": {"mime_type": declared_mime_type, "digest": {"algorithm": "sha256", "value": digest},
                      "location": {"provider": "local-store", "opaque_ref": f"sha256/{digest[:2]}/{digest}"}}}}}


class RecordingInvocations:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def invoke(self, name, body, *, workspace_id, actor, actor_id=None):
        self.calls.append((name, body, workspace_id, actor, actor_id))


def test_a_generated_image_becomes_durable_bytes_and_an_ai_generated_library_row(tmp_path, design_storage) -> None:
    blobs = make_blob_store(create_app(tmp_path / "engine-cache", storage=design_storage))
    invocations = RecordingInvocations()
    port = DurableSiteAssetPort(blobs=blobs, cache_dir=tmp_path / "cache", core=FakeCore(),
                                invocations=invocations, run_id="run_site_1")
    image = b"\x89PNG\r\n\x1a\nfake image"
    stored = port.register_generated(image_bytes=image, mime_type="image/png", prompt="A calm classroom",
                                     model="m", license=None, provenance={"source": "test"})
    digest = hashlib.sha256(image).hexdigest()
    assert stored["digest"] == digest and stored["file"] == f"/asset-store/{digest}"
    assert stored["asset_id"].startswith("asset_gen_")
    assert port.read(digest) == ("image/png", image) and port.exists(digest) and not port.exists("0" * 64)
    [(name, body, workspace_id, actor, actor_id)] = invocations.calls
    assert (name, workspace_id, actor, actor_id) == ("design_register_asset_record", blobs.workspace_id, "agent", "run_site_1")
    assert body["record"]["source"]["kind"] == "generated" and body["record"]["label"] == "A calm classroom"
    assert body["record"]["media"]["location"]["provider"] == "clue-storage"


def test_an_image_the_engine_refuses_is_a_typed_error(tmp_path, design_storage) -> None:
    blobs = make_blob_store(create_app(tmp_path / "engine-cache", storage=design_storage))
    port = DurableSiteAssetPort(blobs=blobs, cache_dir=tmp_path / "cache", core=FakeCore(ok=False),
                                invocations=RecordingInvocations(), run_id="run_site_1")
    with pytest.raises(SiteAssetError) as refused:
        port.register_generated(image_bytes=b"x", mime_type="image/png", prompt="p", model=None, license=None, provenance={})
    assert refused.value.code == "site_asset.ingest_failed"
```

Run: API `test_site_turn_ports.py`
Expected: the two new tests FAIL at import — `ImportError: cannot import name 'DurableSiteAssetPort'`.

- [ ] **Step 5: Add the asset port** to `site_turn_ports.py` (extend `__all__` with
`"DurableSiteAssetPort"`, `"SiteAssetError"`):

```python
import base64
import copy
from pathlib import Path
from uuid import uuid4


class SiteAssetError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class DurableSiteAssetPort:
    """SiteAssetPort over this workspace's design blobs and its asset library."""

    def __init__(self, *, blobs: Any, cache_dir: Any, core: Any, invocations: Any, run_id: str) -> None:
        self.blobs = blobs
        self.cache_dir = Path(cache_dir)
        self.core = core
        self.invocations = invocations
        self.run_id = run_id

    def read(self, digest: str) -> tuple[str, bytes]:
        return self.blobs.read_blob(digest)

    def exists(self, digest: str) -> bool:
        from .design_store import CustodyState

        return self.blobs.custody_states([digest]).get(digest) is CustodyState.READABLE

    def register_generated(
        self, *, image_bytes: bytes, mime_type: str, prompt: str, model: str | None,
        license: dict | None, provenance: dict,
    ) -> dict:
        """Ingest, give durable custody, and register an AI-generated library asset (the web lane's
        `_generate_image_record` source shape, and the account-logo binder's custody discipline)."""

        from clue_design.storage import SOURCE_KEY_ASSET

        from .asset_custody import register_engine_write

        asset_id = f"asset_gen_{uuid4().hex}"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        ingest = self.core.ingest_asset(
            store_root=str(self.cache_dir),
            bytes_base64=base64.b64encode(image_bytes).decode("ascii"),
            asset_id=asset_id,
            label=prompt[:200],
            declared_mime_type=mime_type,
            kind="raster_image",
            license=license,
            provenance=provenance,
            source={"kind": "generated", "request_id": asset_id, "model": model},
            raise_on_error=False,
        )
        if not ingest.get("ok"):
            raise SiteAssetError("site_asset.ingest_failed", str((ingest.get("error") or {}).get("message") or "unknown"))
        record = copy.deepcopy((ingest.get("asset") or {}).get("record") or {})
        register_engine_write(self.blobs, self.cache_dir, source_key=SOURCE_KEY_ASSET, record=record)
        digest = str(((record.get("media") or {}).get("digest") or {}).get("value") or "")
        if not digest or not self.exists(digest):
            raise SiteAssetError("site_asset.bytes_unavailable", f"no durable bytes for {asset_id}")
        self.invocations.invoke(
            "design_register_asset_record", {"record": record},
            workspace_id=self.blobs.workspace_id, actor="agent", actor_id=self.run_id,
        )
        return {"asset_id": str(record.get("id") or asset_id), "digest": digest, "file": f"/asset-store/{digest}"}
```

Run: API `test_site_turn_ports.py`
Expected: PASS.

- [ ] **Step 6: Commit.**

```bash
git add subsystems/clue-design/apps/agent_runtime/lumen_agent/site/tools.py subsystems/clue-design/apps/agent_runtime/tests/test_site_images.py subsystems/clue-design/apps/api/lumen_api/site_turn_ports.py subsystems/clue-design/apps/api/tests/test_site_turn_ports.py
git commit -m "generate_image: the platform's image provider, stored durably as an AI-generated library asset named /asset-store/<sha256>"
```

---

### Task 11: `search_assets` — the hybrid image search, wired (B4)

The hybrid search arrived with the scene-ad merge (`deb3a0e98`). It is moved, unchanged, out of
the scene substrate into `asset_catalog` so the site tool calls the same function; the executor
loads the workspace's CLIP vectors the way the scene path does (`main.py:9240-9246`).

**Files:**
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/tools/asset_catalog.py` (add
  `one_line`, `visual_asset_ranking`, `hybrid_search`)
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/tools/substrate.py:187-195`
  (`_one_line` becomes an import) and `:1329-1397` (`search_assets` delegates;
  `_visual_asset_ranking` removed)
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/site/tools.py` (add `search_assets`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/site_workspace_view.py` (`asset_candidates`,
  `asset_embeddings`)
- Test: `apps/agent_runtime/tests/test_search_assets_hybrid.py` (unchanged, must stay green),
  `apps/agent_runtime/tests/test_site_search_assets.py` (new),
  `apps/api/tests/test_site_workspace_view.py`

**Interfaces:**
- Consumes: `asset_catalog.rank_assets`, `asset_summary`, `_asset_kind_matches`;
  `lumen_api.asset_embeddings.{embed_query, visual_ranking, hybrid_ranking, FUSION_DEPTH, EmbeddingUnavailable, load_workspace_embeddings}`.
- Produces:
  - `asset_catalog.one_line(text, limit=220) -> str | None`
  - `asset_catalog.visual_asset_ranking(query: str, candidates: dict, kind: str, embeddings: dict | None) -> tuple[list[str], str]`
  - `asset_catalog.hybrid_search(candidates: dict[str, tuple[dict, str]], q: str, kind: str | None, limit: int, embeddings: dict | None) -> dict` (the scene tool's exact JSON payload)
  - `SiteTools.search_assets(q: str, kind: str | None = None, limit: int = 8) -> str`
  - `site_workspace_view.search_candidates(kit_assets, asset_library) -> dict`

- [ ] **Step 1: Run the scene suite before moving anything** (the guard):

Run: RT `test_search_assets_hybrid.py`
Expected: PASS (10 tests).

- [ ] **Step 2: Move the search into `asset_catalog.py`.** Append:

```python
def one_line(text: Any, limit: int = 220) -> Optional[str]:
    """An asset description's first sentence, capped — `search_assets` results stay compact;
    `view("asset:<id>")` carries the full analysis."""
    if not text:
        return None
    flat = " ".join(str(text).split())
    end = flat.find(". ")
    first = flat[: end + 1] if 0 < end < limit else flat
    return first if len(first) <= limit else first[: limit - 1].rstrip() + "…"


def visual_asset_ranking(query: str, candidates: dict, kind: str, embeddings: Optional[dict]) -> tuple[list[str], str]:
    """Candidate ids closest to the query by CLIP image vector, and a plain status line.

    Visual search is an addition, never a requirement: no vectors for this library, no model on
    this host, or a failed query embedding each return [] with the reason, and the caller ranks by
    keyword alone.
    """
    if not embeddings:
        return [], "off: this library has no image vectors yet"
    try:
        from lumen_api.asset_embeddings import EmbeddingUnavailable, embed_query, visual_ranking
    except Exception as error:  # noqa: BLE001 - the API package may be absent in a bare runtime
        return [], f"off: visual search is not installed here ({type(error).__name__})"
    try:
        vector = embed_query(query)
    except EmbeddingUnavailable as error:
        return [], f"off: {error}"
    eligible = [aid for aid, (entry, _) in candidates.items() if _asset_kind_matches(entry.get("record") or {}, kind)]
    ranking = visual_ranking(vector, embeddings, eligible)
    return ranking, ("on" if ranking else "off: none of these images has a vector yet")


def hybrid_search(candidates: dict, q: str, kind: Optional[str], limit: int, embeddings: Optional[dict]) -> dict:
    """`search_assets`' payload: exact ids first, then keyword and look fused (founder ruling 2026-10-05)."""
    if not q.strip() or isinstance(limit, bool) or not 1 <= limit <= 20:
        return {"status": "error", "message": "Supply a query and limit 1..20"}
    query, wanted_kind = q.strip(), (kind or "").lower()
    ranked = rank_assets(candidates, query.lower(), wanted_kind)
    named = [row[0] for row in ranked if row[3]]
    keyword = [row[0] for row in ranked if not row[3]]
    visual, visual_status = visual_asset_ranking(query, candidates, wanted_kind, embeddings)
    if visual:
        from lumen_api.asset_embeddings import FUSION_DEPTH, hybrid_ranking

        fused = [aid for aid in hybrid_ranking(keyword, visual) if aid not in named]
        keyword_set, visual_set = set(keyword[:FUSION_DEPTH]), set(visual[:FUSION_DEPTH])
    else:
        fused = keyword
        keyword_set, visual_set = set(keyword), set()
    results = []
    for aid in (named + fused)[:limit]:
        entry, origin = candidates[aid]
        results.append({
            "asset_id": aid, "origin": origin, "title": entry.get("title"),
            "description": one_line(entry.get("description")), "usage": entry.get("usage"),
            "view": f"asset:{aid}", **asset_summary(entry),
            "match": ("id" if aid in named else
                      "words and look" if aid in keyword_set and aid in visual_set else
                      "words" if aid in keyword_set else
                      "look" if aid in visual_set else
                      "words" if aid in keyword else "look"),
        })
    return {"status": "ok", "results": results, "count": len(results),
            "inventory_count": len(candidates), "visual_search": visual_status}
```

Add `Optional` to `asset_catalog.py`'s `typing` import if absent.

- [ ] **Step 3: Make the scene substrate delegate.** In `tools/substrate.py`, replace the
`_one_line` definition (`:187-195`) with `from .asset_catalog import one_line as _one_line`
(placed with the module's other imports), delete `_visual_asset_ranking` (`:1376-1397`), and
replace the body of `search_assets` after its docstring (keep the docstring byte for byte — it is
the scene tool's description) with:

```python
        from .asset_catalog import hybrid_search

        candidates = {}
        for manifest, origin in ((self.config.brand_kit_assets or {}, "brand_kit"),
                                 (self.config.asset_library or {}, "library")):
            for asset_id, entry in manifest.items():
                candidates.setdefault(asset_id, (entry, origin))
        return json.dumps(hybrid_search(candidates, q, kind, limit, self.config.asset_embeddings))
```

Run: RT `test_search_assets_hybrid.py`
Expected: PASS (unchanged tests: the move changed nothing the scene agent sees).

- [ ] **Step 4: Write the failing site tests** `apps/agent_runtime/tests/test_site_search_assets.py`:

```python
"""search_assets for the site agent (Lane B Task 11): the scene's hybrid search, with files."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from lumen_agent.site.tools import SiteTools
from lumen_agent.site.workspace import materialize_workspace
from site_fixtures import FakeAssets, garner_site, inputs_for, png

D_CLASS, D_DASH = "1" * 64, "2" * 64
CANDIDATES = {
    "asset_classroom": {"origin": "library", "title": "Classroom", "description": "A calm classroom in morning light.",
                        "record": {"id": "asset_classroom", "kind": "raster_image", "label": "classroom.png",
                                   "media": {"mime_type": "image/png", "digest": {"value": D_CLASS}}}},
    "asset_dashboard": {"origin": "brand_kit", "title": "Dashboard", "description": "The product dashboard.",
                        "record": {"id": "asset_dashboard", "kind": "raster_image", "label": "dash.png",
                                   "media": {"mime_type": "image/png", "digest": {"value": D_DASH}}}},
}


def _vec(*hot):
    v = np.zeros(512, np.float32)
    for i in hot:
        v[i] = 1.0
    return (v / np.linalg.norm(v)).tolist()


def _tools(tmp_path: Path, embeddings=None) -> SiteTools:
    inputs = inputs_for(asset_candidates=CANDIDATES, asset_embeddings=embeddings,
                        assets=FakeAssets(blobs={D_CLASS: ("image/png", png())}))
    materialize_workspace(tmp_path / "workspace", inputs, site=garner_site())
    return SiteTools(workspace=tmp_path / "workspace", inputs=inputs, base_site=garner_site(), retry_delay_s=0)


def test_results_carry_a_placeable_file_and_join_the_turns_brand(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    answer = json.loads(tools.search_assets("calm classroom"))
    assert answer["status"] == "ok" and answer["visual_search"].startswith("off")
    first = answer["results"][0]
    assert first["asset_id"] == "asset_classroom" and first["file"] == f"/asset-store/{D_CLASS}"
    assert "view" not in first
    assert tools.view_asset([first["file"]])[0]["text"].startswith(first["file"])


def test_the_look_finds_an_image_whose_words_do_not_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from lumen_api import asset_embeddings

    monkeypatch.setattr(asset_embeddings, "embed_query", lambda text: np.array(_vec(7), np.float32))
    tools = _tools(tmp_path, embeddings={"asset_dashboard": _vec(7), "asset_classroom": _vec(1)})
    answer = json.loads(tools.search_assets("blue glowing interface"))
    assert answer["visual_search"] == "on" and answer["results"][0]["asset_id"] == "asset_dashboard"


def test_bad_inputs_are_refused(tmp_path: Path) -> None:
    assert json.loads(_tools(tmp_path).search_assets("x", limit=0))["status"] == "error"
```

Run: RT `test_site_search_assets.py`
Expected: FAIL — `AttributeError: 'SiteTools' object has no attribute 'search_assets'`.

- [ ] **Step 5: Add `search_assets` to `SiteTools`:**

```python
    def search_assets(self, q: str, kind: str | None = None, limit: int = 8) -> str:
        """Search the seller's images by what they show and how they look."""

        import json

        from lumen_agent.tools.asset_catalog import hybrid_search

        candidates = {
            asset_id: (entry, str(entry.get("origin") or "library"))
            for asset_id, entry in (self.inputs.asset_candidates or {}).items()
        }
        answer = hybrid_search(candidates, q, kind, limit, self.inputs.asset_embeddings)
        for row in answer.get("results") or []:
            row.pop("view", None)
            entry, _ = candidates[row["asset_id"]]
            record = entry.get("record") or {}
            digest = ((record.get("media") or {}).get("digest") or {}).get("value")
            if not isinstance(digest, str) or not _ASSET_FILE.match(f"/asset-store/{digest}"):
                continue
            row["file"] = f"/asset-store/{digest}"
            # Found by search, so placeable: the validator checks images against the turn's brand.
            self.brand.setdefault("assets", {}).setdefault(row["asset_id"], {
                "kind": record.get("kind") or "other", "label": entry.get("title") or record.get("label"),
                "description": entry.get("description"), "mime": (record.get("media") or {}).get("mime_type"),
                "file": row["file"], "logo": record.get("logo"),
            })
        self._record("search_assets", query=q, count=len(answer.get("results") or []))
        return json.dumps(answer)
```

Run: RT `test_site_search_assets.py`
Expected: PASS.

- [ ] **Step 6: Give the turn its candidates and vectors.** Add to
`lumen_api/site_workspace_view.py`:

```python
#: Images and logos only: a font or a document is never a section image.
_SEARCHABLE_KINDS = frozenset({"raster_image", "vector"})


def search_candidates(kit_assets: Mapping[str, Any] | None, asset_library: Mapping[str, Any] | None) -> dict:
    """search_assets' inventory: the kit's assets, then the workspace library, images only."""

    candidates: dict[str, dict] = {}
    for origin, manifest in (("brand_kit", kit_assets or {}), ("library", asset_library or {})):
        for asset_id, entry in manifest.items():
            record = entry.get("record") or {}
            if record.get("kind") in _SEARCHABLE_KINDS and record.get("status", "ready") != "archived":
                candidates.setdefault(asset_id, {**entry, "origin": origin})
    return candidates
```

and in `build_site_turn_inputs`, before the `return`, compute:

```python
    candidates = search_candidates(kit_assets, asset_library)
    if candidates:
        from .asset_embeddings import load_workspace_embeddings

        embeddings = load_workspace_embeddings(blobs.workspace_id)
    else:
        embeddings = {}
```

and pass `asset_candidates=candidates, asset_embeddings=embeddings` to `SiteTurnInputs(...)`.

Append to `apps/api/tests/test_site_workspace_view.py`:

```python
def test_search_candidates_are_the_kits_and_the_librarys_images() -> None:
    kit = {"asset_logo": {"record": {"kind": "vector"}}, "asset_font": {"record": {"kind": "font"}}}
    library = {"asset_logo": {"record": {"kind": "raster_image"}}, "asset_photo": {"record": {"kind": "raster_image"}},
               "asset_old": {"record": {"kind": "raster_image", "status": "archived"}}}
    candidates = view.search_candidates(kit, library)
    assert {k: v["origin"] for k, v in candidates.items()} == {"asset_logo": "brand_kit", "asset_photo": "library"}
```

and in `test_the_turn_inputs_put_it_together`, add
`monkeypatch.setattr("lumen_api.asset_embeddings.load_workspace_embeddings", lambda workspace_id: {})`
before the call, pass `asset_library={"asset_photo": {"record": {"kind": "raster_image"}}}`, and
assert `set(inputs.asset_candidates) == {"asset_photo"}` and `inputs.asset_embeddings == {}`.

Run: API `test_site_workspace_view.py`
Expected: PASS.

- [ ] **Step 7: Commit.**

```bash
git add subsystems/clue-design/apps/agent_runtime/lumen_agent/tools/asset_catalog.py subsystems/clue-design/apps/agent_runtime/lumen_agent/tools/substrate.py subsystems/clue-design/apps/agent_runtime/lumen_agent/site/tools.py subsystems/clue-design/apps/agent_runtime/tests/test_site_search_assets.py subsystems/clue-design/apps/api/lumen_api/site_workspace_view.py subsystems/clue-design/apps/api/tests/test_site_workspace_view.py
git commit -m "search_assets for the site agent: the scene's hybrid search moved to asset_catalog unchanged, with placeable files and CLIP vectors"
```

---
### Task 12: The site executor — `execute_site_turn_job`, `run_site_agent_turn`, the fleet dispatch (B5, design side; needs A2)

Contract 7: envelope `kind = "site_turn"`; the executor returns `{status, summary,
current_version, model_calls, doc_kind: "site", error?, stop_reason?}`; it persists through
`design_write_site` under CAS (one request, one undo step); it emits `site_document_saved
{document_id, version}` and never an `operations` key. Fresh session per request: the LangGraph
thread is the run (the platform sets `checkpoint_thread_id = run_id`, Task 13); the session
*folder* is the document's (`design_session_id`), synced with regenerated inputs left out.

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/models.py` (add `SiteTurnRequest` after `WebTurnRequest`, `:172`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/site_turn_ports.py` (add `SitePersistOutcome`, `DurableSiteVersionPort`)
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/session_sync.py:37-74` (`exclude`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py` (new functions after
  `execute_web_turn_job`'s body ends at `:11449`; `app.state.site_turn_runner` beside
  `web_turn_runner` `:848`; the embedded `host()` `:594-610`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/fleet_handler.py` (`DesignTurnHost` `:120-150`,
  capabilities `:213`, `_TRACE_SHAPES` `:456-467`, `_execute_turn` `:629-683`)
- Test: `apps/agent_runtime/tests/test_session_sync.py`, `apps/api/tests/test_site_turn_ports.py`,
  `apps/api/tests/test_site_turn_executor.py` (new), `apps/api/tests/test_site_fleet_dispatch.py` (new)

**Interfaces:**
- Consumes: A2's `design_write_site@1`, `SiteDocumentInvalid`, `HybridRepository.update_site_document`,
  `sections_not_stored` and the `site_brand_loader` / `site_section_loader` seams (Lane A Tasks 11
  and 12, see "Cross-lane interfaces"); `site_kit_support.ensure_site_kit_dist` (Lane A test helper);
  `site_brand_loader_for` (Task 8); `build_site_turn_inputs` (Tasks 8, 11); `DurableSiteAssetPort` (Task 10), `PlatformSiteRenderer` (Task 9);
  `run_site_turn`, `SiteTurnResult` (Task 7); `append_history`, `history_count`, `saved_line`,
  `site_changes`, `site_pages_of`, `SESSION_REGENERATED` (Task 5); existing `main.py` helpers
  `_turn_model_call_collector`, `_with_model_calls`, `_turn_spend_stamp`, `_drain_spend`,
  `_turn_blob_store`, `_turn_design_tools`, `_host_engine_cache_root`, `_turn_core`,
  `_document_drift_note`, `_session_manifest`, `_run_cancel_probe`, `_stamp_session_manifest`,
  `resolve_web_turn_brand_kit`, `pinned_asset_library`, `failed_agent_turn_response`,
  `conflicted_web_turn_response`, `repo_root`, `DurableLogoFamilyCache`.
- Produces:
  - `models.SiteTurnRequest(prompt: str, base_version: int)`
  - `site_turn_ports.SitePersistOutcome(status: Literal["saved", "conflicted", "refused"], version: int | None, detail: str | None)`
  - `site_turn_ports.DurableSiteVersionPort(store, document_id)` with `list_versions(limit)`, `site_at(version)`
  - `session_sync.snapshot_session(session_dir, *, register, history_file, exclude: frozenset[str] = frozenset())`
  - `main.run_site_agent_turn(document, prompt, *, user_message, inputs, persist, workspace_id, run_id, session_id, session_manifest, blobs, checkpointer=None, cancel_requested=None, callbacks=None, event_sink=None, runner=None) -> dict`
  - `main.execute_site_turn_job(envelope, *, store, host, event_sink, checkpointer=None, lease_generation=None, spend_drain=None, callbacks=None, session_continued=False) -> (status, response, event_type, event_data)`
  - `fleet_handler.executor_for_kind(kind: str) -> Callable` (raises `DesignTurnJobError` for an unknown kind)
  - `fleet_handler.DesignTurnHost.site_turn_runner` (test seam: `runner(prompt, *, document, workspace, run_id, callbacks) -> SiteTurnResult`)
  - run event `site_document_saved` with data `{"document_id": str, "version": int}`

- [ ] **Step 1: Check A2's write tool against what this task assumes.**

```bash
grep -rn '"design_write_site"' subsystems/clue-design/apps/api/lumen_api/toolbelt/ | head -3
grep -rn 'class .*SiteInput\|expected_base_version\|agent_run_active' subsystems/clue-design/apps/api/lumen_api/toolbelt/site*.py | head -20
```

Expected (Lane A's plan, its Task 12): the tool exists; its input has `document_id`, `site`,
`expected_base_version`, `intent`, `actor_kind`, `source`; a CAS loss raises
`WebDocumentVersionConflict`; a contract refusal raises `SiteDocumentInvalid(errors)`; the tool
has no `agent_run_active` check (that refusal is in the routes, contract conflict 6), so the run's
own write is admitted. Also check the two loader seams exist:
`grep -n "site_brand_loader\|site_section_loader" subsystems/clue-design/apps/api/lumen_api/toolbelt/wiring.py subsystems/clue-design/apps/api/lumen_api/main.py`.
If a name differs, use the real name below. If the tool refuses the run's own write, stop and
raise it with Lane A before going on.

- [ ] **Step 2: Write the failing session-sync test** (append to
`apps/agent_runtime/tests/test_session_sync.py`):

```python
def test_a_snapshot_can_leave_out_regenerated_folders(tmp_path: Path) -> None:
    session = tmp_path / "sessions" / "dsess_site"
    workspace = session / "workspace"
    (workspace / "research").mkdir(parents=True)
    (workspace / "fetched").mkdir()
    (workspace / "plan.md").write_text("plan", encoding="utf-8")
    (workspace / "page.json").write_text("{}", encoding="utf-8")
    (workspace / "research" / "overview.md").write_text("old research", encoding="utf-8")
    (workspace / "fetched" / "story.md").write_text("evidence", encoding="utf-8")
    manifest = snapshot_session(session, register=_Blobs().register, history_file=None,
                                exclude=frozenset({"research", "page.json"}))
    assert set(manifest["files"]) == {"workspace/plan.md", "workspace/fetched/story.md"}
    # The default leaves out nothing, byte-identical to the web and scene lanes.
    everything = snapshot_session(session, register=_Blobs().register, history_file=None)
    assert "workspace/research/overview.md" in everything["files"]
```

Run: RT `test_session_sync.py`
Expected: FAIL — `TypeError: snapshot_session() got an unexpected keyword argument 'exclude'`.

- [ ] **Step 3: Add `exclude`** to `lumen_agent/session_sync.py`. Change `_iter_workspace_files`
to take it and skip by the first path part under `workspace/`, and thread it through:

```python
def _iter_workspace_files(session_dir: Path, exclude: frozenset[str] = frozenset()) -> Iterator[tuple[str, Path]]:
    """``(manifest key, path)`` for every file the session workspace may carry across turns.

    ``exclude`` names top-level entries of ``workspace/`` that are rebuilt for every turn (the site
    agent's research, catalog and page files) and so never belong in the session's memory.
    """
    workspace = session_dir / "workspace"
    if not workspace.is_dir():
        return
    for path in sorted(workspace.rglob("*")):
        # ``is_symlink`` is checked FIRST: ``is_file`` follows the link, so a symlink to a real
        # file would otherwise be read and stored as if it were session content.
        if path.is_symlink() or not path.is_file():
            continue
        if path.relative_to(workspace).parts[0] in exclude:
            continue
        if path.stat().st_size <= MAX_FILE_BYTES:
            yield path.relative_to(session_dir).as_posix(), path
```

```python
def snapshot_session(
    session_dir: Path,
    *,
    register: Callable[[bytes, str, str], str],
    history_file: Path | None,
    exclude: frozenset[str] = frozenset(),
) -> dict:
```

and inside it `entries = list(_iter_workspace_files(session_dir, exclude))`.

Run: RT `test_session_sync.py`
Expected: PASS (every existing test unchanged).

- [ ] **Step 4: Write the failing version-port test** (append to `apps/api/tests/test_site_turn_ports.py`):

```python
from lumen_api.design_store import HybridRepository
from lumen_api.site_turn_ports import DurableSiteVersionPort


def _site(doc_id: str, heading: str) -> dict:
    return {"id": doc_id, "title": "S", "theme": {}, "shell": None, "agent_sections": {},
            "pages": {"/": {"root": {"props": {"title": "S"}}, "content": [{"type": "CtaBand", "props": {"id": "c", "heading": heading}}]}}}


def test_saved_versions_are_read_from_the_documents_history() -> None:
    store = HybridRepository()
    doc_id = f"doc_site_{uuid4().hex[:10]}"
    born = store.create_document(_site(doc_id, "v0"), doc_kind="site")
    previous = born["scene"]
    for heading, actor in (("v1", "agent"), ("v2", "human")):
        new = _site(doc_id, heading)
        store.update_web_document(doc_id, new, intent=f"make {heading}", checkpoint_label=None,
                                  operations=[{"kind": "replace_site", "site": new}],
                                  inverse_operations=[{"kind": "replace_site", "site": previous}],
                                  actor_kind=actor, source=actor)
        previous = new
    port = DurableSiteVersionPort(store, doc_id)
    assert [(v["version"], v["actor"], v["intent"]) for v in port.list_versions(10)] == [
        (2, "human", "make v2"), (1, "agent", "make v1")]
    assert port.site_at(1)["pages"]["/"]["content"][0]["props"]["heading"] == "v1"
    assert port.site_at(9) is None
```

(add `from uuid import uuid4` to the file's imports).

Run: API `test_site_turn_ports.py -k versions`
Expected: FAIL — `ImportError: cannot import name 'DurableSiteVersionPort'`.

- [ ] **Step 5: Add the outcome and the version port** to `site_turn_ports.py` (extend `__all__`):

```python
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class SitePersistOutcome:
    """What the governed site write did with one request's site."""

    status: Literal["saved", "conflicted", "refused"]
    #: The new version when saved; the stored version when conflicted; None when refused.
    version: int | None
    detail: str | None = None


def _replace_site(envelope: dict) -> dict | None:
    operations = envelope.get("operations") or []
    if len(operations) == 1 and isinstance(operations[0], dict) and operations[0].get("kind") == "replace_site":
        site = operations[0].get("site")
        return site if isinstance(site, dict) else None
    return None


class DurableSiteVersionPort:
    """SiteVersionPort over the document's edit history (Contract 2: one envelope per save or
    request, each a whole-site snapshot)."""

    def __init__(self, store: Any, document_id: str) -> None:
        self.store = store
        self.document_id = document_id

    def list_versions(self, limit: int) -> list[dict]:
        rows = self.store.list_envelopes(self.document_id, limit=limit, newest_first=True)
        return [
            {"version": int(row["base_revision"]) + 1, "actor": (row.get("actor") or {}).get("kind"),
             "intent": row.get("intent"), "created_at": row.get("created_at")}
            for row in rows
            if _replace_site(row) is not None
        ]

    def site_at(self, version: int) -> dict | None:
        for row in self.store.list_envelopes(self.document_id, newest_first=True):
            if int(row["base_revision"]) + 1 == int(version):
                site = _replace_site(row)
                return copy.deepcopy(site) if site is not None else None
        return None
```

Run: API `test_site_turn_ports.py`
Expected: PASS.

- [ ] **Step 6: Write the failing executor tests** `apps/api/tests/test_site_turn_executor.py`:

```python
"""The site executor (Lane B Task 12, Contract 7): persist under CAS, announce, remember."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from py_lumen_config import settings

from lumen_agent.site.harness import CANCELLED_SUMMARY, SiteTurnResult
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app


@pytest.fixture(autouse=True)
def _agent_workspace_in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "agent-workspace"
    monkeypatch.setattr(settings, "lumen_agent_trace_dir", None)
    monkeypatch.setattr(settings, "lumen_agent_workspace_root", root)
    return root


@pytest.fixture(autouse=True)
def _site_kit_built() -> None:
    # The persist runs Lane A's real write validation (the site-kit validator bundle).
    from site_kit_support import ensure_site_kit_dist

    ensure_site_kit_dist()


#: A site site-kit's validator passes with an empty brand (no clones, no images), so A2's write
#: validation accepts it: a shell, and one CtaBand whose button goes to the shell's destination.
SHELL = {"header": {"id": "header", "preparedFor": "Acme", "ctaLabel": "Book a demo",
                    "ctaHref": "https://seller.example/demo"},
         "footer": {"id": "footer", "legal": "© Seller"}}


def _site(doc_id: str, heading: str = "Hello") -> dict:
    return {"id": doc_id, "title": "S", "theme": {}, "shell": SHELL, "agent_sections": {},
            "pages": {"/": {"root": {"props": {"title": "S"}}, "content": [{"type": "CtaBand", "props": {
                "id": "c", "surface": "brand", "heading": heading, "buttonLabel": "Book a demo",
                "buttonHref": "https://seller.example/demo"}}]}}}


def _host(app, runner):
    from lumen_api.fleet_handler import DesignTurnHost

    return DesignTurnHost(site_turn_runner=runner, core=app.state.core, storage=app.state.storage,
                          engine_cache_root=app.state.engine_cache_root)


def _envelope(document_id: str, workspace_id: str, *, prompt: str = "Make the hero warmer.", bundle: dict | None = None):
    from clue_design.envelopes import DesignTurnEnvelope

    run_id = f"run_{uuid4().hex[:12]}"
    return DesignTurnEnvelope(kind="site_turn", work_id=uuid4(), workspace_id=workspace_id, run_id=run_id,
                              checkpoint_thread_id=run_id, document_id=document_id,
                              config={"request": {"prompt": prompt, "base_version": 0},
                                      "delegation_bundle": bundle or {"brief": "B"}, "leg": {"leg_id": "leg-1"}})


def _simulate_model_call(callbacks) -> None:
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, LLMResult

    collector = callbacks.handlers[0]
    run = uuid4()
    collector.on_chat_model_start({}, [[]], run_id=run, invocation_params={"model": "openai:test/model"})
    collector.on_llm_end(LLMResult(generations=[[ChatGeneration(message=AIMessage(content="ok"))]]), run_id=run)


def _run(app, store, document, runner, events, **envelope_kwargs):
    from lumen_api.main import execute_site_turn_job

    envelope = _envelope(document["id"], store.workspace_id, **envelope_kwargs)
    return execute_site_turn_job(envelope, store=store, host=_host(app, runner),
                                 event_sink=lambda event_type, data: events.append((event_type, data))), envelope


def _workspace(agent_root: Path, store, document_id: str) -> Path:
    from clue_design.sessions import design_session_id

    return agent_root / "sessions" / design_session_id(store.workspace_id, document_id) / "workspace"


def test_an_applied_site_turn_saves_one_version_and_announces_it(tmp_path, design_storage, _agent_workspace_in_tmp) -> None:
    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    store = HybridRepository()
    document = store.create_document(_site(f"doc_site_{uuid4().hex[:10]}"), doc_kind="site")
    seen: dict = {}

    def runner(prompt, *, document, workspace, run_id, callbacks):
        seen["prompt"] = prompt
        _simulate_model_call(callbacks)
        return SiteTurnResult("applied", "Warmed the hero.", _site(document["id"], "Warm hello"), None, [], [])

    events: list = []
    (status, response, event_type, _), _ = _run(app, store, document, runner, events)
    assert status == "succeeded" and event_type == "result"
    assert response["status"] == "applied" and response["doc_kind"] == "site"
    assert response["current_version"] == 1 and response["saved_version"] == 1
    assert len(response["model_calls"]) == 1 and response["session_manifest_sha256"]
    assert seen["prompt"] == "Make the hero warmer."  # the brief is brief.md, not a prompt block
    stored = store.require_document(document["id"])
    assert stored["current_version"] == 1 and stored["scene"]["pages"]["/"]["content"][0]["props"]["heading"] == "Warm hello"
    assert events == [("site_document_saved", {"document_id": document["id"], "version": 1})]
    assert all("operations" not in data for _, data in events)
    history = (_workspace(_agent_workspace_in_tmp, store, document["id"]) / "history.md").read_text()
    assert "## 1. Make the hero warmer.\n" in history and "- Saved: as version 1\n" in history


def test_a_site_turn_that_loses_the_version_race_saves_nothing(tmp_path, design_storage, _agent_workspace_in_tmp) -> None:
    """Review focus 1: a human saved while the request ran; the human's version stands."""

    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    store = HybridRepository()
    document = store.create_document(_site(f"doc_site_{uuid4().hex[:10]}"), doc_kind="site")

    def runner(prompt, *, document, workspace, run_id, callbacks):
        human = _site(document["id"], "Human edit")
        store.update_site_document(document["id"], human, intent="manual", checkpoint_label=None,
                                   operations=[{"kind": "replace_site", "site": human}],
                                   inverse_operations=[{"kind": "replace_site", "site": document["scene"]}],
                                   actor_kind="human", source="editor")
        return SiteTurnResult("applied", "Warmed the hero.", _site(document["id"], "Agent edit"), None, [], [])

    events: list = []
    (status, response, _, _), _ = _run(app, store, document, runner, events)
    assert status == "failed" and response["status"] == "conflicted"
    assert response["error"]["code"] == "site_turn.version_conflict" and response["saved_version"] is None
    assert store.require_document(document["id"])["scene"]["pages"]["/"]["content"][0]["props"]["heading"] == "Human edit"
    assert events == []
    history = (_workspace(_agent_workspace_in_tmp, store, document["id"]) / "history.md").read_text()
    assert "- Saved: no, the site changed while this request ran\n" in history


def test_a_cancelled_site_turn_saves_nothing_and_says_so(tmp_path, design_storage, _agent_workspace_in_tmp) -> None:
    """Review focus 4."""

    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    store = HybridRepository()
    document = store.create_document(_site(f"doc_site_{uuid4().hex[:10]}"), doc_kind="site")

    def runner(prompt, *, document, workspace, run_id, callbacks):
        return SiteTurnResult("failed", CANCELLED_SUMMARY, document["scene"], "cancelled_by_request", [], [])

    events: list = []
    (status, response, _, _), _ = _run(app, store, document, runner, events)
    assert status == "failed" and response["summary"] == CANCELLED_SUMMARY
    assert response["stop_reason"] == "cancelled_by_request" and response["error"]["code"] == "site_turn.cancelled_by_request"
    assert store.require_document(document["id"])["current_version"] == 0 and events == []
    history = (_workspace(_agent_workspace_in_tmp, store, document["id"]) / "history.md").read_text()
    assert "- Saved: no, it was stopped\n" in history


def test_an_unchanged_site_writes_no_version(tmp_path, design_storage, _agent_workspace_in_tmp) -> None:
    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    store = HybridRepository()
    document = store.create_document(_site(f"doc_site_{uuid4().hex[:10]}"), doc_kind="site")

    def runner(prompt, *, document, workspace, run_id, callbacks):
        return SiteTurnResult("applied", "Nothing needed changing.", document["scene"], None, [], [])

    events: list = []
    (status, response, _, _), _ = _run(app, store, document, runner, events)
    assert status == "succeeded" and response["outcome"] == "unchanged" and response["saved_version"] is None
    assert store.require_document(document["id"])["current_version"] == 0 and events == []


def test_the_session_snapshot_keeps_memory_and_leaves_out_regenerated_inputs(tmp_path, design_storage, _agent_workspace_in_tmp) -> None:
    """Review focus 5: a fresh worker gets plan.md, history.md and fetched/ back — never stale
    research, catalog or page files."""

    import shutil

    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    store = HybridRepository()
    document = store.create_document(_site(f"doc_site_{uuid4().hex[:10]}"), doc_kind="site")

    def first(prompt, *, document, workspace, run_id, callbacks):
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "plan.md").write_text("the plan")
        (workspace / "fetched").mkdir(exist_ok=True)
        (workspace / "fetched" / "story.md").write_text("evidence")
        (workspace / "research").mkdir(exist_ok=True)
        (workspace / "research" / "overview.md").write_text("research as of request 1")
        (workspace / "page.json").write_text("{}")
        (workspace / "work").mkdir(exist_ok=True)
        (workspace / "work" / "offload.md").write_text("compaction offload")
        return SiteTurnResult("applied", "Planned.", _site(document["id"], "One"), None, [], [])

    (status, response, _, _), _ = _run(app, store, document, first, [])
    assert status == "succeeded"
    manifest = json.loads(_blobs(app).read(response["session_manifest_sha256"]))
    assert {"workspace/plan.md", "workspace/history.md", "workspace/fetched/story.md"} <= set(manifest["files"])
    assert not any(key.startswith(("workspace/research/", "workspace/work/")) or key == "workspace/page.json"
                   for key in manifest["files"])

    shutil.rmtree(_workspace(_agent_workspace_in_tmp, store, document["id"]).parent)  # a fresh worker
    restored: dict = {}

    def second(prompt, *, document, workspace, run_id, callbacks):
        restored["plan"] = (workspace / "plan.md").read_text()
        restored["research"] = (workspace / "research" / "overview.md").exists()
        return SiteTurnResult("applied", "Done.", document["scene"], None, [], [])

    _run(app, store, store.require_document(document["id"]), second, [])
    assert restored == {"plan": "the plan", "research": False}


def _blobs(app):
    from conftest import make_blob_store

    return make_blob_store(app)


def test_a_site_the_write_refuses_saves_nothing_and_says_why(tmp_path, design_storage, _agent_workspace_in_tmp) -> None:
    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    store = HybridRepository()
    document = store.create_document(_site(f"doc_site_{uuid4().hex[:10]}"), doc_kind="site")

    def runner(prompt, *, document, workspace, run_id, callbacks):
        broken = _site(document["id"], "Warm hello")
        broken["pages"]["/"]["content"][0]["props"]["surface"] = "green"
        return SiteTurnResult("applied", "Warmed the hero.", broken, None, [], [])

    events: list = []
    (status, response, _, _), _ = _run(app, store, document, runner, events)
    assert status == "failed" and response["status"] == "failed"
    assert response["summary"].startswith("The website could not be saved: ") and "surface" in response["summary"]
    assert store.require_document(document["id"])["current_version"] == 0 and events == []
    history = (_workspace(_agent_workspace_in_tmp, store, document["id"]) / "history.md").read_text()
    assert "- Saved: no, the save was refused\n" in history


def test_a_non_site_document_is_refused(tmp_path, design_storage) -> None:
    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    store = HybridRepository()
    web = store.create_document({"id": f"doc_web_{uuid4().hex[:8]}", "title": "W", "theme": {}, "pages": [], "assets": {}},
                                doc_kind="web")
    (status, response, _, _), _ = _run(app, store, web, lambda *a, **k: pytest.fail("must not run"), [])
    assert status == "failed" and response["diagnostics"][0]["code"] == "site_turn.not_a_site"


def test_the_prompt_carries_the_drift_note_and_the_assignment_never_the_brief(tmp_path, design_storage) -> None:
    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    store = HybridRepository()
    document = store.create_document(_site(f"doc_site_{uuid4().hex[:10]}"), doc_kind="site")
    seen: dict = {}

    def runner(prompt, *, document, workspace, run_id, callbacks):
        seen["prompt"] = prompt
        return SiteTurnResult("applied", "ok", document["scene"], None, [], [])

    bundle = {"brief": "THE STANDING BRIEF", "artifact": {"position": 1, "count": 2, "title": "Morgan site", "note": ""}}
    _run(app, store, document, runner, [], prompt="Add a pricing page.", bundle=bundle)
    assert "CURRENT DOCUMENT ASSIGNMENT" in seen["prompt"] and seen["prompt"].endswith("Add a pricing page.")
    assert "THE STANDING BRIEF" not in seen["prompt"]
```

Run: API `test_site_turn_executor.py`
Expected: FAIL at import — `ImportError: cannot import name 'execute_site_turn_job'` (after the
`lumen_agent.site.harness` import succeeds).

- [ ] **Step 7: Add the request model** to `models.py` after `WebTurnRequest`:

```python
class SiteTurnRequest(BaseModel):
    """A Puck site agent turn (Lane B, Contract 7) against one stored site document.

    ``base_version`` records what the platform saw when it offered the turn; the executor re-reads
    the document and persists under CAS on the version it actually read.
    """

    prompt: str
    base_version: int = 0
```

- [ ] **Step 8: Add the executor to `main.py`.** Import `SiteTurnRequest` with the other `.models`
imports, and add after `_execute_web_turn_job`:

```python
def _site_turn_response(result: Any, outcome: Any, *, base_version: int) -> JsonObject:
    """The site turn's result_json (Contract 7), from the runtime's result and the write's outcome."""

    common = {"schema_version": 1, "doc_kind": "site", "stop_reason": result.stop_reason,
              "operations": [], "preview_paths": []}
    if result.status != "applied":
        code = f"site_turn.{result.stop_reason or 'failed'}"
        failed = failed_agent_turn_response(code, result.summary, "; ".join(result.errors)[:500])
        return {**failed, **common, "current_version": base_version, "saved_version": None,
                "error": {"code": code, "message": result.summary}}
    if outcome is None:
        return {**common, "status": "applied", "outcome": "unchanged", "summary": result.summary,
                "current_version": base_version, "saved_version": None}
    if outcome.status == "saved":
        return {**common, "status": "applied", "outcome": "saved", "summary": result.summary,
                "current_version": outcome.version, "saved_version": outcome.version}
    if outcome.status == "conflicted":
        conflicted = conflicted_web_turn_response(base_version, int(outcome.version or base_version))
        return {**conflicted, **common, "saved_version": None,
                "error": {"code": "site_turn.version_conflict", "message": conflicted["summary"]}}
    message = f"The website could not be saved: {outcome.detail or 'the write was refused'}"
    failed = failed_agent_turn_response("site_turn.write_refused", message, outcome.detail or "")
    return {**failed, **common, "current_version": base_version, "saved_version": None,
            "error": {"code": "site_turn.write_refused", "message": message}}


def run_site_agent_turn(
    document: JsonObject,
    prompt: str,
    *,
    user_message: str,
    inputs: Any,
    persist: Any,
    workspace_id: str,
    run_id: str,
    session_id: str,
    session_manifest: JsonObject | None,
    blobs: DesignBlobStore,
    checkpointer: Any = None,
    cancel_requested: Any = None,
    callbacks: Any = None,
    event_sink: Any = None,
    runner: Any = None,
) -> JsonObject:
    """One Puck site request: restore the session folder, run, persist under CAS, write history,
    snapshot memory. Never raises — every failure folds into a failed response.

    Fresh session per request (founder ruling 2026-10-11): the LangGraph thread is ``run_id``; the
    agent's memory across requests is the session folder's plan.md, history.md and fetched/, which
    are synced; everything the view rebuilds is left out of the snapshot.
    """

    try:
        import functools

        from lumen_agent.config import AgentRuntimeConfig
        from lumen_agent.session_sync import restore_session, snapshot_session
        from lumen_agent.site.harness import run_site_turn
        from lumen_agent.site.workspace import (
            SESSION_REGENERATED,
            append_history,
            history_count,
            saved_line,
            site_changes,
            site_pages_of,
        )
    except Exception as error:
        return failed_agent_turn_response(
            "agent_runtime.unavailable", "Agent runtime dependencies are not available to the API process.", str(error)
        )
    config = replace(AgentRuntimeConfig.from_env(repo_root()), session_id=session_id, run_id=run_id)
    session_dir = config.session_dir()
    workspace = session_dir / "workspace"
    try:
        if not session_dir.exists() and session_manifest is not None:
            restored = restore_session(session_dir, session_manifest, read_blob=blobs.read_blob, history_file=None)
            api_logger.info("design_session.restored", session_id=session_id, files=restored)
        if runner is not None:
            result = runner(prompt, document=document, workspace=workspace, run_id=run_id, callbacks=callbacks)
        else:
            from lumen_agent.llm import assert_model_supports_image_input

            assert_model_supports_image_input(config.orchestrator_model, base_url=config.agent_base_url,
                                              api_key=config.agent_api_key)
            result = run_site_turn(
                prompt, config=config, inputs=inputs, workspace=workspace, site=document["scene"], run_id=run_id,
                checkpointer=checkpointer, thread_id=run_id, cancel_requested=cancel_requested,
                callbacks=callbacks, event_sink=event_sink,
            )
    except Exception as error:
        return failed_agent_turn_response("agent_runtime.failed", "Site agent failed before returning a result.", str(error))

    base_version = int(document["current_version"])
    outcome = persist(result.site) if result.status == "applied" and result.site != document["scene"] else None
    response = _site_turn_response(result, outcome, base_version=base_version)
    saved = outcome is not None and outcome.status == "saved"
    workspace.mkdir(parents=True, exist_ok=True)
    append_history(
        workspace,
        number=history_count(workspace) + 1,
        request=user_message,
        changes=site_changes(site_pages_of(document["scene"]), site_pages_of(result.site)) if saved else [],
        shell_changed=saved and document["scene"].get("shell") != result.site.get("shell"),
        reply=result.summary,
        saved=saved_line(status=result.status, stop_reason=result.stop_reason,
                         outcome_status=outcome.status if outcome else None,
                         version=outcome.version if outcome else None),
    )
    shutil.rmtree(workspace / "work", ignore_errors=True)
    return _stamp_session_manifest(
        response, session_dir=session_dir, history_file=None, session_id=session_id, blobs=blobs,
        snapshot_session=functools.partial(snapshot_session, exclude=SESSION_REGENERATED),
    )


def execute_site_turn_job(
    envelope: Any,
    *,
    store: HybridRepository,
    host: Any,
    event_sink: Any,
    checkpointer: Any = None,
    lease_generation: Optional[int] = None,
    spend_drain: Any = None,
    callbacks: Any = None,
    session_continued: bool = False,
) -> Tuple[str, JsonObject, str, JsonObject]:
    """One Puck site turn under its own spend scope and model-call collector (Contract 7).

    ``session_continued`` is accepted for the fleet's one call shape and ignored: a site request
    always opens a fresh thread (its memory is the session folder)."""

    from . import spend as _spend

    del session_continued
    collector, turn_callbacks = _turn_model_call_collector(callbacks)
    with _spend.spend_scope(_turn_spend_stamp(envelope), drain_fn=spend_drain) as scope:
        try:
            status, response, event_type, event_data = _execute_site_turn_job(
                envelope, store=store, host=host, event_sink=event_sink, checkpointer=checkpointer,
                lease_generation=lease_generation, callbacks=turn_callbacks,
            )
            return status, _with_model_calls(response, collector), event_type, event_data
        finally:
            _drain_spend(scope)


def _execute_site_turn_job(
    envelope: Any,
    *,
    store: HybridRepository,
    host: Any,
    event_sink: Any,
    checkpointer: Any = None,
    lease_generation: Optional[int] = None,
    callbacks: Any = None,
) -> Tuple[str, JsonObject, str, JsonObject]:
    from .site_turn_ports import (
        DurableSiteAssetPort,
        DurableSiteVersionPort,
        PlatformSiteRenderer,
        SitePersistOutcome,
    )
    from .site_workspace_view import build_site_turn_inputs

    run_subject = DesignRunSubject(run_id=envelope.run_id, lease_generation=lease_generation)
    payload = SiteTurnRequest.model_validate(envelope.config.get("request") or {})
    leg_block = envelope.config.get("leg") or {}
    bundle = envelope.config.get("delegation_bundle")
    bundle = bundle if isinstance(bundle, dict) else {}
    workspace_id = envelope.workspace_id
    document_id = str(envelope.document_id)
    platform_reads = None
    if leg_block:
        reads_factory = getattr(host, "platform_reads_factory", None)
        if callable(reads_factory):
            try:
                platform_reads = reads_factory(envelope)
            except Exception:
                api_logger.warning("design_turn.platform_reads_unavailable", run_id=envelope.run_id, exc_info=True)
    try:
        doc = store.require_document(document_id)
        if doc.get("doc_kind") != "site":
            failed = failed_agent_turn_response(
                "site_turn.not_a_site", "This turn was addressed to a document that is not a website.",
                f"document {document_id} is {doc.get('doc_kind')!r}",
            )
            return "failed", {**failed, "doc_kind": "site"}, "error", {"message": failed["summary"]}
        base_version = int(doc["current_version"])
        drift_note = _document_drift_note(store, document_id=document_id, current_version=base_version) if leg_block else None
        artifact = bundle.get("artifact") if isinstance(bundle.get("artifact"), dict) else None
        # The brief rides in brief.md (the spike's way); the prompt is the user's words, the drift
        # note when a human moved the site, and the multi-document assignment line.
        prompt = render_leg_turn_prompt(bundle=None, history=None, prompt=payload.prompt,
                                        drift_note=drift_note, artifact=artifact)
        blobs = _turn_blob_store(host, workspace_id)
        invocations = _turn_design_tools(host, run_subject)

        def persist(site: JsonObject) -> Any:
            try:
                invocations.invoke(
                    "design_write_site",
                    {"document_id": document_id, "site": site, "expected_base_version": base_version,
                     "intent": payload.prompt[:120], "actor_kind": "agent", "source": "agent"},
                    workspace_id=workspace_id, actor="agent", actor_id=envelope.run_id,
                )
            except WebDocumentVersionConflict as conflict:
                return SitePersistOutcome("conflicted", int(conflict.current), None)
            except SiteDocumentInvalid as refused:
                return SitePersistOutcome("refused", None, "; ".join(refused.errors)[:500])
            except PreconditionFailed as refused:
                return SitePersistOutcome("refused", None, "; ".join(f.message for f in refused.failures)[:500])
            except TurnCancelled:
                # Stop pressed between the agent's last step and the save: nothing is written.
                return SitePersistOutcome("refused", None, "it was stopped")
            return SitePersistOutcome("saved", int(store.require_document(document_id)["current_version"]), None)

        runner = getattr(host, "site_turn_runner", None)
        inputs = None
        if runner is None:
            cache_dir = _host_engine_cache_root(host, workspace_id)
            brand_kit, _source, kit_assets, font_spec = resolve_web_turn_brand_kit(doc["scene"], blobs)
            inputs = build_site_turn_inputs(
                document=doc, store=store, blobs=blobs, cache_dir=cache_dir, platform_reads=platform_reads,
                account_card=envelope.config.get("account_card"), delegation_bundle=bundle,
                brand_kit=brand_kit, kit_assets=kit_assets, font_spec=font_spec,
                asset_library=pinned_asset_library(store, envelope.run_id),
                assets=DurableSiteAssetPort(blobs=blobs, cache_dir=cache_dir, core=_turn_core(host),
                                            invocations=invocations, run_id=envelope.run_id),
                site_versions=DurableSiteVersionPort(store, document_id),
                renderer=PlatformSiteRenderer(read_blob=blobs.read_blob),
                logo_cache=DurableLogoFamilyCache(blobs=blobs),
            )
        response = run_site_agent_turn(
            doc, prompt, user_message=payload.prompt, inputs=inputs, persist=persist, workspace_id=workspace_id,
            run_id=envelope.run_id, session_id=design_session_id(workspace_id, document_id),
            session_manifest=_session_manifest(store, blobs, document_id=document_id), blobs=blobs,
            checkpointer=checkpointer, cancel_requested=_run_cancel_probe(store, envelope.run_id),
            callbacks=callbacks, event_sink=event_sink, runner=runner,
        )
        if response.get("saved_version") is not None and event_sink is not None:
            # Contract 7: the forwarder turns this into the chat's design.checkpoint frame.
            event_sink("site_document_saved", {"document_id": document_id, "version": int(response["saved_version"])})
        status = "succeeded" if response.get("status") == "applied" else "failed"
        return status, {**response, "doc_kind": "site"}, "result", {"status": response.get("status")}
    except Exception as error:  # pragma: no cover - defensive
        failed = failed_agent_turn_response("agent_runtime.failed", "Website turn crashed before returning a result.", str(error))
        return "failed", {**failed, "doc_kind": "site"}, "error", {"message": str(error)}
```

`main.py` already imports `replace` from `dataclasses` (`:24`); add `import shutil` beside its other
stdlib imports (`:3-21`) — it is not imported today. `functools` is imported inside
`run_site_agent_turn` above. Import `SiteDocumentInvalid` from `.site_doc_validate` and
`TurnCancelled` from `lumen_agent.cancellation` inside `_execute_site_turn_job` (beside its other
local imports).

Fill Lane A's two loader seams (contract: Lane A Task 12 ships them refusing; B2 and B6 replace
them). In `create_app`, replace `app.state.site_brand_loader = brand_loader_not_composed` with

```python
    # Lane B2: the site's BrandData from its pinned kit (lumen_api.site_brand, the one builder).
    app.state.site_brand_loader = site_brand_loader_for(lambda workspace_id: engine_cache_dir(workspace_id))
```

(import `site_brand_loader_for` from `.site_workspace_view`; the lambda defers `engine_cache_dir`,
which `create_app` defines further down). In `_turn_design_tools`, add to the
`design_tool_host(...)` call, after `compile_fn=lambda: compile_custom_component,`:

```python
            # Lane B (Wave 2): the site turn's persist validates through design_write_site, which
            # needs the site's brand and its agent-section modules (Task 15 replaces the second).
            site_brand_loader=lambda: site_brand_loader_for(lambda ws: _host_engine_cache_root(host, ws)),
            site_section_loader=lambda: sections_not_stored,
```

(`sections_not_stored` from `.site_doc_inputs`: a site with no agent sections passes; one that
places a section is refused until Task 15).

- [ ] **Step 9: Give the app and the embedded worker the test seam.** In `create_app`, after
`app.state.web_turn_runner = None` (`:848`), add:

```python
    # Puck site turn test seam (Lane B): a callable (prompt, *, document, workspace, run_id,
    # callbacks) -> SiteTurnResult that replaces the site runtime. None = live.
    app.state.site_turn_runner = None
```

and in the embedded `host()` (`:594`), add `site_turn_runner=app.state.site_turn_runner,` after
`web_turn_runner=…`.

- [ ] **Step 10: Write the failing fleet tests** `apps/api/tests/test_site_fleet_dispatch.py`:

```python
"""Fleet dispatch of a site turn (Lane B Task 12): an explicit map, the capability, the trace."""

from __future__ import annotations

import pytest

from lumen_api import fleet_handler
from lumen_api.fleet_handler import DesignJobWorkHandler, DesignTurnJobError, executor_for_kind


def test_each_turn_kind_has_its_own_executor_and_an_unknown_kind_is_refused() -> None:
    from lumen_api.main import execute_agent_turn_job, execute_site_turn_job, execute_web_turn_job

    assert executor_for_kind("agent_turn") is execute_agent_turn_job
    assert executor_for_kind("web_turn") is execute_web_turn_job
    assert executor_for_kind("site_turn") is execute_site_turn_job
    with pytest.raises(DesignTurnJobError):
        executor_for_kind("poster_turn")  # never the web executor by default


def test_the_turn_pool_serves_site_turns_and_the_ingestion_pool_does_not() -> None:
    assert "site_turn" in DesignJobWorkHandler().task_capabilities[0].supported
    assert "site_turn" not in DesignJobWorkHandler(ingestion_only=True).task_capabilities[0].supported


def test_a_site_turn_is_one_named_trace_grouped_by_its_document() -> None:
    name, as_type, keys, session_key, tags = fleet_handler._TRACE_SHAPES["site_turn"]
    assert (name, as_type, session_key) == ("design.turn", "agent", "document_id")
    assert "run_id" in keys and "document_id" in keys and tags == ("kind",)
```

Run: API `test_site_fleet_dispatch.py`
Expected: FAIL at import — `ImportError: cannot import name 'executor_for_kind'`.

- [ ] **Step 11: Change `fleet_handler.py`.** Add the field to `DesignTurnHost` after
`web_turn_runner`:

```python
    #: Puck site turn test seam (Lane B): replaces the site runtime; see main.run_site_agent_turn.
    site_turn_runner: Any = None
```

Widen the turn pool at `:213` to `{"agent_turn", "web_turn", "site_turn"}`. After the
`_TRACE_SHAPES` dict comprehension add:

```python
#: A site turn opens a fresh thread per request (founder ruling 2026-10-11), so its Langfuse session
#: is its DOCUMENT, which groups a site's requests the way one continued thread groups a web page's.
_TRACE_SHAPES["site_turn"] = (
    "design.turn",
    "agent",
    ("run_id", "document_id", "project_id"),
    "document_id",
    ("kind",),
)
```

Add the map above `_execute_turn`:

```python
def executor_for_kind(kind: str) -> Any:
    """The executor for one design turn kind. An unknown kind is refused, never run as web: the old
    ``else execute_web_turn_job`` sent every non-scene envelope to the web executor."""

    from .main import execute_agent_turn_job, execute_site_turn_job, execute_web_turn_job

    executors = {
        DesignRunKind.AGENT_TURN.value: execute_agent_turn_job,
        DesignRunKind.WEB_TURN.value: execute_web_turn_job,
        DesignRunKind.SITE_TURN.value: execute_site_turn_job,
    }
    try:
        return executors[kind]
    except KeyError:
        raise DesignTurnJobError(f"no executor for design turn kind {kind!r}") from None
```

In `_execute_turn`, delete the line `from .main import execute_agent_turn_job, execute_web_turn_job`,
add `executor = executor_for_kind(envelope.kind)` as the function's first statement (before
`def sink`), and delete the `executor = (execute_agent_turn_job if … else execute_web_turn_job)`
assignment inside the `with` block. A raise here is contained by `_handle` and terminalizes the row
(`fleet_handler.py:378-399`).

- [ ] **Step 12: Run the design API tests.**

Run: API `test_site_fleet_dispatch.py`, then API `test_site_turn_executor.py`, then API
`test_web_turns.py -k "leg or route_shaped"` (the web executor is unchanged).
Expected: PASS, PASS, PASS.

- [ ] **Step 13: Commit.**

```bash
git add subsystems/clue-design/apps/api/lumen_api/models.py subsystems/clue-design/apps/api/lumen_api/site_turn_ports.py subsystems/clue-design/apps/agent_runtime/lumen_agent/session_sync.py subsystems/clue-design/apps/api/lumen_api/main.py subsystems/clue-design/apps/api/lumen_api/fleet_handler.py subsystems/clue-design/apps/agent_runtime/tests/test_session_sync.py subsystems/clue-design/apps/api/tests/test_site_turn_ports.py subsystems/clue-design/apps/api/tests/test_site_turn_executor.py subsystems/clue-design/apps/api/tests/test_site_fleet_dispatch.py
git commit -m "site executor: one Puck request per run, persisted through design_write_site under CAS, announced as site_document_saved, memory synced"
```

---
### Task 13: The platform side of a site turn — envelope, account card, labels, summaries, the checkpoint frame (B5, platform side)

**Files:**
- Modify: `platform/api/clue_api/design_leg_wiring.py`: delete `DESIGN_LEG_SITE_RUNTIME_NOT_COMPOSED`
  (`:177-180`), `SiteRuntimeNotComposedError` (`:183-194`), their two `__all__` entries
  (`:128`, `:134`) and the `except SiteRuntimeNotComposedError` branch (`:1570-1585`); change the
  G2 account card (`:1515-1520`), `_exit_judge_artifact_lines` (`:338`), `_assistant_summary`
  (`:869`), `batch_summary` (`:972`) and `_envelope` (`:2635-2700`)
- Modify: `platform/api/clue_api/design_event_forwarder.py:55-62` (`_FORWARDED_DESIGN_EVENTS`)
- Test: `tests/api/test_site_leg_birth_db.py` (replace the refusal test),
  `tests/api/test_site_turn_summaries.py` (new), `tests/api/test_site_checkpoint_forwarding.py` (new)

**Interfaces:**
- Consumes: `clue_design.envelopes.DesignTurnEnvelope(kind="site_turn")` (Wave 1);
  `TurnEventType.DESIGN_CHECKPOINT`; the executor's result keys (Task 12).
- Produces: a site leg turn dispatches `DesignTurnEnvelope(kind="site_turn",
  checkpoint_thread_id=<run id>, config={"request": {"prompt", "base_version"}, "delegation_bundle",
  "history", "leg", "account_card"?})`; `site_document_saved` → `design.checkpoint {document_id,
  version}` on the leg's thread.

- [ ] **Step 1: Replace the Wave 1 refusal test** in `tests/api/test_site_leg_birth_db.py`. Delete
`test_a_site_document_turn_refuses_until_the_site_runtime_lands` and add (it reuses the file's
`_seed_site_leg`, `_FakeLane`, `_submit_message`, `_run_turn`):

```python
from clue_api.design_leg_wiring import _exit_judge_artifact_lines, design_leg_run_id
from datetime import UTC, datetime

#: What the site executor returns for a saved request (Contract 7), with one collected model call.
APPLIED_SITE_RESULT: dict[str, Any] = {
    "schema_version": 1,
    "status": "applied",
    "outcome": "saved",
    "summary": "Built the landing page.",
    "doc_kind": "site",
    "current_version": 1,
    "saved_version": 1,
    "stop_reason": None,
    "model_calls": [{
        "run_id": "8f0f1f51-0b5d-4a43-9d39-1d3c5d2f0a11", "sequence": 1,
        "requested_model": "openai:test/model", "answering_model": "test/model", "status": "completed",
        "role": "design_site", "input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 0,
        "cost_cents": "0.5", "cost_source": "gateway", "langfuse_trace_id": None,
        "langfuse_observation_id": None, "latency_ms": 12.0, "error_code": None,
        "started_at": datetime(2026, 10, 11, 9, 0, tzinfo=UTC).isoformat(),
        "completed_at": datetime(2026, 10, 11, 9, 0, 1, tzinfo=UTC).isoformat(),
    }],
}


def test_a_site_document_leg_dispatches_a_site_turn_on_a_fresh_thread(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """Contract 7: doc_kind='site' -> kind='site_turn'; fresh session per request (thread = run);
    the summary names the website; the run's model calls reach agent_model_call."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds, document = await _seed_site_leg(conn, storage_root=tmp_path, label="siteturn")
            with hermetic_flag_env():
                registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            lane = _FakeLane(conn_factory=seeds["conn_factory"], result=APPLIED_SITE_RESULT)
            submission = await _submit_message(conn, seeds, label="siteturn", message="Build the landing page.")
            await _run_turn(conn, seeds, registry, lane, submission)

            envelope = lane.envelopes[0]
            run_id = design_leg_run_id(submission.turn_id)
            assert envelope.kind == "site_turn" and envelope.document_id == document["id"]
            assert envelope.checkpoint_thread_id == envelope.run_id == run_id
            assert envelope.config["request"] == {
                "prompt": "Build the landing page.", "base_version": document["current_version"]}
            assert "ad_lane" not in envelope.config and "design_memory" not in envelope.config
            assert "document_base_version" not in envelope.config["leg"]
            kind = (await conn.execute(
                text("SELECT kind FROM design_agent_run WHERE run_id = :run AND workspace_id = :ws"),
                {"run": run_id, "ws": seeds["workspace_id"]},
            )).scalar_one()
            assert str(kind) == "site_turn"
            reply = (await conn.execute(
                text("SELECT role FROM agent_thread_message WHERE workspace_id = :ws AND thread_id = :t "
                     "ORDER BY sequence"),
                {"ws": seeds["workspace_id"], "t": seeds["thread_id"]},
            )).scalars().all()
            assert list(reply)[-1] == "assistant"
            calls = (await conn.execute(
                text("SELECT count(*) FROM agent_model_call WHERE turn_id = :turn"), {"turn": submission.turn_id}
            )).scalar_one()
            assert int(calls) == 1

    run_async(scenario())


def test_the_exit_judge_calls_a_site_a_web_page(tmp_path: Path, migrated_db: bool) -> None:  # noqa: F811
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds, document = await _seed_site_leg(conn, storage_root=tmp_path, label="sitelabel")
            lines = await _exit_judge_artifact_lines(
                conn, workspace_id=seeds["workspace_id"],
                leg_documents=[{"document_id": document["id"], "doc_kind": "site",
                                "title": "Harbor & Sage", "position": 0}],
            )
            assert lines[0].startswith('1. "Harbor & Sage" (web page)')

    run_async(scenario())
```

Run: PLATFORM `tests/api/test_site_leg_birth_db.py`
Expected: FAIL — `test_a_site_document_leg_dispatches_a_site_turn_on_a_fresh_thread` fails with
`failure_code == "design_leg_site_runtime_not_composed"` (no envelope dispatched: `IndexError`),
and the label test fails (`(scene ad)`).

- [ ] **Step 2: Write the failing summary tests** `tests/api/test_site_turn_summaries.py`:

```python
"""A site turn's thread record reads like a website's (Contract 7), never a scene ad's."""

from __future__ import annotations

from clue_api.design_leg_wiring import _assistant_summary, batch_summary


def test_a_saved_site_turn_names_the_website_and_its_version() -> None:
    run = {"status": "succeeded", "document_id": "doc_1",
           "result": {"doc_kind": "site", "status": "applied", "current_version": 3, "summary": "Built the page."}}
    assert _assistant_summary(run) == "Design turn applied on website document doc_1 (now version 3): Built the page."


def test_a_batch_line_for_a_site_does_not_repeat_its_version() -> None:
    run = {"status": "succeeded", "document_id": "doc_1",
           "result": {"doc_kind": "site", "status": "applied", "current_version": 3, "summary": "Done."}}
    line = batch_summary([({"title": "SCSD page"}, run)])
    assert line == "SCSD page: Design turn applied on website document doc_1 (now version 3): Done."
```

Run: PLATFORM `tests/api/test_site_turn_summaries.py`
Expected: FAIL — the site run gets the scene summary ("Design turn applied.") and the batch line
appends a second "(now version 3)".

- [ ] **Step 3: Write the failing forwarder test** `tests/api/test_site_checkpoint_forwarding.py`:

```python
"""Contract 7: a saved site becomes the chat's design.checkpoint frame; nothing else a site turn
emits becomes a frame (and none of it carries operations)."""

from __future__ import annotations

from types import SimpleNamespace

from clue_api.chat.turn_events import TurnEventType
from clue_api.design_event_forwarder import _forwarded_frame
from clue_core import RunEventTopic


def _row(event_type: str, data: dict) -> SimpleNamespace:
    return SimpleNamespace(topic=RunEventTopic.DESIGN_RUN_EVENT.value,
                           payload={"event_type": event_type, "data": data})


def test_a_saved_site_becomes_a_checkpoint_frame() -> None:
    frame = _forwarded_frame(_row("site_document_saved", {"document_id": "doc_1", "version": 4, "x": 1}),
                             document_id="doc_1")
    assert frame == (TurnEventType.DESIGN_CHECKPOINT, {"document_id": "doc_1", "version": 4})


def test_site_progress_events_stay_on_the_design_stream() -> None:
    for event_type in ("site_valid", "site_render", "site_generate_image", "site_section_written"):
        assert _forwarded_frame(_row(event_type, {"route": "/"}), document_id="doc_1") is None
```

Run: PLATFORM `tests/api/test_site_checkpoint_forwarding.py`
Expected: FAIL — the first test gets `None`.

- [ ] **Step 4: Forward the saved-site event.** In `design_event_forwarder.py`, after
`_SCENE_CHECKPOINT_EVENT` add:

```python
#: The site executor's one announcement (Lane B, Contract 7): a request saved the site at
#: `version`. It becomes the same design.checkpoint frame a scene checkpoint does, so the
#: frontend's existing designRefreshForEvent reloads the canvas. Never an `operations` key.
_SITE_DOCUMENT_SAVED_EVENT: Final = "site_document_saved"
```

and add to `_FORWARDED_DESIGN_EVENTS`:

```python
    _SITE_DOCUMENT_SAVED_EVENT: (TurnEventType.DESIGN_CHECKPOINT, ("document_id", "version")),
```

Run: PLATFORM `tests/api/test_site_checkpoint_forwarding.py`
Expected: PASS.

- [ ] **Step 5: Change `design_leg_wiring.py`.** Lane A's Task 9 owns the label, summary and
account-card changes (ruling R8) and must have landed before this task. Confirm it:

```bash
grep -n "def design_kind_label\|def _card_account_id" platform/api/clue_api/design_leg_wiring.py
```

Expected: both are printed. If either is missing, stop: Lane A Task 9 has not landed. Then do only
(a) and (f) below; (b)–(e) are kept as the record of what Lane A's Task 9 already did, and this
task's summary tests (Step 2) pass against Lane A's code. Do not edit those lines here.

(a) Delete `DESIGN_LEG_SITE_RUNTIME_NOT_COMPOSED`, `SiteRuntimeNotComposedError`, their `__all__`
entries and the `except SiteRuntimeNotComposedError as exc:` branch in `run_leg_turn` (the
`try/except` keeps its other branches).

(b) `_exit_judge_artifact_lines` (`:338`):

```python
        kind = "web page" if document.get("doc_kind") in ("web", "site") else "scene ad"
```

(c) G2 account card (`:1515-1520`): a site page born for an account gets its card like a web page:

```python
                account_id = (
                    row.get("account_id")
                    if row is not None and row.get("doc_kind") in ("web", "site")
                    else None
                )
```

(d) `_assistant_summary` (`:869`):

```python
    if str(result.get("doc_kind") or "") in ("web", "site"):
        return _web_turn_summary(run, result)
```

(e) `batch_summary` (`:972`):

```python
            if str(result.get("doc_kind") or "") not in ("web", "site") and stands_at:
```

(f) `_envelope`: replace the site refusal and the two-way kind choice with

```python
        doc_kind = document.get("doc_kind")
        # B1 + Lane B (Contract 7): the leg document's kind decides which design runtime executes
        # the turn. A scene document (or no pinned document at all) keeps the shipped
        # ``agent_turn`` request byte-for-byte.
        kind: Literal["agent_turn", "web_turn", "site_turn"] = (
            "site_turn" if doc_kind == "site" else "web_turn" if doc_kind == "web" else "agent_turn"
        )
        if kind == "site_turn":
            # Fresh session per request (founder ruling 2026-10-11): the site agent's thread is this
            # run; its memory across requests is the session folder (plan.md, history.md,
            # fetched/), which the design side syncs.
            thread_id = run_id
```

and make the request a three-way branch, adding before `if kind == "web_turn":`

```python
        if kind == "site_turn":
            request = {
                "prompt": message_text,
                # The executor re-reads the document and persists under CAS on the version it read.
                "base_version": int(document.get("current_version") or 0),
            }
        elif kind == "web_turn":
```

(the existing `if kind == "web_turn":` becomes `elif`; its body and the scene `else:` are
unchanged). `web_targets` is already computed only when `kind == "web_turn"`, and the scene-only
blocks (`document_base_version`, `ad_lane`, `design_memory`) are already gated on
`kind == "agent_turn"`.

- [ ] **Step 6: Run the platform tests.**

Run: PLATFORM `tests/api/test_site_leg_birth_db.py`, PLATFORM `tests/api/test_site_turn_summaries.py`,
then the existing leg suites:

```bash
set -a; source .env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_trenton_wave1"; .venv/bin/python -m pytest tests/api/test_genweb_web_turn_dispatch_db.py tests/api/test_genad_leg_document_birth_db.py tests/design/test_design_checkpoint_forwarding.py -q -o addopts="" --ignore-glob='*_live.py'
```

Expected: PASS for all (web and scene legs unchanged).

- [ ] **Step 7: Commit.**

```bash
git add platform/api/clue_api/design_leg_wiring.py platform/api/clue_api/design_event_forwarder.py tests/api/test_site_leg_birth_db.py tests/api/test_site_turn_summaries.py tests/api/test_site_checkpoint_forwarding.py
git commit -m "design legs: a site document runs a site_turn on a fresh thread, reads like a website, and its save reaches the chat as design.checkpoint"
```

---
### Task 13a: The marketer's selection reaches the site agent (B5; controller ruling R9; approved text T15)

The editor turns a selected section, field, header or footer into an annotation chip whose ref is a
`design_node` with object id `site:<route>#<componentId>[.<field>]` or `site:shell#header|footer`
(Lane C Task 11), and Lane A Task 14 lets the composer accept those refs on a site document. As
first planned nothing carried them past the composer, so a request like "make this warmer" reached
the site agent with no "this". The web lane carries its refs as `target_node_ids` + `target_notes`
(`design_leg_wiring.py:2655,2688-2697`) and its prompt names each one
(`lumen_api/main.py:9528-9681`). This task does the same for a site, more simply: the request
carries `targets: [{object_id, note}]` in submission order (only when the person pointed at
something), and the executor appends one plain block (T15) after the person's words.

The envelope does **not** re-check the targets against the stored site. The composer already did
at submission (Lane A Task 14); a part deleted since then reaches the agent, whose block tells it to
say so — the same footing as the web lane's `resolve_web_targets`, which never reads the document.

**Files:**
- Modify: `platform/api/clue_api/design_leg_wiring.py` (`_envelope`, the `site_turn` request)
- Modify: `subsystems/clue-design/apps/api/lumen_api/models.py` (`SiteTurnTarget`; `SiteTurnRequest.targets`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py` (`execute_site_turn_job`: append the block)
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/site/workspace.py` (`targets_block`)
- Test: `tests/api/test_site_leg_birth_db.py`, `subsystems/clue-design/apps/agent_runtime/tests/test_site_workspace.py`,
  `subsystems/clue-design/apps/api/tests/test_site_turn_executor.py`

**Interfaces:**
- Consumes: Task 12's `SiteTurnRequest`, `execute_site_turn_job` and its test helpers (`_envelope`,
  `_run`, `_site`); Task 13's site branch of `_envelope` and `APPLIED_SITE_RESULT`; T15 (Task 0).
- Produces:
  - the site request's optional key `targets: [{"object_id": str, "note": str | None}]`, present
    only when at least one `design_node` ref rides the turn (a targetless request keeps
    `{"prompt", "base_version"}` byte for byte);
  - `models.SiteTurnTarget(object_id: str, note: Optional[str] = None)`,
    `models.SiteTurnRequest.targets: list[SiteTurnTarget]` (default empty);
  - `lumen_agent.site.workspace.targets_block(targets: Sequence[Mapping[str, Any]]) -> str` (`""`
    for no targets).

- [ ] **Step 1: Confirm T15 is approved.** Read `_memory/2026-10-11-lane-b-site-agent.md`, section
  "Founder text review". If T15 was edited, use the founder's words in Step 6 and in Step 2's
  expected strings. If it was declined, stop and report: the selection then needs another way to
  reach the agent, which is the founder's call.

- [ ] **Step 2: Write the failing block test.** Append to
  `apps/agent_runtime/tests/test_site_workspace.py` (add `targets_block` to its import from
  `lumen_agent.site.workspace`):

```python
def test_the_selection_block_names_each_part_in_order_with_its_note() -> None:
    block = targets_block([
        {"object_id": "site:/analysis#analysis-hero.title", "note": "1. Make it warmer."},
        {"object_id": "site:shell#header", "note": None},
        {"object_id": "site:shell#footer.ctaLabel", "note": "2. Say book a call"},
        {"object_id": "site:/#proof", "note": ""},
    ])
    assert block == (
        "The person also pointed at parts of the site:\n"
        '- Page /analysis, the section with id "analysis-hero", its "title" field. Their note: "1. Make it warmer."\n'
        "- The header. (No note.)\n"
        '- The footer, its "ctaLabel" field. Their note: "2. Say book a call"\n'
        '- Page /, the section with id "proof". (No note.)\n'
        "Work through these in the order listed. Change only these parts, unless their message asks "
        "for more. If a part is no longer on the site, say so in your report and use your judgement. "
        "In your report, say what you did for each part, or why you did not."
    )


def test_no_selection_means_no_block_and_an_odd_id_is_named_as_written() -> None:
    assert targets_block([]) == ""
    assert '- The part "site:nowhere" of the site. (No note.)' in targets_block([{"object_id": "site:nowhere", "note": None}])
```

- [ ] **Step 3: Write the failing request test.** Append to `tests/api/test_site_leg_birth_db.py`
  (add `from clue_agents import DomainObjectRef` to its imports):

```python
def test_site_annotations_ride_the_request_as_targets_in_order(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """Ruling R9: the parts the person pointed at reach the site turn, in submission order, with
    their notes. (A targetless site request staying exactly {prompt, base_version} is pinned by
    Task 13's `test_a_site_document_leg_dispatches_a_site_turn_on_a_fresh_thread`.)"""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds, document = await _seed_site_leg(conn, storage_root=tmp_path, label="sitetargets")
            registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            lane = _FakeLane(conn_factory=seeds["conn_factory"], result=APPLIED_SITE_RESULT)

            def ref(object_type: str, object_id: str, note: str | None = None) -> DomainObjectRef:
                return DomainObjectRef(
                    workspace_id=seeds["workspace_id"], object_type=object_type, object_id=object_id, note=note
                )

            submission = await _submit_message(conn, seeds, label="sitetargets", message="Two fixes, please.")
            await _run_turn(
                conn, seeds, registry, lane, submission,
                focus_refs=(
                    ref("design_document", document["id"]),
                    ref("design_node", "site:/#hero.title", "1. Make it warmer."),
                    ref("design_node", "site:shell#header"),
                ),
            )
            request = lane.envelopes[0].config["request"]
            assert request["prompt"] == "Two fixes, please."
            assert request["targets"] == [
                {"object_id": "site:/#hero.title", "note": "1. Make it warmer."},
                {"object_id": "site:shell#header", "note": None},
            ]

    run_async(scenario())
```

- [ ] **Step 4: Write the failing executor test.** In
  `apps/api/tests/test_site_turn_executor.py`, give the `_envelope` helper a `targets` keyword:

```python
def _envelope(document_id: str, workspace_id: str, *, prompt: str = "Make the hero warmer.",
              bundle: dict | None = None, targets: list | None = None):
    from clue_design.envelopes import DesignTurnEnvelope

    run_id = f"run_{uuid4().hex[:12]}"
    request = {"prompt": prompt, "base_version": 0, **({"targets": targets} if targets else {})}
    return DesignTurnEnvelope(kind="site_turn", work_id=uuid4(), workspace_id=workspace_id, run_id=run_id,
                              checkpoint_thread_id=run_id, document_id=document_id,
                              config={"request": request,
                                      "delegation_bundle": bundle or {"brief": "B"}, "leg": {"leg_id": "leg-1"}})
```

  and append:

```python
def test_the_selection_block_follows_the_persons_words(tmp_path, design_storage) -> None:
    from lumen_agent.site.workspace import targets_block

    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    store = HybridRepository()
    document = store.create_document(_site(f"doc_site_{uuid4().hex[:10]}"), doc_kind="site")
    seen: dict = {}

    def runner(prompt, *, document, workspace, run_id, callbacks):
        seen["prompt"] = prompt
        return SiteTurnResult("applied", "ok", document["scene"], None, [], [])

    targets = [{"object_id": "site:/#c.heading", "note": "1. Shorter"}]
    _run(app, store, document, runner, [], prompt="Fix this.", targets=targets)
    assert seen["prompt"].endswith("Fix this.\n\n" + targets_block(targets))

    _run(app, store, document, runner, [], prompt="No selection.")
    assert seen["prompt"].endswith("No selection.")
```

- [ ] **Step 5: Run the three tests to see them fail.**

Run: RT `test_site_workspace.py`, then PLATFORM `tests/api/test_site_leg_birth_db.py`, then API
`test_site_turn_executor.py`
Expected: FAIL — `targets_block` cannot be imported; the request has no `targets` key; the
executor's `_envelope(..., targets=...)` request is refused by `SiteTurnRequest` or its prompt ends
at "Fix this.".

- [ ] **Step 6: The block, in `lumen_agent/site/workspace.py`** (the T15 wording; agent-facing text
  lives with the agent):

```python
#: A selected part's object id (Lane A Task 14 / Lane C Task 11): site:<route>#<id>[.<field>],
#: where <route> is "/", "/<name>" or "shell" (the header or the footer).
_TARGET = re.compile(
    r"^site:(?P<route>shell|/(?:[a-z0-9][a-z0-9-]*)?)#(?P<id>[A-Za-z0-9_-]{1,200})(?:\.(?P<field>[A-Za-z0-9_]+))?$"
)


def _target_line(object_id: str, note: str | None) -> str:
    match = _TARGET.fullmatch(object_id)
    if match is None:
        where = f'The part "{object_id}" of the site'
    elif match["route"] == "shell":
        where = f"The {match['id']}"
    else:
        where = f'Page {match["route"]}, the section with id "{match["id"]}"'
    if match is not None and match["field"]:
        where += f', its "{match["field"]}" field'
    said = f' Their note: "{note.strip()}"' if note and note.strip() else " (No note.)"
    return f"- {where}.{said}"


def targets_block(targets: Sequence[Mapping[str, Any]]) -> str:
    """What the person pointed at (ruling R9, text T15), or "" when they pointed at nothing."""
    if not targets:
        return ""
    lines = [_target_line(str(t.get("object_id") or ""), t.get("note")) for t in targets]
    return (
        "The person also pointed at parts of the site:\n"
        + "\n".join(lines)
        + "\nWork through these in the order listed. Change only these parts, unless their message asks "
        "for more. If a part is no longer on the site, say so in your report and use your judgement. "
        "In your report, say what you did for each part, or why you did not."
    )
```

  Add `import re` and `from collections.abc import Mapping, Sequence` (and `Any`) to the module's
  imports if Task 5 did not already, and `"targets_block"` to `__all__` if the module has one.

Run: RT `test_site_workspace.py`
Expected: PASS.

- [ ] **Step 7: The request model and the executor.** In `models.py`, above `SiteTurnRequest`:

```python
class SiteTurnTarget(BaseModel):
    """One part of the site the person pointed at (ruling R9): its composer object id, as submitted."""

    object_id: str
    note: Optional[str] = None
```

  and add to `SiteTurnRequest`, after `base_version`:

```python
    #: The parts the person pointed at, in submission order (empty when they pointed at nothing).
    targets: list[SiteTurnTarget] = Field(default_factory=list)
```

  (import `Field` from pydantic if `models.py` does not already). In `execute_site_turn_job`
  (`main.py`), directly after the `prompt = render_leg_turn_prompt(...)` assignment, add:

```python
        if payload.targets:
            from lumen_agent.site.workspace import targets_block

            # Ruling R9: what the person pointed at follows their own words (text T15).
            prompt = f"{prompt}\n\n{targets_block([t.model_dump() for t in payload.targets])}"
```

  `user_message=payload.prompt` is unchanged, so `history.md` still records the person's words only.

Run: API `test_site_turn_executor.py`
Expected: PASS (every earlier test in the file too).

- [ ] **Step 8: The envelope.** In `_envelope`'s `site_turn` request (Task 13 Step 5 (f)), replace

```python
        if kind == "site_turn":
            request = {
                "prompt": message_text,
                # The executor re-reads the document and persists under CAS on the version it read.
                "base_version": int(document.get("current_version") or 0),
            }
```

  with

```python
        if kind == "site_turn":
            # Ruling R9: the parts the person pointed at, in their order, as submitted. Not re-checked
            # against the stored site (the composer did, Lane A Task 14); a part deleted since then
            # reaches the agent, which says so. Absent when nothing was pointed at, so a targetless
            # request stays exactly {prompt, base_version}.
            site_targets = [
                {"object_id": ref.object_id, "note": ref.note}
                for ref in focus_refs
                if ref.object_type == "design_node"
            ]
            request = {
                "prompt": message_text,
                # The executor re-reads the document and persists under CAS on the version it read.
                "base_version": int(document.get("current_version") or 0),
                **({"targets": site_targets} if site_targets else {}),
            }
```

Run: PLATFORM `tests/api/test_site_leg_birth_db.py`, then the web leg suite
`tests/api/test_genweb_web_turn_dispatch_db.py` (web requests unchanged)
Expected: PASS.

- [ ] **Step 9: Commit.**

```bash
git add platform/api/clue_api/design_leg_wiring.py subsystems/clue-design/apps/api/lumen_api/models.py subsystems/clue-design/apps/api/lumen_api/main.py subsystems/clue-design/apps/agent_runtime/lumen_agent/site/workspace.py tests/api/test_site_leg_birth_db.py subsystems/clue-design/apps/agent_runtime/tests/test_site_workspace.py subsystems/clue-design/apps/api/tests/test_site_turn_executor.py
git commit -m "site turn: the parts the person pointed at reach the site agent, in order, with their notes (ruling R9)"
```

---

### Task 14: `design_record_site_section`, the next design profile, and the two grants (B0 + B6 authority; founder-reviewed)

The site turn records a compiled section through one governed design tool, so every agent-written
module is journaled like any other design write. The tool and `read_cited_claims@1` (Task 1) are
granted to the design role in one reviewed profile bump: `build_agent_profile_registry` refuses to
compose when a role's grants and its profile's pins differ
(`platform/api/clue_api/agent_registry_wiring.py:1027-1040`), so the grant, the pin and the
profile version move together, and every registered `design_*` tool must be granted to the design
role (`tests/agents/test_tool_authority_audit.py:310-314`).

**Files:**
- Create: `subsystems/clue-design/apps/api/lumen_api/toolbelt/site_sections.py`
- Modify: `subsystems/clue-design/apps/api/lumen_api/toolbelt/factory.py` (`DESIGN_TOOL_TYPES`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/design_store.py` (`record_site_section` after
  the Task 8 reads)
- Modify: `subsystems/clue-design/apps/api/tests/test_write_path_governance.py`
- Modify: `platform/api/clue_api/agent_registry_wiring.py` (`C6_ACTIVE_PROFILE_VERSIONS`,
  `C6_AGENT_TOOL_AUTHORITY`)
- Create: `platform/agents/catalog/profiles/design/v<N>/profile.yaml`
- Modify: `tests/api/test_agent_registry_wiring.py`, `tests/api/test_toolbelt_wiring.py`,
  `tests/agents/test_tool_authority_audit.py`, `tests/agents/test_catalog.py`
- Test: `subsystems/clue-design/apps/api/tests/test_site_section_tool.py` (new)

**Interfaces:**
- Consumes: `clue_design.site_sections.record_site_section` (Task 2); `SOURCE_KEY_SITE_SECTION`
  (Task 2); Lane A's `lumen_api.site_render.read_section_schema(module_js, *, timeout_s=10.0) -> dict`
  and `SiteRenderError(code, message)` (Lane A Tasks 11 and 17).
- Produces:
  - `HybridRepository.record_site_section(*, digest: str, name: str, source_sha256: str, css_sha256: str, props_schema: dict, created_by_run_id: str | None) -> dict`
  - `toolbelt/site_sections.py`: `RecordSiteSectionInput(name, source, module_js, css="")`,
    `SiteSectionRef(digest, name, source_sha256, css_sha256)`,
    `class SiteSectionRefused(Exception)` (`.code`, `.message`),
    `record_site_section_bytes(*, repository, blobs, name, source, module_js, css, created_by_run_id, read_schema) -> SiteSectionRef`,
    `RecordSiteSectionTool` (`design_record_site_section@1`)
  - `profile:design@v<N>` pinning everything C6 grants `AgentRole.DESIGN`, `C6_ACTIVE_PROFILE_VERSIONS[AgentRole.DESIGN] = "v<N>"`

- [ ] **Step 1: Find `<N>` and the starting counts.** Lane A registers its site tools ungranted and
mints no design profile (ruling R6), so `<N>` is the next folder after the highest one today
(`v5` while only `v1`–`v4` exist). The counts depend on which other tools landed first.

```bash
ls platform/agents/catalog/profiles/design/
grep -n 'AgentRole.DESIGN: "v' platform/api/clue_api/agent_registry_wiring.py
grep -n 'len(registry.names()) ==\|len(registry) ==' tests/api/test_toolbelt_wiring.py
grep -n 'len(by_address) ==' tests/api/test_agent_registry_wiring.py
grep -n 'len(C6_AGENT_TOOL_AUTHORITY) ==' tests/agents/test_tool_authority_audit.py
grep -n '"design_write_site": ()' platform/api/clue_api/agent_registry_wiring.py
```

Expected: the highest folder `vK` and `AgentRole.DESIGN: "vK"` agree; `<N>` is `K + 1` (`v5` if
only `v1`–`v4` exist). Write down each count; this task adds exactly one to each (one name, one
address, one C6 entry). If Lane A's Task 12 has landed, the last grep prints its ungranted entry;
those tools are granted to nobody, so they are not pinned here and Step 8's script never prints
them.

- [ ] **Step 2: Write the failing tool tests** `apps/api/tests/test_site_section_tool.py`:

```python
"""design_record_site_section (Lane B Task 14, Contract 4): one compiled agent section, recorded
with the props schema its own module declares, per workspace, never publicly served."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from conftest import make_blob_store, make_client
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app
from lumen_api.toolbelt.site_sections import SiteSectionRefused

MODULE = 'import { z } from "zod";\nexport const schema = z.object({ id: z.string(), surface: z.string() });\nexport function render() { return null; }\n'
SOURCE = "export const schema = z.object({ id: z.string(), surface: z.string() });\n"
CSS = ".px-6{padding-inline:1.5rem}"
SCHEMA = {"type": "object", "properties": {"id": {"type": "string"}, "surface": {"type": "string"}}}


@pytest.fixture()
def client(tmp_path: Path, design_storage):
    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


def _record(client, workspace_id: str, **overrides):
    body = {"name": "StepsBand", "source": SOURCE, "module_js": MODULE, "css": CSS, **overrides}
    return client.app.state.design_tools.invoke(
        "design_record_site_section", body, workspace_id=workspace_id, actor="agent", actor_id="run_sections_1"
    )


def test_a_section_is_recorded_with_its_own_schema(client, workspace_id: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from lumen_api import site_render

    read: list[str] = []
    monkeypatch.setattr(site_render, "read_section_schema", lambda module_js, **_: read.append(module_js) or SCHEMA)
    result = _record(client, workspace_id)
    digest = hashlib.sha256(MODULE.encode()).hexdigest()
    assert result.references == {
        "digest": digest, "name": "StepsBand",
        "source_sha256": hashlib.sha256(SOURCE.encode()).hexdigest(),
        "css_sha256": hashlib.sha256(CSS.encode()).hexdigest(),
    }
    assert read == [MODULE]
    (row,) = HybridRepository(workspace_id).get_site_sections([digest])
    assert row["props_schema"] == SCHEMA and row["created_by_run_id"] == "run_sections_1"
    blobs = make_blob_store(client.app)
    assert blobs.read(digest).decode() == MODULE
    assert blobs.read(row["css_sha256"]).decode() == CSS
    # The same module again records nothing new.
    assert _record(client, workspace_id).references["digest"] == digest
    assert len(HybridRepository(workspace_id).list_latest_site_sections()) == 1


def test_a_module_whose_schema_cannot_be_read_is_refused_and_nothing_is_recorded(
    client, workspace_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lumen_api import site_render

    def refuse(module_js, **_):
        raise site_render.SiteRenderError("render.failed", "`schema` must be a zod object")

    monkeypatch.setattr(site_render, "read_section_schema", refuse)
    with pytest.raises(SiteSectionRefused) as refused:
        _record(client, workspace_id)
    assert refused.value.code == "render.failed" and "zod object" in refused.value.message
    assert HybridRepository(workspace_id).list_latest_site_sections() == []


def test_a_bad_section_name_is_refused_before_anything_runs(client, workspace_id: str) -> None:
    from pydantic import ValidationError

    # The invoker validates the body against the input model before any check runs
    # (clue_toolbelt/invoker.py:187), so a bad name never reaches the schema read or the store.
    with pytest.raises(ValidationError):
        _record(client, workspace_id, name="stepsBand")
```

Run: API `test_site_section_tool.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'lumen_api.toolbelt.site_sections'`.

- [ ] **Step 3: Add the store write** to `HybridRepository` in `design_store.py`, directly after
`list_latest_site_sections` (Task 8):

```python
    def record_site_section(
        self,
        *,
        digest: str,
        name: str,
        source_sha256: str,
        css_sha256: str,
        props_schema: JsonObject,
        created_by_run_id: Optional[str],
    ) -> JsonObject:
        """Record one compiled agent section (Lane B, Contract 4). Governed: only
        ``toolbelt/site_sections.py`` calls it (test_write_path_governance)."""
        return self._bridge._run(
            lambda conn: design_site_sections.record_site_section(
                conn,
                workspace_id=self.workspace_id,
                digest=digest,
                name=name,
                source_sha256=source_sha256,
                css_sha256=css_sha256,
                props_schema=props_schema,
                created_by_run_id=created_by_run_id,
            )
        )
```

(`design_site_sections` is the `from clue_design import site_sections as design_site_sections`
import Task 8 added.)

- [ ] **Step 4: Create `lumen_api/toolbelt/site_sections.py`:**

```python
"""Agent-written Puck sections (Wave 2 Lane B, Contract 4): the one governed write.

``design_record_site_section`` stores one compiled section — its source, its compiled module and
its CSS — in this workspace's DesignBlobStore under ``SOURCE_KEY_SITE_SECTION`` (which the public
``/asset-store`` read never serves) and records its ``design_site_section`` row. The digest is the
sha256 of the module bytes, computed here, so no caller can name a digest its bytes do not have.

The props schema is read HERE, from the module itself, inside Lane A's hardened render page
(``site_render.read_section_schema``), so the stored schema is always the module's own and no agent
module is ever imported in a platform process (D2). A module that cannot be read refuses with
``SiteSectionRefused`` and nothing is stored.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any, ClassVar

from pydantic import Field

from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
    ReplayPolicy,
    ReplaySafety,
    ToolContext,
    ToolEffectClass,
    ToolInput,
    ToolOutput,
)

from .base import DesignTool

__all__ = [
    "RecordSiteSectionInput",
    "RecordSiteSectionTool",
    "SiteSectionRef",
    "SiteSectionRefused",
    "record_site_section_bytes",
]

#: The same rule the table's CHECK holds (design_site_section_name_shape).
SECTION_NAME_PATTERN = r"^[A-Z][A-Za-z0-9]{2,40}$"


class SiteSectionRefused(Exception):
    """The module cannot join a site: its props schema could not be read in the render page."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class RecordSiteSectionInput(ToolInput):
    name: str = Field(pattern=SECTION_NAME_PATTERN)
    #: The section's TSX source as the agent wrote it.
    source: str
    #: The esbuild output (ESM; imports only react, react/jsx-runtime and zod).
    module_js: str
    #: Tailwind's output for the section's own classes under the brand theme.
    css: str = ""


class SiteSectionRef(ToolOutput):
    digest: str
    name: str
    source_sha256: str
    css_sha256: str


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def record_site_section_bytes(
    *,
    repository: Any,
    blobs: Any,
    name: str,
    source: str,
    module_js: str,
    css: str,
    created_by_run_id: str | None,
    read_schema: Callable[[str], dict],
) -> SiteSectionRef:
    """Read the module's props schema, store the three files, record the row."""

    from clue_design.storage import SOURCE_KEY_SITE_SECTION

    try:
        props_schema = read_schema(module_js)
    except Exception as error:  # Lane A's SiteRenderError carries .code and .message
        raise SiteSectionRefused(
            str(getattr(error, "code", "render.failed")), str(getattr(error, "message", error))
        ) from error
    module_bytes, source_bytes, css_bytes = module_js.encode("utf-8"), source.encode("utf-8"), css.encode("utf-8")
    for data, media_type in (
        (module_bytes, "text/javascript"),
        (source_bytes, "text/plain"),
        (css_bytes, "text/css"),
    ):
        blobs.register(data, media_type=media_type, source_key=SOURCE_KEY_SITE_SECTION)
    row = repository.record_site_section(
        digest=_sha(module_bytes),
        name=name,
        source_sha256=_sha(source_bytes),
        css_sha256=_sha(css_bytes),
        props_schema=props_schema,
        created_by_run_id=created_by_run_id,
    )
    return SiteSectionRef(
        digest=row["digest"], name=row["name"], source_sha256=row["source_sha256"], css_sha256=row["css_sha256"]
    )


class RecordSiteSectionTool(DesignTool):
    """Record one compiled agent-written Puck section in this workspace."""

    name = "design_record_site_section"
    version = "1"
    model_description = (
        "Record one compiled agent-written website section (its source, compiled module and CSS) in "
        "this workspace, with the props schema its module declares. Returns the section's digest "
        "and file digests, never its code."
    )
    input_model: ClassVar[type[ToolInput]] = RecordSiteSectionInput
    output_model: ClassVar[type[ToolOutput]] = SiteSectionRef
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="workspace + sha256(module_js)",
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "content-addressed: the row's key is the module's sha256 and the blobs are stored by "
            "their own sha256, so a repeat of the same module converges on one row and one set of "
            "blobs; the schema read is a pure function of the module"
        ),
    )
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(safe_display_fields=("name",))

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, RecordSiteSectionInput)
        from ..site_render import read_section_schema

        return record_site_section_bytes(
            repository=self.host.repository(ctx.workspace_id),
            blobs=self.host.blobs(ctx.workspace_id),
            name=inputs.name,
            source=inputs.source,
            module_js=inputs.module_js,
            css=inputs.css,
            created_by_run_id=ctx.actor_id,
            read_schema=lambda module_js: read_section_schema(module_js),
        )
```

Check the replay policy's constructor against an existing `DOMAIN_IDEMPOTENT` tool before running
(`RegisterQrAssetTool` in `toolbelt/assets.py:252-275` is one); if `ReplaySafety` refuses a
`DOMAIN_IDEMPOTENT` policy without `operation_id_required`, copy that tool's arguments.

- [ ] **Step 5: Register the tool.** In `toolbelt/factory.py`, add
`from .site_sections import RecordSiteSectionTool` and append to `DESIGN_TOOL_TYPES` (after the
Lane A site tools if they are there, else after `LinkAdPregeneratedAssetsTool,`):

```python
    # Wave 2 Lane B — agent-written Puck sections (Contract 4).
    RecordSiteSectionTool,
```

- [ ] **Step 6: Run the tool tests.**

Run: API `test_site_section_tool.py`
Expected: PASS (3 tests).

- [ ] **Step 7: The design-side governance pins.** In `apps/api/tests/test_write_path_governance.py`:
  - in `_GOVERNED`, after the last entry, add:

```python
    # --- Wave 2 Lane B: agent-written Puck sections --------------------------------------------
    "record_site_section": ("method", ("lumen_api/design_store.py",)),
    "record_site_section_bytes": ("function", ()),
```
  - in `test_every_governed_name_actually_exists`, add
    `from lumen_api.toolbelt import site_sections as toolbelt_site_sections` and add
    `toolbelt_site_sections,` to the tuple of modules it searches;
  - in `test_design_tool_names_are_stable`, add `"design_record_site_section",` as the last name.

Run: API `test_write_path_governance.py`
Expected: the same pass/fail as before this task (the file has one pre-existing failure at
`asset_enrichment.py:51` until Lane A fixes it; no new failure).

- [ ] **Step 8: Print the pins the next profile needs.** From the repo root:

```bash
set -a; source .env; set +a; .venv/bin/python - <<'PY'
import pathlib
import yaml
from clue_agents import AgentRole
from clue_api.agent_registry_wiring import _roles_for
from clue_api.toolbelt_wiring import build_toolbelt
from tests.api.conftest import hermetic_flag_env

profiles = sorted(pathlib.Path("platform/agents/catalog/profiles/design").iterdir(), key=lambda p: int(p.name[1:]))
current = yaml.safe_load((profiles[-1] / "profile.yaml").read_text())
pinned = {(tool["name"], str(tool["version"])) for tool in current["tools"]}
with hermetic_flag_env():
    registry = build_toolbelt(storage=None, gateway=None)
print(f"# from {profiles[-1].name}")
for d in sorted(registry.all_descriptors(), key=lambda d: (d.name, d.version)):
    if AgentRole.DESIGN in _roles_for(d.address, d.name) and (d.name, d.version) not in pinned:
        print(f"  - name: {d.name}\n    version: \"{d.version}\"\n    input_schema_sha256: {d.input_schema_sha256}\n    output_schema_sha256: {d.output_schema_sha256}")
PY
```

Expected before Step 10: nothing after the `# from vK` line (no grant yet). It is run again in
Step 11.

- [ ] **Step 9: The profile change — APPROVED by the founder on 2026-10-12** (review sheet Part 2,
"Lane B Task 14"). Record it as below and continue; the text shown to the founder follows. A profile bump is a
reviewed act. Show exactly this:

> **design@v<N>** — design@vK plus two tools, nothing else moves (same prompt, model, workspace
> policy and limits):
> 1. `read_cited_claims@1` — the design API reads the claims a research page cites, by id, behind
>    the same display gate as every account read, and learns why each held one was held
>    (Contract 5). The site agent never calls it; its research files are built from it.
> 2. `design_record_site_section@1` — records one compiled website section the agent wrote (source,
>    module, CSS and the props schema read from the module in the hardened render page), per
>    workspace (Contract 4).
> Lane A's site writes and site publish stay granted to nobody (ruling R6): no model can save,
> undo, redo or publish a site directly.

Record the approval in
`_memory/2026-10-11-lane-b-site-agent.md` under "design profile bump".

- [ ] **Step 10: Grant the two tools and select the new profile.** In
`platform/api/clue_api/agent_registry_wiring.py`:
  - change `"read_cited_claims": (),` (Task 1) to

```python
    # Contract 5 (Lane B, 2026-10-11): the claims a research page cites, by id, behind the display
    # gate, with a reason for each held one. The design API reads it to build a site turn's research
    # files; the site agent itself never calls it. Granted at `design@v<N>` (reviewed bump).
    "read_cited_claims": (AgentRole.DESIGN,),
```
  - after the Lane A site tools' entries (or after `"design_redo_web_document": (AgentRole.DESIGN,),`
    if they are not there), add

```python
    # Contract 4 (Lane B): records one compiled agent-written Puck section; the site turn's section
    # port calls it. Granted to the design role like every design write, at `design@v<N>`.
    "design_record_site_section": (AgentRole.DESIGN,),
```
  - change `AgentRole.DESIGN: "vK",` to `AgentRole.DESIGN: "v<N>",` and add above it the comment
    line `# v<N> (2026-10-11, Wave 2 Lane B): read_cited_claims@1 and design_record_site_section@1.`

- [ ] **Step 11: Write the profile.** Run Step 8's script again; it now prints the pins for
`read_cited_claims@1` and `design_record_site_section@1`. Then:

```bash
mkdir -p platform/agents/catalog/profiles/design/v<N>
cp platform/agents/catalog/profiles/design/vK/profile.yaml platform/agents/catalog/profiles/design/v<N>/profile.yaml
```

In the new file: change `version: vK` to `version: v<N>`; after the last `# vK (...)` header
comment line add

```yaml
# v<N> (2026-10-11, Wave 2 Lane B): vK plus read_cited_claims@1 (the claims a research page cites,
# with why each held one was held; read by the design API to build a site turn's research files)
# and design_record_site_section@1 (one compiled agent-written website section). Nothing else moves.
```

and paste the printed pin blocks at the end of the `tools:` list, under the comment line
`  # 2026-10-11 (design@v<N>, Wave 2 Lane B).` Run Step 8's script a third time.

Expected: the third run prints nothing after `# from v<N>`.

- [ ] **Step 12: Update the platform registry tests** (each count goes up by exactly one from the
value recorded in Step 1):
  - `tests/api/test_toolbelt_wiring.py`: in `_MATRIX` add
    `"design_record_site_section": ("precondition", ("design_runtime_not_configured",)),`; in
    `_bodies()` add
    `"design_record_site_section": {"name": "StepsBand", "source": "x", "module_js": "x", "css": ""},`;
    raise both `len(registry.names())` and both `len(registry)` assertions by one with the comment
    `# Wave 2 Lane B: design_record_site_section (+1 name, +1 address)`.
  - `tests/api/test_agent_registry_wiring.py`: add `"design_record_site_section@1",` to the
    `design_addresses` set; raise both `len(by_address)` assertions by one (same comment); in
    `test_design_profile_resolves_with_the_full_granted_write_surface` change
    `assert resolved.profile.version == "vK"` to `"v<N>"`, raise
    `assert len(resolved.profile.tools) == …` by two,
    raise the `pin.name.startswith("design_")` count by one, and add
    `"read_cited_claims@1",` to the tuple of addresses the test checks.
  - `tests/agents/test_tool_authority_audit.py`: raise `len(C6_AGENT_TOOL_AUTHORITY)` by one; add
    after the `read_account_research@3` assertion:

```python
    # Wave 2 Lane B (design@v<N>): the cited-claims read and the agent-section record.
    assert C6_AGENT_TOOL_AUTHORITY["read_cited_claims"] == (AgentRole.DESIGN,)
    assert C6_AGENT_TOOL_AUTHORITY["design_record_site_section"] == (AgentRole.DESIGN,)
```
  - `tests/agents/test_catalog.py`: after `"profile:design@vK",` add

```python
        # Wave 2 Lane B: read_cited_claims@1 and design_record_site_section@1. Nothing else moves.
        "profile:design@v<N>",
```

- [ ] **Step 13: Run the platform registry suites.**

```bash
set -a; source .env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_trenton_wave1"; .venv/bin/python -m pytest tests/agents/test_tool_authority_audit.py tests/agents/test_catalog.py tests/api/test_toolbelt_wiring.py tests/api/test_agent_registry_wiring.py tests/api/test_design_platform_reads_db.py -q -o addopts="" --ignore-glob='*_live.py'
```

Expected: PASS, including `test_out_of_order_matrix` on `clue_trenton_wave1`.

- [ ] **Step 14: Commit.**

```bash
git add subsystems/clue-design/apps/api/lumen_api/toolbelt/site_sections.py subsystems/clue-design/apps/api/lumen_api/toolbelt/factory.py subsystems/clue-design/apps/api/lumen_api/design_store.py subsystems/clue-design/apps/api/tests/test_write_path_governance.py subsystems/clue-design/apps/api/tests/test_site_section_tool.py platform/api/clue_api/agent_registry_wiring.py platform/agents/catalog/profiles/design tests/api/test_agent_registry_wiring.py tests/api/test_toolbelt_wiring.py tests/agents/test_tool_authority_audit.py tests/agents/test_catalog.py _memory/2026-10-11-lane-b-site-agent.md
git commit -m "design@v<N>: grant read_cited_claims@1 and the new design_record_site_section@1 (agent-written Puck sections, schema read in the hardened page)"
```

---
### Task 15: Agent sections — compile, record, load, and `write_section` (B6, compile half; needs Lane A Tasks 4, 6, 11, 17)

Contract 4: compile (esbuild, tsc, the lint) runs in Node and never executes the module; the props
schema is read inside Lane A's hardened render page (`design_record_site_section` does that,
Task 14); the module, its source and its CSS are stored per workspace. This task adds the compile
CLI, the section port the turn calls, Lane A's `site_section_loader` seam (so a save, render or
publish of a site that places a section finds its module), and the agent's `write_section` tool.

**Files:**
- Create: `apps/frontend/packages/site-kit/bin/compile-section.ts`
- Create: `apps/frontend/packages/site-kit/test/compile-section.test.ts`
- Modify: `subsystems/clue-design/apps/api/lumen_api/site_kit_cli.py` (`compile_section_source`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/site_turn_ports.py` (`DurableSiteSectionPort`,
  `SCHEMA_UNREADABLE`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/site_workspace_view.py` (`load_site_section_modules`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py` (`app.state.site_section_loader`,
  `_turn_design_tools`, `_execute_site_turn_job`)
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/site/tools.py` (`write_section`)
- Modify: `docker/backend/Dockerfile`, `docker/backend/smoke.sh`, `tests/deploy/test_backend_image.py`
  (contract conflict 8, agreed with Lane A first)
- Test: `apps/api/tests/test_site_kit_cli.py`, `apps/api/tests/test_site_turn_ports.py`,
  `apps/api/tests/test_site_section_tool.py`, `apps/agent_runtime/tests/test_site_sections_tool.py` (new)

**Interfaces:**
- Consumes: site-kit `lint(source, options)`, `lintOptionsFor(brand): LintOptions` and
  `typeCheck(file)` (`src/check-section.ts`, Lane A Task 6 and the A9 rewrite's Task 6b), and
  `tailwindThemeCss(brand)` (`src/theme.ts`, the A9 rewrite's Task 4); `lumen_api.web_export.compile_tailwind_css(html, input_css, node_bin, timeout_seconds=120) -> str`
  (Lane A Task 17); `lumen_api.site_render.{SectionModule, SiteRenderError, SECTION_MODULE_MISSING}`
  (Lane A Task 11); `app.state.site_section_loader` and `DesignToolHost.site_section_loader`
  (Lane A Task 12); `design_record_site_section`, `SiteSectionRefused` (Task 14);
  `read_section_bytes` (Task 8); `record_component` (Task 5); `run_site_kit_script` (Task 3).
- Produces:
  - `bin/compile-section.ts`: stdin `{"name", "source", "brand"}` → stdout
    `{"ok": true, "name", "moduleJs", "tailwindTheme"}` or `{"ok": false, "name", "errors": [str]}`;
    `export async function compileSection(input) -> Compiled`, `export const HOST_SPECIFIERS`
  - `site_kit_cli.compile_section_source(*, name: str, source: str, brand: Mapping) -> dict`
  - `site_turn_ports.DurableSiteSectionPort(*, store, invocations, run_id, brand, node_bin="node")` with `compile(*, name, source) -> dict`
  - `site_workspace_view.load_site_section_modules(repo, blobs, agent_sections: Mapping[str, str]) -> list[SectionModule]`
  - `SiteTools.write_section(name: str, code: str) -> str`

- [ ] **Step 1: Write the failing compile tests** `apps/frontend/packages/site-kit/test/compile-section.test.ts`:

```ts
// Lane B Task 15 (Contract 4): an agent-written section is checked, bundled and given its
// Tailwind theme in Node, and never imported (D2).
import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";
import { compileSection, HOST_SPECIFIERS } from "../bin/compile-section";
import { garner } from "./fixtures/garner";

// The spike's writing-a-section example, verbatim (the check-section tests use the same file).
const EXAMPLE = fs.readFileSync(new URL("./fixtures/section-example.tsx", import.meta.url), "utf-8");
const CHECK_DIR = new URL("../.section-check/", import.meta.url);

test("a valid section compiles to a module that imports only what the host provides", async () => {
  const result = await compileSection({ name: "QuoteBand", source: EXAMPLE, brand: garner() });
  assert.equal(result.ok, true, JSON.stringify(result));
  if (!result.ok) return;
  const imports = [...result.moduleJs.matchAll(/(?:^|\n)\s*import\s[^"']*["']([^"']+)["']/g)].map((m) => m[1]);
  assert.ok(imports.every((specifier) => HOST_SPECIFIERS.includes(specifier)), imports.join(", "));
  assert.match(result.moduleJs, /export\s*\{/);
  assert.ok(result.tailwindTheme.startsWith("@theme inline {"));
});

test("the same source compiles to the same bytes, so the digest is the content's", async () => {
  const a = await compileSection({ name: "QuoteBand", source: EXAMPLE, brand: garner() });
  const b = await compileSection({ name: "QuoteBand", source: EXAMPLE, brand: garner() });
  assert.ok(a.ok && b.ok);
  if (a.ok && b.ok) assert.equal(a.moduleJs, b.moduleJs);
});

test("a brand-token error is refused before the type check runs", async () => {
  const source = EXAMPLE.replace("mt-6 font-body text-body text-ink-secondary", "mt-6 text-emerald-600");
  const result = await compileSection({ name: "QuoteBand", source, brand: garner() });
  assert.equal(result.ok, false);
  if (!result.ok) assert.ok(result.errors.some((e) => e.includes('class "text-emerald-600"')), result.errors.join("; "));
});

test("a type error is refused", async () => {
  const source = EXAMPLE.replace("export function render", 'const wrong: number = "seven";\nexport function render');
  const result = await compileSection({ name: "QuoteBand", source, brand: garner() });
  assert.equal(result.ok, false);
  if (!result.ok) assert.ok(result.errors.some((e) => e.startsWith("type error:")), result.errors.join("; "));
});

test("a bad name is refused and the check folder is left empty", async () => {
  const result = await compileSection({ name: "quoteBand", source: EXAMPLE, brand: garner() });
  assert.deepEqual(result, { ok: false, name: "quoteBand", errors: ['section name "quoteBand" is not PascalCase letters and digits'] });
  await compileSection({ name: "QuoteBand", source: EXAMPLE, brand: garner() });
  const left = fs.existsSync(CHECK_DIR) ? fs.readdirSync(CHECK_DIR).filter((entry) => entry.length === 36) : [];
  assert.deepEqual(left, []);
});
```

Run: SITE-KIT `compile-section.test.ts`
Expected: FAIL — `Cannot find module '../bin/compile-section'`.

- [ ] **Step 2: Write `bin/compile-section.ts`:**

```ts
// Compile one agent-written section (Wave 2 Lane B, Contract 4).
//
// Usage: node --import tsx bin/compile-section.ts < input.json
// Reads {"name": string, "source": string, "brand": BrandData} from stdin and prints ONE JSON line:
//   {"ok": true, "name", "moduleJs", "tailwindTheme"}  or  {"ok": false, "name", "errors": [string]}
//
// The check is site-kit's own: the lint (brand tokens, banned names, allowed imports; the brand's
// extra surfaces count as its own), then the type check. The bundle is esbuild's: ESM, the automatic
// JSX runtime, react / react/jsx-runtime / zod left as imports each host provides. The module is
// NEVER imported here (D2): its props schema is read in the design API's hardened render page
// (lumen_api.site_render.read_section_schema, through design_record_site_section).
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import type { BrandData } from "../src/brand";
import { lint, lintOptionsFor, typeCheck } from "../src/check-section";
import { tailwindThemeCss } from "../src/theme";

const NAME = /^[A-Z][A-Za-z0-9]{2,40}$/;
/** The only imports a compiled module may keep; each host (editor, renderer) provides them. */
export const HOST_SPECIFIERS = ["react", "react/jsx-runtime", "zod"];
const PACKAGE = fileURLToPath(new URL("..", import.meta.url));

export type Compiled =
  | { ok: true; name: string; moduleJs: string; tailwindTheme: string }
  | { ok: false; name: string; errors: string[] };

export async function compileSection(input: { name: string; source: string; brand: BrandData }): Promise<Compiled> {
  const { name, source, brand } = input;
  const fail = (errors: string[]): Compiled => ({ ok: false, name, errors });
  if (!NAME.test(name)) return fail([`section name "${name}" is not PascalCase letters and digits`]);
  // The A9 rewrite (Lane A Task 6b): checked against this brand's looks, surfaces and motion classes.
  const errors = lint(source, lintOptionsFor(brand));
  if (errors.length) return fail(errors);

  // Type-checked in a throwaway folder inside the package (where zod and react resolve), never
  // next to a file the app imports; removed afterwards. `.section-check/` is git-ignored.
  const checkDir = path.join(PACKAGE, ".section-check", crypto.randomUUID());
  fs.mkdirSync(checkDir, { recursive: true });
  try {
    const checked = path.join(checkDir, `${name}.tsx`);
    fs.writeFileSync(checked, source);
    errors.push(...typeCheck(checked));
    if (errors.length) return fail(errors);
    const bundled = await build({
      entryPoints: [checked],
      bundle: true,
      write: false,
      format: "esm",
      jsx: "automatic",
      platform: "neutral",
      target: "es2022",
      // "@/*" stays external so a value import of the kit is caught below instead of bundling the
      // host's own sections into the module; type imports are erased either way.
      external: [...HOST_SPECIFIERS, "@/*"],
      logLevel: "silent",
    });
    // esbuild opens the module with a comment naming the checked file's path; dropped so the bytes
    // (and so the digest) depend on the source alone.
    const moduleJs = bundled.outputFiles[0].text.replace(/^\/\/ [^\n]*\n/, "");
    const imports = [...moduleJs.matchAll(/(?:^|\n)\s*import\s[^"']*["']([^"']+)["']/g)].map((m) => m[1]);
    const foreign = imports.filter((specifier) => !HOST_SPECIFIERS.includes(specifier));
    if (foreign.length) {
      return fail(foreign.map((s) => `the module imports "${s}"; the kit arrives as render's second argument, import only its type`));
    }
    return { ok: true, name, moduleJs, tailwindTheme: tailwindThemeCss(brand) };
  } finally {
    fs.rmSync(checkDir, { recursive: true, force: true });
  }
}

async function main() {
  let raw = "";
  for await (const chunk of process.stdin) raw += chunk;
  const input = JSON.parse(raw) as { name: string; source: string; brand: BrandData };
  console.log(JSON.stringify(await compileSection(input)));
}

if (process.argv[1]?.endsWith("compile-section.ts")) await main();
```

The refusal sentences are the spike's (`trials/puck-spike/scripts/compile-section.ts`) and the
lint's own; none is new.

- [ ] **Step 3: Run the compile tests and the package's type check.**

Run: SITE-KIT `compile-section.test.ts`, then `cd apps/frontend && npm run typecheck -w @clue/site-kit`
Expected: PASS (5 tests); no type errors.

- [ ] **Step 4: Add the Python call and its test.** Append to `apps/api/tests/test_site_kit_cli.py`:

```python
from lumen_api.site_kit_cli import compile_section_source, section_toolchain_missing

EXAMPLE = (SITE_KIT_DIR / "test" / "fixtures" / "section-example.tsx").read_text()


@pytest.mark.skipif(section_toolchain_missing() is not None, reason=f"section toolchain: {section_toolchain_missing()}")
def test_a_section_compiles_through_the_cli() -> None:
    answer = compile_section_source(name="QuoteBand", source=EXAMPLE, brand=_brand())
    assert answer["ok"] is True and "export" in answer["moduleJs"]
    refused = compile_section_source(name="QuoteBand", source=EXAMPLE.replace("text-ink-secondary", "text-red-500"), brand=_brand())
    assert refused["ok"] is False and any('class "text-red-500"' in error for error in refused["errors"])
```

and add to `site_kit_cli.py` (and its `__all__`):

```python
def compile_section_source(*, name: str, source: str, brand: Mapping[str, Any]) -> dict[str, Any]:
    """Check and bundle one agent-written section (Task 15). The answer is the CLI's own:
    ``{"ok": True, "name", "moduleJs", "tailwindTheme"}`` or ``{"ok": False, "name", "errors"}``.
    A toolchain that cannot answer raises ``SiteKitCliError``."""

    return run_site_kit_script("compile-section.ts", {"name": name, "source": source, "brand": dict(brand)})
```

Run: API `test_site_kit_cli.py`
Expected: PASS.

- [ ] **Step 5: Confirm T13 was approved** (Task 0) and write the failing port and loader tests.
Append to `apps/api/tests/test_site_turn_ports.py`:

```python
from types import SimpleNamespace

from lumen_api.site_turn_ports import SCHEMA_UNREADABLE, DurableSiteSectionPort
from lumen_api.toolbelt.site_sections import SiteSectionRefused

SECTION_SCHEMA = {"type": "object", "properties": {"id": {"type": "string"}, "surface": {"type": "string"}}}


class _SectionStore:
    workspace_id = "ws_sections"

    def get_site_sections(self, digests):
        return [{"digest": d, "name": "StepsBand", "props_schema": SECTION_SCHEMA} for d in digests]


class _SectionInvocations:
    def __init__(self, refuse: bool = False) -> None:
        self.calls: list[tuple] = []
        self.refuse = refuse

    def invoke(self, name, body, *, workspace_id, actor, actor_id=None):
        self.calls.append((name, body, workspace_id, actor, actor_id))
        if self.refuse:
            raise SiteSectionRefused("render.failed", "the props need \"surface\"")
        return SimpleNamespace(references={"digest": "d" * 64, "name": body["name"]})


def _compiled(monkeypatch: pytest.MonkeyPatch, answer: dict) -> list:
    from lumen_api import site_turn_ports

    seen: list = []
    monkeypatch.setattr(site_turn_ports, "compile_section_source", lambda **kw: seen.append(kw) or answer)
    monkeypatch.setattr(
        site_turn_ports, "compile_tailwind_css",
        lambda html, input_css, node_bin, timeout_seconds=120: f"/* {input_css.splitlines()[0]} */.px-6{{}}",
    )
    return seen


def test_the_section_port_compiles_records_and_answers_with_the_section(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _compiled(monkeypatch, {"ok": True, "name": "StepsBand", "moduleJs": "export {};", "tailwindTheme": "@theme inline {}"})
    invocations = _SectionInvocations()
    port = DurableSiteSectionPort(store=_SectionStore(), invocations=invocations, run_id="run_s1", brand={"assets": {}})
    answer = port.compile(name="StepsBand", source="SRC")
    assert answer["ok"] is True
    section = answer["section"]
    assert (section.name, section.digest, section.props_schema) == ("StepsBand", "d" * 64, SECTION_SCHEMA)
    assert section.module_js == "export {};" and section.css == '/* @import "tailwindcss"; */.px-6{}'
    assert seen == [{"name": "StepsBand", "source": "SRC", "brand": {"assets": {}}}]
    assert invocations.calls == [(
        "design_record_site_section",
        {"name": "StepsBand", "source": "SRC", "module_js": "export {};", "css": '/* @import "tailwindcss"; */.px-6{}'},
        "ws_sections", "agent", "run_s1",
    )]


def test_check_errors_pass_through_and_nothing_is_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    _compiled(monkeypatch, {"ok": False, "name": "StepsBand", "errors": ["type error: (3,7): bad"]})
    invocations = _SectionInvocations()
    port = DurableSiteSectionPort(store=_SectionStore(), invocations=invocations, run_id="r", brand={})
    assert port.compile(name="StepsBand", source="SRC") == {"ok": False, "errors": ["type error: (3,7): bad"]}
    assert invocations.calls == []


def test_a_schema_the_render_page_cannot_read_is_one_error_to_fix(monkeypatch: pytest.MonkeyPatch) -> None:
    _compiled(monkeypatch, {"ok": True, "name": "StepsBand", "moduleJs": "export {};", "tailwindTheme": ""})
    port = DurableSiteSectionPort(store=_SectionStore(), invocations=_SectionInvocations(refuse=True), run_id="r", brand={})
    assert port.compile(name="StepsBand", source="SRC") == {
        "ok": False,
        "errors": [SCHEMA_UNREADABLE.format(code="render.failed", message='the props need "surface"')],
    }
```

Append to `apps/api/tests/test_site_section_tool.py`:

```python
def test_the_section_loader_serves_what_a_site_pins_and_refuses_the_rest(
    client, workspace_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lumen_api import site_render
    from lumen_api.site_doc_inputs import load_section_modules
    from lumen_api.site_workspace_view import load_site_section_modules

    monkeypatch.setattr(site_render, "read_section_schema", lambda module_js, **_: SCHEMA)
    digest = _record(client, workspace_id).references["digest"]
    repo, blobs = HybridRepository(workspace_id), make_blob_store(client.app)
    assert client.app.state.site_section_loader is load_site_section_modules
    (module,) = load_site_section_modules(repo, blobs, {"StepsBand": digest})
    assert (module.name, module.digest, module.module_js, module.css, module.props_schema) == (
        "StepsBand", digest, MODULE, CSS, SCHEMA)
    # Lane A's pin check accepts it: the bytes hash to the pinned digest.
    assert load_section_modules(load_site_section_modules, repo, blobs, {"agent_sections": {"StepsBand": digest}})
    for pins in ({"StepsBand": "0" * 64}, {"OtherName": digest}):
        with pytest.raises(site_render.SiteRenderError) as missing:
            load_site_section_modules(repo, blobs, pins)
        assert missing.value.code == site_render.SECTION_MODULE_MISSING
```

Run: API `test_site_turn_ports.py`, then API `test_site_section_tool.py`
Expected: FAIL — `ImportError: cannot import name 'SCHEMA_UNREADABLE'` and
`cannot import name 'load_site_section_modules'`.

- [ ] **Step 6: Add the port.** In `site_turn_ports.py` (extend `__all__` with
`"DurableSiteSectionPort"`, `"SCHEMA_UNREADABLE"`; add the imports at module top:
`from .site_kit_cli import compile_section_source` and `from .web_export import compile_tailwind_css`):

```python
#: T13 (founder-approved text): the one error write_section shows when the hardened render page
#: could not read the module's props schema. {message} is the render page's own reason.
SCHEMA_UNREADABLE = (
    "the section could not be loaded to read its props ({code}: {message}); check that it exports "
    "`schema` (a zod object with `id` and `surface`) and `render`"
)


class DurableSiteSectionPort:
    """SiteSectionPort (Contract 4): check and bundle in Node (the module never runs here), build its
    CSS the way the renderer builds a site's (Tailwind over the text, with the brand's theme), then
    record it through the governed design_record_site_section, which reads the props schema in Lane
    A's hardened render page. Check errors come back as a list to fix; a toolchain that cannot
    answer raises (write_section turns that into "the check crashed")."""

    def __init__(self, *, store: Any, invocations: Any, run_id: str, brand: dict, node_bin: str = "node") -> None:
        self.store = store
        self.invocations = invocations
        self.run_id = run_id
        self.brand = brand
        self.node_bin = node_bin

    def compile(self, *, name: str, source: str) -> dict:
        from lumen_agent.site.inputs import SiteSection

        from .toolbelt.site_sections import SiteSectionRefused

        answer = compile_section_source(name=name, source=source, brand=self.brand)
        if not answer.get("ok"):
            return {"ok": False, "errors": [str(error) for error in answer.get("errors") or []]}
        module_js = str(answer["moduleJs"])
        css = compile_tailwind_css(source, '@import "tailwindcss";\n' + str(answer.get("tailwindTheme") or ""), self.node_bin)
        try:
            result = self.invocations.invoke(
                "design_record_site_section",
                {"name": name, "source": source, "module_js": module_js, "css": css},
                workspace_id=self.store.workspace_id,
                actor="agent",
                actor_id=self.run_id,
            )
        except SiteSectionRefused as refused:
            return {"ok": False, "errors": [SCHEMA_UNREADABLE.format(code=refused.code, message=refused.message)]}
        digest = str(result.references["digest"])
        (row,) = self.store.get_site_sections([digest])
        return {
            "ok": True,
            "section": SiteSection(name=name, digest=digest, props_schema=row["props_schema"], module_js=module_js, css=css),
        }
```

Check `compile_tailwind_css`'s input against Lane A's renderer before running: if Lane A's
`render_site` builds its Tailwind input with a helper (search `site_render.py` for
`@import "tailwindcss"`), call that helper here instead of writing the prefix a second time.

- [ ] **Step 7: Add the loader** to `site_workspace_view.py`, after `site_sections_for_turn`
(extend `__all__` if the module has one):

```python
def load_site_section_modules(repo: Any, blobs: Any, agent_sections: Mapping[str, str]) -> list:
    """Lane A's ``site_section_loader`` (Contract 4): the modules a site pins, from this workspace's
    store. A pin this workspace does not hold, held under another name, or whose files are gone
    refuses with ``render.section_module_missing`` (a save answers site.invalid, a publish refuses);
    Lane A's ``pinned_modules`` then checks each module's bytes hash to its pin."""

    from .site_render import SECTION_MODULE_MISSING, SectionModule, SiteRenderError

    pins = {str(name): str(digest) for name, digest in agent_sections.items()}
    rows = {row["digest"]: row for row in repo.get_site_sections(list(pins.values()))}
    modules = []
    for name, digest in pins.items():
        row = rows.get(digest)
        if row is None or row["name"] != name:
            raise SiteRenderError(SECTION_MODULE_MISSING, f"agent section {name} has no stored module {digest[:12]}")
        try:
            module_js, css = read_section_bytes(blobs, row)
        except NotFoundError as error:
            raise SiteRenderError(SECTION_MODULE_MISSING, f"agent section {name}'s stored files are gone") from error
        modules.append(SectionModule(name=name, digest=digest, module_js=module_js, css=css, props_schema=row["props_schema"]))
    return modules
```

- [ ] **Step 8: Compose the loader and the port** in `main.py`:
  - in `create_app`, replace Lane A's `app.state.site_section_loader = sections_not_stored` with

```python
    # Lane B6 (Contract 4): the workspace's recorded agent sections. A site that places one finds
    # its module here for every save, render and publish.
    app.state.site_section_loader = load_site_section_modules
```
    and add `from .site_workspace_view import load_site_section_modules` to the imports (drop
    `sections_not_stored` from the `site_doc_inputs` import if nothing else uses it);
  - in `_turn_design_tools`, change the `site_section_loader=lambda: sections_not_stored,` line
    Task 12 added to `site_section_loader=lambda: load_site_section_modules,`;
  - in `_execute_site_turn_job`, directly after `inputs = build_site_turn_inputs(...)`, add

```python
            inputs = replace(
                inputs,
                sections=DurableSiteSectionPort(
                    store=store, invocations=invocations, run_id=envelope.run_id, brand=inputs.brand
                ),
            )
```
    and add `DurableSiteSectionPort` to that function's `from .site_turn_ports import (...)`.

Run: API `test_site_turn_ports.py`, API `test_site_section_tool.py`, API `test_site_turn_executor.py`
Expected: PASS.

- [ ] **Step 9: Write the failing tool tests** `apps/agent_runtime/tests/test_site_sections_tool.py`:

```python
"""write_section (Lane B Task 15): a new section through the section port, placed by name."""

from __future__ import annotations

import json
from pathlib import Path

from lumen_agent.site.tools import SiteTools
from lumen_agent.site.workspace import materialize_workspace, read_site_files
from site_fixtures import FakeSections, garner_site, inputs_for

SOURCE = 'export const schema = z.object({ id: z.string(), surface: z.string(), quote: z.string() });'


def _tools(tmp_path: Path, sections) -> SiteTools:
    workspace = tmp_path / "workspace"
    inputs = inputs_for(sections=sections)
    site = garner_site()
    materialize_workspace(workspace, inputs, site=site)
    return SiteTools(workspace=workspace, inputs=inputs, base_site=site, retry_delay_s=0)


def test_a_written_section_joins_the_turn_and_its_catalog(tmp_path: Path) -> None:
    sections = FakeSections()
    tools = _tools(tmp_path, sections)
    result = tools.write_section("StepsBand", SOURCE)
    assert result.startswith(
        'WRITTEN: StepsBand is ready for this site. Place it in a page with "type": "StepsBand" and these props:\n'
    )
    assert sections.calls == [("StepsBand", SOURCE)]
    assert tools.sections["StepsBand"].digest == "e" * 64
    assert "## StepsBand" in (tools.workspace / "catalog" / "seller-components.md").read_text()
    assert tools.events[-1]["kind"] == "section_written" and tools.events[-1]["digest"] == "e" * 64


def test_a_placed_section_is_pinned_when_the_site_is_read_back(tmp_path: Path) -> None:
    tools = _tools(tmp_path, FakeSections())
    tools.write_section("StepsBand", SOURCE)
    page = json.loads((tools.workspace / "page.json").read_text())
    page["content"].append({"type": "StepsBand", "props": {"id": "steps", "surface": "page", "quote": "Fewer surprises."}})
    (tools.workspace / "page.json").write_text(json.dumps(page))
    assert read_site_files(tools.workspace, tools.base_site, tools.sections)["agent_sections"] == {"StepsBand": "e" * 64}


def test_check_errors_come_back_as_a_list_to_fix(tmp_path: Path) -> None:
    error = 'class "text-red-500" is a Tailwind palette colour; use the brand\'s text-ink-*, bg-surface-* or border-line-*'
    tools = _tools(tmp_path, FakeSections(errors=[error]))
    assert tools.write_section("StepsBand", SOURCE) == f"NOT WRITTEN (fix these, then call write_section again):\n- {error}"
    assert "StepsBand" not in tools.sections


def test_names_are_checked_before_anything_compiles(tmp_path: Path) -> None:
    sections = FakeSections()
    tools = _tools(tmp_path, sections)
    assert tools.write_section("stepsBand", SOURCE) == "NOT WRITTEN: a section name is PascalCase letters and digits, for example StepsBand."
    assert tools.write_section("CtaBand", SOURCE) == "NOT WRITTEN: CtaBand is one of the built-in sections; choose another name."
    assert sections.calls == []


def test_a_toolchain_that_cannot_answer_reads_as_the_check_crashing(tmp_path: Path) -> None:
    class Broken:
        def compile(self, *, name, source):
            raise RuntimeError("tsc is not installed")

    assert _tools(tmp_path, Broken()).write_section("StepsBand", SOURCE) == "NOT WRITTEN: the check crashed: tsc is not installed"
```

Run: RT `test_site_sections_tool.py`
Expected: FAIL — `AttributeError: 'SiteTools' object has no attribute 'write_section'`.

- [ ] **Step 10: Add `write_section` to `SiteTools`.** Add `import json` to the module's imports,
`record_component` to its `from .workspace import …`, and after `LOOP_GUARD_AT` the constants:

```python
#: The spike's built-in section names (tools.py:42) plus the shell's two: a new section may not
#: take one of them.
BUILT_IN_SECTIONS = frozenset({"ClonedSection", "StatsBand", "FeatureSplit", "ProofCard", "CtaBand", "TokenProbe", "SiteHeader", "SiteFooter"})
SECTION_NAME = re.compile(r"[A-Z][A-Za-z0-9]{2,40}")
```

Then the method (the spike's `write_section`, `trials/puck-spike/agent/trials_puck_agent/tools.py:375-404`,
with the dev-server file writes replaced by the section port; every sentence is the spike's):

```python
    # --- new sections (E5) -----------------------------------------------------------------------

    def write_section(self, name: str, code: str) -> str:
        """Write a new section as one React file. It must pass the brand-token check and type-check;
        only then does it join this site, under its name."""

        if not SECTION_NAME.fullmatch(name or ""):
            return "NOT WRITTEN: a section name is PascalCase letters and digits, for example StepsBand."
        if name in BUILT_IN_SECTIONS:
            return f"NOT WRITTEN: {name} is one of the built-in sections; choose another name."
        port = self.inputs.sections
        try:
            if port is None:
                raise RuntimeError("section store unavailable")
            answer = port.compile(name=name, source=code)
        except Exception as error:  # noqa: BLE001 - a toolchain that cannot answer is an answer, not a crash
            detail = getattr(error, "detail", None) or str(error)
            return f"NOT WRITTEN: the check crashed: {str(detail).strip()[-500:]}"
        if not answer.get("ok"):
            errors = [str(error) for error in answer.get("errors") or []]
            self._record("section_refused", name=name, errors=errors)
            return "NOT WRITTEN (fix these, then call write_section again):\n" + "\n".join(f"- {e}" for e in errors)
        section = answer["section"]
        self.sections[name] = section
        record_component(self.workspace, name, section.props_schema)
        self._record("section_written", name=name, digest=section.digest)
        return (f"WRITTEN: {name} is ready for this site. Place it in a page with \"type\": \"{name}\" and "
                f"these props:\n{json.dumps(section.props_schema, indent=1)[:4000]}")
```

Run: RT `test_site_sections_tool.py`, then RT `test_site_tools.py` and RT `test_site_harness.py`
Expected: PASS.

- [ ] **Step 11: The compile toolchain in the backend image (contract conflict 8, ruling R7: accepted
as written; Lane A's Task 15 must have landed its `sitekit` stage).** In `docker/backend/Dockerfile`,
after Lane A's `COPY --from=sitekit … /dist …` line, add:

```dockerfile
# Lane B (Contract 4): the section compiler needs the frontend toolchain at run time (tsc with the
# react and zod types, esbuild, tsx); the site-kit sources come with `COPY . /app`.
COPY --from=sitekit /src/apps/frontend/node_modules /app/apps/frontend/node_modules
```

In `docker/backend/smoke.sh`, after Lane A's `site-kit bundles` check, add:

```bash
check "site-kit section toolchain" run test -d /app/apps/frontend/node_modules/typescript -a -d /app/apps/frontend/node_modules/esbuild -a -d /app/apps/frontend/node_modules/tsx
```

and append to `tests/deploy/test_backend_image.py`:

```python
def test_the_image_ships_the_section_compile_toolchain() -> None:
    """Agent-written sections are checked and bundled at run time (Wave 2 Lane B, Contract 4)."""
    assert "COPY --from=sitekit /src/apps/frontend/node_modules /app/apps/frontend/node_modules" in DOCKERFILE
    assert 'check "site-kit section toolchain"' in SMOKE
```

Run: PLATFORM `tests/deploy/test_backend_image.py`
Expected: PASS. (The image itself is built by CI; do not build it locally unless asked.)

- [ ] **Step 12: Commit.**

```bash
git add apps/frontend/packages/site-kit/bin/compile-section.ts apps/frontend/packages/site-kit/test/compile-section.test.ts subsystems/clue-design/apps/api/lumen_api/site_kit_cli.py subsystems/clue-design/apps/api/lumen_api/site_turn_ports.py subsystems/clue-design/apps/api/lumen_api/site_workspace_view.py subsystems/clue-design/apps/api/lumen_api/main.py subsystems/clue-design/apps/agent_runtime/lumen_agent/site/tools.py subsystems/clue-design/apps/api/tests/test_site_kit_cli.py subsystems/clue-design/apps/api/tests/test_site_turn_ports.py subsystems/clue-design/apps/api/tests/test_site_section_tool.py subsystems/clue-design/apps/agent_runtime/tests/test_site_sections_tool.py docker/backend/Dockerfile docker/backend/smoke.sh tests/deploy/test_backend_image.py
git commit -m "agent sections: compile in Node without running the module, record through the governed tool, load for saves/renders/publishes, and write_section"
```

---
### Task 16: Section links — `POST /documents/{id}/site/section-links` and the token-gated module read (B6, serving half)

Contract 4: the editor never reads an agent module through `/asset-store`. The app asks
`POST /documents/{id}/site/section-links` (the document must place the digest) and receives
`{"links": [{name, digest, token, expires_at, props_schema}]}` (`props_schema` added, contract
conflict 5; the `links` wrapper matches Lane A's `{"versions": [...]}`, ruling R1); the
token is an HMAC over `(workspace_id, document_id, digest, expires_at)` with
`CLUE_SITE_SECTION_LINK_SECRET`, valid 10 minutes. The editor app's own server route
`GET /sections/<digest>.mjs|.css?t=<token>` (Lane C) calls `GET /site-sections/{digest}.mjs?t=<token>`
(the module) or `GET /site-sections/{digest}.css?t=<token>` (its stored CSS, empty when it has none)
on the design API **without a workspace header** (the same posture as its `design-public`
passthrough, `apps/frontend/src/app/api/clue/design-public/[...path]/public-proxy-handler.ts`): the
token is the only statement of tenancy, so both routes join the O4 allowlist. Each answers
`X-Clue-Workspace-Id: <the token's workspace>`, so the editor server can refuse a module that
belongs to a workspace other than the one in its `Host` (ruling R2, Lane C's K1).

**Files:**
- Modify: `libs/clue-config/clue_config/secrets.py` (`site_section_link_secret`)
- Modify: `.env.example`, `subsystems/clue-design/.env.example`, the local `.env` (not committed)
- Create: `subsystems/clue-design/apps/api/lumen_api/site_section_links.py`
- Modify: `subsystems/clue-design/apps/api/lumen_api/models.py` (`SiteSectionLinksRequest`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py` (two routes; `app.state.site_section_link_secret`)
- Modify: `subsystems/clue-design/apps/api/tests/test_workspace_seam_route_table.py` (`ALLOWLIST`)
- Test: `tests/test_site_section_link_settings.py` (new), `subsystems/clue-design/apps/api/tests/test_site_section_links.py` (new)

**Interfaces:**
- Consumes: `HybridRepository.get_site_sections` (Task 8), `design_record_site_section` (Task 14),
  `DesignBlobStore.read`, `clue_config.Secrets`.
- Produces:
  - env `CLUE_SITE_SECTION_LINK_SECRET` (secret; `Secrets.site_section_link_secret: SecretStr | None`)
  - `site_section_links`: `LINK_TTL_S = 600`, codes `TOKEN_INVALID = "site_section_link.invalid"`,
    `TOKEN_EXPIRED = "site_section_link.expired"`, `UNCONFIGURED = "site_section_links.unconfigured"`,
    `NOT_REFERENCED = "site_section.not_referenced"`, `NOT_FOUND = "site_section.not_found"`;
    `class SectionLinkRefused(Exception)` (`.code`, `.message`); `link_secret() -> bytes | None`;
    `mint_section_token(*, secret: bytes, workspace_id: str, document_id: str, digest: str, expires_at: int) -> str`;
    `verify_section_token(token: str, *, secret: bytes, digest: str, now: int) -> tuple[str, str]` (workspace, document);
    `section_links(repo, document: dict, digests: list[str] | None, *, secret: bytes, now: int) -> list[dict]`
  - `POST /documents/{document_id}/site/section-links` body `{digests?: [sha256]}` → 200
    `{"schema_version": 1, "links": [{name, digest, token, expires_at (ISO 8601 UTC), props_schema}]}`; 404 `site_section.not_referenced`
    / `site_section.not_found`; 409 `document.kind_unsupported`; 503 `site_section_links.unconfigured`
  - `GET /site-sections/{digest}.mjs?t=<token>` and `GET /site-sections/{digest}.css?t=<token>` (no
    workspace header) → 200 `text/javascript; charset=utf-8` (the module) / `text/css; charset=utf-8`
    (its stored CSS, possibly empty), each with `cache-control: no-store`,
    `x-content-type-options: nosniff` and `x-clue-workspace-id: <the token's workspace>`; 403
    `site_section_link.invalid` / `site_section_link.expired`; 404 `site_section.not_found`; 503
    `site_section_links.unconfigured`

- [ ] **Step 1: Write the failing settings test** `tests/test_site_section_link_settings.py`:

```python
"""Contract 4 (Lane B Task 16): the section-link secret is a documented, optional secret."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from clue_config import Secrets

REPO = Path(__file__).resolve().parents[1]


def test_the_section_link_secret_is_an_optional_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLUE_SITE_SECTION_LINK_SECRET", raising=False)
    assert "site_section_link_secret" in Secrets.model_fields
    assert Secrets(_env_file=None).site_section_link_secret is None  # type: ignore[call-arg]


def test_both_env_examples_document_it_as_a_placeholder() -> None:
    for example in (REPO / ".env.example", REPO / "subsystems" / "clue-design" / ".env.example"):
        assert re.search(r"^CLUE_SITE_SECTION_LINK_SECRET=$", example.read_text(encoding="utf-8"), re.MULTILINE), example
```

Run: PLATFORM `tests/test_site_section_link_settings.py`
Expected: FAIL — the field and the env lines do not exist.

- [ ] **Step 2: Add the secret and document it.** In `secrets.py`, after `pages_edge_secret`, add:

```python
    # Env: CLUE_SITE_SECTION_LINK_SECRET. Signs the 10-minute links the editor uses to load an
    # agent-written Puck section module (Wave 2 Contract 4): an HMAC over (workspace, document,
    # digest, expiry). Unset = the design API refuses to mint or honour section links (503).
    site_section_link_secret: SecretStr | None = None
```

In `.env.example`, after the `CLUE_PAGES_ORIGIN_PORT=8040` line, and in
`subsystems/clue-design/.env.example` at the end of the file, add (with a blank line before it):

```
# Puck sites (Wave 2 Contract 4): the secret that signs the editor's 10-minute links to an
# agent-written section module. Set it in every environment that runs the design API; empty =
# section links are refused (503 site_section_links.unconfigured).
CLUE_SITE_SECTION_LINK_SECRET=
```

Give the local `.env` its own value (never committed):

```bash
grep -q '^CLUE_SITE_SECTION_LINK_SECRET=' .env || printf '\nCLUE_SITE_SECTION_LINK_SECRET=%s\n' "$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" >> .env
```

Run: PLATFORM `tests/test_site_section_link_settings.py`
Expected: PASS.

- [ ] **Step 3: Write the failing route tests** `apps/api/tests/test_site_section_links.py`:

```python
"""Section links (Lane B Task 16, Contract 4): the editor loads an agent module through a
10-minute signed link, never through /asset-store."""

from __future__ import annotations

import time
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from conftest import make_client
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app
from lumen_api.site_section_links import mint_section_token

SECRET = b"test-section-link-secret"
MODULE = 'export const schema = 1;\nexport function render() { return null; }\n'
SCHEMA = {"type": "object", "properties": {"id": {"type": "string"}, "surface": {"type": "string"}}}


@pytest.fixture()
def app(tmp_path: Path, design_storage, monkeypatch: pytest.MonkeyPatch):
    from lumen_api import site_render

    monkeypatch.setattr(site_render, "read_section_schema", lambda module_js, **_: SCHEMA)
    application = create_app(tmp_path / "engine-cache", storage=design_storage)
    application.state.site_section_link_secret = lambda: SECRET
    return application


def _site_with_section(client: TestClient, workspace_id: str) -> tuple[dict, str]:
    digest = client.app.state.design_tools.invoke(
        "design_record_site_section",
        {"name": "StepsBand", "source": "src", "module_js": MODULE, "css": ".a{}"},
        workspace_id=workspace_id, actor="agent", actor_id="run_links",
    ).references["digest"]
    doc_id = f"doc_site_{uuid4().hex[:10]}"
    site = {"id": doc_id, "title": "S", "theme": {}, "shell": None, "agent_sections": {"StepsBand": digest},
            "pages": {"/": {"root": {"props": {"title": "S"}}, "content": []}}}
    return HybridRepository(workspace_id).create_document(site, doc_kind="site"), digest


def test_a_link_is_minted_for_a_placed_section_and_serves_its_module(app, workspace_id: str) -> None:
    client = make_client(app)
    document, digest = _site_with_section(client, workspace_id)
    response = client.post(f"/documents/{document['id']}/site/section-links", json={})
    assert response.status_code == 200, response.text
    (link,) = response.json()["links"]
    assert (link["name"], link["digest"], link["props_schema"]) == ("StepsBand", digest, SCHEMA)
    assert link["expires_at"].endswith("Z") and link["token"]
    bare = TestClient(app)  # the editor's server sends no workspace header
    served = bare.get(f"/site-sections/{digest}.mjs", params={"t": link["token"]})
    assert served.status_code == 200 and served.content == MODULE.encode()
    assert served.headers["content-type"].startswith("text/javascript")
    assert served.headers["cache-control"] == "no-store" and served.headers["x-content-type-options"] == "nosniff"
    assert served.headers["x-clue-workspace-id"] == workspace_id  # ruling R2: the editor checks its Host
    styles = bare.get(f"/site-sections/{digest}.css", params={"t": link["token"]})
    assert styles.status_code == 200 and styles.content == b".a{}"
    assert styles.headers["content-type"].startswith("text/css")
    assert styles.headers["x-clue-workspace-id"] == workspace_id


def test_a_token_for_another_digest_or_after_expiry_is_refused(app, workspace_id: str) -> None:
    """Review focus 3."""

    client = make_client(app)
    document, digest = _site_with_section(client, workspace_id)
    bare = TestClient(app)
    now = int(time.time())
    good = mint_section_token(secret=SECRET, workspace_id=workspace_id, document_id=document["id"], digest=digest, expires_at=now + 600)
    other_digest = "0" * 64
    assert bare.get(f"/site-sections/{other_digest}.mjs", params={"t": good}).json()["detail"]["code"] == "site_section_link.invalid"
    expired = mint_section_token(secret=SECRET, workspace_id=workspace_id, document_id=document["id"], digest=digest, expires_at=now - 1)
    refused = bare.get(f"/site-sections/{digest}.mjs", params={"t": expired})
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "site_section_link.expired"
    forged = mint_section_token(secret=b"another-secret", workspace_id=workspace_id, document_id=document["id"], digest=digest, expires_at=now + 600)
    assert bare.get(f"/site-sections/{digest}.css", params={"t": forged}).json()["detail"]["code"] == "site_section_link.invalid"
    assert bare.get(f"/site-sections/{digest}.mjs", params={"t": "not-a-token"}).status_code == 403
    # A link minted for another workspace reads only that workspace, which does not hold the module.
    elsewhere = mint_section_token(secret=SECRET, workspace_id=f"ws_other_{uuid4().hex[:8]}", document_id="doc_x", digest=digest, expires_at=now + 600)
    not_held = bare.get(f"/site-sections/{digest}.mjs", params={"t": elsewhere})
    assert not_held.status_code == 404 and not_held.json()["detail"]["code"] == "site_section.not_found"
    # And the module never comes out of the public byte route.
    assert bare.get(f"/asset-store/{digest}").status_code == 404


def test_a_digest_the_document_does_not_place_is_not_linked(app, workspace_id: str) -> None:
    client = make_client(app)
    document, _ = _site_with_section(client, workspace_id)
    response = client.post(f"/documents/{document['id']}/site/section-links", json={"digests": ["0" * 64]})
    assert response.status_code == 404 and response.json()["detail"]["code"] == "site_section.not_referenced"


def test_without_a_secret_no_link_is_minted_or_honoured(app, workspace_id: str) -> None:
    client = make_client(app)
    document, digest = _site_with_section(client, workspace_id)
    app.state.site_section_link_secret = lambda: None
    minted = client.post(f"/documents/{document['id']}/site/section-links", json={})
    assert minted.status_code == 503 and minted.json()["detail"]["code"] == "site_section_links.unconfigured"
    assert TestClient(app).get(f"/site-sections/{digest}.mjs", params={"t": "x"}).status_code == 503
```

Run: API `test_site_section_links.py`
Expected: FAIL at import — `ModuleNotFoundError: No module named 'lumen_api.site_section_links'`.

- [ ] **Step 4: Write `lumen_api/site_section_links.py`:**

```python
"""Short-lived signed links to agent-written Puck section modules (Wave 2 Lane B, Contract 4).

An agent module is code, so it is never served by the public ``/asset-store`` route (the public
read skips ``SOURCE_KEY_SITE_SECTION``). The editor asks for links to the sections a document
places; each link is a token valid for ``LINK_TTL_S`` seconds:

    token = base64url(JSON {"w": workspace, "d": document, "e": expires_at}) "." base64url(HMAC)
    HMAC  = HMAC-SHA256(CLUE_SITE_SECTION_LINK_SECRET, "workspace\\ndocument\\ndigest\\nexpires_at")

The digest is not inside the token: the verifier takes it from the URL and recomputes the HMAC, so a
token minted for one module cannot fetch another. The token is the only statement of tenancy the
module route accepts; the module is read from the token's workspace only.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any

__all__ = [
    "LINK_TTL_S",
    "NOT_FOUND",
    "NOT_REFERENCED",
    "TOKEN_EXPIRED",
    "TOKEN_INVALID",
    "UNCONFIGURED",
    "SectionLinkRefused",
    "link_secret",
    "mint_section_token",
    "section_links",
    "verify_section_token",
]

LINK_TTL_S = 600
TOKEN_INVALID = "site_section_link.invalid"
TOKEN_EXPIRED = "site_section_link.expired"
UNCONFIGURED = "site_section_links.unconfigured"
NOT_REFERENCED = "site_section.not_referenced"
NOT_FOUND = "site_section.not_found"


class SectionLinkRefused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def link_secret() -> bytes | None:
    """The configured signing secret, or ``None`` when the environment has none."""

    from clue_config import Secrets

    value = Secrets().site_section_link_secret
    return value.get_secret_value().encode("utf-8") if value is not None and value.get_secret_value() else None


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signature(secret: bytes, workspace_id: str, document_id: str, digest: str, expires_at: int) -> bytes:
    message = f"{workspace_id}\n{document_id}\n{digest}\n{expires_at}".encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).digest()


def mint_section_token(*, secret: bytes, workspace_id: str, document_id: str, digest: str, expires_at: int) -> str:
    claims = json.dumps({"w": workspace_id, "d": document_id, "e": int(expires_at)}, separators=(",", ":"))
    return f"{_b64(claims.encode('utf-8'))}.{_b64(_signature(secret, workspace_id, document_id, digest, int(expires_at)))}"


def verify_section_token(token: str, *, secret: bytes, digest: str, now: int) -> tuple[str, str]:
    """``(workspace_id, document_id)`` the token was minted for, if it is genuine, for ``digest``
    and unexpired; otherwise ``SectionLinkRefused``. The signature is checked before the expiry, so
    a forged token never learns whether its time was right."""

    try:
        claims_part, signature_part = token.split(".")
        claims = json.loads(_unb64(claims_part))
        workspace_id, document_id, expires_at = str(claims["w"]), str(claims["d"]), int(claims["e"])
        signature = _unb64(signature_part)
    except (ValueError, KeyError, TypeError) as error:
        raise SectionLinkRefused(TOKEN_INVALID, "the section link is not valid") from error
    expected = _signature(secret, workspace_id, document_id, digest, expires_at)
    if not hmac.compare_digest(signature, expected):
        raise SectionLinkRefused(TOKEN_INVALID, "the section link is not valid")
    if now >= expires_at:
        raise SectionLinkRefused(TOKEN_EXPIRED, "the section link has expired; ask for a new one")
    return workspace_id, document_id


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def section_links(repo: Any, document: dict, digests: list[str] | None, *, secret: bytes, now: int) -> list[dict]:
    """Links to the sections ``document`` places (all of them when ``digests`` is None)."""

    site = document.get("scene") or {}
    names = {str(digest): str(name) for name, digest in (site.get("agent_sections") or {}).items()}
    wanted = list(dict.fromkeys(digests if digests is not None else names))
    for digest in wanted:
        if digest not in names:
            raise SectionLinkRefused(NOT_REFERENCED, f"the document does not place section {digest[:12]}")
    rows = {row["digest"]: row for row in repo.get_site_sections(wanted)}
    expires_at = now + LINK_TTL_S
    links = []
    for digest in wanted:
        row = rows.get(digest)
        if row is None:
            raise SectionLinkRefused(NOT_FOUND, f"this workspace holds no section {digest[:12]}")
        links.append({
            "name": names[digest],
            "digest": digest,
            "token": mint_section_token(
                secret=secret, workspace_id=repo.workspace_id, document_id=str(document["id"]),
                digest=digest, expires_at=expires_at,
            ),
            "expires_at": _iso(expires_at),
            "props_schema": row["props_schema"],
        })
    return links
```

- [ ] **Step 5: Add the request model** to `models.py` (after `BrandCompatibilityRequest`):

```python
class SiteSectionLinksRequest(BaseModel):
    """POST /documents/{id}/site/section-links (Wave 2 Contract 4). ``digests`` names the sections
    to link; omitted = every section the document places."""

    digests: Optional[List[str]] = None
```

- [ ] **Step 6: Add the routes** to `main.py`. Import `SiteSectionLinksRequest` with the other
`.models`. In `create_app`, beside the other `app.state` seams (after Lane A's
`app.state.site_section_loader` line), add:

```python
    # Contract 4 (Lane B): the section-link signing secret, read per call so a deployment that sets
    # it needs no restart; a test replaces the thunk.
    from .site_section_links import link_secret

    app.state.site_section_link_secret = link_secret
```

Then, after Lane A's site routes (search for `"/documents/{document_id}/site/versions"`), add:

```python
    @app.post("/documents/{document_id}/site/section-links")
    def mint_site_section_links(
        document_id: str, payload: SiteSectionLinksRequest, repo: HybridRepository = Depends(repository)
    ) -> JsonObject:
        """Ten-minute links to the agent sections this site places (Contract 4; ruling R1)."""
        from .site_section_links import UNCONFIGURED, SectionLinkRefused, section_links

        secret = app.state.site_section_link_secret()
        if secret is None:
            raise HTTPException(status_code=503, detail={"code": UNCONFIGURED, "message": "section links are not configured"})
        document = repo.require_document(document_id)
        if document.get("doc_kind") != "site":
            raise HTTPException(status_code=409, detail={"code": "document.kind_unsupported", "message": "not a website document"})
        try:
            links = section_links(repo, document, payload.digests, secret=secret, now=int(time.time()))
        except SectionLinkRefused as refused:
            raise HTTPException(status_code=404, detail={"code": refused.code, "message": refused.message}) from refused
        return {"schema_version": 1, "links": links}

    def _serve_site_section(digest: str, token: str, part: str) -> Response:
        """An agent section's compiled module (``part="module"``) or its stored CSS (``part="css"``)
        for the editor's own server (Contract 4, ruling R2). Token-gated; NO workspace header: the
        token is the only statement of tenancy, the bytes are read from the token's workspace alone,
        and that workspace rides back in ``x-clue-workspace-id`` so the editor server can refuse a
        module that is not its Host's."""
        from .site_section_links import NOT_FOUND, UNCONFIGURED, SectionLinkRefused, verify_section_token

        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise HTTPException(status_code=404, detail={"code": NOT_FOUND, "message": "not a section digest"})
        secret = app.state.site_section_link_secret()
        if secret is None:
            raise HTTPException(status_code=503, detail={"code": UNCONFIGURED, "message": "section links are not configured"})
        try:
            workspace_id, _document_id = verify_section_token(token, secret=secret, digest=digest, now=int(time.time()))
        except SectionLinkRefused as refused:
            raise HTTPException(status_code=403, detail={"code": refused.code, "message": refused.message}) from refused
        rows = HybridRepository(workspace_id, ensure_workspace=False).get_site_sections([digest])
        if not rows:
            raise HTTPException(status_code=404, detail={"code": NOT_FOUND, "message": "no such section"})
        blob_key = digest if part == "module" else rows[0]["css_sha256"]
        try:
            data = DesignBlobStore(app.state.storage, workspace_id, ensure_workspace=False).read(blob_key)
        except NotFoundError as error:
            raise HTTPException(status_code=404, detail={"code": NOT_FOUND, "message": "no such section"}) from error
        return Response(
            content=data,
            media_type="text/javascript; charset=utf-8" if part == "module" else "text/css; charset=utf-8",
            headers={
                "cache-control": "no-store",
                "x-content-type-options": "nosniff",
                "x-clue-workspace-id": workspace_id,
            },
        )

    @app.get("/site-sections/{digest}.mjs")
    def get_site_section_module(digest: str, t: str = Query(...)) -> Response:
        return _serve_site_section(digest, t, "module")

    @app.get("/site-sections/{digest}.css")
    def get_site_section_css(digest: str, t: str = Query(...)) -> Response:
        return _serve_site_section(digest, t, "css")
```

`time`, `re`, `Query`, `Response`, `List`, `DesignBlobStore` and `NotFoundError` are already
imported by `main.py` (check with `grep -n "^import time\|^import re\|Query,\|Response\b" main.py`
and add any that are missing).

- [ ] **Step 7: Allowlist the module route (O4).** In `test_workspace_seam_route_table.py`, add to
`ALLOWLIST`:

```python
    # Wave 2 Contract 4: an agent-written section module for the editor's own server, which cannot
    # send a workspace header; a 10-minute HMAC link token (minted by a header-gated route) carries
    # the workspace, and the module is read from that workspace only.
    ("GET", "/site-sections/{digest}.mjs"): "HMAC section-link token carries tenancy",
    ("GET", "/site-sections/{digest}.css"): "HMAC section-link token carries tenancy",
```

- [ ] **Step 8: Run the tests.**

Run: API `test_site_section_links.py`, then API `test_workspace_seam_route_table.py`
Expected: PASS (the seam guard sees the mint route demand the header and the module route answer
headerless, as allowlisted).

- [ ] **Step 9: Commit.**

```bash
git add libs/clue-config/clue_config/secrets.py .env.example subsystems/clue-design/.env.example subsystems/clue-design/apps/api/lumen_api/site_section_links.py subsystems/clue-design/apps/api/lumen_api/models.py subsystems/clue-design/apps/api/lumen_api/main.py subsystems/clue-design/apps/api/tests/test_workspace_seam_route_table.py subsystems/clue-design/apps/api/tests/test_site_section_links.py tests/test_site_section_link_settings.py
git commit -m "section links: 10-minute HMAC links to agent modules (CLUE_SITE_SECTION_LINK_SECRET) and the token-gated module read, never /asset-store"
```

---
### Task 17: Cost and tracing proofs for a site request (B7)

No new mechanism: a site request rides the design turn's existing spend scope, model-call
collector, gateway role labels and Langfuse trace. These tests prove each one reaches the site
path — in particular that the spend contextvar reaches the tool threads LangGraph runs
`generate_image` on (the survey's one open question, `lumen_api/spend.py:145-159`).

**Files:**
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_site_cost_and_tracing.py` (new)
- Modify (test only): `subsystems/clue-design/apps/api/tests/test_site_turn_executor.py`,
  `subsystems/clue-design/apps/api/tests/test_design_job_trace.py`

**Interfaces:**
- Consumes: `lumen_api.spend.{spend_scope, current_scope, openrouter_call}`, `clue_spend.{LedgerStamp, HttpResponse}`;
  `lumen_agent.harness._fresh_model` (the monkeypatch seam `_instrument` calls with
  `role=f"design_{role}"`); `run_site_turn` (Task 7); `execute_site_turn_job` (Task 12);
  `DesignJobWorkHandler` and `_TRACE_SHAPES["site_turn"]` (Task 12).
- Produces: tests only.

- [ ] **Step 1: Write the runtime tests** `apps/agent_runtime/tests/test_site_cost_and_tracing.py`:

```python
"""B7 (Lane B Task 17): a site request's spend and model calls land where every design turn's do."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from langchain_core.messages import AIMessage

from clue_spend import HttpRequest, HttpResponse, LedgerStamp
from lumen_agent.config import AgentRuntimeConfig
from lumen_agent.site.harness import run_site_turn
from lumen_api import spend
from site_fixtures import FakeAssets, ScriptedModel, call, garner_site, inputs_for, png


class _Transport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = list(responses)
        self.sent: list[HttpRequest] = []

    def send(self, request: HttpRequest) -> HttpResponse:
        self.sent.append(request)
        return self.responses.pop(0)


def _priced(cost: float) -> HttpResponse:
    body = {"choices": [{"message": {"content": "{}"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": cost}, "model": "test/image"}
    return HttpResponse(status=200, body=json.dumps(body).encode())


def test_an_image_made_inside_a_request_is_charged_to_the_requests_scope(tmp_path: Path) -> None:
    seen: list = []

    def generate(**kwargs):
        # The provider's own path: one priced call through the open scope's caller.
        seen.append(spend.current_scope())
        spend.openrouter_call(operation="design.site.generate_image", body={"model": "test/image"},
                              label="site image", timeout_s=1, api_key="k", base_url="https://or.example/api/v1")
        return SimpleNamespace(image_bytes=png("white", (64, 36)), mime_type="image/png", width=64, height=36,
                               model="test/image", provenance={}, license=None)

    model = ScriptedModel(messages=iter([
        AIMessage(content="", tool_calls=[call("generate_image", {"prompt": "A calm classroom, morning light"}, 1)]),
        AIMessage(content="Made one image."),
    ]))
    with spend.spend_scope(LedgerStamp(workspace_id="ws_site", job_id=uuid4()), transport=_Transport([_priced(0.04)])) as scope:
        run_site_turn("Add a hero image.", config=AgentRuntimeConfig.from_env(),
                      inputs=inputs_for(assets=FakeAssets(), image_generate=generate),
                      workspace=tmp_path / "workspace", site=garner_site(), run_id="run_cost", model=model)
    assert seen == [scope], "generate_image ran outside the request's spend scope"
    assert [row.phase for row in scope.ledger.rows if row.phase == "result"] == ["result"]
    assert scope.caller.totals().usd == Decimal("0.04")


def test_the_site_model_is_labelled_design_site_at_the_gateway(tmp_path: Path, monkeypatch) -> None:
    from lumen_agent import harness as platform_harness

    built: list[tuple[str, str]] = []

    def fresh(runtime_config, model_id, *, role):
        built.append((model_id, role))
        return ScriptedModel(messages=iter([AIMessage(content="Nothing to change.")]))

    monkeypatch.setattr(platform_harness, "_fresh_model", fresh)
    config = AgentRuntimeConfig.from_env()
    run_site_turn("Look only.", config=config, inputs=inputs_for(), workspace=tmp_path / "workspace",
                  site=garner_site(), run_id="run_role")
    # One orchestrator model, the configured one (never a new model env), labelled for usage capture.
    assert built == [(config.orchestrator_model, "design_site")]
```

Run: RT `test_site_cost_and_tracing.py`
Expected: PASS. If the first test fails with `seen == [None]`, the scope does not reach the tool
thread: wrap the tool call in `contextvars.copy_context().run` inside `site_tool_set` (each
`StructuredTool`'s function becomes `lambda **kw: ctx.run(method, **kw)` with `ctx` taken when the
request starts), re-run, and record the finding in `_memory/2026-10-11-lane-b-site-agent.md`.

- [ ] **Step 2: Prove the executor stamps and drains the run's scope.** Append to
`apps/api/tests/test_site_turn_executor.py`:

```python
def test_a_site_turn_spends_inside_its_own_stamped_scope_and_drains_it(tmp_path, design_storage, _agent_workspace_in_tmp, monkeypatch) -> None:
    from uuid import UUID

    from lumen_api import main as api_main
    from lumen_api import spend
    from lumen_api.main import execute_site_turn_job

    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    store = HybridRepository()
    document = store.create_document(_site(f"doc_site_{uuid4().hex[:10]}"), doc_kind="site")
    seen: dict = {}
    drained: list = []
    monkeypatch.setattr(api_main, "_drain_spend", lambda scope: drained.append(scope))

    def runner(prompt, *, document, workspace, run_id, callbacks):
        seen["scope"] = spend.current_scope()
        return SiteTurnResult("applied", "No change.", document["scene"], None, [], [])

    envelope = _envelope(document["id"], store.workspace_id)
    run_id = str(uuid4())
    envelope = envelope.model_copy(update={"run_id": run_id, "checkpoint_thread_id": run_id})
    execute_site_turn_job(envelope, store=store, host=_host(app, runner), event_sink=lambda *_: None)
    assert seen["scope"] is not None and drained == [seen["scope"]]
    assert seen["scope"].stamp.workspace_id == store.workspace_id
    assert seen["scope"].stamp.job_id == UUID(run_id)
```

(`DesignTurnEnvelope` is a pydantic model, `subsystems/design/clue_design/envelopes.py:64`, so
`model_copy` gives the run a UUID id the ledger stamp can carry.)

- [ ] **Step 3: Prove the site turn is its own named trace, grouped by document.** Append to
`apps/api/tests/test_design_job_trace.py`:

```python
def test_a_site_turn_is_a_named_agent_trace_whose_session_is_its_document(inner_step: None) -> None:
    """Lane B: each site request runs on a fresh thread (the run), so the Langfuse session groups
    a document's requests by the document instead."""
    by_name = _run(DesignJobWorkHandler(), {**_TURN, "kind": "site_turn", "checkpoint_thread_id": "run-1"})
    step = by_name["design.step"]
    assert step["langfuse.trace.name"] == "design.turn"
    assert step["session.id"] == "doc-1" and step["user.id"] == "ws-1"
    assert set(step["langfuse.trace.tags"]) == {"design", "site_turn"}
```

- [ ] **Step 4: Run them.**

Run: API `test_site_turn_executor.py`, then API `test_design_job_trace.py`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add subsystems/clue-design/apps/agent_runtime/tests/test_site_cost_and_tracing.py subsystems/clue-design/apps/api/tests/test_site_turn_executor.py subsystems/clue-design/apps/api/tests/test_design_job_trace.py
git commit -m "site turns: prove spend reaches the tool threads and drains under the run's stamp, the design_site gateway label, and the document-grouped trace"
```

---
### Task 18: Rebuilding a seller's section — `view_clone` and `compare_section` on the renderer (R2), and the founder's live check (B8)

The spike's R2 tools drew sections on its dev server and cut each one out of the page
(`trials/puck-spike/agent/trials_puck_agent/tools.py:404-543`). Production has no dev server:
each section is drawn ALONE on a one-section scratch site (no shell) by Lane A's renderer through
the render port, so the full-page screenshot is the section. Every sentence the model reads is the
spike's (`skills-e5/rebuilding-a-section` and the tool texts), carried verbatim.

**Files:**
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/site/tools.py` (`view_clone`,
  `compare_section`, `_scratch_site`, `_draw`, module-level `_difference`, `_missing_words`,
  `_visible_text`)
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_site_clone_rebuild.py` (new)

**Interfaces:**
- Consumes: `SiteRenderPort.render/screenshot` (Task 4), `SiteTools._tiles`, `SCALE_BY_WIDTH`
  (Task 9), `SiteTools.sections` and `write_section` (Task 15).
- Produces:
  - `SiteTools.view_clone(fragment_id: str) -> list[dict] | str`
  - `SiteTools.compare_section(name: str, fragment_id: str, props: dict) -> list[dict] | str`

- [ ] **Step 1: Write the failing tests** `apps/agent_runtime/tests/test_site_clone_rebuild.py`:

```python
"""R2 (Lane B Task 18): look at a seller's section alone, and compare a rebuilt one with it."""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from lumen_agent.site.inputs import SiteSection
from lumen_agent.site.tools import SiteTools
from lumen_agent.site.workspace import materialize_workspace
from site_fixtures import garner_brand, garner_site, inputs_for

SCHEMA = {"type": "object", "properties": {"id": {"type": "string"}, "surface": {"type": "string"}, "heading": {"type": "string"}}}


@dataclass
class DrawingRenderer:
    """Draws a scratch site's one section: a clone as its stored HTML, an agent section as its
    heading. The picture is grey for a clone and white for a rebuilt section."""

    brand: dict
    calls: list = field(default_factory=list)

    def render(self, site, brand, sections, *, route):
        (item,) = site["pages"][route]["content"]
        self.calls.append(("render", item["type"], site.get("shell"), [s.name for s in sections]))
        if item["type"] == "ClonedSection":
            return f"<main>{self.brand['clones'][item['props']['fragmentId']]['html']}</main>", "", []
        return f"<main><h2>{item['props'].get('heading', '')}</h2></main>", "", []

    def screenshot(self, html, css, *, width):
        buffer = io.BytesIO()
        Image.new("RGB", (width, 400), "grey" if "<h2>" not in html else "white").save(buffer, format="PNG")
        return buffer.getvalue()


def _tools(tmp_path: Path, renderer) -> SiteTools:
    workspace = tmp_path / "workspace"
    inputs = inputs_for(renderer=renderer, agent_sections={
        "HeroRebuilt": SiteSection(name="HeroRebuilt", digest="e" * 64, props_schema=SCHEMA, module_js="export {}", css="")})
    site = garner_site()
    materialize_workspace(workspace, inputs, site=site)
    return SiteTools(workspace=workspace, inputs=inputs, base_site=site, retry_delay_s=0)


def _clone_id() -> str:
    return next(iter(garner_brand()["clones"]))


def test_view_clone_draws_the_section_alone_at_both_widths(tmp_path: Path) -> None:
    renderer = DrawingRenderer(garner_brand())
    blocks = _tools(tmp_path, renderer).view_clone(_clone_id())
    texts = [block["text"] for block in blocks if block["type"] == "text"]
    assert texts[1].startswith("The original at 1440 wide, in 1 part(s)") and texts[2].startswith("The original at 375 wide")
    assert [call[:3] for call in renderer.calls] == [("render", "ClonedSection", None)]
    assert sum(1 for block in blocks if block["type"] == "image") == 2


def test_view_clone_names_a_clone_that_does_not_exist(tmp_path: Path) -> None:
    assert _tools(tmp_path, DrawingRenderer(garner_brand())).view_clone("frag_nope") == "No clone frag_nope; see catalog/index.md."


def test_compare_section_scores_the_difference_and_lists_missing_words(tmp_path: Path) -> None:
    renderer = DrawingRenderer(garner_brand())
    blocks = _tools(tmp_path, renderer).compare_section("HeroRebuilt", _clone_id(), {"heading": "Something else entirely"})
    summary = blocks[0]["text"]
    assert summary.startswith("1440 wide: 100% of the area differs; heights 400px (original) and 400px (yours).")
    assert "Words of the original missing from yours: " in summary and "375 wide:" in summary
    rebuilt = [call for call in renderer.calls if call[1] == "HeroRebuilt"]
    assert rebuilt and rebuilt[0][3] == ["HeroRebuilt"]


def test_compare_section_needs_a_written_component(tmp_path: Path) -> None:
    result = _tools(tmp_path, DrawingRenderer(garner_brand())).compare_section("NotWritten", _clone_id(), {})
    assert result == "No component NotWritten on this site yet; write it with write_section first."


def test_a_render_that_fails_reads_as_the_spikes_sentence(tmp_path: Path) -> None:
    class Failing(DrawingRenderer):
        def render(self, site, brand, sections, *, route):
            raise RuntimeError("render.failed")

    tools = _tools(tmp_path, Failing(garner_brand()))
    assert tools.view_clone(_clone_id()) == f"Could not show {_clone_id()} (the preview did not render)."
    assert tools.compare_section("HeroRebuilt", _clone_id(), {}) == (
        "Could not compare: the preview did not show both sections. Check that the props fit "
        "HeroRebuilt's schema (catalog/seller-components.md)."
    )
```

Run: RT `test_site_clone_rebuild.py`
Expected: FAIL — `AttributeError: 'SiteTools' object has no attribute 'view_clone'`.

- [ ] **Step 2: Add the two tools.** In `tools.py`, copy the spike's `_difference` and
`_missing_words` verbatim to module level (`trials/puck-spike/agent/trials_puck_agent/tools.py:581-612`,
with `io` imported at the top of `tools.py`), and add beside them:

```python
def _visible_text(html: str) -> str:
    """The words a rendered section shows (tags and scripts dropped), for _missing_words."""

    import html as html_lib

    body = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S | re.I)
    return html_lib.unescape(re.sub(r"<[^>]+>", " ", body))
```

Then add to `SiteTools`, after `write_section`:

```python
    # --- rebuilding the seller's sections (R2) ----------------------------------------------------

    def _scratch_site(self, item: dict, sections: list[SiteSection]) -> dict:
        """A one-page site holding just this section, with no shell, so the page IS the section."""

        return {
            **copy.deepcopy(self.base_site),
            "shell": None,
            "agent_sections": {section.name: section.digest for section in sections},
            "pages": {"/": {"root": {"props": {"title": "scratch"}}, "content": [item]}},
        }

    def _draw(self, item: dict, sections: list[SiteSection]) -> tuple[str, str] | None:
        """``(html, css)`` of the section drawn alone, or None when it could not be drawn."""

        renderer = self.inputs.renderer
        if renderer is None:
            return None
        try:
            html, css, _warnings = renderer.render(self._scratch_site(item, sections), self.brand, sections, route="/")
        except Exception:  # noqa: BLE001 - the caller answers with the spike's sentence
            return None
        return html, css

    def _shot(self, drawn: tuple[str, str], width: int) -> bytes | None:
        try:
            return self.inputs.renderer.screenshot(drawn[0], drawn[1], width=width)
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _original(fragment_id: str) -> dict:
        return {"type": "ClonedSection", "props": {
            "id": "original", "fragmentId": fragment_id, "slots": {}, "replacements": [], "links": []}}

    def view_clone(self, fragment_id: str) -> list[dict] | str:
        """Look at one of the seller's sections on its own: desktop and mobile pictures, plus its card."""

        if fragment_id not in (self.brand.get("clones") or {}):
            return f"No clone {fragment_id}; see catalog/index.md."
        card_path = self.workspace / "catalog" / "clones" / f"{fragment_id}.md"
        blocks: list[dict] = [{"type": "text", "text": card_path.read_text()[:4000] if card_path.exists() else fragment_id}]
        drawn = self._draw(self._original(fragment_id), [])
        if drawn is None:
            return f"Could not show {fragment_id} (the preview did not render)."
        for width in (1440, 375):
            shot = self._shot(drawn, width)
            if shot is None:
                return f"Could not show {fragment_id} (the preview did not render)."
            tiles = self._tiles(shot, SCALE_BY_WIDTH.get(width, 1.0))
            blocks.append({"type": "text", "text": f"The original at {width} wide, in {len(tiles)} part(s), top to bottom."})
            blocks.extend(tiles)
        self._record("view_clone", fragment_id=fragment_id)
        return blocks

    def compare_section(self, name: str, fragment_id: str, props: dict) -> list[dict] | str:
        """Show the original section and your component side by side, with a difference score and
        the original's words your version is missing."""

        section = self.sections.get(name)
        if section is None:
            return f"No component {name} on this site yet; write it with write_section first."
        could_not = (f"Could not compare: the preview did not show both sections. Check that the props fit "
                     f"{name}'s schema (catalog/seller-components.md).")
        original = self._draw(self._original(fragment_id), [])
        rebuilt = self._draw({"type": name, "props": {"id": "rebuilt", "surface": "page", **(props or {})}}, [section])
        if original is None or rebuilt is None:
            return could_not
        blocks: list[dict] = []
        summary: list[str] = []
        scores: dict[int, float] = {}
        for width in (1440, 375):
            original_shot, rebuilt_shot = self._shot(original, width), self._shot(rebuilt, width)
            if original_shot is None or rebuilt_shot is None:
                return could_not
            score, pair, heights = _difference(original_shot, rebuilt_shot)
            scores[width] = score
            summary.append(f"{width} wide: {score:.0%} of the area differs; heights {heights[0]}px (original) "
                           f"and {heights[1]}px (yours).")
            if width == 1440:
                missing = _missing_words(_visible_text(original[0]), _visible_text(rebuilt[0]))
                summary.append("Words of the original missing from yours: "
                               + (", ".join(missing[:40]) if missing else "none") + ".")
            tiles = self._tiles(pair, 0.5 if width == 1440 else 1.0)
            blocks.append({"type": "text", "text": f"Side by side at {width} wide (original left, yours right), "
                                                   f"in {len(tiles)} part(s)."})
            blocks.extend(tiles)
        self._record("compare", name=name, fragment_id=fragment_id, scores=scores)
        return [{"type": "text", "text": "\n".join(summary)}] + blocks
```

`SiteSection` is already imported in `tools.py` (Task 6); `copy` too.

- [ ] **Step 3: Run the tests.**

Run: RT `test_site_clone_rebuild.py`, then RT `test_site_tools.py`, RT `test_site_harness.py`
Expected: PASS. (`test_compare_section_scores…`'s first line holds because the two pictures differ
everywhere — grey against white — and are the same height.)

- [ ] **Step 4: Commit.**

```bash
git add subsystems/clue-design/apps/agent_runtime/lumen_agent/site/tools.py subsystems/clue-design/apps/agent_runtime/tests/test_site_clone_rebuild.py
git commit -m "R2 on the platform: view_clone and compare_section draw each section alone through Lane A's renderer (the spike's texts verbatim)"
```

- [ ] **Step 5: Run the whole Lane B set once, in its separate sessions.** Each line is its own
pytest process (the runtime and API `conftest` modules collide):

```bash
cd subsystems/clue-design && set -a; source ../../.env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_trenton_wave1"; LUMEN_INGESTION_DESCRIBE=0 LUMEN_INGESTION_VISION=0 PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/agent_runtime/tests/test_site_package.py apps/agent_runtime/tests/test_site_workspace.py apps/agent_runtime/tests/test_site_tools.py apps/agent_runtime/tests/test_site_harness.py apps/agent_runtime/tests/test_site_render_tool.py apps/agent_runtime/tests/test_site_images.py apps/agent_runtime/tests/test_site_search_assets.py apps/agent_runtime/tests/test_site_sections_tool.py apps/agent_runtime/tests/test_site_clone_rebuild.py apps/agent_runtime/tests/test_site_cost_and_tracing.py apps/agent_runtime/tests/test_session_sync.py apps/agent_runtime/tests/test_search_assets_hybrid.py -q -o addopts="" --ignore-glob='*_live.py'
```

```bash
cd subsystems/clue-design && set -a; source ../../.env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_trenton_wave1"; LUMEN_INGESTION_DESCRIBE=0 LUMEN_INGESTION_VISION=0 PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest apps/api/tests/test_site_kit_cli.py apps/api/tests/test_site_brand.py apps/api/tests/test_site_workspace_view.py apps/api/tests/test_site_turn_ports.py apps/api/tests/test_site_turn_executor.py apps/api/tests/test_site_fleet_dispatch.py apps/api/tests/test_site_section_tool.py apps/api/tests/test_site_section_links.py apps/api/tests/test_design_job_trace.py apps/api/tests/test_write_path_governance.py apps/api/tests/test_workspace_seam_route_table.py -q -o addopts="" --ignore-glob='*_live.py'
```

```bash
set -a; source .env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_trenton_wave1"; .venv/bin/python -m pytest tests/api/test_arv2_read_tools.py tests/arv2/test_read_tools_db.py tests/api/test_design_platform_reads_db.py tests/design/test_site_sections_dal_db.py tests/api/test_site_leg_birth_db.py tests/api/test_site_turn_summaries.py tests/api/test_site_checkpoint_forwarding.py tests/agents/test_tool_authority_audit.py tests/agents/test_catalog.py tests/api/test_toolbelt_wiring.py tests/api/test_agent_registry_wiring.py tests/test_site_section_link_settings.py tests/deploy/test_backend_image.py -q -o addopts="" --ignore-glob='*_live.py'
```

```bash
cd apps/frontend && npm run build -w @clue/site-kit && npx tsx --test packages/site-kit/test/*.test.ts && npm run typecheck -w @clue/site-kit
```

Expected: every line passes (the design-API governance file keeps only its pre-existing
`asset_enrichment.py:51` failure if Lane A has not fixed it). Stop the lane's design stack first
(`./scripts/dev_stack_trenton.sh down`, or whatever `DEV_STACK.md` names for this lane): its
embedded and fleet workers claim test jobs from a shared database.

- [ ] **Step 6: The live check — the founder's go, the founder's run.** A live request spends
model money (up to 100 orchestrator calls, plus image generation). Ask the founder exactly:

> Lane B is ready for one live website request on the trenton stack. It spends model money (up to
> 100 calls on the orchestrator model, plus any images it generates). Do you want to run it now?
> If yes, which workspace and project, and which request — for example "Build a one-page site for
> <account>" and then "Rebuild the seller's hero section as a component and use it on the page"
> (the second exercises write_section, view_clone and compare_section)?

Do not start the stack or the request yourself; the founder drives the run in the app. Wait for
the founder to say the run finished, and the run id (the leg's run, shown in the design activity
or read below).

- [ ] **Step 7: Read the outcome (reads only).** From the repo root, with the lane's own `.env`:

```bash
set -a; source .env; set +a; PGURL="${CLUE_DATABASE_URL/postgresql+asyncpg/postgresql}"
psql "$PGURL" -c "SELECT run_id, kind, status, result_json->>'status' AS outcome, result_json->>'stop_reason' AS stop, result_json->>'current_version' AS version, updated_at FROM design_agent_run WHERE kind = 'site_turn' ORDER BY updated_at DESC LIMIT 3"
psql "$PGURL" -c "SELECT turn_id, count(*) AS model_calls, sum(cost_usd) AS usd FROM agent_model_call WHERE role = 'design' AND started_at > now() - interval '2 hours' GROUP BY turn_id ORDER BY max(started_at) DESC LIMIT 3"
psql "$PGURL" -c "SELECT operation, count(*), sum(cost_usd) FROM provider_call_ledger WHERE recorded_at > now() - interval '2 hours' AND operation LIKE 'design.%' GROUP BY operation"
psql "$PGURL" -c "SELECT name, digest, created_by_run_id, created_at FROM design_site_section ORDER BY created_at DESC LIMIT 5"
```

Expected (what to check, not what to force): the run is `succeeded` with outcome `applied` and a
version; its model calls are on the leg's turn under role `design` (the ledger's profile role;
the `design_site` sub-role lives in Langfuse, `design_leg_wiring.py:1052`); image spend (if any) is in the
ledger; a rebuilt section, if asked for, has a `design_site_section` row stamped with the run. Ask
the founder to open the site in the editor and confirm the change is there and one undo step
reverts it. Record the run id, the numbers and the founder's verdict in
`_memory/2026-10-11-lane-b-site-agent.md` under "Live check", and commit:

```bash
git add _memory/2026-10-11-lane-b-site-agent.md
git commit -m "memory: Lane B live site request (founder-run) — outcome and numbers"
```

If the founder declines, record "Live check: owed (founder declined on <date>)" instead and commit
the same file.

---

### Task 19: Close-out — memory, the coordination notes, and the open items

**Files:**
- Modify: `_memory/2026-10-11-lane-b-site-agent.md`
- Modify: `docs/superpowers/plans/2026-10-09-website-agent-on-puck-integration.md` (the Wave 2
  Contract 4 bullet: `props_schema` in the section-links response; Contract 1's `brand_kit` key)

- [ ] **Step 1: Check the master plan's contracts match what this lane shipped.** The controller
amended them at the 2026-10-11 review (Contract 1's `{"id", "version"}` kit ref; Contract 4's
`{"links": [... props_schema]}` response and its `.mjs` / `.css` module routes with
`x-clue-workspace-id`; Contract 7's site `targets`). Confirm each still matches the merged code:

```bash
grep -n '"brand_kit": {"id"\|"links"\|site-sections/{digest}.mjs\|x-clue-workspace-id\|targets' docs/superpowers/plans/2026-10-09-website-agent-on-puck-integration.md
```

Expected: each phrase is printed. If the shipped code differs from a contract line, change the line
to the code's truth and say so in the commit message.

- [ ] **Step 2: Write the closing memory entry.** Append to `_memory/2026-10-11-lane-b-site-agent.md`
a section "Close-out" with: the commits of Tasks 1–18 (`git log --oneline` since the branch's
Lane B start), the design profile version minted, the migration id, the env key added, the
founder's answers to the four open questions and the T1–T14 review, every test command run with
its result, and what remains owed (the live check if declined; contract conflict 8's image change
if Lane A has not built it; the residuals below).

Residuals to list (each is real and unowned until the founder assigns it):
- The site agent's E5 tools are on by default; a workspace cannot turn them off (no flag by
  ruling — "built features on by default").
- `read_cited_claims@1` holds a cited id the gate refuses even when the page's statement rests on
  more than one claim; the statement leaves the research files whole (fail closed).
- Account logos are fetched at the start of every request (cached by the logo family cache); a
  request with no account card has none.
- Section CSS is Tailwind's output under the brand of the site that first compiled it; a section
  placed on a site of another brand in the same workspace keeps that CSS (the renderer compiles a
  site's CSS over its own HTML, so rendered pages are right; only the editor's injected CSS can
  differ).

- [ ] **Step 3: Commit.**

```bash
git add _memory/2026-10-11-lane-b-site-agent.md docs/superpowers/plans/2026-10-09-website-agent-on-puck-integration.md
git commit -m "memory + master plan: Lane B close-out (section-links props_schema, brand_kit key, residuals)"
```
