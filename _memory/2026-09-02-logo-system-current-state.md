# Logo fetching — current-state map (singapore-v1 worktree, 2026-09-02)

> **Plan formalized:** `docs/superpowers/plans/2026-09-02-vendor-first-logo-family.md`
> (14 tasks, TDD, founder-approved shape). Execute with subagent-driven-development
> or executing-plans; the plan is self-contained (§0 restates every ruling).

**Session scope: understanding only, no code changes.** This worktree is for the
vendor-first logo robustness work (decision record:
`_memory/2026-08-31-logo-vendor-first-decision.md`; target branch
`origin/platform/pilot-budget-controls`). The attached chat transcript
(`.context/attachments/jld1hI/Transcript of Discuss Logo Vendor.md`) never landed on disk
in any workspace — proceeded from the memory doc alone; ask the founder to re-attach if
its details matter.

## The ladder core — `subsystems/clue-design/apps/api/lumen_ingestion/logo_ladder.py` (~2,740 lines)

Two PURE stages + one network driver (the only impure entry point):

- **Stage 1 `harvest(tree, page_url, stylesheets)`** — pulls candidates from 13 rungs
  (`NAV_VISIBLE, HEADER, INLINE_SVG, BRAND_PAGE, PAGE_LOGO_NAMED, JSONLD_ORG, FOOTER,
  CSS_BG, MANIFEST_ICON, APPLE_TOUCH, OG_LOGO, OG_IMAGE, FAVICON`). Fetches nothing;
  caller supplies bytes via `attach_bytes` (a failed fetch is recorded as `fetch_error`,
  candidate never silently dropped). `repair_svg_case` fixes HTML-parser-lowercased SVG
  attrs + injects width/height/xmlns.
- **Stage 2 `resolve(candidates, page_meta, domain, company_name)`** — appearance
  (light/dark/adaptive from fills or pixels; photographic detection), lockup
  classification (symbol/wordmark/full_lockup via rasterized ink-column gap analysis,
  PIL+pymupdf), scoring (rung base 24–100; not-first-party −200, partner link −80,
  junk tokens, inline-svg-without-brand-evidence −55, etc.), then slot filling for
  `light/dark/mark/wordmark`. Two hard guards, both from live incidents:
  1. **Asset-level identity anchoring** (`identity_anchor` → `slot_eligible`): no
     positive evidence "this is THIS brand's mark" → ineligible for every slot (AWS
     logo-as-WorkSpan's; 19×19 OpenAI glyph as apollo.io's reversed primary).
     Ineligible, not down-scored — penalties proved insufficient twice.
  2. **Never synthesize**: a variant is a real published asset, or a `currentColor`
     SVG materialized ONLY in an ink the site's own CSS was observed painting
     (`materialize_adaptive`; unobserved ink → slot honestly absent).
  Identity check fail → fail-closed: zero winners, `needs_review`, ranked list kept.
  `confidence` measures evidence quantity, never correctness.
- **Driver `fetch_logo_family` (async, bottom of file)** — static tier ONLY (no
  Playwright: ~30s > a turn budget; JS-shell pages come back honestly empty, noted).
  Homepage + ≤12 stylesheets + ≤2 first-party brand/press pages, everything through
  the shared SSRF/redirect/15MB guard (`capture.net.BoundedFetcher`).
- `svg_is_renderable(blob)` — shared "can this SVG paint standalone?" predicate
  (intrinsic geometry AND a drawable element; the 124-byte external-sprite `<use>`
  incident).

## Use #1 — brand-kit WEBSITE INGESTION (seller's own kit)

`run_website_ingestion` (`lumen_ingestion/pipeline.py`, driven on the `design_job`
fleet by `lumen_api.main.execute_ingestion_job`) → capture →
`capture/evidence_builder.py::_ladder_logos` (line ~477) runs harvest+resolve over the
already-captured snapshot (here the RENDERED tier can be available, unlike the agent
tool) and emits `LogoEvidence` per slot → `normalizer.emit.BrandKitBuilder.add_logos`
→ kit logo slots. Slot mapping `_SLOT_ORDER`: light→primary (first, becomes
`logo.primary`), dark→primary reversed variant, mark→mark, wordmark→wordmark; dark
plate from ladder theme surfaces else `#121212`. `capture/candidates.py` calls
`logo_ladder.candidate_asset_urls` so the static collector pre-downloads every ladder
candidate (fetch-everything invariant). Non-resolved → `LUMI0510` warning diagnostic
with top-5 candidates (no silent drop). `logo_policy.py` (allowed_backgrounds rule) is
shared between this ingestion path and human curation `POST /brand-kits/{id}/logo`.

## Use #2 — the `fetch_logo` TOOL (target-account logos, design time)

Shared prep layer: `apps/agent_runtime/lumen_agent/tools/logo_fetch.py::fetch_logo_family`
(blocking `asyncio.run` wrapper) → `PreparedLogo` per slot, content-addressed
`asset_id=asset_ing_<sha16>`, tags `("target-account","logo-ladder")`, provenance
`created_by="logo_ladder"` (THE marker `is_ladder_fetched` gates on). `needs_review` →
`review_payload` ("ask for the file; never draw/recolor/approximate").

- **Scene lane** `tools/substrate.py::fetch_logo` (~1333), registered `harness.py:460`.
  Ingests slots via `core.ingest_asset` + scene `upsert_asset`. Its DOCSTRING carries
  the founder's full-lockup ruling (complete lockup first; bare mark only as fallback)
  — scene-substrate-only, per the 2026-08-31 record.
- **Web lane** `tools/web_substrate.py::fetch_logo` (~3309) — same + round-budget
  consumption + custody registration; plus `bind_account_logo` (~3434) → binder.
  Both tools are on author AND generic subagents (`harness_web.py:295,405` — F4 fix).
- **Account binding (web only)** `lumen_api/agent_account_logos.py::
  DurableAgentAccountLogoBinder`, composed per web turn at `main.py:~9857`. One
  `bind()`: G1 `design_register_asset_record` + G2 `design_update_web_account`
  (`design_account.logo_asset_id` — the single column `{{account.logo}}` reads at
  derive). Doors in order: workspace-scoped account lookup (B3), usable record
  (id+digest), custody write + READABLE probe (bytes before stamp), `svg_is_renderable`
  on SVG mimes (fail-closed even on read errors), governed-tools-only writes, convergent
  re-bind. Only `is_ladder_fetched` records may bind. Scene lane has NO account binding.
- Prompt steering (`prompts_web.py` ~371–502): target logo only from ladder/marker,
  empty logo CORRECT, bind once per named account, `data-slot="account.logo"`.

## Gaps the vendor-first work addresses (confirmed in code)

- Agent-tool path is static-tier, homepage-bounded → accuracy ceiling; slot
  classification heuristic on top.
- NO caching on the tool path: every `fetch_logo` re-fetches the site (content-addressed
  asset id only dedupes ingestion, not network). Decision wants blob cache keyed
  workspace+account, very high TTL, + `force_refresh` eviction affordance.
- Vendor rung doesn't exist yet; wire two-rung dispatch INSIDE
  `logo_fetch.fetch_logo_family` (the shared prep) so both lanes inherit with zero
  harness changes. Template: PDL company-identity resolver pattern (env-keyed creds,
  typed missing-credential error, honest degrade to ladder, result stamps source).
- Known asymmetries NOT to "fix" without founder say-so: full-lockup ruling text
  scene-only; `svg_is_renderable` guards only the web bind door (not scene ingest, not
  the ingestion kit path).

## Founder rulings this session (2026-09-02)

1. **2×2 is the tool contract**: theme (light/dark) × completeness (mark / lockup) =
   four family cells the deepagent receives in one `fetch_logo` call and reasons over.
   Chosen explicitly because it is the same model the deferred batch-time
   slot-selection rule needs.
2. **Vendor = Brandfetch.** Founder linked the Logo API docs; research below shows the
   Brand API is the compliant product for our architecture.
3. **Cache confirmed**: workspace+account-keyed blob cache, very high TTL; first
   design-time fetch stores the family; repeat calls hit cache, not vendor.
4. Re-confirmed: NO fetch/bind at account discovery/enrichment; deepagent may call
   `fetch_logo` for any company at any time; account binding stays a separate
   deliberate act.

## Brandfetch research (docs scraped 2026-09-02, in `.firecrawl/`)

- **Logo API (cdn.brandfetch.io) is hotlink-only and FORBIDS our use**: usage
  guidelines require direct `<img>` embedding with Referer; "Programmatic access to
  logo images is not permitted"; the `automated_traffic` check 302s even a
  valid-client-ID curl; server-side caching requires a custom sales agreement. Our
  architecture (server-side fetch → durable blob custody → serve from our storage) is
  exactly what it blocks. Do NOT build on it.
- **Brand API (api.brandfetch.io/v2/brands/domain/{domain}, Bearer key) is the right
  rung**: programmatic by design; ONE call returns the full `logos[]` array — per
  entry: `theme` (dark/light/null), `type` (icon/logo/symbol/other), `tags`
  (photographic/portrait warnings), `formats[]` (svg/webp/png/jpeg with `src`,
  width/height, byte size, `background: transparent|null`). Also returns colors/fonts
  (out of scope now). Quotas: 100 free dev requests; paid plans + overage billing
  (spending cap settable, $0 disables overage); quota headers
  `x-api-key-quota`/`x-api-key-approximate-usage`; 429 on exhaustion; ~100 rps
  throughput. `brandfetch.com` lookups are free for integration testing. With
  per-account-once caching, usage ≈ distinct target accounts.
- **THEME SEMANTICS ARE INVERTED vs our ladder slots** (critical mapping trap):
  Brandfetch labels the asset's own appearance — `theme=dark` = dark-colored logo FOR
  LIGHT backgrounds (→ our `light` slot); `theme=light` = light/white logo FOR DARK
  backgrounds (→ our `dark` slot). The mapping must invert or every theme pairing
  ships backwards.
- 2×2 mapping proposal: lockup ← `type=logo`; mark ← `type=symbol` (icon is the
  social-avatar-on-a-plate, weaker; whether icon may backfill an empty mark cell =
  open founder question). `theme=null` entries need a classification decision
  (ladder's `analyze_appearance` is reusable for that).
- Open sub-questions taken to founder: (i) Brand API = paid product, confirm; (ii)
  icon-as-mark backfill allowed?; (iii) fallback granularity — family-level
  (vendor answered at all → vendor family, else ladder) vs per-cell merge.

## Founder rulings, round 2 (2026-09-02, same session)

- **Brand API on the FREE tier** (100 requests) for the explicit logo tooling.
  Quota exhaustion / missing key degrades honestly to the ladder (PDL pattern).
- **Logo API (hotlink CDN) IS in scope for a second lane**: decorative third-party
  logos inside generated web pages — agent writes `<img src="cdn.brandfetch.io/...">`
  directly into markup (compliant: end-viewer browsers fetch with Referer). No cache,
  no custody. Boundary: named-target personalization / `{{account.logo}}` → custody
  path (fetch_logo); ambient logo walls / integration strips → hotlink. Caveats
  accepted: post-publish drift (no eyes), needs an empirical check that editor/review
  headless renders pass the hotlink guards, client ID is public in page URLs.
- **(i) NO icon backfill** — `type=icon` never fills the mark cell.
- **(ii) PER-CELL ladder fallback** — vendor fills what it can; the ladder backfills
  only the empty cells; mixed-provenance families allowed, each cell stamps its
  source.
