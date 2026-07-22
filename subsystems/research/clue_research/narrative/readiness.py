"""The injected **readiness** seam the M12.3 handoff API consumes (M12 ↔ M7 campaign-run state).

A handoff is only servable once the account has passed verification (M9) and assembly (M12.2), and
the API must expose the campaign-run ``handoff`` phase so a content-layer consumer can *poll* rather
than guess (Doc C §4 — the ``handoff`` phase is the readiness gate). That state lives in the M7
``project_run`` / ``account_run`` tables, owned by the ``durable`` package — which ``narrative`` (a
worker under the import-linter independence contract) may NOT import. So readiness reaches the
service
through this **injected seam**; the production reader (over ``durable.get_project_run`` +
``account_run``) is built at the ``api`` composition root and injected, exactly like the M12.1
positioner's committee reader and the M12.2 assembler's committee reader.

The seam deliberately exposes only the **core** :class:`~clue_core.ProjectPhase`
(importable
by ``narrative``) plus pre-computed booleans / plain strings for the durable-internal statuses
(``ProjectRunStatus`` / ``AccountRunStatus`` live in ``durable.enums`` and are out of bounds here)
—
the production reader does the durable→bool mapping so ``narrative`` never learns those enum tokens.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from clue_core import EntityId, ProjectPhase, ProjectRunId


class RunReadiness(BaseModel):
    """The campaign-run's readiness, as the handoff API exposes it. ``phase`` is the current
    :class:`ProjectPhase` (``HANDOFF`` ⟹ the run reached the handoff gate); ``is_terminal`` is
    ``True`` once the run is ``COMPLETED``/``FAILED`` (no further handoffs will appear). A consumer
    polls this to decide whether to keep waiting or start pulling.

    ``icp_key`` / ``icp_version`` are the run's ICP segment coordinates (D5): the emit path
    assembles each ready account's handoff under *this* segment, reading them off the run rather
    than taking them as separate params."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_run_id: ProjectRunId
    workspace_id: str
    phase: ProjectPhase
    icp_key: str = ""
    icp_version: int = 1
    is_terminal: bool = False


class AccountReadiness(BaseModel):
    """One account's readiness within a run. ``is_ready`` is the production reader's verdict that
    the account finished deep profiling + verification (``account_run.status = DONE`` AND
    ``sub_phase = CONTACTS_COMPLETE`` — "M12-ready", per the ``AccountRunSubPhase`` docstring), so a
    handoff may be assembled/served. ``status`` / ``sub_phase`` are the durable tokens carried as
    plain strings for diagnostics (the API does not branch on them — it trusts ``is_ready``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_entity_id: EntityId
    is_ready: bool
    status: str | None = None
    sub_phase: str | None = None
    tier: str | None = None  # the account's research tier (M6 two-pass) — stamped on the handoff


@runtime_checkable
class HandoffReadinessReader(Protocol):
    """Read campaign-run + per-account readiness for the handoff API (the M12.3 ↔ M7 seam).

    Workspace-scoped on ``workspace_id`` (a workspace only sees its own runs). ``run_readiness``
    returns the
    run's phase (or ``None`` if the run does not exist / is not this tenant's); ``ready_accounts``
    returns the accounts in the run that have reached handoff-readiness (the emit path iterates
    them).
    The production impl (over ``durable``) is injected at the ``api`` root."""

    async def run_readiness(
        self, *, project_run_id: ProjectRunId, workspace_id: str
    ) -> RunReadiness | None: ...

    async def ready_accounts(
        self, *, project_run_id: ProjectRunId, workspace_id: str
    ) -> tuple[AccountReadiness, ...]: ...


class InMemoryHandoffReadinessReader:
    """A fixture :class:`HandoffReadinessReader` for M12.3 tests / local runs before the
    durable-backed
    reader is wired at ``api``. Backed by plain maps keyed on ``project_run_id``."""

    def __init__(
        self,
        *,
        runs: dict[ProjectRunId, RunReadiness] | None = None,
        ready: dict[ProjectRunId, tuple[AccountReadiness, ...]] | None = None,
    ) -> None:
        self._runs = runs or {}
        self._ready = ready or {}

    async def run_readiness(
        self, *, project_run_id: ProjectRunId, workspace_id: str
    ) -> RunReadiness | None:
        rr = self._runs.get(project_run_id)
        if rr is None or rr.workspace_id != workspace_id:
            return None
        return rr

    async def ready_accounts(
        self, *, project_run_id: ProjectRunId, workspace_id: str
    ) -> tuple[AccountReadiness, ...]:
        rr = self._runs.get(project_run_id)
        if rr is None or rr.workspace_id != workspace_id:
            return ()
        return self._ready.get(project_run_id, ())
