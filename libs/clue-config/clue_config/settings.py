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


def load_settings(**kwargs: Any) -> Settings:
    """Load settings from the environment (and optional ``.env``).

    Pass ``_env_file=None`` in tests so a developer's local ``.env`` is not picked up.
    """
    return Settings(**kwargs)
