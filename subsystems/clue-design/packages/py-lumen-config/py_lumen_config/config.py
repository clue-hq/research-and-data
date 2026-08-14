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

from pydantic import field_validator
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

    # --- Image generation (image_provider) ---
    # Blank base_url/api_key → /assets/generate returns a clean 503.
    image_model_base_url: str = ""
    image_model_api_key: str = ""
    image_model_id: str = "default"
    image_model_provider_id: str = "image-gen-v1"
    image_model_timeout_s: float = 60.0
    image_model_max_retries: int = 2
    # Optional OpenRouter attribution headers (ranking only; harmless if unset).
    image_model_http_referer: str | None = None
    image_model_app_title: str | None = None

    # --- Brand-kit ingestion (lumen_ingestion) ---
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    lumen_ingestion_assist: bool = False
    lumen_ingestion_assist_model: str = "x-ai/grok-4.5"
    lumen_ingestion_vision: bool = False
    lumen_ingestion_vision_model: str = "x-ai/grok-4.5"
    lumen_ingestion_describe: bool = False
    lumen_ingestion_describe_model: str = "x-ai/grok-4.5"

    # --- Agent runtime (lumen_deepagent) ---
    # OpenRouter is the SOLE LLM gateway: the model id must be "openai:<id>" and
    # init_model errors without OpenRouter creds. Blank/unset base_url falls back
    # to the OpenRouter API URL in AgentRuntimeConfig.from_env.
    lumen_agent_model: str = "openai:x-ai/grok-4.5"
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
        "lumen_agent_provider_sort",
        "lumen_agent_llm_timeout_s",
        "lumen_agent_model_orchestrator",
        "lumen_agent_model_author",
        "lumen_agent_model_reviewer",
        "lumen_agent_max_tokens",
        "anthropic_api_key",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        """`VAR=` in a .env file means unset, matching the old `.strip() or None`."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("lumen_agent_reasoning")
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
