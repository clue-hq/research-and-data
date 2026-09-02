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
| 14 | `193ba27e3`, `426a28a20`, and this note's commit | Suite-wide vendor guard (D9), the end-to-end mixed-provenance test, the warnings filter (D1), the gates, and this record. |

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
  has no __module__ attribute`) still print in both suites' warnings summary, raised at
  `logo_ladder._rasterize`'s lazy `import pymupdf` on Python 3.12. Third-party, pre-existing, and out
  of scope for D1 (which named exactly the starlette filter).

## 5. Full-suite results

*(filled by the controller-provided results)*

Background runs launched from `subsystems/clue-design` with the env prefix in §6 and
`-p no:cacheprovider -q -rf`: `/tmp/t14_agent_runtime_suite.log`, `/tmp/t14_api_suite.log`.

Baseline to triage against (D10, resolved 2026-09-02): on the prepared worktree
`apps/agent_runtime/tests` was fully GREEN, and `apps/api/tests` left **28 distinct failing tests**
(custom-component compiler/publish/runtime, image-model w14/w17, asset-store serving, grammar audit,
web-turn composition) — the SAME 28 fail at the pre-batch commit `b46b8c815` in a clean temporary
worktree with an identical environment. Those are environment/config debt, not this plan's.

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

Two invocations, not one — see the `conftest` collision in §4.

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
