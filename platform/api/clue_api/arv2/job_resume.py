"""Resume or restart a stopped ARV2 research job.

Spec: docs/superpowers/specs/2026-10-14-arv2-research-job-resume-design.md. One identity function
(§3.2), one restart signal, and one audited resume operation (§3.5) that the developer script
(§3.6) and the admin endpoints (§3.7) share.
"""

from __future__ import annotations

from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

RestartReason = Literal["instructions_changed", "context_changed_before_start"]


def research_execution_id(
    job_id: UUID, restart_count: int = 0, unit_key: str | None = None
) -> UUID:
    """The execution a research job's conversation runs under.

    Restart 0 is the id every job had before restarts existed, so existing jobs keep their saved
    state. A reconciliation unit keeps its own id whatever the restart count: only the job's main
    conversation moves on a restart.
    """
    if restart_count < 0:
        raise ValueError("a restart count is never negative")
    if unit_key:
        return uuid5(NAMESPACE_URL, f"research-quality:{job_id}:{unit_key}")
    if restart_count == 0:
        return uuid5(NAMESPACE_URL, f"research-quality:{job_id}")
    return uuid5(NAMESPACE_URL, f"research-quality:{job_id}:restart:{restart_count}")


class ResearchRestartRequired(RuntimeError):
    """The job's saved conversation cannot be continued; the driver gives it a fresh one."""

    def __init__(self, reason: RestartReason) -> None:
        super().__init__(f"research job needs a fresh conversation: {reason}")
        self.reason: RestartReason = reason
