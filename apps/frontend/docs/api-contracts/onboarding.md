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

`company_name` is **optional** (`string | null`; an empty string is refused — send `null`).
The workspace and its first brand are named by this precedence: the typed company name when
one is given, otherwise the canonical name of the company website's domain. The profile
screen says so under the field ("Leave blank to use your website's name"), which is why the
website itself stays required.

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
On success the frontend re-authorizes and selects the exact returned `workspace_id`, writing
the HTTP-only workspace-selection cookie through the existing session action, then enters the
real `setting-up` flow. It never silently selects the first membership. Fast-lane completion
later exits through `/session/establish` into the protected app.

## Workspace setup (slices 2–3 + crawl progress C8 — implemented 2026-08-12–14)

_Superseded 2026-09-12 by "The setting-up screen runs the new onboarding lane" below; kept as the record of the legacy Stage-0 surface, which still exists behind CLUE_LEGACY_STAGE0_RECON_ENABLED._

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

### Brand-kit ingestion auto-trigger (brand-kit slice 2 — 2026-08-18)

The same `POST /stage0/setup` also seeds the client's **draft brand kit**, so the
Brand-context screen has real brand data to review instead of an empty page. Nothing about the
setup wire shape changes; this is a backend side effect, recorded here because it is the
onboarding flow's behaviour.

- **Trigger.** After the capture step and the recon dispatch, the platform makes ONE
  server-side call to the design API: `POST {CLUE_DESIGN_API_BASE_URL}/brand-kits/ingest/website`,
  header `X-Workspace-Id: <the PROVISIONED workspace>`, body `{"url": <company_website>}`.
  Never from the browser, and never a platform-side write of `design_ingestion_job` — the
  design API owns the SSRF guard and writes the job row plus its `design_job` fleet task in one
  transaction. The kit is born `draft`: **ingestion never approves anything** (approval is the
  human gate, brand-kit slice 4).
- **First-time-only, structurally.** The trigger is reachable only through the self-serve
  provisioning scope that supplies `brand_id` + `company_website`, so workspaces created any
  other way never auto-ingest. Re-runs and refreshes are manual from the Brand-context screen.
  There is no "first time" flag to get out of sync.
- **Idempotency key = the workspace.** The enqueue is skipped when ANY `design_ingestion_job`
  row already exists for the workspace, so setup replays (the setting-up screen polls and the
  submit can be retried) produce exactly one job. The check and the enqueue run under a
  per-workspace Postgres advisory transaction lock, so two concurrent first-time setups also
  produce exactly one.
- **Fail-soft.** A design API that is unreachable, slow, or refuses the URL never fails or
  delays the setup response, and leaves no job row. Because a failed attempt writes nothing,
  the next setup replay re-attempts — a transient outage self-heals, and brand-kit slice 4's
  manual trigger is the final rescue.
- **`brand_id` is not threaded.** A self-serve-provisioned workspace has exactly one brand, and
  the kit-birth path's exactly-one-brand heuristic (`clue_design.joins.resolve_brand_id`) stamps
  it. A multi-brand workspace resolves to `NULL` rather than guessing — which is why the manual
  re-ingest in slice 4 passes an explicit brand.
- **Config.** `CLUE_DESIGN_API_BASE_URL` (server-side only, backend-to-backend; distinct from
  the frontend's own `LUMEN_API_BASE_URL` for its BFF proxy). Unset = the trigger does not fire,
  which is a deployment posture, not an error. The route itself still rides
  `CLUE_SELF_SERVE_PROVISIONING_ENABLED`.
- **Reading the result.** The Brand-context page reads the kit through the design BFF (see
  `brand-context.md`); the onboarding checklist row for brand-kit status is brand-kit slice 3
  below.

### Brand-kit checklist row goes live (brand-kit slice 3 — 2026-08-18)

The setting-up checklist's **"Creating brand kit — Colors, typography, tone & voice"** row stops
being the founder-ratified explicit dummy (forced `queued` since FI-4 slice 3) and reports the
slice-2 job's real status. Nothing visual changes: the row, its copy, and the three designed
states are the frozen dummy design; only *which* state it shows is now derived from truth.

`GET /stage0/setup/current` gains one additive, nullable field, served in **every** branch
(`unavailable` / `none` / `starting` / `running` / `complete` / `failed`):

```json
"brand_kit_ingestion": { "job_id": "ingest_b91eb1c4…", "status": "queued" }
```

- `null` = the workspace has no `design_ingestion_job` row at all (or a backend that predates
  this slice) — never a fabricated `queued`.
- `status` is the `design_ingestion_status` enum **as stored**: `queued | running | succeeded |
  failed`. The backend derives nothing; putting the row mapping on the server would move
  presentation policy into the API.
- Source: the workspace's newest job, via the sanctioned `clue_design.ingestion.list_recent`
  DAL port (`limit=1`, workspace-scoped, newest-first) — the same read slice 2's trigger uses
  for its idempotency check. One cheap read per poll tick; no join, no derivation.

**Row mapping (frontend-owned, `model/setup-items.ts`, pure + unit-tested):**

| wire | row status | detail |
|---|---|---|
| field absent / `null` | `queued` | fixture detail unchanged |
| `queued` or `running` | `running` | fixture detail unchanged |
| `succeeded` | `complete` | fixture detail unchanged |
| `failed` | `queued` + `" — part of this hit a problem"` | the existing failure annotation |
| unrecognized (future) status | `running` | fixture detail unchanged |

**Why `failed` maps to `queued` + an annotation** (controller ruling, binding): the frozen
`SetupItemSchema.status` vocabulary has no failed state; `complete` would claim a kit exists
when nothing was produced; and the detail-line annotation is the design's failure surface —
exactly how a failed recon field annotates its group. No new copy was invented: the row reuses
the existing `FAILED_MEMBER_ANNOTATION` string verbatim. Brand-kit slice 4's manual trigger is
the rescue path.

The brand-kit row sits **outside** the D-6 group reduction: the ingestion is separate work from
recon, so neither lane truth, nor the halt rule, nor the index-0 warm-up rule touches it — a
published kit stays `complete` under a failed recon run, and a running ingestion stays `running`
under a released one. The row keeps its fixture identity (id/label/base detail) and its
drop-if-absent behaviour.

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
  "background_budget_exhausted": null,
  "official_site": {
    "schema_version": "stage0-official-site-c8-v1",
    "crawl_run_id": "…",
    "run_status": "fast_active",
    "phase": "fast",
    "message": "Scraping selected company pages (3/8).",
    "states": ["leased", "provider-active", "persisted"],
    "queued": 4,
    "leased": 1,
    "provider_active": 1,
    "reconciliation_pending": 0,
    "persistence_pending": 0,
    "retry_wait": 0,
    "expansion_queued": 1,
    "expansion_leased": 0,
    "expansion_retry_wait": 0,
    "expansion_completed": 2,
    "expansion_failed": 0,
    "fetched": 3,
    "total_pages": 8,
    "snapshots": 3,
    "fetch_spend_unknown": 0,
    "extraction_active": 0,
    "extraction_materialized": 0,
    "extraction_empty": 0,
    "extraction_failed": 0,
    "extraction_spend_unknown": 0,
    "recovery_required": false,
    "partial": false,
    "completed": false,
    "last_event_seq": 42,
    "last_event_kind": "stage0.crawl.page_fetched"
  },
  "brand_kit_ingestion": { "job_id": "ingest_b91eb1c4…", "status": "running" }
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
- `fields[]` — one entry per field in the explicit eleven-field onboarding checklist the lanes
  have reached, **already
  reduced server-side**: the events are an at-least-once outbox, so the server takes
  last-writer-wins by event `seq` per `field_key`. The client must NOT re-reduce (it never
  sees `seq`). Ordered and filtered by `CLIENT_ONBOARDING_FIELDS`; company navigation or future
  pack fields are not silently added to the checklist. Empty until the running lane emits its
  first checklist-field event (and on any pre-slice-3 payload).
- **Cross-lane last-writer-wins is deliberate, and it regresses honestly.** The reduction is
  per `field_key`, not per `(lane, field_key)` — the background lane re-runs
  `reverse_profile` over broader company knowledge, while this endpoint filters the result back
  to the eleven onboarding fields. After release a checklist field can still go
  `{lane: "fast", status: "resolved"}` → `{lane: "background", status: "started"}`. The later
  answer is the truer one; the frontend annotates that state rather than hiding it (see the
  detail lines below). There is no separate "re-research" marker on the wire.
- `fast_budget_exhausted` / `background_budget_exhausted` — `true|false|null`, taken from the
  newest COMPLETED lane-transition event carrying the flag. **`null` means "we do not know
  yet"** (the lane has not reached COMPLETED, it failed, or the run predates the flag) and
  must never be read as `false`. This is truth-telling, not cost governance: a truncated lane
  must never render as fully-researched.
- `official_site` — C8's additive, nullable crawl projection. `null` means no durable crawl row
  exists (and preserves pre-C8 compatibility); a present value combines authoritative row counts
  with the latest idempotently-reduced crawl event. It exposes no URL, page body, raw model output,
  or provider receipt. `states` is a non-exclusive operational vocabulary: `queued`, `leased`,
  `provider-active`, `spend-unknown`, `persisted`, `extracted`, `partial`, `completed`. The frontend
  accepts future state/status strings but validates all known counts/booleans. C8 does not change
  the setup release condition: C10 owns the live browser/cutover gate.
- `brand_kit_ingestion` — brand-kit slice 3's additive, nullable job truth (`{job_id, status}`),
  present in every branch; `null` means no ingestion job exists. See the row mapping above.
- A locally surfaced setup stall is not a backend terminal. The screen keeps polling after showing
  “Try again / Continue anyway”; later committed progress clears the fallback, and a later
  `status=complete` still releases automatically. `expansion_*` counts expose the independently
  fenced link-discovery state without exposing URLs or bodies.

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

D-6 ratified four groups over the eleven `client.*` onboarding fields (each field appears in
exactly one group). **The mapping is frontend-owned data, not backend labels** —
`src/features/onboarding/data/setup-groups.ts`; the reduction (`model/setup-items.ts`) takes
the table as a parameter and knows nothing about these particular rows:

| id | label | fields |
|---|---|---|
| `product-value` | Understanding your product & value | `client.product`, `client.value_prop`, `client.differentiator` |
| `pricing-proof` | Pricing & proof | `client.pricing_posture`, `client.proof_point` |
| `customers-market` | Customers & market | `client.customer`, `client.icp_evidence`, `client.market_reputation`, `client.delivered_value` |
| `competitors-buyers` | Competitors & likely buyers | `client.competitor`, `client.buyer_profile` |

Plus the brand-kit row, which since **brand-kit slice 3 (2026-08-18)** reports the workspace's
real ingestion job (mapping above); it was the founder-ratified explicit dummy until then. It is
not a D-6 group and is not part of the reduction below. Row ids are stable across every poll
tick.

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
`GET /stage0/recon/{id}/brief` now returns real facts — **but the brief reads at
`fast_client_kb_version` only**, so a fact the *background* lane derived never appears in it or
in `fact_count`; `client.competitor` / `client.buyer_profile` are tier-3 and therefore always
background-lane, so they can never show up there. Read the Client KB itself, not the brief, for
those.

Both composition roots build the extractor through the single
`build_stage0_claim_extractor(gateway)` — one function, so the two processes cannot drift into
extracting differently — but they **source that gateway differently on purpose**. The HTTP root
(`projections_main`) uses the degrading `build_optional_platform_gateway`: with no
`OPENROUTER_API_KEY` (and no `CLUE_GATEWAY_ALLOW_STUB` opt-in) it logs
`stage0.claim_extraction_disabled_no_gateway`, returns `None`, and the composition falls back to
slice 2's explicitly-empty extractor — snapshots without values. It never raises: a keyless
deployment must not take the whole web process down at import over one tool's optional LLM step.
The fleet worker (`fleet_main`) passes the mandatory `build_platform_gateway` gateway it already
built for every other model consumer in that process, and that builder **deliberately raises**
without a credential — a worker that cannot call a model cannot do its job, so failing at boot
is its designed contract, not a regression.

Two new onboarding fields ship with it — `client.competitor` and `client.buyer_profile`
(object-typed, appended at the END of `CLIENT_ONBOARDING_FIELDS` so no existing field's budget
position moves; the onboarding checklist is now **11**). Their only source is the tier-3
`exa_search` resolver (Exa's *search* API — never Exa *deep*, which is tier-4 and would breach
the pre-confirmation tier ceiling). The fast lane's `max_source_tier=2` walks past them at zero
spend, so they are background-lane fields for free. The resolver is bound only when
`CLUE_EXA_API_KEY` is configured; without it the source stays **unbound** (logged
`stage0.exa_search_unbound_no_credential`), the waterfall records `NO_RESOLVER` at zero spend,
and the two fields end honestly empty — a keyless deployment must not lose onboarding over an
optional enrichment. A hard provider refusal (revoked key, 402, 400) is likewise an honest
empty miss, not a dead recon lane.

The field policy now names three independent company sets rather than overloading one baseline:

- `CLIENT_ICP_SYNTHESIS_FIELDS` is the stable nine-field ICP-readiness denominator and retains the
  seven-of-nine Insight Health acceptance contract. A workspace may explicitly add requirements.
- `CLIENT_ONBOARDING_FIELDS` is the original eleven-field recon/progress checklist above.
- `CLIENT_COMPANY_KNOWLEDGE_FIELDS` (the compatibility `CLIENT_BASELINE_FIELDS`) additionally
  contains `client.product_catalog`, making the broader account-wide knowledge set 12 fields.

`client.product_catalog` is bounded portfolio-navigation knowledge. It is not an onboarding row,
does not enter the ICP denominator, and cannot delay the legacy fast onboarding release: the fast
recon call is constrained to `CLIENT_ONBOARDING_FIELDS`. It may publish through later/background
company knowledge and the durable official-site path. Detailed product facts are a separate
product-scoped set and require an exact `product_id`.

**Evidence-serving posture differs by field, and the difference is deferred work.** The scrape
lane is snapshot-wrapped: its claims cite a durable, sha-256'd artifact captured through the
storage seam. The `exa_search` resolver carries **no snapshot/artifact wiring at all**, so
`client.competitor` / `client.buyer_profile` claims cite a `source_url` plus a verbatim
`evidence_span` and nothing durable behind them — if the cited page changes or disappears, the
span cannot be re-verified from our own bytes. The claims are still fail-closed grounded
(attributable to a url this call retrieved, span-checked against that record's own text,
target-locked), so this is an evidence-*durability* gap, not a fabrication risk. Any evidence
serving built over recon claims must treat the two tier-3 fields as URL-cited-only until Exa
records get snapshot capture.

**Deployment stance (founder ruling 2026-08-13, FI-4 §9 — onboarding is budget-unconstrained).**
Onboarding recon forms the base of everything downstream, so research quality is never traded
for spend here. The `Stage0Policy` envelopes are **floors to raise per deployment** the moment
they truncate onboarding research; no new throttles, caps, or gates are added on the onboarding
path. Since the slice-3 close-out that is an actual mechanism, not a code change: the two lane
budgets are env-backed settings — **`CLUE_STAGE0_FAST_BUDGET_CENTS` (default `25`) and
`CLUE_STAGE0_BACKGROUND_BUDGET_CENTS` (default `100`)** — read by
`clue_config.stage0_policy_from_settings` and composed into the recon tools at
`build_toolbelt`. The dedupe TTL (24h) and the readiness floors stay versioned constants
(correctness/governance, not cost), and the library default `DEFAULT_STAGE0_POLICY` keeps its
old 5¢/100¢ values for uncomposed callers. The accepted implementation remains the
homepage/field-oriented official-site resolver; `CLUE_SCRAPE_BACKEND=scrapling` is the local
credit-free single-page alternative. The honesty surfaces (`*_budget_exhausted`) and the tier ≤3
pre-confirmation ceiling are unaffected — truth and compliance, not cost governance. Extractor LLM
spend is observable on `llm.gateway_call` spans but is **not** charged to the recon envelopes;
that residual is founder-accepted, not merely parked.

**Implemented through C8 in default-off, allowlisted shadow mode (2026-08-14):** broad
official-site coverage now has a PostgreSQL frontier/ledger, conservative URL deduplication,
generation-fenced concurrent leases, one fast/background crawl run, coordinator-owned
depth/safety/retry rules, content-addressed artifacts with URL-level provenance, provider-neutral
single-page Firecrawl/Scrapling fetchers, immutable corpus checkpoints, grounded concurrent
materialization, provider-neutral `official_site` claims, stable crawl/extraction events, a
rows-first setup projection, privacy-safe metrics/logs, and fenced operator recovery. A retained
Insight Health Firecrawl + Luna run materialized checkpoint claims and cold-replayed with zero new
provider attempts or duplicate claims. A rejected provider-owned 50-page spike is not the contract.
The binding implementation plan and exit gates are
[`docs/specs/FI-stage0-durable-official-site-crawl-plan.md`](../../../../docs/specs/FI-stage0-durable-official-site-crawl-plan.md).
The nullable `official_site` field is now part of both fixture/live transport schemas, but the
current setup screen and browser release continue to derive from the committed legacy fast
Client-KB version. C9 owns the full offline adversarial gate and C10 owns live browser acceptance
and authoritative cutover.

**Done (2026-08-18):** the design subsystem is merged, so the brand kit is real — slice 2
auto-triggers the ingestion at first-time setup and slice 3 binds the checklist row to that
job's live status (both sections above).

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

## The setting-up screen runs the new onboarding lane (2026-09-12)

Spec `docs/superpowers/specs/archive/2026-09-12-onboarding-v2-default-design.md`. After provisioning, the
setting-up screen posts `POST /api/clue/onboarding` `{ company_domain, brand_id: null }` (the
profile's website, folded to its host; a 409 `onboarding_in_progress` is the replay-safe answer)
and polls `GET /api/clue/onboarding/current` every 1.5 s. The screen's `SetupStatus` is derived in
`data/setup.ts`: `complete` when every fast step (`overview`, `lineup`, `reviews`, `synthesis`) is
`completed` or `empty`, `failed` when one is `failed`, `starting` for a queued run, `none` before
the first post. Rows (`data/setup-groups.ts`) map onto step kinds: company, products, proof,
audience (which completes on the ICP turn and notes that personas continue in the background),
plus the brand-kit row over the ingestion job. Release, stall and error handling are unchanged.
Backend: `CLUE_ONBOARDING_V2_ENABLED` defaults on; the old Stage-0 recon composes only behind
`CLUE_LEGACY_STAGE0_RECON_ENABLED` (default off) until section G of the ledger retires it.
