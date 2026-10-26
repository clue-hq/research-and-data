# Provider incidents — design

**Status:** draft for founder review (2026-09-16). Rulings taken in discussion the same day:
scope **B** (refusals and repeated failures), user surface **inline only**, operator channel
**Sentry only**, unit of notification **the incident** (one event on open, one on close).

## 1. The problem

External providers stop serving us and nobody is told. On 2026-09-16 alone: Exa's Search API
answered `402 NO_MORE_CREDITS`, Exa Websets halted a discovery run with `payment_required`, and
OpenRouter refused every model call for two hours with `403 Key limit exceeded (weekly limit)`.
The platform recorded each failure honestly — `provider_halted` in the discovery receipt,
`model_error` on 45 research jobs, `permission_denied_error` on a chat turn, 12 overview sections
left ungenerated — and told no human. The founder found out by opening the app and seeing empty
sections under an account marked "Researched".

Two audiences need to know, in different ways:

- **Clue's operators** (the founders) need one notification when a provider stops serving and one
  when it recovers, with counts. They fix the account, the key, or the cap.
- **The platform's users** need each affected surface to say *why* it is empty or failed, in one
  sentence, and that Clue already knows. No global banner (ruling).

## 2. What exists

- **The ARV2 provider caller** (`clue_api/arv2/calls.py::ProviderCaller`) is the one wrapper every
  Exa, OpenRouter-chat and live-HTTP call in the research lane goes through. It already evaluates a
  per-provider **halt rule** (`openrouter_halt_rule`, `exa_halt_rule`: 402, or a non-2xx body naming
  "credit"/"insufficient") and raises `ProviderHalted`, latching the provider for the rest of the
  run. It writes an estimate row and a result row to `provider_call_ledger` with `outcome`,
  `http_status`, `error_code`.
- **The model gateway** (`clue_gateway/agent_model.py::GovernedAgentChatModel`) carries every
  conversation-turn and research-agent model call. A provider 4xx/5xx surfaces as the OpenAI SDK's
  exception (`PermissionDeniedError`, `RateLimitError`, `APIStatusError`, …) and propagates
  unclassified; the research driver records it as `failure_code="model_error"`, the turn runner as
  an error code derived from the exception class name (`permission_denied_error`).
- **Sentry** (`clue_obs/sentry.py`): `install_sentry` at the roots behind `CLUE_SENTRY_ENABLED`
  (default `false`, DSN blank today), `capture(exc)` for exceptions. PII off, traces off.
- **Frontend surfaces** that show the consequences today: the research progress card
  (`frontend_read/research_progress.py`, pill `needs_attention`), the account detail overview
  sections (`frontend_read/account_detail.py`, generated on read by `display.ensure_page`), and the
  chat transcript's failed turn (`chat-transcript.ts`, `failureCode`).

## 3. Design

### 3.1 One classifier, two writers, one table, three readers

```
ProviderCaller ─┐                         ┌─ research progress card
                ├─ classify ─ recorder ─ provider_incident ─┼─ account overview sections
model gateway  ─┘        │                └─ failed chat turn
                         └─ Sentry: open / close events
```

### 3.2 The classifier (pure, shared)

`clue_core/provider_failures.py` — no I/O, importable by the gateway and the API.

```python
class ProviderFailure(FrozenContract):
    provider: str            # "openrouter" | "exa" | "exa_websets" | "live_http" | …
    kind: Literal["refusal", "failure"]
    reason: Literal[
        "credits_exhausted",   # 402; body names credits / insufficient / NO_MORE_CREDITS
        "key_limit",           # 403 body "Key limit exceeded"
        "auth_invalid",        # 401, or 403 without a limit message
        "account_suspended",   # body names suspended / disabled
        "rate_limited",        # 429  (failure, not refusal)
        "server_error",        # 5xx
        "timeout",             # transport timeout / connection error
    ]
    message: str             # the provider's own sentence, ≤ 300 chars, never request content

def classify_http(provider: str, status: int | None, body: str | None) -> ProviderFailure | None
def classify_exception(provider: str, exc: BaseException) -> ProviderFailure | None
```

Refusals: `credits_exhausted`, `key_limit`, `auth_invalid`, `account_suspended`. Failures:
`rate_limited`, `server_error`, `timeout`. A 2xx, a 404, a 4xx that is the caller's own fault
(400, 422) return `None` — those are not the provider refusing to serve. The existing halt rules
stay as they are (they decide the *run's* money behaviour); the classifier decides *incidents*,
and the two agree by construction on 402 and credit bodies.

### 3.3 The recorder (platform, durable)

`clue_api/provider_incidents.py` — one class, constructed at the roots with the conn factory.

```python
class ProviderIncidentRecorder:
    async def failed(self, failure: ProviderFailure, *, surface: str, workspace_id: str | None) -> None
    async def succeeded(self, provider: str) -> None
```

**Table** `provider_incident` (one migration, reversible):

| column | type | note |
|---|---|---|
| incident_id | uuid pk | |
| provider | text | |
| reason | text | the classifier's reason |
| kind | text | refusal / failure |
| opened_at | timestamptz | |
| last_failure_at | timestamptz | |
| failure_count | int | every classified failure while open |
| sample_message | text | first message seen |
| surfaces_json | jsonb | `{"research_job": 45, "display_section": 12, "chat_turn": 1}` |
| workspaces_json | jsonb | distinct workspace ids hit (for the inline reads) |
| closed_at | timestamptz null | |
| sentry_open_event_id / sentry_close_event_id | text null | proof the notification left the box |

Partial unique index `(provider, reason) WHERE closed_at IS NULL` — one open incident per
provider and reason, platform-wide (a key limit or an empty credit balance hits every tenant).

**Open rule.** A `refusal` opens on the first sight: `INSERT … ON CONFLICT DO NOTHING RETURNING
incident_id`; the process whose insert returned a row fires the Sentry open event; every other
process's failure is an `UPDATE … SET failure_count = failure_count + 1, last_failure_at, surfaces_json, workspaces_json`. A `failure` opens only when the same provider has **≥ 3 classified
failures within 5 minutes** — counted from `provider_call_ledger` result rows (the caller) and from
`agent_model_call` receipts (the gateway), which already exist; no new counter table.

**Close rule.** `succeeded(provider)` is called on every 2xx / successful completion. It runs
`UPDATE provider_incident SET closed_at = now() WHERE provider = :p AND closed_at IS NULL RETURNING
*`; the process that closed rows fires one Sentry close event per closed row. The read is cheap
(indexed partial scan); the write happens only when an incident was open.

**Sentry events.** `sentry_sdk.capture_message` (not `capture_exception`): level `error` on open,
`info` on close; tags `provider`, `reason`, `kind`; fingerprint `["provider-incident", provider,
reason, opened_at.isoformat()]` so open and close of one incident group together and two incidents
a week apart do not. Titles are the sentences the founder approved:

- open: `OpenRouter refused: key limit exceeded (weekly)`
- close: `OpenRouter recovered after 2h 14m — 57 calls failed (45 research jobs, 12 overview sections, 1 chat turn)`

When Sentry is not installed the recorder still writes the row and logs at `warning`
(`provider_incident.opened` / `.closed`); the event id columns stay null. Nothing here may raise
into the call it observes: the recorder catches and logs its own failures.

### 3.4 The two writers

> **Amended by the plan (2026-09-16).** The gateway hook below is superseded: `libs/clue-gateway`
> is not modified. The two writers are (1) the ARV2 provider caller, which classifies at settle
> time and stamps `extras["provider_failure"]` on the failing ledger row, with
> `drain_provider_calls` — the one function every ARV2 row passes through with a connection and a
> `LedgerStamp` — recording the incident (the research agent's model rounds are ledger rows too and
> get the same stamp from their exception); and (2) the chat turn's `DurableAgentModelCallHandler`,
> which classifies in `on_llm_error` and records through a connection factory. See
> `docs/superpowers/plans/2026-09-16-provider-incidents.md`, header.


- **ProviderCaller** gets an optional `incidents: ProviderIncidentRecorder | None`. In `_settle`
  (the result row) it calls `classify_http(spec.provider, status, body)`; a `ProviderFailure` →
  `failed(…, surface=<label family>)`, `None` on a 2xx → `succeeded(provider)`. `ProviderHalted`
  paths call `failed` too (they are refusals by definition). The caller is synchronous; the
  recorder exposes a sync façade over the conn factory the caller already has for its ledger.
- **GovernedAgentChatModel** gets an optional `failure_hook: Callable[[ProviderFailure | None], None]`
  set by the roots (`agent_runtime_wiring`, `fleet_main`). In `_generate`/`_agenerate`/`_stream`/
  `_astream` the existing `except` around the provider call passes `classify_exception("openrouter", exc)`
  to the hook before re-raising; a completed call passes `None` (success). The gateway stays free
  of Postgres and Sentry: it reports, the root records.

### 3.5 The classified reason stays on the row

So a surface explains itself after the incident closes:

- `arv2_research_job.failure_code` gains values `provider_refused:<provider>:<reason>` and
  `provider_failed:<provider>:<reason>` beside the existing `model_error` (a CHECK-free text column;
  the status vocabulary is unchanged: the job is still `needs_review`).
- `agent_turn` failure code: the turn runner maps a classified exception to
  `provider_refused:<provider>:<reason>` instead of the class-name-derived `permission_denied_error`.
- Display: `ensure_page` returns the sections it could not write with their `ProviderFailure` in a
  new `unavailable: tuple[(section_key, reason, message)]` beside `skipped_empty` / `stale_served`;
  no block row is written (as today), so the next read retries (as today).

### 3.6 The three readers (inline only)

One sentence builder in `clue_api/provider_incidents.py`:

```python
def incident_sentence(failure_or_incident) -> str
# "Model provider refused: key limit exceeded (weekly). Since 16:01, 45 jobs affected. Clue has been notified."
# "Discovery provider refused: credits exhausted. Since 14:39. Clue has been notified."
# "Model provider failing: server errors. Since 09:12, 7 calls affected. Clue has been notified."
```

"Clue has been notified" is said only when a Sentry event id exists on the incident; otherwise
the sentence ends at the count. Provider display names: `openrouter → Model provider`,
`exa`/`exa_websets` → `Discovery provider`, `live_http` → `Website fetch`.

| surface | payload change | rendering |
|---|---|---|
| research progress card (`research_progress.py`) | `incident: {provider_label, reason_label, since, affected, notified} \| null` when any job in the run carries a `provider_*` failure code; taken from the open incident if one exists, else from the jobs' own codes | under the pill: the sentence, replacing the raw `PermissionDeniedError…` text shown today |
| account overview sections (`account_detail.py`) | each section entry gains `unavailable: {reason_label, message} \| null` from `ensure_page` | an empty section renders "Not generated: model provider refused (key limit exceeded). Retries automatically." instead of blank |
| failed chat turn | the turn's `failureCode` is `provider_refused:…`; the transcript maps it through the same label table | the error part reads the sentence instead of `permission_denied_error` |

No new frontend route. The three payloads already exist; each gains one optional field validated
by its Zod schema.

### 3.7 Configuration

No new flags. Sentry uses the existing `CLUE_SENTRY_ENABLED` / `CLUE_SENTRY_DSN` /
`CLUE_SENTRY_ENVIRONMENT`. The failure threshold (3 in 5 minutes) is a constant in the recorder
with its reasoning in a comment; a founder-tuned knob is not warranted until the number is wrong.

### 3.8 What this does not do

- No global banner, no email, no user-triggered report (rulings).
- No retry policy changes: the caller's retries and the gateway's fallback are untouched.
- No spend cap, no auto-pause of runs. A run that hits a refusal still halts the way it does today;
  the incident is a record and a notification, not an authority.
- Design-subsystem image/ad calls are not on any ledger (founder ruling 2026-09-15) and stay out.

## 4. Testing

- Classifier: table-driven tests over the real bodies seen on 2026-09-16 (Exa `NO_MORE_CREDITS`
  402, Websets `payment_required`, OpenRouter `Key limit exceeded` 403, a 429, a 503, a 404 that
  must return `None`).
- Recorder (DB tests on the lane database): a refusal opens once across two concurrent writers;
  a second refusal increments; three failures in five minutes open, two do not; a success closes
  and stamps `closed_at`; Sentry receives exactly one open and one close (fake transport).
- Writers: the caller's result path calls `failed`/`succeeded`; the gateway hook receives a
  classified failure on a `PermissionDeniedError` and `None` on success.
- Readers: research-progress and account-detail payload tests with an open incident and with
  a closed one (jobs' own codes still explain); frontend model tests for the label table and the
  three sentences.
- Live: flip `CLUE_SENTRY_DSN` to a real project on the lane, force one refusal with the lane's
  exhausted Exa Search key, see the open event; top up or swap the key, see the close event.

## 5. Founder answers (2026-09-16)

1. **Sentry is configured.** The lane `.env` already carries `CLUE_SENTRY_ENABLED=true`, a DSN
   for the Clue Sentry project and `CLUE_SENTRY_ENVIRONMENT=lane-san-salvador`. The running API
   and worker processes booted before the flag was turned on (their boot log says
   `sentry.not_installed`), so the first restart after this lands is also the moment Sentry goes
   live; the plan's live step restarts the stack.
2. **A 429 counts as a failure** toward the 3-in-5-minutes threshold, like a 5xx or a timeout.
