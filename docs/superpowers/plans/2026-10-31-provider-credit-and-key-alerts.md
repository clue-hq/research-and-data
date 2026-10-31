# Provider Credit and Key Alerts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every paid or keyed external provider that runs out of credits or quota, refuses its key, or has no key at a service's start-up opens one provider incident and one Sentry event (emailed from production only, by a Sentry alert rule).

**Architecture:** The incident recorder moves from `clue_api` into the shared spend library (`clue_spend.incidents`), and the library's own ledger drain records incidents — so every spend scope in every subsystem (design request scopes, ingestion-pool coordinators, conversation naming) feeds it without a platform shim. The calls that bypass the spend layer today are routed through it with one async helper (`clue_spend.acall`). A data-only key registry (`clue_spend.key_check`) is checked at each app role's start-up and opens a `key_missing` incident per `(role, env name)`.

**Tech Stack:** Python 3.12, SQLAlchemy async + asyncpg, sentry-sdk 2.x, httpx, pytest.

**Spec:** `docs/superpowers/specs/2026-10-31-provider-credit-and-key-alerts-design.md` (extends `docs/superpowers/specs/archive/2026-09-16-provider-incidents-design.md`, whose rules stand unless this one changes them).

## Global Constraints

- New refusal reasons, open on first sight: `quota_exhausted` (words "quota used up"), `key_missing` (words "API key missing"). Existing refusals/failures and the 3-in-5-minutes failure threshold are unchanged.
- `quota_exhausted` = a 429 or 403 whose body matches `quota|resource_exhausted|usage limit|quotaexceeded` (case-insensitive). A 429 without those words stays `rate_limited`. 402 stays `credits_exhausted`.
- A `key_missing` incident's `provider` value is `"<role>:<ENV_NAME>"` (e.g. `design-api:PDL_API_KEY`); roles are exactly `platform-api`, `design-api`, `worker` (`deploy/check_prod_env.py` `APP_ROLES`). Only that role's start-up check closes it; `record_success(conn, "<provider id>")` never touches it (its `provider` never equals a provider id).
- Design-side OpenRouter refusals are incidents under provider id `openrouter_design` (display "Design model provider"). Their **ledger rows keep `provider='openrouter'`** — `clue_projections/cost.py:214` groups model spend by that value (ruling, see Task 4).
- Sentry open events (`level="error"`) carry the extra tag `alert=provider`; close events do not. Fingerprint and titles as in the 2026-09-16 design.
- An incident row with `sentry_open_event_id IS NULL` is sent by the next process with Sentry installed that touches it (increment path or start-up check), then stamped.
- Never put a key value, request body or auth header in a Sentry event, log line, incident row or ledger extras. `key_missing` messages name the env variable only: `"<ENV_NAME> is not set"`.
- The recorder, the drain hook, `acall` and the start-up check never raise into the observed call or into start-up; failures log `provider_incident.recorder_failed` / `provider_keys.check_failed`.
- Out of scope: ZoomInfo, Clay, Apollo, BuiltWith, Dun & Bradstreet (not checked, not routed); Firecrawl and Sumble (out of the stack); Langfuse, S3/R2, keyless media downloads.
- No new env flag. Sentry keeps `CLUE_SENTRY_ENABLED` / `CLUE_SENTRY_DSN` / `CLUE_SENTRY_ENVIRONMENT`.
- Import seams: `clue_spend` may import only `clue_core`, `clue_obs`, `clue_storage`, SQLAlchemy (root `pyproject.toml` contract "the spend seam imports no platform or subsystem internals"). The design tree never imports `clue_api`. `clue_research` and `clue_auth` may import `clue_spend` once their own `pyproject.toml` declares `clue-spend` (and `clue-obs` for `clue_auth`).
- Tests run only through `.superpowers/review/2026-10-13-wave2/pytest-keyless.sh <one file>` with a hard timeout; never a whole folder; never `*_live.py`; DB suites use that wrapper's test DB. `uv run lint-imports` after Tasks 2, 8, 10.
- Commits: local only, no push, no AI attribution, on `fix/design-reference-ads` (founder 2026-10-31).

## Rulings in this plan (beyond the spec)

- **Parallel is not routed.** `register_synthesis_wiring` has no production caller (`synthesis_wiring.py:39`), so the path is dormant like BuiltWith/D&B. Cost if wrong: one more `acall` site later.
- **Clerk's JWKS refresh (`clue_auth/providers/clerk.py:67`) is not routed.** It runs before a principal exists (no workspace for the ledger stamp) and fetches public keys. Clerk's management API (`clerk_api.py`) is routed.
- **The ingestion pool does not run its own key check.** On the worker VM it reads the same env file as the fleet worker (`/srv/clue/env`), so the `worker` role's check covers it.
- **Customer readers need no code change.** They filter `open_incidents(providers=["openrouter"])` (display pages) or the job's own provider id (research progress); `key_missing` and `openrouter_design` rows never match. Task 12 pins this with a test.

## Review Focus

1. A provider refusing hundreds of calls inside one drain or across many processes → exactly one open incident and one Sentry event (pinned in Task 3).
2. A key missing for a role in one service and present in another role → two independent incidents, neither closed by the other's start-up or by ordinary successful calls (pinned in Task 11).
3. The database is unreachable while a drain records incidents or while the start-up check runs → the job, call or start-up proceeds; one `recorder_failed` / `check_failed` log (pinned in Tasks 3 and 11).
4. A `key_missing` or `openrouter_design` incident is open while a customer opens an account overview or research card → no "refused" sentence for it (pinned in Task 12).
5. A Sentry event for any incident contains no key value: the `sample_message` of a `key_missing` incident is exactly `"<ENV_NAME> is not set"` (pinned in Task 11).

---

### Task 1: Two new reasons in the classifier

**Files:**
- Modify: `libs/clue-core/clue_core/provider_failures.py` (`FailureReason`, `_REFUSALS`, `_reason_for`, new `_QUOTA_WORDS`)
- Test: `tests/core/test_provider_failures.py`

**Interfaces:**
- Produces: `FailureReason` gains `"quota_exhausted"`, `"key_missing"`; both in `_REFUSALS`. `classify_http` unchanged in signature.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("status, body", [
    (429, '{"error": {"status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded"}}'),
    (403, '{"error": {"errors": [{"reason": "quotaExceeded"}]}}'),
    (429, "monthly usage limit reached"),
])
def test_quota_replies_are_a_quota_refusal(status, body):
    failure = classify_http("gemini", status, body)
    assert (failure.kind, failure.reason) == ("refusal", "quota_exhausted")

def test_a_plain_429_is_still_a_rate_limit():
    assert classify_http("brandfetch", 429, "Too Many Requests").reason == "rate_limited"

def test_402_stays_credits_exhausted():
    assert classify_http("composio", 402, "Payment Required").reason == "credits_exhausted"

def test_key_missing_round_trips_through_failure_code():
    assert parse_failure_code(failure_code(ProviderFailure("pdl", "refusal", "key_missing", "x"))) == ("pdl", "refusal", "key_missing")
```

Use the module's existing `failure_code`/`parse_failure_code` signatures; adapt the last assertion to what `parse_failure_code` returns today.

- [ ] **Step 2: Run, verify FAIL** — `pytest-keyless.sh tests/core/test_provider_failures.py` → the quota cases return `rate_limited`/`auth_invalid`; `key_missing` is rejected by `parse_failure_code`.
- [ ] **Step 3: Implement.** Quota check runs before the credit/key-limit/suspended/auth checks for 403 and before the 429 → `rate_limited` branch.
- [ ] **Step 4: Run, verify PASS** (whole file).
- [ ] **Step 5: Commit** — `Classify quota-used-up replies as a refusal and add the key_missing reason`.

### Task 2: The recorder moves into `clue_spend.incidents`

**Files:**
- Create: `libs/clue-spend/clue_spend/incidents.py` (moved body of `platform/api/clue_api/provider_incidents.py`)
- Modify: `platform/api/clue_api/provider_incidents.py` → re-export only (same `__all__`); `libs/clue-spend/clue_spend/__init__.py` exports
- Modify: `libs/clue-spend/clue_spend/ledger.py` `_stamped_failure` (honour an override provider, below)
- Test: `tests/api/test_provider_incidents_db.py` (existing, must stay green unchanged), new `tests/spend/test_incidents_db.py`

**Interfaces:**
- Produces (in `clue_spend.incidents`, same signatures as today): `record_failure(conn, failure, *, surface, workspace_id, now) -> OpenIncident | None`, `record_success(conn, provider, *, now) -> tuple[OpenIncident, ...]`, `open_incidents(conn, *, providers=None)`, `OpenIncident`, `incident_sentence(...)`, `provider_display(provider) -> str`, `reason_words(reason) -> str`, `FAILURE_THRESHOLD`, `FAILURE_WINDOW`.
- Produces: `PROVIDER_DISPLAY: dict[str, str]` — add `openrouter_design: "Design model provider"`, `pdl: "People Data Labs"`, `deepgram: "Transcription provider"`, `gemini: "Media model provider"`, `adyntel: "Ad library"`, `brandfetch: "Logo provider"`, `composio: "CRM connector"`, `cloudflare: "Custom domains"`, `clerk: "Sign-in provider"`, `youtube_data: "YouTube"`, `podcast_index: "Podcast Index"`, `ai_ark: "Contact data provider"`.
- Produces: `provider_display("design-api:PDL_API_KEY") == "People Data Labs key PDL_API_KEY (design-api)"` — a `role:ENV` value resolves its provider through `clue_spend.key_check.provider_for_env` (Task 11; until then, fall back to the env name: `"PDL_API_KEY (design-api)"`).
- Produces: a ledger row's `extras["provider_failure"]` may carry `"provider"`; `_stamped_failure` uses it instead of `row.provider` when present (Task 4 relies on this).

- [ ] **Step 1: Write the failing tests** in `tests/spend/test_incidents_db.py` (reuse the DB/Sentry fixtures of `tests/api/test_provider_incidents_db.py`):
  - `test_open_event_carries_the_alert_tag` — capture events with a recording Sentry transport; after `record_failure(... credits_exhausted ...)` the event's tags include `alert: "provider"`; after `record_success` the close event has no `alert` tag.
  - `test_an_unsent_open_event_is_sent_by_the_next_recorder` — insert an open incident with `sentry_open_event_id NULL` (Sentry not installed), install Sentry, call `record_failure` for the same `(provider, reason)`; one error event is captured and the row's `sentry_open_event_id` is now set; a third call sends nothing.
  - `test_stamped_failure_prefers_the_override_provider` — a `LedgerRow(provider="openrouter", extras={"provider_failure": {"kind": "refusal", "reason": "credits_exhausted", "message": "m", "provider": "openrouter_design"}})` → `_stamped_failure(row).provider == "openrouter_design"`.
  - `test_role_key_display` — `provider_display("worker:ADYNTEL_API_KEY")` contains `"ADYNTEL_API_KEY"` and `"(worker)"`.
- [ ] **Step 2: Run, verify FAIL** (import error for `clue_spend.incidents`).
- [ ] **Step 3: Move the code**; add the tag in `_sentry_event` when `level == "error"`; add the late-send on the increment path (when the incremented row's `sentry_open_event_id` is NULL and `sentry_is_installed()`); keep `clue_api.provider_incidents` as a pure re-export so its three readers and two writers are untouched.
- [ ] **Step 4: Run, verify PASS** — the new file and `tests/api/test_provider_incidents_db.py` unchanged; `uv run lint-imports` clean.
- [ ] **Step 5: Commit** — `Move the provider-incident recorder into clue_spend so every subsystem can record`.

### Task 3: The library drain records incidents

**Files:**
- Modify: `libs/clue-spend/clue_spend/ledger.py` `drain_provider_calls` / `record_drain`
- Modify: `platform/api/clue_api/arv2/provider_ledger.py` → re-export the library drain (keep the module's names)
- Test: `tests/spend/test_drain_incidents_db.py`; existing `tests/api/test_provider_incidents_db.py`

**Interfaces:**
- Consumes: Task 2 recorder.
- Produces: `clue_spend.drain_provider_calls(conn, *, raw, ledger, artifacts, stamp, held=None, record_incidents: bool = True) -> DrainReport` — with `record_incidents=True` it does what `clue_api.arv2.provider_ledger.drain_provider_calls` does today (record each stamped failure, then close a provider only when its last word in the batch was a success, one `record_success` per provider). The `on_failure` parameter is removed; the one caller passing it is the platform shim.

- [ ] **Step 1: Write the failing tests:**
  - `test_the_bare_library_drain_opens_an_incident` — buffer one `result` row with a stamped `credits_exhausted` failure for `pdl`, call `clue_spend.drain_provider_calls(..., artifacts=None)`; `open_incidents(providers=["pdl"])` has one row.
  - `test_two_hundred_refusals_in_one_drain_open_one_incident` — 200 stamped refusal rows for `exa`; one open incident, `failure_count == 200`, one captured Sentry error event.
  - `test_a_drain_whose_recorder_fails_still_writes_its_rows` — patch `record_failure` to raise; rows are inserted, the drain returns its report, `provider_incident.recorder_failed` is logged.
- [ ] **Step 2: Run, verify FAIL** (no incident opened by the bare drain).
- [ ] **Step 3: Implement** — move the fold-by-time logic from the shim into the library; the shim becomes re-exports (keep `_INSERT_LEDGER`, `_ledger_params` reachable — the existing incident tests import them).
- [ ] **Step 4: Run, verify PASS** — the new file, `tests/api/test_provider_incidents_db.py`, and the existing design spend drain tests (`subsystems/clue-design/apps/api/tests/test_spend_scope.py`).
- [ ] **Step 5: Commit** — `The shared ledger drain records provider incidents for every spend scope`.

### Task 4: Design-side refusals are `openrouter_design`

**Files:**
- Modify: `libs/clue-spend/clue_spend/calls.py` (`CallSpec.incident_provider: str | None = None`; `_failure_extras` writes `"provider": incident_provider` into `provider_failure` when set)
- Modify: `subsystems/clue-design/apps/api/lumen_api/spend.py` (the OpenRouter call helper at ~L200 passes `incident_provider="openrouter_design"`; `record_collected_model_call` stamps `extras["provider_failure"]` from the receipt)
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/usage_collector.py` (`CollectedModelCall.provider_failure: dict | None = None`; `on_llm_error` sets it from `classify_exception("openrouter_design", error)` as `{"kind","reason","message","provider"}`)
- Test: `subsystems/clue-design/apps/api/tests/test_spend_scope.py`, `subsystems/clue-design/apps/agent_runtime/tests/test_usage_collector.py` (create if absent)

**Interfaces:**
- Consumes: Task 2 `_stamped_failure` override.
- Produces: design ledger rows keep `provider="openrouter"`; their stamped failure names `openrouter_design`.

- [ ] **Step 1: Write the failing tests:**
  - `test_a_design_model_refusal_is_stamped_as_the_design_provider` — a fake transport answers 402 to the design OpenRouter helper inside `spend_scope`; the scope's ledger result row has `provider == "openrouter"` and `extras["provider_failure"]["provider"] == "openrouter_design"`.
  - `test_a_failed_agent_call_carries_its_classified_failure` — `on_llm_error` with an exception carrying `status_code=402` → the collected call's `provider_failure["reason"] == "credits_exhausted"` and `["provider"] == "openrouter_design"`; `record_collected_model_call` copies it into the row's extras.
- [ ] **Step 2: Run, verify FAIL.**
- [ ] **Step 3: Implement.** `lumen_agent` imports `clue_core.provider_failures` (already a design dependency).
- [ ] **Step 4: Run, verify PASS** (both files).
- [ ] **Step 5: Commit** — `Design-side model refusals open their own incident; cost rows keep the openrouter provider`.

### Task 5: `clue_spend.acall` — one async call plus its own drain

**Files:**
- Create: `libs/clue-spend/clue_spend/acall.py`; export from `clue_spend/__init__.py`
- Test: `tests/spend/test_acall_db.py`

**Interfaces:**
- Produces: `async def acall(spec: CallSpec, *, conn_factory: Callable[[], AsyncContextManager[AsyncConnection]], stamp: LedgerStamp, transport: Transport | None = None) -> HttpResponse` — builds buffered sinks and a `ProviderCaller` (`HttpxTransport()` by default), runs `caller.call(spec)` in `asyncio.to_thread`, then **in `finally`** drains with `drain_provider_calls(conn, ..., artifacts=None, stamp=stamp)` inside `async with conn_factory() as conn`; returns the response or re-raises the caller's error after draining. A drain failure is logged (`provider_incident.recorder_failed`) and never replaces the call's own result or error.

- [ ] **Step 1: Write the failing tests:** `test_acall_returns_the_response_and_ledgers_it` (fake transport 200 → one result row), `test_acall_ledgers_a_402_and_opens_an_incident` (fake 402 → row + open incident; the 402 response is returned, not raised, since `call` returns non-2xx responses), `test_acall_returns_even_when_the_drain_fails` (conn_factory raises → response still returned).
- [ ] **Step 2: Run, verify FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, verify PASS.**
- [ ] **Step 5: Commit** — `Add clue_spend.acall: one ledgered async provider call with its own drain`.

### Task 6: PDL through the spend layer

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_ingestion/ad_library/pdl.py` `_get` — copy `adyntel.py` `_post`: `spend.caller().call(CallSpec(provider="pdl", operation="design.ad_library.identity", label="ad_library:company identity", request=HttpRequest(method="GET", url=f"{self.endpoint}?website={quote(domain)}", headers={"X-Api-Key": …, "Accept": "application/json"}, …), estimate=SpendEstimate(credits=Decimal(1)), max_attempts=1, binary=False))`. 404 → `None`; ≥400 → `CompanyIdentityError("company_identity.http_error", …)` as today.
- Test: `subsystems/clue-design/apps/api/tests/test_ad_library_pdl.py` (create if absent; else the existing PDL test file)

**Interfaces:**
- Consumes: the design `spend_scope` already open in `execute_ingestion_job` (`lumen_api/main.py:12734`); Task 3 makes its drain record incidents (pool coordinators included).

- [ ] **Step 1: Write the failing test** `test_a_pdl_402_is_ledgered_as_credits_exhausted` — inside `spend_scope` with a fake transport answering 402 for the PDL URL, `PdlResolver(api_key="k").resolve("pallet.com")` raises `CompanyIdentityError`; the scope ledger holds one `provider="pdl"` result row whose `extras["provider_failure"]["reason"] == "credits_exhausted"`; the request headers recorded in the raw sink do not appear in `extras`.
- [ ] **Step 2: Run, verify FAIL** (no ledger row: PDL uses `httpx.get`).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, verify PASS** plus `subsystems/clue-design/apps/api/tests/test_ad_assets_onboarding.py`.
- [ ] **Step 5: Commit** — `Route the PDL identity lookup through the spend layer`.

### Task 7: Exa deep acquisition through `acall`

**Files:**
- Modify: `platform/api/clue_api/exa_deep_acquisition.py` `ExaDeepHttpAcquisitionTransport.search` (~L123) — build a `CallSpec(provider="exa", operation="research.exa_deep.search", …)` and call `acall` with the coordinator's `conn_factory` and `LedgerStamp(workspace_id=…, job_id=<the entity research job id>)`; map a non-2xx `HttpResponse` to the same `ExaDeepRequestFailure` cases as today (`:134-160`).
- Modify: the three transport builders (`entity_research_provider_wiring.py:309,555`, `contact_research_preparation.py:815`, `exa_deep_preparation.py:312`) to pass `conn_factory`.
- Test: the existing exa-deep acquisition test file (find with `rg -l ExaDeepHttpAcquisitionTransport tests`)

- [ ] **Step 1: Write the failing test** `test_an_exa_deep_402_is_ledgered_and_opens_an_incident` (fake transport, test DB).
- [ ] **Step 2: Run, verify FAIL.**
- [ ] **Step 3: Implement.** Keep the call sync-in-thread semantics: `search` is already run via `asyncio.to_thread` at `:285`; make `search` async and drop that thread hop, or keep it sync and call `caller.call` directly with a scope drained by the async caller — choose the one that keeps `acquire`'s error handling unchanged, and ledger the choice as a ruling.
- [ ] **Step 4: Run, verify PASS** (the file + existing exa-deep tests).
- [ ] **Step 5: Commit** — `Route Exa deep acquisition through the spend layer`.

### Task 8: Exa Websets lifecycle through `acall`

**Files:**
- Modify: `subsystems/research/pyproject.toml` (add `clue-spend`)
- Modify: `subsystems/research/clue_research/adapters/exa_websets.py` — the adapter takes an injected `send: Callable[[CallSpec], Awaitable[HttpResponse]]`; `_raw_request` (~L1373) and `upload_import_csv` (~L1151) build `CallSpec(provider="exa_websets", …)` and await `send`; transport errors map to the adapter's existing typed errors (`_provider_error` ~L1404).
- Modify: the builders in `clue_api` (`exa_websets_lifecycle.py`, `exa_targeted_enrichment.py`, `frontend_read/contact_email_lookup.py`) pass `send=functools.partial(acall, conn_factory=…, stamp=LedgerStamp(workspace_id=operation.workspace_id))`.
- Test: the existing websets adapter test file; add `test_a_websets_payment_required_is_ledgered`.

- [ ] **Step 1: Write the failing test.**
- [ ] **Step 2: Run, verify FAIL.**
- [ ] **Step 3: Implement.** The presigned CSV PUT goes to object storage, not Exa: route it with `provider="exa_websets"` only if it is billed; otherwise leave it on its client and record that as a ruling.
- [ ] **Step 4: Run, verify PASS**; `uv run lint-imports` clean.
- [ ] **Step 5: Commit** — `Route the Exa Websets lifecycle adapter through the spend layer`.

### Task 9: Composio and Cloudflare through `acall`

**Files:**
- Modify: `platform/api/clue_api/crm/composio_gateway.py` `_request` (~L218) and `delete_account` (~L165) — `CallSpec(provider="composio", operation="crm.composio.<op>", estimate=SpendEstimate(credits=Decimal(0)))` through `acall` with the gateway's `conn_factory` and `LedgerStamp(workspace_id=…)`; non-2xx keeps raising `ComposioError` via `_http_error`. Add `402 → kind="credits"` beside the existing kinds if `ComposioError` has a kind list (keeps today's `bad_request` mapping for other 4xx).
- Modify: `platform/api/clue_api/cloudflare_custom_hostnames.py` `_request` (~L94) — each attempt of its retry loop is one `acall` with `max_attempts=1`; `provider="cloudflare"`.
- Test: the existing composio gateway and cloudflare test files; add `test_a_composio_402_opens_an_incident`, `test_a_cloudflare_403_is_ledgered`.

- [ ] **Steps 1–5** as above. Commit — `Route Composio and Cloudflare calls through the spend layer`.

### Task 10: Clerk's management API through an injected sender

**Files:**
- Modify: `platform/auth/pyproject.toml` (add `clue-spend`, `clue-obs`)
- Modify: `platform/auth/clue_auth/providers/clerk_api.py` `ClerkApi._request` (~L36) — optional constructor arg `send: Callable[[CallSpec], Awaitable[HttpResponse]] | None`; when set, requests go through it with `provider="clerk"`; when `None`, today's per-call `AsyncClient`.
- Modify: `projections_app.py:985`, `frontend_read/settings.py:206` to pass `send=partial(acall, conn_factory=…, stamp=LedgerStamp(workspace_id=<acting workspace>))`. A Clerk call made with no workspace in hand keeps `send=None` (ruling).
- Test: the existing clerk_api test file; add `test_a_clerk_401_through_send_is_ledgered`.

- [ ] **Steps 1–5** as above; `uv run lint-imports` clean. Commit — `Route Clerk's management API through the spend layer`.

### Task 11: The start-up key check

**Files:**
- Create: `libs/clue-spend/clue_spend/key_check.py`
- Modify: `platform/api/clue_api/projections_app.py` (`_projections_lifespan`, after `db_lifespan`), `platform/fleet/.../fleet_main.py` `_serve` (after `db_lifespan()` at ~:1074), `subsystems/clue-design/apps/api/lumen_api/main.py` (design API start-up, via a private engine like `spend.drain_sync`)
- Test: `tests/spend/test_key_check_db.py`

**Interfaces:**
- Produces: `KeyRequirement(provider: str, env_names: tuple[str, ...], roles: frozenset[str])` — one requirement is satisfied when **any** of its `env_names` is non-blank (fallback pairs).
- Produces: `PROVIDER_KEYS: tuple[KeyRequirement, ...]` — starting rows (the builder verifies each role against where the setting is read and drops a role that never reads it; ledger each drop):
  - `openrouter` — `CLUE_OPENROUTER_API_KEY`|`OPENROUTER_API_KEY` — platform-api, design-api, worker
  - `openrouter_design` — `LUMEN_AGENT_API_KEY` — design-api, worker; `IMAGE_MODEL_API_KEY` — design-api, worker (two rows)
  - `gemini` — `CLUE_GEMINI_API_KEY` — worker
  - `deepgram` — `CLUE_DEEPGRAM_API_KEY`|`DEEPGRAM_API_KEY` — worker
  - `youtube_data` — `CLUE_YOUTUBE_DATA_API_KEY` — worker
  - `podcast_index` — `CLUE_PODCAST_INDEX_API_KEY`; `CLUE_PODCAST_INDEX_API_SECRET` — worker (two rows)
  - `exa` — `CLUE_EXA_API_KEY` — platform-api, worker
  - `ai_ark` — `CLUE_AI_ARK_API_KEY` — worker
  - `pdl` — `PDL_API_KEY` — worker
  - `adyntel` — `ADYNTEL_API_KEY`; `ADYNTEL_EMAIL` — worker (two rows)
  - `brandfetch` — `BRANDFETCH_API_KEY` — worker
  - `composio` — `CLUE_COMPOSIO_API_KEY` — platform-api, worker
  - `cloudflare` — `CLUE_CLOUDFLARE_API_TOKEN` — platform-api
  - `clerk` — `CLUE_AUTH_CLERK_SECRET_KEY` — platform-api
- Produces: `provider_for_env(env_name: str) -> str | None` (used by Task 2's display).
- Produces: `async def check_provider_keys(conn_factory, *, role: str, environ: Mapping[str, str], now: datetime) -> None` — for each requirement listing `role`: all names blank → `record_failure(conn, ProviderFailure(f"{role}:{env_names[0]}", "refusal", "key_missing", f"{env_names[0]} is not set"), surface="startup", workspace_id=None, now=now)`; any name set → `record_success(conn, f"{role}:{env_names[0]}", now=now)`. An open `key_missing` row with no `sentry_open_event_id` is sent (Task 2's late-send). Never raises: logs `provider_keys.check_failed`.
- Produces: `def check_provider_keys_blocking(*, role: str, environ: Mapping[str, str], database_url: str) -> None` for the design API (private engine, one loop, like `lumen_api.spend.drain_sync`).
- Start-up wiring runs the check as a background task (platform API, fleet worker) or a background thread (design API) so start-up never waits on it.

- [ ] **Step 1: Write the failing tests:**
  - `test_a_missing_key_opens_one_incident_per_role_and_env` — `check_provider_keys(role="worker", environ={})` twice → open incident `worker:PDL_API_KEY` with `sample_message == "PDL_API_KEY is not set"`, `failure_count == 2`, one Sentry error event.
  - `test_a_fallback_name_satisfies_the_requirement` — `environ={"DEEPGRAM_API_KEY": "x"}` → no `worker:CLUE_DEEPGRAM_API_KEY` incident.
  - `test_present_in_one_role_does_not_close_another_roles_incident` — open via `role="worker"` with `{}`; run `role="platform-api"` with every key set; `worker:PDL_API_KEY` still open; `record_success(conn, "pdl")` leaves it open too.
  - `test_the_same_role_with_the_key_closes_it` — then `role="worker"` with `PDL_API_KEY` set → closed, one info event.
  - `test_a_key_value_never_reaches_sentry` — `environ={"PDL_API_KEY": "   ", "ADYNTEL_API_KEY": "secret-value-123"}` (whitespace counts as blank) → a `worker:PDL_API_KEY` incident with message `"PDL_API_KEY is not set"`; no captured Sentry event and no incident row contains `"secret-value-123"`.
  - `test_the_check_never_raises` — `conn_factory` raises → returns `None`, logs `provider_keys.check_failed`.
  - `test_left_out_providers_are_not_checked` — no requirement names ZoomInfo, Clay, Apollo, BuiltWith, DUNS, Firecrawl or Sumble env names.
- [ ] **Step 2: Run, verify FAIL.**
- [ ] **Step 3: Implement** the module and the three start-up hooks.
- [ ] **Step 4: Run, verify PASS**; then restart the trenton stack (`scripts/dev_stack_trenton.sh restart`) and confirm in `provider_incident` that the lane's empty keys opened `key_missing` rows and no service failed to start.
- [ ] **Step 5: Commit** — `Check provider keys at start-up and open a key_missing incident per role and env name`.

### Task 12: Customer surfaces, operator note, memory

**Files:**
- Test: `tests/api/test_provider_incidents_db.py` (add `test_customer_readers_ignore_key_missing_and_design_incidents`)
- Modify: `docs/superpowers/specs/2026-10-31-provider-credit-and-key-alerts-design.md` — append §10 "Sentry alert rule" (append): the exact rule — issue alert, filter tag `alert` equals `provider` AND `environment` equals `production`, action email `akeshri516@gmail.com` (must be an org member); frequency once per issue.
- Create: `_memory/2026-10-31-provider-credit-and-key-alerts.md` (what changed, verification, owed: the Sentry rule, the PDL top-up, a production key-check walk).

- [ ] **Step 1: Write the failing test** — open incidents for `openrouter_design` (credits_exhausted) and `platform-api:CLUE_OPENROUTER_API_KEY` (key_missing); `open_incidents(conn, providers=["openrouter"])` is empty (passes immediately if readers are already safe — then it is a regression pin, record that in the ledger).
- [ ] **Step 2–4:** run, write the docs.
- [ ] **Step 5: Commit** — `Pin that customer surfaces never show alert-only incidents; record the Sentry rule`.
