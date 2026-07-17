"""Non-secret environment settings — model ids and other deploy-time knobs (M0.4).

:class:`Secrets` holds credentials (API keys, DSN). This module holds **non-secret** values read
from the environment via ``pydantic-settings`` — the same ``CLUE_`` prefix and ``.env`` file, but
plain strings rather than :class:`~pydantic.SecretStr`. Loaded once and injected; callers do not
read ``os.environ`` ad hoc.

The ICP synthesis model id (M5.2) is the first live setting here; it also feeds
:class:`~clue_research.config.gateway.GatewayConfig.synthesis_model` so ``get_config`` and
``synthesize_icps`` share one default.
"""

from __future__ import annotations

from typing import Any, Final

from pydantic_settings import BaseSettings, SettingsConfigDict

# Canonical fallback when ``CLUE_SYNTHESIS_MODEL`` is unset — keep in sync with GatewayConfig docs.
DEFAULT_SYNTHESIS_MODEL: Final = "anthropic/claude-opus-4-8"


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


def load_settings(**kwargs: Any) -> Settings:
    """Load settings from the environment (and optional ``.env``).

    Pass ``_env_file=None`` in tests so a developer's local ``.env`` is not picked up.
    """
    return Settings(**kwargs)
