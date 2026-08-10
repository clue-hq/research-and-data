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

    # Temporary master switch for M9 runtime verification. False keeps the canonical VERIFICATION
    # phase in the durable state-machine sequence, but skips deterministic corroboration and
    # prevents the API composition roots from constructing the M9.3 faithfulness judge (including
    # the earlier reverse-profiling and toolbelt entailment call sites). Structural controls outside
    # that runtime pass (pre-spend authorization, born contact identity binding,
    # freshness/retention, and M10's use gate) remain active. Unverified tier-4 claims remain
    # excluded by the merge policy.
    # Env: ``CLUE_VERIFICATION_ENABLED``.
    verification_enabled: bool = True

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
    # M8D R10 production cutover for the separately launched account/contact ``create_agent()``
    # runs. This switch owns only the shared entity-research worker and launch/read tools; it does
    # not authorize a provider. Exa/Sumble/channel switches above remain independent hard gates.
    # Env: ``CLUE_ENTITY_RESEARCH_RUNTIME_ENABLED``.
    entity_research_runtime_enabled: bool = False
    # Part II D5 Round B production cutover for design agent turns (scene + website). This switch
    # owns only whether the detached fleet worker registers the ``design_job`` handler; the design
    # API always offers the work, and its own embedded worker (LUMEN_EMBEDDED_FLEET_WORKER) is
    # what drains it in development. Off by default because a platform worker without the design
    # app installed cannot execute a design turn — registering the handler there would claim work
    # it must then fail. Env: ``CLUE_DESIGN_RUNTIME_ENABLED``.
    design_runtime_enabled: bool = False
    # Part II D5 Round C: how often the stranded-design-work reaper sweeps, in seconds. Gated by
    # ``design_runtime_enabled`` (a deployment that does not drain design work must not re-offer
    # it); ``<= 0`` disables the sweep entirely, the ``storage_orphan_sweep_interval_s``
    # convention. Sized well above the fleet lease TTL and task-staleness window so a pass never
    # races a worker that is merely between heartbeats.
    # Env: ``CLUE_DESIGN_REAPER_INTERVAL_S``.
    design_reaper_interval_s: float = 300.0
    # R9 requires a positive worst-case monetary reservation even when a subscription provider
    # reports credits while ``sumble_cents_per_credit`` is intentionally zero. This admission
    # floor is released after settlement and is never recorded as spend. It is policy, not an
    # invented provider price. Env: ``CLUE_ENTITY_RESEARCH_UNPRICED_RESERVATION_CENTS``.
    entity_research_unpriced_reservation_cents: Decimal = Field(default=Decimal(1), gt=0)
    # One process-wide provider permit policy is shared by account/contact jobs. Exact per-run and
    # per-job concurrency limits are still enforced separately by the R2/R9 substrate.
    # Env: ``CLUE_ENTITY_RESEARCH_PROVIDER_CONCURRENCY_LIMIT``.
    entity_research_provider_concurrency_limit: int = Field(default=8, ge=1, le=1024)
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

    @field_validator("agent_workspace_allowlist", mode="before")
    @classmethod
    def _parse_agent_workspace_allowlist(cls, value: Any) -> Any:
        """Accept a JSON array *or* a plain comma-separated list of workspace ids."""

        return _parse_string_list(value, _ALLOWLIST_FORMAT_ERROR)

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
