"""Shared observability for Lumen's Python side.

The ONE module that configures structlog and builds formatters — every app
(apps/api, apps/agent_runtime, future apps) acquires loggers via
``obs.get_logger`` and configures once via ``obs.configure``. DRY logging: no
repeated setup blocks anywhere else.

    from py_lumen_obs import configure, get_logger, LogMode, bind_context, log_span

    configure(mode=LogMode.DEBUG)
    log = get_logger("lumen_agent.harness")
    bind_context(run_id="run_abc")
    with log_span("compile_dsl", logger=log, block="hero"):
        ...
"""
from __future__ import annotations

from .config import configure, get_logger
from .config_types import LogFormat, LogMode
from .context import (
    bind_context,
    bind_request_id,
    bind_role,
    bind_round,
    bind_run_id,
    bind_turn,
    bound_context,
    clear_context,
    unbind_context,
)
from .redact import is_secret_key, mask_blob, redact_processor, redact_value
from .spans import log_span
from .testing import LogCapture, capture_events, pytest_fixture

__all__ = [
    # configuration + logger acquisition
    "configure",
    "get_logger",
    "LogMode",
    "LogFormat",
    # context binding
    "bind_context",
    "clear_context",
    "unbind_context",
    "bound_context",
    "bind_run_id",
    "bind_turn",
    "bind_round",
    "bind_role",
    "bind_request_id",
    # spans
    "log_span",
    # redaction helpers (pure)
    "redact_processor",
    "redact_value",
    "is_secret_key",
    "mask_blob",
    # testing capture
    "capture_events",
    "LogCapture",
    "pytest_fixture",
]
