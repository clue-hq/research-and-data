"""The expiry job, held to the test's own chats (fix pass 2, review area 3 M-3).

``AgentWorkspaceRetentionJob.run_once`` sweeps every cold chat in the database, as it must in
production. The DB tests share one test database, so an unscoped pass both *saw* other tests'
chats — an exact ``chats_checked`` was then wrong whenever anything else was cold — and *acted*
on them: a pass with a zero-second window expired the raw and working files of every chat in the
database, including those of tests running at the same moment.

This subclass runs the real candidate scan, paging and keyset included, and drops only the chats
outside the test's own workspaces before the job looks at them. Nothing the job does to a chat it
keeps is changed. It lives in the tests, so production keeps sweeping everything.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Collection
from datetime import datetime
from typing import Any

from clue_api.agent_workspace_retention import AgentWorkspaceRetentionJob


class ScopedRetentionJob(AgentWorkspaceRetentionJob):
    """The real job, sweeping only the chats of ``workspaces``."""

    def __init__(self, *, workspaces: Collection[str], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._workspaces = frozenset(workspaces)

    async def _candidates(self, *, cutoff: datetime) -> AsyncIterator[Any]:
        async for chat in super()._candidates(cutoff=cutoff):
            if chat.workspace_id in self._workspaces:
                yield chat
