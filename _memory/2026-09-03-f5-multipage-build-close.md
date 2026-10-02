# 2026-09-03 — F5 multi-page sites + real publishing: BUILT on `design/website-multi-page`

Execution of `docs/superpowers/plans/2026-09-02-f5-multipage-sites-and-publishing.md` (22 tasks)
via SDD. Process (founder rules): Opus implementers only; Fable did every review, verification and
ruling inline (no reviewer subagents, no Opus scouts); every task's diff read and its tests re-run
first-hand before acceptance. 26 local commits `38b830289..3e835b230` (never pushed). Ledger with
every ruling: `.superpowers/sdd/2026-09-02-f5-multipage-sites-and-publishing/progress.md`.

## What landed (by lane)
- **Engine (T1–T3):** `route_is_valid` + LUMW0036 (validate.rs); `AddPage`/`RemovePage` ops,
  invertible, route-checked; `SetPageMeta` refuses bad/duplicate routes. Helper + wasm rebuilt,
  HANDSHAKE OK. API round-trip test through `/web/operations` (422 now carries `engine_code`).
- **Render (T4–T5):** `GET /web/render?page_id=` (first page default, typed 404
  `web_render.page_missing`); `resolve_web_page_id` in main.py; frontend fetch/hook/canvas take
  `pageId`.
- **Agent (T6–T9):** `LumenWebTools` active page + `list_pages/add_page/remove_page/switch_page`
  (switch resets budget + previews + state captures); turn side resolves fragments/targets across
  pages (`web_doc_all_fragment_ids`, `build_fragment_render_package_for_document`); harness
  registers page tools (author gets `list_pages` only); prompt laws ONE AUTHOR BRIEF PER PAGE +
  LINKS; skills create-website/edit-website/campaign-page-workflow gained page sections;
  conversion-copywriting YAML fixed (it had NEVER loaded). R-F5-8: campaign-shell shape gate and
  by-role nav/footer refusal → advice (`campaign_shell_shape_notes`); unlisted-pin refusal → advice.
- **Publish (T10–T12):** migration `6893f29b6973` (`design_web_publish_revision_page`, immutable,
  keyed `(publish_id, workspace_id, route)` because publish_id is a shared content address;
  `design_web_publish_page` materialized per `(workspace, slug, route)`, rebuilt on publish and
  rollback); publish package renders every page (`PublishedPage`), per-page SEO/CSS/noindex,
  `rewrite_site_links` exact-match, export ZIP one folder per page; serving `/w/{ws}/p/{slug}` +
  `/{route:path}` with legacy `/` fallback; `PublicSiteAddress` (`public_address.py`) from
  `LUMEN_PUBLIC_PAGES_HOST_SUFFIX` (blank = interim path) + `LUMEN_PUBLIC_PAGES_SCHEME`; all
  reported URLs absolute; `page_urls` on GET and POST.
- **Shell + domain (T13–T16):** real Publish via `WebPublishRepository` (fixture + HTTP over BFF),
  no timer, no `SHARE_HOST`; `noindex` on the publish request; workspace handle (migration
  `5456c0770de8`, DAL `workspace_handles.py`, `GET/PUT /workspace/handle`, locked at first publish);
  Host-matched public pages sub-app (`public_pages.py`, mounted only when the suffix is set;
  resolver = custom-domain seam); share menu lists per-page links (Advanced → Page settings).
- **Editor (T17–T21):** TS builders + `routeIsValid` mirror; session-owned active page + header
  switcher (≥2 pages); inspector Page section (name/route/add/remove) with pure decisions in
  `inspector-page-field.ts`; bridge posts `lumen:navigate` for route hrefs → active page switch;
  dev-shell parity (active-page-first `findWebNode`, select switcher, route card).
- **Fix wave:** 3 pre-existing agent-turn test failures fixed (`_fake_turn` lacked
  `cancel_requested`); `apps/frontend/docs/api-contracts/web-publish.md` written.

## Verification at close
- Cargo workspace: 70 result lines, all ok. Frontend `npm test`: 2089 pass / 0 fail; lint/build
  green per task reports. Platform ruff/mypy on touched files clean; `alembic heads` =
  `5456c0770de8` (single head). Design API full suite + agent-runtime per-file loop: see the
  appended RESULTS section below.
- Test env facts for this worktree: NO `.env`, no subsystem `.venv` (use root `../../.venv`); design
  API tests need `CLUE_DATABASE_URL=postgresql+asyncpg://clue:clue@localhost:5432/clue_f5_multipage_test`
  (disposable DB created + migrated for this lane — drop when done); `apps/frontend/node_modules`
  and `apps/editor/node_modules` were installed here.

## OPEN — founder
1. **CP3 live walk (Task 22) NOT run**: needs the dev stack via DEV_STACK.md and the dev DB
   migrated to `5456c0770de8`. Walk: 3-page ABM microsite in one leg → switch pages → rename a
   route → Publish → every route serves → unpublish/rollback → export ZIP folders.
2. Prompt/skill wording (T8) quoted verbatim in `task-8-report.md`; two R24-1 absolutes remain
   (`prompts_web.py` "never reach for the cloned nav"; `fragments/abm_page.py` docstring).
3. FLAGGED UI slots with no design: page switcher (header), Page section (inspector), per-page
   links list (share menu Advanced tab). Description/custom-HTML/regenerate fields unwired.
   Unpublish exists in the seam, no control. Bare host root `{handle}.<suffix>/` → 404 (no
   default site). R-F5-5 handle default still a plan default.
4. Deployment/domain (public ingress for the design API, wildcard DNS+TLS, custom domains) —
   ruled out of scope for now; DEV_STACK.md carries the operator prerequisites.
5. Local `.env` files in other worktrees need the two new keys (parity rule).

## Deferred minors (ledger)
Three hand-kept route-grammar copies without a shared fixture; `_describe_web_turn_targets`
first-page-wins on duplicate node ids until the platform sends `active_page_id` for web turns;
per-page node CSS compile cost; advice bucket mixes dicts and sentences; brief first-page flicker
after add page; `test_custom_component_publish` needs node deps here; one implementer used
`git stash` once (T20) — verified harmless.

## RESULTS (appended 2026-09-03)
- Agent-runtime suite, one file per process: 57/57 files green (no F/E in any file; test_fetch_logo_tool re-run alone, exit 0).
- Cargo `--workspace`: all 70 result lines ok. Frontend `npm test`: 2089 pass / 0 fail.
- Design API full suite (`apps/api/tests`, single process, ~55 min): 23 failures, all triaged — 17 custom-component tests (ERR_MODULE_NOT_FOUND `typescript`: no node deps under subsystems/clue-design in this worktree; pre-existing class), 2 asset-store/custody 404s (stale shared-DB artifact rows; pre-existing), 3 in test_web_turn_asset_base_url (a 4th fake-turn stub lacking `cancel_requested` + a source-grep pin on the ZIP asset base that Task 11 legitimately changed to `f"{prefix}assets"`) — FIXED in d4a866cf4 + 89a2382b8, and 1 REAL F5 GAP: the new `GET /w/{ws}/p/{slug}/{route:path}` route was missing from the O4 workspace-seam ALLOWLIST beside its sibling — FIXED in a0a5f388e (both files re-run first-hand, green). No other failure.

## 2026-09-03 afternoon — browser-testing setup + share-menu follow-ups (commits 36ee7f07e..805c270b9)
- DBs: `clue` (localhost:5432) is the shared TEST-SUITE db (31k workspaces, fixture user "Avery QA", foreign migration lineage 612428f3731f from missoula/semarang; its field registry conflicts with this branch's core pack — fleet worker cannot start on it). Cloned as `clue_dushanbe` (stamped to fork a1c5b9842f0e + upgraded) as asked, but NOT used. The real dev db is `clue_istanbul_dev`; cloned via pg_dump 17 to `clue_dushanbe_dev` (head 5456c0770de8) + istanbul/.artifacts rsynced to dushanbe/.artifacts. Stack from this worktree runs on 3026/8016/8026/8036 (`CLUE_DEV_*` keys in .env; pidfile-scoped down; logs /tmp/browser_*_dushanbe.log).
- dev_stack.sh parameterized (36ee7f07e). Agent catalog digests re-pinned for design_publish_web + design_rollback_web_publish (output = WebPublishRef gained page_count/routes) — done by Fable directly (one yaml value each) while the founder waited.
- Share menu: Preview externally opens shareUrl; ZIP downloads GET /documents/{id}/web/export via the seam (a6e1b18e4); NEW web PDF export route GET /documents/{id}/web/export.pdf (web_pdf.py: publish package pages -> Chromium page.pdf -> pymupdf merge, nothing persisted; c0ad7d056) + PDF button (805c270b9). Live-verified with curl on the OpenAI page: zip 200 (8 files), pdf 200 (3 pages).
- Founder question answered: Preview/ZIP were backend-existing + unwired; web PDF was built from scratch.
- ZIP export was self-blocking: the bundle's meta CSP (no public_base -> no origin, no self) refused its own site.css/assets/fonts on disk and on any static host — pre-F5 defect, never walked. Fixed 335653548: `_delivery_csp(static_bundle=True)` adds `'self'` + `file:` to script/style/img/font; publish/serving CSP byte-identical; Playwright file:// test added (images naturalWidth>0, site.css present, zero CSP violations). Stack restarted; re-export of the OpenAI page carries the new policy.
- PDF export layout (founder: "breaking up"): was print media + A4 with 10mm margins (~718px content box < md:768 -> mobile squeeze). Now 768 viewport + screen media, bands fill the 794px A4 sheet (no margins, no body pin), asset-store refs inlined as data: URIs (Chromium had no origin -> broken logo/alt text), atoms (headings/p/li/img) unbreakable while bands may split (whole-band avoid left half-page voids). Commits ea3681a5f, 452c97314, 2ceaaa399. Fable rasterized the live OpenAI export with pymupdf and inspected every page: logo, ribbon, photo band, 3-col grid all correct.
