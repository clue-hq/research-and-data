# Provider credit and key alerts — design

**Status:** for founder approval (2026-10-31); all open questions resolved. Extends the provider-incident design of
2026-09-16 (`docs/superpowers/specs/archive/2026-09-16-provider-incidents-design.md`, plan
`docs/superpowers/plans/2026-09-16-provider-incidents.md`). That design stays authoritative for
everything this one does not change.

## 1. Why

On 2026-10-31 a Pallet ad-assets onboarding (trenton lane) asked People Data Labs who
`pallet.com` is. PDL answered `402 PAYMENT REQUIRED`. The only trace was an `httpx` info line in
an ingestion child's log file. The job carried on unverified, guessed the founder's name as the
brand's advertiser name, kept his 11 personal posts as "the brand's ads", dropped 36 likely company
ads, and wrote "Sushanth Raman's advertising" into four image prompts. Nobody was told PDL had
stopped serving.

The platform already has a mechanism for exactly this — provider incidents, which send one Sentry
event when a provider stops serving and one when it recovers — but only about half of the
external calls feed it, some quota replies are graded as ordinary rate limits, and a missing API
key never reaches it at all.

**Goal (founder, 2026-10-31):** whenever any external service provider runs out of credits or
quota, or its API key is missing, the founders get a Sentry alert, emailed to
`akeshri516@gmail.com`. This covers every paid or keyed provider, explicitly including the
transcription and media-handling APIs.

## 2. Rulings taken in discussion (founder, 2026-10-31)

1. **Alert channel:** Sentry, emailed to `akeshri516@gmail.com`.
2. **Out of credits / quota:** alert when it happens, on the first refusal.
3. **Missing key:** alert **at service start-up**, not only when a call is first attempted.
4. **Production only:** emails come from the production environment only
   (`CLUE_SENTRY_ENVIRONMENT=production`), never from a dev lane.
5. **ZoomInfo, Clay and Apollo are left out for now** ("for today"): their keys are not checked and
   their failures do not alert. Nothing in production calls them yet.
6. **Firecrawl and Sumble are out of the stack** and are ignored entirely (no key check, no alerting).
7. **Code without a database connection does not record directly** (§9 Q1, option b): a call site
   raises a typed error carrying the classified failure, and the job or drain that runs it — which
   already holds a connection — records the incident.
8. **The calls outside the spend layer go through it** (§9 Q2): Exa Websets lifecycle, Exa deep,
   Parallel, PDL, Composio, Cloudflare and Clerk are routed through the `clue_spend` caller, so their
   calls and credits land in `provider_call_ledger` and their incidents open and close through the
   drain like every other ledgered call.
9. **BuiltWith and Dun & Bradstreet are left out of the key check** (§9 Q3), like ZoomInfo, Clay and
   Apollo — nothing in production calls them yet.

## 3. Goals, non-goals, anti-goals

**Goals**
- One Sentry event per outage, per provider and reason — not one per call, and not one per
  process restart.
- Every external provider listed in §5 reaches the incident recorder when it refuses for credits,
  quota, key limit, rejected key, or suspended account.
- Every key listed in §5 that a production service needs, and does not have, opens an incident at
  that service's start-up.
- The incident closes (one "recovered" event) when the provider serves again, or when a later
  start-up finds the key present.

**Non-goals**
- No new notification channel (no Slack, no direct SMTP). Sentry's own alert rule sends the email.
- No change to how jobs and turns fail or degrade today. Alerting is observation only.
- No balance polling or low-balance warnings (the existing OpenRouter/Exa credit probes in
  `workspace_ops/preflight.py` stay as they are).
- Not the advertiser-name fix for the Pallet case (falling back to the brand kit's name when PDL
  cannot answer). That changes which ads are kept and is a separate change.

**Anti-goals**
- **The alerting must never break or slow the call it observes.** The recorder already never
  raises (`provider_incident.recorder_failed`); every new hook keeps that.
- **No alert storms.** A dev-lane restart, a missing key for an unused provider, or a provider
  refusing 400 calls in a minute must not produce more than one email.
- **No secrets in Sentry.** Key values, request bodies and auth headers never go into an event.

## 4. What exists (verified 2026-10-31)

- **Classifier** `libs/clue-core/clue_core/provider_failures.py`: `classify_http(provider, status,
  body)` and `classify_exception(provider, exc)` return a `ProviderFailure(provider, kind, reason,
  message)`. Refusals (open on first sight): `credits_exhausted` (402, or 401/403 naming credit),
  `key_limit`, `account_suspended`, `auth_invalid`. Failures (open after 3 within 5 minutes):
  `rate_limited` (429), `server_error` (5xx), `timeout`.
- **Recorder** `platform/api/clue_api/provider_incidents.py`: `record_failure(conn, failure, *,
  surface, workspace_id, now)` and `record_success(...)` over the `provider_incident` table (one open
  row per `(provider, reason)`, partial unique index). Whichever process wins the insert sends the
  single Sentry event (`_sentry_event`, tags `provider` / `reason` / `kind`, fingerprint
  `["provider-incident", provider, reason, opened_at]`); whichever wins the close sends the
  "recovered" event.
- **Who feeds it today:** the ARV2 ledger drain (`platform/api/clue_api/arv2/provider_ledger.py`),
  which sees every call made through the `clue_spend` caller in a scope that drains through the
  platform, and the platform chat turn's model-call handler (`agent_runtime_wiring.py`).
- **Sentry** is installed by `clue_obs.production.install_production_sentry` behind
  `CLUE_SENTRY_ENABLED` + `CLUE_SENTRY_DSN`; `CLUE_SENTRY_ENVIRONMENT` labels the environment
  (`production` in production, `lane-<name>` on lanes — lanes send events too).

## 5. Gaps this design closes

A survey on 2026-10-31 mapped every external call (file:line references in the session record).

**5.1 Calls that never reach the recorder** (they do not go through `clue_spend`, or go through it
in a scope that does not drain to the platform):

| Provider | Where | Today on 402/quota |
|---|---|---|
| People Data Labs | `lumen_ingestion/ad_library/pdl.py` (`httpx.get`) | `CompanyIdentityError`, job degrades silently |
| Exa Websets lifecycle | `clue_research/adapters/exa_websets.py` | `ExaWebsetsPaymentRequired`, warning log only |
| Exa deep (account/contact) | `exa_deep_acquisition.py` → `resolvers/http.py` | `ProviderResponseError(402)` |
| Parallel | `resolvers/parallel` | `ProviderResponseError` |
| Composio (CRM) | `crm/composio_gateway.py` | `ComposioError`, 402 falls to `bad_request` |
| Cloudflare | `cloudflare_custom_hostnames.py` | `CloudflareError` |
| Clerk | `clue_auth/providers/clerk_api.py`, `clerk.py` | `ClerkApiError` |
| OpenRouter — design scene/site/web agents and the brief agent | `clue_gateway/agent_model.py` | `gateway.provider_refused` warning log only |
| Design-side `clue_spend` calls in default-drain scopes (image generate/edit, background removal, describe, vision, assist, distill, Brandfetch, Adyntel per-request paths) | `lumen_api/spend.py` default drain | ledger row written, no incident |

**5.2 Quota graded as a rate limit or a rejected key**

| Provider | Reply | Today | Should be |
|---|---|---|---|
| Gemini (native media, transcription) | 429 `RESOURCE_EXHAUSTED` | `rate_limited` (needs 3 in 5 min) | refusal on first sight |
| Brandfetch | 429 quota | `rate_limited` | refusal on first sight |
| YouTube Data API | 403 `quotaExceeded` | `auth_invalid` | quota, not "key rejected" |
| Composio | 402 | not classified (`bad_request`) | `credits_exhausted` |

**5.3 Missing keys never alert.** Each provider handles a missing key its own way: a start-up
crash, a feature silently switched off (Composio, Clerk, Podcast Index, YouTube), or an error on
first use. There is no shared "missing key" type.

**Providers in scope** (keys from `.env.example`): OpenRouter (incl. `LUMEN_AGENT_API_KEY`,
`IMAGE_MODEL_API_KEY`), Gemini, Deepgram, YouTube Data, Podcast Index, Exa (search, contents,
Websets, deep), AI Ark, Parallel, People Data Labs, Adyntel, Brandfetch,
Composio, Cloudflare, Clerk. **Out of scope by ruling:** ZoomInfo,
Clay, Apollo, BuiltWith, Dun & Bradstreet (no production caller yet), Firecrawl and Sumble (out of the
stack). **Out of scope by design:** Langfuse and S3/R2 storage (not credit-metered services
whose refusal blocks the product; Langfuse already degrades by itself), keyless public-media
downloads (no key, no credits).

## 6. Design

### 6.1 Two new reasons

Add to the classifier, both of kind `refusal` (open on first sight):

- `quota_exhausted` — a provider saying its quota or usage limit is used up. Recognised by quota
  words in the body (`quota`, `RESOURCE_EXHAUSTED`, `usage limit`, `quotaExceeded`) on a 429 or a
  403. A plain 429 with no quota words stays `rate_limited`.
- `key_missing` — the service's configuration has no key for a provider it needs. Never produced
  by an HTTP reply; produced only by the start-up check (§6.3) and by call-time credential errors
  (§6.4).

Reason words: `quota_exhausted → quota used up`, `key_missing → API key missing`. Their incident
sentence and Sentry titles follow the existing pattern (`{Provider} refused: API key missing`).
Display names are added for the new providers (e.g. `pdl → People Data Labs`, `deepgram →
Transcription provider`), every other id keeps falling back to the id.

### 6.2 One recorder both subsystems can use

The recorder lives in the platform (`clue_api`), which the design subsystem must not import. The
design subsystem — PDL, Adyntel, Brandfetch, image models, describe/vision, the design agents —
needs to record incidents too.

**Recommended:** move the recorder (the `provider_incident` reads/writes, the Sentry open/close
events, the display words) into a shared library that both already depend on, next to the
classifier (`libs/clue-core` holds the pure classifier; the recorder needs a database connection,
so it goes where the shared DB access lives). `clue_api.provider_incidents` keeps re-exporting the
names so the platform's three readers do not change. *(Open for the founder: §9 Q1.)*

### 6.3 The start-up key check

One registry, **data, not code per provider**: provider id → the env names that carry its key →
which services need it (platform API, fleet worker, design API, ingestion pool). Each service, at
start-up and after Sentry is installed, checks the providers it needs:

- a key that is missing or blank → `record_failure(ProviderFailure(provider, "refusal",
  "key_missing", "<ENV_NAME> is not set"), surface="startup", …)` — the message names the env
  variable, never a value;
- a key that is present while that role's `key_missing` incident for that env name is open → close
  that one incident, with one "recovered" event (a new close-by-identity call; see below).

**A missing-key incident is identified by the service role and the env name, not by the provider**
*(builder's call, after the builder check)*. Production runs three roles with their own env files
(platform-api, design-api, worker — `deploy/check_prod_env.py`), and some providers have several key
names (OpenRouter: `CLUE_OPENROUTER_API_KEY`, `OPENROUTER_API_KEY`, `LUMEN_AGENT_API_KEY`,
`IMAGE_MODEL_API_KEY`; Deepgram: `CLUE_DEEPGRAM_API_KEY`, `DEEPGRAM_API_KEY`). Keyed by provider, a
key missing in one role and present in another would open and close the incident on every deploy.
So a `key_missing` row's `provider` column holds `"<role>:<ENV_NAME>"` (e.g.
`design-api:PDL_API_KEY`), its display reads "People Data Labs key `PDL_API_KEY` (design-api)",
and **only the start-up check of that same role closes it** — an ordinary successful call never
closes a `key_missing` incident (today's `record_success` closes every open incident of a provider
id; it must not touch these rows). Where a provider accepts either of two names (one falls back to
the other), the check treats the pair as one key: missing only when both are blank.

Because the incident table allows one open incident per `(provider, reason)` platform-wide, several
worker processes of one role and a restart loop still produce one email. A provider whose feature is
deliberately optional (Composio, Clerk, Podcast Index, YouTube) is still listed: the founder asked
for an alert whenever a key is missing.

**Customers never see the new incidents** *(builder's call)*. Two readers put an open incident's
sentence on customer surfaces (`frontend_read/display_pages.py`, `frontend_read/research_progress.py`,
both for `openrouter`). They skip `key_missing` rows. Model refusals from the design agents and the
design-side image and vision calls are recorded under their own provider id, `openrouter_design`
(display "Design model provider"), so a design-side refusal never writes "Model provider refused" into
a customer's research page. A real OpenRouter credit outage still shows on both, because the research
calls refuse too and record under `openrouter`.

**An incident whose open event was never sent is sent later** *(builder's call)*. If the process that
won the insert had no Sentry installed, the row has no `sentry_open_event_id`. The next process with
Sentry that records against that open incident — or any start-up check — sends the open event then and
stamps the id, so an email is late rather than lost.

**ZoomInfo, Clay and Apollo are absent from the registry** (ruling 5). Re-adding one later is one
registry row.

### 6.4 Every refusal reaches the recorder

- **Calls already through `clue_spend`:** the design subsystem's default drain records incidents
  for classified failures the same way the platform drain does, so per-request design scopes stop
  being blind.
- **Calls not through `clue_spend`** (the §5.1 table): each call site that already turns a
  provider reply into its own error passes the status and body to `classify_http` (or the
  exception to `classify_exception`) and records the result. Where a call site already raises a
  typed "credentials missing" error at call time, that is recorded as `key_missing` too.
- **Design agents' model calls:** where `agent_model.py` logs `gateway.provider_refused`, the
  classified failure is recorded as well.

**The §5.1 calls are routed through `clue_spend`** (ruling 8): each gets a `CallSpec` with its
provider id and a credit estimate, so it is ledgered, classified at settle time and drained into the
recorder by the job or scope that runs it. Recovery then needs nothing new: the drain already closes
an incident after successful calls.

### 6.5 Production only

Code records incidents in every environment (lanes keep showing the "provider refused" sentence
in their own UI). **The email is production-only through the Sentry alert rule**, not through
code:

- Sentry alert rule (set up by the founder in Sentry, not in code): *when an event's tags match
  `provider-incident` events (an issue whose message starts with a provider name and "refused:")
  **and** `environment = production`, email `akeshri516@gmail.com`.* Sentry emails only members of
  the organisation, so that address must be a member.
- The code adds one tag to every incident event, `alert=provider` (open events only), so the rule
  can match on a tag instead of message text.

## 7. Constraints

- The recorder and every new hook never raise into the observed call or into start-up.
- No key value, request body, or auth header in any Sentry event, log line, or incident row.
- No new env flag: Sentry already uses `CLUE_SENTRY_ENABLED` / `CLUE_SENTRY_DSN` /
  `CLUE_SENTRY_ENVIRONMENT`. If the key registry needs an env-driven exclusion list, it is a new
  flag and goes into `.env.example` with its default at the moment it is introduced (env parity
  rule).
- The design subsystem keeps its seam: it imports the shared library, never `clue_api`.
- Migrations, if any (e.g. none expected — `reason` is free text), follow the Alembic conventions.

## 8. Left to the builder

- Exact quota-word list and where each new provider's display name lives.
- How each service declares which providers it needs (a constant per entrypoint is fine).
- Test shape, following the existing provider-incident tests.

## 9. Open questions for the founder

1. **RESOLVED 2026-10-31 — option (b).** **How code without a database connection records** (§6.2, §6.4). The recorder writes a database
   row. Many §5.1 call sites have no connection: PDL is a plain synchronous call inside an ingestion
   job, and the research resolvers are library code that must not reach other packages. Either
   (a) those libraries get their own small recorder that opens its own connection, or (b) each call
   site raises a typed error carrying the classified failure and the job/drain layer that already
   holds a connection records it.
2. **RESOLVED 2026-10-31 — add them to the ledger.** **PDL and the other §5.1 calls**: only add alerting (smaller), or also route them through the
   spend layer so their calls and credits appear in the ledger. Routing them also gives them the
   "recovered" email for free (the drain already closes incidents after successful calls, one update
   per provider per drain); without it, a §5.1 incident closes only when the next successful call
   records it.
3. **RESOLVED 2026-10-31 — leave them out.** **BuiltWith and Dun & Bradstreet**: like ZoomInfo/Clay/Apollo they have no production caller
   today. Leave them out of the key check too, or keep them in?

## 10. The Sentry alert rule (set up by the founder in Sentry, not in code)

Built 2026-10-31. The code sends one Sentry **error** event when a provider incident opens, tagged
`alert: provider` (plus `provider`, `reason`, `kind`), and one **info** event when it closes (no
`alert` tag). Lanes send events too, under `environment = lane-<name>`; only production emails.

Create one **issue alert** in the Sentry project the production DSN points at:

- **When:** a new issue is created, or an issue changes state from resolved to unresolved.
- **If (filters, all must match):** the event's tag `alert` equals `provider`, **and** the event's
  `environment` equals `production`.
- **Then:** send an email to `akeshri516@gmail.com` (that address must be a member of the Sentry
  organisation; Sentry emails only members).
- **Action interval:** 5 minutes is fine — each incident is its own issue (the fingerprint carries
  the provider, the reason and the open time), so one outage is one email.

Titles read like `People Data Labs refused: credits exhausted`, `Media model provider refused: quota
used up`, or `People Data Labs key PDL_API_KEY (worker) refused: API key missing`. The recovery
event (`… recovered after 2h 10m — 14 calls failed (…)`) is info-level and does not match the
filter; add a second rule on `level = info` with the same tag if recovery emails are wanted too.
