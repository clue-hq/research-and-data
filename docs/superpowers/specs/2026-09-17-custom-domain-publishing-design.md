# Custom-domain publishing for web pages — design (v1)

**Status:** design approved in chat 2026-09-17 (founder); written for founder review before planning.
**Lane:** `research-streaming`, worktree `san-salvador`.
**Rulings this spec implements:** the founder's "section 20" v1 rules (ratified 2026-09-17), Option C
for the page origin (ratified 2026-09-17), and the eleven design sections approved in chat the same
day. The Part IV ruling of 2026-08-17 ("tenant subdomain only, custom domains not in v1") is
superseded by this spec; its five-piece decomposition is kept and built here.
**Research record:** `_memory/2026-09-17-custom-domain-publishing-research.md` (what the tree serves
today, how Notion / Mutiny / Ploy do it, provider comparison, Railway's per-service domain cap).
**Implementation:** S1 landed on `research-streaming-v3` (commits 2835e8175..4ffd7d3da, 2026-09-17); S0 runbook: `docs/specs/pages-hosting-runbook.md`; session record: `_memory/2026-09-17-custom-domain-publishing-s1.md`. S2 landed on `website/custom-domain` (the same branch, renamed; commits ab3a3bf7b..6e40162af, 2026-09-17/18) — the live Cloudflare acceptance walk of §10 is OWED (founder-triggered); session record: `_memory/2026-09-17-custom-domain-publishing-s2.md`; contract: `apps/frontend/docs/api-contracts/settings.md`. **Reconciled 2026-09-28 with the F5 multi-page lane** (founder ruling: this design for storage and serving; F5's multi-page routes and lock-at-first-publish adopted; `design_workspace_handle` and the design API's Host app removed, handles backfilled into labels): merge `22a581ea4` of `codex/ai-ark-committee-discovery-spec-v1`, then `1aae24fcd` (Alembic join `c16e1ae684b3` + handle backfill `770bf20802e1`), `b84dc742f` + `9bad6e892` (design API on the registry), `e705840e7` (page-origin routes `/{slug}/{route}`), `de80c454d` (share-menu custom URLs, Settings → Pages on the settings slice's shell); plan: `docs/superpowers/plans/2026-09-28-custom-domain-f5-reconciliation.md`; session record: `_memory/2026-09-28-custom-domain-f5-reconciliation.md`.

---

## 1. What this builds, and what it does not

Every workspace gets a permanent public hostname and may connect one hostname it owns. Both serve
the workspace's published web pages through one hostname-aware delivery path.

```text
https://acme.pages.cluehq.ai/annual-report     the system hostname, always live
https://go.acme.com/annual-report              the customer hostname, once active
```

The v1 rules (ratified):

1. Every workspace receives one permanent `<label>.pages.cluehq.ai` hostname.
2. Every workspace may connect ONE customer-owned hostname.
3. The customer hostname must be a subdomain (`go.acme.com`). A bare registrable domain
   (`acme.com`, `acme.co.uk`) is refused with an explanation. Hostnames under `cluehq.ai` are refused.
4. A hostname belongs to exactly one workspace.
5. A customer hostname is active only when ownership, DNS and TLS are all ready. Ownership means
   the TXT record we asked for is observed in DNS, even though Cloudflare would activate on the
   CNAME alone.
6. The system hostname and the customer hostname share one backend delivery path.
7. The system hostname stays live before, during and after custom-domain setup, and after removal.
8. Removing a custom hostname removes the Cloudflare configuration before the local binding.
9. Published HTML and its assets are host-independent: nothing in an immutable publish package
   names the host it was published from.
10. The Railway page origin accepts page traffic only through the trusted Cloudflare edge path.

Not in v1 (recorded so nobody builds it by accident): apex domains; more than one customer
hostname per workspace; `www` + apex pairs and redirects between them; head/body HTML snippets
(deferred to a security review); indexing/following toggles and `llms.txt` (dropped: every ABM page
is permanently `noindex` under ruling R-F1, so a workspace toggle could not change the answer);
canonical/redirect between the two hostnames (moot for the same reason); a homepage at the root path
of a hostname; scheduled background re-verification (on demand plus screen polling instead);
Cloudflare authenticated origin pulls (Railway terminates TLS at its own edge, so the shared secret
is the design, not a stopgap).

Prerequisite this spec also carries (Option C): today only the frontend is hosted. Postgres, both
APIs, the workers and artifact storage run on the founder's machine behind ngrok
(`docs/specs/demo-2026-08-29-runbook.md`). Stage S0 moves Postgres and artifact storage to hosted
services so a Railway page origin can read them; the other services keep running locally against
those hosted stores until they migrate on their own schedule.

---

## 2. Architecture

### 2.1 The request path

```text
Browser ── https://go.acme.com/annual-report
   │
   ▼
Cloudflare edge (cluehq.ai zone, Cloudflare for SaaS)
   │  TLS for go.acme.com (custom hostname certificate)
   │  TLS for *.pages.cluehq.ai (advanced certificate)
   ▼
Cloudflare Worker  "pages-edge"
   │  strips any incoming X-Clue-Public-Host / X-Clue-Edge-Auth
   │  sets  X-Clue-Public-Host: go.acme.com
   │  sets  X-Clue-Edge-Auth: <secret>
   │  fetches https://page-origin.cluehq.ai/annual-report
   ▼
Railway service  "page-origin"  (page-origin.cluehq.ai, DNS-only record)
   │  refuses without the edge secret
   ▼
clue_page_origin (FastAPI)
   │  X-Clue-Public-Host  →  workspace_hostname row (active)  →  workspace_id
   │  path /annual-report →  design_web_publish (workspace_id, slug), status active
   │  returns the immutable publish HTML; assets by digest under the same host
   ▼
Postgres (hosted)  +  S3-compatible storage (R2)
```

The hostname registry (`workspace_hostname`, §4.1) is the load-bearing seam: every public request
begins by resolving the public hostname there. Cloudflare owns nothing product-level; the Worker
knows no workspaces; the backend does the tenant selection.

### 2.2 Where the code lives

| Piece | Location | Notes |
| --- | --- | --- |
| Hostname registry DAL + slug allocation | `libs/clue-spine/clue_spine/hostnames.py` | The workspace spine owns workspace-level identity; platform API, design API and page origin all import it. |
| Pages settings DAL | `libs/clue-spine/clue_spine/pages_settings.py` | One row per workspace. |
| Page origin service | `platform/page_origin/clue_page_origin/` (`main.py:app`) | New uv-workspace package, same shape as `platform/api`. Own `Dockerfile.railway`. |
| Custom-domain control plane | `platform/api/clue_api/settings_pages.py` | Routes under `/frontend/v1/settings/pages`. |
| Cloudflare client | `platform/api/clue_api/cloudflare_custom_hostnames.py` | Three calls; the only module that knows Cloudflare's field names. |
| DNS observation | `platform/api/clue_api/dns_observe.py` | CNAME + TXT lookups via public resolvers (`dnspython`). |
| Publish host-independence | `subsystems/clue-design/apps/api/lumen_api/web_export.py`, `main.py` | Root-relative URLs, CSP `self`, interim routes deleted. Shared asset integrity check re-homed to `subsystems/design/clue_design/publishes.py`. |
| Worker | `infra/cloudflare/pages-edge/worker.js` + `wrangler.toml` | New directory; deployed by hand in S0 (runbook). |
| Frontend | `apps/frontend/src/features/settings/…` (Pages section), `features/chat-shell/hooks/use-artifact-sharing-controller.ts` | Settings shell comes from the settings integration slice. |
| Runbooks | `docs/specs/pages-hosting-runbook.md` | S0 operator steps, verified values filled in as they are done. |

Seam discipline holds: the design API gains a dependency on `clue_spine` (a shared substrate
library it does not import today; it is in the uv workspace, so this is one `pyproject.toml` line)
and never imports platform API internals; the page origin imports `clue_spine`, `clue_design` (DAL
only) and `clue_storage`, never `lumen_api` or `clue_api`.

---

## 3. Stage S0 — infrastructure (founder-operated, runbook-driven)

S0 is done by hand in the Railway and Cloudflare dashboards, following the runbook this spec
commissions. Every value the runbook produces (zone id, hostnames, bucket name, secrets' *names*)
is recorded in `docs/specs/pages-hosting-runbook.md`; secrets themselves never enter the repo.

1. **Hosted Postgres.** A Railway Postgres in the existing Railway project. Run the Alembic chain to
   head against it (`make db-smoke`-style up/down/up on a scratch copy first). Repoint the local
   platform API, design API and workers via `CLUE_DATABASE_URL`. The lane's local database is not
   promoted; a fresh production database starts empty apart from migrations.
2. **Hosted artifact storage.** A Cloudflare R2 bucket used through the existing S3 backend:
   `CLUE_STORAGE_BACKEND=s3`, `CLUE_STORAGE_S3_BUCKET`, `CLUE_STORAGE_S3_ENDPOINT_URL`
   (the account's R2 S3 endpoint), region `auto`, access key pair. All services share it, as
   `.env.example` already requires for production.
3. **Railway service `page-origin`.** Built from repo root with
   `RAILWAY_DOCKERFILE_PATH=/platform/page_origin/Dockerfile.railway`, health check `/healthz`,
   Public Networking domain `page-origin.cluehq.ai` added with Railway's CNAME + `_railway-verify`
   TXT, both DNS-only (grey cloud) in the cluehq.ai zone, exactly like `app.cluehq.ai` today.
4. **Cloudflare for SaaS on the cluehq.ai zone.** Enable SSL for SaaS. Fallback origin:
   `pages.cluehq.ai`, a proxied CNAME to `page-origin.cluehq.ai`. CNAME target given to customers:
   `pages.cluehq.ai`. Custom hostnames are created with HTTP certificate validation and the
   default TXT ownership record.
5. **System hostnames.** A proxied wildcard DNS record `*.pages.cluehq.ai` → `page-origin.cluehq.ai`.
   Universal SSL does not cover a second-level wildcard, so order an **advanced certificate**
   covering `*.pages.cluehq.ai` (Advanced Certificate Manager; verify the price and the exact
   hostname set in the dashboard, roughly ten dollars a month).
6. **Worker `pages-edge`.** Deployed with wrangler; variables `SYSTEM_SUFFIX=pages.cluehq.ai`,
   `ORIGIN_HOST=page-origin.cluehq.ai`, secret `EDGE_SECRET`. Route: per Cloudflare's
   "use a Worker as your origin" guide for SaaS custom hostnames. The research read is a `*/*`
   wildcard route on the zone. **Verify in S0 with one real custom hostname**: the Worker must run for
   both a system hostname and a custom hostname, and must not run for `app.cluehq.ai` (DNS-only, so
   Workers never see it) or any other proxied record we add later. The Worker passes through any
   host it does not own (see §5.1).
7. **Acceptance for S0:** a hand-inserted `workspace_hostname` row and a hand-published page render
   at `https://<label>.pages.cluehq.ai/<slug>` and at one founder-owned custom hostname, both with
   valid certificates; a direct `curl https://page-origin.cluehq.ai/<slug>` without the secret gets
   403; `curl` with a forged `X-Clue-Public-Host` and no secret gets 403.

---

## 4. Data model

One migration, hash id, chained off the current head `e8fdb29cd532`, hand-written and reversible.

### 4.1 `workspace_hostname` — the registry

```sql
CREATE TYPE workspace_hostname_kind   AS ENUM ('system', 'custom');
CREATE TYPE workspace_hostname_status AS ENUM (
  'pending_dns', 'verifying_ownership', 'issuing_certificate', 'active', 'error', 'disconnecting');

CREATE TABLE workspace_hostname (
  hostname              text NOT NULL,                       -- lowercase, no trailing dot, ASCII (IDNA)
  workspace_id          text NOT NULL REFERENCES workspace (workspace_id),
  kind                  workspace_hostname_kind NOT NULL,
  status                workspace_hostname_status NOT NULL,
  cf_custom_hostname_id text,                                -- custom only
  cname_target          text,                                -- custom only: 'pages.cluehq.ai'
  ownership_txt_name    text,                                -- custom only: '_cf-custom-hostname.go.acme.com'
  ownership_txt_value   text,                                -- custom only
  observed_cname        text,                                -- last DNS observation, may be NULL
  observed_txt_present  boolean,                             -- last DNS observation, may be NULL
  last_checked_at       timestamptz,
  last_error_code       text,                                -- closed set, §7.5
  last_error_detail     text,                                -- provider text, display-only
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),
  activated_at          timestamptz,
  CONSTRAINT workspace_hostname_pkey PRIMARY KEY (hostname),
  CONSTRAINT workspace_hostname_lowercase CHECK (hostname = lower(hostname) AND hostname !~ '\.$'),
  CONSTRAINT workspace_hostname_system_is_active CHECK (kind <> 'system' OR status = 'active'),
  CONSTRAINT workspace_hostname_custom_columns CHECK (
    kind <> 'custom' OR (cname_target IS NOT NULL AND ownership_txt_name IS NOT NULL
                         AND ownership_txt_value IS NOT NULL)),
  CONSTRAINT workspace_hostname_system_columns CHECK (
    kind <> 'system' OR (cf_custom_hostname_id IS NULL AND cname_target IS NULL))
);
CREATE UNIQUE INDEX workspace_hostname_one_system_per_workspace
  ON workspace_hostname (workspace_id) WHERE kind = 'system';
CREATE UNIQUE INDEX workspace_hostname_one_custom_per_workspace
  ON workspace_hostname (workspace_id) WHERE kind = 'custom';
CREATE INDEX workspace_hostname_workspace_idx ON workspace_hostname (workspace_id);
```

Rules the code enforces that SQL cannot: the subdomain-only test (§7.3) needs the public suffix
list; the "not under cluehq.ai" test depends on `CLUE_PAGES_SYSTEM_SUFFIX`'s registrable domain;
and the reserved-label list. All three live in `clue_spine.hostnames` next to the DAL so there is
one validator, used by the control plane, the label editor and the backfill.

**System rows are the workspace-slug registry** (Part IV piece 1). `hostname` for a system row is
`<label>.<CLUE_PAGES_SYSTEM_SUFFIX>`. The suffix is an env value that must match the rows at write
time; the page origin and the platform API log a loud warning at startup if any system row does not
end in the configured suffix (a copied database under a different suffix is a configuration error,
not a data error).

**Slug allocation** (`clue_spine.hostnames.allocate_label(name, taken)`):

- NFKD-normalise the workspace name, drop non-ASCII, lowercase, replace runs of non `[a-z0-9]` with
  one hyphen, trim hyphens.
- Length 3–40. Shorter than 3 or empty → `ws-<first 8 hex of the workspace id>`. Longer → cut at 40
  on a hyphen boundary where possible.
- Reserved labels (never allocated, never chosen by hand): `app, api, www, pages, page-origin, mail,
  admin, share, static, assets, cdn, status, help, docs, dev, staging, test, clue, cluehq, login,
  auth, mcp`.
- Collision or reserved → append `-2`, `-3`, … to the first free one.
- Allocation happens inside `clue_spine.create_workspace` in the same transaction as the
  `workspace` insert, so every creator (owner provisioning, self-serve provisioning, tests) gets a
  system row without knowing about it. Existing workspaces are backfilled by an idempotent command
  (`make pages-backfill-hostnames`, §11) run once in S1 and again at production deploy; the
  migration itself creates no rows.

**Label change** (assumption A1, §12): an admin may pick a new label. The change deletes the old
system row and inserts the new one in one transaction. The old label is immediately free, there is
no redirect, and the UI warns that existing links stop working. **Superseded 2026-09-28:** the label locks at the workspace's first publish (`workspace_hostname.locked_at`); after that the change is refused with `label_locked` — see A1 in §12.

### 4.2 `workspace_pages_settings`

```sql
CREATE TABLE workspace_pages_settings (
  workspace_id            text NOT NULL REFERENCES workspace (workspace_id),
  fallback_url            text,           -- https URL or NULL
  page_title              text,           -- NULL = use the brand kit's name
  page_description        text,           -- NULL = use the brand kit's tagline / empty
  favicon_sha256          text,           -- a design blob in this workspace, or NULL
  social_preview_sha256   text,           -- a design blob in this workspace, or NULL
  updated_at              timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT workspace_pages_settings_pkey PRIMARY KEY (workspace_id),
  CONSTRAINT workspace_pages_settings_fallback_https CHECK (fallback_url IS NULL OR fallback_url ~ '^https://')
);
```

A missing row means all defaults. Favicon and social preview bytes are registered through
`clue_design.storage.register_design_bytes` (workspace-scoped artifact rows, same blob store the
page origin already reads), so no second upload path exists. No columns for head/body snippets,
indexing toggles or `llms.txt`.

**How settings reach a page.** Publish packages are immutable, so title, description and social
preview are read at publish time as defaults for pages whose document sets none; changing them does
not rewrite pages already published (the UI says so; republish applies). The favicon is different:
every publish emits `<link rel="icon" href="/favicon.ico">` and the origin serves the current
favicon live, so a favicon change applies immediately. The fallback URL is read live by the origin.

---

## 5. The edge and the page origin

### 5.1 Worker `pages-edge`

```js
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const host = url.hostname.toLowerCase();
    const ours = host.endsWith("." + env.SYSTEM_SUFFIX) || !host.endsWith("cluehq.ai");
    if (!ours) return fetch(request);                       // another record in our zone: untouched
    if (request.method !== "GET" && request.method !== "HEAD") return new Response(null, { status: 405 });
    const headers = new Headers(request.headers);
    headers.delete("x-clue-public-host");
    headers.delete("x-clue-edge-auth");
    headers.set("x-clue-public-host", host);
    headers.set("x-clue-edge-auth", env.EDGE_SECRET);
    const target = new URL(url.pathname + url.search, "https://" + env.ORIGIN_HOST);
    return fetch(new Request(target, { method: request.method, headers, redirect: "manual" }));
  },
};
```

`redirect: "manual"` matters: the origin's fallback-URL redirect must reach the browser as a
redirect, not be followed at the edge. The Worker never reads the registry; a hostname the backend
does not know gets the backend's 404.

### 5.2 `clue_page_origin` routes

GET and HEAD only; anything else is 405. Every route except `/healthz` runs the edge gate first.

| Route | Behaviour |
| --- | --- |
| `GET /healthz` | 200, no auth (Railway health check). |
| `GET /` | Fallback redirect (302) when the workspace has a fallback URL, else the 404 page. No homepage concept in v1. |
| `GET /favicon.ico` | The workspace favicon blob, `Cache-Control: public, max-age=300`; 404 when none. |
| `GET /{slug}` | The active publish's HTML for `(workspace_id, slug)`. Unknown or inactive slug → fallback redirect or 404 page. |
| `GET /{slug}/manifest.json` | The publish manifest, as today. |
| `GET /p-assets/{sha256}.{js\|css\|html}` | Workspace-scoped `clue_design.storage.read_design_blob` plus the extension-vs-media-type integrity check (re-homed from `lumen_api.web_export.resolve_publish_asset` into `clue_design.publishes` so both callers share it). Immutable cache headers. |
| `GET /asset-store/{sha256}` | `clue_design.storage.read_public_design_blob` (workspace-unscoped by ruling R-D4-7; fonts and rehosted images). Immutable cache headers. |

Slug pattern: `^[a-z0-9][a-z0-9-]{0,71}$` (the share menu's 72-character limit). Anything else is
404 before any lookup.

**Edge gate.** `X-Clue-Edge-Auth` compared to `CLUE_PAGES_EDGE_SECRET` with `hmac.compare_digest`;
missing or wrong → 403 with an empty body, logged with the source IP and the claimed host, never
with the header value. `X-Clue-Public-Host` is lowercased, must parse as a hostname, else 400. When
`CLUE_PAGES_TRUST_HOST_HEADER=true` (local development only) the gate is skipped and the `Host`
header is used; the service refuses to start with that flag on unless `CLUE_PAGES_EDGE_SECRET` is
empty, so the two settings cannot both be live in a deployed environment.

**Resolution.** `workspace_hostname WHERE hostname = :h AND status = 'active'` → `workspace_id`,
one indexed lookup per request, no in-process cache in v1 (revisit if origin CPU is ever the
bottleneck; Cloudflare caches the 60-second HTML in front of us). A hostname in any non-active
status, including a custom hostname mid-provisioning, is 404 — never a leak of which workspace is
claiming it.

**Response headers.** HTML and manifest: `Cache-Control: public, max-age=60, must-revalidate`,
`ETag` from the stored digest, `X-Content-Type-Options: nosniff`,
`Referrer-Policy: strict-origin-when-cross-origin`, `X-Robots-Tag: noindex` when the document's
`web_noindex` is true (belt and braces over the in-page meta), and the CSP of §6.2. Assets:
`Cache-Control: public, max-age=31536000, immutable`, `ETag: "sha256-<digest>"`. Nothing sets
`Access-Control-Allow-Origin: *` any more: assets are same-origin by construction.

**404 page.** A small static HTML page, no workspace data on it, branded neutrally, `noindex`.

**Local development.** The service runs on port **8040** in the lane runbook
(`scripts/dev_stack_san_salvador.sh`, `DEV_STACK.md`) with `CLUE_PAGES_SYSTEM_SUFFIX=pages.localhost`,
`CLUE_PAGES_PUBLIC_SCHEME=http`, `CLUE_PAGES_PUBLIC_PORT=8040` and
`CLUE_PAGES_TRUST_HOST_HEADER=true`. Browsers resolve `acme.pages.localhost` to loopback without any
DNS setup, so `http://acme.pages.localhost:8040/annual-report` works out of the box.

---

## 6. Publish becomes host-independent (design API)

### 6.1 What changes in the publish package

`build_publish_package` no longer receives `public_base` from `request.base_url`. Every URL it mints
is root-relative, except one:

| Today (O6b interim) | After |
| --- | --- |
| `{base}/w/{ws}/p-assets/{sha}.js` | `/p-assets/{sha}.js` |
| `/asset-store/{sha}` (already relative) | unchanged |
| `<link rel="lumen-component-manifest" href="…manifest.json">` under `/w/{ws}/p/{slug}/` | `/{slug}/manifest.json` |
| `<link rel="canonical" href="{base}/w/{ws}/p/{slug}">` | **removed** — a canonical naming one host would be wrong on the other, and the pages are `noindex` |
| `<meta property="og:url" …>` | **removed** — unfurlers fall back to the fetched URL, which is the right one on either host |
| `<meta property="og:image" content="{base}/asset-store/{sha}">` | `https://<system hostname>/asset-store/{sha}` — the one absolute URL; unfurlers require it, and the system hostname is always live |
| `manifest.canonical_url` | `https://<system hostname>/{slug}` (informational) |
| (none) | `<link rel="icon" href="/favicon.ico">` always emitted |

The system hostname comes from `clue_spine.hostnames.system_hostname(conn, workspace_id)` plus
`CLUE_PAGES_PUBLIC_SCHEME` / `CLUE_PAGES_PUBLIC_PORT` for dev. Workspace defaults for title,
description and social preview (§4.2) are read at the same point.

Package digests change for every republish after this lands; that is expected and harmless
(content-addressed revisions are append-only).

### 6.2 CSP

```text
default-src 'none'; script-src 'self' 'unsafe-inline' data:; style-src 'self' 'unsafe-inline';
img-src 'self' data: blob:; font-src 'self' data:; connect-src 'none'; object-src 'none';
worker-src 'none'; frame-src 'self' data: blob:; base-uri 'none'; form-action 'none';
frame-ancestors 'self'
```

Sent by the page origin as a header and embedded by the package as the meta form (without
`frame-ancestors`, as today). The origin-specific allow-list is gone.

### 6.3 Publish and state responses

`POST /documents/{id}/web/publish` and `GET …/web/publish` return:

```json
{ "slug": "annual-report",
  "url": "https://acme.pages.cluehq.ai/annual-report",
  "custom_url": "https://go.acme.com/annual-report",   // null unless a custom hostname is active
  "status": "active", "publish_id": "webpub_…", "…": "…" }
```

`public_publish_path` is deleted with the routes below; the `url` builder is one function in
`lumen_api` over the registry read.

### 6.4 Deletions

The three O6b interim routes (`/w/{ws}/p/{slug}`, `/w/{ws}/p/{slug}/manifest.json`,
`/w/{ws}/p-assets/{name}`) and the 404-stub `/p/{slug}` are removed from the design API, with their
tests, per the ruling that they are deleted and never kept as a fallback. `public_repository` /
`public_blob_store` in `main.py` go with them if nothing else uses them.

### 6.5 In-app preview

Anything in the app that shows a *published* page uses `url` from §6.3 in an iframe or a link. The
editor's origin-`null` srcdoc preview renders documents, not publish packages, and keeps using
`/asset-store/…` on the design API as today; it is not affected. S1 verifies this claim by grepping
every consumer of the publish `url` and `/w/` paths in `apps/frontend` and `subsystems/clue-design`
before deleting the routes.

---

## 7. Control plane — connecting a customer hostname

### 7.1 Routes (`platform/api`, mounted under `/frontend/v1/settings/pages`)

| Method + path | Auth | Purpose |
| --- | --- | --- |
| `GET /` | membership | Settings + both hostnames (§7.2 shape). Runs a cheap status refresh (§7.4) when the custom row is non-active and last checked more than 5 s ago. |
| `PATCH /` | `workspace.manage_settings` | `fallback_url`, `page_title`, `page_description` (any subset; `null` clears). |
| `POST /favicon` | `workspace.manage_settings` | multipart image ≤ 256 KB, `image/png` or `image/x-icon` or `image/svg+xml`; stored, digest written. |
| `POST /social-preview` | `workspace.manage_settings` | multipart image ≤ 2 MB, `image/png` or `image/jpeg`. |
| `PATCH /system-hostname` | `workspace.manage_settings` | `{ "label": "acme-hq" }` — label change (§4.1). |
| `POST /custom-hostname` | `workspace.manage_settings` | `{ "hostname": "go.acme.com" }` — connect. |
| `POST /custom-hostname/check` | membership | Check now: refresh from DNS + Cloudflare, advance status. |
| `DELETE /custom-hostname` | `workspace.manage_settings` | Ordered removal. |

Frontend reaches these through the existing seams: `fetchRead` for the GET (server side) and
`fetchMutation` through the BFF for writes, per the settings integration spec §2.2.

`workspace.manage_settings` is the permission the settings integration spec introduces (policy
revision 3, admin + owner). If that slice has not landed when S2 starts, S2 adds it.

### 7.2 Read shape

```json
{
  "settings": { "fallbackUrl": "https://www.acme.com", "pageTitle": "Acme", "pageDescription": "…",
                "faviconUrl": "https://acme.pages.cluehq.ai/favicon.ico",
                "socialPreviewUrl": "https://acme.pages.cluehq.ai/asset-store/<sha>" },
  "systemHostname": { "hostname": "acme.pages.cluehq.ai", "label": "acme", "url": "https://acme.pages.cluehq.ai" },
  "customHostname": {
    "hostname": "go.acme.com",
    "status": "verifying_ownership",
    "records": [
      { "type": "CNAME", "name": "go.acme.com", "required": "pages.cluehq.ai", "observed": "pages.cluehq.ai", "ok": true },
      { "type": "TXT",   "name": "_cf-custom-hostname.go.acme.com", "required": "<token>", "observed": null, "ok": false }
    ],
    "lastCheckedAt": "2026-09-17T12:00:00Z",
    "error": null,                     // or { "code": "caa_blocked", "detail": "…" }
    "url": "https://go.acme.com"       // present only when active
  }
}
```

`customHostname` is `null` when none is connected.

### 7.3 Connect — validation, in order, each with its own refusal code

1. `hostname_invalid` — not a syntactically valid hostname after normalisation (lowercase, trailing
   dot stripped, IDNA-encoded, ≤ 253 chars, labels 1–63 of `[a-z0-9-]`, no leading/trailing hyphen).
2. `hostname_is_apex` — the hostname equals its registrable domain. Registrable domain is computed
   with the public suffix list (`tldextract` with the bundled snapshot and network fetching
   disabled), so `acme.co.uk` is refused and `go.acme.co.uk` is accepted. The message explains that
   a dedicated subdomain such as `go.acme.com` is required.
3. `hostname_reserved` — under `cluehq.ai` (the registrable domain of `CLUE_PAGES_SYSTEM_SUFFIX`).
4. `custom_hostname_exists` — this workspace already has a custom row (any status). Remove first.
5. `hostname_taken` — the hostname exists in the registry for another workspace. The message says
   only "already connected to a workspace".

Then, in one transaction: insert the row with `status = pending_dns`, `cname_target`, and placeholder
ownership columns; commit; call Cloudflare create; update the row with `cf_custom_hostname_id`,
`ownership_txt_name`, `ownership_txt_value`. If Cloudflare refuses (duplicate in the zone, quota,
outage), the row is deleted and the request fails with `provider_error` — Cloudflare's message in
`detail`. The insert-before-create order makes the uniqueness index the arbiter between two
simultaneous connects of the same hostname.

### 7.4 Status derivation (check now, and the read's refresh)

Inputs per check: our DNS observation (CNAME of the hostname, TXT at the ownership name, via
public resolvers so a cached local answer cannot mislead) and Cloudflare's hostname status, SSL
status, and error arrays.

```text
disconnecting                       → retry the Cloudflare delete (§7.6); stay unless it succeeds
Cloudflare or DNS errors present    → error  (code per §7.5; detail = provider text)
CNAME not observed == target        → pending_dns
TXT not observed                    → verifying_ownership     (our rule, even if Cloudflare says active)
Cloudflare hostname or SSL ≠ active → issuing_certificate
all of the above satisfied          → active   (activated_at set once)
```

An `error` row re-enters the ladder on the next check as soon as the errors clear. Results are
stored on the row (`observed_*`, `last_checked_at`, `last_error_*`). Checks are rate-limited to one
per 5 s per workspace; a faster call returns the stored state.

Cloudflare's own hostname validation happens on the CNAME. Our TXT rule is stricter on purpose:
a customer who deletes their site but leaves the CNAME pointing at us cannot have that hostname
re-claimed by another workspace without a fresh TXT they control.

### 7.5 Error codes (closed set, displayed by the UI)

| Code | Meaning |
| --- | --- |
| `cname_incorrect` | CNAME observed but pointing elsewhere (includes "customer still proxies through their own Cloudflare with an A record"). |
| `txt_missing` | Cloudflare reports ownership pending after the CNAME is right for more than 30 minutes. |
| `caa_blocked` | Cloudflare SSL validation error mentions CAA. |
| `hostname_taken` | Cloudflare refuses the hostname (already a custom hostname elsewhere, or the O2O 1034 case). |
| `verification_expired` | Cloudflare moved the hostname to `moved` / `deleted`. |
| `provider_error` | Anything else from Cloudflare; detail carried verbatim for support. |

### 7.6 Remove

1. `UPDATE … SET status = 'disconnecting'` (idempotent; a 404 for a workspace with no custom row).
2. Cloudflare delete. A Cloudflare 404 counts as deleted.
3. `DELETE FROM workspace_hostname WHERE hostname = :h`.
4. Response 204. If step 2 fails, the row stays `disconnecting`, the response is 502
   `provider_error` with `retryable: true`, and check-now retries step 2. The page origin already
   serves 404 for the hostname from step 1 onward. The system hostname is untouched.

### 7.7 Cloudflare client

One module, three functions, `httpx`, bearer token, base
`https://api.cloudflare.com/client/v4/zones/{zone_id}/custom_hostnames`:

- `create(hostname)` → `POST` with `{"hostname": …, "ssl": {"method": "http", "type": "dv"}}`;
  returns `id`, `status`, `ssl.status`, `ownership_verification {name, value}`,
  `verification_errors`, `ssl.validation_errors`.
- `get(id)` → same shape.
- `delete(id)`.

Field names are taken from the current Cloudflare API reference at implementation time and pinned
by recorded-fixture tests; this module is the only place they appear. Timeouts 10 s, one retry on
5xx, no retry on 4xx. The token is scoped to the zone with only "SSL and Certificates: Edit".

---

## 8. Frontend

### 8.1 Share menu

`SHARE_HOST` and the `https://share.cluehq.ai/{slug}` builder are deleted. The controller shows the
`url` returned by the publish state, and, when `custom_url` is present, shows that one as the
primary link with the system URL beneath it. The "Publishing link path" editor keeps editing the
slug; the host part is read-only text from the backend.

### 8.2 Settings → Pages

Lifted from the dummy's `pages-settings.tsx` on top of the settings shell delivered by the settings
integration slice, then trimmed to the ratified field set:

- Kept: Custom domain (replaced by the connection card below), Fallback URL, Favicon, Social
  preview, Page title, Page description, plus a read-only "Your Clue address" row showing the
  system hostname with an Edit affordance for the label (A1).
- Dropped: the "Search engine settings" card and the "AI crawler discovery" card.
- Deferred: the "Additional code snippets" card, removed from the screen for now.

Autosave on blur and the confirmation card follow the settings integration spec.

**Custom domain connection card, four states** (frames owed by the co-founder, §12):

1. *Not connected* — hostname input, helper text "Use a dedicated subdomain such as go.acme.com",
   Connect button. Refusals from §7.3 render inline under the input.
2. *Connecting* — the two DNS records as a table (Type / Name / Required value / Observed value /
   check), a five-step status stepper (Waiting for DNS → Verifying ownership → Issuing certificate →
   Active), a "Check now" button, and the note that DNS changes can take up to 48 hours. The screen
   calls check-now every 5 s while this card is visible.
3. *Active* — the hostname with a green dot, "Open" and "Remove" actions.
4. *Error* — the card of state 2 with the error line from §7.5 and "Check now".

Remove asks for confirmation (two-step, like retire in the research-fields spec) and explains that
the Clue address keeps working.

---

## 9. Configuration and environment

Parity rule: every flag below appears in `.env.example` with its default the moment it is introduced,
and the local `.env` mirrors it.

```dotenv
# --- Public pages: hostnames and delivery ------------------------------------------------
CLUE_PAGES_SYSTEM_SUFFIX=pages.cluehq.ai        # dev: pages.localhost
CLUE_PAGES_CNAME_TARGET=pages.cluehq.ai         # the CNAME value shown to customers
CLUE_PAGES_PUBLIC_SCHEME=https                  # dev: http
CLUE_PAGES_PUBLIC_PORT=                         # dev: 8040 ; empty in production
CLUE_PAGES_EDGE_SECRET=                         # shared with the Worker; empty only in dev
CLUE_PAGES_TRUST_HOST_HEADER=false              # dev only; refuses to start together with a secret
CLUE_PAGES_ORIGIN_PORT=8040
# Cloudflare for SaaS (custom hostnames) — control plane only
CLUE_CLOUDFLARE_API_TOKEN=                      # secret; zone-scoped "SSL and Certificates: Edit"
CLUE_CLOUDFLARE_ZONE_ID=
```

The page origin also reads `CLUE_DATABASE_URL` and the `CLUE_STORAGE_*` block. The Worker's
variables (`SYSTEM_SUFFIX`, `ORIGIN_HOST`, secret `EDGE_SECRET`) live in `wrangler.toml` and the
Cloudflare secret store, documented in the runbook.

New Python dependencies: `tldextract` (public suffix list, offline snapshot) in `libs/clue-spine`,
because the hostname validator lives there; `dnspython` (DNS observation) in the platform API's
package. The page origin needs neither directly.

---

## 10. Testing and acceptance

**Unit (no DB).** Hostname normalisation and the five refusals of §7.3 with the public-suffix cases
(`acme.com`, `acme.co.uk`, `go.acme.co.uk`, `x.cluehq.ai`, IDNA, 63-char label, trailing dot);
slug allocation (accents, short names, reserved words, collisions, 40-char cut); status derivation
over a table of (DNS observation × Cloudflare state) inputs; error-code mapping.

**DB (lane throwaway database only).** Migration up/down/up; the two partial unique indexes; the
system-row CHECKs; `create_workspace` allocates a system row in the same transaction; label change
is atomic; backfill is idempotent; pages-settings upsert.

**Page origin.** Route tests with a fake registry, fake publish DAL and in-memory storage: 403
without the secret, 403 with a forged public host and no secret, 400 on a malformed public host,
404 for a pending custom hostname, fallback redirect vs 404 page, slug pattern refusals, asset
extension/media-type mismatch refused, cache and CSP headers exact, `X-Robots-Tag` on a `noindex`
document, GET/HEAD only.

**Design API.** The publish package contains no `/w/` path and no absolute URL except `og:image`;
canonical and `og:url` absent; favicon link present; CSP header exact; the publish response carries
`url` and `custom_url`; the interim routes return 404 and their tests are gone.

**Control plane.** Connect / check / remove against a recorded-fixture Cloudflare client
(create, get in each state, delete, 404-on-delete, 5xx-then-success); concurrent connect of the same
hostname by two workspaces leaves exactly one row; remove with a Cloudflare outage leaves
`disconnecting` and a later check completes it; permission refusals.

**Frontend.** Existing gate (`npm run design-system:build && npm run lint && npm run build`) plus
component tests for the four card states and the share menu host.

**Live acceptance (founder-triggered, recorded in `_memory/`).** One founder-owned hostname walks
the whole ladder to active and renders a real published page; the same page renders on its system
hostname; removal returns the custom hostname to 404 within a minute while the system hostname keeps
serving; a direct hit on `page-origin.cluehq.ai` without the secret is refused. Live tests spend
nothing but they touch production Cloudflare state, so they run by hand, never in the suite.

---

## 11. Build order

| Slice | Delivers | Exit gate |
| --- | --- | --- |
| **S0 infrastructure** | Hosted Postgres + R2; Railway `page-origin` service with its domain; Cloudflare for SaaS, wildcard record, advanced certificate, Worker; the runbook with every value filled in. Needs S1's Docker image to exist, so S0 finishes after S1's origin service builds; the Cloudflare/Railway setup can start immediately. | §3 item 7. |
| **S1 system hostnames live** | Migration; `clue_spine.hostnames` + allocation in `create_workspace`; `make pages-backfill-hostnames`; `clue_page_origin` with Dockerfile and lane port 8040; host-independent publish + CSP + response `url`; interim route deletion; share menu host; env parity. | `https://<label>.pages.cluehq.ai/<slug>` serves a page published from the app; every test group in §10 except control plane and frontend Pages screen green. |
| **S2 custom domains** | `workspace_pages_settings` DAL and routes; Cloudflare client; DNS observation; connect / check / remove; label change; Settings → Pages screen with the connection card; `workspace.manage_settings` if not yet present. | The live acceptance walk of §10. Depends on the settings shell from the settings integration slice; if that slice is not merged, S2 mounts the Pages section on the lifted shell in this lane and reconciles at merge. |

Each slice is one implementation plan. S1 and the dashboard half of S0 can proceed in parallel.

---

## 12. Assumptions, owed items, follow-ups

**Assumptions carried (say so if any is wrong):**

- **A1** An admin can change the workspace label; the old hostname is freed immediately, no
  redirect, UI warning. Baked `og:image` URLs on already-published pages then point at the old
  system hostname until republish; accepted, since the pages are `noindex` and the image is the
  only absolute URL.
  **Superseded 2026-09-28** by F5's lock-at-first-publish rule (adopted in the F5 reconciliation): the
  label can change only until the workspace's first publish, after which `replace_system_label`
  refuses with `label_locked`.
- **A2** Railway Postgres (same project) rather than an outside provider; R2 for storage.
- **A3** Status checks are on demand plus 5-second screen polling; no scheduled sweep in v1.
- **A4** The root path of a hostname redirects to the fallback URL or shows the 404 page; there is
  no homepage.
- **A5** Favicon changes apply live; title, description and social-preview defaults apply at the
  next publish.
- **A6** `og:url` and `canonical` are dropped from published HTML rather than minted for one host.

**Owed by the co-founder before S2's frontend task:** frames for the four connection-card states,
the "Your Clue address" row with its edit affordance, and the trimmed Pages layout without the
three dropped/deferred cards.

**Owed by the founder in S0:** the dashboard steps of §3, and one owned test hostname for the live
walk.

**Follow-ups recorded, not built here:** head/body snippets (security review: they would need a CSP
relaxation per workspace); apex domains (Ploy-style path proxying or Cloudflare Enterprise apex
proxying); a scheduled re-verification sweep with backoff if customers report silent breakage;
per-hostname HSTS (a customer decision, not ours); moving the remaining backend services to Railway
(the rest of Option C's stage two).
