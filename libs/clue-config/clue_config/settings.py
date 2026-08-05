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

from decimal import Decimal
from typing import Any, Final, Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Canonical fallback when ``CLUE_SYNTHESIS_MODEL`` is unset — keep in sync with GatewayConfig docs.
DEFAULT_SYNTHESIS_MODEL: Final = "openai/gpt-5.6-terra"


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

    # --- fleet worker (PB-B1; append-only per the Phase B treaty §3.2) ----------------------
    # How often an idle worker polls the task queue. Env: ``CLUE_FLEET_POLL_INTERVAL_S``.
    fleet_poll_interval_s: float = 1.0
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
    # Explicit canary workspace ids and deterministic workspace+surface percentage cohort.
    # Env: ``CLUE_AGENT_WORKSPACE_ALLOWLIST`` / ``CLUE_AGENT_CANARY_PERCENT``.
    agent_workspace_allowlist: tuple[str, ...] = ()
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
    projections_auth_mode: Literal["local_header", "service"] = "local_header"

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


def load_settings(**kwargs: Any) -> Settings:
    """Load settings from the environment (and optional ``.env``).

    Pass ``_env_file=None`` in tests so a developer's local ``.env`` is not picked up.
    """
    return Settings(**kwargs)
