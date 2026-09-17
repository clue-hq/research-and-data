# 2026-09-17 — Custom-domain publishing for web pages: research + discussion (no code changed)

Lane `research-streaming`, worktree `san-salvador`. Founder asked how to let a workspace publish
its web pages on its OWN domain (one domain per workspace), how Notion / Mutiny / Ploy do it, and
which of the dummy Settings → Pages fields are actually needed. Analysis only.

## Where the codebase actually is (verified in tree)
- Public pages serve ONLY at the O6b interim route `/w/{workspace_id}/p/{slug}` on the design API
  (`lumen_api/main.py` ~5474). The ruled tenant-subdomain v1 (`{ws-slug}.pages.cluehq.ai/{slug}`,
  Part-IV item 5, five-piece decomposition in the global memory `part4-founder-rulings`) is NOT
  built: no workspace-slug registry, no Host→workspace seam, no wildcard DNS/TLS.
- The share menu shows a hardcoded, non-functional host `share.cluehq.ai`
  (`use-artifact-sharing-controller.ts:14`); copy-link copies `https://share.cluehq.ai/{slug}`.
- Hosting: frontend on Railway (`apps/frontend/docs/railway-deployment.md`, domain `app.cluehq.ai`
  via CNAME+TXT); platform API and design API run LOCALLY behind ngrok tunnels. There is no
  deployed public-page origin today.
- Published HTML bakes ABSOLUTE asset URLs `{request.base_url}/w/{ws}/p-assets/{sha}.{js,css}` at
  publish time and the delivery CSP pins that origin (`web_export.py` ~1264, ~1519). Serving the
  same HTML from another host means assets still load cross-origin from the design API host
  (CORS `*` is set), or the publish must be re-derived with the new base. Design consequence: the
  public base must become a config value, not `request.base_url`.
- `design_document.web_noindex` is durable per page (ruling R-F1: ABM pages noindex forever).
- Dummy Pages page (`port-of-spain/src/features/settings/components/pages-settings.tsx`): custom
  domain, fallback URL, favicon, social preview, page title, page description, allow-indexing +
  allow-following toggles, head/body HTML snippets, llms.txt + autogenerate toggle. Contract
  proposes `PATCH /settings/pages` + two upload endpoints. Prior ruling (2026-09-14): Pages stays
  dummy; re-scope later: brand-kit-sourced favicon/og/title, fallback URL, head/body (security
  review); no custom domain, no index toggles, no llms.txt.

## Research findings (two Opus agents, sources in their reports; key facts)
- Notion Sites: subdomain ONLY (no apex), CNAME → `external.notion.site` + TXT `_notion-dcv.<sub>`,
  $10/mo per domain add-on, ≤25 domains; per-domain favicon/OG/title/GA/indexing toggle; no
  head/body code. Cloudflare proxy must be off.
- Mutiny: ONE dedicated custom SUBDOMAIN per workspace (`go.company.com`), two CNAMEs (CloudFront
  + ACM verification), Business plan+. Workspace-level Settings → Pages = fallback URL, favicon,
  OG image, title, description, index/crawl, head+body HTML snippets. Same field set as our dummy.
- Ploy: apex + www supported via Cloudflare for SaaS (`_acme-challenge` DCV CNAMEs, A record +
  CNAME → `proxy.runploy.com`), Entri one-click DNS, path-based routing rules that proxy the rest
  of the domain to the customer's existing site (max 20 rules). Plan-gated per domain family.
  Their "on the prospect's subdomain" ABM claim has no doc behind it.
- Standard protocol: CNAME (subdomain) or A/ALIAS (apex) + TXT ownership record (prevents
  hostname hijack / dangling-CNAME takeover) + automated cert (LE limit 50 certs / registered
  domain / week; CAA must allow the CA). Cloudflare orange-cloud O2O is the classic pitfall.
- Railway: custom domains per SERVICE are capped Trial 1 / Hobby 2 / Pro 20 → Railway cannot be
  the per-workspace custom-domain host. Wildcard `*.pages.cluehq.ai` counts as ONE domain
  (CNAME + `_acme-challenge` CNAME + `_railway-verify` TXT). Cloudflare-for-SaaS in front of
  Railway hits `x-railway-fallback: true` 404 unless the Host is one Railway knows (community
  threads); a Worker-as-origin rewriting Host to the workspace subdomain is the inferred fix.
- Cloudflare for SaaS: 100 custom hostnames free, $0.10/hostname/month after; TXT/HTTP
  pre-validation; apex only via customer-side CNAME flattening or Enterprise apex proxying.
  Approximated: $0.20/domain/month, single A record (apex works natively). Caddy on-demand TLS
  with an `ask` endpoint = zero-lock-in self-hosted option (belongs on a VM, not Railway).

## Recommendation put to the founder (not yet ruled)
1. Sequence: deploy a real public-page origin + build the ruled tenant-subdomain v1 first (slug
   registry, Host→workspace seam, wildcard on Railway); custom domain = one more row in that seam.
2. v1 custom domain = ONE dedicated SUBDOMAIN per workspace (Mutiny/Notion model), no apex.
3. Edge = Cloudflare for SaaS custom hostnames (cheap, API, TXT pre-validation); origin = the
   page-serving service; Railway direct is ruled out by the cap.
4. Pages settings keep: custom domain (+ status lifecycle), fallback URL, favicon/social/title/
   description as workspace DEFAULTS sourced from the brand kit. Drop: indexing/following toggles
   (contradict R-F1), llms.txt. Defer with security review: head/body snippets (CSP conflict).
Open founder questions: subdomain-only vs apex; plan gating; whether to keep the
`{ws}.pages.cluehq.ai` URL live + canonical after a custom domain connects.

## RATIFIED (founder, 2026-09-17): v1 custom-domain rules = "section 20" of the founder's explainer
Pasted at `.context/attachments/CTpy1V/pasted_text_2026-09-17_13-48-33.txt` (gitignored; the rules
are restated here so they survive):
- Every workspace gets one permanent `<workspace>.pages.cluehq.ai` hostname (kept forever, also
  the fallback while a custom domain provisions or after it is removed).
- Every workspace may connect ONE customer-owned hostname; it MUST be a subdomain (`go.acme.com`).
  Bare apex (`acme.com`) refused with a clear explanation; hostnames under `cluehq.ai` refused;
  a hostname belongs to exactly one workspace.
- Active only when ownership + DNS + TLS are all ready (Cloudflare hostname status AND
  certificate status active). Lifecycle: not connected → waiting for DNS → verifying ownership →
  issuing certificate → active; error states named.
- One hostname-aware delivery path: Cloudflare for SaaS custom hostname (on the cluehq.ai zone
  Cloudflare already holds) → Worker on the `pages.cluehq.ai` fallback origin rewrites Host to the
  ONE Railway origin (`page-origin.cluehq.ai`) and forwards the public hostname in a trusted header
  plus a shared edge-auth secret → backend resolves hostname→workspace from its own registry,
  path→published slug. Railway accepts page traffic only through that edge path.
- Removal is ordered: local row `disconnecting` → delete Cloudflare custom hostname → confirm →
  deactivate local row; Clue hostname stays live.
- HTML and assets must be host-independent (publishing stops baking `request.base_url`).
- Two unrelated "fallbacks": Cloudflare fallback origin (infra) vs workspace fallback URL (product).
Sharpenings agreed in chat: always require the ownership TXT (Cloudflare would accept CNAME
alone → dangling-CNAME reclaim risk); use HTTP certificate validation (customer adds CNAME + 1
TXT only); the shared-secret header is the correct design on Railway (Railway terminates TLS, so
authenticated origin pulls are unavailable); canonical/redirect between the two hostnames is moot
(R-F1 noindex); the workspace-slug registry (Part-IV piece 1) ships in the same slice; the in-app
preview must be checked when assets go relative.
OPEN (next question): which service is the page origin and what does it read — only the
frontend is hosted today; Postgres + platform API + design API + workers all run locally behind
ngrok (`docs/specs/demo-2026-08-29-runbook.md`).

## Closing entry 2026-09-17 — design approved, spec written, no code
- Option C ratified: hosted Postgres (Railway) + R2 now; ONE small page-origin service on Railway
  (`platform/page_origin/clue_page_origin`) reading the publish tables + blobs; other services stay
  local until they migrate. Eleven design sections approved in chat.
- Spec: `docs/superpowers/specs/2026-09-17-custom-domain-publishing-design.md` (registry table
  `workspace_hostname` = slug registry + custom rows; `workspace_pages_settings`; Worker
  `pages-edge`; page origin routes + edge gate; host-independent publish with og:url/canonical
  DROPPED and og:image the one absolute URL; control plane under `/frontend/v1/settings/pages`;
  Cloudflare client; slices S0/S1/S2; assumptions A1–A6; frames owed by the co-founder).
- Verified while writing: lumen_api does not import clue_spine today (spec adds the dependency);
  publish mints canonical/og:url/manifest/asset URLs under `/w/{ws}` (web_export.py ~1503-1640);
  `/asset-store` already relative; alembic head `e8fdb29cd532`; `create_workspace` in
  `libs/clue-spine/clue_spine/spine.py:105` is the single hook for slug allocation; settings
  feature not yet in `apps/frontend` (S2 dependency); permission vocabulary in
  `platform/auth/clue_auth/policy.py` (revision 2; `workspace.manage_settings` = settings spec rev 3).
- Next: founder reviews the spec → writing-plans for S1 (and the S0 runbook).

## Addendum 2026-09-17 — S0 + S1 implementation plan written (no code)
- `docs/superpowers/plans/2026-09-17-custom-domain-publishing-s0-s1.md`: 14 tasks (settings/env parity,
  migration, `clue_spine.hostnames` pure + DAL + `create_workspace` allocation, backfill command, shared
  CSP/asset check in `clue_design.publishes`, the `clue_page_origin` package with fake-backed route tests,
  entrypoint/Dockerfile/dev stack 8040, host-independent publish in `web_export`, `lumen_api.public_pages`
  + tool/route changes, interim `/w/` route deletion with a `published_html` test helper, share-menu
  wiring, the `pages-edge` Worker, the S0 runbook).
- Nine plan-level decisions flagged for the founder in the plan's "Decisions" section (text+CHECK not
  enum; one allocator with three callers incl. the design API's `_ensure_workspace`; suffix as a spine
  parameter; X-Robots-Tag from the manifest; both tables in one migration; `public_origin`/`custom_origin`
  on publish responses; no sniff on `/asset-store`; ads hide the host segment; second link line → S2).
- Verified while planning: the chat-shell share menu is a dummy (no listener for
  `clue:artifact-publish-request`, `fetchWebPublishInfo`/`publishWebDocument` have no consumers);
  `activeDocumentId` is in scope at the `ArtifactHeader` render site, so Task 12 wires it for real.
- Next: founder reviews the plan → execute (subagent-driven, Opus implementers, Fable reviews).

## Addendum 2026-09-17 — S2 plan written (no code)
- `docs/superpowers/plans/2026-09-17-custom-domain-publishing-s2.md` (12 tasks): config/deps; custom-hostname
  validation (tldextract offline) + DAL + atomic label change; `clue_spine.pages_settings` + origin
  fallback/favicon reads; Cloudflare client (MockTransport fixtures); DNS observer + pure status ladder;
  `workspace.manage_settings` (policy rev 3); `/frontend/v1/settings/pages` routes (read/PATCH/uploads/label,
  then connect/check/remove with a ticking test clock); design-API publish-time defaults; frontend model/
  repository/actions; the settings shell lifted verbatim from port-of-spain with only Pages bound
  (Task 11 GATED on the co-founder's four connection-card frames or a written waiver); contract doc.
- Seven plan-level decisions flagged in the plan (txt_missing measured from connect; local 403 mapping;
  verbatim shell lift with fixture for non-Pages sections; no sidebar entry point; DNS in a thread;
  publish-time defaults scope; custom_url appears once a row is active).
