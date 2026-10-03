"""Centralized settings for the Python side of Lumen, loaded from repo-root .env.

Every environment variable read by Python code (apps/api + apps/agent_runtime)
is declared here via pydantic-settings. Import `settings` and use
`settings.image_model_api_key`, etc. instead of load_dotenv/os.getenv.

Notes:
- Real environment variables take precedence over .env / .env.local values,
  matching the previous `set -a; source .env` and load_dotenv(override=False)
  behavior. `.env.local` (if present) overrides `.env`.
- This covers app config only. Test-only pytest gates (LUMEN_AGENT_RUN_LIVE,
  LUMEN_INGESTION_LIVE_E2E, UPDATE_INGESTION_SNAPSHOTS) stay raw os.environ
  reads in the test suites.
- ANTHROPIC_API_KEY is declared for documentation/introspection, but langchain
  reads it from os.environ directly; the dev scripts still export .env.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# D5 Round B (R-D5-B1): this package moved from `<clue-design>/py_lumen_config/` into its own
# distribution directory, `<clue-design>/packages/py-lumen-config/py_lumen_config/`, so it can be
# a real installed uv workspace member instead of a PYTHONPATH shim. The design-tree root is
# therefore three levels up, not one — and it MATTERS: this anchor locates `.env`/`.env.local`
# and the default engine-cache root. Getting it wrong would silently stop loading the dev
# environment rather than fail, which is why it is spelled out here.
# config.py -> [0]=py_lumen_config -> [1]=py-lumen-config -> [2]=packages -> [3]=clue-design root
_REPO_ROOT = Path(__file__).resolve().parents[3]
# .env first, then .env.local (overrides). Real env vars beat both.
_ENV_FILES = [
    _REPO_ROOT / ".env",
    _REPO_ROOT / ".env.local",
]


class Settings(BaseSettings):
    """All environment variables for Lumen's Python apps."""

    model_config = SettingsConfigDict(
        env_file=[str(p) for p in _ENV_FILES if p.exists()],
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Backend API (lumen_api) ---
    lumen_api_cors_origins: str = "http://127.0.0.1:3000,http://localhost:3000"
    # The design API's OWN externally-reachable origin. Every HTTP request path
    # derives asset URLs from `request.base_url` and never needs this; it exists
    # for the ONE consumer that has no request to derive from — the deep agent's
    # in-loop preview render, which runs inside the fleet worker and fetches
    # every `<img data-asset=…>` from `{origin}/asset-store/{digest}` over the
    # network (Playwright `set_content`, so a relative src cannot resolve).
    #
    # This setting exists because that value used to be HARDCODED in the agent
    # runtime at `http://127.0.0.1:8000/asset-store` — a port nothing has
    # listened on since the design API moved to 8010. Every image the agent
    # placed rendered broken in its own screenshots, so the agent (correctly)
    # stripped it and reported "the supplied assets did not render". Cost: a day
    # and three "the model won't use images" misdiagnoses. The default below is
    # the documented canonical dev stack; deployments set LUMEN_API_ORIGIN.
    lumen_api_origin: str = "http://127.0.0.1:8010"
    # D4/R-D4-1: this is the ENGINE MATERIALIZATION CACHE root, not a store. Durable custody of
    # every design byte lives in platform storage (`clue_storage`); the Rust engine only ever
    # reads/writes a transient per-workspace mirror at
    # `{lumen_asset_store_root}/{workspace_id}/sha256/{ab}/{digest}` (the engine's own layout,
    # unchanged, below a workspace dir). Wiping this tree loses nothing — Python writes back
    # after every engine write and materializes read-through before every engine read.
    # None → `<clue-design repo root>/.engine-cache` (git-ignored). The env var keeps its
    # historical name (LUMEN_ASSET_STORE_ROOT) so deployments need no change.
    lumen_asset_store_root: Path | None = None  # None → <repo root>/.engine-cache
    lumen_asset_max_bytes: int = 10 * 1024 * 1024
    # Curated font-library manifest (Track B). Generated + checked in by
    # scripts/provision_font_library.py; missing file → library disabled.
    lumen_font_library_manifest_path: Path = Path("apps/api/font-library/manifest.json")
    lumen_log_level: str = "INFO"  # resolved leniently: unknown names fall back to INFO
    # Prebuilt lumen-api-helper binary; None → `cargo run -p lumen-api-helper`.
    lumen_core_helper: str | None = None
    # D5 Round B (R-D5-B5): run a design fleet worker on the API's OWN event loop.
    # Agent/web turns are leased fleet work now, so SOMETHING has to drain the queue. In
    # production that is the detached `clue_api.fleet_main` worker (behind
    # CLUE_DESIGN_RUNTIME_ENABLED); in development — and under the design API's test suite — no
    # second process exists, and a turn offered with nobody draining would simply sit `queued`
    # forever. Defaults ON so `uvicorn lumen_api.main:app` keeps behaving like one self-contained
    # server. It is the SAME handler either way, so this switch changes who drives, never what
    # runs. Set LUMEN_EMBEDDED_FLEET_WORKER=0 when a detached worker owns the drain.
    lumen_embedded_fleet_worker: bool = True
    # D5 Round C: how often the API's OWN stranded-work reaper sweeps, in seconds. Same argument
    # as the embedded worker — in development nothing else is running, so a run or ingestion job
    # stranded by a hard kill would sit `running` forever with no second process to notice. Runs
    # only when the embedded worker does (the two are one drain story), and `<= 0` disables it.
    # Deliberately slow: it is a safety net over a rare failure, not a control loop, and every
    # pass is a query against three indexed status predicates.
    lumen_design_reaper_interval_s: float = 300.0
    # Clone-fidelity F2.2: the RUNAWAY BACKSTOP on how many website sections one ingestion may
    # mint as fragments. FOUNDER RULING (2026-08-27): extraction yields as many fragments as the
    # page honestly offers — the acceptance's "at least five" is a floor, not a target — so this
    # must never be the thing that truncates a real page. 40 is the capture probe's own
    # MAX_SECTIONS (capture/geometry.py) and the persisted-band ceiling (sections/bands.py), so
    # minting cannot be a SECOND, tighter ceiling on a page the capture layer was willing to
    # measure in full. Tripping it is reported loudly (LUMI0532), never silently truncated.
    lumen_fragment_mint_cap: int = 40
    # New multipage library captures: total per visible/dormant pool; per-page cap still applies.
    lumen_site_library_fragment_mint_cap: int = 240
    # Clone-fidelity F3/F4, FOUNDER RULING R-X4 (2026-08-29): what a repair lineage resolves to
    # when EVERY released member of it — the harvested original and every repair of it — is
    # marked broken. Two values, and the founder's own words for the default:
    #
    #   "keep_flagged"      (DEFAULT) — the newest released repair stays selected, clearly
    #                       flagged as degraded and requiring review. NEVER silently return to a
    #                       known-broken original.
    #   "fallback_original" — a released repair later marked broken falls back to the original
    #                       page (the pre-ruling R-X1 behaviour: the OLDEST approved member).
    #
    # It changes ONLY the entirely-unhealthy arm. A family with one healthy member still
    # resolves to that member in both modes, and an ambiguous family still refuses in both.
    # A typo must fail at startup rather than silently seat the other page, so it is
    # enum-validated below.
    lumen_degraded_repair_selection: str = "keep_flagged"
    # Whether the two automated QA renderers — the page thumbnail and the clone-review walk —
    # present a normal Chrome User-Agent instead of the headless one. Brandfetch's logo CDN
    # refuses any User-Agent containing `HeadlessChrome`, so a hotlinked decorative logo renders
    # EMPTY there and the review cannot judge the page as a visitor sees it. FOUNDER DECISION
    # (2026-09-02, plan D11): default ON; `0` restores the headless User-Agent, which is the
    # switch to reach for if the vendor objects. It reaches those two renderers only — never the
    # editor, never publish, never fragment isolation. See `lumen_api/qa_render_ua.py`.
    lumen_qa_render_ua_override: bool = True

    # Whether the in-house logo ladder (the target-logo scrape that runs as the second rung
    # behind Brandfetch) fetches with a real Chrome TLS/HTTP fingerprint — curl_cffi
    # `impersonate="chrome"`, the engine under scrapling's Fetcher. Cloudflare-walled sites
    # score the TLS/HTTP2 handshake, not the User-Agent string, so plain httpx gets a 403
    # challenge page (openai.com) and the rung reports "blocked" no matter what UA we send.
    # FOUNDER DECISION (2026-09-02): default ON; `0` restores the plain httpx transport.
    # It reaches the LADDER's own client only — the brand-kit ingestion capture keeps httpx.
    # See `lumen_ingestion/capture/impersonate.py`.
    lumen_ladder_impersonate_chrome: bool = True

    # --- Image generation (image_provider) ---
    # Blank base_url/api_key → /assets/generate returns a clean 503.
    image_model_base_url: str = ""
    image_model_api_key: str = ""
    # W1.4: `"default"` is a sentinel, NOT a usable model id — it 404s on
    # OpenRouter exactly like a wrong id does. `image_provider.configured_model_id()`
    # resolves it to `image_provider.DEFAULT_IMAGE_MODEL_ID` (the verified working
    # `openai/gpt-5.4-image-2`). Resolution lives there, not here, because this
    # package must stay provider-agnostic — it has no business naming a vendor model.
    image_model_id: str = "default"
    image_model_provider_id: str = "image-gen-v1"
    # Which OpenRouter TRANSPORT the configured image model speaks:
    #   "chat"   — the OpenAI-compatible chat-completions endpoint with an image
    #              modality (Gemini-class models; the historical default).
    #   "images" — the dedicated Images endpoint, POST {base_url}/images, with a
    #              top-level `prompt`/`aspect_ratio`/`quality`/`input_references`
    #              body and a base64 `data[*].b64_json` response. This is what
    #              `openai/gpt-image-2` takes (founder-supplied OpenRouter API
    #              reference, 2026-08-23) — it does NOT answer the chat call.
    # A typo must fail at startup, not silently post the wrong shape to a paid
    # endpoint forever, so the value is enum-validated below.
    image_model_api_style: str = "chat"
    # Raised 60 → 240 (founder ruling 2026-08-27): the clean-room W5 run proved
    # the old default incompatible with the founder-ordered `openai/gpt-image-2`
    # (measured 67–97s/image at quality=high) — every call timed out and burned
    # all retries, so pre-generation shipped 0/8 while looking like a model
    # outage. A generous ceiling costs fast chat-path models (~14s) nothing.
    image_model_timeout_s: float = 240.0
    image_model_max_retries: int = 2
    # Optional OpenRouter attribution headers (ranking only; harmless if unset).
    image_model_http_referer: str | None = None
    image_model_app_title: str | None = None

    # --- Brand-kit ingestion (lumen_ingestion) ---
    # THE design subsystem's one OpenRouter credential. Every design-side gateway caller
    # resolves it through this single field — the describer, the brief agent, the ingestion
    # assist, the PDF vision pass, the ad-DNA distiller and the turn-time style-group matcher.
    # There is deliberately no second resolution anywhere; a caller that reached for its own
    # env var would be a lane that can be keyless while its neighbours are keyed.
    openrouter_api_key: str = ""
    # The monorepo half of that same resolution. The platform side of this repo namespaces its
    # settings under `CLUE_` (`clue_config.Secrets`, env_prefix="CLUE_"), so the shared secret
    # is spelled `CLUE_OPENROUTER_API_KEY` there while the design subsystem has always spelled
    # it `OPENROUTER_API_KEY`. Repo-root `.env.example` bridges the two by reference
    # (`OPENROUTER_API_KEY="${CLUE_OPENROUTER_API_KEY}"`), but that bridge only exists if the
    # operator's own `.env` actually carries the line AND the process was started by shell-
    # sourcing it — a `.env` written before that line landed leaves the design side keyless.
    #
    # W5/R2-B, 2026-08-26: that is exactly what happened. On a stock checkout the ad-DNA
    # distiller found no key, wrote no card, pre-generation produced nothing, and the job
    # still reported `succeeded` — the lane's whole distinctive half silently inert.
    #
    # So the fallback is declared here, in the ONE place the design subsystem resolves this
    # credential, rather than at any call site: `OPENROUTER_API_KEY` still wins when it carries
    # a value, and `CLUE_OPENROUTER_API_KEY` is consulted only when it does not. Declaring it
    # as a real field (rather than hiding it in a validation alias) keeps this module's promise
    # that every environment variable Python reads is visible here.
    clue_openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    lumen_ingestion_assist: bool = False
    lumen_ingestion_assist_model: str = "x-ai/grok-4.5"
    lumen_ingestion_vision: bool = False
    lumen_ingestion_vision_model: str = "x-ai/grok-4.5"
    # Asset descriptions (design-quality Wave 1, founder ruling R4). ON by
    # default: a brand card whose image menu is bare `img.N` rows gives the
    # agent nothing to choose between, and the last real harvest carried 46
    # images and zero descriptions. The EFFECTIVE gate is still key presence —
    # `OpenRouterDescriber.active` requires this flag AND an OpenRouter key, so
    # a keyless deployment behaves exactly as it did with the flag off.
    #
    # The model is a small, cheap vision model chosen by the live OpenRouter
    # probe of 2026-08-23 (candidates, prices and sample captions are recorded
    # in `.env.example`) — ~$0.00021 per caption vs grok-4.5's ~$0.0039, and
    # the describe stage keeps its OWN model: brief/vision/assist are untouched.
    lumen_ingestion_describe: bool = True
    lumen_ingestion_describe_model: str = "deepseek/deepseek-v4.1-flash"
    lumen_ingestion_describe_concurrency: int = Field(default=40, ge=1, le=128)
    # Output cap per described asset, sent as ``max_tokens`` (one describe call = one asset;
    # a multi-asset call multiplies it, capped at 131072). Without it the model's own ceiling
    # was the only stop: on 2026-09-29 a looping deepseek answer ran to 131072 tokens at $0.157
    # a call, and 35 such runaways were $5.02 of a $6.46 describe bill. A finished analysis of
    # that same site measured a median of ~4.5k output tokens and a p99 of ~15k, so 32768 is
    # twice the p99 — generous for the largest legitimate answer, a quarter of a runaway.
    lumen_ingestion_describe_max_tokens_per_asset: int = Field(default=32768, ge=1024, le=131072)
    lumen_ingestion_pool_workers: int = Field(default=4, ge=1, le=32)
    lumen_ingestion_worker_concurrency: int = Field(default=10, ge=1, le=32)
    lumen_ingestion_pool_idle_seconds: int = Field(default=60, ge=1)
    lumen_ingestion_pool_poll_seconds: float = Field(default=2, gt=0)
    # The ingestion pool CONTROLLER's own database address. Empty (the default) → it uses
    # CLUE_DATABASE_URL like everything else. The worker VM sets it to a direct Postgres URL:
    # the controller's leadership is a session advisory lock, which PgBouncer's transaction
    # pooling would strand on a borrowed server connection. Its children never read it, so they
    # stay on the container's PgBouncer CLUE_DATABASE_URL (first deployment, Task 3 Step 3).
    lumen_ingestion_controller_database_url: str = ""
    # The design-brief agent (tier 2). OFF → ingestion publishes exactly the kit
    # it publishes today, with no `brand_kit_json.brief` and no diagnostic about
    # one. The model must be vision-capable: the stage hands it the capture's
    # screenshots alongside the measured evidence.
    lumen_ingestion_brief: bool = False
    lumen_ingestion_brief_model: str = "x-ai/grok-4.7"
    # The brief's own reasoning effort (founder ruling 2026-09-29: grok-4.7 at medium).
    # Separate from LUMEN_AGENT_REASONING so the design trio and the brief move independently;
    # blank/unset -> no reasoning field on the request.
    lumen_ingestion_brief_reasoning: str | None = "medium"

    # --- Brand Ad Assets v1 (docs/brand-ad-assets-v1-spec.md §5 W2) ---
    # THE lane flag. OFF (the default) → the whole ad-assets substrate is absent: the
    # onboarding route 404s exactly like an unregistered path, no ad-assets ingestion job
    # can be created, and nothing in the lane's tables is ever read or written. ON → the
    # harvest → filter/dedupe → custody → distill → pre-generate job becomes reachable.
    # Named without an `_ENABLED` suffix to match every other switch in this file
    # (`lumen_ingestion_describe`, `lumen_agent_fast_loop`, …).
    lumen_brand_ad_assets: bool = False
    # D3: Adyntel is the v1 ad-library fetch vendor, wired behind the provider seam in
    # `lumen_ingestion.ad_library`. CREDENTIALS COME FROM THE ENVIRONMENT ONLY — they are
    # never defaulted to a real value here, never logged, and never committed. Unset (the
    # default) makes the provider raise the typed `AdLibraryCredentialsMissing` rather than
    # attempting an unauthenticated call.
    adyntel_api_key: str = ""
    adyntel_email: str = ""
    adyntel_base_url: str = "https://api.adyntel.com"
    adyntel_timeout_s: float = 60.0
    # W5/R3-A: People Data Labs is the v1 COMPANY-IDENTITY resolver, wired behind the
    # `lumen_ingestion.ad_library.company_identity` seam. It answers "which LinkedIn page is
    # this domain" from a source that is NOT the ad library, so the harvest can be addressed by
    # a verified page id instead of the vendor's own unverified domain resolution — which for
    # apollo.io returned a real page with zero ads while the brand's true page had 135.
    # CREDENTIALS COME FROM THE ENVIRONMENT ONLY, never defaulted to a real value, never
    # logged. Blank (the default) makes the resolver raise the typed
    # `CompanyIdentityCredentialsMissing`, which the lane DEGRADES from rather than failing on:
    # the harvest falls back to vendor domain resolution and says, at the top level, that
    # nothing verified it.
    #
    # `pdl_base_url` accepts either the API host or the full enrichment endpoint — the
    # resolver's `_normalize_base_url` folds both to one URL, because both forms are already in
    # live use and a doubled path would 404 in a way indistinguishable from "no such company".
    pdl_api_key: str = ""
    pdl_base_url: str = "https://api.peopledatalabs.com"
    pdl_timeout_s: float = 30.0

    # -- Brandfetch (target-account logo vendor; vendor-first logo family, 2026-09-02) ----
    # Brand API key (Bearer). Blank = vendor rung disabled: `fetch_logo` degrades honestly
    # to the in-house ladder, exactly like a blank PDL_API_KEY degrades ad identity.
    brandfetch_api_key: str = ""
    # Logo API *client id* (PUBLIC — appears in published-page <img> URLs). Powers the
    # hotlink lane only; blank = the hotlink prompt guidance is omitted.
    brandfetch_client_id: str = ""
    brandfetch_api_base_url: str = "https://api.brandfetch.io"
    brandfetch_timeout_s: float = 20.0

    # The vision model that distils harvested creatives into the ad-DNA card. Same shape and
    # same gateway as the asset describer above (OpenRouter chat-completions, multimodal).
    lumen_ad_dna_model: str = "x-ai/grok-4.5"

    # --- Agent runtime (lumen_deepagent) ---
    # OpenRouter is the SOLE LLM gateway: the model id must be "openai:<id>" and
    # init_model errors without OpenRouter creds. Blank/unset base_url falls back
    # to the OpenRouter API URL in AgentRuntimeConfig.from_env.
    lumen_agent_model: str = "openai:x-ai/grok-4.6"
    lumen_agent_max_iterations: int = 5
    lumen_agent_preview_format: str = "svg"
    # W-isolation (D3): the deepagent's isolated workspace root. None → the run
    # root falls back to `lumen_agent_trace_dir` (explicit override) or
    # `<repo root>/.deepagent-workspace`. `trace_dir` IS the workspace root; runs
    # land at `<workspace>/run_<id>`.
    lumen_agent_workspace_root: Path | None = None
    lumen_agent_trace_dir: Path | None = None  # None → workspace_root / .deepagent-workspace
    lumen_agent_asset_store: Path | None = None  # None → <trace dir>/asset-store
    lumen_agent_base_url: str | None = None
    lumen_agent_api_key: str | None = None
    # D10(a) — an OPTIONAL output-token bound applied in the single init_model
    # gateway to every deep-agent LLM call (damage-limitation against runaway
    # generation, e.g. the grok-4.5 65k-completion LengthFinishReasonError).
    # Unset → today's behavior, byte-identical (no max_tokens kwarg). A non-int
    # or <=0 value fails LOUDLY at config parse. Recommend 16000 in .env.
    lumen_agent_max_tokens: int | None = None
    # D10(c) — OPTIONAL per-role model overrides. Each defaults to
    # LUMEN_AGENT_MODEL when unset; the same "openai:<id>" contract is enforced
    # by init_model. The harness builds up to three model instances (identical
    # resolved ids share one) — orchestrator to create_deep_agent, author/
    # reviewer into their subagent "model" keys.
    lumen_agent_model_orchestrator: str | None = None
    lumen_agent_model_author: str | None = None
    lumen_agent_model_reviewer: str | None = None
    # OpenRouter unified reasoning effort for every deep-agent LLM call
    # ("low" | "medium" | "high"). Applied in init_model for whatever model id is
    # configured — one mechanism for all models.
    #
    # DEFAULT CHANGED None → "medium" at P3.2 checkpoint 3 (gate finding,
    # 2026-08-14): under the governed gateway, an UNSET effort inherits the
    # platform baseline — which requests effort NONE for gpt-5.x — and a
    # no-reasoning visual reviewer degrades into a myopic identical-call loop
    # (3,338 repeated read_file calls to the recursion limit, reproduced twice;
    # 5 healthy calls with effort=medium). The old direct path sent no reasoning
    # field and got the provider's own default instead; "medium" restores that
    # behavior as EXPLICIT policy. Blank still means "unset" for a deployment
    # that genuinely wants the platform baseline.
    # D1 (founder, 2026-08-26) + W1.8: medium is the shipped default — the live
    # A/B showed medium halves call latency vs high with no quality loss the
    # rubric could see. (v2's earlier "high" default, 2026-08-23, is superseded.)
    lumen_agent_reasoning: str | None = "medium"
    # L1 (latency: cache locality) — OpenRouter provider `sort` preference applied
    # to every deep-agent LLM call. `sort` DISABLES OpenRouter's load-balancing and
    # pins one provider replica, which is the cache-locality lever: a byte-identical
    # 30K prefix scattered across xAI replicas hit cache 2/8 on default routing but
    # 8/8 with sort="latency" (probe-proven 2026-07-12). Default "latency"; blank/
    # unset → NO provider field on the request (byte-identical to pre-L1). Valid
    # OpenRouter values are latency|throughput|price, but this is not enum-validated
    # here — an unknown value is forwarded and OpenRouter rejects it loudly.
    lumen_agent_provider_sort: str | None = "latency"
    # Route NON-OpenAI agent models (x-ai/grok-4.6 is the default) over OpenRouter's
    # chat-completions endpoint instead of its /responses bridge — the platform lane's own
    # ruling (`openrouter_chat_completions_fallback`), now mirrored here. Live 2026-09-04: a
    # 136-second grok generation on /responses died mid-stream with a server-side
    # `Auth context expired` and took a six-minute solo run with it. OpenAI-family ids are
    # unaffected either way (the gateway applies the switch to non-`openai/` ids only).
    # Env: LUMEN_AGENT_OPENROUTER_CHAT_COMPLETIONS. 0 restores the /responses path.
    lumen_agent_openrouter_chat_completions: bool = True
    # P3.2: OPTIONAL fallback model id (bare OpenRouter id) tried when the primary
    # errors — rides GatewayConfig.fallback_model with truthful answering-model
    # attribution. Must be vision-capable (the loop is mandatory-multimodal).
    # None → no fallback (a hard upstream failure fails the turn honestly).
    lumen_agent_fallback_model: str | None = None
    # L3 (latency: straggler watchdog) — per-request timeout in SECONDS applied to
    # every deep-agent LLM call. Installs `timeout` + `max_retries=2` on the
    # ChatOpenAI client, which the OpenAI SDK uses to retry a timed-out request
    # (exponential backoff) then propagate openai.APITimeoutError. Kills the 60–97s
    # real-trace stragglers; do NOT go below 60 (even fully-cached calls spike to
    # ~28s). Default 60.0; blank/unset → NO timeout/retry kwargs (today's behavior).
    # A non-positive value fails loudly at startup.
    lumen_agent_llm_timeout_s: float | None = 60.0
    # Brief-clarification headless/eval mode. When true, the orchestrator NEVER
    # gets the `request_clarification` tool: it applies the clarify-design-brief
    # skill's defaults and records each assumption via record_gap so results stay
    # comparable across a sweep. Probes/sweeps set LUMEN_AGENT_AUTO_DEFAULTS=1;
    # live editor runs leave it off so the agent can ask.
    lumen_agent_auto_defaults: bool = False

    # --- Fast loop v1 (docs/deepagent-fast-loop-v1-spec.md §5) ---
    # THE cutover flag (§7 "flag-gated cutover"). OFF → the scene turn is
    # byte-identical to the pre-fast-loop loop: orchestrator-only render, the
    # `lumen-visual-reviewer` subagent dispatched as always, discovered (not
    # composed) author context, no harness-enforced budgets, no inner-iteration
    # cap. ON → the §5 loop. Web turns (`create-website`) are untouched either
    # way — this flag is scene-turn-only, by §3 non-goal.
    # DEFAULT FLIPPED TO TRUE (founder ruling, 2026-08-26): the fast loop is
    # the production loop — proven live across the reference-ads acceptance
    # runs. Set LUMEN_AGENT_FAST_LOOP=0 to fall back to the legacy loop.
    lumen_agent_fast_loop: bool = True
    # Scene-only knowledge selection; separate workspace roots prevent mixing
    # knowledge during concurrent control/candidate runs. Website is unchanged.
    lumen_agent_scene_skill_bundle: Literal["legacy", "candidate"] = "legacy"
    # Optional caller-owned viewing profile from the candidate manifest. Empty
    # means no numeric native-copy floor. Never inferred from page units/brand.
    lumen_agent_scene_review_profile: str = ""
    # Default-off single-agent scene experiment. Requires candidate knowledge
    # and the fast loop at scene construction; has no effect on website turns.
    lumen_agent_scene_solo: bool = False
    # R3's kill-switch. Under the fast loop the `lumen-visual-reviewer` subagent
    # is NOT dispatched on scene turns (the author's own self-audit critique.json
    # replaces it); setting this to 1 re-enables the reviewer WITHOUT leaving the
    # fast loop, which is how §7's "kill-switch check" run is performed and how a
    # defect class the self-audit misses gets the old reviewer back. Meaningless
    # (and ignored) when the fast loop is off — the reviewer is always dispatched
    # there.
    lumen_agent_scene_reviewer: bool = False
    # --- the WEB lane's own fast-loop flag (clone-fidelity F3.3, ruling D-F7) ------------
    # The flag above is scene-turn-only by §3 non-goal, so the web lane gets its own,
    # mirroring its shape exactly (founder preflight ruling P-6). OFF — the default — leaves
    # a web turn byte-identical to the pre-F3.3 loop: the `lumen-web-reviewer` subagent is
    # dispatched as always. ON quarantines it (built, never registered) and the orchestrator
    # self-reviews against the SAME shared rubric artifact. D-F7's closing line is the whole
    # contract: the flag changes WHO checks, never WHAT is checked.
    #
    # Default OFF rather than the scene flag's True, deliberately. The scene default was
    # flipped only after the fast loop had been proven live across the reference-ads
    # acceptance runs; nothing has been proven for web self-review yet, and a flag that
    # removes a reviewer earns its default from evidence rather than from its sibling's.
    lumen_agent_web_fast_loop: bool = False
    # The twin of `lumen_agent_scene_reviewer`: put the web reviewer back WITHOUT leaving the
    # web fast loop. Meaningless (and ignored) when that flag is off — the reviewer is always
    # dispatched there.
    lumen_agent_web_reviewer: bool = False
    # SOLO MODE (founder ruling 2026-09-04): ONE web deepagent — director, designer and
    # reviewer in a single model loop. Both subagents (`lumen-web-author`,
    # `lumen-web-reviewer`) are QUARANTINED (not registered; tool-absence enforcement, the
    # D-F7 pattern), the orchestrator carries the full authoring toolset, and the merged
    # solo prompt replaces direction-by-delegation with plan -> build -> render -> self-review.
    # Motive: the 2026-09-01 OpenAI-CFO diagnostic run measured ~20+ minutes of pure trio
    # coordination overhead (per-delegation skill re-reads, brief writing, discovery loss)
    # in a 57-minute page build. Overrides the two web flags above when on: there are no
    # subagents to quarantine selectively.
    lumen_agent_web_solo: bool = False
    # §5.6 budgets. RULING D1 (founder, 2026-08-26) SPLIT THESE IN TWO: budgets
    # are GUIDANCE, not gates.
    #
    #   * The TARGET is what the agent is told about. It rides the orchestrator
    #     prompt as a plain obligation ("aim to finish within…") and the
    #     round-boundary BUDGET LEFT line. NOTHING cuts a run off at the target
    #     — crossing it is recorded as `budget_target_exceeded` and the run
    #     carries on.
    #   * The BACKSTOP is the circuit breaker for a hung or runaway run, set at
    #     ~2x the target. It is the only hard stop, it still finalizes
    #     checkpointed work gracefully, and the agent's prompt never mentions it
    #     because a healthy run never reaches it.
    #
    # WHY 900s AND NOT 600s. Live A/B, 2026-08-26 (Apollo POC,
    # `.context/ref-ads-pilot-apollo-report.md`): at a 600s HARD wall the run was
    # cut right after its first look and shipped at reference_fidelity 1; at 900s
    # the same brief reacted to its own critique and reached fidelity 2. The old
    # ceiling was not protecting the run from waste, it was amputating the repair
    # round the loop exists to run.
    #
    # A non-positive value is a startup failure, not a silently disabled budget,
    # and a backstop below its own target is refused too (see the validators).
    lumen_agent_fast_loop_target_llm_calls: int = 45
    lumen_agent_fast_loop_target_wall_clock_s: float = 900.0
    lumen_agent_fast_loop_max_llm_calls: int = 90
    lumen_agent_fast_loop_wall_clock_s: float = 1800.0
    lumen_agent_fast_loop_inner_iterations: int = 4
    # §5.1 pin list override: comma-separated knowledge paths, each relative to
    # `apps/agent_runtime/knowledge_docs/`, inlined into the author's composed
    # frame payload. Blank/unset → `lumen_agent.frame.DEFAULT_PINNED_KNOWLEDGE`.
    # This is the seam a format skill's `pinned_knowledge:` manifest field feeds
    # once pre-dispatch skill selection exists (see the spec's §5.1 as-built note).
    lumen_agent_fast_loop_pinned_knowledge: str | None = None

    # §5.4 deterministic autofix: how many planning passes the code loop may run
    # per preflight. The loop also exits as soon as a pass makes no progress, so
    # this is a ceiling, not a schedule. 0 disables autofix while leaving the
    # rest of the fast loop on. Only read when `lumen_agent_fast_loop` is true.
    lumen_agent_autofix_max_passes: int = 2

    # Read by langchain directly from os.environ; declared here for visibility.
    anthropic_api_key: str | None = None

    @field_validator(
        "lumen_core_helper",
        "image_model_http_referer",
        "image_model_app_title",
        "lumen_agent_workspace_root",
        "lumen_agent_trace_dir",
        "lumen_agent_asset_store",
        "lumen_agent_base_url",
        "lumen_agent_api_key",
        "lumen_agent_reasoning",
        "lumen_ingestion_brief_reasoning",
        "lumen_agent_provider_sort",
        "lumen_agent_fallback_model",
        "lumen_agent_llm_timeout_s",
        "lumen_agent_model_orchestrator",
        "lumen_agent_model_author",
        "lumen_agent_model_reviewer",
        "lumen_agent_max_tokens",
        "lumen_agent_fast_loop_pinned_knowledge",
        "anthropic_api_key",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        """`VAR=` in a .env file means unset, matching the old `.strip() or None`."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("lumen_agent_reasoning", "lumen_ingestion_brief_reasoning")
    @classmethod
    def _validate_reasoning_effort(cls, value: str | None) -> str | None:
        """A typo'd effort must fail at startup, not silently no-op mid-run."""
        if value is None:
            return value
        effort = value.strip().lower()
        if effort not in {"low", "medium", "high"}:
            raise ValueError(
                "LUMEN_AGENT_REASONING must be one of low|medium|high (or unset "
                f"for no reasoning field); got {value!r}"
            )
        return effort

    @field_validator("lumen_agent_autofix_max_passes")
    @classmethod
    def _validate_autofix_max_passes(cls, value: int) -> int:
        """A negative cap is a typo, and an unbounded one defeats the point of a
        bounded loop — both must fail at startup rather than mid-turn."""
        if value < 0:
            raise ValueError(
                "LUMEN_AGENT_AUTOFIX_MAX_PASSES must be >= 0 (0 disables autofix); "
                f"got {value!r}"
            )
        return value

    @field_validator("lumen_agent_max_tokens")
    @classmethod
    def _validate_max_tokens(cls, value: int | None) -> int | None:
        """A junk or non-positive bound must fail at startup, not silently
        disable itself (or, worse, cap generation at 0) mid-run."""
        if value is None:
            return value
        if value <= 0:
            raise ValueError(
                "LUMEN_AGENT_MAX_TOKENS must be a positive integer (or unset for "
                f"no output bound); got {value!r}"
            )
        return value

    @field_validator("lumen_agent_llm_timeout_s")
    @classmethod
    def _validate_llm_timeout(cls, value: float | None) -> float | None:
        """A junk or non-positive timeout must fail at startup, not silently
        disable itself (or cap every call at 0s) mid-run."""
        if value is None:
            return value
        if value <= 0:
            raise ValueError(
                "LUMEN_AGENT_LLM_TIMEOUT_S must be a positive number of seconds "
                f"(or unset for no per-call timeout); got {value!r}"
            )
        return value

    @field_validator("lumen_api_origin", mode="before")
    @classmethod
    def _normalize_api_origin(cls, value: object) -> object:
        """Blank → the default (`VAR=` in a .env means unset); a trailing slash
        is stripped so `{origin}/asset-store` never doubles up."""
        if not isinstance(value, str):
            return value
        trimmed = value.strip().rstrip("/")
        return trimmed or "http://127.0.0.1:8010"

    @field_validator("lumen_degraded_repair_selection", mode="before")
    @classmethod
    def _validate_degraded_repair_selection(cls, value: object) -> object:
        """A typo'd value must fail at startup, not silently pick the other page.

        The two answers differ in exactly the way the founder ruled about — whether a page can
        seat a known-broken original — so falling back to a default on an unrecognized string
        would be the system quietly choosing for a deployment that thought it had chosen.
        """
        if not isinstance(value, str):
            return value
        selection = value.strip().lower()
        if not selection:
            return "keep_flagged"
        if selection not in {"keep_flagged", "fallback_original"}:
            raise ValueError(
                "LUMEN_DEGRADED_REPAIR_SELECTION must be one of "
                "keep_flagged|fallback_original (keep_flagged = the newest released repair "
                "stays selected, flagged degraded and requiring review; fallback_original = a "
                f"degraded released repair falls back to the original); got {value!r}"
            )
        return selection

    @field_validator("image_model_api_style", mode="before")
    @classmethod
    def _validate_image_model_api_style(cls, value: object) -> object:
        """A typo'd transport must fail at startup, not silently send a
        chat-completions body to an Images endpoint (or vice versa) — either
        way every generation 400s straight to the grey stub placeholder."""
        if not isinstance(value, str):
            return value
        style = value.strip().lower()
        if not style:
            return "chat"
        if style not in {"chat", "images"}:
            raise ValueError(
                "IMAGE_MODEL_API_STYLE must be one of chat|images (chat = the "
                "chat-completions image modality, images = POST {base_url}/images); "
                f"got {value!r}"
            )
        return style

    @field_validator(
        "lumen_agent_fast_loop_target_llm_calls",
        "lumen_agent_fast_loop_target_wall_clock_s",
        "lumen_agent_fast_loop_max_llm_calls",
        "lumen_agent_fast_loop_wall_clock_s",
        "lumen_agent_fast_loop_inner_iterations",
    )
    @classmethod
    def _validate_fast_loop_budget(cls, value: float) -> float:
        """§5.6 budgets must be real numbers a run can be measured against.

        A zero or negative budget would either stop the run before its first
        model call or (read the other way) disable the backstop entirely — both
        are silent, and a budget that silently does nothing is worse than no
        budget at all. Fail at startup instead.
        """
        if value <= 0:
            raise ValueError(
                "LUMEN_AGENT_FAST_LOOP_* budgets must be positive (calls, seconds, "
                f"iterations); got {value!r}"
            )
        return value

    @model_validator(mode="after")
    def _validate_backstop_sits_above_its_target(self) -> Settings:
        """D1: the backstop must be reachable only AFTER the target, never before.

        A backstop below its own target inverts the whole ruling — the run would
        be hard-stopped before it ever crossed the guidance it was told to steer
        by, and the prompt's "nothing cuts you off here" would be a lie the
        harness tells the agent. That is exactly the silent failure the other
        budget validators exist to prevent, so it fails at startup too.
        """
        if self.lumen_agent_fast_loop_max_llm_calls < self.lumen_agent_fast_loop_target_llm_calls:
            raise ValueError(
                "LUMEN_AGENT_FAST_LOOP_MAX_LLM_CALLS (the backstop, "
                f"{self.lumen_agent_fast_loop_max_llm_calls}) must be >= "
                "LUMEN_AGENT_FAST_LOOP_TARGET_LLM_CALLS (the target, "
                f"{self.lumen_agent_fast_loop_target_llm_calls})"
            )
        if (
            self.lumen_agent_fast_loop_wall_clock_s
            < self.lumen_agent_fast_loop_target_wall_clock_s
        ):
            raise ValueError(
                "LUMEN_AGENT_FAST_LOOP_WALL_CLOCK_S (the backstop, "
                f"{self.lumen_agent_fast_loop_wall_clock_s}) must be >= "
                "LUMEN_AGENT_FAST_LOOP_TARGET_WALL_CLOCK_S (the target, "
                f"{self.lumen_agent_fast_loop_target_wall_clock_s})"
            )
        return self

    @model_validator(mode="after")
    def _resolve_openrouter_key_from_the_platform_name(self) -> Settings:
        """W5/R2-B: one OpenRouter resolution for the whole design subsystem.

        `OPENROUTER_API_KEY` is the design name and keeps precedence. When it is absent or
        blank, the platform-namespaced `CLUE_OPENROUTER_API_KEY` supplies the same secret, so
        a monorepo `.env` that only spells the platform name still keys the describer, the
        brief agent, the ingestion assist, the PDF vision pass, the ad-DNA distiller and the
        turn-time style-group matcher — all of which read `settings.openrouter_api_key` and
        none of which resolve anything themselves.

        Blank counts as absent, matching `_blank_is_unset`: `OPENROUTER_API_KEY=` in a `.env`
        (or the same line shell-expanded from an unset variable) means "not configured", and
        it must not shadow a platform key that IS configured. Falling through is what makes
        the failure loud-by-absence rather than silently inert.
        """
        if not self.openrouter_api_key.strip() and self.clue_openrouter_api_key.strip():
            self.openrouter_api_key = self.clue_openrouter_api_key
        return self

    @field_validator("image_model_id", mode="before")
    @classmethod
    def _normalize_image_model_id(cls, value: object) -> object:
        """Tolerate stray surrounding quotes in a `.env` value; blank → default."""
        if not isinstance(value, str):
            return value
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        return value or "default"

    @property
    def cors_origins_list(self) -> list[str]:
        origins = [o.strip() for o in self.lumen_api_cors_origins.split(",") if o.strip()]
        return origins or ["http://127.0.0.1:3000"]

    @property
    def asset_base_url(self) -> str:
        """The absolute base every `data-asset` image resolves against off-request:
        `{LUMEN_API_ORIGIN}/asset-store`.

        Derived rather than configured whole so an operator can never point the
        origin at a real server and still get a wrong PATH — the `/asset-store`
        suffix is the route's own, spelled here once (the request-bound paths in
        `lumen_api.main` build the same string from `request.base_url`)."""
        return f"{self.lumen_api_origin.rstrip('/')}/asset-store"

    @property
    def effective_asset_store_root(self) -> Path:
        """The engine materialization-cache ROOT (D4): LUMEN_ASSET_STORE_ROOT if set, else the
        git-ignored `.engine-cache` beside this repo.

        It used to be anchored to the (now-deleted) SQLite database path; with the database gone
        and the durable home moved to `clue_storage`, a repo-local ignored directory is the
        honest default for a cache nothing durable depends on. Per-WORKSPACE cache dirs hang
        below this root — callers take `engine_cache_root(workspace_id)`, never this raw path.
        """
        return self.lumen_asset_store_root or _REPO_ROOT / ".engine-cache"

    def image_model_configured(self) -> bool:
        return bool(self.image_model_base_url.strip() and self.image_model_api_key.strip())


# Singleton instance — import this from anywhere:
#   from py_lumen_config import settings
settings = Settings()
