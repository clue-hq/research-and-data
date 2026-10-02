# Vendor-first logo family — build close-out (2026-09-02)

**Status: BUILT.** Branch `design/website-logo-v2` (Conductor worktree `singapore-v1`), local
commits only — nothing pushed.

- Plan (authoritative): `docs/superpowers/plans/2026-09-02-vendor-first-logo-family.md` — its
  **Execution status** list and **Deferred items ledger** are the source of truth for per-task
  status and every deferral.
- SDD ledger (rulings, reviews, live runs): `.superpowers/sdd/2026-09-02-vendor-first-logo-family/progress.md`.
- Decision record this implements: `_memory/2026-08-31-logo-vendor-first-decision.md` (now marked BUILT).
- Current-state map read before planning: `_memory/2026-09-02-logo-system-current-state.md`.

What it is, in one paragraph: fetching a target account's logo is now **vendor-first**. The
Brandfetch Brand API is rung one (one keyed call by domain); the in-house scrape ladder is rung
two and backfills **only** the cells the vendor left empty. The tool contract is a **2×2 family** —
`light_lockup`, `dark_lockup`, `light_mark`, `dark_mark`, where the theme names *the background the
asset is for* — returned whole by one `fetch_logo` call on both design lanes. Each family is cached
durably per `(workspace_id, registrable_domain)`; `force_refresh=True` is the eviction affordance.
Decorative third-party logos inside generated pages go through a separate **hotlink** lane (Logo API
CDN URLs written into markup) and never through custody. An empty cell stays a correct answer:
nothing in this build invents, recolors or approximates a logo.

## 1. What shipped, per task

Commits, newest last. All authored by the human committer; no AI attribution anywhere.

| Task | Commits | What landed |
|---|---|---|
| 1 | `0cf64d654` | 4 `BRANDFETCH_*` settings fields in `py_lumen_config`, with env lines in both `.env.example`s (parity rule, same commit). |
| 2 | `5a6e05d78` | `lumen_ingestion/logo_family.py` — the shared 2×2 vocabulary (`CELL_NAMES`, `cell_name`, `FamilyCell`, the `SOURCE_*` constants). |
| 3 | `e8a5efe63` | `logo_vendor.py` parsing + mapping: `parse_brand_payload`, `pick_format`, `map_vendor_assets_to_cells` (theme inversion, `icon`/`other`/photographic filtering, SVG renderability gate). |
| 3b | `9387f9b7f` | D2 + D3: Pillow `_raster_decodes` gate for png/webp/jpeg cells; base-url env assertion. |
| 4 | `abe5d9d4f`, `417da50b4` | The network driver `fetch_vendor_family` — 404-is-an-answer, typed `quota`/`auth`/`timeout`/`http`/`malformed` degrades, the `brandfetch.io` asset-host allowlist (D6), and an explicit `User-Agent` on the lookup *and* every asset download. Live-verified with the real key. |
| 5 | `50908e087` | `ladder_cells()` — the ladder's four slots folded into the 2×2 (symbol-shaped primary is a MARK; wordmark backfills `light_lockup`). |
| 6 | `08de3c8e2`, `ab6b477a4`, `2d1d31d8e` | The two-rung dispatch in `lumen_agent/tools/logo_fetch.py`: cache → vendor → per-cell ladder backfill, `PreparedLogo`/`LogoFetchOutcome`, per-cell `source` and `provenance` stamping. |
| 7 | `16857940d`, `dcbcd4b63` | The durable cache: migration `1d09aba87206` (`design_logo_family`), the `clue_design/logo_family_cache.py` DAL, the `DurableLogoFamilyCache` wrapper over `DesignBlobStore`. |
| 8 | `753e1e9d7` | `bind_account_logo`'s provenance gate widened to accept `brandfetch` alongside `logo_ladder`; generated images and placeholders still refused. (Ran before Task 7 to close the vendor-logos-unbindable window.) |
| 9 | `8c3d0f3f7` | The cache composed into BOTH turn functions (`run_agent_turn_preview`, `run_web_agent_turn`); `brandfetch_client_id` on the runtime config. |
| 10 | `7f301f62f` | Both `fetch_logo` tools speak cells end to end — payload `logos[]` with `cell`/`source`, `force_refresh`, `cache_hit`, `failed_cells`. Batch 4–10 live-verified end to end. |
| 11 | `aa8b943a3`, `6c3748fb6` | Prompts + the `abm-page.md` knowledge doc rewritten to the 2×2 cell vocabulary (D4 + D7 closed). |
| 12 | `598ac2d64` | The hotlink lane — prompt prose only, rendered whenever `brandfetch_client_id` is set. |
| 13 | — (empirical; caveat sentence in `79727edb6`) | Hotlink render verification. No code. See §2. |
| 14 | `193ba27e3`, `426a28a20`, `a3141df88`, `10e7c0479`, `4f48750ad` | Suite-wide vendor guard (D9), the end-to-end mixed-provenance test, the warnings filter (D1), the gates, and this record. |

## 2. Task 13 — the empirical hotlink result

Question: does a hotlinked Logo-API CDN image render in our automated contexts? Three byte-identical
runs of a throwaway script (`.context/hotlink_check.py`, git-excluded; the client id was parsed from
`.env` at runtime and redacted from every log line).

URL under test: `https://cdn.brandfetch.io/domain/brandfetch.com/fallback/404/type/logo?c=<redacted>`

| # | Context | Final status | `x-bf-error` | `naturalWidth` | Verdict |
|---|---|---|---|---|---|
| A | Served localhost page, **headless** chromium (Referer set) | 302 → docs guidelines | `automated_traffic` | 0 | REFUSED |
| B | Served localhost page, **headed** chromium | 200 `image/webp` | — | 820 | SERVED |
| C | `page.set_content(html)`, headless (about:blank, no Referer) | 302 | `automated_traffic` | 0 | REFUSED |
| D | Sandboxed `srcdoc` iframe (origin `null`, no Referer), headless | 302 | `automated_traffic` | 0 | REFUSED |
| E | `httpx.get`, browser-like UA, **no Referer**, no cookies | 200 `image/webp` (15698 B) | — | n/a | SERVED |

**The finding: the guard is a User-Agent check, not a Referer check.** Contexts F/G/H re-ran A/C/D
headless with nothing changed but a non-headless UA string — all three flipped to 200. Context E
(no browser, no Referer at all) is served. Two corollaries worth remembering: `fallback/404` is
never consulted on a refusal (the guard short-circuits with a **302** first, so "hotlink failed"
never looks like a 404), and the heuristic survives none of `navigator.webdriver`, CDP control, or
an opaque iframe origin.

Shipped consequence: the author prompt carries the caveat, amended to what was actually measured —
*"Automated renders (the page thumbnail, the reviewer's render) may show a hotlinked logo as empty;
it renders in the editor preview and on the published page."* (the plan's original wording was
false: a human's editor preview is a headed real Chrome, i.e. context B, which is served).

**A UA override was NOT applied — this is open decision D11 (founder).** Our three production
Playwright launch sites all run `headless=True` with no `user_agent`, so all three currently present
the `HeadlessChrome` token and would be refused:

- `subsystems/clue-design/apps/api/lumen_api/document_thumbnails.py:178`
- `subsystems/clue-design/apps/api/lumen_api/clone_review/browser.py:87`
- `subsystems/clue-design/apps/api/lumen_api/fragments/isolation.py:237` — separate matter: this page
  installs a fail-closed route handler allowing only this workspace's own bytes, so a hotlink is
  blocked there by **our own policy** regardless of UA.

The mitigation is one `user_agent=` argument per site. It was deliberately not taken: presenting a
non-headless UA to a vendor CDN whose guard is explicitly refusing automated traffic is a
terms/compliance call for the founder, not an implementation detail. Until it is decided,
thumbnails and the review-gate walk show decorative hotlinked logos as empty.

## 3. Deviations from the plan

Each of these was ruled at execution time and is recorded in the plan's ledger; listed here so the
next reader does not re-derive them.

- **D8 — vendor cells ingest with the engine's `website` source kind.** Task 6 originally stamped
  `source_ref["kind"] = "vendor"`, and the engine's serde-tagged `AssetSource` enum
  (`crates/lumen-core/src/assets.rs`) has no such variant, so **every real vendor ingest failed**
  `helper.asset_source` while the mocked tests stayed green. Caught only by a controller live run.
  Vendor cells now use `website` with the asset's own URL; the vendor identity lives in
  `provenance.created_by` / `source_label` = `brandfetch`. No engine change (crates were out of scope).
- **The status rule for hesitant ladder families.** `status == "ok"` iff something was prepared AND
  (a `brandfetch`-sourced cell exists OR the ladder returned `resolved`). A ladder that hesitated
  (alternate lockups, a non-auto-accept rung) still *prepares* its cells — the agent may place them —
  but the outcome stays `needs_review`, and `cache.put` runs only on `ok`. The first implementation
  used a bare `status = "ok" if prepared`, which both dropped the ladder's hesitation signal and
  would have frozen a family a human must adjudicate into a no-TTL cache.
- **The DAL placement.** The cache's SQL lives in `subsystems/design/clue_design/logo_family_cache.py`
  (async functions over `AsyncConnection`) reached through `DesignStoreBridge`, mirroring how
  `HybridRepository` delegates to `clue_design.accounts` — not raw SQL inside `lumen_api`.
- **D4 — the account-scoped prompt block.** The web author's `fetch_logo` prose lives *inside*
  `account_block`, so the rendered-prompt test passes a truthy `account_card="{}"`; a second render
  without an account asserts only that the old slot phrasing is gone.
- **Task 12's hotlink block renders in the GENERAL author prompt**, not inside `account_block` —
  customer logo walls and integration strips are landing-page sections, not ABM-only.
- **`PreparedLogo.slot`** survived as a read-only alias of `.cell` from Task 6 to Task 10 so the two
  tools kept working across four tasks; it is gone at Task 10 (grep-verified, zero `xfail` left).

- **Final-review fix `c1196ed8d` — vendor cells survive a blocked ladder backfill.** `fetch_logo_family`
  ran the ladder whenever a cell was missing, and the ladder's `CaptureError` (blocked/unreachable
  site) propagated to both tools, which discarded the vendor's cells behind an error envelope. Now:
  vendor filled ≥1 cell → the failure is a note and the partial family stands (and caches — D15);
  vendor filled nothing → re-raised as before.

## 4. Deferred markers (open work, owned by nobody yet)

- **Batch-time slot selection consumes `CELL_NAMES`.** The batch/personalization path that picks
  *which* cell to place per page (light vs dark background, lockup vs mark) is not part of this
  build. It should read `lumen_ingestion.logo_family.CELL_NAMES` rather than re-spelling the four
  names, so the vocabulary stays defined in one place.
- **The free-tier quota ceiling.** The live smoke returned `x-api-key-quota: 100`, and
  `x-api-key-approximate-usage` incremented even on a vendor-documented "free" domain — treat "free"
  as unverified and do not re-probe casually. When the ceiling is hit, the vendor answers **HTTP 429**
  → `VendorLookupFailed(code="quota")` → the dispatch appends a note to `LogoFetchOutcome.notes`
  ("vendor rung degraded (quota): …") → the tool payload's `notes` / `vendor_notes`, and **the ladder
  takes over for every cell**. The degrade is honest and never a hard failure, but nothing today
  *alerts* on it: a workspace could silently run ladder-only for a month. No monitoring is wired.
- **No TTL on the cache** (founder decision #4): rows grow unbounded by distinct domain per
  workspace. `force_refresh=True` is the only eviction. Revisit only if it ever matters.
- **D11 — the headless-render UA decision** (see §2). Open, founder-owned.
- **The pre-existing `conftest` collision.** `apps/api/tests` and `apps/agent_runtime/tests` cannot
  share one pytest process: both directories hold a `conftest.py`, neither is a package, so
  `apps/api/tests/test_logo_family_cache.py`'s `from conftest import make_blob_store` resolves to
  whichever conftest landed in `sys.modules` last and errors. Reproduced unchanged at
  `79727edb6` — pre-existing, not this plan's. Run the two suites as two invocations (which is what
  `subsystems/clue-design/AGENTS.md` §3 already prescribes).
- **Three `pymupdf` SWIG `DeprecationWarning`s** (`builtin type SwigPyPacked/SwigPyObject/swigvarlink
  has no __module__ attribute`), raised at `logo_ladder._rasterize`'s lazy `import pymupdf` on
  Python 3.12 — third-party and pre-existing. **Filtered** (a second narrow `filterwarnings` entry
  in the root `pyproject.toml`, alongside the starlette one), so both focused gates now end with
  `N passed` and no warnings summary at all. The filter hides noise we cannot act on; if pymupdf
  ever warns about something real under that same message shape, the regex is narrow enough that
  only `builtin type … has no __module__ attribute` is swallowed.

## 5. Full-suite results

Both suites run from `subsystems/clue-design` with the §6 env prefix (vendor key blanked, release
helper pinned) and `-p no:cacheprovider -q -rf`. Results collected by the controller 2026-09-02.

- **`apps/agent_runtime/tests` — GREEN.** 0 FAILED/ERROR, progress reached [100%]. Read off
  `/tmp/t14_agent_runtime_suite.log`: 1569 passed, 1 skipped, zero `F`/`E` characters, no `FAILED`
  lines. (The log has no closing `N passed in Xs` line — the process appears to die at interpreter
  shutdown after the warnings summary — so the counts are from the progress characters, which are
  complete.)
- **`apps/api/tests` — 29 distinct failing tests** (`/tmp/t14_api_suite.log`; distinct list
  `/tmp/t14_api_failed.txt`). Against the D10 baseline (`/tmp/d10_baseline.txt`, 28 tests):
  **28 identical, 0 fixed, 1 new.**

The one new failure is `test_ingestion_grammar_audit.py::test_the_published_draft_kit_carries_the_grammar_audit`.
It fails at the same assertion and the same line (587, `'running' == 'succeeded'` after
`wait_for_ingestion_job`) as its two baseline siblings in the same file: a live brand-kit ingest
whose grok-4.5 "ingestion-brief" completion took 66.6s and outran the 60s poll budget. The
controller re-ran it in isolation at HEAD and it **passed in 58s**; the ingest path imports no plan
code. **Controller ruling: same live-LLM-latency class as the two baseline siblings, not a
regression.**

### Triage of the 28 baseline failures, by cause

Read off the failure sections in `/tmp/t14_api_suite.log` (each test's `E ` lines and first
exception).

**A. Custom-component compiler / publish / runtime — 14 tests. Cause: environment / toolchain.**
`test_agent_custom_components.py` (1), `test_custom_component_compiler.py` (5),
`test_custom_component_publish.py` (4), `test_custom_component_runtime.py` (4). Every one returns
`503` from the compile route with the same diagnostic body:

```
"status":"transient_error","compiler_version":"unavailable",
"diagnostics":[{"code":"CCI0002","category":"infrastructure",
  "message":"custom-component compiler returned invalid JSON: …
    Error [ERR_MODULE_NOT_FOUND]: Cannot find package 'typescript' imported from …/subsystems/"}]
```

The Node compiler worker cannot resolve `typescript`, i.e. its npm dependency tree is not installed
in this worktree. The engine itself classifies this `infrastructure`. Same class as D10's
`apps/editor/node_modules` gap — the controller's `npm install` covered `apps/editor`, not the
compiler's own package directory.

**B. Image model w14 / w17 — 4 tests (`test_api.py`). Cause: config (the test fixture does not pin
the transport, so it inherits the operator's `.env`).** `_image_model_env` (test_api.py:4260) sets
`image_model_base_url` / `_api_key` / `_id` but **not** `image_model_api_style`. This workspace's
`.env` — and both `.env.example`s — set `IMAGE_MODEL_API_STYLE=images`, so `_invoke_model` routes to
`_invoke_images_api`, while the w17 stubs feed **chat-completions-shaped** payloads:

```
E  lumen_api.image_provider.ImageGenerationError: images API response contained no
   data[0].b64_json or data[0].url: {'choices': [{'message': {'images': [{'image_url': …
E  … : {'choices': [{'message': {'content': "I can't make that image."}}]}
```

These three (`w17a`, both `w17b`) pass only when the env selects `chat`. Not live-model
nondeterminism — `httpx.post` is monkeypatched in all of them. The fourth, `w14`, is consistent with
the same routing cause (its typed error is raised correctly; only the W1.4 diagnostic log line is
missing — `assert 'openai/gpt-image-2' in ''`), but its section does not disambiguate "the images
branch does not emit that diagnostic" from a structlog/`caplog` capture issue — **cause not fully
established from the log** for w14 alone.

**C. Asset custody / asset-store serving — 3 tests. Cause not established from the log.**
`test_asset_custody.py` (2), `test_asset_store_serving.py` (1). All three are
`assert 404 == 200` on `GET /asset-store/{digest}`. The log shows a clean 404 from the route with no
exception and no error event — and in the same test the sibling routes succeed
(`/assets/{id}/bytes` 200, `/assets/{id}/thumbnail` 200), so the rows and bytes exist and only the
content-addressed lookup misses. A storage-root/config mismatch in this worktree is the most likely
explanation, but the log does not prove it.

**D. Grammar audit — 2 baseline tests (`test_ingestion_grammar_audit.py`). Cause: live-model
latency.** Both end with `{'status': 'running', 'stage': 'Preparing your brand kit…'}` after
`wait_for_ingestion_job`'s 60s budget: a real brand-kit ingest whose LLM call had not returned. The
third test in this file is the new failure discussed above, same shape, and it passed on an isolated
re-run — which is the direct evidence for the latency label.

**E. Web-turn composition / fragment render / asset base URL / cloned sections — 5 tests. Cause not
established from the log.** `test_agent_cloned_sections.py` (1), `test_web_fragment_render.py` (2),
`test_web_turn_asset_base_url.py` (2). All five monkeypatch `harness_web.run_deepagent_web_turn`
with a stub and then call `main_mod.run_web_agent_turn`; the stub **never runs**, so the turn raises
during composition before reaching the harness. Two surface shapes, one failure:

```
E  AssertionError: {'schema_version': 1, 'status': 'failed',
     'summary': 'Agent runtime failed before returning a result.', 'run_id': None, …}
E  KeyError: 'config'          # the same thing, seen through the un-populated capture dict
```

The underlying exception is swallowed into the failed envelope and does not appear anywhere in the
captured log, so the cause cannot be named from this run.

### These 28 are not this plan's debt

The evidence is the D10 pre-batch control, **not** file non-overlap: the same 28 test ids were run
at `b46b8c815` (the commit before this plan's batch) in a clean temporary worktree with an identical
environment, all 28 failed there, and `comm -23` against this run's list is empty. Stating it that
way deliberately, because file non-overlap would be a **false** argument here —
`git diff --stat b46b8c815..HEAD` shows the plan did touch `lumen_api/main.py` (+7, Task 9's two
cache-composition lines), `lumen_agent/config.py` and `harness_web.py` (+1), which sit on group E's
call path. Group E fails identically at `b46b8c815`, where none of those lines existed, which is
what actually clears them.

## 6. How to run the focused gates

From `subsystems/clue-design`, with `R` = the repo root:

```
set -a; source R/.env; set +a          # the api tests need the DB DSN
BRANDFETCH_API_KEY="" \
LUMEN_CORE_HELPER=R/subsystems/clue-design/target/release/lumen-api-helper \
PYTHONPATH=.:apps/api:apps/agent_runtime R/.venv/bin/python -m pytest \
  apps/api/tests/test_logo_vendor.py \
  apps/api/tests/test_logo_family_cache.py \
  apps/api/tests/test_logo_ladder.py \
  apps/api/tests/test_ingestion_logo_family.py \
  apps/api/tests/test_logo_policy.py -v          # 105 passed

BRANDFETCH_API_KEY="" \
LUMEN_CORE_HELPER=R/subsystems/clue-design/target/release/lumen-api-helper \
PYTHONPATH=.:apps/api:apps/agent_runtime R/.venv/bin/python -m pytest \
  apps/agent_runtime/tests/test_fetch_logo_tool.py \
  apps/agent_runtime/tests/test_web_account_logo_bind.py \
  apps/agent_runtime/tests/test_prompts_logo_cells.py -v   # 47 passed
```

Two invocations, not one — see the `conftest` collision in §4. Both end with `N passed` and no
warnings summary.

The `BRANDFETCH_API_KEY=""` prefix is now belt-and-braces: the D9 autouse fixture in both
conftests blanks `settings.brandfetch_api_key`, and `fetch_vendor_family` reads it at call time, so
no test can reach the live vendor even with a real key in the environment (proven by running the
logo suites with the key live: green, no network). A test that *wants* the vendor path patches
`logo_fetch._vendor_rung` or passes `api_key=` itself.

Migration gates (2026-09-02): `alembic heads` → `1d09aba87206`, exactly one head. `make db-smoke`
(up → down to base → up) green, exit 0, **on a throwaway `clue_singapore_v1_smoke` database only** —
created and dropped in the same step, with the DSN override proven to take effect before the
downgrade ran. Never run it against the dev DB in `.env`: `downgrade base` would destroy this
workspace's data.

## 7. D11 resolved — the QA-render User-Agent override (founder decision 2026-09-02)

Later the same day the founder ruled: the two automated QA renderers present a normal Chrome
User-Agent so the review agent sees hotlinked logos as a visitor would. Shipped in `7f0b7ecd5`
behind **`LUMEN_QA_RENDER_UA_OVERRIDE`** (default ON; set `0` to restore the headless UA — the switch
to reach for if Brandfetch objects). Constant + helper: `apps/api/lumen_api/qa_render_ua.py`; applied
only at the thumbnail and clone-review `new_context` calls. Verified on the shipped code: flag on →
CDN 200 and the logo paints in both renderers; flag off → 302 `automated_traffic`. The vendor's
guidelines still say programmatic access "may result in rate limiting or blocking" and that
server-side use needs "a custom setup" — the founder accepted that risk knowingly; asking Brandfetch
for a sanctioned setup remains the clean long-term answer.

## 8. Task 16 — the ladder's Chrome-impersonating transport (founder decision 2026-09-02)

The ladder's plain httpx client was refused by Cloudflare walls at the TLS layer (openai.com: 403,
whatever the User-Agent). Shipped in `e3164d6e6`: the ladder's owned client is now
`lumen_ingestion/capture/impersonate.py::ImpersonatingClient` (curl_cffi `impersonate="chrome"`,
scrapling's engine, the same call the platform's Stage-0 scrapling adapter makes), behind
**`LUMEN_LADDER_IMPERSONATE_CHROME`** (default ON; `0` restores httpx). Everything above the wire is
unchanged (SSRF guard, redirect re-guard, size caps, every ladder rule); the brand-kit capture keeps
httpx. Measured: impersonation clears openai.com in 0.3s and fetches assets; the browser-based
`StealthyFetcher` costs 14–23s per page and still got 403 on g2.com, so no browser tier was built (D16).
Live on the real dispatch: openai.com flag on → `ok`, `light_lockup` + `light_mark` from the ladder;
flag off → `LUMI0503` 403. In that lane we no longer announce `lumen-ingestion/1` to scraped sites.

## 9. Task 17 — both sources propose, one arbiter picks (founder decision 2026-09-02)

The freshcontext.ai fetch exposed two rules that lost real assets: vendor-first let Brandfetch's
single, mislabelled asset (short "f(c)" form, dark art labelled for dark surfaces) hold `dark_lockup`
while the site's real on-dark SVG was discarded, and the ladder's header-first fold let the short form
beat the complete wordmark. Shipped in `9662fb285`: the ladder ALWAYS runs, both sources propose
candidates for every cell, and `lumen_ingestion/logo_arbiter.py::choose_cells` picks per cell —
measured ink for the surface first (dark cells must prove light ink; the vendor label is a hint),
then completeness, SVG over raster, size, vendor on ties. Unproven candidates rank below proven ones
and are never dropped. Winners carry `measured_verdict` + `arbitration.beat`. Plan §0.5 is superseded.
Live: freshcontext.ai → `wordmark.png` (light_lockup), `wordmark-ondark.svg` (dark_lockup),
apple-icon (light_mark); brandfetch.com → four proven vendor SVGs with the ladder 403-blocked.

## 10. Task 18 — alternatives beside the 2×2 (founder decision 2026-09-02)

The arbiter cannot know whether a vendor "logo" is complete (workspan.com's is the bare W) or whether a
short form fits a placement; the agent looking at the page can. Shipped in `8da597f58` + `7ef959d4c`:
the four cells stay the recommendation, and every other VETTED asset — arbitration losers from either
source and the vendor's `icon`/`other` types, never the ladder's raw ranked list — is registered like a
cell and listed under `alternatives` in both tools' payloads, each with `competed_for`, `measured_verdict`,
size/format and a one-line `reason`. Cached with the family; bindable. Prompts/docstrings: "use a cell
first; an alternative only when the cell does not fit the placement — say so." Live: workspan.com → 15
alternatives (the vendor's monochrome horizontal/stacked/square lockup variants in both inks — a real
dark-surface full lockup among them); freshcontext.ai → the two short forms. Not capped (founder: show all).

## 11. Session close (2026-09-02)

Final HEAD carries Tasks 1–18 plus the final-review fix. D11 is resolved (§7). Still open, outside this plan: the 28 baseline api failures
(§5; the image-model fixture's missing `image_model_api_style` pin is the cheapest of them).
Deferred items D12–D15 have named owners in the plan's ledger. Nothing pushed.

