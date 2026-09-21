"""The fleet identity of one ARV2 research task: its work id, its dedup key, its priority.

These three facts are shared by both ends of the lane and belong to neither: the **enqueuer**
(``account_research_launch``, and the committee step through it) offers the task, and the
**handler** (``account_research_driver``) drains it. They lived in the driver until R3, when the
driver started enqueueing the person jobs the committee step creates — which made the driver
import the launch that already imported the driver. One small module both may import is the
honest shape of a fact both own; the driver still re-exports the three names, so every existing
caller and test reads them where they always did.

R4's discovery task has the same three facts and lives here for the same reason: the discovery
launch offers it and the discovery driver drains it, and neither may import the other.
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

from clue_fleet.lease import WorkId

__all__ = [
    "ARV2_ACCOUNT_DEDUP_PREFIX",
    "ARV2_ACCOUNT_TASK_PRIORITY",
    "ARV2_DISCOVERY_DEDUP_PREFIX",
    "ARV2_DISCOVERY_TASK_PRIORITY",
    "ARV2_DISPLAY_DEDUP_PREFIX",
    "ARV2_DISPLAY_TASK_PRIORITY",
    "arv2_account_work_id",
    "arv2_discovery_work_id",
    "arv2_display_work_id",
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


#: R4's prefix, so a discovery run's dedup key cannot collide with a research job's.
ARV2_DISCOVERY_DEDUP_PREFIX = "arv2-discovery:"

#: The fleet orders by ASCENDING priority — the lower number is the more urgent task — so a
#: discovery run at -90 outranks ordinary work but **yields to account research** at -100. That is
#: the right way round: research is work a human already approved on named accounts, while
#: discovery is looking for accounts nobody has picked yet. It still outranks ordinary work
#: because a run holding a paid-for webset should not sit behind a queue of background chores.
ARV2_DISCOVERY_TASK_PRIORITY = -90


def arv2_discovery_work_id(run_id: UUID) -> WorkId:
    """The run id IS the work id: one task per discovery run, checked against the row on arrival."""
    return WorkId(run_id)


#: The display page's prefix, so a page task's dedup key cannot collide with a research job's.
ARV2_DISPLAY_DEDUP_PREFIX = "arv2-display-page:"

#: A page write yields to research (-100) and discovery (-90): both produce the claims a page is
#: written from, so a page waiting behind them is written from more, not less. It still outranks
#: ordinary work (0) because a person is looking at the blank section it fills.
ARV2_DISPLAY_TASK_PRIORITY = -80


def arv2_display_work_id(subject_kind: str, subject_id: str, page: str) -> WorkId:
    """One work id per (subject, page): the same page offered twice is one task, whoever offers
    it."""
    name = f"clue:arv2-display-page:{subject_kind}:{subject_id}:{page}"
    return WorkId(uuid5(NAMESPACE_URL, name))
