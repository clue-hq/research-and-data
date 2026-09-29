# Pages hosting runbook — Stage S0 (founder-operated)

Stand up the hosted pieces that custom-domain publishing needs: a hosted Postgres, a hosted blob
store, the Railway `page-origin` service, Cloudflare for SaaS, the system-hostname wildcard, and the
`pages-edge` Worker. Everything here is done by hand in the Railway and Cloudflare dashboards; the
code it deploys is already on the branch (S1, see the session record).

- Design spec: `docs/superpowers/specs/2026-09-17-custom-domain-publishing-design.md` (§3 is this
  runbook's source; §3 item 7 is the acceptance walk in section 7 below).
- S1 session record: `_memory/2026-09-17-custom-domain-publishing-s1.md`.
- Local dev equivalent of all of this: `DEV_STACK.md` (port 8040, `*.pages.localhost`).
- Today's hosting posture this stage changes: `docs/specs/demo-2026-08-29-runbook.md`.

**Secrets never go in this file.** Record a secret's *name* and where it lives (Railway variable,
`wrangler secret`, `.env`), never its value. Angle-bracket placeholders below are values the
operator reads out of a dashboard.

Order matters: section 1 and 2 first (the origin needs a database and a blob store), then 3, then
4 and 5 (Cloudflare in front of it), then 6 (the Worker), then 7 (acceptance).

---

## Values recorded

Fill this in as you go; every row is also captured in its section's table.

| Value | Recorded |
| --- | --- |
| Railway project | `<railway-project-name>` |
| Railway Postgres service | `<postgres-service-name>` |
| Cloudflare account id | `<account-id>` |
| Cloudflare zone id (`cluehq.ai`) | `<zone-id>` |
| R2 bucket | `<bucket>` |
| R2 S3 endpoint | `https://<account-id>.r2.cloudflarestorage.com` |
| Railway origin service | `page-origin` |
| Origin public domain | `page-origin.cluehq.ai` |
| System suffix | `pages.cluehq.ai` |
| Fallback origin (Cloudflare for SaaS) | `pages.cluehq.ai` |
| Advanced certificate order id | `<cert-order-id>` |
| Advanced certificate price | `<price-shown>` |
| Worker name / deployed version | `pages-edge` / `<version-id>` |
| Secret names in use (values elsewhere) | `CLUE_PAGES_EDGE_SECRET` (Railway), `EDGE_SECRET` (Worker) |

---

## 1. Hosted Postgres (Railway)

The lane's local database is **not** promoted. A fresh hosted database starts empty apart from
migrations.

1. In the existing Railway project: **New → Database → Add PostgreSQL**.
2. Copy its connection string from the service's **Variables** tab. The repo needs the async form —
   `postgresql+asyncpg://…`, not `postgres://…`. Keep it in a scratch shell only.

```bash
export RAILWAY_DSN='postgresql+asyncpg://<user>:<password>@<host>:<port>/<database>'
```

3. Reversibility smoke **against a copy first**, never the real one (`db-smoke` runs
   `upgrade head → downgrade base → upgrade head`):

```bash
# create a throwaway database on the same Railway Postgres (or locally), then:
CLUE_DATABASE_URL="$RAILWAY_SMOKE_DSN" make db-smoke
```

4. Migrate the real database to head, and confirm one head:

```bash
CLUE_DATABASE_URL="$RAILWAY_DSN" uv run alembic upgrade head
CLUE_DATABASE_URL="$RAILWAY_DSN" uv run alembic heads
```

5. Allocate system hostnames for any workspace that predates the migration. On a fresh database
   this writes nothing — that is the expected answer, not a failure:

```bash
make pages-backfill-hostnames ARGS="--database-url $RAILWAY_DSN --dry-run"
make pages-backfill-hostnames ARGS="--database-url $RAILWAY_DSN"
# {"missing": 0, "written": 0, "off_suffix": 0}
```

`off_suffix` counts system rows that do not end in the configured suffix — a non-zero value means
some process ran with the wrong `CLUE_PAGES_SYSTEM_SUFFIX`; fix the config before going further.

**Since the 2026-09-28 F5 reconciliation** (`_memory/2026-09-28-custom-domain-f5-reconciliation.md`):

- **`design_workspace_handle` no longer exists.** Migration `770bf20802e1` turned every F5 workspace
  handle into that workspace's system label (`<handle>.<suffix>`, carrying the handle's lock over) and
  dropped the table. A workspace that already had a system row kept it. The suffix the backfill wrote
  is the `CLUE_PAGES_SYSTEM_SUFFIX` in force **when the migration ran** (`alembic/env.py` passes it to
  SQL; unset means the settings default `pages.cluehq.ai`), so run step 4 with the production suffix —
  a wrong one shows up as `off_suffix` above. A handle whose hostname another workspace already held
  was skipped; step 5 allocates that workspace a label.
- **A label locks at the workspace's first publish** (`workspace_hostname.locked_at`, set by the
  design API's publish). After that, `PATCH /frontend/v1/settings/pages/system-hostname` is refused
  with `label_locked`. There is no unlock route; unlocking is a deliberate operator `UPDATE`.

6. Repoint the local services (platform API, design API, workers) by setting `CLUE_DATABASE_URL` in
   the checkout's `.env` to the Railway DSN, then restart the stack (`./scripts/dev_stack.sh down`
   then `up`). The local Postgres stays untouched as a fallback.

**Recorded values**

| Item | Value |
| --- | --- |
| Railway project | `<railway-project-name>` |
| Postgres service name | `<postgres-service-name>` |
| Database name | `<database>` |
| Alembic head after upgrade | `<revision>` |
| `db-smoke` on the copy | `<pass/fail>` |
| Backfill output | `<{"missing": …, "written": …, "off_suffix": …}>` |
| Date `.env` repointed | `<date>` |

---

## 2. R2 bucket

The origin and the design API read the same blobs, so both must point at the same bucket. R2 is used
through the repo's existing S3 backend — no new code.

1. Cloudflare dashboard → **R2 → Create bucket** → name `<bucket>`, location Automatic. Record the
   **account id** shown on the R2 overview page.
2. **R2 → Manage R2 API Tokens → Create API token**, permission **Object Read & Write**, scoped to
   `<bucket>`. Copy the Access Key ID and Secret Access Key **once** (Cloudflare shows the secret a
   single time).
3. Set these in the Railway `page-origin` service variables (section 3) **and** in the local `.env`:

```bash
CLUE_STORAGE_BACKEND=s3
CLUE_STORAGE_S3_BUCKET=<bucket>
CLUE_STORAGE_S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
CLUE_STORAGE_S3_REGION=auto
CLUE_STORAGE_S3_ACCESS_KEY_ID=<from the R2 token>
CLUE_STORAGE_S3_SECRET_ACCESS_KEY=<from the R2 token>
```

Leave `CLUE_STORAGE_FS_ROOT` in place; it is ignored while the backend is `s3`.

4. Verify locally before the origin exists: restart the design API with the new variables, upload an
   image in the editor, and fetch it back through the design API's own blob route:

```bash
curl -s -o /dev/null -w '%{http_code} %{content_type}\n' http://127.0.0.1:8010/asset-store/<sha256>
# 200 image/png
```

Also confirm the object landed in the bucket (R2 → `<bucket>` → Objects).

**Recorded values**

| Item | Value |
| --- | --- |
| Account id | `<account-id>` |
| Bucket | `<bucket>` |
| S3 endpoint | `https://<account-id>.r2.cloudflarestorage.com` |
| Token name (value not recorded) | `<token-name>` |
| Local upload + `/asset-store` fetch | `<pass/fail>` |

---

## 3. Railway service `page-origin`

The origin image is built from the repo root by `platform/page_origin/Dockerfile.railway`; its entry
point is the uvicorn **factory** `clue_page_origin.main:build_application` (the container runs
`python -m clue_page_origin.main`, which binds `PORT` if Railway injects it, otherwise
`CLUE_PAGES_ORIGIN_PORT`).

1. Railway project → **New → GitHub Repo** → this repo. Service name `page-origin`.
2. **Settings → Source**: branch `<branch>` (the branch carrying S1). **Root Directory: leave
   unset** — the Dockerfile copies from the repo root.
3. **Settings → Build**: add the service variable

```bash
RAILWAY_DOCKERFILE_PATH=/platform/page_origin/Dockerfile.railway
```

4. **Settings → Deploy → Health Check Path**: `/healthz`.
5. **Variables** (in addition to the `CLUE_STORAGE_*` block from section 2):

```bash
CLUE_DATABASE_URL=<railway async DSN from section 1>
CLUE_PAGES_SYSTEM_SUFFIX=pages.cluehq.ai
CLUE_PAGES_PUBLIC_SCHEME=https
CLUE_PAGES_PUBLIC_PORT=
CLUE_PAGES_TRUST_HOST_HEADER=false
CLUE_PAGES_EDGE_SECRET=<generated below>
```

Generate the shared secret once and keep it in the password manager — the same value goes into the
Worker in section 6:

```bash
openssl rand -hex 32
```

`CLUE_PAGES_TRUST_HOST_HEADER=false` is what makes the origin refuse anything that did not come
through the Worker. Never set it `true` on a hosted service.

6. **Settings → Networking → Public Networking → Custom Domain** → `page-origin.cluehq.ai`. Railway
   shows a CNAME target and a `_railway-verify` TXT record. Create both in the `cluehq.ai` zone as
   **DNS-only (grey cloud)** records — exactly like `app.cluehq.ai` today. Wait for Railway to show
   the domain as active.

7. Verify (from any machine):

```bash
curl -s https://page-origin.cluehq.ai/healthz
# {"status":"ok"}

curl -s -o /dev/null -w '%{http_code}\n' https://page-origin.cluehq.ai/anything
# 403

curl -s -o /dev/null -w '%{http_code}\n' \
  -H 'X-Clue-Public-Host: x.pages.cluehq.ai' https://page-origin.cluehq.ai/anything
# 403   (a forged host with no edge secret is still refused)
```

**Recorded values**

| Item | Value |
| --- | --- |
| Service name | `page-origin` |
| Branch deployed | `<branch>` |
| Deployed commit | `<sha>` |
| Public domain | `page-origin.cluehq.ai` |
| Railway CNAME target | `<railway-cname-target>` |
| `_railway-verify` TXT created | `<yes/no>` |
| Edge secret name (value elsewhere) | `CLUE_PAGES_EDGE_SECRET` |
| `/healthz` / unsigned / forged-host checks | `<pass/fail>` |

---

## 4. Cloudflare for SaaS

1. Cloudflare dashboard → zone `cluehq.ai` → record the **zone id** from the Overview page.
2. **SSL/TLS → Custom Hostnames** → enable **SSL for SaaS**.
3. Fallback origin: `pages.cluehq.ai`. Cloudflare will ask for it to resolve, so first create the
   DNS record:

   **DNS → Records → Add record**: type `CNAME`, name `pages`, target `page-origin.cluehq.ai`,
   **Proxied (orange cloud)**.

4. Back in **Custom Hostnames**, set the fallback origin to `pages.cluehq.ai` and wait for it to
   report active. The CNAME target customers will be given is `pages.cluehq.ai`.
5. Custom hostnames themselves are created by S2's control plane. S0 creates exactly **one** by hand
   for the acceptance walk in section 7 (HTTP certificate validation, default TXT ownership record)
   and deletes it afterwards.

**Recorded values**

| Item | Value |
| --- | --- |
| Zone id | `<zone-id>` |
| SSL for SaaS enabled | `<date>` |
| Fallback origin | `pages.cluehq.ai` |
| `pages` CNAME → `page-origin.cluehq.ai`, proxied | `<yes/no>` |
| Fallback origin status | `<active/pending>` |

---

## 5. System hostnames

1. **DNS → Records → Add record**: type `CNAME`, name `*.pages`, target `page-origin.cluehq.ai`,
   **Proxied (orange cloud)**. This is what makes `<label>.pages.cluehq.ai` resolve.
2. Universal SSL does **not** cover a second-level wildcard, so the certificate must be ordered:
   **SSL/TLS → Edge Certificates → Order Advanced Certificate**. Hostnames: `*.pages.cluehq.ai`
   **and** `pages.cluehq.ai`. Certificate authority and validation method: whatever the dashboard
   defaults to (TXT validation is fine — we control the zone). **Record the price the dashboard
   shows** before confirming.
3. Wait for the certificate to reach **Active** (typically minutes; can take longer on DCV).
4. Verify the certificate actually covers a third-level name:

```bash
curl -sI https://anything.pages.cluehq.ai/ | head -1
```

What is being tested here is the **TLS handshake**: if `curl` returns any HTTP status instead of a
certificate error, the wildcard certificate is live. The status itself is a 404 either way — before
section 6 it is Railway's fallback (the Host is not a domain Railway knows), and after the Worker is
deployed it is the origin's own 404 for a label no workspace owns.

**Recorded values**

| Item | Value |
| --- | --- |
| `*.pages` CNAME → `page-origin.cluehq.ai`, proxied | `<yes/no>` |
| Advanced certificate order id | `<cert-order-id>` |
| Hostnames on the certificate | `*.pages.cluehq.ai`, `pages.cluehq.ai` |
| Price shown | `<price-shown>` |
| Status / activation date | `<active date>` |

---

## 6. Worker `pages-edge`

The Worker sits on a zone-wide route, forwards `*.pages.cluehq.ai` and every Cloudflare for SaaS
custom hostname to the origin stamping `X-Clue-Public-Host` and `X-Clue-Edge-Auth`, and passes
through every other proxied record untouched. Source and details:
`infra/cloudflare/pages-edge/README.md`; configuration (`SYSTEM_SUFFIX`, `ORIGIN_HOST`, the route)
is in `infra/cloudflare/pages-edge/wrangler.toml`.

```bash
cd infra/cloudflare/pages-edge
npx wrangler login
npx wrangler secret put EDGE_SECRET     # paste the SAME value as CLUE_PAGES_EDGE_SECRET
npx wrangler deploy
```

If the secret and `CLUE_PAGES_EDGE_SECRET` differ, every page request 403s — that is the first thing
to check if section 7 fails.

Routing tests (no deployment needed, run from the repo root; the glob form is required on
Node ≥ 22):

```bash
node --test 'infra/cloudflare/pages-edge/*.test.js'
```

After deploying:

1. Dashboard → **Workers & Pages → pages-edge → Settings → Domains & Routes**: confirm the route
   `*/*` on zone `cluehq.ai`, and that `SYSTEM_SUFFIX=pages.cluehq.ai` /
   `ORIGIN_HOST=page-origin.cluehq.ai` are the deployed variables.
2. Confirm the Worker does not touch the app. `app.cluehq.ai` is a DNS-only (grey-cloud) record, so
   Workers never see it:

```bash
curl -sI https://app.cluehq.ai | head -1
```

The app must answer exactly as it did before the deploy and still load in a browser — unchanged
status, no Worker-added headers, no redirect to the origin.

**Recorded values**

| Item | Value |
| --- | --- |
| Worker name | `pages-edge` |
| Deployed version id | `<version-id>` |
| Route | `*/*` on `cluehq.ai` |
| `SYSTEM_SUFFIX` / `ORIGIN_HOST` | `pages.cluehq.ai` / `page-origin.cluehq.ai` |
| `EDGE_SECRET` matches the Railway variable | `<yes/no>` |
| `app.cluehq.ai` unaffected | `<pass/fail>` |

---

## 7. Acceptance (spec §3 item 7)

Run this once, end to end, after sections 1–6. It is the S0 exit gate.

**a. A page on a system hostname.** Publish a web page from the app (the publish allocates the
workspace's system hostname if it has none), or take an already-published one and read its label:

```bash
psql "<railway psql DSN>" -c \
  "select workspace_id, hostname, kind, status from workspace_hostname order by created_at desc limit 5;"
```

If the workspace has no system row (an old workspace, pre-migration), run the section 1 backfill
again rather than inserting by hand — it picks the label. A system row can also be inserted
directly; it must be `active` and must leave the Cloudflare columns null (table CHECKs
`workspace_hostname_system_is_active` / `workspace_hostname_system_columns`):

```bash
psql "<railway psql DSN>" -c \
  "insert into workspace_hostname (hostname, workspace_id, kind, status)
   values ('<label>.pages.cluehq.ai', '<workspace-id>', 'system', 'active');"
```

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://<label>.pages.cluehq.ai/<slug>
# 200
curl -s https://<label>.pages.cluehq.ai/<slug> | head -20
# the published HTML
```

Open it in a browser: the certificate must be valid (no warning), the page's CSS/JS load from
`/p-assets/…` and its images from `/asset-store/…`, and the console shows no CSP errors.

**b. A founder-owned custom hostname, by hand.**

1. Cloudflare → zone `cluehq.ai` → **SSL/TLS → Custom Hostnames → Add Custom Hostname** →
   `<custom-hostname>` (a subdomain you own, e.g. `go.<your-domain>`), HTTP certificate validation.
2. In **that domain's own DNS** (not the cluehq.ai zone), add the CNAME
   `<custom-hostname>` → `pages.cluehq.ai` and the ownership TXT record Cloudflare displays.
3. Wait for the custom hostname to show **Active**.
4. Bind it locally to the same workspace:

A `custom` row must carry the CNAME target and the ownership TXT record Cloudflare gave you — the
`workspace_hostname_custom_columns` CHECK rejects it otherwise (S2's control plane writes these from
the API response; here you copy them out of the dashboard):

```bash
psql "<railway psql DSN>" -c \
  "insert into workspace_hostname
     (hostname, workspace_id, kind, status, cf_custom_hostname_id,
      cname_target, ownership_txt_name, ownership_txt_value, activated_at)
   values ('<custom-hostname>', '<workspace-id>', 'custom', 'active', '<cf-custom-hostname-id>',
           'pages.cluehq.ai', '<ownership-txt-name>', '<ownership-txt-value>', now());"
```

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://<custom-hostname>/<slug>
# 200   — the same page, on the customer hostname
```

**c. The origin refuses anything that did not come through the edge.**

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://page-origin.cluehq.ai/<slug>
# 403
curl -s -o /dev/null -w '%{http_code}\n' \
  -H 'X-Clue-Public-Host: <label>.pages.cluehq.ai' https://page-origin.cluehq.ai/<slug>
# 403   — forged host, no secret
```

**d. Clean up the hand-made custom hostname.** Cloudflare configuration first, then the local row
(the spec's removal order):

```bash
# 1. Cloudflare → Custom Hostnames → delete <custom-hostname>
# 2. then:
psql "<railway psql DSN>" -c \
  "delete from workspace_hostname where hostname = '<custom-hostname>';"
```

Re-check that the system hostname still serves the page (rule 7: it stays live before, during and
after custom-domain setup, and after removal).

**Recorded values**

| Check | Result |
| --- | --- |
| Date run | `<date>` |
| Workspace / label / slug used | `<workspace-id>` / `<label>` / `<slug>` |
| `https://<label>.pages.cluehq.ai/<slug>` | `<200 + valid cert / …>` |
| Assets + CSP in the browser console | `<clean / …>` |
| Custom hostname used | `<custom-hostname>` |
| `https://<custom-hostname>/<slug>` | `<200 / …>` |
| Direct origin without the secret | `<403 / …>` |
| Forged `X-Clue-Public-Host` without the secret | `<403 / …>` |
| Custom hostname + row removed, system hostname still live | `<yes/no>` |

---

## Not done yet

S0 is Option C **stage one**: the shared stores move to hosted services, the origin is hosted, and
nothing else does.

- **Platform API, design API and the fleet workers still run on the founder's machine** behind ngrok
  (`docs/specs/demo-2026-08-29-runbook.md`), now reading the hosted Postgres and the R2 bucket. They
  move to Railway on their own schedule — Option C stage two, unscheduled.
- **The custom-domain control plane is S2**: connect / check / remove, the Cloudflare API client, DNS
  observation of the ownership TXT, the label change, and the Settings → Pages screen. In S1 a custom
  hostname can only be created by hand, as section 7 does.
- **`workspace_pages_settings` has no reader yet** — the fallback URL and favicon seams on the origin
  return nothing until S2 fills them.
- **No scheduled re-verification sweep** (spec A3: on demand plus screen polling).
- **Apex domains, more than one custom hostname per workspace, and head/body HTML snippets** are out
  of v1 (spec §1).
