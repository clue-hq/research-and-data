# 2026-09-18 — Custom-domain publishing S2 (custom domains + Settings → Pages)

Branch `website/custom-domain` (the founder's rename of `research-streaming-v3`; same history),
worktree `addis-ababa`, lane DB `clue_addis-ababa@55040` (throwaway, empty, at head `aaff3d831895`).
Spec: `docs/superpowers/specs/archive/2026-09-17-custom-domain-publishing-design.md` §7/§8.2/§10/§11.
Plan: `docs/superpowers/plans/2026-09-17-custom-domain-publishing-s2.md`. Per-task briefs, reports
and the full ruling ledger: `.superpowers/sdd/2026-09-17-custom-domain-publishing-s2/progress.md`.
Predecessor: `_memory/2026-09-17-custom-domain-publishing-s1.md` (system hostnames live).

S2 = a workspace admin connects ONE customer-owned subdomain from Settings → Pages, watches it walk
pending DNS → verifying ownership → issuing certificate → active, and removes it in the spec's
order; the same screen edits the workspace's page defaults and the Clue address label.

## What landed (13 commits, `ab3a3bf7b..6e40162af`)

| Task | Commit(s) | What |
| --- | --- | --- |
| 1 | `0b4efa1ff` | `pages_cname_target`, `cloudflare_zone_id`, `cloudflare_api_token`; `.env.example`/`.env` parity; `tldextract`, `dnspython`, `python-multipart` |
| 2 | `80b761220`, `48745b9d0` | `clue_spine.hostnames`: `validate_custom_hostname` / `validate_label` / `registrable_domain` (offline public-suffix snapshot), the custom-hostname DAL, atomic `replace_system_label` |
| 3 | `98e9edfe9` | `clue_spine.pages_settings` DAL (UNSET-sentinel partial update); the page origin's fallback-URL and favicon reads stop returning `None` |
| 4 | `a2acb2778` | `clue_api.cloudflare_custom_hostnames` — create/get/delete, 10 s timeouts, one retry on 5xx, none on 4xx; the only module that knows Cloudflare's field names |
| 5 | `a2c482d6a` | `dns_observe` (CNAME + TXT over `1.1.1.1`/`8.8.8.8` in a worker thread) and the pure `pages_hostname_status.derive_status` ladder + closed error-code set |
| 6 | `e73e4d620` | `workspace.manage_settings` in the internal policy (revision 3, admin + owner) |
| 7 | `66686c276` | `frontend_read/settings_pages.py`: the §7.2 read, `PATCH`, both multipart uploads, the label change, permission checks |
| 8 | `2437f18a0`, `92be35449` | connect / check / remove against Cloudflare for SaaS; the 5 s check rate limit; the ordered removal with `retryable` |
| 9 | `dc5876774` | design API publish-time defaults (spec §4.2): workspace description fills an empty page description, workspace social preview becomes `og:image` when the page has no image node |
| 10 | `9f954bf67` | frontend `model/pages.ts` (Zod + `connectionView`/`stepIndex`/`REFUSAL_MESSAGES`), `data/pages.repository.ts` (`fetchRead`), `data/pages.actions.ts` (BFF + the raw multipart `fetch`) |
| 11 | `6e40162af` | the dummy's settings shell lifted, the Pages section bound, the four-state custom-domain card, the `/settings/[[...section]]` route, the shared confirmation card |
| 12 | this commit | `apps/frontend/docs/api-contracts/settings.md`, this note, the spec status line |

## The seven plan-level decisions (all reversible; plan §"Decisions this plan makes beyond the spec")

1. `txt_missing` is measured from the row's `created_at`, not from "CNAME correct for 30 minutes" —
   the S1 table has no "CNAME first seen correct" timestamp and adding one is a migration for a timer.
2. The permission check is **local to the settings routes** (the frontend-read app installs no
   `PermissionDenied` handler), raising the FI-1 envelope `403 PERMISSION_REQUIRED` itself.
3. The settings shell is lifted **verbatim** and the non-Pages sections keep the dummy's fixture, so
   the settings-integration merge is a same-file no-op for everything but Pages.
4. **No sidebar entry point** is added — `/settings/pages` is reached by URL until the settings slice
   merges its profile menu. No new visible element.
5. DNS observation runs in a worker thread (`asyncio.to_thread`) because `dnspython`'s resolver is
   synchronous; public resolvers only, 5 s lifetime.
6. Publish-time defaults: description and social preview are applied; **`page_title` is NOT** (the
   document always has a title) and stays the workspace default the screen edits for S3-era consumers.
7. `custom_url` / `custom_origin` appear on publish responses the moment a row reaches `active` — the
   design API's existing `active_custom_hostname` read already does it; no design API change for that.

Execution rulings (each with its cost-if-wrong) are in the ledger; the load-bearing ones:

- **Validation order is invalid → reserved → apex** (the spec enumerates apex before reserved). Our
  own zone apex `cluehq.ai` matches both and must report `hostname_reserved`; every other input
  refuses identically under either order.
- **`check(force=)`** separates "Check now" from the GET's passive refresh: only a forced check
  retries a stuck `disconnecting` delete, so a passive GET can never answer 502.
- **The removal retry sits ABOVE the 5 s DNS rate limit** (fix round 1 on Task 8) — a Check now
  within 5 s of a failed removal must complete the removal, not answer "disconnecting".
- **The Cloudflare client is built once at route registration** (it owns an HTTP client); tests
  inject fakes through `app.state.pages_{cloudflare,resolver,clock}`.
- Task 11's frames gate: the founder said "proceed" without the co-founder's frames, so the
  connection card and the Clue-address row were **built from spec §8.2** with the lifted primitives
  and both files carry a "pending the co-founder's frames (2026-09-18); re-lift when they land"
  marker. Costs one card re-lift if the frames differ.
- One unplanned lifted-file edit accepted: `members-settings.tsx` `variant="primary"` → `"default"`
  (this repo's button has no `primary`; the dummy declares `default` as its alias). One word.

## Tests actually run (per the task reports in `.superpowers/sdd/…`)

- `uv run pytest tests/test_pages_settings.py -q -p no:warnings` → 4 passed.
- `tests/clue_spine` → **79 passed** (48 pre-existing + 28 new pure + 3 new DB); `tests/auth` → **51
  passed** (S1 baseline 50, +1).
- `tests/clue_spine/test_pages_settings_db.py` + `tests/page_origin` → **19 passed**.
- `tests/api/test_cloudflare_custom_hostnames.py` → **5 passed** (`httpx.MockTransport`, no network).
- `tests/api/test_dns_observe.py` + `tests/api/test_pages_hostname_status.py` → **17 passed**.
- `tests/api/test_frontend_read_settings_pages_db.py` → **10 passed**, 0 skipped (4 from Task 7, 5
  from Task 8, 1 from the fix round); `tests/api/test_frontend_read_artifacts_db.py` → 6 passed
  (the envelope regression guard).
- Design API from `subsystems/clue-design/apps/api`: `tests/test_public_pages.py` → **4 passed**,
  `tests/test_web_export.py -k host_independent` → 1 passed (`-k publish` → 11 passed).
- Frontend: `npm test` → **2294 pass / 0 fail** (113 suites); `npm run lint` → 0 errors, 2 warnings
  (the pre-existing `canvasOperations.ts` unused-vars); `npx tsc --noEmit` **57 → 57, delta 0**.
- Static gates throughout: `ruff format --check` / `ruff check` clean on touched paths; `uv run mypy`
  at the known baseline **4 errors in 3 files** (`ad_assets.py`, two `arv2/*` — pre-existing);
  `lint-imports` **28 kept**.
- Known reds that are **not ours**, proven at base `66686c276`: six in
  `tests/api/test_frontend_read_app.py` / `tests/api/test_projections_app.py` /
  `tests/api/test_frontend_read_accounts_list.py`.

## Owed / not run (honest list)

- **The live Cloudflare acceptance walk (spec §10)** — founder-triggered, needs a founder-owned
  hostname: the whole ladder to active through the screen, the page rendering on it, and removal
  returning it to 404 within a minute while the system hostname keeps serving. **NOT run.** Nothing
  hosted exists yet (S0 is still the founder-operated runbook `docs/specs/pages-hosting-runbook.md`).
- **The dev-stack walk of Settings → Pages** (autosave, the favicon served by the origin at
  `http://<label>.pages.localhost:8040/favicon.ico`, the label change updating the share menu's host,
  an apex refused inline) — **NOT run**; no stack was started during the slice.
- **`cd apps/frontend && npm run build`** — **NOT run**, port 3020 was busy. Substitute evidence is
  `npx tsc --noEmit` at an unchanged 57; it does not exercise Next's build-time route/type generation.
- **The co-founder's frames** for the connection card and the Clue-address row — owed. Both files are
  built from spec §8.2 prose and marked for re-lift.
- **The whole-branch final review** — runs after this task.
- `DbPageReads`' real database reads are still exercised by no committed test (Task 3's live proof was
  a rolled-back smoke against the lane DB); the dev-stack walk is their first real exercise.

## Settings-integration merge reconciliation

**DONE 2026-09-28** — the settings slice arrived with the F5 merge (`22a581ea4`) and was reconciled there: its shell won, our `data/settings.fixture.ts` / `data/settings.repository.ts` / `components/settings-autosave-input.tsx` were deleted, and Pages was bound through the slice's `readSettingsSection` (`de80c454d`). Record: `_memory/2026-09-28-custom-domain-f5-reconciliation.md`. The list below is the pre-merge plan, kept as written.

The settings-integration slice (Profile / Workspace / Members) is on another branch. When it merges,
these files under `apps/frontend/src/features/settings/` are **byte-identical to the dummy**
(port-of-spain `93c6120`, branch `codex/artifacts-page`) and should merge as a no-op — take either side:

`components/settings-sidebar.tsx`, `components/settings-nav-icon.tsx`,
`components/settings-primitives.tsx`, `components/settings-coming-soon.tsx`,
`components/connections-settings.tsx`, `components/profile-settings.tsx`,
`components/workspace-settings.tsx`, `components/data-model-settings.tsx`,
`components/billing-settings.tsx`, `config/settings-navigation.ts`, `model/settings.ts`,
`data/settings.fixture.ts`.

S2 changed exactly four of the lifted files, plus one rewrite:

| File | S2's change |
| --- | --- |
| `components/settings-screen.tsx` | `canManage` + `pages` props threaded through `SettingsScreen`/`SettingsBody`; the `pages` branch renders `<PagesSettings>` (and throws on a null read rather than rendering empty). |
| `data/settings.repository.ts` | Fixture-only rewrite — `createHttpSettingsRepository` and the `CLUE_API_BASE_URL` selection deleted, `getSettingsWorkspace` → `getSettingsFixture`. The settings slice's real per-section repositories replace this. |
| `components/members-settings.tsx` | **One token**: `variant="primary"` → `"default"` (compile fix; the dummy declares them aliases). |
| `components/settings.module.css` | Verbatim + **one appended class**, `.statusDot`. |
| `components/pages-settings.tsx` | **Not a lift — a rewrite.** The dummy's Pages section (search-engine settings, code snippets, AI crawler discovery) is gone; the §8.2 field set replaces it. Take S2's side. |

New in S2 and not the settings slice's to reconcile: `components/custom-domain-card.tsx`,
`components/settings-autosave-input.tsx`, `hooks/use-pages-settings.ts`, `model/pages.ts` (+ its
test), `data/pages.repository.ts`, `data/pages.actions.ts`,
`src/app/(protected)/settings/[[...section]]/{page,error,loading}.tsx`,
`src/components/ui/confirmation-card.tsx`. The contract resolution is recorded in
`apps/frontend/docs/api-contracts/settings.md` (Pages section only).

## Carried defects / deferred minors

Every `minor (deferred)` line is in the ledger. The ones worth carrying forward:

- `_service`'s name-based `hasattr` probe on `app.state` would degrade production to
  `cloudflare=None` if an unrelated `pages_*` attribute ever appeared there.
- `read_with_refresh` re-derives an **error**-status row on every GET (spec §7.1 as written; the 5 s
  rate limit is the only brake).
- `set_custom_hostname_provider` / `set_custom_hostname_status` are silent on a missing row.
- `SettingsAutosaveInput` never re-syncs from props, so a server-side normalisation of, say,
  `fallbackUrl` would not appear until reload.
- The confirmation card shows a `Check` icon for the error tone (only the colour changes), and a
  connect refusal is reported twice — inline under the input *and* in the card.
- Six design-system tokens the dummy's confirmation card uses do not exist here and were substituted
  (`surface-inverse`→`primitives-gray-900`, `text-inverse`→`content-knockout`, `success`/`danger`→
  `primitives-positive-400`/`critical-400`, `radius-md`→`button-md-radius`); add the semantic tokens
  or accept the primitives.
- `canManage` is `false` when authentication is disabled (`getProtectedSession()` returns `null`), so
  the whole screen is read-only on an auth-disabled local stack. Safe direction, looks like a bug.
- `label_taken` / `label_reserved` / `label_invalid` are not in `REFUSAL_MESSAGES`; the server's own
  message is shown. The polling and the remove→check sequencing have no unit test.
- Still open from S1: reserved slugs are not refused at publish time; no `sniff_mime` fallback on the
  origin's `/asset-store/{digest}`; the design subsystem's own `webDocuments.ts` still types `url`
  as a path.

## Addendum 2026-09-18 — whole-slice final review (Fable) + close-out
- Final review found one Important in the Pages hook: a provider-failed removal (502) left the screen on
  "active" with no polling while the backend row was already `disconnecting`. Fixed in `9f3c361ae`
  (adopt `disconnecting` locally on a 502 → view flips to connecting → the 5 s forced-check poll
  retries the delete to completion). npm test 2295/2295.
- Rulings taken during S2 SDD (all reversible): Task 11 built the connection card + Clue-address row
  from spec §8.2 with the lifted primitives pending the co-founder's frames (files carry the marker);
  hostname validation order is invalid → reserved → apex (our own zone apex reports "reserved");
  `check(force=)` — a passive GET never retries a failing provider delete, only Check now does; the
  `disconnecting` retry runs above the 5 s DNS rate limit; the one-token `variant="primary"` →
  `"default"` edit in the lifted `members-settings.tsx` (this repo's button has no `primary`).
- Exit gate 2026-09-18: root 185 tests green; design API `test_public_pages` + `test_web_export`
  green; ruff/mypy (4 baseline)/lint-imports (28) clean; npm test 2295, lint 0 errors.
  Still owed: `npm run build` (port 3020 busy with a founder stack), the dev-stack walk of
  Settings → Pages, the live Cloudflare acceptance (spec §10), the frames re-lift.
