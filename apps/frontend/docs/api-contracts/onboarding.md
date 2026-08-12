# Onboarding API contract

Status: **slices 1–3 implemented** (2026-08-13) — authentication, workspace provisioning,
the setup composition, and per-field recon progress are all live against the backend.
This document records the **ratified** contract (FI-4, `docs/specs/FI-onboarding-contract-gap-review.md`
§8/§9); the original frontend-authored proposal it replaces is preserved in git history.

Figma source: production Clue file, `onboarding-flow` page (`1634:16661`), the seven frames
marked Ready for dev — **visually frozen** (§9 ruling 2026-08-12). One screen was added beyond
the approved set by founder ruling: `verify-email`, designed in-house within the frozen visual
vocabulary.

## Authentication (D-1, ratified)

**There are no backend authentication endpoints.** The previously proposed
`POST /api/v1/auth/{google,sign-in,sign-up}` are rejected — they contradicted the Lane-B
contract (`session.md`). Clerk owns credential verification and the session cookie,
**headlessly**: the frozen screens render every pixel and drive Clerk's custom-flow API
(`password()`, `sso()`, `verifications.sendEmailCode()/verifyEmailCode()`, `finalize()`)
through the `OnboardingAuthAdapter` seam (`src/features/onboarding/data/onboarding-auth.tsx`).
No Clerk component renders anywhere in onboarding. Operational preconditions (founder-ratified):
Clerk bot protection **disabled instance-wide** (no CAPTCHA element mounts); email
verification **on**, served by the `verify-email` step.

Flow: `sign-in`/`sign-up` (provider choice) → email screens → (`verify-email` on sign-up) →
sign-in completes to `/session/establish`; sign-up completes to `profile`. Google OAuth lands
on `/onboarding/sso-callback` (handles first-time-user transfer) and completes to
`/session/establish`. A session without a Clue identity or membership is routed by the session
DAL to `/onboarding/profile` (never `/access-denied`); the codes are
`IDENTITY_NOT_PROVISIONED` and `WORKSPACE_MEMBERSHIP_REQUIRED`.

With `CLUE_AUTH_ENABLED` unset/false, the whole flow runs in **fixture mode**: identical
screens, navigation theatre, no network. `?hold=1` still freezes the setup timer for visual QA.

## Read flow configuration (D-7, ratified)

`GET /api/v1/onboarding` is **retired**. Screen copy, role options, and the setup checklist
art are frontend-owned fixture data (`onboarding.fixture.ts`), validated by
`OnboardingFlowSchema`. Serving button copy over HTTP earned nothing, and the old adapter's
direct-origin fetch crashed auth-configured environments (defect F1).

## Provisioning (D-2/D-3, ratified — replaces `PUT /api/v1/onboarding/profile`)

`POST /api/onboarding/provision` (same-origin Next handler) → backend
`POST /auth/v1/provision`. The dedicated handler exists because the generic `/api/clue` BFF
requires a resolved membership before proxying, and provisioning is the call that creates the
first membership. Requires a live Clerk session; no membership.

Request (snake_case, matching the backend model):

```json
{
  "first_name": "Aakash",
  "last_name": "Shrivastava",
  "job_role": "Founder",
  "company_name": "Company",
  "company_website": "www.company.com"
}
```

`job_role` is a self-described title, never the authorization `role_key`. `company_website`
is normalized server-side (scheme-less input gains `https://`; non-http(s) refused).

One replay-safe backend transaction: links the Clerk identity to a Clue `platform_user`,
creates the workspace (name = company_name), creates its **first brand** (name =
company_name), makes the user the workspace **owner**, persists the profile
(`platform_user.first_name/last_name/job_role`, DSAR-erased with the rest of the profile).
**Idempotent per user**: a browser retry — or a second linked identity — returns the same
workspace (`created: false`), never a second one. A user who already belongs to a workspace
gets `409 PROVISIONING_CONFLICT` (self-serve provisioning is first-time setup only).

Response:

```json
{
  "user_id": "usr_…", "workspace_id": "ws_…", "brand_id": "brd_…",
  "membership_id": "wsm_…", "role_key": "owner",
  "company_name": "Company", "company_website": "https://www.company.com",
  "first_name": "Aakash", "last_name": "Shrivastava", "job_role": "Founder",
  "created": true
}
```

Errors use the standard envelope `{"error": {"code", "message", "requestId"}}`; relevant
codes: `AUTHENTICATION_REQUIRED` (401), `PROVISIONING_CONFLICT` (409), 422 for validation.
On success the frontend exits to `/session/establish`, which lands the user in the app.

## Workspace setup (slices 2–3 — implemented 2026-08-12 / 2026-08-13)

`POST /stage0/setup` (BFF: `/api/clue/stage0/setup`, 202; requires `research.launch` — recon
is spend) captures the provisioned company website as a durable artifact, records the
`onboarding_input` (kind `website`, actor `human`, no URL copy in the un-redactable
`source_ref`), and drives the governed `start_recon` — fast lane (≤ tier 2, 5¢) then
background lane (≤ tier 3, 100¢) via the D-4c kicker. Ids are deterministic per
`(workspace, website, attempt, iteration)`: idle retries are replays, while a retry after a
failed fast lane mints a genuinely new attempt (the failed run releases its dedupe slot).
`GET /stage0/setup/current` serves lane-level truth plus per-field truth (slice 3). The
setting-up screen polls at 1.5s; every tick maps to durable state; terminal failures render
real recovery controls ("Try again" = a fresh attempt; "Continue anyway" = into the app;
expired sessions link to sign-in). The 3.2s timer survives only in fixture mode. Both the
routes AND the scrape-binder composition ride `CLUE_SELF_SERVE_PROVISIONING_ENABLED` — an
unconfigured deployment refuses `start_recon` everywhere, exactly as before slice 2.

### `GET /stage0/setup/current` response

```json
{
  "schema_version": "…",
  "status": "starting",
  "recon_run_id": null,
  "fast_status": null,
  "background_status": null,
  "company_website": "https://www.company.com",
  "fast_client_kb_version": null,
  "fact_count": null,
  "fields": [
    { "field_key": "client.value_prop", "lane": "fast", "status": "resolved" },
    { "field_key": "client.product", "lane": "fast", "status": "started" }
  ],
  "fast_budget_exhausted": null,
  "background_budget_exhausted": null
}
```

- `status ∈ unavailable|none|starting|running|complete|failed`. `starting` means the
  submission is durably captured but the recon row is not yet visible; `complete` (the
  release signal) carries `fact_count` so a lane that ran but derived nothing is
  distinguishable. **`starting` is where the whole healthy fast lane lives** — that lane runs
  inside one transaction, so its `recon_run` row is invisible until it commits, and overall
  `running` is therefore *not* part of a healthy fast lane's vocabulary. Slice 3's `starting`
  branch serves per-field truth for the not-yet-visible run (keyed on the deterministic
  attempt id), which is the only motion there is to show during the fast lane.
- `fields[]` — one entry per Client-KB baseline field the lanes have reached, **already
  reduced server-side**: the events are an at-least-once outbox, so the server takes
  last-writer-wins by event `seq` per `field_key`. The client must NOT re-reduce (it never
  sees `seq`). Ordered by Client-KB **baseline order** (`CLIENT_BASELINE_FIELDS`, the outer
  budget order the lane walks); any non-baseline field sorts after it, alphabetically. Empty
  until the running lane emits its first field event (and on any pre-slice-3 payload).
- **Cross-lane last-writer-wins is deliberate, and it regresses honestly.** The reduction is
  per `field_key`, not per `(lane, field_key)` — the background lane re-runs
  `reverse_profile` over *every* baseline field, so after the release a field can go
  `{lane: "fast", status: "resolved"}` → `{lane: "background", status: "started"}`. The later
  answer is the truer one; the frontend annotates that state rather than hiding it (see the
  detail lines below). There is no separate "re-research" marker on the wire.
- `fast_budget_exhausted` / `background_budget_exhausted` — `true|false|null`, taken from the
  newest COMPLETED lane-transition event carrying the flag. **`null` means "we do not know
  yet"** (the lane has not reached COMPLETED, it failed, or the run predates the flag) and
  must never be read as `false`. This is truth-telling, not cost governance: a truncated lane
  must never render as fully-researched.

### Progress event vocabulary (D-5 Path B)

Per-field events are emitted from inside `reverse_profile`'s field loop, on the same
`run_event` substrate as the lane transitions, discriminated by `payload.kind`:

- `payload.kind = "stage0.recon.field"` (`RECON_FIELD_PROGRESS_KIND`), topic
  `run.step.progress`, payload `{kind, recon_run_id, lane, field_key, status}`.
- `status ∈ started | resolved | empty | failed` (`FieldProgressStatus`). **`empty` is a
  CORRECT outcome, not a failure** — a field no source could answer is left blank and flagged;
  fabrication is the only real failure. `failed` means the resolution attempt itself errored.
- Delivery is **at-least-once**; the server reduction above is the contract's dedup. In
  production the emitter commits on its **own** connection so a poller sees motion mid-lane;
  events on that path survive a lane rollback by design, and lane truth (the `recon_run`
  status) supersedes on the read side.
- Lane-COMPLETED transition events (`stage0.recon.transition`) now carry `budget_exhausted`,
  which is what the two read-side flags reduce.

Transport is **polling** (D-8 ratified): the states are durable, and the repository seam hides
the transport, so SSE can replace it later without component changes.

### The four D-6 checklist groups

D-6 ratified four groups over the eleven `client.*` baseline fields (each field appears in
exactly one group). **The mapping is frontend-owned data, not backend labels** —
`src/features/onboarding/data/setup-groups.ts`; the reduction (`model/setup-items.ts`) takes
the table as a parameter and knows nothing about these particular rows:

| id | label | fields |
|---|---|---|
| `product-value` | Understanding your product & value | `client.product`, `client.value_prop`, `client.differentiator` |
| `pricing-proof` | Pricing & proof | `client.pricing_posture`, `client.proof_point` |
| `customers-market` | Customers & market | `client.customer`, `client.icp_evidence`, `client.market_reputation`, `client.delivered_value` |
| `competitors-buyers` | Competitors & likely buyers | `client.competitor`, `client.buyer_profile` |

Plus the brand-kit row, still the founder-ratified **explicit dummy** (forced `queued`) until
the design-integration branch merges. Row ids are stable across every poll tick.

Group reduction (pure, unit-tested): no member reached → `queued`; every reached member
terminal and none missing → `complete`; anything between → `running`; overall `complete`
forces `complete` (the screen must never contradict the release); a **halted** run demotes an
unfinished group to `queued` rather than spinning. Halt has two independent axes — overall
`failed`/`unavailable`, and a stopped (`failed`/`paused`) FAST lane with no `running`
background lane, since the backend collapses every non-failed non-completed fast lane to
overall `running` and a PAUSED lane would otherwise spin forever.

The frozen `SetupItemSchema.status` vocabulary is only `complete|running|queued`, so every
further nuance is carried as copy appended to the row's detail line, **at most one per row**,
in priority order (a second clause would churn the `aria-live` region for no added truth):

1. `" — part of this hit a problem"` — a member field reported `failed`.
2. `" — stopped at the research budget"` — a member no lane reached, while a lane reported its
   budget exhausted (`null` is never read as `false`).
3. `" — deepening research"` — every member reached and all in-flight work belongs to the
   background lane, i.e. the honest explanation of the `resolved → started` cross-lane
   regression. Withheld when the fast lane hit its cap, because a background `started` may
   then be *first* contact with that field rather than a second pass.

**These three strings are integration-authored copy pending founder review** (as are the group
labels and detail lines). They are named here so the review has an exact list.

### The repository seam + fixture source

The setting-up flow's transport sits behind `SetupProgressSource`
(`data/setup-progress.repository.ts`): `{ start(), read() }`. `useSetupProgress` owns the
lifecycle (start once, poll, release on the fast lane's completion) and knows nothing about
where frames come from. Two adapters ship: `httpSetupProgressSource` (the live BFF calls,
the hook's default) and `createFixtureSetupProgressSource(script)` — a frame-per-`read()`
scripted stream that sticks at its last frame, parsed through the **same** `SetupStatusSchema`
the HTTP adapter parses, so a fixture cannot drift from the wire. The shipped script is 14
wire-faithful frames: `starting` with no events → the fast lane's baseline walk (still served
as `starting`, `recon_run_id: null`) → the `complete` release frame, where it ends because
that is where the screen's life ends. The poll tick is transport simulation, not a lifecycle
model — nothing advances because time passed.

**Fixture mode's default is unchanged**: with `CLUE_AUTH_ENABLED` unset/false the
setting-up screen still renders the designed static theatre (`SetupScreen` + the 3.2s timer);
only clerk mode mounts `LiveSetupScreen`. The founder offered a one-liner to drive fixture
mode from the scripted stream instead — passing `createFixtureSetupProgressSource()` into
`useSetupProgress` — and it is deliberately **not** taken here: the static walkthrough is the
approved design-review artefact. The seam makes the swap a one-line change whenever that is
wanted.

### Claim extraction and the deployment stance

The slice-2 limitation is **resolved**: a production `LlmClaimExtractor`
(`platform/api/clue_api/claim_extraction.py`) now drafts `client.*` values from scraped text.
It is grounded (every drafted `evidence_span` must be a literal substring of the normalized
document, and `source_url` is grounded in the full document text) and **drop-never-raise** — an
ungrounded or unparseable draft is dropped, never promoted, and never fails the lane;
`GET /stage0/recon/{id}/brief` now returns real facts. Both composition roots
(`projections_main`, `fleet_main`) build it through `build_optional_platform_gateway`: with no
`OPENROUTER_API_KEY` (and no `CLUE_GATEWAY_ALLOW_STUB` opt-in) the builder logs
`stage0.claim_extraction_disabled_no_gateway` and returns `None`, and the composition degrades
to slice 2's explicitly-empty extractor — snapshots without values. It never raises: a keyless
deployment must not take the HTTP process down at import.

Two new baseline fields ship with it — `client.competitor` and `client.buyer_profile`
(object-typed, appended at the END of `CLIENT_BASELINE_FIELDS` so no existing field's budget
position moves; the baseline denominator is now **11**). Their only source is the tier-3
`exa_search` resolver (Exa's *search* API — never Exa *deep*, which is tier-4 and would breach
the pre-confirmation tier ceiling). The fast lane's `max_source_tier=2` walks past them at zero
spend, so they are background-lane fields for free. The resolver is bound only when
`CLUE_EXA_API_KEY` is configured; without it the source stays **unbound** (logged
`stage0.exa_search_unbound_no_credential`), the waterfall records `NO_RESOLVER` at zero spend,
and the two fields end honestly empty — a keyless deployment must not lose onboarding over an
optional enrichment. A hard provider refusal (revoked key, 402, 400) is likewise an honest
empty miss, not a dead recon lane.

**Deployment stance (founder ruling 2026-08-13, FI-4 §9 — onboarding is budget-unconstrained).**
Onboarding recon forms the base of everything downstream, so research quality is never traded
for spend here. The `Stage0Policy` envelopes (5¢ fast / 100¢ background / 24h dedupe;
`libs/clue-config/clue_config/stage0.py`, injected at the composition root — policy-as-data
constants today, not env vars) are **floors to raise per deployment** the moment they truncate
onboarding research; no new throttles, caps, or gates are added on the onboarding path. With a
real extractor, `CLUE_SCRAPE_BACKEND=firecrawl` (the settings default) becomes viable
per-deployment — at ~1¢/scrape the 5¢ fast envelope walks only ~5 of the 11 fields, which is
exactly the case the ruling says to fix by raising the envelope, not by degrading the backend.
`CLUE_SCRAPE_BACKEND=scrapling` (local, zero-cost) remains the choice for a deployment that
would rather walk every field free. The honesty surfaces (`*_budget_exhausted`) and the tier ≤3
pre-confirmation ceiling are unaffected — truth and compliance, not cost governance. Extractor
LLM spend is observable on `llm.gateway_call` spans but is **not** charged to the recon
envelopes; that residual is founder-accepted, not merely parked.

Still ahead: brand-kit flips real per `brand-kit.md` when the design-integration branch merges.

## Freeze-record notes (round-2 review)

- In-flight submits render the design system's standard disabled state (50% opacity) on the
  approved buttons — a transient interaction state, named here so the visual freeze record is
  complete; no resting appearance changed. Errors render via the additive `.authError` line at
  the card foot in every mode (including the Google-only screens).
- The fixture walkthrough now includes the ratified `verify-email` addition
  (`sign-up-email → verify-email → profile`); everything else in the design-review theatre is
  unchanged, and the profile step remains click-through-able unvalidated in fixture mode.
- **Superseded (slice 2, kept corrected).** The slice-1 record said that with authentication
  enabled `/onboarding/setting-up` and `/onboarding/finalizing` redirect to the profile step so
  no fake progress is reachable. Since slice 2 there is no such redirect and no fake progress
  to guard against: in clerk mode both steps render `LiveSetupScreen`, driven entirely by
  durable recon truth. The static theatre survives only in fixture mode.
- A replayed provision whose submitted company name differs from the recorded workspace name
  returns `company_name_ignored: true` (names are fixed at creation); the response schema is
  deliberately non-strict so additive backend fields can never fail a successful provision.
- `GET /auth/v1/session` carries `has_inactive_memberships`: the session DAL routes lost-access
  users (revoked/suspended) to `/access-denied` and only membership-history-free users to
  `/onboarding/profile`.
- `POST /auth/v1/provision` mounts only when `CLUE_SELF_SERVE_PROVISIONING_ENABLED=true`
  (default off, like every neighbouring write surface).

## Integration notes

- Passwords touch Clerk only; they never reach a Clue backend or fixture.
- Authentication errors map to field-level messages inside the approved card geometry via the
  additive `.authError` style; the card layout is unchanged.
- The onboarding draft (including the profile fields) survives step navigation via a
  memory-only provider; nothing is written to storage.
- The fixture provisioning twin (`provisionWorkspaceFixture`) keeps the fixture and HTTP
  paths swap-equivalent for tests and design review.
