# Logo sourcing — founder decision record (2026-08-31)

**Status: BUILT — see `docs/superpowers/plans/2026-09-02-vendor-first-logo-family.md` and
`_memory/2026-09-02-logo-vendor-build.md` (2026-09-02).** Scope was deliberately ruled
lean by the founder; do not expand it at implementation time.

## Premise — how this discussion arose

During the 2026-08-31 review of the `integration/frontend-design-part-iv-v4` merge into
`integration/design-improvement` (merge commit `c3dc7ba8a`), the logo pipeline surfaced three
times:

1. **The in-house logo ladder's accuracy ceiling.** The shared fetcher
   (`subsystems/clue-design/apps/agent_runtime/lumen_agent/tools/logo_fetch.py`,
   `fetch_logo_family`, used by BOTH the scene and web deepagents) is a single-page,
   static-tier scrape of the target's landing page — no JS rendering (a Playwright launch
   costs ~30s, more than a turn budget; its own docstring says a JS-rendered header "comes
   back honestly empty"). If the dark variant or clean wordmark is not in the homepage HTML,
   the ladder cannot produce it. Slot classification is heuristic on top of that.
2. **Two live incidents proved the failure modes.** (a) A 124-byte sprite-reference SVG
   (external `<use>`, no viewBox, no artwork) was fetched, stored, bound `bound: true`, and
   rendered 0×0 on derived pages — fixed on the web bind door by `svg_is_renderable`
   (`lumen_ingestion/logo_ladder.py`, sole production caller
   `lumen_api/agent_account_logos.py`). (b) A live Cursor ABM scene run placed the bare mark
   despite all four slots registering — the founder's full-lockup ruling now lives in the
   SCENE substrate's `fetch_logo` contract only (`tools/substrate.py` ~1345).
3. **The founder's scaling concern:** logos that are merely "usually right" cannot sit under
   a scalable templatization function. At batch scale the wrong primary logo (or a mark where
   a lockup belongs) is reproduced across every derived artifact.

## Problem it solves

Target-account logos today come from an inference process (scrape + heuristics) when the
problem is actually keyed retrieval (`domain → asset family`). The ladder's coverage and
accuracy are bounded by homepage contents; wrong or missing primary logos undermine
account-personalized artifacts in both lanes, and the risk compounds when batching arrives.

## Purpose

A simple, lean, workable logo-sourcing scheme that raises accuracy now, adds no process
overhead, and leaves the batch-time selection problem cleanly deferred.

## The decision (founder, 2026-08-31)

1. **Seller's own logos are never fetched.** They live in the brand kit's asset library; the
   agent reads them from there. Skills/artifact specs will state, per artifact, which logo
   type belongs where. That prose is the only steering — no new machinery.
2. **Target-account / partner / third-party logos: vendor-first, ladder-second.** A logo
   vendor (Brandfetch/Logo.dev class — vendor NOT yet chosen) is the first source; the
   in-house ladder is the fallback. A plain two-rung fallback — not a waterfall framework.
   **Explicitly rejected: running a ladder-vs-vendor comparison first.** Vendor-first is
   decided; no experiment gates it.
3. **Fetch happens at design time, on demand, from either deepagent (web or scene) —
   never at account discovery/enrichment.** Explicitly rejected: enrichment-time prefetch of
   logos for discovered accounts.
4. **Caching:** first successful fetch for an account is stored in blob/object storage keyed
   to that account id, with a very high TTL. Cost is per-account-once, not per-turn.
5. **No verification cards, no gates, no mechanical blockers, no prompt bureaucracy.** The
   human looking at the design is the verification layer. Do not add approval steps to the
   logo path, and do not add gating language to deepagent prompts/skills beyond the
   "which logo type where" artifact prose in (1).
6. **Deferred: family-aware account binding + derive-time slot selection** (the batch /
   templatization scenario). The founder's mental model for when it IS built: a 2×2 —
   **theme** (light-compatible vs dark-compatible) × **completeness** (symbol+wordmark
   lockup vs bare symbol). At derive time, pick the slot from the placement's background
   (dark background → dark-theme-compatible logo, etc.). Ruled "later, not now."

## Advisory notes accepted into the record (from the discussion)

- **Eviction path, not a gate:** with a very-high-TTL cache and no gates, a wrong cached
  logo is wrong forever. The agreed mitigation consistent with the visual-verification
  philosophy: a refetch/replace affordance (e.g. a `force_refresh` on the fetch tool or a
  one-click replace) so "the user saw it's wrong" has an action attached. This is in scope
  for the build.
- **Cache keying must be workspace-scoped** (workspace + account, not global by domain) —
  the B3 workspace-localization ruling (2026-07-22: no cross-tenant enrichment reuse, on
  provider-licensing + GDPR controller-separation grounds) applies; the existing artifact
  cache is already keyed `(source_key, ref, workspace_id)`.
- **Implementation template exists in-tree:** the PDL company-identity resolver (R3-A,
  merged from part-iv-v4) is the exact shape — env-keyed credentials
  (`PDL_API_KEY`-style), typed missing-credentials error, blank key or vendor miss degrades
  honestly to the old path, result stamps which source answered. Clone that pattern for the
  logo vendor rung.
- **Marker for the batch era:** the no-gates ruling is sound while every placement has eyes
  on it (agent preview + human review in-turn). When batch derivation lands (no eyes per
  artifact), a minimal "does this file actually paint" check (`svg_is_renderable` already
  exists, shared, in `logo_ladder.py`) earns its place on that path — revisit then, not now.

## Facts for whoever picks this up

- Shared fetcher: `lumen_agent/tools/logo_fetch.py::fetch_logo_family` — both substrates
  expose it as `fetch_logo`. It ALREADY returns the family:
  `SLOT_NAMES = ("light", "dark", "mark", "wordmark")` + `lockup_completeness`. The
  founder's 2×2 maps onto this existing taxonomy, so the deferred batch work inherits
  populated categories for free — it needs a selection rule, not a data migration.
- `bind_account_logo` (web lane) binds ONE `asset_id` per account; `{{account.logo}}`
  resolves that scalar at derive time. Family-aware binding = the deferred schema change.
- Known asymmetries recorded in the merge review (2026-08-31 session): the full-lockup
  ruling text is scene-substrate-only; `svg_is_renderable` guards only the web bind door.
  Neither is to be "fixed" as part of this scope unless the founder says so.
- Prior art caveat: a "Phase 2 logo corroboration" design exists (deferred indefinitely by
  founder ruling, preserved in the part-iv-v4 `_memory` line, commit `56b129088`). Parts of
  it assume background/corroborated resolution — **this decision supersedes any
  enrichment-time-fetch aspect of that design**; treat it as reference for sizing only.

## Open items for the pickup branch

- Choose the vendor + confirm pricing/licensing terms.
- Name the config keys (mirror the PDL pattern) and add both `.env.example` lines.
- Decide the exact cache location/key shape (blob store keyed workspace+account) and TTL.
- Wire the two-rung dispatch inside `fetch_logo_family` so both lanes inherit it with zero
  harness changes; ensure the seller-vs-target routing (brand kit vs fetch) is stated in the
  relevant skills/prompts per (1).
