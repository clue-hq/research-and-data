# Settings API contract — Pages section

Status: as-built contract for Settings → Pages, landed 2026-09-18 on `website/custom-domain` (S2 of
custom-domain publishing). Covers the **Pages section only**; the other settings sections are the
settings-integration slice's to record here.
Spec: `docs/superpowers/specs/2026-09-17-custom-domain-publishing-design.md` §7 (repo root), with
`docs/superpowers/specs/2026-09-15-settings-integration-design.md` §2.2–2.3 for the seam and authority.

**Reconciled 2026-09-17:** the dummy proposes one blob, `GET /api/v1/settings`, with all nine
sections inside. This repo serves **per-section reads under `/frontend/v1`** and each section needs
its own authority, so the Pages section is a dedicated read plus seven further routes under
`/frontend/v1/settings/pages`, taken on this repo's existing seams (`fetchRead` server-side for the
read, `fetchMutation` through the same-origin BFF for writes). **The dummy's
`GET /api/v1/settings` blob is superseded for Pages.** The remaining sections keep the dummy's
`data/settings.fixture.ts` until the settings-integration slice binds them.

## Read (`/frontend/v1`, server, `fetchRead`)

`GET /frontend/v1/settings/pages` → the spec §7.2 shape, camelCase, no envelope wrapper:

```json
{
  "settings": { "fallbackUrl": string|null, "pageTitle": string|null, "pageDescription": string|null,
                "faviconUrl": string|null, "socialPreviewUrl": string|null },
  "systemHostname": { "hostname": string, "label": string, "url": string },
  "customHostname": null | {
    "hostname": string,
    "status": "pending_dns"|"verifying_ownership"|"issuing_certificate"|"active"|"error"|"disconnecting",
    "records": [ { "type": "CNAME"|"TXT", "name": string, "required": string,
                   "observed": string|null, "ok": bool } ],
    "lastCheckedAt": string|null,
    "error": null | { "code": string, "detail": string|null },
    "url": string|null
  }
}
```

`customHostname` is `null` when none is connected; `url` is non-null only when `status == "active"`.
`records` always carries exactly the CNAME and the ownership TXT, in that order.
`faviconUrl` / `socialPreviewUrl` are absolute URLs on the workspace's system hostname
(`…/favicon.ico`, `…/asset-store/<sha256>`) and are `null` until an image is uploaded.

Auth: an active membership (the read surface's workspace dependency). Every **write** below
additionally requires `workspace.manage_settings` (clue_auth policy revision 3 — admin and owner);
without it the route answers `403` `PERMISSION_REQUIRED`.

The GET is not purely passive: when the custom row is non-active it re-derives status from DNS + the
provider, rate-limited to one derivation per 5 s per workspace (spec §7.1/§7.4). It never retries a
stuck removal — only "Check now" does.

## Writes (`/frontend/v1`, browser, `fetchMutation` through `/api/clue/frontend/v1`)

| Method + path | Body | Success | Notes |
| --- | --- | --- | --- |
| `PATCH /settings/pages` | `{ fallbackUrl?, pageTitle?, pageDescription? }` | `200` + the read shape | Partial: an absent key is untouched, an explicit `null` clears. Unknown keys are refused (`extra="forbid"`). |
| `POST /settings/pages/favicon` | multipart `file` | `200` + the read shape | ≤ 256 KB; `image/png`, `image/x-icon`, `image/vnd.microsoft.icon`, `image/svg+xml`. |
| `POST /settings/pages/social-preview` | multipart `file` | `200` + the read shape | ≤ 2 MB; `image/png`, `image/jpeg`. |
| `PATCH /settings/pages/system-hostname` | `{ "label": string }` | `200` + the read shape | The Clue address label (spec §4.1 A1). The old hostname stops resolving immediately; there is no redirect. |
| `POST /settings/pages/custom-hostname` | `{ "hostname": string }` | **`201`** + the read shape | Connect. One custom hostname per workspace. |
| `POST /settings/pages/custom-hostname/check` | — | `200` + the read shape | "Check now". **Membership only** — it reads the world rather than changing it — and it is the one path that retries a stuck `disconnecting` removal. |
| `DELETE /settings/pages/custom-hostname` | — | **`204`**, no body | Ordered removal (row → `disconnecting`, provider delete, row deleted). |

Both uploads go through the same storage path as design assets; there is no second upload route.

## Refusals

Every refusal is the frontend-read envelope: `{ "error": { "code", "message", "requestId" } }`.

| Code | HTTP | When |
| --- | --- | --- |
| `PERMISSION_REQUIRED` | 403 | Any write without `workspace.manage_settings`. |
| `UNAUTHORIZED` | 401 | No principal on a deployment that does not allow local mutations. |
| `VALIDATION_ERROR` | 422 | `fallbackUrl` does not start with `https://`. |
| `UNSUPPORTED_MEDIA_TYPE` | 415 | Upload content type outside the allowed set. |
| `PAYLOAD_TOO_LARGE` | 413 | Upload over the section's byte cap. |
| `PAGES_STORAGE_UNAVAILABLE` | 503 | The deployment has no storage backend. |
| `label_invalid` / `label_reserved` | 422 | Label shape (3–40 of `[a-z0-9-]`, no edge hyphen) / reserved word. |
| `label_taken` | 409 | Another workspace holds that Clue address. |
| `hostname_invalid` | 422 | Not a valid hostname after normalisation. |
| `hostname_reserved` | 422 | Under our own registrable domain (`cluehq.ai`). |
| `hostname_is_apex` | 422 | The hostname equals its registrable domain — a dedicated subdomain is required. |
| `custom_hostname_exists` | 409 | This workspace already has a custom row; remove it first. |
| `hostname_taken` | 409 | The hostname is already connected to a workspace. |
| `PROVIDER_NOT_CONFIGURED` | 503 | Connect on a deployment with no Cloudflare token/zone. Everything else on the screen still works. |
| `provider_error` | 502 | Cloudflare refused. On removal the envelope also carries `"retryable": true` and the row stays `disconnecting`. |
| `CUSTOM_HOSTNAME_NOT_FOUND` | 404 | Removing when nothing is connected. |
| `SYSTEM_HOSTNAME_MISSING` | 500 | The workspace has no system hostname row — run `make pages-backfill-hostnames`. |

The hostname and label codes are the spec's own lowercase codes (from
`clue_spine.hostnames.validate_custom_hostname` / `validate_label`, plus `provider_error`); every
other code is the read surface's uppercase envelope convention. Validation order is
invalid → reserved → apex, so our own zone apex reports `hostname_reserved`, not `hostname_is_apex`.

`customHostname.error.code` on the read is a different, closed set — the provisioning failure the
row last observed, not an HTTP refusal: `cname_incorrect`, `txt_missing`, `caa_blocked`,
`hostname_taken`, `verification_expired`, `provider_error` (spec §7.5).

## Frontend seam

- `src/features/settings/model/pages.ts` — the Zod schemas (`PagesSettingsReadSchema`), the
  `connectionView` / `stepIndex` derivations and `REFUSAL_MESSAGES` (copy per refusal code).
- `src/features/settings/data/pages.repository.ts` — `getPagesSettings()` over `fetchRead`.
  **No fixture mode:** a misconfigured or unauthorised surface throws `ClueApiError` rather than
  rendering an empty screen.
- `src/features/settings/data/pages.actions.ts` — the five JSON mutations over `fetchMutation`
  (`fetchMutation` returns `null` for the 204), plus `uploadPagesImage`, which calls the BFF with a
  raw `fetch` because the browser must set the multipart boundary itself; the BFF catch-all
  (`src/app/api/clue/[...path]/route.ts`) forwards the raw body and headers, so the boundary
  survives the hop.
- `src/features/settings/hooks/use-pages-settings.ts` — holds the read as state, replaces it with
  each mutation's response, and polls `check` every 5 s while the connection view is `connecting`.

The screen is `src/app/(protected)/settings/[[...section]]/page.tsx`; it fetches the Pages read only
for the `pages` section and passes `canManage` from
`session.principal.permissions.includes("workspace.manage_settings")`. A caller without it sees the
section read-only (no input, no Connect, no Check now, no Remove) rather than a hidden section.
