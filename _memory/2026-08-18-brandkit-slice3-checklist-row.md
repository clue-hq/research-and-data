# Brand-kit × onboarding — Slice 3: the checklist row goes live (2026-08-18)

Branch `feature/brandkit-onboarding-integration`. Commit `18dcc2b9`. Backend + frontend.

## What shipped

The onboarding setting-up checklist's **"Creating brand kit"** row stopped being the
founder-ratified explicit dummy (forced `queued` since FI-4 slice 3) and now reports slice 2's
real `design_ingestion_job` status.

- **Backend** — `GET /stage0/setup/current` gains the additive, nullable
  `brand_kit_ingestion: {job_id, status} | null` (`SetupBrandKitIngestion`). Read once at the top
  of `current_setup` via `clue_design.ingestion.list_recent(limit=1)` (the sanctioned platform-side
  DAL port slice 2 already uses) and threaded into **all four** response constructions —
  `unavailable`, `_serve_lane_truth`, the `starting` branch, `none`. `status` is the
  `design_ingestion_status` enum served raw; no derivation server-side.
- **Frontend** — `SetupStatusSchema` gains a tolerant `SetupBrandKitIngestionSchema`
  (`.nullable().optional().default(null)`; job status `.catch("running")` so a future status
  degrades to in-flight, never to a claimed kit). `deriveSetupItems`'s force-downgrade is replaced
  by the pure `brandKitItem`.

## The mapping (binding controller ruling on the failed case)

| wire | row | detail |
|---|---|---|
| absent / `null` | `queued` | unchanged |
| `queued` / `running` | `running` | unchanged |
| `succeeded` | `complete` | unchanged |
| `failed` | `queued` | + the EXISTING `FAILED_MEMBER_ANNOTATION` (`" — part of this hit a problem"`) |
| unrecognized | `running` | unchanged |

`failed → complete` would claim a kit that was never produced, and the row schema has no failed
state, so the failure rides the detail line — the same idiom a failed recon field uses on its
group. No new copy invented. Slice 4's manual trigger is the rescue path.

The brand-kit row sits **outside** the D-6 group reduction: lane truth, the halt rule and the
index-0 warm-up rule never touch it (tested both directions).

## Recordings

- `apps/frontend/docs/api-contracts/onboarding.md` — new "Brand-kit checklist row goes live"
  section (wire shape + mapping table), the JSON example, the field bullet, and the two stale
  "explicit dummy / when the design branch merges" lines corrected.
- `docs/specs/FI-onboarding-contract-gap-review.md` §9 — a NEW dated 2026-08-18 entry superseding
  the 2026-08-12 "brand-kit stays out" ruling (the old entry got a one-line
  `[SUPERSEDED …]` pointer only; append-only log discipline).

## Live verification (three fresh first-time onboardings, real Clerk sign-ups)

Stack 8014 (design, `LUMEN_CORE_HELPER` from the istanbul worktree — `crates/` diff-identical) /
8034 (platform, `CLUE_SELF_SERVE_PROVISIONING_ENABLED=true`,
`CLUE_DESIGN_API_BASE_URL=http://127.0.0.1:8014`) / 3034 (frontend). Shared dev DB 55040.
gstack `/browse` headless only.

- `onboarding+clerk_test_20260818s3@example.com` — Vercel, ws `ws_3e83adb8b3dc461e98e42d3d07c6e265`,
  job `ingest_90501c23…` succeeded in ~4.6s (flip outran the first screenshot).
- `onboarding+clerk_test_20260818s3b@example.com` — Notion, ws `ws_41872584ef7345c190f2c703e01f4133`,
  job `ingest_0c11d851…`.
- `onboarding+clerk_test_20260818s3c@example.com` — **Figma**, ws
  `ws_8a5ee09e3aef4c37b405b96037c520ea`, brand `brd_3de0f9f8…`, job `ingest_621c7f75…`
  created 14:54:18.86 → succeeded 14:54:36.57 (~18s). **Both states captured on this one run:**
  spinner at 14:54:20.1 (`/tmp/slice3-brandkit-running.png`), checkmark after the flip
  (`/tmp/slice3-brandkit-complete2.png`).
- Wire proof (browser fetch through the BFF): `{"status":"starting","brand_kit_ingestion":
  {"job_id":"ingest_621c7f75…","status":"succeeded"}}`.
- **Failed branch also proven live**: a synthetic `failed` job row inserted for the Figma
  workspace made the row render `queued` + `" — part of this hit a problem"`
  (`/tmp/slice3-brandkit-failed.png`); the probe row was then DELETED and the row returned to
  `complete`. No other dev data touched.

**Leave these accounts' data in place — later slices use them.**

## Gotchas found

- `browse`'s `$B js` samples at ~30ms, so a naive "40 iterations" loop covers ~1-2 seconds, not
  ~10. Timestamp the samples or the running state looks like it never happened.
- Signing out between runs needs the `/sign-out` page's **button click** (visiting the route is
  not enough); otherwise the next sign-up shows "You're already signed in."
- The setting-up row's status is only readable in the DOM as the CSS-module class
  (`setupRow_running` / `setupRow_complete`; `queued` renders as `setupRow undefined`, since the
  module has no `setupRow_queued` rule) — the label text is identical in all three states.

## Follow-ups / open

- The fixture progress script reports `brand_kit_ingestion: null` on every frame (it replays recon
  vocabulary only), so the scripted preview leaves the row `queued`. Honest, but if slice 4+ wants
  fixture theatre for the kit, that is where to add it.
- Slice 4 owns the manual trigger + approval gate; it is the documented rescue path for a `failed`
  job, and the annotation copy above is what points at it.
