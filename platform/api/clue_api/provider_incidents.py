"""Provider incidents — re-exported from their shared home, :mod:`clue_spend.incidents`.

The recorder moved to the spend library on 2026-10-31 (design
``docs/superpowers/specs/2026-10-31-provider-credit-and-key-alerts-design.md`` §6.2) so the design
subsystem, which may not import ``clue_api``, records through the same code. Every name the
platform's writers, readers and tests used stays importable from this address.
"""

from __future__ import annotations

from clue_spend.incidents import (  # noqa: F401
    _CLOSE,
    _INSERT,
    _SELECT_ONE,
    FAILURE_THRESHOLD,
    FAILURE_WINDOW,
    OpenIncident,
    incident_sentence,
    open_incidents,
    provider_display,
    reason_words,
    record_failure,
    record_success,
)

__all__ = [
    "FAILURE_THRESHOLD",
    "FAILURE_WINDOW",
    "OpenIncident",
    "incident_sentence",
    "open_incidents",
    "provider_display",
    "reason_words",
    "record_failure",
    "record_success",
]
