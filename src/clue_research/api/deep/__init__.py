"""``clue_research.api.deep`` — campaign-run deep orchestration (M8A).

The composition-layer package that sequences the M8 deep-research worker families per high-tier
account (``account → committee → contact``) under the M7 durable substrate — the milestone
that makes Pass B run end-to-end. It is the one home the import-linter independence contract permits
for work that co-composes ``durable`` + ``profiling`` (+ ``verification`` at M8A.6), since only the
``api`` composition root is import-exempt.

M8A.1 ships the trunk — :class:`AccountDeepOrchestrator` (the per-account sequence, resumable on the
M8A.0 ``account_run.sub_phase`` marker) + its injectable :class:`AccountRunIO` cursor seam. The
``DeepPhaseHandler`` (M8A.2), fan-out budget (M8A.3), exactly-once spend (M8A.4), the handoff
skeleton (M8A.5), and the composition root that injects the concretes (M8A.6) build against this
interface.
"""

from __future__ import annotations

from clue_research.api.deep.orchestrator import (
    AccountDeepOrchestrator,
    AccountDeepResult,
    DiscoverCommitteeFn,
    ProfileAccountFn,
    ProfileContactFn,
    deep_account_run_id,
)
from clue_research.api.deep.run_io import (
    AccountRunIO,
    DbAccountRunIO,
    DeepRunState,
)

__all__ = [
    # the per-account orchestrator trunk (M8A.1)
    "AccountDeepOrchestrator",
    "AccountDeepResult",
    "deep_account_run_id",
    "ProfileAccountFn",
    "DiscoverCommitteeFn",
    "ProfileContactFn",
    # the account_run persistence seam (M8A.1)
    "AccountRunIO",
    "DbAccountRunIO",
    "DeepRunState",
]
