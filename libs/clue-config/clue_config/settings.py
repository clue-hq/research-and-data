"""Non-secret environment settings — model ids and other deploy-time knobs (M0.4).

:class:`Secrets` holds credentials (API keys, DSN). This module holds **non-secret** values read
from the environment via ``pydantic-settings`` — the same ``CLUE_`` prefix and ``.env`` file, but
plain strings rather than :class:`~pydantic.SecretStr`. Loaded once and injected; callers do not
read ``os.environ`` ad hoc.

The ICP synthesis model id (M5.2) is the first live setting here; it also feeds
:class:`~clue_config.gateway.GatewayConfig.synthesis_model` so ``get_config`` and
``synthesize_icps`` share one default.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Annotated, Any, Final, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Canonical fallback when ``CLUE_SYNTHESIS_MODEL`` is unset — keep in sync with GatewayConfig docs.
DEFAULT_SYNTHESIS_MODEL: Final = "openai/gpt-5.6-terra"

_ALLOWLIST_FORMAT_ERROR: Final = (
    'CLUE_AGENT_WORKSPACE_ALLOWLIST must be a JSON array (["ws-a","ws-b"]) or a comma-separated '
    "list (ws-a,ws-b)"
)
_FALLBACK_MODELS_FORMAT_ERROR: Final = (
    'CLUE_AGENT_FALLBACK_MODELS must be a JSON array (["x-ai/grok-4.7","meta/muse-spark-1.3"]) '
    "or a comma-separated list (x-ai/grok-4.7,meta/muse-spark-1.3)"
)

_CONTEXT_WINDOWS_FORMAT_ERROR: Final = (
    "CLUE_AGENT_MODEL_CONTEXT_WINDOWS must be a comma-separated list of model=tokens "
    "(x-ai/grok-4.6=500000,meta/muse-spark-1.3=1048576) or a JSON object "
    '({"x-ai/grok-4.6": 500000})'
)

_CORS_ORIGINS_FORMAT_ERROR: Final = (
    'CLUE_FRONTEND_CORS_ALLOW_ORIGINS must be a JSON array (["https://app.example"]) or a '
    "comma-separated list (https://app.example,http://localhost:3000)"
)

_CORS_WILDCARD_ERROR: Final = (
    'CLUE_FRONTEND_CORS_ALLOW_ORIGINS must not contain "*": the platform sends credentials and '
    "authorizes tenants from a trusted X-Workspace-Id header, and Starlette does not refuse the "
    "wildcard-plus-credentials combination — it echoes back whichever Origin asked, which would "
    "make every browser origin a credentialed caller of the whole app. List the exact origins "
    "(https://app.example,http://localhost:3000)"
)

_AUTH_PARTIES_FORMAT_ERROR: Final = (
    'CLUE_AUTH_CLERK_AUTHORIZED_PARTIES must be a JSON array (["https://app.example"]) or a '
    "comma-separated list (https://app.example,http://localhost:3000)"
)

_OFFICIAL_SITE_ALLOWLIST_FORMAT_ERROR: Final = (
    "CLUE_STAGE0_OFFICIAL_SITE_CRAWL_WORKSPACE_ALLOWLIST must be a JSON array "
    '(["ws-a","ws-b"]) or a comma-separated list (ws-a,ws-b)'
)


def _parse_string_list(value: Any, format_error: str) -> Any:
    """Accept a JSON array *or* a plain comma-separated list for a ``tuple[str, ...]`` setting.

    Both spellings survive the ways these values actually reach a process (a JSON array in a
    ``.env`` file; a bare comma-separated list that a shell ``source`` cannot mangle). A value that
    is neither fails as *its own* field, with a message naming both accepted formats, rather than
    aborting the construction of every other setting (see the ``NoDecode`` note at the call sites).
    """

    if not isinstance(value, str):
        return value
    raw = value.strip()
    if not raw:
        return ()
    if raw.startswith("["):
        try:
            decoded = json.loads(raw)
        except ValueError as exc:
            raise ValueError(format_error) from exc
        if not isinstance(decoded, list):
            raise ValueError(format_error)
        return decoded
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _parse_model_windows(value: Any) -> Any:
    """Accept ``model=tokens,model=tokens`` *or* a JSON object for the context-window registry."""

    if not isinstance(value, str):
        return value
    raw = value.strip()
    if not raw:
        return {}
    if raw.startswith("{"):
        try:
            decoded = json.loads(raw)
        except ValueError as exc:
            raise ValueError(_CONTEXT_WINDOWS_FORMAT_ERROR) from exc
        if not isinstance(decoded, dict):
            raise ValueError(_CONTEXT_WINDOWS_FORMAT_ERROR)
        return decoded
    windows: dict[str, str] = {}
    for entry in (item.strip() for item in raw.split(",")):
        if not entry:
            continue
        model, sep, tokens = entry.rpartition("=")
        if not sep or not model.strip() or not tokens.strip():
            raise ValueError(_CONTEXT_WINDOWS_FORMAT_ERROR)
        windows[model.strip()] = tokens.strip()
    return windows


# The checked-in activation record for the integration/pilot product path
# (``docs/FI-comprehensive-account-contact-research-contract.md`` §9). Applied as *defaults* by
# :meth:`Settings._apply_product_path_overlay` when ``CLUE_PRODUCT_PATH=integration_pilot``; an
# explicitly provided value (env var or kwarg) always wins over an entry here.
INTEGRATION_PILOT_OVERLAY: dict[str, bool] = {
    "exa_websets_lifecycle_enabled": True,
    "exa_websets_acquisition_enabled": True,
    "exa_account_deep_acquisition_enabled": True,
    "sumble_account_gap_enrichment_enabled": True,
    "sumble_committee_acquisition_enabled": True,
    "exa_contact_deep_acquisition_enabled": True,
    "entity_research_runtime_enabled": True,
    "chat_enabled": True,
    "frontend_read_enabled": True,
    "verification_enabled": False,
    "budget_controls_enabled": False,
    # Slice F adds: contact_channel_enrichment_enabled, frontend_contact_email_lookup_enabled.
    # Slice G adds: c7_research_view_read_enabled, c7_snapshot_compose_enabled,
    #               c7_production_handoff_enabled.
}


class Settings(BaseSettings):
    """Deploy-time settings read from the environment (not secrets)."""

    model_config = SettingsConfigDict(
        env_prefix="CLUE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    # OpenRouter model id for ICP synthesis (M5.2) and other grounded-synthesis call sites that
    # reuse ``GatewayConfig.synthesis_model``. Env: ``CLUE_SYNTHESIS_MODEL``.
    synthesis_model: str = DEFAULT_SYNTHESIS_MODEL
    # OpenRouter model id for every LLM-as-judge call site (the M9.3 faithfulness judge, and
    # through it PC-C8 §6c-b's typed-interview-value entailment). ``None`` keeps the code default
    # in ``GatewayConfig.judge_model``. Env: ``CLUE_JUDGE_MODEL``.
    #
    # This exists because the code default is a *code* default: model ids rot, and the 2026-08-01
    # §6c probe found `anthropic/claude-3.5-sonnet` no longer served ("No endpoints found"), which
    # made every judged claim fail closed as `judge_unavailable`. Picking the platform's judge is a
    # deployment decision, so it gets the same env seam ``synthesis_model`` already has rather than
    # a rewritten constant.
    judge_model: str | None = None
    # The gateway's per-call timeout ceiling (``GatewayConfig.timeout_s``). It bounds every gateway
    # request AND is the ceiling the agent model builder enforces on a profile's ``model.timeout_s``
    # (a profile above it is refused at build time — how the first onboarding-synthesis turn
    # failed, 2026-09-08). Founder ruling 2026-09-08: 60s. Env: ``CLUE_GATEWAY_TIMEOUT_S``.
    gateway_timeout_s: float = Field(default=30.0, gt=0)

    # Temporary master switch for M9 runtime verification. False keeps the canonical VERIFICATION
    # phase in the durable state-machine sequence, but skips deterministic corroboration and
    # prevents the API composition roots from constructing the M9.3 faithfulness judge (including
    # the earlier reverse-profiling and toolbelt entailment call sites). Structural controls outside
    # that runtime pass (pre-spend authorization, born contact identity binding,
    # freshness/retention, and M10's use gate) remain active. Unverified tier-4 claims remain
    # excluded by the merge policy.
    # Env: ``CLUE_VERIFICATION_ENABLED``.
    verification_enabled: bool = True

    # Pilot master switch for budget/cost *controls* (FI-pilot-budget-controls, ratified
    # 2026-08-11). True is today's behavior. False is the pilot posture: users are never shown a
    # cost or budget number and **nothing on the platform stops a pre-approved action on budget
    # grounds** — hard spend control lives at the provider consoles instead. Specifically, when
    # False: (a) the directive-confirmation gate still computes and durably stores
    # ``max_spend_cents`` (audit + approval integrity) but the amount leaves every model- and
    # human-visible surface; (b) the R9 atomic tool-batch admission, the M7.5 project-run budget
    # pre-gate, and the launchers' economic equality/headroom checks admit instead of refusing.
    # Spend **recording** is untouched in both modes — reservations, settlements, ``spent_cents``,
    # and the M13.4 cost observability all keep accumulating honestly, so a pilot deployment
    # over-spends visibly rather than silently. Structural controls stay on in both modes:
    # depth/fanout caps, the exact human-approved account selection, canary/quality suspension, the
    # M9.1 pre-spend *authority* gate, and the gate's directive-digest binding.
    # Deployment-scoped, not pinned per run (the same accepted caveat as ``verification_enabled``).
    # Env: ``CLUE_BUDGET_CONTROLS_ENABLED``.
    budget_controls_enabled: bool = True

    # The integration/pilot product path (docs/FI-comprehensive-account-contact-research-contract.md
    # §9). "integration_pilot" applies INTEGRATION_PILOT_OVERLAY as *defaults*: any flag explicitly
    # provided (env var or kwarg) still wins. This is the checked-in activation record; individual
    # deployments keep the conservative "default" path.
    # Env: ``CLUE_PRODUCT_PATH``.
    product_path: Literal["default", "integration_pilot"] = "default"

    # --- production metrics export -------------------------------------------------------
    # Tests/dev may retain the deterministic in-memory sink. A production-auth deployment must
    # choose OTLP explicitly and provide the collector's HTTP /v1/metrics endpoint; otherwise a
    # process that appears observable would silently discard every metric at shutdown.
    metrics_exporter: Literal["memory", "otlp"] = "memory"
    metrics_otlp_endpoint: str | None = None
    metrics_export_interval_ms: int = Field(default=10_000, ge=100)

    # --- telemetry roots (lane 3 slice 2; all off by default) ------------------------------
    # OTLP/HTTP traces endpoint (slice 3 points it at Langfuse). Empty → spans are created
    # in-process and exported nowhere, today's behaviour. Env: ``CLUE_OTEL_TRACES_ENDPOINT``.
    otel_traces_endpoint: str | None = None
    # Instrument the FastAPI app (server spans) and httpx (client spans) at the roots. On by
    # default because without an endpoint the spans cost nothing and go nowhere.
    # Env: ``CLUE_OTEL_INSTRUMENT_FASTAPI`` / ``CLUE_OTEL_INSTRUMENT_HTTPX``.
    otel_instrument_fastapi: bool = True
    otel_instrument_httpx: bool = True
    # Sentry (R6): installed only when enabled AND ``CLUE_SENTRY_DSN`` (a secret) is set; the
    # roots refuse ``enabled`` with no DSN. ``sentry_environment`` names the deployment posture
    # on every event; ``release`` is the code version (a git sha), empty → unset.
    # Env: ``CLUE_SENTRY_ENABLED`` / ``CLUE_SENTRY_ENVIRONMENT`` / ``CLUE_RELEASE``.
    sentry_enabled: bool = False
    sentry_environment: str = "lane-san-salvador"
    release: str | None = None

    # --- Langfuse (lane 3 slice 3, R4: cloud, EU) -------------------------------------------
    # On by default (founder, 2026-09-15): installed whenever both keys (secrets) are set; with
    # the keys blank the roots log ``langfuse.not_installed`` and run without it, so a process
    # without a project (CI, a fresh worktree) still boots. Set it false to silence a configured
    # project. The client attaches to the process's tracer provider but exports only the agent
    # harness (2026-10-03: no HTTP or ``fleet.task`` spans; each fleet task is its own trace,
    # linked to its launcher). ``langfuse_environment`` names the
    # deployment posture on every trace (Langfuse allows ``[a-z0-9-_]`` only).
    # Env: ``CLUE_LANGFUSE_ENABLED`` / ``CLUE_LANGFUSE_HOST`` / ``CLUE_LANGFUSE_ENVIRONMENT``.
    langfuse_enabled: bool = True
    langfuse_host: str = "https://cloud.langfuse.com"
    langfuse_environment: str = "lane-san-salvador"

    # --- fleet worker (PB-B1; append-only per the Phase B treaty §3.2) ----------------------
    # How often an idle worker polls the task queue. Env: ``CLUE_FLEET_POLL_INTERVAL_S``.
    fleet_poll_interval_s: float = 1.0
    # How many tasks ONE worker process drives at once (founder ruling 2026-09-10). The worker
    # runs this many independent drain loops over the same queue; each claims on its own (the
    # claim is already ``FOR UPDATE SKIP LOCKED``, so two loops never get the same row) and each
    # task keeps its own lease and heartbeat. Several worker processes still run against the same
    # queue — this knob is per process. 1 is the single loop the fleet shipped with.
    # Env: ``CLUE_FLEET_WORKER_CONCURRENCY``.
    fleet_worker_concurrency: int = Field(default=1, ge=1)
    # Which task kinds THIS worker process claims (first deployment, 2026-10-01): a comma-separated
    # list of ``FleetTaskKind`` values, blank = every kind (the behaviour before this setting). It
    # is how one VM runs separate pools — chat (``agent_turn``), design (``design_job``) and batch
    # — so a long research job can never hold the slot a chat turn needs.
    # Env: ``CLUE_FLEET_WORKER_KINDS``.
    fleet_worker_kinds: str = ""
    # Per-run driver-lease TTL: a killed driver's run is re-drivable after this long. Must be
    # comfortably larger than the heartbeat interval. Env: ``CLUE_FLEET_LEASE_TTL_S``.
    fleet_lease_ttl_s: float = 30.0
    # How often a driving worker renews (heartbeats) its run lease. Env:
    # ``CLUE_FLEET_HEARTBEAT_INTERVAL_S``.
    fleet_heartbeat_interval_s: float = 10.0
    # How long a claimed ``fleet_task`` is honoured before it is presumed orphaned by a killed
    # worker and re-owned. Sized to outlive the lease TTL (takeover is lease-gated first). Env:
    # ``CLUE_FLEET_TASK_STALE_AFTER_S``.
    fleet_task_stale_after_s: float = 60.0
    # The worker process's thread pool: every blocking provider call AND the event loop's DNS
    # lookups (a fresh DB connection, the lease heartbeat's included) share it. Python's default,
    # min(32, cpu + 4), is filled by a few research jobs; threads start only on demand.
    # Env: ``CLUE_FLEET_THREAD_POOL_SIZE``.
    fleet_thread_pool_size: int = Field(default=128, ge=8)
    # The deep-phase concurrency window — account jobs in flight at once (REQ-10 ~16–32; the
    # accounts-per-pass half of the cost dial). Env: ``CLUE_FLEET_DEEP_WINDOW``.
    fleet_deep_window: int = 16

    # --- Exa Websets durable discovery lifecycle (M6A D3) -------------------------------
    # Default-off until the deployment has Websets API entitlement. The webhook HTTP route is
    # independently exposed when its secret is configured; this switch starts the poll worker.
    # It deliberately does NOT authorize new paid Websets: deployments may need to drain/reconcile
    # existing operations while preventing any new spend.
    # Env: CLUE_EXA_WEBSETS_LIFECYCLE_ENABLED / CLUE_EXA_WEBSETS_POLL_WORKER_INTERVAL_S.
    exa_websets_lifecycle_enabled: bool = False
    exa_websets_poll_worker_interval_s: float = Field(default=1.0, gt=0)
    # Independent master authorization for confirmed-ICP -> paid Webset acquisition (M6A D6).
    # Production also requires lifecycle_enabled so originated work cannot be left undrained.
    # Env: CLUE_EXA_WEBSETS_ACQUISITION_ENABLED.
    exa_websets_acquisition_enabled: bool = False
    # Independent authorization for post-seal, explicitly targeted E1 imports. The lifecycle
    # worker still drains already-created E1 operations whenever Websets lifecycle is enabled.
    # Env: CLUE_EXA_TARGETED_ENRICHMENT_ENABLED.
    exa_targeted_enrichment_enabled: bool = False
    # Independent default-off authorization and bounded wire-policy knobs for target-locked Exa
    # Search account-deep acquisition (M8B A0/E0). This is not Websets discovery or post-seal
    # Websets import; neither existing Exa flag implicitly enables it.
    # Env: CLUE_EXA_ACCOUNT_DEEP_ACQUISITION_ENABLED / CLUE_EXA_ACCOUNT_DEEP_SEARCH_TYPE /
    # CLUE_EXA_ACCOUNT_DEEP_MAX_RESULTS / CLUE_EXA_ACCOUNT_DEEP_MAX_ADDITIONAL_QUERIES.
    exa_account_deep_acquisition_enabled: bool = False
    exa_account_deep_search_type: Literal["deep", "deep-reasoning"] = "deep-reasoning"
    # Exa's public endpoint currently admits up to 100, but the accepted Clue policy cap is 50.
    exa_account_deep_max_results: int = Field(default=50, ge=1, le=50)
    exa_account_deep_max_additional_queries: int = Field(default=10, ge=0, le=10)
    # Independent default-off authorization for exact selected-contact Exa Search (M8C C6).
    # Account-profile acquisition never implicitly enables personal/contact research.
    # Env: CLUE_EXA_CONTACT_DEEP_ACQUISITION_ENABLED.
    exa_contact_deep_acquisition_enabled: bool = False
    # Exact selected-contact channel work remains independently default-off and additionally
    # requires a concrete validator binding at composition. A coarse directive flag cannot enable
    # this deployment switch. Env: CLUE_CONTACT_CHANNEL_ENRICHMENT_ENABLED.
    contact_channel_enrichment_enabled: bool = False
    # One provider-neutral due-operation scan serves committee and contact waits in C6.
    # Env: CLUE_EXTERNAL_RESEARCH_WAKE_WORKER_INTERVAL_S.
    external_research_wake_worker_interval_s: float = Field(default=1.0, gt=0)
    # Independent authorization for the bounded, pre-seal Sumble organization-field waterfall.
    # This is deliberately separate from post-selection S1: enabling optional jobs/technology work
    # must not silently authorize discovery-stage spend, or vice versa.
    # Env: CLUE_SUMBLE_DISCOVERY_GAP_ENRICHMENT_ENABLED.
    sumble_discovery_gap_enrichment_enabled: bool = False
    # Independent authorization and plan-specific monetary conversion for post-selection Sumble S1.
    # Provider credits remain the authoritative charged unit; zero means no honest subscription
    # allocation has been configured and monetary reporting stays zero rather than being invented.
    # Env: CLUE_SUMBLE_ACCOUNT_GAP_ENRICHMENT_ENABLED / CLUE_SUMBLE_CENTS_PER_CREDIT.
    sumble_account_gap_enrichment_enabled: bool = False
    sumble_cents_per_credit: Decimal = Field(default=Decimal(0), ge=0)
    # Independent, default-off authorization for S2 no-reveal Teams + People acquisition during
    # account-deep research. Enabling S1 never enables personal-data acquisition implicitly.
    # Env: CLUE_SUMBLE_COMMITTEE_ACQUISITION_ENABLED / CLUE_SUMBLE_COMMITTEE_POLL_AFTER_S /
    # CLUE_SUMBLE_COMMITTEE_WAKE_WORKER_INTERVAL_S.
    sumble_committee_acquisition_enabled: bool = False
    sumble_committee_poll_after_s: int = Field(default=30, ge=1)
    sumble_committee_wake_worker_interval_s: float = Field(default=1.0, gt=0)

    # --- C5 Recipe #1 new-run routing -------------------------------------------------------
    # Master switch. False is a hard off regardless of allowlist/percentage; existing runs are
    # never backfilled. Env: ``CLUE_RECIPE1_ROUTING_ENABLED``.
    recipe1_routing_enabled: bool = False
    # Explicit workspace canary targets (JSON array in environment configuration).
    # Env: ``CLUE_RECIPE1_WORKSPACE_ALLOWLIST``.
    recipe1_workspace_allowlist: tuple[str, ...] = ()
    # Deterministic workspace-hash percentage canary. Zero plus an empty allowlist means no target.
    # Env: ``CLUE_RECIPE1_CANARY_PERCENT``.
    recipe1_canary_percent: int = Field(default=0, ge=0, le=100)
    # The supervisor policy version Recipe #1 must pin at start.
    # Env: ``CLUE_RECIPE1_SUPERVISOR_POLICY_VERSION``.
    recipe1_supervisor_policy_version: str = "supervisor-v1"
    # Process-local ceiling applied in addition to each recipe's promoted max_fanout.
    # Env: ``CLUE_RECIPE_EXECUTOR_MAX_CONCURRENCY``.
    recipe_executor_max_concurrency: int = Field(default=32, ge=1)
    # --- scoped memory (PB-B3; append-only additions per treaty §3.2) -----------------------
    # Deploy-level master default for the memory substrate. The *real* mechanism is the
    # per-workspace toggle + audit journal (Doc M §17a — the ``memory_switch`` table); this flag
    # layers above it: False blanks memory for every workspace. Env: ``CLUE_MEMORY_ENABLED``.
    memory_enabled: bool = True
    # OpenRouter model id for the write-time reconciliation judge (Doc M §9).
    # Env: ``CLUE_MEMORY_RECONCILE_MODEL``.
    memory_reconcile_model: str = DEFAULT_SYNTHESIS_MODEL
    # --- durable artifact storage (Phase B2 / REQ-07; append-only per treaty §3.2) ---
    # Which StorageBackend `clue_storage.storage_from_settings` builds. The fs ↔ S3 swap is this
    # one setting (the B2 exit gate); nothing else may branch on it.
    storage_backend: Literal["fs", "s3"] = "fs"
    # Root directory for the fs backend. Env: ``CLUE_STORAGE_FS_ROOT``.
    storage_fs_root: str = ".artifacts"
    # S3-compatible backend knobs (endpoint config covers AWS S3 / R2 / MinIO). The bucket is
    # required when ``storage_backend=s3`` (the factory fails loud). Credentials are Secrets
    # (``CLUE_STORAGE_S3_ACCESS_KEY_ID`` / ``CLUE_STORAGE_S3_SECRET_ACCESS_KEY``), not settings.
    storage_s3_bucket: str | None = None
    storage_s3_endpoint_url: str | None = None
    storage_s3_region: str | None = None
    # Keep-alive connections the shared S3 client may hold (research slowness fix 2026-10-03).
    # Env: ``CLUE_STORAGE_S3_MAX_POOL_CONNECTIONS``.
    storage_s3_max_pool_connections: int = Field(default=50, ge=1)

    # --- platform deepagent workspace (C6.1) -----------------------------------------------
    # Dedicated host root for ephemeral agent execution trees. Production composition requires
    # an absolute path unrelated to both the source worktree and the service user's home. It is
    # intentionally separate from durable artifact storage. Env: ``CLUE_AGENT_WORKSPACE_ROOT``.
    agent_workspace_root: str | None = None
    # C6.8 production routing is fail-closed and applies only to new durable ownership subjects.
    # False is a hard off even when an allowlist or percentage is configured.
    # Env: ``CLUE_AGENT_RUNTIME_ROUTING_ENABLED``.
    agent_runtime_routing_enabled: bool = False
    # Independently admit the two production verticals. The master switch still dominates.
    # Env: ``CLUE_AGENT_STAGE0_ROUTING_ENABLED`` / ``CLUE_AGENT_ACCOUNT_ROUTING_ENABLED``.
    agent_stage0_routing_enabled: bool = False
    agent_account_routing_enabled: bool = False
    # M8D R10 production cutover for the separately launched account/contact ``create_agent()``
    # runs. This switch owns only the shared entity-research worker and launch/read tools; it does
    # not authorize a provider. Exa/Sumble/channel switches above remain independent hard gates.
    # Env: ``CLUE_ENTITY_RESEARCH_RUNTIME_ENABLED``.
    entity_research_runtime_enabled: bool = False

    # --- ARV2 research lane (R1) ------------------------------------------------------------
    # Selects the ARV2 fleet handler and launcher at composition (A7). Shipped dark through R1;
    # **default True since the R2 exit gate passed on 2026-09-08** (founder instruction
    # 2026-09-07: flip once R2 is over). A worker missing a credential still composes no handler.
    # Env: ``CLUE_ARV2_ACCOUNT_RESEARCH_ENABLED``.
    # New launches use the discovery-first v4 Deep Agent (founder ruling 2026-09-24).
    # Historical jobs still resolve their pinned catalog, including legacy v1 rows.
    arv2_research_catalog_version: Literal["v1", "v2", "v3", "v4"] = "v4"
    arv2_account_research_enabled: bool = True
    # Durable quality continuation/outbox recovery; no effect when no quality generation exists.
    arv2_quality_reconcile_interval_s: float = Field(default=10.0, gt=0)
    # Minimum seconds between AI Ark calls (the proof-of-concept pacing, kept until the paid
    # tier's real rate limit is confirmed). Env: ``CLUE_ARV2_AI_ARK_MIN_GAP_S``.
    arv2_ai_ark_min_gap_s: float = 10.5
    # OpenRouter model id for the structuring pass (prose -> claims against the field catalog).
    # Env: ``CLUE_ARV2_STRUCTURING_MODEL``.
    arv2_structuring_model: str = "openai/gpt-5-mini"
    # OpenRouter model id for the cheap first pass over short media (Appendix A law 11's
    # two-model recipe). Env: ``CLUE_ARV2_MEDIA_SHORT_MODEL``.
    arv2_media_short_model: str = "google/gemini-3.5-flash-lite"
    # **Native Gemini** model id — the one ARV2 call that bypasses OpenRouter, because OpenRouter
    # serves neither this transcription model nor a file upload. It reads
    # ``Secrets.gemini_api_key`` directly. Env: ``CLUE_ARV2_MEDIA_TRANSCRIBE_MODEL``.
    arv2_media_video_model: str = "gemini-3.5-flash-lite"
    arv2_media_transcribe_model: str = "gemini-3.5-transcribe"
    # Active recording ASR is Deepgram Nova-3; Gemini fields above serve legacy callers.
    # en matches the trial; auto detects dominant language; multi permits code-switching.
    arv2_deepgram_language: str = "en"
    # PAYG prerecorded list rates; computed USD is an estimate, not invoice metering.
    arv2_deepgram_usd_per_minute: Decimal = Field(
        default=Decimal("0.0043"), ge=0, allow_inf_nan=False
    )
    arv2_deepgram_multi_usd_per_minute: Decimal = Field(
        default=Decimal("0.0052"), ge=0, allow_inf_nan=False
    )
    # OpenRouter embeddings model id (text embeddings only — Appendix A law 11).
    # Env: ``CLUE_ARV2_EMBEDDING_MODEL``.
    arv2_embedding_model: str = "google/gemini-embedding-2"
    # Hard ceiling on media seconds sent to a model in one research run. Enforced (money truth,
    # master plan §2 item 3). Env: ``CLUE_ARV2_MEDIA_SECONDS_CEILING``.
    arv2_media_seconds_ceiling: int = 9000
    # Above this duration a media item is not eligible for the cheap short-model pass.
    # Env: ``CLUE_ARV2_MEDIA_SHORT_MAX_SECONDS``.
    arv2_media_short_max_seconds: int = 600
    # Where the file raw sink and the JSONL ledger write in development and tests (production
    # routes raw bodies to the ``artifact`` table and the ledger to ``provider_call_ledger``),
    # and — in every environment — where research downloads podcast audio, deleted once
    # transcribed. Relative paths resolve against the working directory; the backend image sets
    # an absolute, writable one. Env: ``CLUE_ARV2_RAW_ROOT``.
    arv2_raw_root: str = ".artifacts/arv2"

    # --- ARV2 R2 account agent (master plan §9 R2; founder stop-policy ruling 2026-09-08) ------
    # Model rounds per research job (account and person), 350 by founder ruling 2026-09-27. The
    # agent is told to wrap up three rounds before the end and finalizes ``blocked`` with what it
    # saved; it is a safety net, never a budget. The upper bound is the runtime's own ceiling
    # (``clue_agents.execution.MAX_RUNTIME_MODEL_ROUNDS``), so a value the runtime would refuse
    # is refused here, at start-up. Env: ``CLUE_ARV2_ACCOUNT_MAX_MODEL_ROUNDS``.
    arv2_account_max_model_rounds: int = Field(default=350, ge=1, le=500)
    # Tool calls the model may issue in ONE round; the excess receive a recoverable refusal.
    # Env: ``CLUE_ARV2_ACCOUNT_MAX_TOOL_CALLS_PER_ROUND``.
    arv2_account_max_tool_calls_per_round: int = Field(default=50, ge=1)
    # Wall clock per research job, seconds; 0 means no timeout (founder ruling 2026-09-27).
    # ``agent_long_turn_alert_s`` still warns when a job runs long.
    # Env: ``CLUE_ARV2_ACCOUNT_MAX_RUNTIME_S``.
    arv2_account_max_runtime_s: int = Field(default=0, ge=0)
    # Account jobs one worker drives concurrently. Env: ``CLUE_ARV2_ACCOUNT_MAX_PARALLEL_JOBS``.
    arv2_account_max_parallel_jobs: int = Field(default=4, ge=1)
    # Concurrent calls per provider within one job (AI Ark is always 1 — its pacing is per
    # client). Env: ``CLUE_ARV2_ACCOUNT_PROVIDER_CONCURRENCY``.
    arv2_account_provider_concurrency: int = Field(default=4, ge=1)
    # Largest podcast enclosure the media tool downloads, MiB.
    # Env: ``CLUE_ARV2_ACCOUNT_MEDIA_MAX_ENCLOSURE_MB``.
    arv2_account_media_max_enclosure_mb: int = Field(default=200, ge=1)

    # --- Deep Agent turn limits (founder ruling 2026-09-27) -----------------------------------
    # Operator settings, not profile content: changing one never mints a profile version.
    # Model rounds per Head-of-ABM chat turn. As with research, the agent is told to wrap up
    # three rounds before the end and then finalizes ``awaiting_input`` ("reply continue").
    # Env: ``CLUE_HEAD_OF_ABM_MAX_MODEL_ROUNDS``.
    head_of_abm_max_model_rounds: int = Field(default=350, ge=1, le=500)
    # Conversation compaction for every governed agent (founder ruling 2026-09-29). The model's
    # context window comes from OpenRouter's catalogue unless overridden; compaction starts at
    # TRIGGER_FRACTION of it and keeps the newest KEEP_FRACTION whole. With no known window the
    # fixed pair applies. Env: ``CLUE_AGENT_CONTEXT_WINDOW_TOKENS``,
    # ``CLUE_AGENT_COMPACT_TRIGGER_FRACTION``, ``CLUE_AGENT_COMPACT_KEEP_FRACTION``,
    # ``CLUE_AGENT_COMPACT_TRIGGER_TOKENS``, ``CLUE_AGENT_COMPACT_KEEP_MESSAGES``.
    agent_context_window_tokens: int | None = Field(default=None, ge=1)
    agent_compact_trigger_fraction: float = Field(default=0.90, gt=0, lt=1)
    agent_compact_keep_fraction: float = Field(default=0.10, gt=0, lt=1)
    agent_compact_trigger_tokens: int = Field(default=170_000, ge=1)
    agent_compact_keep_messages: int = Field(default=6, ge=1)
    # Head-of-ABM chat turns resume the thread's last completed turn (append-only prompt).
    # Env: ``CLUE_HEAD_OF_ABM_CONTINUATION_ENABLED``.
    head_of_abm_continuation_enabled: bool = True
    # Wall clock per Head-of-ABM chat turn, seconds; 0 means no timeout. When set, the agent is
    # told to wrap up about three minutes before it. Env: ``CLUE_HEAD_OF_ABM_TURN_TIMEOUT_S``.
    head_of_abm_turn_timeout_s: float = Field(default=0.0, ge=0)
    # A Head-of-ABM turn or research job still running after this many seconds logs a warning,
    # flags its Langfuse trace and sends one Sentry warning (when Sentry is installed); 0 turns
    # the alert off. It never stops the turn. Env: ``CLUE_AGENT_LONG_TURN_ALERT_S``.
    agent_long_turn_alert_s: float = Field(default=3600.0, ge=0)

    # --- ARV2 R3 person agent (master plan §9 R3) ---------------------------------------------
    # Media items ONE person job may read (podcast episodes, conference talks, YouTube
    # appearances). A person is a much smaller media surface than an account, and each item costs
    # a transcription; 0 disables media for person jobs entirely.
    # Env: ``CLUE_ARV2_PERSON_MEDIA_MAX_ITEMS``.
    arv2_person_media_max_items: int = Field(default=3, ge=0)

    # --- ARV2 R4 verified account discovery (master plan §9 R4; spec §2–§4) -------------------
    # On by default (2026-10-04: no shipped feature is blocked behind a default-off switch). A
    # worker still composes the discovery handler only when ``CLUE_EXA_API_KEY`` is configured too,
    # so a deployment without the key runs no discovery. Env: ``CLUE_ARV2_DISCOVERY_ENABLED``.
    arv2_discovery_enabled: bool = True
    #: Exa Answer model for gate verification (``exa``, ``exa-pro``, ``exa-fast``).
    arv2_discovery_answer_model: str = "exa"
    #: Seconds between Websets polls while a discovery run is in flight (spec §3).
    arv2_discovery_poll_interval_s: float = Field(default=15.0, gt=0)
    #: Wall clock for one discovery SEARCH, seconds — a run makes its first search and then up to
    #: ``arv2_discovery_max_topups`` more, one after another.
    arv2_discovery_wall_s: int = Field(default=1800, ge=60)
    #: Websets bill 10 credits per all-green result; this is the plan's dollar rate per credit.
    arv2_discovery_websets_usd_per_credit: Decimal = Field(default=Decimal("0.00449"), ge=0)
    #: How many Exa Answer calls one discovery run may have in flight while verifying (spec
    #: 2026-09-12 §2). One semaphore serves both levels: candidates verify in a pool, and one
    #: candidate's gate questions are asked together. ``1`` reproduces the serial order the R4
    #: DB proof scripts by position. Env: ``CLUE_ARV2_DISCOVERY_VERIFY_CONCURRENCY``.
    arv2_discovery_verify_concurrency: int = Field(default=4, ge=1)
    #: How many top-up searches a discovery run may make after its first, each with the SAME brief
    #: the Head of ABM wrote, while it has shown fewer companies than asked (spec 2026-09-30 §4).
    #: ``3`` means at most four searches. Env: ``CLUE_ARV2_DISCOVERY_MAX_TOPUPS``.
    arv2_discovery_max_topups: int = Field(default=3, ge=0, le=15)
    #: Brandfetch **Logo API** client id — public by design (it rides in every ``<img src>``),
    #: so a setting, not a secret. Empty (the default) means no Brandfetch fallback: an account
    #: with no LinkedIn mark shows the frontend's placeholder. Founder ruling 2026-09-11: the
    #: Logo API only, never the Brand API. Env: ``CLUE_BRANDFETCH_CLIENT_ID``.
    brandfetch_client_id: str = ""

    # --- ARV2 onboarding lane (Track O; ARV2-ONBOARDING-PLAN.md §10) --------------------------
    # Routes ``POST /onboarding`` to the new fleet driver (O3). ON by default since 2026-09-12
    # (spec 2026-09-12-onboarding-v2-default): the Welcome flow's setting-up screen runs this
    # lane. Env: ``CLUE_ONBOARDING_V2_ENABLED``.
    onboarding_v2_enabled: bool = True
    # Exa Agent effort for the company-overview run (ARV2-COMPANY-OVERVIEW-CONTRACT.md §1).
    # Env: ``CLUE_ONBOARDING_OVERVIEW_EFFORT``.
    onboarding_overview_effort: str = "high"
    # Exa Agent effort for the customer-reviews run (plan §4.3).
    # Env: ``CLUE_ONBOARDING_REVIEWS_EFFORT``.
    onboarding_reviews_effort: str = "medium"
    # Exa Agent effort for each per-product research run (plan §4.4; ruling O-D2 — raise to
    # ``high`` per deployment if the product files read thin).
    # Env: ``CLUE_ONBOARDING_PRODUCT_EFFORT``.
    onboarding_product_effort: str = "medium"
    # When the reviews run happens (ruling O-D3: ``fast``). Env: ``CLUE_ONBOARDING_REVIEWS_PHASE``.
    onboarding_reviews_phase: Literal["fast", "background"] = "fast"
    # Cap on concurrent background per-product Exa Agent runs.
    # Env: ``CLUE_ONBOARDING_MAX_PARALLEL_RUNS``.
    onboarding_max_parallel_runs: int = Field(default=6, ge=1)
    # The governed ``exa_search_evidence@1`` tool the synthesis agent may call once per persona
    # role (ruling O-D6: on). Env: ``CLUE_ONBOARDING_PERSONA_EVIDENCE_ENABLED``.
    onboarding_persona_evidence_enabled: bool = True
    # Catalog identity ladder (O3 follow-up, founder ruling 2026-09-08): after the fingerprint and
    # exact-spelling stages, one batched model call per run decides "same offering or new" for the
    # leftovers, with each entry's official page as evidence; automatic merge only at high
    # confidence. Env: ``CLUE_ONBOARDING_CATALOG_RECONCILE_ENABLED``.
    onboarding_catalog_reconcile_enabled: bool = True
    # OpenRouter model for that call (validated 2026-09-08 on gpt-5-mini and grok-4.6; the small
    # one is faster and a fraction of a cent). Env: ``CLUE_ONBOARDING_RECONCILE_MODEL``.
    onboarding_reconcile_model: str = "openai/gpt-5-mini"

    # --- ARV2 lenient write gate and annotation checks (D1; master plan §2 items 2 and 6, §4) ---
    # The claim write gate stores instead of refusing: an unregistered key becomes a proposed field,
    # a schema miss is stored with ``schema_valid=false``, a missing source URL is stored with
    # ``source_missing``. False restores strict refusals. Env: ``CLUE_CLAIM_WRITE_LENIENT``.
    claim_write_lenient: bool = True
    # When "on", quoted spans are checked against cited claims and the verdict is recorded as a
    # marker; never a blocker. Env: ``CLUE_EVIDENCE_VERBATIM_CHECK``.
    evidence_verbatim_check: Literal["on", "off"] = "off"
    # When true, rows with no quote or no URL are purged by the compliance pass; when false they
    # are only marked ``unevidenced``. It cannot reach a provider-API record or the hooks claim:
    # those carry neither quote nor URL by design and rule 6 exempts them either way.
    # Env: ``CLUE_UNEVIDENCED_ROW_PURGE_ENABLED``.
    unevidenced_row_purge_enabled: bool = False
    # When "on", the interview records whether a typed value is entailed by the user's statement
    # as a marker; the value is never required to be a substring. Env:
    # ``CLUE_INTERVIEW_ENTAILMENT_CHECK``.
    interview_entailment_check: Literal["on", "off"] = "off"
    # The one default-on check: redact references to minors from a value and mark special-category
    # facts outreach_safe=false. It never drops a claim. Env: ``CLUE_SENSITIVITY_FLOOR_ENABLED``.
    sensitivity_floor_enabled: bool = True

    # --- ARV2 display layer (D2; master plan §7) -----------------------------------------------
    # OpenRouter model id for focused account reconciliation and the legacy section writer. Grok
    # 4.6 since 2026-09-29 (founder request; Muse Spark 1.3 from 2026-09-28, Luna before). Env:
    # ``CLUE_ARV2_DISPLAY_MODEL``.
    arv2_display_model: str = "x-ai/grok-4.6"
    # Per-section HTTP timeout. A page's sections run in parallel, so this bounds the first open.
    # Env: ``CLUE_ARV2_DISPLAY_TIMEOUT_S``.
    arv2_display_timeout_s: float = 240.0
    # How many sections of one page are in flight at once (one ProviderCaller each).
    # Env: ``CLUE_ARV2_DISPLAY_MAX_PARALLEL``.
    arv2_display_max_parallel: int = 30
    # The separate page writer (recipe 25+): one call writes an account's Overview + Insights or a
    # contact page, so it needs far longer than one section. The model is the research-narrative
    # role's (``RESEARCH_NARRATIVE_AGENT_MODEL`` / ``_EFFORT``), falling back to
    # ``arv2_display_model``. Env: ``CLUE_ARV2_PAGE_WRITER_TIMEOUT_S``.
    arv2_page_writer_timeout_s: float = 900.0
    # ``client.what_we_sell`` in the display prompt, until Track O's company-overview artifact
    # supplies it (D2 decision 7). Env: ``CLUE_ARV2_DISPLAY_CLIENT_PITCH``.
    arv2_display_client_pitch: str = (
        "AI-native ABM: account and committee research, personalised content, "
        "brand-aligned artifacts, scaled per account"
    )
    # D3 decision 10: an accounts screen whose display block is missing generates it during the
    # request (the first open waits). Off makes every read a pure projection — a page with no
    # stored block serves its honest empty state instead of calling a model.
    # Env: ``CLUE_ARV2_DISPLAY_GENERATE_ON_READ``.
    arv2_display_generate_on_read: bool = True
    # The fit-band cuts over the 0–1 ``account.scoring.fit`` score (D3 ruling S3: thresholds are
    # config, not code — a client tunes what "High" means without a deploy). ``>= high`` is High,
    # ``>= medium`` is Medium, below is Low; an unscored account has no band at all.
    # Env: ``CLUE_ARV2_FIT_HIGH_THRESHOLD``.
    arv2_fit_high_threshold: float = 0.70
    # Env: ``CLUE_ARV2_FIT_MEDIUM_THRESHOLD``.
    arv2_fit_medium_threshold: float = 0.40

    # --- Conversation naming (spec 2026-09-18-conversation-naming-design §4.8) ---------------
    # One cheap call names the chat (and, on the Home path, the project) once the first agent
    # reply exists. Off keeps the placeholders. Env: ``CLUE_CONVERSATION_NAMING_ENABLED``.
    conversation_naming_enabled: bool = True
    # OpenRouter model id for the naming call. Env: ``CLUE_CONVERSATION_NAMING_MODEL``.
    conversation_naming_model: str = "openai/gpt-5.6-luna"
    # The naming call's HTTP timeout. The turn never waits this long — the engine waits
    # ``NAMING_GRACE_S`` and lets a slower call finish detached (§4.1).
    # Env: ``CLUE_CONVERSATION_NAMING_TIMEOUT_S``.
    conversation_naming_timeout_s: float = 60.0

    # Part II D5 Round B production cutover for design agent turns (scene + website). This switch
    # owns only whether the detached fleet worker registers the ``design_job`` handler; the design
    # API always offers the work, and its own embedded worker (LUMEN_EMBEDDED_FLEET_WORKER) is
    # what drains it in development. Off by default because a platform worker without the design
    # app installed cannot execute a design turn — registering the handler there would claim work
    # it must then fail. Env: ``CLUE_DESIGN_RUNTIME_ENABLED``.
    design_runtime_enabled: bool = False
    # Staged until output-history erasure closure and explicit preference writes are validated.
    # Gates only production scene preference selection/resolution, not ordinary platform memory.
    # Env: ``CLUE_DESIGN_PREFERENCE_CONTEXT_ENABLED``.
    design_preference_context_enabled: bool = False
    # Part II D5 Round C: how often the stranded-design-work reaper sweeps, in seconds. Gated by
    # ``design_runtime_enabled`` (a deployment that does not drain design work must not re-offer
    # it); ``<= 0`` disables the sweep entirely, the ``storage_orphan_sweep_interval_s``
    # convention. Sized well above the fleet lease TTL and task-staleness window so a pass never
    # races a worker that is merely between heartbeats.
    # Env: ``CLUE_DESIGN_REAPER_INTERVAL_S``.
    design_reaper_interval_s: float = 300.0
    # Base URL of the design API (``lumen_api``) for the few platform surfaces that must reach it
    # as a SERVICE rather than through the ``clue_design`` DAL — today only the brand-kit
    # onboarding trigger, which enqueues a website ingestion through the design toolbelt's own
    # guarded route instead of writing design rows behind its back. ``None`` (the default) means
    # the platform makes no server-side design-API calls at all: the trigger logs that it is
    # unconfigured and does nothing, which is a posture, not an error. Env:
    # ``CLUE_DESIGN_API_BASE_URL``.
    design_api_base_url: str | None = None
    # Onboarding also offers ONE ad-assets harvest for the company's own LinkedIn ads, beside the
    # website ingestion and through the same trigger (auto ad ingestion, 2026-09-28): the most
    # recent static ads, up to ``brand_ad_assets_auto_max_creatives``, reading at most
    # ``brand_ad_assets_auto_max_pages`` ad-library pages (~25 ads and ~1 vendor credit each).
    # The design API must also run the ad lane (``LUMEN_BRAND_AD_ASSETS``); when it does not, the
    # route 404s and the offer is a logged, fail-soft skip. Env:
    # ``CLUE_BRAND_AD_ASSETS_AUTO_ONBOARD`` / ``_AUTO_MAX_CREATIVES`` / ``_AUTO_MAX_PAGES``.
    brand_ad_assets_auto_onboard: bool = True
    brand_ad_assets_auto_max_creatives: int = Field(default=50, ge=1)
    brand_ad_assets_auto_max_pages: int = Field(default=8, ge=1)
    # R9 requires a positive worst-case monetary reservation even when a subscription provider
    # reports credits while ``sumble_cents_per_credit`` is intentionally zero. This admission
    # floor is released after settlement and is never recorded as spend. It is policy, not an
    # invented provider price. Env: ``CLUE_ENTITY_RESEARCH_UNPRICED_RESERVATION_CENTS``.
    entity_research_unpriced_reservation_cents: Decimal = Field(default=Decimal(1), gt=0)
    # One process-wide provider permit policy is shared by account/contact jobs. Exact per-run and
    # per-job concurrency limits are still enforced separately by the R2/R9 substrate.
    # Env: ``CLUE_ENTITY_RESEARCH_PROVIDER_CONCURRENCY_LIMIT``.
    entity_research_provider_concurrency_limit: int = Field(default=30, ge=1, le=1024)
    # R5 structured Sumble actions retain the S1 per-request credit cap in addition to monetary
    # admission. The compiler still raises when a selected field set has a larger documented
    # bounded maximum. Env: ``CLUE_ENTITY_RESEARCH_SUMBLE_PROVIDER_CREDIT_CAP``.
    entity_research_sumble_provider_credit_cap: int = Field(default=25, ge=1, le=10_000)
    # Explicit canary workspace ids and deterministic workspace+surface percentage cohort.
    # Env: ``CLUE_AGENT_WORKSPACE_ALLOWLIST`` / ``CLUE_AGENT_CANARY_PERCENT``.
    #
    # ``NoDecode`` hands the raw environment string to the validator below instead of letting
    # pydantic-settings JSON-decode it first: its decode failure is a ``SettingsError`` raised
    # while *building* the settings object, so one malformed allowlist takes down every unrelated
    # setting with an error that names neither the accepted formats nor the fix. (Seen live: a
    # shell ``source .env`` strips the JSON string quotes, leaving ``[ws-a]``.)
    agent_workspace_allowlist: Annotated[tuple[str, ...], NoDecode] = ()
    # Every agent model call's fallback chain (founder ruling 2026-10-04): tried in order when the
    # primary fails before answering — an error, or no first chunk within
    # ``agent_first_token_timeout_s``. Comma-separated (or JSON) OpenRouter ids; blank = none.
    # Env: ``CLUE_AGENT_FALLBACK_MODELS``.
    agent_fallback_models: Annotated[tuple[str, ...], NoDecode] = (
        "x-ai/grok-4.7",
        "meta/muse-spark-1.3",
    )
    # The context window, in tokens, of every model the platform's agents run on — the primaries
    # AND the fallback chain above. Compaction sizes itself from it; a model listed here never
    # costs a network call. Only an unlisted model falls back to OpenRouter's public catalogue
    # (2026-10-05: a slow catalogue fetch froze a fleet worker for 105 s). A model added to the
    # agent model settings belongs here too. ``CLUE_AGENT_CONTEXT_WINDOW_TOKENS`` still overrides
    # every model. Env: ``CLUE_AGENT_MODEL_CONTEXT_WINDOWS`` (``model=tokens,...`` or JSON).
    agent_model_context_windows: Annotated[dict[str, Annotated[int, Field(ge=1)]], NoDecode] = {
        "x-ai/grok-4.6": 500_000,
        "x-ai/grok-4.7": 500_000,
        "meta/muse-spark-1.3": 1_048_576,
    }
    # Seconds a streamed agent model call may wait for its FIRST chunk before the next model is
    # tried (production 2026-10-04: grok-4.6 sent nothing for 300 s). 0 = no first-chunk deadline;
    # mid-answer pauses stay governed by LANGCHAIN_OPENAI_STREAM_CHUNK_TIMEOUT_S.
    # Env: ``CLUE_AGENT_FIRST_TOKEN_TIMEOUT_S``.
    agent_first_token_timeout_s: float = Field(default=120.0, ge=0)
    agent_canary_percent: int = Field(default=0, ge=0, le=100)
    # Absolute API-root ceiling for one governed account-agent plan. The prepared runner further
    # clamps this to the account's durable research budget when one exists.
    # Env: ``CLUE_AGENT_ACCOUNT_PLAN_BUDGET_LIMIT_MILLICENTS``.
    agent_account_plan_budget_limit_millicents: int = Field(default=1_000_000, ge=0)
    # Terminal isolated workspaces are retained briefly for operator inspection, then purged by
    # the C6.8 cleanup job. Zero is allowed for tests/immediate cleanup.
    # Env: ``CLUE_AGENT_WORKSPACE_RETENTION_S``.
    agent_workspace_retention_s: float = Field(default=86400.0, ge=0)
    # Periodic worker cadence. Non-positive disables scheduling without weakening the job itself.
    # Env: ``CLUE_AGENT_CLEANUP_INTERVAL_S``.
    agent_cleanup_interval_s: float = 3600.0

    # --- C7 structured research-view activation -------------------------------------------
    # Each externally reachable capability is independently default-off. Deployments can canary
    # read-only projection first, then enable mutations/evidence, cut production handoff over, and
    # expose the deprecated dossier aliases last. Rollback disables routes/handlers only; the
    # append-only receipts, snapshots, and history remain inert and readable after reactivation.
    # Env: ``CLUE_C7_RESEARCH_VIEW_READ_ENABLED``.
    c7_research_view_read_enabled: bool = False
    # Env: ``CLUE_C7_SNAPSHOT_COMPOSE_ENABLED``.
    c7_snapshot_compose_enabled: bool = False
    # Env: ``CLUE_C7_EVIDENCE_ACTIONS_ENABLED``.
    c7_evidence_actions_enabled: bool = False
    # Env: ``CLUE_C7_RECHECK_ENABLED``.
    c7_recheck_enabled: bool = False
    # Env: ``CLUE_C7_PRODUCTION_HANDOFF_ENABLED``.
    c7_production_handoff_enabled: bool = False
    # Env: ``CLUE_C7_LEGACY_DOSSIER_ALIAS_ENABLED``.
    c7_legacy_dossier_alias_enabled: bool = False
    # Developer-only admission for a future governed-vs-candidate diagnostic comparator. This
    # setting never weakens statement governance or exposes denied values through normal C7 APIs.
    # Env: ``CLUE_C7_GOVERNANCE_SHADOW_COMPARE_ENABLED``.
    c7_governance_shadow_compare_enabled: bool = False
    # Optional JSON array of workspace ids admitted after a global C7 capability is enabled.
    # Empty means no additional workspace restriction (useful for local/manual trials).
    # Env: ``CLUE_C7_WORKSPACE_CANARY_IDS``.
    c7_workspace_canary_ids: tuple[str, ...] = ()

    # --- FI-2 frontend-read layer (slice 1) -------------------------------------------------
    # One default-off gate over the whole ``/frontend/v1`` router — the workspace-scoped, Band-2
    # read surface the frontend's accounts flow binds to. Off means the routes are never
    # registered (a request 404s exactly as it does today) and this router's error envelope /
    # request-id handlers are never installed, so no existing surface changes shape. Same posture
    # as the C7 block above: activation is a deployment decision, rollback disables routes only.
    # Env: ``CLUE_FRONTEND_READ_ENABLED``.
    frontend_read_enabled: bool = False
    # Browser origins allowed to call this process cross-origin. Empty (the default) adds **no**
    # CORS middleware at all — same-origin only, which is what a Next.js proxy deployment wants;
    # a value opts the whole app into standard ``CORSMiddleware`` for exactly those origins. Read
    # only at app construction. ``NoDecode`` + the validator below accept a JSON array *or* a bare
    # comma-separated list, for the same shell-``source`` reason as the agent allowlist.
    # Env: ``CLUE_FRONTEND_CORS_ALLOW_ORIGINS``.
    frontend_cors_allow_origins: Annotated[tuple[str, ...], NoDecode] = ()
    # Authenticated, user-initiated professional-email acquisition for the Contacts table. This is
    # intentionally distinct from ``contact_channel_enrichment_enabled``: that switch owns C5's
    # stricter independently-validated delivery workflow, while this one exposes the AI Ark export
    # (founder ruling 2026-09-29: on by default, the same AI Ark path the research agents use)
    # without promoting ``contact_entity.verified_email``. A missing AI Ark key remains an honest
    # unavailable outcome. Budget controls do not stop this explicit user action; realized provider
    # units/cost are still recorded durably.
    # Env: ``CLUE_FRONTEND_CONTACT_EMAIL_LOOKUP_ENABLED`` /
    # ``CLUE_FRONTEND_CONTACT_EMAIL_POLL_AFTER_S``.
    frontend_contact_email_lookup_enabled: bool = True
    frontend_contact_email_poll_after_s: int = Field(default=5, ge=1, le=300)

    # --- FI Lane D production chat surface --------------------------------------------------
    # One default-off gate over the whole ``/api/v1`` chat router (REQ-21's thread shell today;
    # turns, gates, and the token stream in later slices). Off means the routes are never
    # registered and a request 404s exactly as it does today. Same posture as the two blocks
    # above: activation is a deployment decision, rollback disables routes only — the durable
    # ``agent_thread`` rows stay readable after reactivation.
    # Env: ``CLUE_CHAT_ENABLED``.
    chat_enabled: bool = False
    # The internal ids the **development** principal carries while Lane B's real authentication
    # (B2/B3) is in flight. They are Clue-owned — a ``platform_user.user_id`` and a
    # ``workspace_membership.membership_id`` — never a provider (Clerk) value, and they are
    # readable only when ``projections_auth_mode='local_header'``; a production process refuses
    # the dev principal outright rather than trusting these. Since the B1 join they name **real
    # rows**: ``clue_api.chat.dev_fixture.provision_dev_principal`` idempotently provisions them
    # through Lane B's own CRUD at startup and fails the process loudly when it cannot (contract
    # §4 — even a dev adapter resolves a real user/membership fixture from Postgres).
    # Env: ``CLUE_CHAT_DEV_PRINCIPAL_USER_ID`` / ``CLUE_CHAT_DEV_PRINCIPAL_MEMBERSHIP_ID``.
    chat_dev_principal_user_id: str = "usr_local_dev"
    chat_dev_principal_membership_id: str = "wsm_local_dev"
    # The one workspace the development principal is a member of. A membership grants access to a
    # single workspace (contract §3.3), so this cannot be derived from the request's tenant
    # selector: it is named up front and every other requested workspace is refused 403
    # ``WORKSPACE_FORBIDDEN`` by the router's existing principal/workspace re-check. Empty (the
    # default) means "no development principal is provisionable" — enabling the chat surface
    # without it fails at startup rather than serving an identity that owns no membership.
    # Env: ``CLUE_CHAT_DEV_PRINCIPAL_WORKSPACE_ID``.
    chat_dev_principal_workspace_id: str = ""

    # --- FI Lane D D3 turn streaming (charter §§3.2-3.6) -------------------------------------
    # Whether a production conversation turn streams. On by default *within* the chat surface,
    # which is itself default-off, so an unconfigured deployment is unchanged; switching it off
    # leaves turns fully functional and merely unobserved (the durable outcome never depends on
    # the stream). Env: ``CLUE_CHAT_TURN_STREAMING_ENABLED``.
    chat_turn_streaming_enabled: bool = True
    # The bounded micro-batching of §3.3(3). A batch may reduce frame count but may never wait for
    # model completion: the first delta of a part is always flushed immediately, and thereafter a
    # batch closes at whichever of these two bounds is reached first. Env:
    # ``CLUE_CHAT_TURN_STREAM_BATCH_MAX_CHARS`` / ``CLUE_CHAT_TURN_STREAM_BATCH_INTERVAL_S``.
    chat_turn_stream_batch_max_chars: int = Field(default=256, ge=1)
    chat_turn_stream_batch_interval_s: float = Field(default=0.05, ge=0.0)
    # How often the worker observes the durable stop-request table while a generation is running
    # (§3.5). This is the cancellation latency bound; ``0`` disables stop observation entirely.
    # Env: ``CLUE_CHAT_TURN_STOP_POLL_INTERVAL_S``.
    chat_turn_stop_poll_interval_s: float = 0.25
    # Chat attachments (spec 2026-09-18). Per-message ceilings the upload route and the
    # submission route both enforce, and the number of prior-turn images re-sent to the model
    # as image parts on every later turn of a thread (``0`` = no cap). Env:
    # ``CLUE_CHAT_ATTACHMENT_MAX_FILES`` / ``_MAX_TOTAL_BYTES`` / ``_IMAGE_MAX_BYTES`` /
    # ``_TEXT_MAX_BYTES`` / ``_HISTORY_IMAGES_MAX``.
    chat_attachment_max_files: int = Field(default=10, ge=1)
    chat_attachment_max_total_bytes: int = Field(default=150 * 1024 * 1024, ge=1)
    chat_attachment_image_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1)
    chat_attachment_text_max_bytes: int = Field(default=5 * 1024 * 1024, ge=1)
    chat_attachment_history_images_max: int = Field(default=20, ge=0)
    # Document attachments (spec 2026-09-19 §3.1): the per-file cap of the document family
    # (PDF, DOCX, PPTX, XLSX, CSV, JSON). Env: ``CLUE_CHAT_ATTACHMENT_DOCUMENT_MAX_BYTES``.
    chat_attachment_document_max_bytes: int = Field(default=25 * 1024 * 1024, ge=1)
    # The code sandbox (spec 2026-09-19 §3.4): on by default (founder, 2026-09-20) — one container
    # per run with these bounds. The image must exist on the worker host (`make sandbox-image`);
    # without it, or with the flag off, run_python refuses ``sandbox_unavailable`` and a binary
    # attachment is unreadable to the agent. Env: ``CLUE_SANDBOX_ENABLED`` /
    # ``_IMAGE`` / ``_TIMEOUT_S`` / ``_CPUS`` / ``_MEMORY_MB`` / ``_MAX_RUNS_PER_TURN`` /
    # ``_MAX_OUTPUT_BYTES``.
    sandbox_enabled: bool = True
    sandbox_image: str = "clue-agent-sandbox:latest"
    sandbox_timeout_s: float = Field(default=60.0, gt=0)
    sandbox_cpus: float = Field(default=1.0, gt=0)
    sandbox_memory_mb: int = Field(default=1024, ge=64)
    sandbox_max_runs_per_turn: int = Field(default=10, ge=1)
    sandbox_max_output_bytes: int = Field(default=1_048_576, ge=1024)
    # The explicit replay-retention policy of §3.3(7): how long a *terminal* turn's frames stay in
    # the outbox before the worker's sweep deletes them. Should be >= CLUE_SSE_REPLAY_HORIZON_S —
    # pruning inside the replay horizon promises a replay the table can no longer serve (still
    # correct, because the cursor then resets and the client re-fetches, just needlessly often).
    # A live turn is never pruned at any age. Env: ``CLUE_CHAT_TURN_EVENT_RETENTION_S``.
    chat_turn_event_retention_s: float = 86400.0  # 24h
    # Cadence of the worker's two chat sweeps: the turn-outbox retention prune, and the
    # stranded-dispatch self-heal (a thread whose queued submission lost its dispatch to a process
    # death between task-finalize and dispatch-next). ``0`` disables both.
    # Env: ``CLUE_CHAT_SWEEP_INTERVAL_S``.
    chat_sweep_interval_s: float = 60.0
    # How long a single-use *turn* stream token is valid for. Separate from the B4 run-stream TTL
    # because a turn stream is opened by a browser the instant a 202 lands, while a run stream may
    # be opened long after. Env: ``CLUE_CHAT_STREAM_TOKEN_TTL_S``.
    chat_stream_token_ttl_s: float = 300.0  # 5m
    # SSE poll cadence of the turn stream's live tail. The outbox is the buffer (§3.3(7)); a slow
    # or absent consumer never touches model execution. Env: ``CLUE_CHAT_STREAM_POLL_INTERVAL_S``.
    chat_stream_poll_interval_s: float = 0.25

    # --- FI Lane D "dev-lens" mini-slice (prompt/skill tuning; DEV-ONLY BY CONSTRUCTION) ------
    # Two developer lenses onto a turn. Both are refused at process start outside a dev/local
    # deployment by :meth:`_refuse_dev_lens_in_production` below — the same predicate the dev
    # principal and the ``local_header`` projections resolver are refused by — so the production
    # contract they would weaken cannot be reached by a configuration mistake, only by editing the
    # refusal itself.
    #
    # (1) What the ``reasoning`` part carries. ``summary`` (the default, and the ONLY value a
    # production process may hold) is charter §3.3's ratified contract byte for byte: the part is a
    # safe status surface — a round is running, it asked for N governed calls — and no provider
    # reasoning token reaches the wire. ``raw`` additionally asks the provider for whatever
    # reasoning trace it is willing to expose and streams it onto that same part, so a developer
    # tuning a prompt can see how the model reacted to it. What arrives is provider-dependent and
    # frequently a *summary of* rather than the actual private chain-of-thought; see
    # ``clue_gateway.agent_model._reasoning_request`` for the honest per-provider account.
    # Env: ``CLUE_CHAT_REASONING_TRACE_MODE``.
    chat_reasoning_trace_mode: Literal["summary", "raw"] = "summary"
    # Optional thinking budget requested alongside ``raw``. ``None`` (the default) asks for the
    # provider's own default depth. It is a *request*: a model with no extended-thinking mode
    # ignores it, and no platform behaviour depends on it being honoured.
    # Env: ``CLUE_CHAT_REASONING_THINKING_BUDGET_TOKENS``.
    chat_reasoning_thinking_budget_tokens: int | None = Field(default=None, ge=1)
    # (2) The turn-context inspector: four dev-only read routes under the chat surface that serve
    # the C6 receipts a turn already wrote (the seven-layer context bundle and its included bytes,
    # the model rounds, the authored/validated plan, the tool invocations and their refusals). It
    # adds no storage and writes nothing; it is dev-only because it hands one HTTP caller the exact
    # bytes that were put in front of a model, which is a debugging affordance and not a product
    # surface. Off means the routes are never registered and a request 404s.
    # Env: ``CLUE_CHAT_DEV_INSPECTOR_ENABLED``.
    chat_dev_inspector_enabled: bool = False
    # Cumulative byte budget one inspector response may spend hydrating content-addressed bodies.
    # Over-budget bodies come back as refs plus a ``budget`` truncation marker — never silently
    # shortened text. Env: ``CLUE_CHAT_DEV_INSPECTOR_BUDGET_BYTES``.
    chat_dev_inspector_budget_bytes: int = Field(default=512_000, ge=1)
    # --- Lane B authenticated principal ----------------------------------------------------
    # Provider authentication is an adapter choice; Clue-owned users/memberships remain the
    # authorization substrate in every mode. The local fixture adapter still resolves a real
    # ``auth_identity`` row and is construction-time forbidden in production.
    # Env: ``CLUE_AUTH_ENVIRONMENT`` / ``CLUE_AUTH_MODE``.
    auth_enabled: bool = False
    auth_environment: Literal["local", "test", "production"] | None = None
    auth_mode: Literal["local_fixture", "clerk"] = "local_fixture"
    # Clerk JWT verification metadata. No Clerk secret is required at the FastAPI edge: the
    # short-lived session JWT (Clerk's default session token — no JWT template, no audience
    # claim) is verified against the instance JWKS. All are deployment settings, not domain
    # identity. Env: ``CLUE_AUTH_CLERK_*``.
    auth_clerk_jwks_url: str | None = None
    auth_clerk_issuer: str | None = None
    auth_clerk_authorized_parties: Annotated[tuple[str, ...], NoDecode] = ()
    # Public frontend origin used for settings invitation links. Env: CLUE_APP_ORIGIN.
    app_origin: str = "http://localhost:3020"
    # FI-4 slice 1: gates POST /auth/v1/provision (self-serve workspace creation). Default-off
    # like every neighbouring write surface — an unconfigured deployment serves session reads
    # only; enabling requires an explicit operator decision because each valid provider session
    # can mint one workspace+brand. Env: ``CLUE_SELF_SERVE_PROVISIONING_ENABLED``.
    self_serve_provisioning_enabled: bool = True

    # --- Public pages: hostnames and delivery (custom-domain publishing spec 2026-09-17 §9) ---
    # The suffix every workspace's permanent system hostname ends in (`<label>.<suffix>`). The
    # registry rows are written under it, so it must match the rows a database holds; the page
    # origin and the backfill warn loudly when they do not. Dev stack: `pages.localhost`.
    # Env: ``CLUE_PAGES_SYSTEM_SUFFIX``.
    pages_system_suffix: str = "pages.cluehq.ai"
    # Scheme and optional port for public page URLs the design API mints (og:image, publish `url`).
    # Production: https and no port; dev stack: http + 8040. Env: ``CLUE_PAGES_PUBLIC_SCHEME`` /
    # ``CLUE_PAGES_PUBLIC_PORT`` (empty string = unset).
    pages_public_scheme: Literal["http", "https"] = "https"
    pages_public_port: int | None = None
    # Local development only: the page origin skips the edge-secret gate and reads the public
    # hostname from the Host header. The origin refuses to start with this on while
    # CLUE_PAGES_EDGE_SECRET is set, so the two can never both be live in a deployment.
    # Env: ``CLUE_PAGES_TRUST_HOST_HEADER``.
    pages_trust_host_header: bool = False
    # The port `python -m clue_page_origin.main` listens on when Railway's PORT is absent.
    # Env: ``CLUE_PAGES_ORIGIN_PORT``.
    pages_origin_port: int = Field(default=8040, gt=0, lt=65536)
    # The CNAME value a customer points their subdomain at (spec §3 item 4, §7.2). Normally the
    # Cloudflare for SaaS fallback-origin record in our zone. Env: ``CLUE_PAGES_CNAME_TARGET``.
    pages_cname_target: str = "pages.cluehq.ai"
    # The Cloudflare zone that holds our DNS and the SaaS custom hostnames (spec §7.7). None = the
    # custom-domain control plane is not configured (connect answers 503).
    # Env: ``CLUE_CLOUDFLARE_ZONE_ID``.
    cloudflare_zone_id: str | None = None

    # The OLD Stage-0 recon (scrape binder, ``/stage0/setup``, the STAGE0_RECON fleet handler and
    # the official-site crawl). Until 2026-09-12 it composed whenever provisioning was on, which
    # meant "provisioning on" = "old lane on" (ledger A4). It now composes only behind this flag,
    # default off, until section G of the ledger retires the code. Env:
    # ``CLUE_LEGACY_STAGE0_RECON_ENABLED``.
    legacy_stage0_recon_enabled: bool = False

    # --- Lane E E3 value-narrative synthesis ------------------------------------------------
    # One default-off gate over the on-completion positioning step (the M12.1 Positioner behind
    # the governed ``synthesize_value_narrative@1`` tool). Off means the fleet never *offers* a
    # finalized account job to it — no journal rows, no spend — and the tool, which still registers
    # everywhere so the C6 authority surface is identical in every process, refuses
    # ``value_narrative_not_composed``. Same posture as the C7 block above: activation is a
    # deployment decision, and rollback stops new narratives without touching the append-only
    # claims already written. Env: ``CLUE_VALUE_NARRATIVE_SYNTHESIS_ENABLED``.
    value_narrative_synthesis_enabled: bool = False

    # --- local Clue Trial canary ------------------------------------------------------------
    # The Sumble-only founder acceptance surface is never part of the default production app.
    # It must be enabled explicitly and binds to loopback by default. Env:
    # ``CLUE_TRIAL_ENABLED`` / ``CLUE_TRIAL_HOST`` / ``CLUE_TRIAL_PORT`` /
    # ``CLUE_TRIAL_ROOT``.
    trial_enabled: bool = False
    trial_host: str = "127.0.0.1"
    trial_port: int = Field(default=8010, ge=1, le=65535)
    trial_root: str = ".context/sumble-trials"

    # --- projections HTTP process ----------------------------------------------------------
    # Env: ``CLUE_PROJECTIONS_HOST`` / ``CLUE_PROJECTIONS_PORT``.
    projections_host: str = "127.0.0.1"
    projections_port: int = Field(default=8000, ge=1, le=65535)
    # Header tenancy is explicitly local/manual-test only; service auth must be wired before that
    # mode can be selected in production.
    # Env: ``CLUE_PROJECTIONS_AUTH_MODE``.
    projections_auth_mode: Literal["local_header", "authenticated_principal", "service"] = (
        "local_header"
    )

    # --- scrape backend (Phase B2.4, founder addition) ---
    # Which ScrapeBackend the tier-2 HTML→markdown adapter uses when none is injected:
    # ``firecrawl`` (the paid API, default) or ``scrapling`` (local, credit-free). Read only by
    # ``adapters.default_scrape_backend``. Env: ``CLUE_SCRAPE_BACKEND``.
    scrape_backend: Literal["firecrawl", "scrapling"] = "firecrawl"

    # --- orphan-blob sweep cadence (Phase B2 review-hardening; append-only per treaty §3.2) ---
    # How often the fleet worker process runs ``clue_storage.sweep_orphan_blobs`` in the background
    # (the orphan leg the retention sweep does not cover — an abandoned rolled-back upload leaves a
    # blob with no ``artifact`` row). ``0`` (or any non-positive value) disables the loop. Sized
    # well above any transaction lifetime; the sweep's own grace window is the actual race guard.
    # Env: ``CLUE_STORAGE_ORPHAN_SWEEP_INTERVAL_S``.
    storage_orphan_sweep_interval_s: float = 21600.0  # 6h

    # --- fleet run-start composition (PB-B4 slice 1; append-only per treaty §3.2) ---
    # LRU capacity of the ``ComposingRunDriver``'s per-``(workspace_id, icp_key, icp_version)``
    # ``PhaseHandlerRegistry`` + ``ProjectRun`` cache (D1: two concurrent runs with different ICPs
    # never fight over the DEEP/VERIFICATION slot — each drives its own composed registry). The
    # durable state (project_run / ledger / budget) is shared; only the cheap state-machine object
    # + its handler registry are cached, so a small window suffices. Env:
    # ``CLUE_COMPOSER_REGISTRY_CACHE_SIZE``.
    composer_registry_cache_size: int = 8
    # Whether the run-composition ``_default_gateway`` may build a canned-output ``StubGateway``
    # when the ``OPENROUTER_API_KEY`` secret is absent. Default False → a missing key is a
    # construction-time ``RuntimeError`` (a misconfigured production worker must NOT silently drive
    # runs on stub LLM output). CI/tests/scripts opt in explicitly.
    # Env: ``CLUE_GATEWAY_ALLOW_STUB``.
    gateway_allow_stub: bool = False

    # --- toolbelt A9 idempotency (PB-B4 slice 2; append-only per treaty §3.2 / D10) ---
    # Read-time freshness window of the ``tool_invocation`` idempotency record (D6): a keyed tool
    # invocation replays its stored response for this long; a reused key past the window is a fresh
    # invocation (its stale row is overwritten), and a reused key *within* the window with a changed
    # request body is an ``IdempotencyConflict``. Env: ``CLUE_TOOLBELT_IDEMPOTENCY_TTL_S``.
    toolbelt_idempotency_ttl_s: float = 86400.0  # 24h

    # --- treaty SSE (PB-B4 slice 3; append-only per treaty §3.2 / D10) ---
    # How far back the SSE surface will replay ``run_event`` rows for a reconnecting consumer
    # (``Last-Event-ID``). A cursor whose event is older than this window can no longer be replayed
    # gaplessly, so the surface emits ``stream.reset`` (the client re-fetches the projection) rather
    # than promise continuity. A read-time horizon (``created_at`` arithmetic), not a DB sweep. Env:
    # ``CLUE_SSE_REPLAY_HORIZON_S``.
    sse_replay_horizon_s: float = 86400.0  # 24h
    # TTL of a single-use SSE ``stream_token``: a minted token opens the ``…/events`` stream once
    # within this window, then is consumed (``used_at`` stamped). A reconnect re-mints. Env:
    # ``CLUE_SSE_STREAM_TOKEN_TTL_S``.
    sse_stream_token_ttl_s: float = 300.0  # 5m
    # Page size of one replay/backlog read (review F12 — honesty about the D8 "10k events" figure:
    # the live tail drains the remainder, and in replay-then-close mode this bounds one connect's
    # backlog). Env: ``CLUE_SSE_REPLAY_PAGE_LIMIT``.
    sse_replay_page_limit: int = 10_000

    # --- Stage-0 recon envelopes (FI-4 slice 3 close-out; append-only per treaty §3.2) --------
    # The two per-lane spend caps of the governed Stage-0 recon policy, made per-deployment
    # tunable so the founder ruling "onboarding is budget-unconstrained — envelopes must never
    # truncate onboarding research" (FI-onboarding-contract-gap-review §9, 2026-08-13) has an
    # actual mechanism instead of a code change. Read by
    # :func:`clue_config.stage0.stage0_policy_from_settings`, which the composition root
    # (``build_toolbelt``) uses to build the ``Stage0Policy`` the recon tools run under.
    #
    # The fast default is 25¢, not the frozen ``DEFAULT_STAGE0_POLICY``'s 5¢: at the default
    # ``CLUE_SCRAPE_BACKEND=firecrawl`` (~1¢/fetch) the full eleven-field Client-KB walk costs
    # ~11¢, so 5¢ released the user with the last checklist groups unreached ("stopped at the
    # research budget"). 25¢ covers the whole walk with headroom. ``DEFAULT_STAGE0_POLICY``
    # itself is unchanged (5/100) — it is the library default many tests pin; the *production*
    # default is this settings-derived one. Env: ``CLUE_STAGE0_FAST_BUDGET_CENTS`` /
    # ``CLUE_STAGE0_BACKGROUND_BUDGET_CENTS``.
    # ``gt=0``: a zero envelope would refuse the whole walk, and the ruling says an envelope must
    # never truncate onboarding — so a mistyped ``0`` fails at construction rather than silently
    # shipping an onboarding that researches nothing.
    stage0_fast_budget_cents: Decimal = Field(default=Decimal("25"), gt=0)
    stage0_background_budget_cents: Decimal = Field(default=Decimal("100"), gt=0)

    # --- durable Stage-0 official-site crawl (FI C6; default-off canary) -----------------
    # Shadow creates durable acquisition/checkpoint evidence for explicitly named workspaces but
    # leaves the historical field resolver and Client-KB release authoritative. C7 supplies the
    # checkpoint materializer required before authoritative mode can be composed.
    stage0_official_site_crawl_mode: Literal["off", "shadow", "authoritative"] = "off"
    stage0_official_site_crawl_workspace_allowlist: Annotated[tuple[str, ...], NoDecode] = ()
    stage0_page_fetcher: Literal["firecrawl", "scrapling"] = "firecrawl"
    stage0_crawl_max_depth: Literal[2] = 2
    stage0_crawl_fast_deadline_seconds: int = Field(default=40, ge=1, le=40)
    stage0_crawl_fast_page_ceiling: int = Field(default=12, ge=1)
    stage0_crawl_total_page_ceiling: int = Field(default=100, ge=1)
    stage0_crawl_worker_concurrency: int = Field(default=8, ge=1)
    stage0_crawl_per_host_concurrency: int = Field(default=3, ge=1)
    stage0_crawl_lease_ttl_seconds: int = Field(default=90, ge=3)
    stage0_crawl_heartbeat_seconds: int = Field(default=20, ge=1)
    stage0_crawl_request_timeout_seconds: int = Field(default=30, ge=1)
    stage0_crawl_max_response_bytes: int = Field(default=5_000_000, ge=1)
    stage0_crawl_allow_subdomains: bool = False
    stage0_crawl_robots_policy: Literal["respect"] = "respect"
    stage0_crawl_url_policy_version: Literal["official-site-url-v1"] = "official-site-url-v1"
    # C7 materialization policy. Model selection remains configuration-only; category/field calls
    # are bounded separately from acquisition workers and never share an open DB connection.
    stage0_extraction_model: str = "openai/gpt-5.6-luna"
    stage0_extraction_concurrency: int = Field(default=4, ge=1, le=16)

    # --- retention (design-integration Part II D8, ruling R-D8-4) ---------------------------
    # How often the fleet worker deletes spent ``stream_token`` rows (used or expired). ``<= 0``
    # disables the loop, the ``storage_orphan_sweep_interval_s`` convention. Default ON: both
    # consume statements require ``used_at IS NULL AND expires_at > now()``, so a swept row was
    # already unreadable by every code path and its deletion is unobservable — there is nothing to
    # canary. Env: ``CLUE_STREAM_TOKEN_SWEEP_INTERVAL_S``.
    stream_token_sweep_interval_s: float = 3600.0  # 1h
    # How often the fleet worker prunes a TERMINAL design run's PROGRESS ``run_event`` rows.
    # ``<= 0`` disables it, and it is the founder-facing switch: this sweep is the only one in the
    # platform that destroys durable run-visibility history, so it is **off until deliberately
    # turned on**. Its safety floors (never a terminal row, never a non-design subject, never a
    # non-terminal run, never inside the retention floor) are baked into the pruner's code, not
    # into this knob. Env: ``CLUE_DESIGN_RUN_EVENT_PRUNE_INTERVAL_S``.
    design_run_event_prune_interval_s: float = 0.0
    # How long a design run must have been terminal before its progress events may be pruned.
    # Clamped UP in code to a hard 7-day floor that strictly exceeds the design stream's 24h replay
    # horizon, so a within-horizon reconnect can never observe a hole; configuring less is logged
    # and ignored, never honoured. Env: ``CLUE_DESIGN_RUN_EVENT_RETENTION_S``.
    design_run_event_retention_s: float = 2_592_000.0  # 30d

    @field_validator("agent_context_window_tokens", mode="before")
    @classmethod
    def _blank_context_window_is_unknown(cls, value: Any) -> Any:
        """``CLUE_AGENT_CONTEXT_WINDOW_TOKENS=`` (blank, the documented default) means "use the
        model catalogue" — ``None`` — rather than an unparsable integer (env-parity rule)."""

        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("stage0_crawl_max_depth", mode="before")
    @classmethod
    def _coerce_stage0_crawl_max_depth(cls, value: Any) -> Any:
        """Coerce the env string form so the documented ``CLUE_STAGE0_CRAWL_MAX_DEPTH=2`` loads.

        The field is ``Literal[2]`` on purpose (the depth is pinned policy, not a knob), but
        pydantic will not coerce ``"2"`` from the environment into a literal int — so a
        deployment that copies ``.env.example`` verbatim (the 2026-08-31 env-parity rule makes
        that the norm) would crash at startup on the only value the field accepts. Any other
        value still fails validation loudly, exactly as before.
        """

        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        return value

    @model_validator(mode="before")
    @classmethod
    def _apply_product_path_overlay(cls, data: Any) -> Any:
        """Fill the §9 activation defaults for the integration product path.

        ``mode="before"`` sees the merged source dict (env + kwargs), so ``setdefault`` never
        overrides a value the deployment stated explicitly.
        """

        if isinstance(data, dict) and data.get("product_path") == "integration_pilot":
            for field, value in INTEGRATION_PILOT_OVERLAY.items():
                data.setdefault(field, value)
        return data

    @field_validator("pages_public_port", mode="before")
    @classmethod
    def _empty_port_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and value.strip() == "" else value

    @field_validator("agent_workspace_allowlist", mode="before")
    @classmethod
    def _parse_agent_workspace_allowlist(cls, value: Any) -> Any:
        """Accept a JSON array *or* a plain comma-separated list of workspace ids."""

        return _parse_string_list(value, _ALLOWLIST_FORMAT_ERROR)

    @field_validator("agent_fallback_models", mode="before")
    @classmethod
    def _parse_agent_fallback_models(cls, value: Any) -> Any:
        """Accept a JSON array *or* a plain comma-separated list of model ids."""

        return _parse_string_list(value, _FALLBACK_MODELS_FORMAT_ERROR)

    @field_validator("agent_model_context_windows", mode="before")
    @classmethod
    def _parse_agent_model_context_windows(cls, value: Any) -> Any:
        """Accept ``model=tokens,...`` *or* a JSON object of model ids to context windows."""

        return _parse_model_windows(value)

    @field_validator("stage0_official_site_crawl_workspace_allowlist", mode="before")
    @classmethod
    def _parse_official_site_workspace_allowlist(cls, value: Any) -> Any:
        return _parse_string_list(value, _OFFICIAL_SITE_ALLOWLIST_FORMAT_ERROR)

    @field_validator("frontend_cors_allow_origins", mode="before")
    @classmethod
    def _parse_frontend_cors_allow_origins(cls, value: Any) -> Any:
        """Accept a JSON array *or* a plain comma-separated list of browser origins, and refuse
        ``"*"`` outright — see :data:`_CORS_WILDCARD_ERROR`. The refusal lives here rather than at
        the middleware so a wildcard fails at process start, loudly, instead of silently widening
        an already-running deployment."""

        parsed = _parse_string_list(value, _CORS_ORIGINS_FORMAT_ERROR)
        if isinstance(parsed, list | tuple) and any(
            isinstance(item, str) and item.strip() == "*" for item in parsed
        ):
            raise ValueError(_CORS_WILDCARD_ERROR)
        return parsed

    @field_validator("auth_clerk_authorized_parties", mode="before")
    @classmethod
    def _parse_auth_clerk_authorized_parties(cls, value: Any) -> Any:
        return _parse_string_list(value, _AUTH_PARTIES_FORMAT_ERROR)

    @field_validator("auth_mode")
    @classmethod
    def _refuse_local_fixture_auth_in_production(cls, value: str, info: Any) -> str:
        if info.data.get("auth_environment") == "production" and value == "local_fixture":
            raise ValueError(
                "production must use Clerk authentication; local fixture auth is forbidden"
            )
        return value

    @model_validator(mode="after")
    def _validate_enabled_auth_environment(self) -> Settings:
        if self.auth_enabled and self.auth_environment is None:
            raise ValueError(
                "CLUE_AUTH_ENVIRONMENT must be set explicitly when CLUE_AUTH_ENABLED=true"
            )
        if self.auth_environment == "production" and self.auth_mode == "local_fixture":
            raise ValueError(
                "production must use Clerk authentication; local fixture auth is forbidden"
            )
        if self.auth_environment == "production" and self.projections_auth_mode == "local_header":
            raise ValueError(
                "production authentication forbids the local-header projections resolver"
            )
        if self.metrics_exporter == "otlp" and not self.metrics_otlp_endpoint:
            raise ValueError(
                "CLUE_METRICS_OTLP_ENDPOINT is required when CLUE_METRICS_EXPORTER=otlp"
            )
        if self.auth_environment == "production" and self.metrics_exporter != "otlp":
            raise ValueError(
                "production requires CLUE_METRICS_EXPORTER=otlp; the in-memory sink is not an "
                "exporter"
            )
        return self

    @model_validator(mode="after")
    def _validate_official_site_crawl_bounds(self) -> Settings:
        if self.stage0_crawl_fast_page_ceiling > self.stage0_crawl_total_page_ceiling:
            raise ValueError(
                "CLUE_STAGE0_CRAWL_FAST_PAGE_CEILING cannot exceed the total page ceiling"
            )
        if self.stage0_crawl_per_host_concurrency > self.stage0_crawl_worker_concurrency:
            raise ValueError(
                "CLUE_STAGE0_CRAWL_PER_HOST_CONCURRENCY cannot exceed worker concurrency"
            )
        if 2 * self.stage0_crawl_heartbeat_seconds >= self.stage0_crawl_lease_ttl_seconds:
            raise ValueError(
                "two Stage-0 crawl heartbeat intervals must fit strictly inside the lease TTL"
            )
        if (
            self.stage0_official_site_crawl_mode != "off"
            and not self.stage0_official_site_crawl_workspace_allowlist
        ):
            raise ValueError(
                "enabled Stage-0 official-site crawling requires an explicit workspace allowlist"
            )
        return self

    @model_validator(mode="after")
    def _refuse_dev_lens_in_production(self) -> Settings:
        """Refuse both dev-lens halves at process start in a production deployment.

        This is the whole "dev-only by construction" claim, and it is deliberately a *startup*
        refusal rather than a request-time check: a production process holding either value does
        not start, so there is no running deployment in which a later code path could be reached
        with the flag on. Same predicate, same place, and the same failure mode as the two refusals
        immediately above (production must not carry the local-fixture auth adapter or the
        local-header projections resolver).

        ``raw`` reasoning would put provider reasoning content on a wire the ratified contract says
        carries only a safe activity summary; the inspector would serve the exact assembled context
        bytes over HTTP. Neither is a product surface, so neither may exist outside a developer's
        own deployment.
        """

        if self.auth_environment != "production":
            return self
        if self.chat_reasoning_trace_mode != "summary":
            raise ValueError(
                "production forbids CLUE_CHAT_REASONING_TRACE_MODE=raw: what streams as reasoning "
                "is a safe activity summary, never provider reasoning content"
            )
        if self.chat_dev_inspector_enabled:
            raise ValueError(
                "production forbids CLUE_CHAT_DEV_INSPECTOR_ENABLED: the turn-context inspector "
                "serves the exact assembled context bytes and is a development lens only"
            )
        return self


def load_settings(**kwargs: Any) -> Settings:
    """Load settings from the environment (and optional ``.env``).

    Pass ``_env_file=None`` in tests so a developer's local ``.env`` is not picked up.
    """
    return Settings(**kwargs)
