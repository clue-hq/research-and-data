"""The fleet identity of one ARV2 research task: its work id, its dedup key, its priority.

These three facts are shared by both ends of the lane and belong to neither: the **enqueuer**
(``account_research_launch``, and the committee step through it) offers the task, and the
**handler** (``account_research_driver``) drains it. They lived in the driver until R3, when the
driver started enqueueing the person jobs the committee step creates — which made the driver
import the launch that already imported the driver. One small module both may import is the
honest shape of a fact both own; the driver still re-exports the three names, so every existing
caller and test reads them where they always did.
"""

from __future__ import annotations

from uuid import UUID

from clue_fleet.lease import WorkId

__all__ = [
    "ARV2_ACCOUNT_DEDUP_PREFIX",
    "ARV2_ACCOUNT_TASK_PRIORITY",
    "arv2_account_work_id",
]

#: What an enqueuer puts in front of the job id, so an R2 task's dedup key cannot collide with
#: another kind's.
ARV2_ACCOUNT_DEDUP_PREFIX = "arv2-account-research:"

#: Account research outranks ordinary work but yields to onboarding (-150): a workspace that is
#: still being profiled has nothing to research against yet.
ARV2_ACCOUNT_TASK_PRIORITY = -100


def arv2_account_work_id(job_id: UUID) -> WorkId:
    """The job id IS the work id: one task per subject, and the identity is checked on arrival."""
    return WorkId(job_id)
