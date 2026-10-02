# ARV2 R1 — Step 0 foundation and the six provider clients

**Spec:** `docs/specs/ARV2-MASTER-PLAN.md` (v1.6; §3 the stack, §4 data model, §9 Track R R1,
Appendix A laws), `docs/specs/ARV2-WORK-SPLIT.md` (§6.3 the AI Ark charter shape),
`docs/specs/ARV2-PRODUCT-CATALOG-CONTRACT.md` §3 (the second Exa `outputSchema`),
`docs/specs/ARV2-ai-ark-contract-notes.md`. Founder rulings taken in the 2026-09-07 session (Aryan):
tests run **live against the real providers** (no replay fixtures); Gemini `gemini-3.5-transcribe`
is called on Google's native endpoint (the one exception to "OpenRouter only"); flash-lite and
embeddings go through OpenRouter; AI Ark key present and validated; all keys in the local `.env`.

**Branching.** Task 1 commits on `track-R` directly. Tasks 2–7 each run on their own worktree and
branch `task/R1-<name>` cut from `track-R` after Task 1 lands; the controller merges each into
`track-R` after review. Nothing is pushed.

---

## Global Constraints (bind every task)

1. **Appendix A laws 1–2 are implemented once, in the Step 0 wrapper, and every client calls
   through it.** Law 1: save the raw response (every attempt) before parsing; annotate status,
   latency and the redacted request; then write the ledger row. **Law 3 runs first (amended
   2026-09-07 after review):** when a spec carries a `raw_scrubber`, the scrubbed body replaces
   the response the moment it arrives, so the raw record, the cost reader, the halt rule and the
   returned `CallResult` all carry the same bytes and a dropped key exists on no path. Law 2: record the pre-spend
   estimate before the wire; retries honour `Retry-After`, else `12·(n+1)` s for 429/5xx and
   `2·(n+1)` s for transport errors, `n` = zero-based attempt index, default 4 attempts.
2. **Money truth blocks; money caps only record** (master plan §2 item 3). A ceiling sets
   `over_ceiling=true` on the ledger row and the call proceeds. A 402/403, a body naming
   "credit", or an unknown-spend state raises a typed halt and latches that provider.
3. **Live tests only.** Tests under `tests/arv2/` call the real provider with the key read from
   the local `.env` through `clue_config.Secrets()`; when a key is unset the test
   `pytest.skip`s with the key's name in the reason. No recorded-response replay, no mocked
   provider bodies. The **wrapper's own retry/halt arithmetic** (Task 1) is unit-tested with a
   scripted transport because timing cannot be asserted live; that is the only test double.
4. **Raw output of test runs goes under `.artifacts/arv2/`** (already git-ignored): raw records
   in `.artifacts/arv2/raw/<provider>/`, the ledger in `.artifacts/arv2/ledger.jsonl`. Never
   commit anything under `.artifacts/`.
5. **No secret anywhere** except `.env`: not in code, tests, reports, commit messages, raw
   records (headers `Authorization`, `X-TOKEN`, `x-api-key`, `x-goog-api-key` and the `key`
   query parameter are redacted before a raw record is written), or `.context/`.
6. **Every configuration knob the code reads is a `Settings`/`Secrets` field and a line in
   `.env.example` with its default, in the same commit** (CLAUDE.md parity rule). Never change
   an existing `.env.example` value.
7. **`platform/api/clue_api/arv2/` imports nothing quarantined.** Allowed internal prefixes:
   `clue_api.arv2`, `clue_core`, `clue_config`, `clue_obs`, `clue_storage`, `clue_db`,
   `clue_gateway`, `clue_locks`, `clue_spine`, `clue_toolbelt`, `clue_fleet`, `clue_agents`,
   `clue_execution`, `clue_auth`, `clue_projections`, `clue_research.claimstore`. Everything else
   under `clue_research`, all of `clue_memory`, and any `clue_api.*` outside `arv2` is forbidden.
   Provider SDKs (`openai`, `google.*`, `exa_py`, `firecrawl`, `sumble`) are forbidden; HTTP goes
   through the wrapper. The Task 1 guard test enforces this.
8. **Code style:** `from __future__ import annotations`; ruff line length 100; mypy `strict`
   (`clue_api` is in the mypy file set, so new modules must type-check); frozen pydantic models
   or frozen dataclasses for value types; docstrings state the law a function implements.
   `httpx` is the HTTP library, declared in `platform/api/pyproject.toml`.
9. **Commits:** on the task's branch only; message says what and why; **no Co-Authored-By and
   no AI attribution**; never push.
10. **Reports:** the implementer writes its full report to the report path in its dispatch and
    returns only the short status contract.
11. **Subjects for live tests** (the answer keys): Zafran Security — domain `zafran.io`, Ashby
    slug `zafran-security`, people Nick Fisher (`https://www.linkedin.com/in/nicholastfisher`),
    Sanaz Yashar (`https://www.linkedin.com/in/sanaz-yashar`), Vari Kaur / Varinder Kaur
    (`https://www.linkedin.com/in/varinderkaur`); podcast Boardroom Club RSS
    `https://anchor.fm/s/f695d6d8/podcast/rss`, Sanaz's episode (42:49, 2569 s, MP3 enclosure on
    `anchor.fm/s/f695d6d8/podcast/play/106390290/…`); YouTube (Nick Fisher, Cocktail Chemistry)
    `https://www.youtube.com/watch?v=avcD5WVLCYs` (04:14) and
    `https://www.youtube.com/watch?v=8_YWBtq4eic` (01:31). Probook — domain `probook.ai`, Ashby
    slug `probook`, people Mark Hoffman (`https://www.linkedin.com/in/mark-hoffman-582a5741`),
    Kate Blumberg (`https://www.linkedin.com/in/kibrady12`), George Eliadis
    (`https://www.linkedin.com/in/george-eliadis`), Aaron Churba.
12. **PoC reference scripts** (read for prompts and wire shapes; port the rules, never copy the
    scripts): `.context/arv2-one-account-aiark/z_lib.py`, `z1a_ark_company.py`,
    `z1b_ark_people.py`, `z1c_ark_emails.py`, `z1d_reparse_emails.py`, `z2b_ashby.py`,
    `z3_media_resolve.py`, `z4a_gemini_youtube.py`, `z4b_gemini_podcast.py`,
    `z4d_retranscribe.py`, `z4e_quote_verify.py`, `z5_exa_deep.py`, `z6_embed_retrieval.py`,
    `z7_structure.py`; `.context/arv2-person-depth/p1_sweep.py`, `p2a_resolve.py`,
    `p2b_captions.py`, `p2c_exa_media.py`, `p3_deep.py`, `p4_structure.py`;
    `.context/arv2-clue-sample-v3/step4b_ashby.py`, `step6_account_deep.py`;
    `.context/arv2-smoke-cluehq/field_catalog.py`; `.context/ai-ark-canary/canary.py`.

---

## Task 1 — Step 0: the shared foundation (on `track-R`)

### 1.1 Settings, Secrets, `.env.example`

- `libs/clue-config/clue_config/secrets.py` — add, in the provider-keys block:
  `ai_ark_api_key: SecretStr | None = None` and `gemini_api_key: SecretStr | None = None`, each
  with a one-line comment naming its env var (`CLUE_AI_ARK_API_KEY`, `CLUE_GEMINI_API_KEY`) and
  what reads it (the ARV2 AI Ark client; the ARV2 media client's native transcribe call only).
- `libs/clue-config/clue_config/settings.py` — add an `# --- ARV2 research lane (R1) ---` block
  next to `entity_research_runtime_enabled` with exactly these fields and defaults:
  - `arv2_account_research_enabled: bool = False` — comment: selects the ARV2 fleet handler and
    launcher at composition (A7); **False until the R2 exit gate passes, then the default flips
    to True** (founder instruction 2026-09-07).
  - `arv2_ai_ark_min_gap_s: float = 10.5` — minimum seconds between AI Ark calls (PoC pacing
    until the paid tier's rate is confirmed).
  - `arv2_structuring_model: str = "openai/gpt-5-mini"`
  - `arv2_media_short_model: str = "google/gemini-3.5-flash-lite"` (OpenRouter id)
  - `arv2_media_transcribe_model: str = "gemini-3.5-transcribe"` (native Gemini id — the one
    call that bypasses OpenRouter; comment says so and why: OpenRouter serves neither this model
    nor a file upload)
  - `arv2_embedding_model: str = "google/gemini-embedding-2"` (OpenRouter embeddings id)
  - `arv2_media_seconds_ceiling: int = 9000` (enforced; money truth)
  - `arv2_media_short_max_seconds: int = 600`
  - `arv2_raw_root: str = ".artifacts/arv2"` (where the file raw sink and JSONL ledger write in
    development and tests; production routes raw bodies to the `artifact` table at A7)
- `.env.example` — add `CLUE_AI_ARK_API_KEY=` and `CLUE_GEMINI_API_KEY=` to the provider-keys
  block (after `CLUE_EXA_API_KEY`'s Exa lines) with comments; add a new block
  `# --- ARV2 research lane (R1; master plan §9 Track R) ---` after the R0 posture block carrying
  every `CLUE_ARV2_*` line above with its default and one comment line each. The lane flag's
  comment repeats the flip-to-true-after-R2 rule.
- `platform/api/pyproject.toml` — add `"httpx>=0.28"` to `dependencies`; run `uv lock` (the
  package is already resolved transitively, so the lock delta is small) and `uv sync`.

### 1.2 The package `platform/api/clue_api/arv2/`

Create these modules (and nothing else):

- `__init__.py` — re-exports the public names below; module docstring states the lane's two rules
  (imports nothing quarantined; every provider call goes through `ProviderCaller`).
- `README.md` — the module map: the five Step 0 modules and the six client modules that Tasks 2–7
  add (`ai_ark_client.py`, `exa_client.py`, `ats_client.py`, `media_feeds_client.py`,
  `gemini_media_client.py`, `structuring_client.py`), one line each, plus where raw records and
  the ledger go, and the sentence "the `provider_call_ledger` table and the `artifact`-backed raw
  sink land with D1/A7; R1 ships the sinks' protocols and the file/memory implementations".
- `errors.py` — `Arv2Error(Exception)`; `ProviderHalted(Arv2Error)` with attributes `provider`,
  `reason_code`, `http_status: int | None`, `ledger_row_id: str | None`, `latched: bool`;
  `ProviderTransportError(Arv2Error)` with `provider`, `attempts`, `last_error: str`;
  `RawParseError(Arv2Error)` with `raw_ref`.
- `transport.py`:
  - `BROWSER_USER_AGENT` = the PoC Chrome 126 macOS string (from `z_lib.py`).
  - `HttpRequest` (frozen): `method: str`, `url: str`, `headers: Mapping[str, str]`,
    `body: bytes | None`, `timeout_s: float`.
  - `HttpResponse` (frozen): `status: int`, `headers: Mapping[str, str]` (lower-cased keys),
    `body: bytes`.
  - `TransportFailure(Exception)` — the network-level failure a transport raises.
  - `Transport(Protocol)`: `def send(self, request: HttpRequest) -> HttpResponse`.
  - `HttpxTransport(Transport)`: lazy-imports `httpx` inside `send`; `follow_redirects=True`;
    wraps `httpx.TransportError`/`httpx.TimeoutException` into `TransportFailure`; returns
    non-2xx as a normal `HttpResponse` (never raises on status).
  - `ScriptedTransport(Transport)`: a queue of `HttpResponse | TransportFailure` items consumed in
    order; records every `HttpRequest` it received. Test double for the wrapper only.
  - `json_request(method, url, *, headers, json_body, timeout_s) -> HttpRequest` serialising with
    `json.dumps(obj, separators=(",", ":"), sort_keys=True).encode()` and adding
    `Content-Type: application/json`.
- `sinks.py`:
  - `redact_headers(headers) -> dict[str, str]` masking (case-insensitive) `authorization`,
    `x-token`, `x-api-key`, `x-goog-api-key` to `"***"`; `redact_url(url) -> str` masking the
    value of a `key` query parameter.
  - `RawRecord` (frozen): `call_id: str`, `provider`, `operation`, `label`, `attempt: int`,
    `recorded_at: datetime`, `latency_ms: int`, `request: RawRequest` (`method`, `url` redacted,
    `headers` redacted, `body_text: str | None`, `body_sha256: str | None`),
    `response: RawResponse` (`status`, `headers`, `body_text: str | None` when the body decodes as
    UTF-8 and `binary=False`, else `body_sha256` + `body_bytes: int` + `body_path: str | None`).
  - `RawSink(Protocol)`: `def save(self, record: RawRecord, body: bytes) -> str` returning a
    `raw_ref`.
  - `FileRawSink(root: Path)`: writes `<root>/<provider>/<recorded_at compact>_<label>_a<attempt>.json`
    (the record as JSON; `body_text` inline) and, for binary bodies, a sidecar `.bin` next to it
    with `body_path` set; returns the JSON path as `raw_ref`. `MemoryRawSink`: keeps
    `(record, body)` tuples; `raw_ref` = `"memory:<n>"`.
  - `LedgerRow` (frozen): `row_id: str`, `call_id: str`, `phase: Literal["estimate", "result"]`,
    `provider`, `operation`, `label`, `recorded_at`, `http_status: int | None`,
    `latency_ms: int | None`, `attempts: int`, `estimate_usd: Decimal`, `estimate_credits: Decimal`,
    `estimate_media_seconds: int`, `cost_usd: Decimal | None`, `credits: Decimal | None`,
    `media_seconds: int | None`, `over_ceiling: bool`,
    `outcome: Literal["estimate", "ok", "client_error", "retry_exhausted", "halted", "transport_error"]`,
    `error_code: str | None`, `provider_request_id: str | None`, `raw_ref: str | None`,
    `extras: Mapping[str, object]` (JSON-safe).
  - `LedgerSink(Protocol)`: `def record(self, row: LedgerRow) -> str` returning `row_id`.
  - `JsonlLedger(path: Path)`: appends one JSON object per row (Decimals as strings) under an
    exclusive file lock; `MemoryLedger`: list plus `totals() -> SpendTotals(usd, credits,
    media_seconds)` over `phase == "result"` rows.
- `text.py` — shared verbatim-matching primitives used by Tasks 6 and 7, ported from
  `z4e_quote_verify.py`: `normalize_for_match(s) -> str` (NFKC, curly quotes and double quotes
  straightened, `\s+` → one space, non-`[a-z0-9 ]` → space, lower-case, stripped) and
  `substring_verdict(needle, haystack, *, window=40, stride=10) -> Literal["EXACT", "PARTIAL",
  "NOT_FOUND"]` (EXACT when the normalised needle is a substring; PARTIAL when any `window`-char
  slice at `stride` steps is; else NOT_FOUND).
- `openrouter.py` — the thin OpenRouter HTTP helpers both LLM clients share (no SDK):
  `openrouter_chat_request(*, base_url, api_key: SecretStr, model, messages, response_format=None,
  reasoning=None, max_tokens=None, temperature=None, extra: Mapping[str, object] | None = None,
  timeout_s) -> HttpRequest` posting to `{base_url}/chat/completions` with
  `"usage": {"include": true}`, headers `Authorization: Bearer …`, `HTTP-Referer:
  https://cluehq.ai/arv2`, `X-Title: Clue ARV2`; `openrouter_embeddings_request(*, base_url,
  api_key, model, inputs, dimensions=None, timeout_s)` posting to `{base_url}/embeddings`;
  `openrouter_cost_reader(response) -> CostReading` reading
  `usage.cost_details.upstream_inference_cost`, else `usage.cost`, and `id` as the request id;
  `openrouter_message_text(body) -> str` (first choice's `message.content`). Base URL and key
  come from `clue_config.GatewayConfig().base_url` and `Secrets.openrouter_api_key` at the call
  site; this module takes them as parameters.
- `calls.py` — the wrapper:
  - `SpendEstimate` (frozen): `usd: Decimal = 0`, `credits: Decimal = 0`, `media_seconds: int = 0`.
  - `Ceilings` (frozen): `usd: Decimal | None`, `credits: Decimal | None`,
    `media_seconds: int | None` — **record-only**.
  - `CostReading` (frozen): `cost_usd: Decimal | None`, `credits: Decimal | None`,
    `provider_request_id: str | None`, `media_seconds: int | None = None`.
  - Type aliases: `HaltRule = Callable[[HttpResponse], str | None]` (a reason code or None);
    `CostReader = Callable[[HttpResponse], CostReading]`; `RawScrubber = Callable[[object], object]`
    (applied to the parsed JSON body before the raw record is written — law 3's hook; when the
    body is not JSON the scrubber is skipped and the body saved as-is).
  - `CallSpec` (frozen): `provider`, `operation`, `label`, `request: HttpRequest`,
    `estimate: SpendEstimate`, `max_attempts: int = 4`, `retry_statuses: frozenset[int] =
    {429, 500, 502, 503, 504}`, `halt_rule: HaltRule | None = None`,
    `cost_reader: CostReader | None = None`, `raw_scrubber: RawScrubber | None = None`,
    `binary: bool = False`, `extras: Mapping[str, object] = {}`.
  - `CallResult` (frozen): `response: HttpResponse`, `latency_ms`, `attempts`, `raw_ref`,
    `raw_refs: tuple[str, ...]` (every attempt), `ledger_row_id`, `cost: CostReading`,
    `over_ceiling: bool`; methods `text()` and `json()` — `json()` raises `RawParseError(raw_ref)`
    on failure.
  - `ProviderCaller(*, transport: Transport, raw_sink: RawSink, ledger: LedgerSink,
    ceilings: Ceilings | None = None, sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic, now: Callable[[], datetime])` with
    `call(spec) -> CallResult`, `halted(provider) -> str | None`, `reset_halt(provider)`, and
    `totals() -> SpendTotals`. Exact order inside `call`:
    1. If the provider is latched, raise `ProviderHalted(latched=True, reason_code=f"latched:{orig}")`
       without touching the wire and without a ledger row.
    2. Compute `over_ceiling` from running totals + `spec.estimate` against `ceilings`; write the
       **estimate** ledger row (`phase="estimate"`, `outcome="estimate"`) **before the wire**.
    3. Attempt loop, `n` from 0: `transport.send`; on `TransportFailure` — if not the last attempt,
       `sleep(2 * (n + 1))` and continue; else write a result row `outcome="transport_error"` and
       raise `ProviderTransportError`. On a response: **save the raw record first** (scrubbed JSON
       if `raw_scrubber` and the body parses; headers and URL redacted; `binary` handled per
       sinks), then if `status in retry_statuses` and not the last attempt, wait
       `Retry-After` (integer seconds or HTTP-date → seconds from `now()`), else `12 * (n + 1)`,
       and continue.
    4. After the loop: `cost = spec.cost_reader(response)` if given (exceptions → `CostReading()`
       and `error_code="cost_unreadable"`), then `spec.halt_rule(response)`; a reason latches the
       provider, writes the result row `outcome="halted"`, and raises `ProviderHalted`.
    5. Outcome: `"ok"` for 2xx; `"client_error"` for 4xx; `"retry_exhausted"` when the final
       status is still in `retry_statuses`. Update totals from `cost` (falling back to the
       estimate when the reader gave no number — a fallback the row marks with
       `extras["cost_source"]="estimate"`), write the result row, return.
  - A `Retry-After` header that fails to parse is treated as absent.

### 1.3 Tests — `tests/arv2/`

- `__init__.py`; `conftest.py` with `live_secrets` (session fixture: `Secrets()` read from
  `.env`), `require_secret(secrets, "exa_api_key")` helper that `pytest.skip`s naming the env var,
  `arv2_raw_root` (session fixture: `Path(".artifacts/arv2")`, created), and factories
  `make_caller(transport=None)` returning a `ProviderCaller` over `HttpxTransport`,
  `FileRawSink(root/"raw")`, `JsonlLedger(root/"ledger.jsonl")`.
- `test_import_guard.py`: walks every `.py` under `platform/api/clue_api/arv2` with `ast`,
  resolves relative imports, and fails naming each offender against constraint 7; plus a
  self-test that feeds the checker an in-memory module source importing
  `clue_api.sumble_claim_materialization` and `clue_research.sources.waterfall` and asserts both
  are reported.
- `test_calls.py` (scripted transport, fake sleep/clock; Global Constraint 3's one double):
  (a) success path — estimate row precedes the result row, raw saved **before** the cost reader
  runs (assert via a reader that inspects the sink), ledger fields populated, `over_ceiling`
  false; (b) 429 with `Retry-After: 7` sleeps 7; 429 without it sleeps 12, 24, 36 then returns
  `outcome="retry_exhausted"` with four raw records; (c) transport failures sleep 2, 4, 6 then
  raise `ProviderTransportError` with a `transport_error` row; (d) a halt rule raises
  `ProviderHalted`, the next call for that provider raises `latched:` without a request, and
  `reset_halt` clears it; (e) headers and the `key` query parameter are redacted in the raw
  record; (f) a ceiling smaller than the estimate sets `over_ceiling=True` on both rows and the
  call still proceeds; (g) `raw_scrubber` output is what the sink stores and `birth_date` is absent
  from it; (h) `json()` on a non-JSON body raises `RawParseError` carrying the raw ref; (i) a
  binary spec stores the sha and byte count, not the body text.
- `test_text.py`: `substring_verdict` EXACT / PARTIAL / NOT_FOUND on the z4e semantics including
  curly quotes and NFKC.
- `test_settings.py`: `Settings(_env_file=None)` defaults for every field in 1.1;
  `Secrets(_env_file=None).ai_ark_api_key is None`; `Secrets.for_auth_ref("CLUE_AI_ARK_API_KEY")`
  resolves; every new env name appears in `.env.example`.
- `test_live_foundation.py` (live, per constraint 3): (1) `HttpxTransport` GET
  `https://api.ashbyhq.com/posting-api/job-board/zafran-security?includeCompensation=true` → 200,
  JSON with `jobs`; raw record and both ledger rows exist on disk with cost 0. (2) One OpenRouter
  chat completion through `openrouter_chat_request` (model `openai/gpt-5-mini`, reasoning
  `{"effort": "minimal"}`, `max_tokens` 16, user message "Reply with the single word OK") → 200,
  `openrouter_cost_reader` yields a positive `cost_usd` and a request id, the ledger row carries
  them. Skips when `CLUE_OPENROUTER_API_KEY` is unset.

### 1.4 Documents

- `docs/specs/ARV2-MASTER-PLAN.md` §4: add a bullet after the `display_section_recipe` bullet:
  "**`provider_call_ledger`** (D1 addition, 2026-09-07): one row per provider call **phase**
  (`estimate` before the wire, `result` after): `(ledger_id uuid PK, call_id uuid NOT NULL,
  workspace_id text NULL, project_id text NULL, project_run_id text NULL,
  entity_research_job_id uuid NULL, provider text NOT NULL, operation text NOT NULL, label text
  NOT NULL, phase text NOT NULL CHECK (phase IN ('estimate','result')), http_status int NULL,
  latency_ms int NULL, attempts int NOT NULL DEFAULT 0, estimate_usd numeric(12,6) NOT NULL
  DEFAULT 0, estimate_credits numeric(12,3) NOT NULL DEFAULT 0, estimate_media_seconds int NOT
  NULL DEFAULT 0, cost_usd numeric(12,6) NULL, credits numeric(12,3) NULL, media_seconds int NULL,
  over_ceiling boolean NOT NULL DEFAULT false, outcome text NOT NULL CHECK (outcome IN
  ('estimate','ok','client_error','retry_exhausted','halted','transport_error')), error_code text
  NULL, provider_request_id text NULL, request_artifact_key text NULL, response_artifact_key text
  NULL, recorded_at timestamptz NOT NULL DEFAULT now())`, indexes on `(workspace_id,
  recorded_at)` and `(call_id)`. Raw request and response bodies are `artifact` rows written
  through `record_artifact` with `source_key = 'arv2:<provider>:<operation>'`; the ledger row
  references their keys. R1 ships the wrapper and the file/memory sinks; the table and the
  artifact-backed sink land with D1/A7."
- `docs/specs/ARV2-DATA-SOURCE-MAP.md` §2.2: add the matching table row (`provider_call_ledger`,
  the same column list, "why: Appendix A laws 1–2 — every paid call's estimate, cost, credits,
  media seconds and raw refs; the cost dashboards read it").

### 1.5 Exit gate

`uv run pytest tests/arv2 -q` green (live tests run — keys are present); `uv run ruff format
--check platform/api/clue_api/arv2 tests/arv2 libs/clue-config` and `uv run ruff check` on the same
paths clean; `uv run mypy` reports no new errors (the baseline has exactly one pre-existing
error, recorded in `_memory/2026-09-01-r0-step2-merge-complete.md`); `uv run lint-imports`
passes; `git status` clean after the commits; nothing under `.artifacts/` staged.

---

## Task 2 — AI Ark client (`task/R1-ai-ark`)

Files: `platform/api/clue_api/arv2/ai_ark_client.py`, `tests/arv2/test_ai_ark_client.py`
(unit: shape rules), `tests/arv2/test_ai_ark_client_live.py`.

- `AiArkClient(caller: ProviderCaller, api_key: SecretStr, *, min_gap_s: float,
  base_url="https://api.ai-ark.com/api/developer-portal", sleep=time.sleep,
  monotonic=time.monotonic)`. Every request carries `X-TOKEN`, `Content-Type: application/json`,
  `Accept: application/json`, `User-Agent: BROWSER_USER_AGENT` (Cloudflare 403s default clients).
  Pacing: at least `min_gap_s` between any two calls (sleep the remainder).
- Halt rule (money truth): `status in (402, 403)` or (`status >= 400` and `"credit"` in the body,
  case-insensitive) → reason `ai_ark_credit_exhausted_or_denied`; the wrapper latches.
- Raw scrubber (law 3): recursively drop keys `birth_date`, `birthDate`, `birthday` from every
  parsed body before the raw record and before any returned object.
- `company_by_domain(domain) -> AiArkCompany | None`: `POST /v1/companies` body
  `{"account": {"domain": {"any": {"include": [domain]}}}, "page": 0, "size": 1}`; estimate 0.1
  credit; credits by result count (0.1 × `len(content)`); returns the first record's fields
  (`name`, `domain`, `linkedin`, `industry`, `employee_count`, `revenue`, `technologies`, location,
  `raw: dict` of the record) or `None` when `content` is empty.
- `people_by_name(name_variants: Sequence[str], domain: str, *, size: int = 3) -> list[AiArkPerson]`:
  `POST /v1/people` body `{"contact": {"fullName": {"any": {"include": {"mode": "STRICT",
  "content": [...variants]}}}}, "account": {"domain": {"any": {"include": [domain]}}}, "page": 0,
  "size": size}`; `size > 3` raises `ValueError`; an empty `name_variants` raises `ValueError`
  (**there is no domain-roster method, by construction**); estimate 0.5 × size credits; credits
  0.5 × `len(content)`. `AiArkPerson`: `full_name`, `title`, `headline`, `linkedin_url`,
  `location`, `current_company`, `current_company_domain`, `department`, `ark_id`, `raw`.
- `export_email(linkedin_url) -> AiArkEmailExport`: `POST /v1/people/export/single`
  `{"url": linkedin_url}`; estimate 1.0 credit; credits 0.5 + 0.5 when `email.output[0].found`;
  parse `email.output[0]`: `address`, `status`, `domainType`, `subStatus`, `mx{record, provider,
  found, google}`, `free`, `generic`, `found`, `date`; verdict `verified_smtp` when
  `status == VALID and domainType == SMTP`, `catch_all_valid` when `status == VALID` otherwise,
  else `not_found`; keep the whole email block as `raw_email_block`; also `profile.full_name`,
  `profile.title`, `position_groups[0].company.name`, `certifications` when present.
- Unit tests: size cap, empty-variants refusal, verdict mapping on three hand-written email
  blocks, scrubber removes nested `birth_date`.
- Live tests (≈5 credits per run): Zafran `company_by_domain("zafran.io")` name contains
  "Zafran"; `people_by_name(["Nick Fisher", "Nicholas Fisher"], "zafran.io")` → a person whose
  `linkedin_url` ends with `/in/nicholastfisher` and `current_company` contains "Zafran";
  `export_email("https://www.linkedin.com/in/nicholastfisher")` → verdict in the three values and
  no `birth_date` key anywhere in the raw record on disk (scan the saved JSON); Probook
  `company_by_domain("probook.ai")`, `people_by_name(["Mark Hoffman"], "probook.ai")` →
  `mark-hoffman-582a5741`, `export_email("https://www.linkedin.com/in/kibrady12")`. Ledger rows
  show credits by the arithmetic above; pacing observed (≥ 10.5 s between calls, measured).
- Exit gate: unit + live green; ruff/mypy/lint-imports clean; one commit on the task branch.

## Task 3 — Exa client (`task/R1-exa`)

Files: `platform/api/clue_api/arv2/exa_client.py`, `tests/arv2/test_exa_client.py` (unit: request
shaping, guard arithmetic), `tests/arv2/test_exa_client_live.py`.

- `ExaClient(caller, api_key: SecretStr, *, base_url="https://api.exa.ai")`; header `x-api-key`.
  Cost from `costDollars.total` (reader also keeps the breakdown in `extras`); request id from
  `requestId`.
- `search(query, *, type="auto", num_results=8, include_domains=None, include_text=None,
  start_published_date=None, end_published_date=None, category=None, text_max_chars=1500,
  highlights=None, timeout_s=180) -> ExaSearchResult` — an option is put on the wire **only when
  the caller passed it**; no module-level default for `includeDomains`. Estimate $0.01.
  `ExaSearchResult.results[]`: `url`, `title`, `published_date`, `author`, `text`, `highlights`.
- `contents(urls, *, text_max_chars=8000, livecrawl: Literal["always", "fallback", "never"] |
  None = None, highlights=None, timeout_s=240) -> ExaContentsResult` — indexed copy by default,
  `livecrawl` only when requested; `statuses` per URL surfaced. Estimate $0.002 × len(urls).
- `deep_reasoning(*, system_prompt, query, output_schema: Mapping[str, object], num_results=20,
  additional_queries: Sequence[str] | None = None, text_max_chars=10000, highlights_query=None,
  highlights_max_chars=2000, timeout_s=1200) -> ExaDeepResult` — body `type="deep-reasoning"`,
  `stream=False`, `contents.text.maxCharacters`, optional `contents.highlights`, `outputSchema` as
  passed (no default schema; two helpers ship the known shapes: `report_output_schema()` = one
  required string property `report`, and `product_catalog_output_schema()` = the exact §3 JSON of
  `ARV2-PRODUCT-CATALOG-CONTRACT.md`). Result: `output_text`, `output_object` (parsed when the
  output is JSON), `report_text` (the `report` string when present), `grounding`
  (`output.grounding` as returned), `results`, `cost_usd`, `n_results`. Estimate $0.05.
  **Silent-fail guard (law 4):** after the call, `thin = n_results <= 9 and cost_usd <= 0.016`;
  for the `report` schema also `len(report_text) < 3000`; when thin, retry once and keep the
  richer response; `ExaDeepResult.retried: bool`.
- Unit tests: options absent from the body unless passed; guard arithmetic on synthetic
  `(n, cost, chars)` triples; both helper schemas are valid JSON objects with the documented
  property counts (1 and 9).
- Live tests (≈$0.25 per run): `search('"Zafran Security" ABM manager job', include_domains=
  ["jobs.ashbyhq.com", "boards.greenhouse.io", "jobs.lever.co"])` → 200 and every result URL is
  on one of those domains; `search('"Zafran Security" funding', start_published_date=
  "2025-01-01")` → results carry `published_date`; `contents(["https://zafran.io",
  "https://www.youtube.com/watch?v=avcD5WVLCYs"])` → text for both; `deep_reasoning` Zafran
  dossier with the `z5_exa_deep.py` system prompt and charter (ported verbatim into the test) →
  `report_text` ≥ 3000 chars and contains "NOT FOUND"; `deep_reasoning` product catalog for
  `zafran.io` with `product_catalog_output_schema()` (system prompt per contract §3 request
  discipline, `include_domains` restricted pass) → `output_object["products"]` non-empty, each
  with `name` and `offering_kind`; Probook `deep_reasoning` dossier with
  `step6_account_deep.py`'s prompt. Every result's `cost_usd` > 0 and ledger rows carry it.
- Exit gate as Task 2.

## Task 4 — ATS boards client (`task/R1-ats`)

Files: `platform/api/clue_api/arv2/ats_client.py`, `tests/arv2/test_ats_client.py` (unit:
detection on saved HTML strings written in the test, normalisation), `tests/arv2/test_ats_client_live.py`.

- `AtsKind = Literal["ashby", "greenhouse", "lever"]`; `AtsBoard(kind, slug, source_url)`.
- `detect_boards(html: str, page_url: str) -> list[AtsBoard]` — from links and embeds:
  `jobs.ashbyhq.com/<slug>`, `api.ashbyhq.com/posting-api/job-board/<slug>`,
  `boards.greenhouse.io/<slug>`, `job-boards.greenhouse.io/<slug>`,
  `boards-api.greenhouse.io/v1/boards/<slug>`, `greenhouse.io/embed/job_board?for=<slug>`,
  `jobs.lever.co/<slug>`, `api.lever.co/v0/postings/<slug>`. Slugs are **read, never guessed**.
- `find_board(company_url, caller) -> AtsBoard | None` — fetches the homepage and up to six
  candidate career pages (`/careers`, `/careers/`, `/jobs`, `/company/careers`, `/about/careers`,
  plus any homepage link whose text or path contains "career" or "jobs"), each through the wrapper
  as provider `live_http` with `BROWSER_USER_AGENT`, cost 0; returns the first detected board;
  returns `None` when none is found (never a guessed slug).
- `fetch_postings(board, caller) -> BoardPostings` — endpoints exactly:
  Ashby `https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true`;
  Greenhouse `https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true`;
  Lever `https://api.lever.co/v0/postings/{slug}?mode=json`. A 404 → `BoardNotFound` (typed,
  carries the URL), not a crash. Postings normalised to `JobPosting(title, department, team,
  location, published_at: date | None, days_open: int | None (from `published_at` to today),
  is_listed: bool | None, compensation: str | None, description_plain: str | None, url,
  apply_url, provider_fields: Mapping[str, object])` reading Ashby `descriptionPlain`,
  `publishedAt`, `isListed`, `compensation.compensationTierSummary`; Greenhouse `content` (HTML →
  text with tags stripped), `updated_at`/`first_published`, `pay_input_ranges` when present; Lever
  `descriptionPlain`, `createdAt` (ms epoch), `salaryRange`, `categories`.
- Live tests (free): `find_board("https://zafran.io")` → `ashby/zafran-security`;
  `fetch_postings` → ≥ 1 posting with `published_at` and `is_listed` set;
  `find_board("https://probook.ai")` → `ashby/probook`; `fetch_postings(AtsBoard("greenhouse",
  "translucent", …))` and `fetch_postings(AtsBoard("lever", "smarsh", …))` return normalised
  postings with `description_plain`; `fetch_postings(AtsBoard("ashby", "zafran", …))` raises
  `BoardNotFound` (the smoke-test lesson). Ledger rows cost 0, raw records present.
- Exit gate as Task 2.

## Task 5 — Podcast RSS and the YouTube probe (`task/R1-media-feeds`)

Files: `platform/api/clue_api/arv2/media_feeds_client.py`, `tests/arv2/test_media_feeds_client.py`
(unit: feed parsing on an inline XML string, episode-number matching, host rejection),
`tests/arv2/test_media_feeds_client_live.py`.

- `fetch_feed(url, caller) -> Podcast` (provider `rss`, cost 0, `Accept:
  application/rss+xml,application/xml;q=0.9,*/*;q=0.8`, `BROWSER_USER_AGENT`);
  `parse_feed(xml) -> Podcast(title, feed_url, episodes[Episode(number: int | None, title,
  enclosure_url, enclosure_bytes, duration_s, published_at, link, description)])` using
  `xml.etree` with the itunes namespace (`itunes:episode`, `itunes:duration` in `H:MM:SS`,
  `MM:SS` or seconds; number also from a leading `Ep 297` / `#297` / `Episode 297` in the title
  when the tag is absent).
- `find_episode(podcast, *, number: int | None = None, title_contains: str | None = None) ->
  Episode | None` — exact number match first; `title_contains` is a case-insensitive substring
  test; no fuzzy matching.
- `download_enclosure(episode, dest: Path, caller, *, max_bytes: int) -> AudioFile(path, bytes,
  sha256, duration_s, content_type)` — fetched through the wrapper as a `binary=True` call (the
  `Transport` seam materialises bodies; a streaming path is future work — amended 2026-09-07; a
  `Content-Length` HEAD precheck refuses an oversized enclosure before the GET when the feed
  declares no length)
  (provider `live_http`, cost 0), refuses with `EnclosureTooLarge` above `max_bytes`.
- YouTube: `is_youtube(url)`; `reject_native_video(url)` raises `UnsupportedMediaHost` for
  `linkedin.com`, `x.com`, `twitter.com` video URLs (law: never fetch LinkedIn- or X-native video);
  `youtube_metadata(watch_url, caller) -> YouTubeMeta(video_id, title, length_s)` from the watch
  page's `ytInitialPlayerResponse` (`videoDetails.title`, `lengthSeconds`), cost 0;
  `youtube_words(watch_url, page_text: PageTextFetcher) -> YouTubeWords(url, title, text)` where
  `PageTextFetcher = Callable[[Sequence[str]], Mapping[str, str]]` (the Exa `contents` client
  satisfies it after Task 3 merges; the caption endpoint is dead and is not called).
- Live tests: Boardroom feed → 65 episodes (≥ 60 asserted); `find_episode(title_contains=
  "Sanaz")` → `duration_s == 2569` and enclosure URL starting with
  `https://anchor.fm/s/f695d6d8/podcast/play/`; `download_enclosure` into `tmp_path` →
  `content_type` audio and `bytes` > 10 MB, sha recorded in the raw record;
  `youtube_metadata("https://www.youtube.com/watch?v=avcD5WVLCYs")` → `length_s` between 250 and
  260; `youtube_words` with a 10-line fetcher written in the test that POSTs to
  `https://api.exa.ai/contents` through the wrapper (key from `.env`) → non-empty text;
  `reject_native_video("https://www.linkedin.com/posts/…video…")` raises.
- Exit gate as Task 2.

## Task 6 — Gemini media client (`task/R1-gemini-media`)

Files: `platform/api/clue_api/arv2/gemini_media_client.py`, `tests/arv2/test_gemini_media_client.py`
(unit: loop detector, speaker verdicts, ceiling), `tests/arv2/test_gemini_media_client_live.py`.

- `GeminiMediaClient(caller, *, openrouter_api_key: SecretStr, openrouter_base_url: str,
  gemini_api_key: SecretStr, short_model, transcribe_model, embedding_model,
  media_budget: MediaBudget, short_max_seconds: int)`.
- `MediaBudget(ceiling_s: int)` with `reserve(seconds)` → raises `MediaCeilingExceeded` (money
  truth; a ledger `halted`-style row via a zero-cost call is **not** written — the refusal is
  recorded by the client on the ledger through `ledger.record` with `outcome="halted"`,
  `error_code="media_ceiling"`) and `used_s`.
- `transcribe_short(audio: AudioFile, *, context: SpeakerContext(person_name, person_role,
  organisation, named_in_metadata: bool)) -> Transcript` — `audio.duration_s >
  short_max_seconds` raises `ValueError`; OpenRouter chat completion to `short_model` with one
  user message carrying `{"type": "input_audio", "input_audio": {"data": <base64>, "format":
  "mp3"}}` plus the z4b prompt text (META / TRANSCRIPT with `[MM:SS]` + speaker label / QUOTES /
  BUYING_AND_VENDOR_SIGNALS), `temperature 0`, `usage.include`; cost via
  `openrouter_cost_reader`; `media_seconds = audio.duration_s` on the ledger row.
  `Transcript(model, text, lines[TranscriptLine(ts_s: int | None, speaker, text)], meta:
  Mapping[str, str], quotes[QuoteCandidate], has_timestamps: bool)`.
- `transcribe_long(audio, *, context) -> Transcript` — native Gemini, header `x-goog-api-key`
  (never the `key` query parameter): resumable upload start `POST
  https://generativelanguage.googleapis.com/upload/v1beta/files` with the `X-Goog-Upload-*`
  headers from `z4b_gemini_podcast.py`, then `upload, finalize` to the returned upload URL, then
  poll `GET /v1beta/files/{name}` until `ACTIVE` (≤ 60 polls, 5 s apart; `FAILED` → typed
  error); then `POST /v1beta/models/{transcribe_model}:generateContent` with `file_data` +
  the z4d prompt; text from `candidates[0].content.parts[].audioTranscription.text`, falling back
  to `parts[].text`; `has_timestamps=False`. Cost from `usageMetadata` by modality with the price
  constants from `z_lib.PRICE` (audio 0.30, text in 0.10, text out 0.40 USD per 1M tokens),
  `media_seconds` recorded. The upload is a free ledger row.
- `detect_loops(transcript) -> LoopReport(total_lines, unique_lines, unique_ratio,
  max_consecutive_repeat, first_loop_ts_s | None, tripped)` — tripped when any line text repeats
  three or more times consecutively, or `unique_ratio < 0.6` with ≥ 40 lines, or any 30-line
  window has fewer than 15 unique lines (the z4b measurement: 329 lines, 120 unique, loop from
  12:41).
- `verify_speaker(transcript, context) -> SpeakerVerdict(verified, evidence)` — verified when
  META `guest_identity_evidence` / `narrator_identity_evidence` is not "NOT STATED" and contains
  the person's surname, or `context.named_in_metadata` is true.
- `mine_quotes(transcript_text, *, context, n=6) -> list[QuoteCandidate]` — OpenRouter
  `short_model` text-only call with the z4e STRICT-JSON prompt; each quote gets
  `verdict = substring_verdict(quote, transcript_text)` (from `arv2.text`) and `usable = verdict
  == "EXACT" and speaker_verified`; nothing is dropped, only flagged.
- `embed_chunks(transcript, *, window_lines=14, dimensions=768) -> list[EmbeddedChunk(text,
  start_ts_s, vector)]` — text only, via `openrouter_embeddings_request` to `embedding_model`
  with `dimensions`; if the endpoint rejects `dimensions` (4xx naming it), retry once without it
  and report the served dimension.
- Unit tests: `detect_loops` trips on a synthetic 329-line transcript that repeats a 120-line
  block, and does not trip on 300 distinct lines; speaker verdicts for the three cases;
  `MediaBudget(100).reserve(101)` raises before any call (scripted transport never receives a
  request).
- Live tests (≈$0.05 per run; `ffmpeg` required for the short cut — `pytest.skip` naming it when
  absent): download the Sanaz MP3 once per session (through the wrapper, into `tmp_path_factory`);
  (1) short: `ffmpeg -t 180` cut → `transcribe_short` → ≥ 10 timestamped lines, first `ts_s` <
  30, `detect_loops` not tripped, META has `speakers`; (2) long: full file → `transcribe_long` →
  ≥ 25 000 chars, `has_timestamps` false, `detect_loops` not tripped, ledger row `media_seconds`
  = 2569 and `cost_usd` > 0, `verify_speaker` with `named_in_metadata=True` verified,
  `mine_quotes` → ≥ 3 `EXACT`; (3) `embed_chunks` → every vector length equals the served
  dimension (768 expected) and the ledger shows cost; (4) `MediaBudget(100)` refuses the long file
  with no request sent.
- Exit gate as Task 2, plus the README notes the native-endpoint exception and the `ffmpeg`
  dependency of the short-cut **test** (production never cuts audio).

## Task 7 — OpenRouter structuring client (`task/R1-structuring`)

Files: `platform/api/clue_api/arv2/structuring_client.py`, `tests/arv2/test_structuring_client.py`
(unit: partition and annotations on a hand-written model reply), `tests/arv2/test_structuring_client_live.py`.

- `FieldSpec(key, description, value_schema: Mapping[str, object] | None)`;
  `FieldCatalog(account: Sequence[FieldSpec], contact: Sequence[FieldSpec], facet:
  Sequence[FieldSpec])` with `keys()`; `catalog_menu_text(catalog)` renders the menu the model
  sees (`key — description` per line, three headed sections, as `z7_structure.py` does).
- `StructuringClient(caller, *, api_key: SecretStr, base_url: str, model: str)`.
- `structure_account(subject: AccountSubject(name, domain, already_known: str | None), bundle:
  str, catalog) -> StructuredOutput` and `structure_person(subject: PersonSubject(name, company,
  linkedin_url), bundle, catalog) -> StructuredOutput` — **one subject per call by signature**;
  no batch method exists. Request: `openrouter_chat_request(model, response_format={"type":
  "json_object"}, reasoning={"effort": "minimal"}, max_tokens=32000, temperature=0)`, system
  prompt = the z7 rules (verbatim `evidence_span`, closed catalog, `outreach_safe` rules,
  `use_class` values, never birth/age/health/religion/politics/family, transcript words self-stated)
  plus the priority rubric (`1` active buying intent, `2` qualifying fact, `3` context; for
  people: `1` specific, personal, recent, verbatim, usable now; `2` solid but generic or older;
  `3` weak or company-level); user prompt = menu + the STRICT JSON shape
  `{"claims": [{"field_key", "value", "evidence_span", "source_url", "source_kind",
  "confidence", "use_class", "outreach_safe", "priority", "media_timestamp"}], "proposed_fields":
  [{"suggested_key", "why", "value", "evidence_span", "source_url"}], "negatives_and_risks":
  [{"what", "status", "evidence_span", "source_url", "outreach_safe"}]}` + the bundle. Estimate
  $0.05; cost via `openrouter_cost_reader`.
- Post-parse, in code: `StructuredOutput(claims[StructuredClaim], proposed[ProposedField],
  negatives[], model, cost_usd, request_id, raw_ref)`. A claim whose `field_key` is not in the
  catalog is **moved to `proposed`** with `origin="model_used_unregistered_key"` — never
  refused. Each kept claim gets annotations: `evidence_verbatim = substring_verdict(evidence_span,
  bundle)` (annotation only), `schema_valid: bool | None` (checked against `value_schema` with
  `jsonschema` when importable in the environment, else a minimal `type`/`required`/`enum` check;
  `None` when the field has no schema), `priority` coerced to 1–3 with default 3, `outreach_safe`
  default true. Deterministic provider facts never enter: the only inputs are prose bundles.
- Unit tests: partition of unregistered keys, verbatim annotation values, priority defaulting,
  a malformed reply raises `RawParseError` with the raw ref.
- Live tests (≈$0.10 per run): catalog loaded from `.context/arv2-smoke-cluehq/field_catalog.py`
  via `importlib` (24 account, 8 contact, 12 facet keys); Zafran `structure_account` on
  `.context/arv2-one-account-aiark/report_account_zafran_deep.md` plus the own-site texts from
  `raw/z2_own_site.json` → ≥ 15 claims, every kept key in the catalog, `proposed` listed,
  EXACT verbatim rate ≥ 0.5 (report the actual); Probook `structure_account` on
  `.context/arv2-clue-sample-v3/account_report.md` → ≥ 10 claims; Nick Fisher `structure_person`
  on `.context/arv2-person-depth/structuring_bundle_nick_fisher.txt` → ≥ 8 claims each with a
  priority in 1–3. Ledger rows carry `cost_usd` from `upstream_inference_cost`.
- Exit gate as Task 2.
