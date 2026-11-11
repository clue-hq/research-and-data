"""What happened to each provider call a search job made, so a failure never reads as "nothing".

A job that runs several searches on several sources keeps every answer it got and counts every call
that failed. Its state is then said plainly: ``complete`` when every call answered, ``partial`` when
some failed (what the others found is kept), ``unavailable`` when none answered. A configuration
note (a key not set, a source stopped earlier in the job) is told to the agent but is not a failure:
asking again would not change it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

SearchState = Literal["complete", "partial", "unavailable"]


class SourceStopped(Exception):
    """A paid source refused to sell (out of credit, key refused): stop asking it in this job."""

    def __init__(self, provider: str, reason: str) -> None:
        super().__init__(f"{provider} stopped: {reason}")
        self.provider = provider
        self.reason = reason


@dataclass
class Tally:
    gaps: list[str] = field(default_factory=list)
    answered: int = 0
    failed: int = 0
    #: Sources that stopped selling during the job, with their reason, for the job to latch.
    stopped: dict[str, str] = field(default_factory=dict)

    def answer(self) -> None:
        self.answered += 1

    def fail(self, gap: str) -> None:
        self.failed += 1
        self.gaps.append(gap)

    def note(self, gap: str) -> None:
        self.gaps.append(gap)

    def stop(self, provider: str, reason: str, gap: str) -> None:
        self.stopped.setdefault(provider, reason)
        self.fail(gap)

    @property
    def state(self) -> SearchState:
        if self.answered == 0:
            return "unavailable"
        return "partial" if self.failed else "complete"
