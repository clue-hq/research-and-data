# Vendor-First Logo Family (Brandfetch + 2×2 contract) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make target-account logo fetching vendor-first (Brandfetch Brand API) with per-cell fallback to the in-house ladder, expose the result to both design deepagents as a 2×2 family (theme × completeness), cache each family durably per workspace+domain, and add a hotlink lane for decorative in-page logos.

**Architecture:** A new vendor rung (`lumen_ingestion/logo_vendor.py`) and a shared 2×2 vocabulary (`lumen_ingestion/logo_family.py`) sit beside the existing ladder; the two-rung dispatch lives in the lane-agnostic prep layer (`lumen_agent/tools/logo_fetch.py`) so both the scene and web `fetch_logo` tools inherit it with zero harness changes. A workspace-scoped durable cache (`design_logo_family` table + `DesignBlobStore` blobs) is injected into agent turns as a composed capability, following the `account_logo_binder` pattern exactly. The hotlink lane is prompt prose only.

**Tech Stack:** Python 3.12, httpx (the subsystem is deliberately httpx-only), pydantic-settings (`py_lumen_config`), selectolax, PIL/pymupdf (already present via the ladder), Alembic (root `alembic/`), pytest.

**Spec:** `_memory/2026-08-31-logo-vendor-first-decision.md` (the founder decision record) + `_memory/2026-09-02-logo-system-current-state.md` (the current-state map and this session's rulings). Both travel with this plan; executors read both. §0 below restates every binding ruling so no task depends on outside context.

## Execution status

Ledger: `.superpowers/sdd/2026-09-02-vendor-first-logo-family/progress.md`. Process: Opus-only implementers; all review/verification/decisions by the controller (founder ruling 2026-09-02).

- Task 1 — DONE (`0cf64d654`)
- Task 2 — DONE (`5a6e05d78`)
- Task 3 — DONE (`e8a5efe63`)
- Task 3b — DONE (`9387f9b7f`)
- Task 4 — DONE (`abe5d9d4f`, `417da50b4`) — live-verified
- Task 5 — DONE (`50908e087`)
- Task 6 — DONE (`08de3c8e2`, `ab6b477a4`)
- Task 7 — DONE (`16857940d`, `dcbcd4b63`; migration `1d09aba87206`)
- Task 8 — DONE (`753e1e9d7`) — ran before Task 7
- Task 9 — DONE (`8c3d0f3f7`)
- Task 10 — DONE (`7f301f62f`) — batch 4–10 live-verified end to end
- Task 11 — DONE (`aa8b943a3`, `6c3748fb6`) — D4 + D7 closed; see the task's status note
- Task 12 — DONE (`598ac2d64`)
- Task 13 — DONE (empirical; caveat sentence `79727edb6`; D11 opened)
- Task 14 — DONE (`193ba27e3`, `426a28a20`, `a3141df88`, `10e7c0479`, `4f48750ad`) — full suites: agent_runtime green; api = the 28 D10 baseline + 1 flaky sibling (passes on retry)
- Final whole-branch review — DONE; one finding fixed (`c1196ed8d`: vendor cells survive a blocked ladder backfill); D15 opened
- Task 15 — DONE (`7f0b7ecd5`) — founder decision 2026-09-02: QA-render User-Agent override behind `LUMEN_QA_RENDER_UA_OVERRIDE` (default on); D11 RESOLVED; in-situ verified on and off
- Task 16 — DONE (`e3164d6e6`) — founder decision 2026-09-02: the ladder fetches with a Chrome TLS fingerprint behind `LUMEN_LADDER_IMPERSONATE_CHROME` (default on); live-verified on openai.com; D16 opened
- Task 17 — DONE (`9662fb285`) — founder decision 2026-09-02: both sources propose, one arbiter picks per cell (supersedes §0.5 per-cell backfill); live-verified on freshcontext.ai + brandfetch.com
- Task 18 — DONE (`8da597f58`, `7ef959d4c`) — founder decision 2026-09-02: every other vetted asset is registered and listed as an `alternatives` entry beside the 2×2; live-verified on workspan.com (15) and freshcontext.ai (2)

## Deferred items ledger (founder rule 2026-09-02: every deferral lives HERE and belongs to a task)

| # | Surfaced in | Item | Owning task / resolution |
|---|---|---|---|
| D1 | Task 1 review | `apps/api/tests` emits one pre-existing `StarletteDeprecationWarning` (`fastapi/testclient.py` → "Using `httpx` with `starlette.testclient` is deprecated") from the shared conftest import — unrelated to this plan's code, but the test output is not pristine. | **Task 14, Step 2a**: add a targeted `filterwarnings` entry for exactly that message/module to the pytest config governing `apps/api/tests`; the focused gate must then run warning-free. |
| D2 | Task 1 review | `test_brandfetch_settings_load_from_env` does not assert `brandfetch_api_base_url` from env; the config comment's "W-logo" wave tag is a plan artifact. | **Task 3b** (carry-over, executed before Task 4). |
| D3 | Task 3 review | Rule 6 gates renderability for SVG only, so an undecodable vendor RASTER still fills its cell (caught later by `core.ingest_asset`, never placed — but the mapping's own promise is "a cell holds a file that paints"). | **Task 3b**: Pillow decode gate `_raster_decodes` for png/webp/jpeg cells, with a garbage-bytes test; existing test fixture bytes made real. |
| D4 | Pre-flight scan | Task 11's tests assert on module SOURCE text (`inspect.getsource`), not on a rendered prompt. | **Task 11**: mandatory additional test rendering the web author prompt through the suite's existing `prompt_of` fixture (see `apps/agent_runtime/tests/test_web_account_logo_bind.py`) and asserting the four cell names appear and the old slot phrasing does not. |
| D5 | Task 6 plan text | Pre-existing tool payload tests may be marked `xfail(strict=True)` transiently between Task 6 and Task 10. | **Task 10**: zero `xfail` marks may remain in `test_fetch_logo_tool.py` at completion (controller checks with grep). |
| D7 | Task 10 review | `apps/agent_runtime/knowledge_docs/knowledge/web/abm-page.md:57-58` — a knowledge doc the web agent reads — still says "`fetch_logo` returns one id per slot (`light`, `dark` …, `mark`, `wordmark`)". No plan task covered `knowledge_docs/`. | **Task 11**: rewrite those lines to the 2×2 cell vocabulary in the same voice as the prompt prose; `grep -rn "per slot" apps/agent_runtime/knowledge_docs` must be empty afterwards. |
| D8 | Controller live run after Task 10 | The engine's `AssetSource` enum (`crates/lumen-core/src/assets.rs`, `#[serde(tag = "kind")]`) has NO `vendor` variant; Task 6's `source_ref["kind"] = "vendor"` for Brandfetch cells made every real `ingest_asset` fail with `helper.asset_source` — invisible to the mocked tests, caught only by the controller's live tool run. | **Task 6 fix round 2 (executed immediately)**: vendor cells use the engine's existing `website` source kind with the asset's own URL; the vendor identity stays in `provenance` (`created_by`/`source_label` = `brandfetch`). No engine change (crates are out of scope). |
| D9 | Controller, batch close-out | Only `test_fetch_logo_tool.py` carries the autouse vendor-disabled fixture; any future test that builds a tool with a real `.env` key could reach Brandfetch. Today no other test calls `fetch_logo` (verified by grep), and the controller ran the full suites with `BRANDFETCH_API_KEY=""` exported. | **Task 14, Step 0**: add a suite-wide autouse fixture in `apps/agent_runtime/tests/conftest.py` AND `apps/api/tests/conftest.py` that monkeypatches `py_lumen_config.settings.brandfetch_api_key` to `""` (tests that want the vendor path patch `logo_fetch._vendor_rung` themselves, as today); then drop the file-local fixture in `test_fetch_logo_tool.py` or leave it as a redundant belt. |
| D10 (RESOLVED 2026-09-02) | Controller full-suite run after Task 10 | Both design suites fail en masse in THIS worktree for one environmental reason: `apps/editor/node_modules` (→ `tailwindcss/theme.css`), the vendored Tailwind runtime (`apps/editor/public/vendor/tailwind-browser.js`, untracked), and the release `lumen-api-helper` binary are absent, so every web-export/compile/publish path raises `WebExportCompileError: Cannot find module …/apps/editor/node_modules/…` (42×) or `repair.toolchain_unavailable`. Failing files: `test_web_campaign_shells`, `test_web_recreate_and_repair`, `test_web_retokenize`, `test_web_review_gate` (agent_runtime); `test_abm_batch_publish`, `test_web_export`, `test_web_fragment_*`, `test_custom_component_*`, `test_web_batches`, `test_api`, … (api). No logo-plan test file is among them; every logo file is green. | **Task 14, Step 0b**: prepare the worktree per `subsystems/clue-design/AGENTS.md` §5 BEFORE the full-suite gates — `cd apps/editor && npm install`, vendor `tailwind-browser.js` (copy from a sibling workspace or `node_modules/@tailwindcss/browser/dist/index.global.js`), `cargo build -p lumen-api-helper --release` — then re-run both suites and require the failing set to be EMPTY or provably pre-existing (same failures at the pre-batch commit `b46b8c815`). **Done by the controller 2026-09-02:** worktree prepared (Tailwind runtime vendored from a sibling workspace, `npm install` in `apps/editor`, release helper built); re-run → `apps/agent_runtime/tests` fully GREEN; `apps/api/tests` left 28 failing tests (custom-component compiler/publish/runtime, image-model w14/w17, asset-store serving, grammar audit, web-turn composition) and the SAME 28 fail at `b46b8c815` in a clean temporary worktree with the identical environment — zero regressions from this plan. Task 14 inherits those 28 as pre-existing environment/config failures to triage, not as this plan's debt. |
| D11 (RESOLVED 2026-09-02 → Task 15) | Task 13 empirical run | Brandfetch's Logo-API CDN refuses `HeadlessChrome` User-Agents (`x-bf-error: automated_traffic`, 302 — not a Referer check; a UA-only swap makes every headless context render). Our three production Playwright sites (`document_thumbnails.py:178`, `clone_review/browser.py:87`, `fragments/isolation.py:237`) launch headless with no UA override, so page thumbnails and the reviewer's render walk show hotlinked decorative logos as EMPTY (the human's editor preview and the published page render them). Consequences: (a) thumbnails of logo-wall pages look emptier than the page; (b) the review gate's rendered view could misread an empty logo wall as a defect. | **Task 14 close-out note records this as an OPEN FOUNDER DECISION** — options: accept (shipped; the prompt caveat says so), or set a non-headless `user_agent` on those Playwright contexts (one line each; it defeats a vendor guard that explicitly refuses automated traffic — a terms/compliance call, deliberately NOT taken by the controller). No code in this plan. **Evidence 2026-09-02 (controller, in situ):** injecting `user_agent=` into `Browser.new_context` and running the REAL `web_thumbnail_png` and `run_walk` flips the CDN from 302 `automated_traffic` to 200 `image/webp` on every context and the logo paints (nonwhite pixels 74→4761 thumbnail, 265→16557 walk) — the method works. Brandfetch's guidelines say programmatic access "may result in rate limiting or blocking", a client id does not exempt the automated-traffic check, and server-side use needs "a custom setup" by contacting them. |
| D12 | Task 14 gates | `apps/api/tests` and `apps/agent_runtime/tests` each hold a non-package `conftest.py`; one pytest process over both mis-resolves `from conftest import make_blob_store` (6 errors). Pre-existing (reproduced at `79727edb6`), so this plan's Step 2 single-command gate is an erratum — the gate is TWO invocations (as `subsystems/clue-design/AGENTS.md` §3 prescribes). | **Owner: the next design-suite hygiene pass** (outside this plan's file list): make the two test dirs packages or set `--import-mode=importlib`. |
| D13 | Task 14 close-out | A Brandfetch 429 degrades honestly (`VendorLookupFailed(code="quota")` → outcome/tool `vendor_notes`, ladder takes over every cell) but nothing ALERTS: a workspace could run ladder-only for a month unnoticed. Free-tier ceiling observed `x-api-key-quota: 100`. | **Owner: the design observability pass** — emit one metric/log line at the `quota` degrade site in `logo_fetch.fetch_logo_family`; no code in this plan. |
| D14 | Task 14 close-out | Batch-time slot selection (which cell a derived page places: light vs dark surface, lockup vs mark) is not built; it must read `lumen_ingestion.logo_family.CELL_NAMES`, never re-spell the four names. | **Owner: the ABM batch/personalization task that adds per-page cell choice**; recorded here so the vocabulary stays single-sourced. |
| D15 | Final review fix (`c1196ed8d`) | A vendor-partial family whose ladder backfill hit a TRANSIENT block (rate limit, brief 5xx) is cached with its empty cells and stays that way until `force_refresh=True` — a consequence of decision #4 (no TTL) meeting the new per-cell degrade. | **Owner: whoever revisits decision #4** — if a TTL or a "degraded entry" marker is ever added to `design_logo_family`, retry the ladder for cells whose note says `ladder backfill unavailable`. No code in this plan. |
| D16 | Task 16 measurement | No browser-based stealth tier for the ladder: scrapling's `StealthyFetcher` costs 14–23s per page (more than a chat turn can spend) and still got a 403 on the one hard-blocked site tried (g2.com); Chrome TLS impersonation (0.3s) cleared the Cloudflare wall on openai.com. Hard-blocked sites therefore still come back `LUMI0503` from the ladder (Brandfetch remains the first rung for them). | **Owner: whoever next sees a real target lost to a hard block** — revisit as an on-block-only tier (`StealthyFetcher` page + assets through its browser context), never as the default transport. |
| D6 | Task 4 plan text | Asset downloads bypass `capture.net`'s SSRF re-guard on the reasoning that Brandfetch's asset CDN is a fixed domain — but the driver never enforced that. | **Task 4**: `_ASSET_HOST_SUFFIXES = ("brandfetch.io",)`; a `formats[].src` whose host is not under an allowed suffix is never fetched and is reported in the driver's notes; pinned by a MockTransport test that asserts no request reaches a foreign host. |

## Global Constraints

- **Never push; local commits only; no AI attribution in commit messages** (no `Co-Authored-By: Claude`, no "Generated with" footers) — repo rule.
- **Env-flag parity rule:** every new env var lands in BOTH `.env.example` (repo root) AND `subsystems/clue-design/.env.example`, with defaults, **in the same commit that introduces the code reading it**.
- **Alembic:** hash revision ids only (`alembic revision -m "..."` from the repo root assigns one — never hand-pick); hand-written reversible `upgrade()`/`downgrade()`; named constraints; exactly one head afterward (`alembic heads`); gate with `make db-smoke` on a clean throwaway DB.
- **Workspace scoping (the B3 law):** anything durable is keyed by `workspace_id` and fail-closed across tenants. No cross-workspace cache reads, ever.
- **The never-synthesize register:** an empty cell is a CORRECT answer. Nothing in this plan invents, recolors, letters, or approximates a logo. `needs_review` stays fail-closed.
- **Design test invocation:** from `subsystems/clue-design/`, `PYTHONPATH=.:apps/api:apps/agent_runtime <repo-root>/.venv/bin/python -m pytest <file> -v`. Run ONLY the focused test files named per task inline (the full design suite takes >1h — never run it synchronously; one background full run at the very end).
- **Do not touch:** ladder internals (`logo_ladder.py` stage 1/2 logic), the brand-kit ingestion path (`capture/evidence_builder.py::_ladder_logos` — seller kits keep using the ladder directly; vendor-first was ruled for TARGET logos), `bind_account_logo` mechanics beyond the provenance-gate widening in Task 8, the recorded scene/web asymmetries.
- The subsystem CLAUDE.md engine-handshake rule does not apply (no `crates/` sources change in this plan).

---

## §0 Design contract (founder rulings, restated so the plan is self-contained)

1. **Vendor-first, ladder-second.** Brandfetch **Brand API** (`GET https://api.brandfetch.io/v2/brands/domain/{domain}`, Bearer key, **free tier**) is rung one; the in-house ladder is rung two. A plain two-rung fallback, not a waterfall framework. Missing key, quota exhaustion (HTTP 429), timeout, 5xx, or vendor miss all degrade honestly to the ladder with a typed note — never a hard failure. (The Logo API CDN is hotlink-only and forbids programmatic access — it is used ONLY for the hotlink lane, §0.7.)
2. **The 2×2 is the tool contract.** Four cells: `light_lockup`, `dark_lockup`, `light_mark`, `dark_mark`. Theme uses OUR semantics — *the background the asset is for* (`light` = for light backgrounds = dark-colored art). "Lockup" = the full horizontal logo (a wordmark-only brand still fills the lockup cell, annotated via `lockup_completeness`). "Mark" = the bare symbol. One `fetch_logo` call returns the whole family; the agent reasons about placement.
3. **Brandfetch theme semantics are INVERTED vs ours and the adapter hides that.** Brandfetch labels the asset's own appearance: their `theme: "dark"` = dark-colored logo (for light backgrounds) → our `light_*` cells; their `theme: "light"` → our `dark_*` cells. The inversion lives in exactly one function and is pinned by tests.
4. **`type=icon` never fills anything** (founder ruling): only `type=logo` → lockup cells and `type=symbol` → mark cells. `type=other` and `photographic`-tagged assets are skipped.
5. **Per-cell fallback** (founder ruling): the vendor fills what it can; the ladder runs once only if cells remain empty and backfills only those. Mixed-provenance families are fine; every cell stamps its `source`. **[SUPERSEDED 2026-09-02 by Task 17 — founder ruling after the freshcontext.ai case: BOTH sources propose candidates for every cell (the ladder always runs) and `lumen_ingestion/logo_arbiter.py::choose_cells` picks one per cell — measured ink for the surface first (a dark cell must PROVE light ink; the vendor's theme label is a hint, never proof), then completeness, SVG over raster, pixel size, and the vendor on exact ties. Unproven candidates only rank below proven ones and are never dropped; every chosen cell records what it beat. Mixed-provenance families and per-cell `source` stamping are unchanged.]**
6. **Cache:** first successful fetch stores the family durably, keyed `(workspace_id, registrable_domain)` — domain, not account id, because the tool receives a domain and the agent may fetch for non-account companies (partners); workspace-scoped per B3. No TTL expiry; the eviction affordance is `force_refresh=True` on the tool (per the accepted advisory note: "the user saw it's wrong" must have an action attached).
7. **Hotlink lane:** decorative third-party logos inside generated web pages (logo walls, integration strips) use Logo API CDN URLs written directly into markup — free, uncached, compliant because end-viewer browsers fetch them. Boundary: **named target being personalized → `fetch_logo` (custody path); ambient third-party logos → hotlink.** Never a hotlink for `{{account.logo}}`.
8. **No fetch/bind at account discovery or enrichment.** Design-time, on-demand, either lane, any company.
9. **No gates, no verification cards, no prompt bureaucracy** beyond the routing prose. The human looking at the design is the verification layer. (One hygiene exception ruled in during planning: vendor SVG bytes are checked with the existing `svg_is_renderable` before ingest — new-scope hygiene on the new path, not a change to recorded ladder asymmetries.)
10. **Vendor-fetched assets must be bindable.** `bind_account_logo` currently gates on provenance `created_by == "logo_ladder"`; it widens to accept `"brandfetch"` too (Task 8). Generated images and placeholders stay refused.

### File map (what exists, what is created, what changes)

| File | Action | Responsibility |
|---|---|---|
| `subsystems/clue-design/packages/py-lumen-config/py_lumen_config/config.py` | Modify | 4 new settings fields (Task 1) |
| `.env.example` + `subsystems/clue-design/.env.example` | Modify | new env lines (Task 1) |
| `subsystems/clue-design/apps/api/lumen_ingestion/logo_family.py` | **Create** | the 2×2 vocabulary + `FamilyCell`/`LogoFamily` dataclasses (Task 2) |
| `subsystems/clue-design/apps/api/lumen_ingestion/logo_vendor.py` | **Create** | Brandfetch client: typed errors, pure payload parsing, cell mapping w/ inversion, network driver (Tasks 2–4) |
| `subsystems/clue-design/apps/agent_runtime/lumen_agent/tools/logo_fetch.py` | Modify | ladder→cell mapping, two-rung dispatch, new outcome shape (Tasks 5–6) |
| `alembic/versions/<hash>_design_logo_family_cache.py` | **Create** | cache table migration (Task 7) |
| `subsystems/clue-design/apps/api/lumen_api/agent_logo_family_cache.py` | **Create** | `DurableLogoFamilyCache` capability (Task 7) |
| `subsystems/clue-design/apps/api/lumen_api/agent_account_logos.py` | Modify | provenance-gate widening (Task 8) |
| `subsystems/clue-design/apps/agent_runtime/lumen_agent/config.py` | Modify | `logo_family_cache` + `brandfetch_client_id` config fields (Task 9) |
| `subsystems/clue-design/apps/api/lumen_api/main.py` | Modify | compose the cache at both turn seams (Task 9) |
| `subsystems/clue-design/apps/agent_runtime/lumen_agent/tools/substrate.py` | Modify | scene `fetch_logo`: cache + cells payload + docstring (Task 10) |
| `subsystems/clue-design/apps/agent_runtime/lumen_agent/tools/web_substrate.py` | Modify | web `fetch_logo`: cache + cells payload + docstring; `bind_account_logo` error text (Tasks 8, 10) |
| `subsystems/clue-design/apps/agent_runtime/lumen_agent/prompts.py` / `prompts_web.py` | Modify | 2×2 vocabulary + hotlink lane prose (Tasks 11–12) |
| Tests | **Create/Modify** | named per task |

Import direction sanity: `lumen_agent.tools.logo_fetch` already imports `lumen_ingestion.logo_ladder` (cross-app import is the established seam; `PYTHONPATH` carries `apps/api`), so it may import `logo_vendor` and `logo_family` the same way. `lumen_api` already imports `lumen_ingestion` (`agent_account_logos.py` does). Nothing in `lumen_ingestion` imports upward.

---

### Task 1: Brandfetch settings + env parity

**Status: DONE 2026-09-02 — commit `0cf64d654`; controller first-hand review clean; local `.env` parity restored by controller.**

**Files:**
- Modify: `subsystems/clue-design/packages/py-lumen-config/py_lumen_config/config.py` (add fields beside the `pdl_*` block at ~line 232)
- Modify: `.env.example` (repo root; beside the PDL block at ~line 369)
- Modify: `subsystems/clue-design/.env.example` (beside its PDL block at ~line 76)
- Test: `subsystems/clue-design/apps/api/tests/test_logo_vendor.py` (new file, first test)

**Interfaces:**
- Consumes: nothing.
- Produces: `settings.brandfetch_api_key: str` (default `""`), `settings.brandfetch_client_id: str` (default `""`), `settings.brandfetch_api_base_url: str` (default `"https://api.brandfetch.io"`), `settings.brandfetch_timeout_s: float` (default `20.0`). Later tasks read all four.

- [x] **Step 1: Write the failing test**

```python
# subsystems/clue-design/apps/api/tests/test_logo_vendor.py
"""Brandfetch vendor rung: settings, parsing, cell mapping, network driver."""

from __future__ import annotations


def test_brandfetch_settings_fields_exist_with_safe_defaults(monkeypatch):
    # Fresh Settings instance so developer .env values don't leak into assertions.
    from py_lumen_config.config import Settings

    for var in (
        "BRANDFETCH_API_KEY",
        "BRANDFETCH_CLIENT_ID",
        "BRANDFETCH_API_BASE_URL",
        "BRANDFETCH_TIMEOUT_S",
    ):
        monkeypatch.delenv(var, raising=False)
    fresh = Settings(_env_file=None)
    assert fresh.brandfetch_api_key == ""
    assert fresh.brandfetch_client_id == ""
    assert fresh.brandfetch_api_base_url == "https://api.brandfetch.io"
    assert fresh.brandfetch_timeout_s == 20.0


def test_brandfetch_settings_load_from_env(monkeypatch):
    from py_lumen_config.config import Settings

    monkeypatch.setenv("BRANDFETCH_API_KEY", "bf_test_key")
    monkeypatch.setenv("BRANDFETCH_CLIENT_ID", "idTESTCLIENT")
    monkeypatch.setenv("BRANDFETCH_TIMEOUT_S", "5.5")
    fresh = Settings(_env_file=None)
    assert fresh.brandfetch_api_key == "bf_test_key"
    assert fresh.brandfetch_client_id == "idTESTCLIENT"
    assert fresh.brandfetch_timeout_s == 5.5
```

- [x] **Step 2: Run test to verify it fails**

From `subsystems/clue-design/`:
`PYTHONPATH=.:apps/api:apps/agent_runtime <repo-root>/.venv/bin/python -m pytest apps/api/tests/test_logo_vendor.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'brandfetch_api_key'`.
(If the import of `Settings` itself fails, check how `apps/api/tests/test_ad_company_identity.py` — the PDL settings tests — constructs it and mirror that exactly.)

- [x] **Step 3: Add the settings fields**

In `config.py`, directly below the `pdl_timeout_s` field (~line 237), following the PDL block's comment style:

```python
    # -- Brandfetch (target-account logo vendor; W-logo vendor-first, 2026-09-02) --------
    # Brand API key (Bearer). Blank = vendor rung disabled: `fetch_logo` degrades honestly
    # to the in-house ladder, exactly like a blank PDL_API_KEY degrades ad identity.
    brandfetch_api_key: str = ""
    # Logo API *client id* (PUBLIC — appears in published-page <img> URLs). Powers the
    # hotlink lane only; blank = the hotlink prompt guidance is omitted.
    brandfetch_client_id: str = ""
    brandfetch_api_base_url: str = "https://api.brandfetch.io"
    brandfetch_timeout_s: float = 20.0
```

- [x] **Step 4: Add the env lines (BOTH files, same commit — parity rule)**

Repo-root `.env.example`, after the PDL block (~line 375):

```bash
# Brandfetch — target-account logo vendor (design subsystem). BRANDFETCH_API_KEY is the
# Brand API Bearer key (free tier: 100 requests; blank = fetch_logo uses the in-house
# ladder only). BRANDFETCH_CLIENT_ID is the PUBLIC Logo-API client id embedded in
# published-page <img> URLs for decorative third-party logos (blank = hotlink guidance
# omitted from web prompts). Both from https://developers.brandfetch.com/register.
BRANDFETCH_API_KEY=
BRANDFETCH_CLIENT_ID=
BRANDFETCH_API_BASE_URL=https://api.brandfetch.io
BRANDFETCH_TIMEOUT_S=20
```

`subsystems/clue-design/.env.example`, after its PDL block (~line 80): the same four lines with the same comment.

- [x] **Step 5: Run test to verify it passes**

Same command as Step 2. Expected: both tests PASS.

- [x] **Step 6: Commit**

```bash
git add subsystems/clue-design/packages/py-lumen-config/py_lumen_config/config.py .env.example subsystems/clue-design/.env.example subsystems/clue-design/apps/api/tests/test_logo_vendor.py
git commit -m "feat(logo): Brandfetch settings — api key, public client id, base url, timeout

Env parity: both .env.example files carry the four lines at introduction.
Blank key = vendor rung disabled, honest degrade to the ladder (PDL pattern)."
```

---

### Task 2: The 2×2 vocabulary (`logo_family.py`) + vendor payload parsing (pure half)

**Status: DONE 2026-09-02 — commit `5a6e05d78`; controller first-hand review clean.**

**Files:**
- Create: `subsystems/clue-design/apps/api/lumen_ingestion/logo_family.py`
- Create: `subsystems/clue-design/apps/api/lumen_ingestion/logo_vendor.py`
- Test: `subsystems/clue-design/apps/api/tests/test_logo_vendor.py` (extend)

**Interfaces:**
- Consumes: nothing from earlier tasks (settings are used first in Task 4).
- Produces:
  - `logo_family.CELL_NAMES: tuple[str, ...] = ("light_lockup", "dark_lockup", "light_mark", "dark_mark")`
  - `logo_family.cell_name(theme: str, completeness: str) -> str` (`("light","lockup") -> "light_lockup"`; raises `ValueError` on unknown axis values)
  - `logo_family.FamilyCell` dataclass: `cell: str`, `body: bytes`, `content_type: str`, `source: str` (`"brandfetch" | "ladder" | "ladder-materialized"`), `origin_url: str`, `evidence: dict`
  - `logo_vendor.VENDOR_NAME = "brandfetch"`
  - `logo_vendor.VendorCredentialsMissing(Exception)` with `.env_vars: tuple[str, ...]`
  - `logo_vendor.VendorLookupFailed(Exception)` with `.code: str` (`"quota" | "timeout" | "http" | "malformed"`) and `.message: str`
  - `logo_vendor.VendorAsset` dataclass: `theme: str | None`, `type: str`, `tags: list[str]`, `formats: list[dict]`
  - `logo_vendor.parse_brand_payload(payload: dict) -> list[VendorAsset]`
  - `logo_vendor.pick_format(asset: VendorAsset) -> dict | None` (svg first; else largest transparent raster; else largest raster; `None` when `formats` is empty)

- [x] **Step 1: Write the failing tests**

Append to `test_logo_vendor.py`:

```python
# A trimmed real-shaped Brand API response (the schema's logos[] shape:
# theme dark|light|null, type icon|logo|symbol|other, formats[] with
# src/format/width/height/size/background).
BRAND_PAYLOAD = {
    "name": "Acme",
    "domain": "acme.com",
    "logos": [
        {  # their theme "dark" = dark-colored art FOR LIGHT backgrounds
            "theme": "dark",
            "type": "logo",
            "tags": [],
            "formats": [
                {"src": "https://asset.brandfetch.io/a/lockup-dark.svg", "format": "svg",
                 "width": 400, "height": 80, "size": 4000, "background": "transparent"},
                {"src": "https://asset.brandfetch.io/a/lockup-dark.png", "format": "png",
                 "width": 800, "height": 160, "size": 20000, "background": "transparent"},
            ],
        },
        {
            "theme": "light",
            "type": "symbol",
            "tags": [],
            "formats": [
                {"src": "https://asset.brandfetch.io/a/symbol-light.png", "format": "png",
                 "width": 300, "height": 300, "size": 9000, "background": "transparent"},
            ],
        },
        {  # icon must be ignored entirely (founder ruling i)
            "theme": "dark",
            "type": "icon",
            "tags": [],
            "formats": [
                {"src": "https://asset.brandfetch.io/a/icon.png", "format": "png",
                 "width": 128, "height": 128, "size": 3000, "background": None},
            ],
        },
        {  # photographic assets are never logos
            "theme": None,
            "type": "logo",
            "tags": ["photographic"],
            "formats": [
                {"src": "https://asset.brandfetch.io/a/photo.jpeg", "format": "jpeg",
                 "width": 900, "height": 600, "size": 90000, "background": None},
            ],
        },
    ],
}


def test_cell_name_builds_the_four_cells_and_rejects_junk():
    from lumen_ingestion.logo_family import CELL_NAMES, cell_name

    assert CELL_NAMES == ("light_lockup", "dark_lockup", "light_mark", "dark_mark")
    assert cell_name("light", "lockup") == "light_lockup"
    assert cell_name("dark", "mark") == "dark_mark"
    import pytest as _pytest
    with _pytest.raises(ValueError):
        cell_name("adaptive", "lockup")
    with _pytest.raises(ValueError):
        cell_name("light", "wordmark")


def test_parse_brand_payload_keeps_vendor_vocabulary_and_drops_nothing():
    from lumen_ingestion.logo_vendor import parse_brand_payload

    assets = parse_brand_payload(BRAND_PAYLOAD)
    # Parsing is faithful: all four entries survive; filtering is mapping's job.
    assert [a.type for a in assets] == ["logo", "symbol", "icon", "logo"]
    assert assets[0].theme == "dark"
    assert assets[3].tags == ["photographic"]
    assert assets[0].formats[0]["format"] == "svg"


def test_parse_brand_payload_tolerates_malformed_entries():
    from lumen_ingestion.logo_vendor import parse_brand_payload

    assert parse_brand_payload({}) == []
    assert parse_brand_payload({"logos": "nope"}) == []
    assets = parse_brand_payload({"logos": [{"type": "logo"}, 42, {"formats": []}]})
    # Entries missing fields normalize (theme None, tags [], formats []); non-dicts drop.
    assert len(assets) == 2 and assets[0].type == "logo"


def test_pick_format_prefers_svg_then_largest_transparent_raster():
    from lumen_ingestion.logo_vendor import parse_brand_payload, pick_format

    assets = parse_brand_payload(BRAND_PAYLOAD)
    assert pick_format(assets[0])["format"] == "svg"
    assert pick_format(assets[1])["src"].endswith("symbol-light.png")

    from lumen_ingestion.logo_vendor import VendorAsset
    raster_only = VendorAsset(theme=None, type="logo", tags=[], formats=[
        {"src": "s", "format": "png", "width": 100, "height": 20, "size": 1,
         "background": None},
        {"src": "b", "format": "webp", "width": 600, "height": 120, "size": 2,
         "background": "transparent"},
    ])
    assert pick_format(raster_only)["src"] == "b"
    assert pick_format(VendorAsset(theme=None, type="logo", tags=[], formats=[])) is None
```

- [x] **Step 2: Run tests to verify they fail**

`PYTHONPATH=.:apps/api:apps/agent_runtime <repo-root>/.venv/bin/python -m pytest apps/api/tests/test_logo_vendor.py -v`
Expected: the four new tests FAIL with `ModuleNotFoundError: lumen_ingestion.logo_family` / `logo_vendor`.

- [x] **Step 3: Write `logo_family.py`**

```python
# subsystems/clue-design/apps/api/lumen_ingestion/logo_family.py
"""The 2x2 logo-family vocabulary shared by the vendor rung, the ladder mapping,
the dispatch, and the cache (founder ruling 2026-09-02).

Two axes, four cells. THEME uses OUR semantics -- the background the asset is
FOR: `light` means "place on light backgrounds" (dark-colored art), `dark`
means "place on dark backgrounds" (light/white art). COMPLETENESS is `lockup`
(the full horizontal logo; a wordmark-only brand still fills this cell) or
`mark` (the bare symbol). This is deliberately the same 2x2 the deferred
batch-time slot-selection rule will consume.
"""

from __future__ import annotations

from dataclasses import dataclass, field

THEMES = ("light", "dark")
COMPLETENESS = ("lockup", "mark")
CELL_NAMES = ("light_lockup", "dark_lockup", "light_mark", "dark_mark")

#: `FamilyCell.source` values. "ladder-materialized" is the ladder's
#: observed-ink currentColor export (never synthesis -- see logo_ladder).
SOURCE_BRANDFETCH = "brandfetch"
SOURCE_LADDER = "ladder"
SOURCE_LADDER_MATERIALIZED = "ladder-materialized"


def cell_name(theme: str, completeness: str) -> str:
    """`("light", "lockup") -> "light_lockup"`. Refuses unknown axis values loudly."""
    if theme not in THEMES:
        raise ValueError(f"unknown theme {theme!r} (expected one of {THEMES})")
    if completeness not in COMPLETENESS:
        raise ValueError(
            f"unknown completeness {completeness!r} (expected one of {COMPLETENESS})"
        )
    return f"{theme}_{completeness}"


@dataclass
class FamilyCell:
    """One resolved cell of the 2x2: real bytes plus where they came from."""

    cell: str
    body: bytes
    content_type: str
    source: str  # SOURCE_BRANDFETCH | SOURCE_LADDER | SOURCE_LADDER_MATERIALIZED
    origin_url: str
    evidence: dict = field(default_factory=dict)
```

- [x] **Step 4: Write `logo_vendor.py` (pure half only)**

```python
# subsystems/clue-design/apps/api/lumen_ingestion/logo_vendor.py
"""The Brandfetch rung of the two-rung logo supply chain (vendor-first,
founder decision 2026-08-31; rulings 2026-09-02).

**This module is the only place in the repository that knows Brandfetch's
Brand API exists** -- the shape `ad_library/pdl.py` established for PDL.
Everything else consumes cells of the shared 2x2 (`logo_family`).

The endpoint contract, per the vendor's documented Brand API schema:

    GET {base}/v2/brands/domain/{domain}
    Authorization: Bearer <key>
    -> 200 {"logos": [{"theme": "dark"|"light"|null,
                        "type": "icon"|"logo"|"symbol"|"other",
                        "tags": [...],
                        "formats": [{"src", "format", "width", "height",
                                     "size", "background"}]}], ...}
    -> 404  # unknown brand -- an ANSWER (empty family), not a fault
    -> 429  # free-tier quota out -- a typed degrade, the ladder takes over

**Theme semantics are INVERTED here and nowhere else.** Brandfetch labels the
asset's own appearance (their "dark" = dark-colored art, which belongs on
LIGHT backgrounds); our cells name the background the asset is FOR. The
`_OUR_THEME_FOR_VENDOR_THEME` table is the entire inversion, and the tests pin
it, because shipping this backwards swaps every light/dark pairing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

JsonObject = dict[str, Any]

VENDOR_NAME = "brandfetch"

#: their theme -> our theme. See the module docstring; do not "simplify" this.
_OUR_THEME_FOR_VENDOR_THEME = {"dark": "light", "light": "dark"}

#: vendor `type` -> our completeness axis. `icon` is DELIBERATELY absent
#: (founder ruling 2026-09-02: the social-avatar icon never fills a cell), and
#: so is `other`.
_COMPLETENESS_FOR_VENDOR_TYPE = {"logo": "lockup", "symbol": "mark"}

_FORMAT_MIME = {
    "svg": "image/svg+xml",
    "png": "image/png",
    "webp": "image/webp",
    "jpeg": "image/jpeg",
}


class VendorCredentialsMissing(Exception):
    """No BRANDFETCH_API_KEY configured. The dispatch treats this as
    "vendor rung disabled" and runs the ladder -- a degrade, not a failure."""

    def __init__(self, env_vars: tuple[str, ...] = ("BRANDFETCH_API_KEY",)) -> None:
        self.env_vars = env_vars
        super().__init__(f"missing credentials: {', '.join(env_vars)}")


class VendorLookupFailed(Exception):
    """The vendor was asked and could not answer (quota/timeout/http/malformed).
    Distinct from a 404, which IS an answer (empty family)."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code  # "quota" | "timeout" | "http" | "malformed"
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass
class VendorAsset:
    """One entry of the Brand API `logos[]` array, vendor vocabulary intact.
    Parsing is faithful; filtering (icon/other/photographic) is mapping's job."""

    theme: str | None
    type: str
    tags: list[str] = field(default_factory=list)
    formats: list[JsonObject] = field(default_factory=list)


def parse_brand_payload(payload: JsonObject) -> list[VendorAsset]:
    """Normalize the Brand API response into typed assets. Non-dict entries
    drop; missing fields normalize to empty -- a malformed entry must never
    take the whole family down."""
    logos = payload.get("logos") if isinstance(payload, dict) else None
    if not isinstance(logos, list):
        return []
    out: list[VendorAsset] = []
    for entry in logos:
        if not isinstance(entry, dict):
            continue
        theme = entry.get("theme")
        out.append(
            VendorAsset(
                theme=theme if theme in ("dark", "light") else None,
                type=str(entry.get("type") or ""),
                tags=[str(t) for t in entry.get("tags") or [] if isinstance(t, str)],
                formats=[f for f in entry.get("formats") or [] if isinstance(f, dict)],
            )
        )
    return out


def pick_format(asset: VendorAsset) -> JsonObject | None:
    """SVG first (logos are vector art); else the largest transparent raster;
    else the largest raster. None when the asset ships no formats."""
    svgs = [f for f in asset.formats if f.get("format") == "svg" and f.get("src")]
    if svgs:
        return svgs[0]

    def area(f: JsonObject) -> int:
        return int(f.get("width") or 0) * int(f.get("height") or 0)

    rasters = [
        f for f in asset.formats
        if f.get("src") and f.get("format") in ("png", "webp", "jpeg")
    ]
    transparent = [f for f in rasters if f.get("background") == "transparent"]
    pool = transparent or rasters
    return max(pool, key=area) if pool else None
```

- [x] **Step 5: Run tests to verify they pass**

Same command. Expected: all Task 1 + Task 2 tests PASS.

- [x] **Step 6: Commit**

```bash
git add subsystems/clue-design/apps/api/lumen_ingestion/logo_family.py subsystems/clue-design/apps/api/lumen_ingestion/logo_vendor.py subsystems/clue-design/apps/api/tests/test_logo_vendor.py
git commit -m "feat(logo): 2x2 family vocabulary + Brandfetch payload parsing (pure half)

CELL_NAMES light/dark x lockup/mark; faithful vendor parsing; svg-first
format pick. Theme inversion table declared (mapping lands next)."
```

---

### Task 3: Vendor asset → cell mapping (the inversion, the filters, the renderability gate)

**Status: DONE 2026-09-02 — commit `e8a5efe63`; controller first-hand review clean (raster null-theme path probed through Pillow both directions). Deferred item D3 (undecodable rasters) is owned by Task 3b below.**

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/logo_vendor.py`
- Test: `subsystems/clue-design/apps/api/tests/test_logo_vendor.py` (extend)

**Interfaces:**
- Consumes: `parse_brand_payload`, `pick_format`, `logo_family.FamilyCell`, `logo_family.cell_name`; the ladder's `analyze_appearance` and `svg_is_renderable` (existing, `lumen_ingestion.logo_ladder`).
- Produces: `logo_vendor.map_vendor_assets_to_cells(assets: list[VendorAsset], download: Callable[[str], tuple[bytes, str | None] | None]) -> tuple[dict[str, FamilyCell], list[str]]` — `(cells, notes)`. `download(src_url)` returns `(bytes, content_type)` or `None` on failure; injected so the mapping stays transport-free and testable.

Mapping rules (all pinned by tests):
1. `type` not in `{logo, symbol}` → skipped. `photographic` tag → skipped with a note.
2. Theme inversion: vendor `dark` → our `light`, vendor `light` → our `dark`.
3. `theme=None` → download first, then classify with the ladder's `analyze_appearance` over a minimal `LadderCandidate(fmt=..., body=...)`: verdict `light_variant` → our `light`, `dark_variant` → our `dark`, `adaptive` → our `light` (the ladder's own convention: one adaptive file serves both, filed under light, noted), anything else → our `light` with a note (a lockup with no theme signal is still the primary; empty would be less honest than light-by-default **only for vendor-attributed assets** — the vendor already answered identity, unlike the ladder's unknowns).
4. First asset wins per cell (vendor order is preference order); later duplicates noted, not fetched.
5. A failed download → note, cell stays empty (the ladder may backfill later).
6. SVG bytes failing `svg_is_renderable` → note, cell stays empty. Raster `content_type` falls back from the format's `format` field via `_FORMAT_MIME`.

- [x] **Step 1: Write the failing tests**

```python
def _mini_svg(fill: str = "#111111") -> bytes:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="40" '
        f'viewBox="0 0 120 40"><rect width="120" height="40" fill="{fill}"/></svg>'
    ).encode()


def test_map_vendor_assets_inverts_theme_and_skips_icon_and_photographic():
    from lumen_ingestion.logo_vendor import map_vendor_assets_to_cells, parse_brand_payload

    fetched = {
        "https://asset.brandfetch.io/a/lockup-dark.svg": (_mini_svg("#101820"), "image/svg+xml"),
        "https://asset.brandfetch.io/a/symbol-light.png": (b"\x89PNGfakebytes", "image/png"),
    }
    cells, notes = map_vendor_assets_to_cells(
        parse_brand_payload(BRAND_PAYLOAD), download=lambda url: fetched.get(url)
    )
    # vendor theme=dark logo -> OUR light_lockup; vendor theme=light symbol -> OUR dark_mark
    assert set(cells) == {"light_lockup", "dark_mark"}
    assert cells["light_lockup"].source == "brandfetch"
    assert cells["light_lockup"].content_type == "image/svg+xml"
    assert cells["dark_mark"].origin_url.endswith("symbol-light.png")
    # icon and photographic never became cells; photographic skip is said out loud
    assert any("photographic" in n for n in notes)


def test_map_vendor_assets_null_theme_is_classified_from_the_bytes():
    from lumen_ingestion.logo_vendor import VendorAsset, map_vendor_assets_to_cells

    dark_ink = VendorAsset(theme=None, type="logo", tags=[], formats=[
        {"src": "u1", "format": "svg", "width": 120, "height": 40, "size": 1,
         "background": "transparent"},
    ])
    cells, _ = map_vendor_assets_to_cells(
        [dark_ink], download=lambda url: (_mini_svg("#101820"), "image/svg+xml")
    )
    # near-black ink -> light_variant verdict -> made for LIGHT backgrounds
    assert list(cells) == ["light_lockup"]
    assert "classified" in cells["light_lockup"].evidence.get("theme_basis", "")


def test_map_vendor_assets_refuses_unrenderable_svg_and_failed_downloads():
    from lumen_ingestion.logo_vendor import VendorAsset, map_vendor_assets_to_cells

    sprite = b'<svg xmlns="http://www.w3.org/2000/svg"><use href="s.svg#x"/></svg>'
    assets = [
        VendorAsset(theme="dark", type="logo", tags=[], formats=[
            {"src": "sprite", "format": "svg", "width": 0, "height": 0, "size": 1,
             "background": None}]),
        VendorAsset(theme="dark", type="symbol", tags=[], formats=[
            {"src": "gone", "format": "png", "width": 300, "height": 300, "size": 1,
             "background": None}]),
    ]
    fetched = {"sprite": (sprite, "image/svg+xml"), "gone": None}
    cells, notes = map_vendor_assets_to_cells(
        assets, download=lambda url: fetched.get(url)
    )
    assert cells == {}
    assert any("cannot paint" in n or "renderable" in n for n in notes)
    assert any("download failed" in n for n in notes)


def test_map_vendor_assets_first_asset_wins_per_cell():
    from lumen_ingestion.logo_vendor import VendorAsset, map_vendor_assets_to_cells

    first = VendorAsset(theme="dark", type="logo", tags=[], formats=[
        {"src": "one", "format": "svg", "width": 120, "height": 40, "size": 1,
         "background": None}])
    second = VendorAsset(theme="dark", type="logo", tags=[], formats=[
        {"src": "two", "format": "svg", "width": 120, "height": 40, "size": 1,
         "background": None}])
    cells, _ = map_vendor_assets_to_cells(
        [first, second], download=lambda url: (_mini_svg(), "image/svg+xml")
    )
    assert cells["light_lockup"].origin_url == "one"
```

- [x] **Step 2: Run tests to verify they fail**

Expected: FAIL — `ImportError: cannot import name 'map_vendor_assets_to_cells'`.

- [x] **Step 3: Implement `map_vendor_assets_to_cells`**

Append to `logo_vendor.py`:

```python
def _classify_null_theme(body: bytes, fmt: str) -> tuple[str, str]:
    """Our theme for a vendor asset that carries none, read off the bytes with
    the ladder's own appearance analyzer (one classifier, no drift).
    Returns (our_theme, basis)."""
    from .logo_ladder import LadderCandidate, analyze_appearance

    probe = LadderCandidate(url="", fmt=fmt, body=body)
    verdict = analyze_appearance(probe).get("verdict")
    if verdict == "dark_variant":  # light/white ink -> made for dark surfaces
        return "dark", "classified from bytes: light ink (dark_variant)"
    if verdict == "light_variant":
        return "light", "classified from bytes: dark ink (light_variant)"
    if verdict == "adaptive":
        return "light", "classified from bytes: adaptive (one file, filed under light)"
    return "light", "classified from bytes: no verdict; vendor-attributed, filed light"


def map_vendor_assets_to_cells(assets, download):
    """Vendor assets -> 2x2 cells. Filters (icon/other/photographic), inverts
    theme, classifies theme=None from the bytes, gates SVGs on renderability.
    First asset wins per cell. Returns (cells, notes)."""
    from .logo_family import SOURCE_BRANDFETCH, FamilyCell, cell_name
    from .logo_ladder import svg_is_renderable

    cells: dict[str, FamilyCell] = {}
    notes: list[str] = []
    for asset in assets:
        completeness = _COMPLETENESS_FOR_VENDOR_TYPE.get(asset.type)
        if completeness is None:
            continue  # icon/other: ruled out, silently -- they are not skips gone wrong
        if "photographic" in asset.tags:
            notes.append(f"vendor {asset.type} skipped: tagged photographic")
            continue
        chosen = pick_format(asset)
        if chosen is None:
            notes.append(f"vendor {asset.type} skipped: no downloadable format")
            continue

        our_theme = _OUR_THEME_FOR_VENDOR_THEME.get(asset.theme or "")
        theme_basis = f"vendor theme={asset.theme!r} (inverted to ours)"
        # theme=None needs the bytes to classify, so only pre-check occupancy
        # when the theme is already known.
        if our_theme is not None and cell_name(our_theme, completeness) in cells:
            notes.append(f"vendor {asset.type} ({asset.theme}) skipped: cell already filled")
            continue

        fetched = download(str(chosen.get("src")))
        if fetched is None:
            notes.append(f"vendor {asset.type} download failed: {chosen.get('src')}")
            continue
        body, content_type = fetched
        fmt = str(chosen.get("format") or "")
        if our_theme is None:
            our_theme, theme_basis = _classify_null_theme(body, fmt)

        name = cell_name(our_theme, completeness)
        if name in cells:
            notes.append(f"vendor {asset.type} skipped: cell {name} already filled")
            continue
        if fmt == "svg" and not svg_is_renderable(body):
            notes.append(
                f"vendor {asset.type} refused: SVG cannot paint standalone "
                f"(no intrinsic geometry or no drawable artwork, not renderable)"
            )
            continue
        cells[name] = FamilyCell(
            cell=name,
            body=body,
            content_type=content_type or _FORMAT_MIME.get(fmt, "image/png"),
            source=SOURCE_BRANDFETCH,
            origin_url=str(chosen.get("src")),
            evidence={
                "vendor": VENDOR_NAME,
                "vendor_theme": asset.theme,
                "vendor_type": asset.type,
                "theme_basis": theme_basis,
                "format": fmt,
                "width": chosen.get("width"),
                "height": chosen.get("height"),
            },
        )
    return cells, notes
```

- [x] **Step 4: Run tests to verify they pass**

Expected: all PASS. If `_classify_null_theme` misbehaves, check that `LadderCandidate(url="", fmt="svg", body=...)` satisfies `analyze_appearance` (it reads only `fmt` and `body` for SVGs — see `logo_ladder.py:1377-1412`).

- [x] **Step 5: Commit**

```bash
git add subsystems/clue-design/apps/api/lumen_ingestion/logo_vendor.py subsystems/clue-design/apps/api/tests/test_logo_vendor.py
git commit -m "feat(logo): vendor asset -> 2x2 cell mapping

Theme inversion (their dark = our light) pinned by test; icon/other/photographic
filtered; theme=null classified from bytes via the ladder's analyzer;
svg_is_renderable gates vendor SVGs; first asset wins per cell."
```

---

### Task 3b (carry-over of D2 + D3): raster decodability gate + Task 1 nits

**Status: DONE 2026-09-02 — commit `9387f9b7f`; controller first-hand review clean. (Brief erratum: the Step 2 parenthetical says garbage fills `dark_mark`; vendor theme=dark inverts to OUR light, so it fills `light_mark` — code and test are right.)**

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/logo_vendor.py` (append `_raster_decodes`; one new gate in `map_vendor_assets_to_cells` directly after the SVG gate)
- Modify: `subsystems/clue-design/packages/py-lumen-config/py_lumen_config/config.py` (comment tag only)
- Test: `subsystems/clue-design/apps/api/tests/test_logo_vendor.py` (extend + one fixture fix)

**Interfaces:**
- Consumes: Task 3's `map_vendor_assets_to_cells`; Pillow (already a dependency — the ladder decodes rasters with it, lazily).
- Produces: `logo_vendor._raster_decodes(body: bytes) -> bool`; mapping rule 6b — a png/webp/jpeg cell whose bytes Pillow cannot open is refused with a note containing "cannot be decoded"; the cell stays empty for the ladder to backfill.

- [x] **Step 1: Write the failing tests / fix the fixture**

Append to `test_logo_vendor.py`:

```python
def _mini_png(rgb=(16, 24, 32), size=64) -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGBA", (size, size), rgb + (255,)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_map_vendor_assets_refuses_undecodable_raster():
    from lumen_ingestion.logo_vendor import VendorAsset, map_vendor_assets_to_cells

    garbage = VendorAsset(theme="dark", type="symbol", tags=[], formats=[
        {"src": "g", "format": "png", "width": 300, "height": 300, "size": 1,
         "background": None}])
    cells, notes = map_vendor_assets_to_cells(
        [garbage], download=lambda url: (b"not-a-png-at-all", "image/png")
    )
    assert cells == {}
    assert any("cannot be decoded" in n for n in notes)
```

In `test_map_vendor_assets_inverts_theme_and_skips_icon_and_photographic`, replace the fake bytes `b"\x89PNGfakebytes"` with `_mini_png()` (the fixture must be a real image now that rasters are decoded). Move `_mini_png` above that test so it is defined before use.

In `test_brandfetch_settings_load_from_env`, add `monkeypatch.setenv("BRANDFETCH_API_BASE_URL", "https://example.test")` beside the other setenv calls and `assert fresh.brandfetch_api_base_url == "https://example.test"` beside the other asserts.

- [x] **Step 2: Run to verify FAIL** — the new test fails (garbage bytes currently fill `dark_mark`); the settings test passes already (an assertion added to green code — acceptable, it pins D2).
`PYTHONPATH=.:apps/api:apps/agent_runtime <repo-root>/.venv/bin/python -m pytest apps/api/tests/test_logo_vendor.py -v`

- [x] **Step 3: Implement**

Append to `logo_vendor.py`:

```python
def _raster_decodes(body: bytes) -> bool:
    """Can Pillow open these bytes? The raster twin of `svg_is_renderable`: a
    vendor cell must hold a file that PAINTS, whatever its format, and an
    undecodable raster would otherwise travel all the way to `core.ingest_asset`
    before anything said so."""
    import io

    from PIL import Image  # lazy, like the ladder: `capture` must import PIL-free

    try:
        with Image.open(io.BytesIO(body)) as image:
            image.verify()
        return True
    except Exception:  # noqa: BLE001 - undecodable is the answer, not an error
        return False
```

In `map_vendor_assets_to_cells`, directly after the SVG renderability `continue`:

```python
        if fmt in ("png", "webp", "jpeg") and not _raster_decodes(body):
            notes.append(
                f"vendor {asset.type} refused: {fmt} bytes cannot be decoded as an image"
            )
            continue
```

In `config.py`, change the comment header `# -- Brandfetch (target-account logo vendor; W-logo vendor-first, 2026-09-02) --------` to `# -- Brandfetch (target-account logo vendor; vendor-first logo family, 2026-09-02) ----`.

- [x] **Step 4: Run to verify PASS** — all 11 tests green (same command).

- [x] **Step 5: Commit**

```bash
git add subsystems/clue-design/apps/api/lumen_ingestion/logo_vendor.py subsystems/clue-design/packages/py-lumen-config/py_lumen_config/config.py subsystems/clue-design/apps/api/tests/test_logo_vendor.py
git commit -m "feat(logo): raster decodability gate for vendor cells; settings test pins base url

D3: a png/webp/jpeg cell must decode (Pillow) or it is refused with a note —
the raster twin of svg_is_renderable. D2: base-url-from-env assertion; comment
tag reworded."
```

---

### Task 4: Vendor network driver (`fetch_vendor_family`)

**Status: DONE 2026-09-02 — commits `abe5d9d4f` + fix `417da50b4`; controller first-hand review clean; LIVE-verified end-to-end (real key, `brandfetch.com`: all four cells filled from `cdn.brandfetch.io`, inversion applied, zero notes). Errata: the happy-path fixture's `b"\x89PNGfake"` predates Task 3b's raster gate — shipped as `_mini_png()`; fix round added `_asset_host_allowed` (iterates every suffix), moved `urlsplit` into the import block, and a test for the `timeout`/`malformed` codes (16 tests in the file).**

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/logo_vendor.py`
- Test: `subsystems/clue-design/apps/api/tests/test_logo_vendor.py` (extend)

**Interfaces:**
- Consumes: Task 1 settings; Task 2/3 parsing + mapping; `logo_ladder.registrable_domain` (host folding).
- Produces: `logo_vendor.fetch_vendor_family(domain: str, *, api_key: str | None = None, base_url: str | None = None, timeout_s: float | None = None, client: httpx.Client | None = None) -> tuple[dict[str, FamilyCell], list[str]]`. Also update the `VendorLookupFailed.__init__` inline comment (Task 2) to list the five codes `"quota" | "auth" | "timeout" | "http" | "malformed"`.
  - Raises `VendorCredentialsMissing` when the effective key is blank.
  - Raises `VendorLookupFailed(code="quota")` on 429, `("auth")` on 401/403 (the vendor's documented "Unauthorized" — a MISCONFIGURED key, named as such so the operator sees it, message: `"brandfetch rejected the API key (HTTP <status>); check BRANDFETCH_API_KEY"`), `("timeout")` on `httpx.TimeoutException`, `("http")` on other non-200/404 (incl. the documented 400 "Bad Request"), `("malformed")` on unparseable JSON. (Vendor contract per the Brand API reference, scraped 2026-09-02: responses 200/400/401/404/429, `bearerAuth`.)
  - 404 → `({}, ["brandfetch has no record of <domain> — an answer, not an error"])`.
  - **User-Agent (live-verified 2026-09-02):** the asset CDN (`cdn.brandfetch.io`, where the Brand API's `formats[].src` actually point) answers `302 x-bf-error=user_agent_required` to any request without a `User-Agent`. The driver sends an explicit `User-Agent: clue-design-logo-vendor/1 (+httpx)` on the brand lookup and on every asset download — never relying on the library default. The happy-path MockTransport handler asserts the header is present on both request kinds.
  - **Theme inversion live-verified 2026-09-02** on `brandfetch.com`'s real assets: vendor `theme=dark` SVG → `analyze_appearance` `light_variant` (mean L 0.13) → our `light`; vendor `theme=light` → `dark_variant` (L 1.0) → our `dark`.
  - **D6 — asset host allowlist:** `_ASSET_HOST_SUFFIXES = ("brandfetch.io",)`. `download(src)` refuses (returns `None`) any `src` whose host is not that suffix or a subdomain of it, and the driver appends `"asset host <host> is not on the vendor allowlist; not fetched: <src>"` to its notes (merged with the mapping's notes in the return). The MockTransport test below asserts the handler is never called for the foreign host.
  - **Sync httpx**, not async: the callers (`fetch_logo` tools) are synchronous, and the existing prep layer already wraps the ladder's async driver with `asyncio.run` — the vendor rung stays simpler by being sync end-to-end. Asset downloads go through the same `httpx.Client` with the configured timeout and a 15 MB size cap read via `resp.headers.get("content-length")` check + len guard (mirroring `capture.net`'s cap value; the Brand API srcs are Brandfetch's own asset CDN, not attacker-controlled pages, so the full SSRF re-guard machinery is not pulled in here — the domain never varies).

- [x] **Step 1: Write the failing tests** (httpx.MockTransport — no live network in CI)

```python
def _vendor_transport(handler):
    import httpx

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_vendor_family_happy_path_builds_cells():
    import httpx

    from lumen_ingestion.logo_vendor import fetch_vendor_family

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/brands/domain/acme.com":
            assert request.headers["Authorization"] == "Bearer bf_test_key"
            return httpx.Response(200, json=BRAND_PAYLOAD)
        if request.url.path.endswith("lockup-dark.svg"):
            return httpx.Response(200, content=_mini_svg("#101820"),
                                  headers={"content-type": "image/svg+xml"})
        if request.url.path.endswith("symbol-light.png"):
            return httpx.Response(200, content=b"\x89PNGfake",
                                  headers={"content-type": "image/png"})
        return httpx.Response(404)

    with _vendor_transport(handler) as client:
        cells, notes = fetch_vendor_family(
            "https://www.acme.com/pricing", api_key="bf_test_key", client=client
        )
    assert set(cells) == {"light_lockup", "dark_mark"}


def test_fetch_vendor_family_404_is_an_answer_and_429_is_typed():
    import httpx
    import pytest as _pytest

    from lumen_ingestion.logo_vendor import VendorLookupFailed, fetch_vendor_family

    with _vendor_transport(lambda r: httpx.Response(404)) as client:
        cells, notes = fetch_vendor_family("acme.com", api_key="k", client=client)
    assert cells == {} and any("no record" in n for n in notes)

    with _vendor_transport(lambda r: httpx.Response(429)) as client:
        with _pytest.raises(VendorLookupFailed) as err:
            fetch_vendor_family("acme.com", api_key="k", client=client)
    assert err.value.code == "quota"

    with _vendor_transport(lambda r: httpx.Response(401)) as client:
        with _pytest.raises(VendorLookupFailed) as err:
            fetch_vendor_family("acme.com", api_key="bad", client=client)
    assert err.value.code == "auth" and "BRANDFETCH_API_KEY" in err.value.message


def test_fetch_vendor_family_blank_key_raises_credentials_missing():
    import pytest as _pytest

    from lumen_ingestion.logo_vendor import VendorCredentialsMissing, fetch_vendor_family

    with _pytest.raises(VendorCredentialsMissing):
        fetch_vendor_family("acme.com", api_key="")


def test_fetch_vendor_family_never_fetches_off_allowlist_hosts():
    import httpx

    from lumen_ingestion.logo_vendor import fetch_vendor_family

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        if request.url.path.startswith("/v2/brands/domain/"):
            return httpx.Response(200, json={"logos": [
                {"theme": "dark", "type": "logo", "tags": [], "formats": [
                    {"src": "https://evil.example/lockup.svg", "format": "svg",
                     "width": 100, "height": 40, "size": 1, "background": None}]}]})
        return httpx.Response(200, content=_mini_svg(), headers={"content-type": "image/svg+xml"})

    with _vendor_transport(handler) as client:
        cells, notes = fetch_vendor_family("acme.com", api_key="k", client=client)
    assert cells == {}
    assert "evil.example" not in seen
    assert any("allowlist" in n for n in notes)
```

- [x] **Step 2: Run tests to verify they fail** — `ImportError: fetch_vendor_family`.

- [x] **Step 3: Implement**

Append to `logo_vendor.py`:

```python
#: the Brand API path; the base-url normalizer strips it if the operator's
#: BRANDFETCH_API_BASE_URL already carries it (the PDL _normalize_base_url lesson).
BRAND_PATH_PREFIX = "/v2/brands/domain/"
_MAX_ASSET_BYTES = 15 * 1024 * 1024  # mirrors capture.net's logo cap
#: D6 — the only hosts an asset `src` may point at. Brandfetch serves logo files from its own
#: asset CDN; anything else in a `formats[].src` is not fetched, whatever the API said.
_ASSET_HOST_SUFFIXES = ("brandfetch.io",)


from urllib.parse import urlsplit  # module-level: `download` and `_bare_domain` both need it


def _bare_domain(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    candidate = text if "//" in text else f"//{text}"
    host = (urlsplit(candidate).hostname or text).strip().lower()
    return host[4:] if host.startswith("www.") else host


def fetch_vendor_family(domain, *, api_key=None, base_url=None, timeout_s=None, client=None):
    """One Brand API lookup + asset downloads -> (cells, notes). The one impure
    entry point of this module. See the module docstring for the contract."""
    import httpx
    from py_lumen_config import settings

    key = (api_key if api_key is not None else settings.brandfetch_api_key).strip()
    if not key:
        raise VendorCredentialsMissing()
    base = (base_url if base_url is not None else settings.brandfetch_api_base_url)
    base = base.strip().rstrip("/")
    if base.lower().endswith(BRAND_PATH_PREFIX.rstrip("/")):
        base = base[: -len(BRAND_PATH_PREFIX.rstrip("/"))].rstrip("/")
    timeout = timeout_s if timeout_s is not None else settings.brandfetch_timeout_s
    host = _bare_domain(domain)
    if not host:
        raise VendorLookupFailed("http", f"could not read a host out of {domain!r}")

    def run(http: "httpx.Client"):
        try:
            resp = http.get(
                f"{base}{BRAND_PATH_PREFIX}{host}",
                headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
                timeout=timeout,
            )
        except httpx.TimeoutException as error:
            raise VendorLookupFailed("timeout", f"brand lookup timed out: {error}") from error
        except httpx.HTTPError as error:
            raise VendorLookupFailed("http", f"brand lookup failed: {error}") from error
        if resp.status_code == 404:
            return {}, [f"brandfetch has no record of {host} — an answer, not an error"]
        if resp.status_code == 429:
            raise VendorLookupFailed(
                "quota", "brandfetch quota or throughput limit reached (HTTP 429)"
            )
        if resp.status_code in (401, 403):
            raise VendorLookupFailed(
                "auth",
                f"brandfetch rejected the API key (HTTP {resp.status_code}); "
                "check BRANDFETCH_API_KEY",
            )
        if resp.status_code != 200:
            raise VendorLookupFailed("http", f"brand lookup returned HTTP {resp.status_code}")
        try:
            payload = resp.json()
        except ValueError as error:
            raise VendorLookupFailed("malformed", "brand response was not JSON") from error

        driver_notes: list[str] = []

        def download(src: str):
            host = (urlsplit(src).hostname or "").lower()
            if not (host == _ASSET_HOST_SUFFIXES[0] or any(
                host.endswith("." + suffix) for suffix in _ASSET_HOST_SUFFIXES
            )):
                driver_notes.append(
                    f"asset host {host or '?'} is not on the vendor allowlist; not fetched: {src}"
                )
                return None
            try:
                got = http.get(src, timeout=timeout)
            except httpx.HTTPError:
                return None
            if got.status_code != 200 or not got.content:
                return None
            if len(got.content) > _MAX_ASSET_BYTES:
                return None
            return got.content, got.headers.get("content-type")

        cells, notes = map_vendor_assets_to_cells(parse_brand_payload(payload), download)
        return cells, driver_notes + notes

    if client is not None:
        return run(client)
    with httpx.Client() as owned:
        return run(owned)
```

- [x] **Step 4: Run tests to verify they pass.** Then run the whole file once more:
`PYTHONPATH=.:apps/api:apps/agent_runtime <repo-root>/.venv/bin/python -m pytest apps/api/tests/test_logo_vendor.py -v` — all green.

- [x] **Step 5: Commit**

```bash
git add subsystems/clue-design/apps/api/lumen_ingestion/logo_vendor.py subsystems/clue-design/apps/api/tests/test_logo_vendor.py
git commit -m "feat(logo): Brandfetch network driver — sync httpx, typed degrades

404 = typed absence; 429 = quota degrade; timeout/http/malformed typed;
15MB asset cap; base-url tolerant of the full path (PDL lesson)."
```

---

### Task 5: Ladder slots → 2×2 cells (`ladder_cells`)

**Status: DONE 2026-09-02 — commit `50908e087`; controller first-hand review clean (collision precedence probed). Task 6 pins the symbol-primary-vs-mark collision with a test.**

**Files:**
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/tools/logo_fetch.py`
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_fetch_logo_tool.py` (extend)

**Interfaces:**
- Consumes: `logo_ladder.LadderResolution` (slots dict: `light`/`dark`/`mark`/`wordmark` → `LadderSlot | None`; each `LadderSlot` has `.candidate` (with `.lockup` ∈ `symbol|wordmark|full_lockup|unknown`, `.variant` ∈ `light|dark|adaptive|unknown`, `.url`), `.provenance` (`"genuine" | "materialized-adaptive"`), `.body`, `.content_type`, `.basis`, `.ink`); `logo_family.FamilyCell`.
- Produces: `logo_fetch.ladder_cells(resolution: LadderResolution) -> dict[str, FamilyCell]` — mapping rules:
  - ladder `light` slot → `light_lockup` when `candidate.lockup in ("full_lockup", "wordmark", "unknown")`, else `light_mark` (a symbol-shaped primary is a mark).
  - ladder `dark` slot → same rule on the `dark_*` side.
  - ladder `mark` slot → `dark_mark` when `candidate.variant == "dark"`, else `light_mark` — only if that cell is still empty.
  - ladder `wordmark` slot → `light_lockup` only if still empty (the ladder already refuses dark-variant wordmarks).
  - `source` = `"ladder-materialized"` when `slot.provenance == "materialized-adaptive"`, else `"ladder"`.
  - evidence carries the slot's `basis`, `rung`, ladder slot name, and `ink` when present.

- [x] **Step 1: Write the failing tests**

Append to `test_fetch_logo_tool.py` (it already imports `logo_fetch`; build synthetic resolutions with the real ladder dataclasses):

```python
def _slot(body: bytes, *, lockup: str, variant: str, provenance: str = "genuine",
          url: str = "https://acme.com/logo.svg", rung: str = "HEADER"):
    from lumen_ingestion.logo_ladder import LadderCandidate, LadderSlot

    candidate = LadderCandidate(url=url, rung=rung, fmt="svg")
    candidate.lockup = lockup
    candidate.variant = variant
    return LadderSlot(candidate=candidate, provenance=provenance, body=body,
                      content_type="image/svg+xml", basis="test basis")


def _resolution(slots):
    from lumen_ingestion.logo_ladder import LadderResolution

    res = LadderResolution(status="resolved", identity={"passed": True})
    res.slots = {"light": None, "dark": None, "mark": None, "wordmark": None, **slots}
    return res


def test_ladder_cells_maps_lockup_primaries_and_variant_marks():
    from lumen_agent.tools.logo_fetch import ladder_cells

    cells = ladder_cells(_resolution({
        "light": _slot(_svg(), lockup="full_lockup", variant="light"),
        "dark": _slot(_svg("#ffffff"), lockup="full_lockup", variant="dark"),
        "mark": _slot(_svg(), lockup="symbol", variant="unknown"),
    }))
    assert set(cells) == {"light_lockup", "dark_lockup", "light_mark"}
    assert cells["light_lockup"].source == "ladder"


def test_ladder_cells_symbol_primary_lands_in_the_mark_cell():
    from lumen_agent.tools.logo_fetch import ladder_cells

    cells = ladder_cells(_resolution({
        "light": _slot(_svg(), lockup="symbol", variant="light"),
    }))
    assert list(cells) == ["light_mark"]


def test_ladder_cells_wordmark_backfills_light_lockup_and_materialized_is_stamped():
    from lumen_agent.tools.logo_fetch import ladder_cells

    cells = ladder_cells(_resolution({
        "wordmark": _slot(_svg(), lockup="wordmark", variant="light"),
        "dark": _slot(_svg("#ffffff"), lockup="full_lockup", variant="adaptive",
                      provenance="materialized-adaptive"),
    }))
    assert cells["light_lockup"].evidence["ladder_slot"] == "wordmark"
    assert cells["dark_lockup"].source == "ladder-materialized"
```

- [x] **Step 2: Run to verify FAIL** (`ImportError: ladder_cells`):
`PYTHONPATH=.:apps/api:apps/agent_runtime <repo-root>/.venv/bin/python -m pytest apps/agent_runtime/tests/test_fetch_logo_tool.py -v -k ladder_cells`

- [x] **Step 3: Implement `ladder_cells` in `logo_fetch.py`**

```python
def ladder_cells(resolution) -> dict:
    """The ladder's four slots folded into the 2x2. The ladder's `light`/`dark`
    are theme-correct already (its slot names use OUR background semantics);
    what this adds is the completeness split: a symbol-shaped primary is a
    MARK, not a lockup, and the wordmark slot backfills the light lockup."""
    from lumen_ingestion.logo_family import (
        SOURCE_LADDER,
        SOURCE_LADDER_MATERIALIZED,
        FamilyCell,
    )

    def to_cell(name: str, slot, ladder_slot: str) -> FamilyCell:
        return FamilyCell(
            cell=name,
            body=slot.body,
            content_type=slot.content_type,
            source=(
                SOURCE_LADDER_MATERIALIZED
                if slot.provenance == "materialized-adaptive"
                else SOURCE_LADDER
            ),
            origin_url=slot.candidate.url,
            evidence={
                "ladder_slot": ladder_slot,
                "rung": slot.candidate.rung,
                "basis": slot.basis[:200],
                "lockup": slot.candidate.lockup,
                **({"materialized_ink": slot.ink} if slot.ink else {}),
            },
        )

    cells: dict = {}
    for theme in ("light", "dark"):
        slot = resolution.slots.get(theme)
        if slot is None or not slot.body:
            continue
        completeness = "mark" if slot.candidate.lockup == "symbol" else "lockup"
        cells[f"{theme}_{completeness}"] = to_cell(f"{theme}_{completeness}", slot, theme)

    mark = resolution.slots.get("mark")
    if mark is not None and mark.body:
        name = "dark_mark" if mark.candidate.variant == "dark" else "light_mark"
        if name not in cells:
            cells[name] = to_cell(name, mark, "mark")

    wordmark = resolution.slots.get("wordmark")
    if wordmark is not None and wordmark.body and "light_lockup" not in cells:
        cells["light_lockup"] = to_cell("light_lockup", wordmark, "wordmark")
    return cells
```

- [x] **Step 4: Run to verify PASS** (same command, `-k ladder_cells`).

- [x] **Step 5: Commit**

```bash
git add subsystems/clue-design/apps/agent_runtime/lumen_agent/tools/logo_fetch.py subsystems/clue-design/apps/agent_runtime/tests/test_fetch_logo_tool.py
git commit -m "feat(logo): ladder slots -> 2x2 cells

Symbol-shaped primaries land in mark cells; wordmark backfills light_lockup;
materialized-adaptive provenance survives as its own source label."
```

---

### Task 6: The two-rung dispatch (rewrite `logo_fetch.fetch_logo_family`)

**Status: DONE 2026-09-02 — commits `08de3c8e2` + fixes `ab6b477a4`, `2d1d31d8e` (D8: vendor cells ingest with the engine's `website` source kind); controller first-hand review clean. Errata vs the plan text: `status` is `ok` only when a vendor cell exists or the ladder RESOLVED (a hesitant ladder-only family stays `needs_review` with its cells prepared, as before), and `cache.put` runs only on `ok`; `PreparedLogo.slot` survives as a deprecated alias until Task 10; one strict xfail (`test_web_fetch_logo_registers_with_the_record_op_key`) awaits Task 10.**

**Files:**
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/tools/logo_fetch.py` (the `fetch_logo_family`, `_prepare`, `LogoFetchOutcome`, `PreparedLogo`, `review_payload` block)
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_fetch_logo_tool.py` (extend). **Controller rulings (2026-09-02):** (a) the two HELPER-level tests (`test_the_helper_shapes_one_ingest_per_resolved_slot`, `test_the_helper_reports_review_without_preparing_anything`) test `logo_fetch` itself, which this task rewrites — UPDATE them to the cell vocabulary here (`p.cell`, `{"light_lockup", "dark_lockup"} <= cells`, `kwargs["provenance"]["created_by"] == "logo_ladder"`, `kwargs["source"]["kind"] == "website"` unchanged); (b) the TOOL-level payload tests (`test_web_fetch_logo_registers_with_the_record_op_key` and any scene equivalent asserting `entry["slot"] == "light"`) are Task 10's — mark them `@pytest.mark.xfail(strict=True, reason="cells payload lands in task 10")` and nothing else; (c) **LIVE-CALL SAFETY:** the existing `_fake_site` tests fake only the ladder driver, and the repo-root `.env` now carries a REAL Brandfetch key — so this task adds, at the top of the file, an autouse fixture that disables the vendor rung for every test unless a test overrides it:

```python
@pytest.fixture(autouse=True)
def _vendor_rung_disabled(monkeypatch):
    """No test in this file may reach Brandfetch: the repo .env carries a real key.
    Tests that exercise the vendor path monkeypatch `logo_fetch._vendor_rung` themselves."""
    from lumen_ingestion.logo_vendor import VendorCredentialsMissing

    def disabled(site, company):
        raise VendorCredentialsMissing()

    monkeypatch.setattr(logo_fetch, "_vendor_rung", disabled)
```

The dispatch tests below override it per-test with their own `monkeypatch.setattr(logo_fetch, "_vendor_rung", ...)`, which takes precedence.)

**Interfaces:**
- Consumes: `fetch_vendor_family`, `VendorCredentialsMissing`, `VendorLookupFailed` (Task 4); `ladder_cells` (Task 5); the existing ladder driver `logo_ladder.fetch_logo_family` (async, wrapped in `asyncio.run` as today); `logo_family.CELL_NAMES`.
- Produces the NEW prep contract both lane tools consume in Task 10:
  - `PreparedLogo` gains `cell: str` and `source: str`. **Controller ruling (continuity, 2026-09-02):** `slot` is NOT removed here — both substrate tools read `prepared.slot` in six places and would crash until Task 10. Task 6 keeps a read-only alias `@property def slot(self) -> str: return self.cell` on `PreparedLogo`, commented `# deprecated alias: deleted in Task 10`; Task 10 deletes it when the tools switch to `.cell`. `provenance["created_by"]` becomes `"logo_ladder"` or `"brandfetch"` per cell source (`"ladder-materialized"` stamps `"logo_ladder"` — it is the ladder's mechanism).
  - `LogoFetchOutcome` gains `cells: dict[str, str]` (cell → source, for the payload), `vendor_notes: list[str]`, `cache_hit: bool = False`; keeps `status`/`site`/`company`/`prepared`/`identity`/`lockup_completeness`/`notes`/`candidates`.
  - `fetch_logo_family(url_or_domain: str, *, company_name: str | None = None, force_refresh: bool = False, cache=None) -> LogoFetchOutcome`. `cache` is any object with `get(site: str) -> LogoFetchOutcome | None` and `put(site: str, outcome: LogoFetchOutcome) -> None` (duck-typed; Task 7 builds the durable one; `None` = no caching, today's behavior).
  - Dispatch order: cache (unless `force_refresh`) → vendor → ladder for empty cells only → assemble. Ladder is NOT run when all four cells are vendor-filled. Ladder identity failure with zero vendor cells → `needs_review` exactly as today. Vendor cells survive even when the ladder's backfill run comes back `needs_review` (the vendor already answered identity for its own cells — keyed retrieval).
  - `review_payload` unchanged in shape but its `reason` mentions the vendor when the vendor was tried (`vendor_notes` threaded in).

- [x] **Step 1: Write the failing tests**

```python
class _RecordingCache:
    def __init__(self):
        self.stored = {}
        self.gets = []

    def get(self, site):
        self.gets.append(site)
        return self.stored.get(site)

    def put(self, site, outcome):
        self.stored[site] = outcome


def _vendor_cells(*names):
    from lumen_ingestion.logo_family import SOURCE_BRANDFETCH, FamilyCell

    return {
        n: FamilyCell(cell=n, body=_svg(), content_type="image/svg+xml",
                      source=SOURCE_BRANDFETCH, origin_url=f"https://a/{n}.svg")
        for n in names
    }


def test_dispatch_vendor_full_family_skips_the_ladder(monkeypatch):
    from lumen_agent.tools import logo_fetch

    monkeypatch.setattr(
        logo_fetch, "_vendor_rung",
        lambda site, company: (_vendor_cells(*logo_fetch.CELL_NAMES), []),
    )

    def explode(*a, **k):
        raise AssertionError("ladder must not run when the vendor filled all cells")

    monkeypatch.setattr(logo_fetch, "_ladder_rung", explode)
    outcome = logo_fetch.fetch_logo_family("acme.com")
    assert outcome.status == "ok"
    assert set(outcome.cells) == set(logo_fetch.CELL_NAMES)
    assert all(source == "brandfetch" for source in outcome.cells.values())
    assert {p.cell for p in outcome.prepared} == set(logo_fetch.CELL_NAMES)
    assert all(p.provenance["created_by"] == "brandfetch" for p in outcome.prepared)


def test_dispatch_partial_vendor_gets_ladder_backfill_only_for_empty_cells(monkeypatch):
    from lumen_agent.tools import logo_fetch

    monkeypatch.setattr(
        logo_fetch, "_vendor_rung", lambda site, company: (_vendor_cells("light_lockup"), [])
    )
    ladder = _resolution({
        "light": _slot(_svg(), lockup="full_lockup", variant="light"),   # must NOT win
        "dark": _slot(_svg("#fff"), lockup="full_lockup", variant="dark"),
        "mark": _slot(_svg(), lockup="symbol", variant="unknown"),
    })
    monkeypatch.setattr(logo_fetch, "_ladder_rung", lambda site, company: ladder)
    outcome = logo_fetch.fetch_logo_family("acme.com")
    assert outcome.cells["light_lockup"] == "brandfetch"   # vendor kept
    assert outcome.cells["dark_lockup"] == "ladder"
    assert outcome.cells["light_mark"] == "ladder"


def test_dispatch_vendor_disabled_or_failing_degrades_to_ladder(monkeypatch):
    from lumen_agent.tools import logo_fetch
    from lumen_ingestion.logo_vendor import VendorCredentialsMissing, VendorLookupFailed

    ladder = _resolution({"light": _slot(_svg(), lockup="full_lockup", variant="light")})
    monkeypatch.setattr(logo_fetch, "_ladder_rung", lambda site, company: ladder)

    def no_key(site, company):
        raise VendorCredentialsMissing()

    monkeypatch.setattr(logo_fetch, "_vendor_rung", no_key)
    outcome = logo_fetch.fetch_logo_family("acme.com")
    assert outcome.cells == {"light_lockup": "ladder"}
    assert any("vendor rung disabled" in n for n in outcome.notes)

    def quota(site, company):
        raise VendorLookupFailed("quota", "429")

    monkeypatch.setattr(logo_fetch, "_vendor_rung", quota)
    outcome = logo_fetch.fetch_logo_family("acme.com")
    assert outcome.cells == {"light_lockup": "ladder"}
    assert any("quota" in n for n in outcome.notes)


def test_dispatch_nothing_anywhere_is_fail_closed_needs_review(monkeypatch):
    from lumen_agent.tools import logo_fetch
    from lumen_ingestion.logo_ladder import LadderResolution

    empty = LadderResolution(status="needs_review",
                             identity={"passed": False, "reason": "no overlap"})
    empty.slots = {"light": None, "dark": None, "mark": None, "wordmark": None}
    monkeypatch.setattr(logo_fetch, "_vendor_rung", lambda site, company: ({}, ["no record"]))
    monkeypatch.setattr(logo_fetch, "_ladder_rung", lambda site, company: empty)
    outcome = logo_fetch.fetch_logo_family("acme.com")
    assert outcome.needs_review and outcome.prepared == []


def test_dispatch_cache_hit_skips_both_rungs_and_force_refresh_overwrites(monkeypatch):
    from lumen_agent.tools import logo_fetch

    cache = _RecordingCache()
    monkeypatch.setattr(
        logo_fetch, "_vendor_rung",
        lambda site, company: (_vendor_cells(*logo_fetch.CELL_NAMES), []),
    )
    monkeypatch.setattr(logo_fetch, "_ladder_rung",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no ladder")))
    first = logo_fetch.fetch_logo_family("acme.com", cache=cache)
    assert first.cache_hit is False and "https://acme.com/" in cache.stored

    def explode(site, company):
        raise AssertionError("vendor must not be called on a cache hit")

    monkeypatch.setattr(logo_fetch, "_vendor_rung", explode)
    second = logo_fetch.fetch_logo_family("acme.com", cache=cache)
    assert second.cache_hit is True and set(second.cells) == set(logo_fetch.CELL_NAMES)

    # force_refresh bypasses the read and overwrites the entry
    monkeypatch.setattr(
        logo_fetch, "_vendor_rung",
        lambda site, company: (_vendor_cells("light_lockup"), []),
    )
    ladder = _resolution({})
    monkeypatch.setattr(logo_fetch, "_ladder_rung", lambda site, company: ladder)
    third = logo_fetch.fetch_logo_family("acme.com", cache=cache, force_refresh=True)
    assert third.cache_hit is False and list(third.cells) == ["light_lockup"]
```

- [x] **Step 2: Run to verify FAIL**
`... -m pytest apps/agent_runtime/tests/test_fetch_logo_tool.py -v -k dispatch`
Expected: FAIL — `AttributeError: module ... has no attribute '_vendor_rung'`.

- [x] **Step 3: Rewrite the prep layer**

In `logo_fetch.py`: keep `LOGO_TAGS`; replace `SLOT_NAMES` with a re-export `from lumen_ingestion.logo_family import CELL_NAMES` (delete `SLOT_NAMES` — Task 10 updates the two tool call sites; nothing else imports it, verify with `grep -rn "SLOT_NAMES" subsystems/clue-design --include='*.py'`).

```python
@dataclass
class PreparedLogo:
    """One resolved cell, shaped for `core.ingest_asset`."""

    cell: str
    source: str  # "brandfetch" | "ladder" | "ladder-materialized"
    asset_id: str
    label: str
    body: bytes
    content_type: str
    provenance: JsonObject
    source_ref: JsonObject   # the ingest `source` kwarg (renamed field, same payload)
    evidence: JsonObject

    def ingest_kwargs(self, store_root: str) -> JsonObject:
        import base64

        return {
            "store_root": store_root,
            "bytes_base64": base64.b64encode(self.body).decode("ascii"),
            "asset_id": self.asset_id,
            "label": self.label,
            "declared_mime_type": self.content_type,
            "kind": "vector" if self.content_type == "image/svg+xml" else "raster_image",
            "provenance": self.provenance,
            "source": self.source_ref,
            "tags": list(LOGO_TAGS),
            "raise_on_error": False,
        }


@dataclass
class LogoFetchOutcome:
    status: str
    site: str
    company: Optional[str]
    prepared: List[PreparedLogo] = field(default_factory=list)
    cells: Dict[str, str] = field(default_factory=dict)  # cell -> source
    identity: JsonObject = field(default_factory=dict)
    lockup_completeness: str = "unknown"
    notes: List[str] = field(default_factory=list)
    vendor_notes: List[str] = field(default_factory=list)
    candidates: List[JsonObject] = field(default_factory=list)
    cache_hit: bool = False

    @property
    def needs_review(self) -> bool:
        return not self.prepared


def _vendor_rung(site: str, company_name: Optional[str]):
    """Module-level indirection so tests (and future vendors) swap it whole."""
    from lumen_ingestion.logo_vendor import fetch_vendor_family

    return fetch_vendor_family(site)


def _ladder_rung(site: str, company_name: Optional[str]):
    from lumen_ingestion import logo_ladder

    return asyncio.run(logo_ladder.fetch_logo_family(site, company_name=company_name))


def fetch_logo_family(
    url_or_domain: str,
    *,
    company_name: Optional[str] = None,
    force_refresh: bool = False,
    cache=None,
) -> LogoFetchOutcome:
    """Two-rung dispatch: cache -> Brandfetch -> ladder (per-cell backfill).

    Raises `CaptureError` only from the ladder rung (blocked/unreachable site);
    every vendor failure is a typed degrade recorded in the outcome notes.
    """
    from lumen_ingestion import logo_ladder
    from lumen_ingestion.logo_vendor import VendorCredentialsMissing, VendorLookupFailed

    site = logo_ladder.normalize_site_url(url_or_domain)

    if cache is not None and not force_refresh:
        hit = cache.get(site)
        if hit is not None:
            hit.cache_hit = True
            return hit

    cells: dict = {}
    notes: List[str] = []
    vendor_notes: List[str] = []
    try:
        cells, vendor_notes = _vendor_rung(site, company_name)
    except VendorCredentialsMissing:
        notes.append("vendor rung disabled: no BRANDFETCH_API_KEY configured")
    except VendorLookupFailed as error:
        notes.append(f"vendor rung degraded ({error.code}): {error.message}")

    resolution = None
    missing = [name for name in CELL_NAMES if name not in cells]
    if missing:
        resolution = _ladder_rung(site, company_name)
        for name, cell in ladder_cells(resolution).items():
            if name in missing:
                cells[name] = cell

    outcome = _assemble(cells, resolution, site, company_name, notes, vendor_notes)
    if cache is not None and outcome.prepared:
        cache.put(site, outcome)
    return outcome
```

And `_assemble` (replaces `_prepare`; same hashing/labeling logic, now per cell):

```python
def _assemble(cells, resolution, site, company_name, notes, vendor_notes) -> LogoFetchOutcome:
    from lumen_ingestion import logo_ladder
    from lumen_ingestion.logo_family import CELL_NAMES as _CELLS

    host = logo_ladder.host_of(site)
    label_base = company_name or logo_ladder.registrable_domain(host) or host

    prepared: List[PreparedLogo] = []
    for name in _CELLS:
        cell = cells.get(name)
        if cell is None or not cell.body:
            continue
        import hashlib

        digest = hashlib.sha256(cell.body).hexdigest()
        created_by = "brandfetch" if cell.source == "brandfetch" else "logo_ladder"
        prepared.append(
            PreparedLogo(
                cell=name,
                source=cell.source,
                asset_id=f"asset_ing_{digest[:16]}",
                label=f"{label_base} logo ({name})",
                body=cell.body,
                content_type=cell.content_type,
                provenance={
                    "created_by": created_by,
                    "source_label": "brandfetch" if created_by == "brandfetch" else "website",
                    "confidence": (resolution.confidence if resolution else 0.9),
                },
                source_ref={
                    "kind": "vendor" if created_by == "brandfetch" else "website",
                    "url": cell.origin_url,
                    "captured_at": _now(),
                },
                evidence={"cell": name, "source": cell.source, **cell.evidence},
            )
        )

    all_notes = list(notes)
    if resolution is not None:
        all_notes.extend(resolution.notes)
    if not prepared:
        all_notes.append(
            "no cell cleared both rungs (the vendor had no attributable asset and "
            "the ladder found nothing it could stand behind; a variant is never "
            "synthesized), so nothing was ingested"
        )

    return LogoFetchOutcome(
        status="ok" if prepared else "needs_review",
        site=site,
        company=company_name,
        prepared=prepared,
        cells={p.cell: p.source for p in prepared},
        identity=(
            {
                "passed": resolution.identity.get("passed"),
                "evidence": resolution.identity.get("evidence", [])[:3],
                "reason": resolution.identity.get("reason"),
            }
            if resolution is not None
            else {"passed": bool(prepared), "evidence": [], "reason": None}
        ),
        lockup_completeness=(resolution.lockup_completeness if resolution else "unknown"),
        notes=all_notes,
        vendor_notes=vendor_notes,
        candidates=(
            [c.summary() for c in resolution.ranked[:6]] if resolution is not None else []
        ),
    )
```

`review_payload` gets one line added — after `"notes": outcome.notes[:4],` insert `"vendor_notes": outcome.vendor_notes[:3],`.

- [x] **Step 4: Run the new tests** (`-k dispatch`) — PASS. Then run the whole file; the PRE-EXISTING tool tests (scene/web payload assertions on `slot`) will fail — that is expected and honest; fix them NOW as part of this task if they only touch `PreparedLogo.slot` renames, or mark each `@pytest.mark.xfail(strict=True, reason="cells payload lands in task 10")` when they assert the tool JSON payload shape (Task 10 removes every xfail; the plan's final gate re-runs the file and requires zero xfail marks left).

- [x] **Step 5: Commit**

```bash
git add subsystems/clue-design/apps/agent_runtime/lumen_agent/tools/logo_fetch.py subsystems/clue-design/apps/agent_runtime/tests/test_fetch_logo_tool.py
git commit -m "feat(logo): two-rung dispatch — cache, Brandfetch, per-cell ladder backfill

Vendor-full families skip the site scrape entirely; typed vendor degrades
land in notes; nothing-anywhere stays fail-closed needs_review; cache is a
duck-typed seam (durable impl lands with the migration)."
```

---

### Task 7: The durable family cache (migration + `DurableLogoFamilyCache`)

**Status: DONE 2026-09-02 — commits `16857940d` + tests `dcbcd4b63`; migration `1d09aba87206` (single head; smoke on a throwaway DB; dev DB upgraded additively); controller first-hand review clean. Accepted deviations: jsonb via `clue_design._codec.dump_json/load_json`, timestamps via `iso()` (in-repo conventions). Residual by design: no TTL ⇒ one row per distinct domain per workspace, unbounded (founder decision #4).**

**Files:**
- Create: `alembic/versions/<hash>_design_logo_family_cache.py` (id assigned by `alembic revision -m "design logo family cache"` from the repo ROOT; set `down_revision` to the current single head — run `alembic heads` first and confirm exactly one)
- Create: `subsystems/clue-design/apps/api/lumen_api/agent_logo_family_cache.py`
- Test: `subsystems/clue-design/apps/api/tests/test_logo_family_cache.py` (new)

**Interfaces:**
- Consumes: `DesignBlobStore` (`register(data, *, media_type, source_key) -> str`, `read(sha256) -> bytes`, `custody_states(digests) -> dict[str, CustodyState]`), `HybridRepository`-style bridged SQL (mirror how `agent_account_logos.py` builds its repository), `clue_design.storage.SOURCE_KEY_ASSET`, `logo_fetch.LogoFetchOutcome`/`PreparedLogo`.
- Produces: `DurableLogoFamilyCache(blobs: DesignBlobStore)` with:
  - `get(site: str) -> LogoFetchOutcome | None` — row lookup by `(workspace_id, registrable_domain(site))`; every cell digest custody-probed; **any** non-READABLE digest → the whole family is a miss (honest; the next dispatch refetches and re-puts); bytes read back and a fresh `LogoFetchOutcome` rebuilt (status `"ok"`, `cache_hit` set by the dispatch, prepared entries carrying the stored provenance/evidence verbatim).
  - `put(site: str, outcome: LogoFetchOutcome) -> None` — `blobs.register(...)` per prepared cell (content-addressed upsert, so re-put converges), then UPSERT the row (`ON CONFLICT (workspace_id, registrable_domain) DO UPDATE` — force_refresh overwrite path). Only called with `outcome.prepared` non-empty (the dispatch guards; `put` also no-ops defensively on empty).
  - Failure posture: a cache **read** error degrades to `None` + a logged warning (the fetch path must never die on cache trouble); a cache **write** error is logged and swallowed (the turn already has its family). Same reasoning as the advisory-not-authoritative rules elsewhere: the cache is an optimization, never a gate.

**Migration** (hand-written, reversible, named constraints; raw-SQL style like `86a9ce389e6e`, whose `design_account` uses `workspace_id text NOT NULL` + `FOREIGN KEY (workspace_id) REFERENCES workspace (workspace_id)` — resolved by the controller 2026-09-02):

```python
def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE design_logo_family (
            workspace_id        text        NOT NULL,
            registrable_domain  text        NOT NULL,
            family              jsonb       NOT NULL,
            fetched_at          timestamptz NOT NULL DEFAULT now(),
            refreshed_at        timestamptz,
            CONSTRAINT design_logo_family_pk
                PRIMARY KEY (workspace_id, registrable_domain),
            CONSTRAINT design_logo_family_workspace_fk
                FOREIGN KEY (workspace_id) REFERENCES workspace (workspace_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE design_logo_family")
```

The `family` JSONB holds `{"site", "company", "lockup_completeness", "identity", "notes", "cells": {cell: {"sha256", "content_type", "source", "origin_url", "evidence", "provenance", "source_ref", "label", "asset_id"}}}` — everything `get` needs to rebuild the outcome without re-running either rung.

**Layering (controller ruling 2026-09-02, mirrors how `HybridRepository` delegates to `clue_design.accounts`):** the SQL lives in a new DAL module `subsystems/design/clue_design/logo_family_cache.py` (async functions over `AsyncConnection` using `sqlalchemy.text`, exactly the shape of `clue_design/accounts.py::get_web_account`); the API-side `DurableLogoFamilyCache` calls it through `DesignStoreBridge(self.workspace_id)._run(lambda conn: ...)` (the same bridge `HybridRepository` uses) and does blob custody through `DesignBlobStore.register / custody_states / read`. Mirror how `clue_design/assets.py` binds a jsonb parameter (json.dumps + `CAST(:f AS jsonb)` or its established equivalent — read that file, do not guess).

```python
# subsystems/design/clue_design/logo_family_cache.py
"""``design_logo_family`` DAL — the durable target-logo family cache (vendor-first logo family, Task 7).
Keyed (workspace_id, registrable_domain); workspace-scoped by the row itself, so a foreign
workspace's read is an ordinary miss. No TTL: overwrite (force_refresh) stamps refreshed_at."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

JsonObject = dict[str, Any]


async def get_logo_family(
    conn: AsyncConnection, *, workspace_id: str, registrable_domain: str
) -> JsonObject | None:
    row = (
        await conn.execute(
            text(
                "SELECT family, fetched_at, refreshed_at FROM design_logo_family "
                "WHERE workspace_id = :w AND registrable_domain = :d"
            ),
            {"w": workspace_id, "d": registrable_domain},
        )
    ).first()
    if row is None:
        return None
    family = row.family if isinstance(row.family, dict) else json.loads(row.family)
    return {"family": family, "fetched_at": row.fetched_at, "refreshed_at": row.refreshed_at}


async def upsert_logo_family(
    conn: AsyncConnection, *, workspace_id: str, registrable_domain: str, family: JsonObject
) -> None:
    await conn.execute(
        text(
            "INSERT INTO design_logo_family (workspace_id, registrable_domain, family) "
            "VALUES (:w, :d, CAST(:f AS jsonb)) "
            "ON CONFLICT (workspace_id, registrable_domain) "
            "DO UPDATE SET family = EXCLUDED.family, refreshed_at = now()"
        ),
        {"w": workspace_id, "d": registrable_domain, "f": json.dumps(family)},
    )
```

- [x] **Step 1: Run `alembic heads` from the repo root** with the repo `.env` sourced (`set -a; source .env; set +a`) — it must print ONE id (`6eff96862040` at plan time; if two, STOP — an unmerged parallel branch exists). Set the new migration's `down_revision` to that id.

- [x] **Step 2: Generate the migration** — from repo root: `alembic revision -m "design logo family cache"`; fill in `upgrade()`/`downgrade()` as above with the values from Step 1.

- [x] **Step 3: Gate the migration on a THROWAWAY database — never the workspace dev DB.** `make db-smoke` runs `alembic downgrade base` against whatever `CLUE_DATABASE_URL` names, and the repo `.env` names this workspace's LIVE dev DB (`clue_singapore_v1`, seeded). So, from the repo root:

```bash
PGPASSWORD=clue psql -h localhost -p 55040 -U clue -d postgres -c 'CREATE DATABASE clue_singapore_v1_smoke'
CLUE_DATABASE_URL=postgresql+asyncpg://clue:clue@localhost:55040/clue_singapore_v1_smoke make db-smoke
PGPASSWORD=clue psql -h localhost -p 55040 -U clue -d postgres -c 'DROP DATABASE clue_singapore_v1_smoke'
```
Expected: three alembic runs green (up → down → up), then `alembic heads` prints exactly one id (the new one). ONLY THEN apply the migration to the dev DB additively: `set -a; source .env; set +a; .venv/bin/alembic upgrade head` (upgrade only — never downgrade the dev DB). The API test suite reads that DB.

- [x] **Step 4: Write the failing cache tests**

Fixture pattern (controller-resolved 2026-09-02): the api conftest (`apps/api/tests/conftest.py`) already gives every test an isolated workspace via the autouse `_isolated_design_workspace` (sets `LUMEN_DEV_WORKSPACE_ID`) and a disposable `design_storage` (`FsStorage(tmp_path/...)`); `make_blob_store(app)` builds a `DesignBlobStore` on the app's storage for THIS test's workspace. Build the app the way `apps/api/tests/test_abm_batch_publish.py`'s fixtures (lines ~49–96) do (`create_app(...)` with the injected `design_storage`), and define in this test file:

```python
@pytest.fixture()
def design_blob_store(app):          # `app` = the create_app fixture you mirror from test_abm_batch_publish.py
    from conftest import make_blob_store  # or the import path that file uses
    return make_blob_store(app)


@pytest.fixture()
def other_workspace_blob_store(app):
    import uuid
    from lumen_api.design_store import DesignBlobStore
    return DesignBlobStore(app.state.storage, f"ws_test_other_{uuid.uuid4().hex[:12]}")
```
(`DesignBlobStore(..., ensure_workspace=True)` is the default, so the second workspace row is created on first use.) Tests hit the workspace dev DB named by the repo `.env` — run them with `set -a; source <repo-root>/.env; set +a` in the shell first.

```python
# subsystems/clue-design/apps/api/tests/test_logo_family_cache.py
"""DurableLogoFamilyCache: workspace-scoped get/put, custody-probed reads,
force-refresh overwrite convergence."""

from __future__ import annotations


def _outcome(site="https://acme.com/"):
    from lumen_agent.tools.logo_fetch import LogoFetchOutcome, PreparedLogo

    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" '
        b'viewBox="0 0 10 10"><rect width="10" height="10" fill="#123"/></svg>'
    )
    prepared = PreparedLogo(
        cell="light_lockup", source="brandfetch", asset_id="asset_ing_cafedeadbeef0000",
        label="Acme logo (light_lockup)", body=svg, content_type="image/svg+xml",
        provenance={"created_by": "brandfetch", "source_label": "brandfetch",
                    "confidence": 0.9},
        source_ref={"kind": "vendor", "url": "https://a/x.svg", "captured_at": "t"},
        evidence={"cell": "light_lockup", "source": "brandfetch"},
    )
    return LogoFetchOutcome(status="ok", site=site, company="Acme",
                            prepared=[prepared], cells={"light_lockup": "brandfetch"})


def test_put_then_get_round_trips_the_family(design_blob_store):  # fixture per bind tests
    from lumen_api.agent_logo_family_cache import DurableLogoFamilyCache

    cache = DurableLogoFamilyCache(blobs=design_blob_store)
    cache.put("https://acme.com/", _outcome())
    got = cache.get("https://www.acme.com/pricing")  # registrable-domain keyed
    assert got is not None
    assert got.cells == {"light_lockup": "brandfetch"}
    assert got.prepared[0].body.startswith(b"<svg")
    assert got.prepared[0].provenance["created_by"] == "brandfetch"


def test_get_unknown_domain_is_none_and_put_converges(design_blob_store):
    from lumen_api.agent_logo_family_cache import DurableLogoFamilyCache

    cache = DurableLogoFamilyCache(blobs=design_blob_store)
    assert cache.get("https://nobody.example/") is None
    cache.put("https://acme.com/", _outcome())
    cache.put("https://acme.com/", _outcome())  # idempotent overwrite, no error
    assert cache.get("https://acme.com/") is not None


def test_workspace_isolation_is_fail_closed(design_blob_store, other_workspace_blob_store):
    from lumen_api.agent_logo_family_cache import DurableLogoFamilyCache

    DurableLogoFamilyCache(blobs=design_blob_store).put("https://acme.com/", _outcome())
    foreign = DurableLogoFamilyCache(blobs=other_workspace_blob_store)
    assert foreign.get("https://acme.com/") is None
```

(If `test_web_account_logo_bind.py` has no `other_workspace_blob_store`-style fixture, build one in this test file the same way it builds its primary fixture, with a second workspace id.)

- [x] **Step 5: Run to verify FAIL** — `ModuleNotFoundError: lumen_api.agent_logo_family_cache`.
`PYTHONPATH=.:apps/api:apps/agent_runtime <repo-root>/.venv/bin/python -m pytest apps/api/tests/test_logo_family_cache.py -v`

- [x] **Step 6: Implement `agent_logo_family_cache.py`**

```python
"""The durable target-logo family cache (founder decision #4, 2026-08-31).

Keyed `(workspace_id, registrable_domain)` -- domain, not account id, because
the tool receives a domain and the agent may fetch for companies that are not
accounts (founder ruling 2026-09-02). Workspace-scoped by construction: the
blob store carries the tenant (the `agent_account_logos` rule) and the row
lives under the same workspace, so a cross-tenant read is as unresolvable as
an absent one.

No TTL: the eviction affordance is `force_refresh` on the fetch tool. The
cache is an OPTIMIZATION, never a gate -- every read error degrades to a miss
and every write error is logged and swallowed; the fetch path must never die
on cache trouble.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from py_lumen_obs import get_logger

from clue_design.storage import SOURCE_KEY_ASSET

from .design_store import CustodyState, DesignBlobStore

_logger = get_logger("lumen_api.agent_logo_family_cache")

__all__ = ["DurableLogoFamilyCache"]


class DurableLogoFamilyCache:
    """get/put for one workspace. Duck-typed against the prep layer's seam."""

    def __init__(self, *, blobs: DesignBlobStore) -> None:
        self.blobs = blobs
        self.workspace_id = blobs.workspace_id

    # -- keying ------------------------------------------------------------

    @staticmethod
    def _key(site: str) -> str:
        from lumen_ingestion.logo_ladder import host_of, registrable_domain

        return registrable_domain(host_of(site)) or host_of(site)

    # -- seam --------------------------------------------------------------

    def get(self, site: str):
        try:
            return self._get(site)
        except Exception:  # noqa: BLE001 - a cache read error is a MISS
            _logger.warning("logo_family_cache.read_failed", exc_info=True)
            return None

    def put(self, site: str, outcome: Any) -> None:
        if not getattr(outcome, "prepared", None):
            return
        try:
            self._put(site, outcome)
        except Exception:  # noqa: BLE001 - a cache write error never fails the turn
            _logger.warning("logo_family_cache.write_failed", exc_info=True)

    # -- implementation ----------------------------------------------------
    # `_get`/`_put` use the same bridged-SQL construction as
    # agent_account_logos.DurableAgentAccountLogoBinder._repository (open that
    # file and mirror it): SELECT/UPSERT on design_logo_family, blob custody
    # via self.blobs.register / custody_states / read. `_get` rebuilds a
    # LogoFetchOutcome from the row's `family` JSONB; ANY cell digest whose
    # custody state is not READABLE makes the WHOLE family a miss.
```

`_get`/`_put`, concretely (import `LogoFetchOutcome`/`PreparedLogo` from `lumen_agent.tools.logo_fetch` lazily inside the methods — the API composes agent-runtime types at seams already; `main.py` imports `run_web_agent_turn`):

```python
    def _put(self, site: str, outcome: Any) -> None:
        import hashlib

        from clue_design import logo_family_cache as dal

        from .design_store import DesignStoreBridge

        cells: dict = {}
        for prepared in outcome.prepared:
            sha = hashlib.sha256(prepared.body).hexdigest()
            self.blobs.register(
                prepared.body, media_type=prepared.content_type, source_key=SOURCE_KEY_ASSET
            )
            cells[prepared.cell] = {
                "sha256": sha,
                "content_type": prepared.content_type,
                "source": prepared.source,
                "origin_url": prepared.source_ref.get("url"),
                "evidence": prepared.evidence,
                "provenance": prepared.provenance,
                "source_ref": prepared.source_ref,
                "label": prepared.label,
                "asset_id": prepared.asset_id,
            }
        family = {
            "site": outcome.site,
            "company": outcome.company,
            "lockup_completeness": outcome.lockup_completeness,
            "identity": outcome.identity,
            "notes": list(outcome.notes),
            "cells": cells,
        }
        DesignStoreBridge(self.workspace_id)._run(
            lambda conn: dal.upsert_logo_family(
                conn, workspace_id=self.workspace_id,
                registrable_domain=self._key(site), family=family,
            )
        )

    def _get(self, site: str):
        from clue_design import logo_family_cache as dal
        from lumen_agent.tools.logo_fetch import LogoFetchOutcome, PreparedLogo

        from .design_store import DesignStoreBridge

        row = DesignStoreBridge(self.workspace_id)._run(
            lambda conn: dal.get_logo_family(
                conn, workspace_id=self.workspace_id, registrable_domain=self._key(site)
            )
        )
        if row is None:
            return None
        family = row["family"]
        cells = family.get("cells") or {}
        digests = [c["sha256"] for c in cells.values()]
        states = self.blobs.custody_states(digests)
        if any(states.get(d) is not CustodyState.READABLE for d in digests):
            return None  # any unreadable cell = the WHOLE family is a miss (honest; refetch)
        prepared = [
            PreparedLogo(
                cell=name, source=c["source"], asset_id=c["asset_id"], label=c["label"],
                body=self.blobs.read(c["sha256"]), content_type=c["content_type"],
                provenance=c["provenance"], source_ref=c["source_ref"], evidence=c["evidence"],
            )
            for name, c in cells.items()
        ]
        return LogoFetchOutcome(
            status="ok", site=family["site"], company=family.get("company"),
            prepared=prepared, cells={p.cell: p.source for p in prepared},
            identity=family.get("identity") or {},
            lockup_completeness=family.get("lockup_completeness", "unknown"),
            notes=list(family.get("notes") or []),
        )
```

Add `- Create: \`subsystems/design/clue_design/logo_family_cache.py\`` to this task's Files and to the commit's `git add`.

- [x] **Step 7: Run to verify PASS**, then commit

```bash
git add alembic/versions/*design_logo_family* subsystems/clue-design/apps/api/lumen_api/agent_logo_family_cache.py subsystems/clue-design/apps/api/tests/test_logo_family_cache.py
git commit -m "feat(logo): durable family cache — (workspace, registrable_domain) keyed

Hash-id reversible migration (db-smoke green, one head); custody-probed reads
(any unreadable digest = whole-family miss); read/write errors degrade, never
gate; no TTL — force_refresh is the eviction affordance."
```

---

### Task 8: Widen the bind gate to vendor provenance

**Status: DONE 2026-09-02 — commit `753e1e9d7` (executed before Task 7 to close the vendor-logos-unbindable window); controller first-hand review clean.**

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/agent_account_logos.py` (the `LADDER_PROVENANCE` block + `is_ladder_fetched`)
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/tools/web_substrate.py` (the `is_ladder_fetched` import + the `account_logo.not_a_fetched_logo` refusal text)
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_web_account_logo_bind.py` (extend)

**Interfaces:**
- Consumes: Task 6's provenance stamping (`created_by` ∈ `{"logo_ladder", "brandfetch"}`).
- Produces: `FETCHED_LOGO_PROVENANCES = frozenset({"logo_ladder", "brandfetch"})`; `is_fetched_logo(record) -> bool` (new name; `is_ladder_fetched` kept as a deprecated alias = same function object, so nothing silently breaks); `__all__` updated.

- [x] **Step 1: Write the failing test**

```python
def test_vendor_fetched_records_pass_the_bind_gate_and_generated_ones_do_not():
    from lumen_api.agent_account_logos import is_fetched_logo

    vendor = {"provenance": {"created_by": "brandfetch"}}
    ladder = {"provenance": {"created_by": "logo_ladder"}}
    generated = {"provenance": {"created_by": "image_generation"}}
    assert is_fetched_logo(vendor) and is_fetched_logo(ladder)
    assert not is_fetched_logo(generated)
    # the old name still answers (deprecated alias, same object)
    from lumen_api.agent_account_logos import is_ladder_fetched
    assert is_ladder_fetched is is_fetched_logo
```

- [x] **Step 2: Run to verify FAIL** (`ImportError: is_fetched_logo`):
`... -m pytest apps/agent_runtime/tests/test_web_account_logo_bind.py -v -k vendor_fetched`

- [x] **Step 3: Implement**

In `agent_account_logos.py` replace the `LADDER_PROVENANCE`/`is_ladder_fetched` block:

```python
#: ``provenance.created_by`` values that mean "a real published mark somebody's
#: brand actually serves" — the ladder's site harvest, or the Brandfetch Brand
#: API's keyed retrieval (vendor-first, 2026-09-02). This is what the bind
#: gates on: a generated image is not a company's logo, and neither is a
#: placeholder.
LADDER_PROVENANCE = "logo_ladder"
VENDOR_PROVENANCE = "brandfetch"
FETCHED_LOGO_PROVENANCES = frozenset({LADDER_PROVENANCE, VENDOR_PROVENANCE})


def is_fetched_logo(record: Any) -> bool:
    """True when ``record`` is a mark fetched from the company's own site or
    retrieved from the logo vendor keyed by the company's domain."""
    if not isinstance(record, dict):
        return False
    provenance = record.get("provenance")
    if not isinstance(provenance, dict):
        return False
    return str(provenance.get("created_by") or "") in FETCHED_LOGO_PROVENANCES


#: Deprecated alias (pre-vendor name); same object so identity checks hold.
is_ladder_fetched = is_fetched_logo
```

Update `__all__` to add `"FETCHED_LOGO_PROVENANCES"`, `"VENDOR_PROVENANCE"`, `"is_fetched_logo"`. **Carry-over (Task 6 review):** the `LADDER_PROVENANCE` comment block in this file still names `lumen_agent.tools.logo_fetch._prepare`; Task 6 renamed it `_assemble` — update the mention while rewriting that block. In `web_substrate.py`, switch the import to `is_fetched_logo` and adjust the `account_logo.not_a_fetched_logo` message's first sentence to: `f"'{asset}' was not fetched from that company's own website or logo vendor, so it cannot become their logo."` (rest of the message unchanged).

- [x] **Step 4: Run to verify PASS**, plus the file's existing tests still green:
`... -m pytest apps/agent_runtime/tests/test_web_account_logo_bind.py -v`

- [x] **Step 5: Commit**

```bash
git add subsystems/clue-design/apps/api/lumen_api/agent_account_logos.py subsystems/clue-design/apps/agent_runtime/lumen_agent/tools/web_substrate.py subsystems/clue-design/apps/agent_runtime/tests/test_web_account_logo_bind.py
git commit -m "feat(logo): bind gate accepts vendor provenance

is_fetched_logo({logo_ladder, brandfetch}); generated/placeholder still
refused; old name kept as alias."
```

---

### Task 9: Compose the cache + client id into both lanes' turn config

**Status: DONE 2026-09-02 — commit `8c3d0f3f7`; controller first-hand review clean (composition at `main.py:8519` scene / `:8819` web).**

**Files:**
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/config.py` (beside `account_logo_binder` at ~line 187)
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py` — **controller-resolved seams (2026-09-02):** the SCENE lane's turn config is built inside `run_agent_turn_preview` (def at ~8428; `config = AgentRuntimeConfig.from_env(root)` at ~8502, `turn_blobs` in scope at ~8455) and the WEB lane's inside `run_web_agent_turn` (def at ~8718; `from_env` at ~8806, `turn_blobs` in scope, the `account_logo_binder` replace at ~8872). Compose the cache INSIDE both functions, not at the worker call site (~9857), so both lanes get it from the same `turn_blobs` handle.
- Test: `subsystems/clue-design/apps/api/tests/test_logo_family_cache.py` (extend with a composition assertion) — plus the Task 10 tool tests exercise the seam end-to-end.

**Interfaces:**
- Consumes: `DurableLogoFamilyCache` (Task 7), `_turn_blob_store(host, workspace_id)` (existing).
- Produces: `AgentRuntimeConfig.logo_family_cache: Any | None = None` and `AgentRuntimeConfig.brandfetch_client_id: str | None = None` (populated in `AgentRuntimeConfig.from_env` from `settings.brandfetch_client_id`, blank → `None`); both turn-composition seams pass `logo_family_cache=DurableLogoFamilyCache(blobs=_turn_blob_store(host, workspace_id))`.

- [x] **Step 1: Add the config fields** with comments in the established style:

```python
    # The durable target-logo family cache (founder decision #4, 2026-08-31):
    # `lumen_api.agent_logo_family_cache.DurableLogoFamilyCache`, supplied by the
    # API worker at turn composition like `account_logo_binder`. None -> fetch_logo
    # simply runs the two rungs every call (correct, just slower/costlier).
    logo_family_cache: Any | None = None
    # The PUBLIC Brandfetch Logo-API client id, for the web lane's hotlink prompt
    # guidance (decorative third-party logos). None/blank -> guidance omitted.
    brandfetch_client_id: str | None = None
```

In `from_env`, beside the other settings reads: `brandfetch_client_id=(settings.brandfetch_client_id.strip() or None)`.

- [x] **Step 2: Compose at both seams in `main.py`.** Add the import beside `DurableAgentAccountLogoBinder`'s (~line 69): `from .agent_logo_family_cache import DurableLogoFamilyCache`. Then, in BOTH `run_agent_turn_preview` (scene) and `run_web_agent_turn` (web), directly after the `config = replace(config, asset_store_root=turn_cache_root)` line each function already has (~8515 and ~8812), add one unconditional line:

```python
        # Vendor-first logo family cache (decision #4): per workspace, keyed by registrable
        # domain; the tool degrades to uncached fetching when this is None.
        config = replace(config, logo_family_cache=DurableLogoFamilyCache(blobs=turn_blobs))
```

Both functions already hold `turn_blobs` (a `DesignBlobStore` for the turn's workspace). Nothing changes at the worker call site (~9857). Confirm with `grep -n "logo_family_cache" subsystems/clue-design/apps/api/lumen_api/main.py` → exactly two composition lines + the import.

- [x] **Step 3: Composition test** — append to `test_logo_family_cache.py`:

```python
def test_agent_runtime_config_carries_the_cache_and_client_id_fields():
    from lumen_agent.config import AgentRuntimeConfig
    import dataclasses

    names = {f.name for f in dataclasses.fields(AgentRuntimeConfig)}
    assert "logo_family_cache" in names and "brandfetch_client_id" in names
```

- [x] **Step 4: Run** `... -m pytest apps/api/tests/test_logo_family_cache.py -v` — PASS.

- [x] **Step 5: Commit**

```bash
git add subsystems/clue-design/apps/agent_runtime/lumen_agent/config.py subsystems/clue-design/apps/api/lumen_api/main.py subsystems/clue-design/apps/api/tests/test_logo_family_cache.py
git commit -m "feat(logo): compose the family cache into both lanes' turn config

Same capability seam as account_logo_binder; None = uncached (correct,
just costlier). brandfetch_client_id rides config for the hotlink prompts."
```

---

### Task 10: Both `fetch_logo` tools speak cells (+ `force_refresh`, + cache)

**Status: DONE 2026-09-02 — commit `7f301f62f`; controller first-hand review clean; zero xfail (D5 met); LIVE-verified end to end through the real web tool with the real key and a real durable cache (4 cells ingested, second call a cache hit, bind gate accepts). Errata: `failed_slots` → `failed_cells` (no consumers); "Static fetch only on the ladder fallback" wording; the web payload never had a `next` field.**

**Files:**
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/tools/substrate.py` (`fetch_logo`, ~line 1333)
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/tools/web_substrate.py` (`fetch_logo`, ~line 3309)
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_fetch_logo_tool.py` (update the xfail-marked payload tests; remove every xfail)

**Interfaces:**
- Consumes: Task 6's `fetch_logo_family(url, company_name=..., force_refresh=..., cache=...)` + outcome shape; Task 9's `config.logo_family_cache`.
- Produces (both lanes): tool signature `fetch_logo(self, domain: str, company_name: Optional[str] = None, force_refresh: bool = False) -> str`; success payload now:

```json
{
  "status": "ok",
  "site": "...",
  "identity": {...},
  "lockup_completeness": "...",
  "cache_hit": false,
  "logos": [
    {"cell": "light_lockup", "asset_id": "asset_ing_...", "source": "brandfetch", "...evidence": "..."}
  ],
  "notes": ["..."],
  "next": "Place with ... Match the cell to the placement: *_lockup is the full logo (first choice on any surface that fits it), *_mark is the bare symbol (small placements only). Use dark_* cells on dark surfaces, light_* on light ones."
}
```

Per-lane mechanics unchanged: scene ingests + `upsert_asset` with op key `asset`; web ingests + `_register_asset_record` + custody, with round-budget consumption and `CaptureError` handling exactly as today. **Carry-over (Task 6 ruling):** every `prepared.slot` read in both tools (six sites: `substrate.py` ~1403/1412/1418, `web_substrate.py` ~3385/3393/3400) becomes `prepared.cell` with the dict key `"cell"`, and then the deprecated `slot` alias property on `PreparedLogo` is DELETED in this task (grep `\.slot\b` under `apps/agent_runtime` must return nothing logo-related afterwards). **D5:** remove the one `xfail` on `test_web_fetch_logo_registers_with_the_record_op_key` and rewrite its assertions to cells; `grep -n xfail test_fetch_logo_tool.py` must be empty at completion. Both lanes now pass `cache=getattr(self.config, "logo_family_cache", None)` and `force_refresh=force_refresh` into the prep call, and surface `cache_hit` in the payload. Loop over `outcome.prepared` keys on `prepared.cell` (was `.slot`).

**Docstring updates (both lanes, verbatim contract — the scene docstring KEEPS its full-lockup ruling paragraph, now in cell vocabulary):** returns one asset per FAMILY CELL of a 2×2 — theme (`light_*` = for light backgrounds, `dark_*` = for dark) × completeness (`*_lockup` = the full logo, `*_mark` = the bare symbol). Sourced vendor-first (Brandfetch keyed by domain), in-house ladder fallback per cell; results are cached per workspace+company — pass `force_refresh=True` only when the user says the logo is wrong or outdated, which refetches and replaces the cached family. Scene lane keeps: "In an account-personalized or co-branded design, the OTHER company's logo must be its COMPLETE lockup — the `light_lockup`/`dark_lockup` cell for the surface you are placing on. The bare `*_mark` is a fallback for when the brand publishes no lockup, or the placement is genuinely too small to hold one — never the first choice." Both keep the `needs_review` + never-draw paragraphs verbatim.

- [x] **Step 1: Update the payload tests** — in `test_fetch_logo_tool.py`, remove every `xfail` from Task 6; update assertions from `"slot"` to `"cell"` keys and add, in whichever existing test drives a successful web fetch, `assert payload["logos"][0]["source"] in ("brandfetch", "ladder", "ladder-materialized")` and `assert "cache_hit" in payload`. Add one new test that a tool-level `force_refresh=True` reaches the prep layer (monkeypatch `logo_fetch.fetch_logo_family`, capture kwargs, assert `force_refresh is True` and `cache is config.logo_family_cache`).

- [x] **Step 2: Run to verify FAIL** — the tools still emit `slot`:
`... -m pytest apps/agent_runtime/tests/test_fetch_logo_tool.py -v`

- [x] **Step 3: Update both tools** per the Produces block: signature, the `logo_fetch.fetch_logo_family(...)` call gains `force_refresh=force_refresh, cache=getattr(self.config, "logo_family_cache", None)`; the `placed.append({...})` entries become `{"cell": prepared.cell, "source": prepared.source, "asset_id": ..., **prepared.evidence}`; payload gains `"cache_hit": outcome.cache_hit`; docstrings replaced as specified; the scene payload's `"next"` string updated to the cell wording above.

- [x] **Step 4: Run the whole file** — all PASS, zero xfail remaining:
`... -m pytest apps/agent_runtime/tests/test_fetch_logo_tool.py -v`

- [x] **Step 5: Commit**

```bash
git add subsystems/clue-design/apps/agent_runtime/lumen_agent/tools/substrate.py subsystems/clue-design/apps/agent_runtime/tools/web_substrate.py subsystems/clue-design/apps/agent_runtime/tests/test_fetch_logo_tool.py
git commit -m "feat(logo): both fetch_logo tools speak the 2x2 — cells, sources, cache_hit, force_refresh

Scene keeps the full-lockup ruling in cell vocabulary; per-lane ingest
mechanics untouched."
```

(If `git add` path typo above trips you: the web tool is `subsystems/clue-design/apps/agent_runtime/lumen_agent/tools/web_substrate.py`.)

---

### Task 11: Prompts speak the 2×2 (both lanes)

**STATUS 2026-09-02: DONE** (`aa8b943a3` prose + tests; `6c3748fb6` fix round: wrap, placement hint, unused var). Errata found at execution: (1) the author's `fetch_logo` prose lives inside `account_block`, so the D4 render test passes `account_card="{}"` and a second no-account render asserts only the absence of the old phrase; (2) the orchestrator/reviewer never said "asset ids per slot" — they said "comes only from the ladder", replaced by "comes only from their real published asset — … `fetch_logo` (one asset per family cell: …) binding it"; (3) the scene resource maps' "fetched from their website" → "real published logo, one asset per family cell" (vendor-first made the old wording false); (4) the founder-signed author prose regained one sentence, "The assets are already registered; place them like any other asset." (controller ruling; the scene contract kept its placement hint, the web one had lost it); (5) the brief's unused `text = …__doc__` test line was dropped for the subsystem's ruff gate.

**Files:**
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/prompts_web.py` (orchestrator ~371–380; author ~488–502; reviewer ~681–687)
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/prompts.py` (scene prompt's fetch_logo mention — grep `fetch_logo` in the file for the exact block)
- Modify (D7): `subsystems/clue-design/apps/agent_runtime/knowledge_docs/knowledge/web/abm-page.md` lines ~57–58 — replace the "one id per slot (`light`, `dark` …)" sentence with the 2×2 cell vocabulary (same voice as the author-prompt prose below); `grep -rn "per slot" apps/agent_runtime/knowledge_docs` must be empty afterwards.
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_prompts_logo_cells.py` (new, small)

**Interfaces:** consumes nothing new; prose-only. The exact replacement prose (founder reviews it as part of this plan — the standing skill/prompt-review rule is satisfied by plan sign-off):

Author prompt (~488–502), replace the slot sentences with:

```
- If the account card carries no logo asset, get their real one with
  `fetch_logo("theirdomain.com")`. It returns one asset per family CELL —
  a 2×2 of theme × completeness: `light_lockup`, `dark_lockup`,
  `light_mark`, `dark_mark`. `light_*` cells are FOR light surfaces,
  `dark_*` cells FOR dark surfaces; `*_lockup` is the complete logo
  (symbol + name — the first choice wherever it fits), `*_mark` is the
  bare symbol (small placements only). An empty cell means the brand
  publishes nothing for it — that is a real answer; never fill it by
  recoloring another cell. Results are cached for this company; pass
  `force_refresh=True` only when the user says the logo is wrong or
  outdated. If it comes back `needs_review`, say so and ask for the
  file. Never draw, recolour, letter or approximate someone's logo.
```

Orchestrator (~371–380) and reviewer (~681–687): change only the vocabulary words — where the text says "asset ids per slot — `light`, ..." it becomes "one asset per family cell (`light_lockup`, `dark_lockup`, `light_mark`, `dark_mark`)"; the EMPTY-IS-CORRECT and bind-once-per-account sentences stay verbatim. Scene prompt: same vocabulary swap in its fetch_logo mention.

- [ ] **Step 1: Write the failing test**

```python
# subsystems/clue-design/apps/agent_runtime/tests/test_prompts_logo_cells.py
"""The prompts and the tools agree on the 2x2 vocabulary."""


def test_web_prompts_name_the_four_cells_and_never_the_old_slots():
    from lumen_agent import prompts_web

    text = prompts_web.build_web_author_prompt.__doc__ or ""
    # Assert against the SOURCE, not a rendered prompt (rendering needs a full
    # config): the vocabulary must appear in the module.
    import inspect

    source = inspect.getsource(prompts_web)
    for cell in ("light_lockup", "dark_lockup", "light_mark", "dark_mark"):
        assert cell in source
    assert "asset ids per slot" not in source


def test_scene_prompts_name_the_cells():
    import inspect

    from lumen_agent import prompts

    source = inspect.getsource(prompts)
    assert "light_lockup" in source


def test_rendered_web_author_prompt_names_the_cells():
    # D4: the SOURCE assertions above prove the words exist; this proves they REACH the
    # agent. Same render call `test_web_account_logo_bind.py::_author_prompt` uses.
    from lumen_agent.prompts_web import build_web_author_prompt

    rendered = build_web_author_prompt(brand_card="{}", theme_token_names="brand, ink")
    for cell in ("light_lockup", "dark_lockup", "light_mark", "dark_mark"):
        assert cell in rendered
    assert "asset ids per slot" not in rendered
```

(Controller correction 2026-09-02: there is no `prompt_of` fixture — `test_web_account_logo_bind.py` parametrizes over two local helpers, `_director_prompt()` and `_author_prompt()`; the test above inlines the author helper's exact call. If `build_web_author_prompt`'s signature has changed since, mirror `_author_prompt` in that file verbatim.)

- [ ] **Step 2: FAIL** → **Step 3: apply the prose** → **Step 4: PASS**
`... -m pytest apps/agent_runtime/tests/test_prompts_logo_cells.py -v`

- [ ] **Step 5: Commit**

```bash
git add subsystems/clue-design/apps/agent_runtime/lumen_agent/prompts_web.py subsystems/clue-design/apps/agent_runtime/lumen_agent/prompts.py subsystems/clue-design/apps/agent_runtime/tests/test_prompts_logo_cells.py
git commit -m "feat(logo): prompts speak the 2x2 cell vocabulary

Empty-is-correct and bind-once rules verbatim; only the slot words moved."
```

---

### Task 12: The hotlink lane (web prompts, conditional on client id)

**STATUS 2026-09-02: DONE** (`598ac2d64`). Execution notes: the block renders in the GENERAL author prompt (outside `account_block`, immediately after it) because logo walls / integration strips are landing-page sections too (controller ruling); threaded as a `brandfetch_client_id` kwarg from the single call site in `harness_web.py`; the CDN prefix lives in a module constant only so the source line fits the 100-char lint limit (the rendered URL is unbroken); four rendered-prompt tests plus the brief's source test.

**Files:**
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/prompts_web.py` (author prompt; a new conditional block beside the Task 11 prose)
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_prompts_logo_cells.py` (extend)

**Interfaces:**
- Consumes: `config.brandfetch_client_id` (Task 9). Find how `build_web_author_prompt(...)` receives config/account context (read its signature at `prompts_web.py:472`) and thread `brandfetch_client_id` the same way its neighbors arrive; the block renders ONLY when the id is truthy.
- Produces: prompt prose (verbatim):

```
- DECORATIVE third-party logos — a customer logo wall, an integration grid,
  a partner strip, any place the page merely SHOWS other companies — do not
  need fetch_logo. Write a hotlink image straight into the markup:
    <img src="https://cdn.brandfetch.io/domain/THEIR-DOMAIN/theme/dark/fallback/transparent/type/logo?c={client_id}" alt="THEIR-NAME logo">
  The `theme` segment names the ASSET's own coloring, not the surface: on a
  LIGHT surface use `theme/dark` (dark-colored art); on a DARK surface use
  `theme/light`. Use `type/symbol` where only the bare mark fits.
  `fallback/transparent` makes a missing logo render as nothing — never a
  broken image. This is ONLY for ambient, decorative logos: the account
  being personalized, and anything bound with `bind_account_logo` or
  resolved by `{{account.logo}}`, always uses fetch_logo's registered
  assets, never a hotlink.
```

(`{client_id}` is interpolated at prompt build; the CDN theme segment uses VENDOR semantics on purpose and the prose says so explicitly — this is the one place agents see Brandfetch's convention, so it is spelled out in placement terms.)

- [ ] **Step 1: Write the failing tests**

```python
def test_hotlink_guidance_appears_only_with_a_client_id():
    import inspect

    from lumen_agent import prompts_web

    source = inspect.getsource(prompts_web)
    assert "cdn.brandfetch.io" in source
    assert "fallback/transparent" in source
    # the conditional: the block must be guarded on the client id being set
    assert "brandfetch_client_id" in source
```

Plus a rendered-prompt test if `build_web_author_prompt` is cheaply callable with the existing test fixtures (mirror how existing prompt tests in the suite build one — grep `build_web_author_prompt(` under `apps/agent_runtime/tests/`); assert the URL appears when the id is set and is absent when `None`.

- [ ] **Step 2: FAIL** → **Step 3: implement** (conditional block + threading) → **Step 4: PASS**

- [ ] **Step 5: Commit**

```bash
git add subsystems/clue-design/apps/agent_runtime/lumen_agent/prompts_web.py subsystems/clue-design/apps/agent_runtime/tests/test_prompts_logo_cells.py
git commit -m "feat(logo): hotlink lane — decorative third-party logos via Logo API CDN

Prompt-only; renders only when BRANDFETCH_CLIENT_ID is set; vendor theme
semantics spelled out in placement terms; account.logo stays custody-only."
```

---

### Task 13: Hotlink render verification (empirical check — headless contexts)

**STATUS 2026-09-02: DONE** (throwaway `.context/hotlink_check.py`, three byte-identical runs; results in the ledger and in `_memory/2026-09-02-logo-vendor-build.md` at Task 14). Findings: the guard is a **User-Agent** check, not Referer — headless chromium (served page, `set_content`, sandboxed `srcdoc` iframe) is refused with `x-bf-error: automated_traffic` (302; `fallback/404` is never consulted), headed chromium and a no-Referer `httpx` GET with a browser UA are served. Step 3's caveat sentence was amended to what was measured: "Automated renders (the page thumbnail, the reviewer's render) may show a hotlinked logo as empty; it renders in the editor preview and on the published page." (the plan's "in the editor preview" wording was false — the human's editor is a headed real Chrome). UA spoofing NOT applied — D11.

**Files:** none committed (throwaway script under the gitignored `.context/`); result recorded in `_memory/`.

This answers the one open empirical question: do the editor preview and the review-gate's Playwright renders pass Brandfetch's hotlink guards (`Referer` required; `automated_traffic` heuristics), or do hotlinked logos render only on real published pages?

- [ ] **Step 1:** Obtain a real client id (founder registers at `https://developers.brandfetch.com/register` if not already done; the id goes in `.env` as `BRANDFETCH_CLIENT_ID=...`).
- [ ] **Step 2:** Write `.context/hotlink_check.py`: serve one HTML page on `localhost` containing `<img src="https://cdn.brandfetch.io/domain/brandfetch.com/fallback/404/type/logo?c=<id>">` (using `fallback/404` so a refusal is unambiguous — a 200 means served, a 404/302 means refused); load it with the repo's installed Playwright chromium headless AND headed; log the image response status via `page.on("response")`.
- [ ] **Step 3:** Run and record the outcome (status per context) in `_memory/2026-09-02-logo-vendor-build.md` (the build session note). If headless is REFUSED: the hotlink lane still ships (published pages are real browsers), but add one sentence to the Task 12 prompt block — "In the editor preview a hotlinked logo may show as empty; it renders on the published page." — and note the caveat in the memory file.
- [ ] **Step 4:** No commit unless the prompt sentence was added (then amend prompts + its test string and commit with `docs(logo): editor-preview caveat for hotlinked logos`).

---

### Task 14: Integration pass, full gates, close-out

**STATUS 2026-09-02: DONE.** Errata found at execution: Step 2's single pytest command cannot run (D12) — the gate is two invocations (105 api + 47 agent_runtime = 152 passed); Step 2a's one starlette entry left three third-party `pymupdf` SWIG DeprecationWarnings, ruled a second message-targeted entry; Step 3's `make db-smoke` ran ONLY on a throwaway `clue_singapore_v1_smoke` DB (created/dropped in the step; dev DB untouched, still at head `1d09aba87206`, one head); the full suites run in the background and their results land in the close-out note's §5.

**Files:**
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_fetch_logo_tool.py` (one true end-to-end addition)
- Modify: `_memory/2026-08-31-logo-vendor-first-decision.md` (status header only)
- Create: `_memory/2026-09-02-logo-vendor-build.md` (close-out note)

- [ ] **Step 1: End-to-end tool test** — in `test_fetch_logo_tool.py`, add one test that goes through the WEB tool with the vendor mocked at the httpx layer (monkeypatch `logo_fetch._vendor_rung` to call the real `fetch_vendor_family` with an `httpx.MockTransport` client serving `BRAND_PAYLOAD`-shaped JSON + asset bytes) and the ladder mocked at its driver seam (the file's existing pattern): assert the payload carries mixed sources when the vendor covers two cells and the ladder two, and that every ingested record's `provenance.created_by` matches its cell's source.

- [ ] **Step 2: Focused gates** — run, in order, each green:

```
PYTHONPATH=.:apps/api:apps/agent_runtime <repo-root>/.venv/bin/python -m pytest \
  apps/api/tests/test_logo_vendor.py \
  apps/api/tests/test_logo_family_cache.py \
  apps/api/tests/test_logo_ladder.py \
  apps/api/tests/test_ingestion_logo_family.py \
  apps/api/tests/test_logo_policy.py \
  apps/agent_runtime/tests/test_fetch_logo_tool.py \
  apps/agent_runtime/tests/test_web_account_logo_bind.py \
  apps/agent_runtime/tests/test_prompts_logo_cells.py -v
```

(`test_logo_ladder.py`, `test_ingestion_logo_family.py`, `test_logo_policy.py` must be untouched-green — they prove the do-not-touch constraint held.)

- [ ] **Step 2a (D1): make the focused gate warning-free** — the shared conftest's `fastapi.testclient` import raises one `StarletteDeprecationWarning` ("Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead"). Add ONE targeted `filterwarnings` entry to the pytest config that governs `apps/api/tests` (the `configfile` pytest prints at the top of its run — `pyproject.toml` at the repo root, `[tool.pytest.ini_options]`), of the form `"ignore:Using `httpx` with `starlette.testclient`:DeprecationWarning:fastapi.testclient"` (adjust the category to the exact class the run prints if it is not a `DeprecationWarning` subclass — read it off the warning summary). Re-run the Step 2 command: `N passed` with NO warnings summary. Commit separately: `chore(tests): silence the pre-existing starlette testclient deprecation in the api suite`.

- [ ] **Step 3: Background full runs** — kick off `pytest apps/agent_runtime/tests` and `pytest apps/api/tests` in the background (never synchronously — the >1h rule); collect results before declaring done. Also re-run `alembic heads` (one head) and `make db-smoke` once more from the repo root.

- [ ] **Step 4: Close out the record** — edit the status header of `_memory/2026-08-31-logo-vendor-first-decision.md` from "DECIDED, not yet built" to "BUILT — see `docs/superpowers/plans/2026-09-02-vendor-first-logo-family.md` and `_memory/2026-09-02-logo-vendor-build.md` (2026-09-XX)". Write the build close-out note (`_memory/2026-09-02-logo-vendor-build.md`): what shipped per task, the Task 13 empirical result, deviations from this plan, and the deferred markers (batch-time slot selection consumes `CELL_NAMES`; the free-tier quota ceiling and where the 429 degrade note surfaces).

- [ ] **Step 5: Final commit**

```bash
git add subsystems/clue-design/apps/agent_runtime/tests/test_fetch_logo_tool.py _memory/2026-08-31-logo-vendor-first-decision.md _memory/2026-09-02-logo-vendor-build.md
git commit -m "test(logo): end-to-end mixed-provenance family; close out the vendor-first build

Focused gates green; ladder/ingestion/policy suites untouched-green;
db-smoke green with one head; decision record marked BUILT."
```

---

### Task 15: QA-render User-Agent override behind a flag (founder decision 2026-09-02; resolves D11)

**STATUS 2026-09-02: DONE** (`7f0b7ecd5`). Founder ruling after the D11 evidence: the two automated QA renderers — the page thumbnail (`document_thumbnails.web_thumbnail_png`) and the clone-review walk (`clone_review/browser.py::_open`) — present a normal Chrome User-Agent so hotlinked Brandfetch logos render for review, behind `LUMEN_QA_RENDER_UA_OVERRIDE` (settings field `lumen_qa_render_ua_override: bool = True`; `0` restores the headless UA). The constant and the call-time helper live in `apps/api/lumen_api/qa_render_ua.py`, whose docstring carries the decision, the date, and the vendor's own guideline text. Applied at exactly those two `new_context` calls; never the editor, never publish, never `fragments/isolation.py`. Env parity: the line and its comment sit under `LUMEN_RENDER_STEALTH=1` in both `.env.example` files and in the local `.env`. The hotlink prompt caveat was reworded to stay true in both flag states. Tests: flag default/off loads from env; helper on/off; both call sites pin the kwarg against recording fakes (`test_qa_render_ua.py`, 9 tests). Controller in-situ proof on the shipped code: flag on → CDN 200 and the logo paints in both renderers; flag off → 302 `automated_traffic`.

### Task 16: the ladder fetches with a Chrome TLS fingerprint (founder decision 2026-09-02)

**STATUS 2026-09-02: DONE** (`e3164d6e6`). Cloudflare-walled sites refuse the ladder's plain httpx client at the TLS/HTTP2 layer regardless of User-Agent (openai.com → 403 → `LUMI0503` → the tool reports blocked). The ladder's OWNED client is now `capture/impersonate.py::ImpersonatingClient` — `curl_cffi` with `impersonate="chrome"` (scrapling's engine; the same call the platform's Stage-0 scrapling page fetcher makes), duck-compatible with the slice of `httpx.AsyncClient` that `BoundedFetcher` reads, so the SSRF guard, the per-hop redirect re-guard and the size caps are unchanged — behind `LUMEN_LADDER_IMPERSONATE_CHROME` (settings `lumen_ladder_impersonate_chrome: bool = True`; `0` restores httpx). Our `lumen-ingestion/1` User-Agent is dropped in that lane on purpose (fingerprint coherence). Only the ladder uses it; `capture/evidence_builder.py` and `capture/net.py` are untouched. Env parity in both `.env.example` files and `.env`. Tests: settings on/off; the client against a loopback server (status, headers, redirect no-follow/follow, bytes, 404, the UA it presents); `BoundedFetcher` over the client; transport selection by flag. Live (controller): openai.com flag on → `ok` with two ladder cells; flag off → 403. Deferred: D16.

### Task 17: both sources propose, one arbiter picks per cell (founder decision 2026-09-02; supersedes §0.5)

**STATUS 2026-09-02: DONE** (`9662fb285`). The freshcontext.ai case: Brandfetch's single asset (the short "f(c)" form, labelled `theme=light` → our `dark_lockup`) is dark-brown art that vanishes on a dark surface, and vendor-first let it keep the cell while the site's real on-dark SVG was discarded; inside the ladder the header's short form beat the complete 1162×571 wordmark because the wordmark slot was only a fallback. Now: `ladder_candidates` (replaces `ladder_cells`) proposes every slot, the wordmark competing for `light_lockup`; the dispatch always runs the ladder (Task 16's blocked-ladder contract kept: a vendor-only family stands when the site 403s), pools both sources per cell, and `logo_arbiter.choose_cells` ranks by `(proven ink for the surface, completeness, svg, pixel area, vendor-on-ties)`, with `PROVEN_VERDICTS` asymmetric on purpose (`dark`: dark_variant/adaptive only; `light`: also `unknown`). Winners carry `measured_verdict` and `arbitration.beat`; notes say why a vendor asset lost or why an unverified one was kept. Tool docstrings updated; prompts unchanged (they never named vendor-first). Tests: pure arbiter suite; the freshcontext replay at dispatch level; the converted fold tests. Live: freshcontext.ai → wordmark.png / wordmark-ondark.svg / apple-icon; brandfetch.com → four proven vendor SVGs with the ladder 403-blocked. Cost accepted by the founder: one site scrape per uncached company even when the vendor is complete.

### Task 18: the 2×2 stays the recommendation; every other vetted asset is an alternative (founder decision 2026-09-02)

**STATUS 2026-09-02: DONE** (`8da597f58` + fix `7ef959d4c`). The arbiter can prove ink and identity, not whether a vendor "logo" is complete or whether a short form fits a placement (workspan.com's vendor "logo" is the bare W symbol and holds `dark_lockup`; freshcontext's short form lost `light_lockup` and vanished). Founder ruling with three agreed constraints — vetted assets only (arbitration losers from either source + the vendor's `icon`/`other` types; never the ladder's raw ranked list), the cells stay the default and the prompts say so, notes short and factual. Shipped: `map_vendor_assets_to_cells`/`fetch_vendor_family` return `(cells, extras, notes)` (icon/other and same-cell duplicates are downloaded, gated and kept as extras); `choose_cells` returns `(chosen, alternatives, notes)` with `competed_for`/`lost_to`/`reason` on every loser; the dispatch pools losers + extras, measures every alternative's ink (`measured_verdict`), dedups by content-addressed asset id, and `_assemble` prepares them; both tools ingest and register them (web custody covers them; `bind_account_logo` accepts them) and list them under `alternatives` (`failed_alternatives` when any); the durable cache stores them and treats a missing alternative blob as a whole-family miss; one plain sentence in the author prompt, the scene contract, the knowledge doc and both tool docstrings ("use a cell first; an alternative only when the cell does not fit the placement — say so"). `needs_review` stays fail-closed (nothing registered). Live: workspan.com → 3 cells + 15 alternatives (the vendor's monochrome lockup variants in both inks, now with measured verdicts); freshcontext.ai → 3 cells + the two short forms. Residual (founder-visible, not capped by ruling): a vendor record rich in `other` assets makes a long list.

## Self-review (performed at plan-writing time)

- **Spec coverage:** §0.1 → Tasks 4, 6; §0.2 → Tasks 2, 10, 11; §0.3 → Task 3 (pinned test); §0.4 → Task 3; §0.5 → Tasks 5, 6; §0.6 → Tasks 6, 7, 9, 10; §0.7 → Tasks 12, 13; §0.8 → no task creates any discovery-time path (constraint, verified by the file map); §0.9 → renderability gate in Task 3 only, no other gates added; §0.10 → Task 8. Advisory eviction note → `force_refresh` in Tasks 6, 10, 11. Env parity → Task 1. All four open items from the 2026-08-31 record are owned: vendor chosen (§0.1), config keys (Task 1), cache shape (Task 7), two-rung dispatch inside the shared prep (Task 6).
- **Type consistency:** `FamilyCell(cell, body, content_type, source, origin_url, evidence)` used identically in Tasks 2, 3, 5, 6; `fetch_vendor_family -> (cells, notes)` consistent in Tasks 4, 6; `PreparedLogo.cell`/`.source`/`.source_ref` consistent in Tasks 6, 7, 10; cache seam `get(site) -> LogoFetchOutcome | None` / `put(site, outcome)` consistent in Tasks 6, 7, 9.
- **Known intentional roughness:** Task 7's `_get`/`_put` bodies and the migration's two `<same as design_account>` values are lookups against named in-tree files (`86a9ce389e6e`, `agent_account_logos.py`), not open design decisions; Task 12's prompt-threading step names the exact function and line to read first. Executors must read those files before writing.
