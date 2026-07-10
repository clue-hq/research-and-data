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

# py_lumen_config/config.py -> parents[0]=py_lumen_config, parents[1]=repo root
_REPO_ROOT = Path(__file__).resolve().parents[1]
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
    lumen_api_database_path: Path = Path("apps/api/lumen-api.sqlite3")
    lumen_api_cors_origins: str = "http://127.0.0.1:3000,http://localhost:3000"
    lumen_asset_store_root: Path | None = None  # None → <database dir>/asset-store
    lumen_asset_max_bytes: int = 10 * 1024 * 1024
    # Curated font-library manifest (Track B). Generated + checked in by
    # scripts/provision_font_library.py; missing file → library disabled.
    lumen_font_library_manifest_path: Path = Path("apps/api/font-library/manifest.json")
    lumen_log_level: str = "INFO"  # resolved leniently: unknown names fall back to INFO
    # Prebuilt lumen-api-helper binary; None → `cargo run -p lumen-api-helper`.
    lumen_core_helper: str | None = None

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
    lumen_agent_trace_dir: Path | None = None  # None → <repo root>/.lumen-runs
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
    # ("low" | "medium" | "high"). Unset/blank → no reasoning field on the
    # request (provider default: no extended thinking). Applied in init_model
    # for whatever model id is configured — one mechanism for all models.
    lumen_agent_reasoning: str | None = None
    # Read by langchain directly from os.environ; declared here for visibility.
    anthropic_api_key: str | None = None

    @field_validator(
        "lumen_core_helper",
        "image_model_http_referer",
        "image_model_app_title",
        "lumen_agent_trace_dir",
        "lumen_agent_asset_store",
        "lumen_agent_base_url",
        "lumen_agent_api_key",
        "lumen_agent_reasoning",
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
        """LUMEN_ASSET_STORE_ROOT if set, else asset-store beside the database."""
        return self.lumen_asset_store_root or self.lumen_api_database_path.parent / "asset-store"

    def image_model_configured(self) -> bool:
        return bool(self.image_model_base_url.strip() and self.image_model_api_key.strip())


# Singleton instance — import this from anywhere:
#   from py_lumen_config import settings
settings = Settings()
