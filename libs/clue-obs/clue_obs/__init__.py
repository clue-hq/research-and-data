"""Shared observability for the Clue platform backend (Doc R §4).

The ONE module that configures structlog and builds formatters — every
entrypoint (api, fleet worker, CLI/scripts) configures once via
``clue_obs.setup`` and acquires loggers via ``clue_obs.get_logger``. Direct
``logging.getLogger`` / ``print`` outside this package are lint-banned
(``tests/clue_obs/test_logging_discipline.py``).

    from clue_obs import setup, get_logger, LogMode, bind_context, log_span

    setup(mode=LogMode.DEBUG)
    log = get_logger("clue_fleet.worker")
    bind_context(workspace_id="ws_1", run_id="run_abc", actor="agent")
    with log_span("resolve_field", logger=log, field_key="client.industry"):
        ...

Ported from havana's ``py_lumen_obs`` (copy-port, no cross-repo imports),
adapted to the platform: ``CLUE_LOG_MODE`` / ``CLUE_LOG_FORMAT`` env knobs, the
workspace-era bound-context spine, and the DSAR ids-only rule for claim values
(``redact``).
"""

from __future__ import annotations

from clue_obs.config import get_logger, setup
from clue_obs.config_types import LogFormat, LogMode
from clue_obs.context import (
    bind_account,
    bind_actor,
    bind_context,
    bind_profile_version,
    bind_project,
    bind_request_id,
    bind_run_id,
    bind_workspace,
    bound_context,
    clear_context,
    unbind_context,
)
from clue_obs.critical_section import critical_section
from clue_obs.langfuse import (
    current_ids,
    guardrail,
    install_langfuse,
    langfuse_is_installed,
    observation,
    propagate_trace,
    shutdown_langfuse,
)
from clue_obs.langfuse import (
    event as langfuse_event,
)
from clue_obs.redact import is_claim_value_key, is_secret_key, mask_blob, redact_value
from clue_obs.sentry import capture, install_sentry, sentry_is_installed
from clue_obs.spans import log_span
from clue_obs.testing import LogCapture, capture_events

__all__ = [
    "LogCapture",
    "LogFormat",
    "LogMode",
    "bind_account",
    "bind_actor",
    "bind_context",
    "bind_profile_version",
    "bind_project",
    "bind_request_id",
    "bind_run_id",
    "bind_workspace",
    "bound_context",
    "capture",
    "capture_events",
    "clear_context",
    "critical_section",
    "current_ids",
    "get_logger",
    "guardrail",
    "install_langfuse",
    "install_sentry",
    "is_claim_value_key",
    "is_secret_key",
    "langfuse_event",
    "langfuse_is_installed",
    "log_span",
    "mask_blob",
    "observation",
    "propagate_trace",
    "redact_value",
    "sentry_is_installed",
    "setup",
    "shutdown_langfuse",
    "unbind_context",
]
