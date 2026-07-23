"""The read-side projection DTOs (PB-B4 slice 3, D7 / REQ-11 / REQ-16 A4).

Plain frozen pydantic shapes the projection functions return and the ``clue_api`` HTTP surface
serves as schema-versioned JSON. They compose the existing M13.4 ``review`` panel projections
(``CampaignProgress`` / ``CostBurnDown`` / ``VerificationHealth``) + the additive
``core.CoverageReport`` — *reused, never re-derived* — plus the two genuinely-new projections this
slice owns: the readiness/coverage view and the A4 run-manifest.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from clue_core import CoverageReport, EntityId, ProjectPhase, ProjectRunId
from clue_research.review import CostBurnDown, PhaseProgress, VerificationHealth

# The read-side schema version served on the projection HTTP surface (mirrors the handoff API's
# ``HANDOFF_SCHEMA_VERSION`` header discipline — an additive bump keeps a pinned consumer ok).
PROJECTIONS_SCHEMA_VERSION = "1"


class RunOverview(BaseModel):
    """The run-overview projection (REQ-11): accounts-by-state, phase progress, burn-down, and
    verification health for one run, plus the **HANDOFF narrative gap marker** — so a
    gap-completed run (the composer's documented M12-integration gap, whose HANDOFF checkpoint
    carries ``narrative_emit_skipped``) is distinguishable from a truly-handed-off one by a UI/tool
    reading this projection (spec §2 slice-3 amendment / slice-1 review #10)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_run_id: ProjectRunId
    workspace_id: str
    current_phase: ProjectPhase
    run_status: str
    is_paused: bool = False
    is_terminal: bool = False
    awaiting_input: bool = False
    phases: tuple[PhaseProgress, ...] = ()
    accounts_total: int = 0
    accounts_by_state: dict[str, int] = {}
    burn_down: CostBurnDown | None = None
    verification_health: VerificationHealth | None = None
    coverage: CoverageReport | None = None
    handoff_reached: bool = False
    # THE slice-1 gap marker surfaced in the run projection (spec §2 amendment).
    narrative_emit_skipped: bool = False


class AccountProgress(BaseModel):
    """Per-account progress within a run — its research-run status/sub-phase, tier, accrued cost,
    and the filled-vs-planned aspect tally (from the M7.1 ``account_run`` plan + references index).
    Read-only (MVCC)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_run_id: ProjectRunId
    workspace_id: str
    account_entity_id: EntityId
    tier: str
    status: str
    sub_phase: str | None = None
    cost_cents: str = "0"
    aspects_planned: int = 0
    aspects_filled: int = 0
    claim_count: int = 0
    filled_aspects: tuple[str, ...] = ()


class AccountReadiness(BaseModel):
    """One account's readiness line in the run-readiness projection — filled vs planned aspects."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_entity_id: EntityId
    tier: str
    status: str
    aspects_planned: int = 0
    aspects_filled: int = 0


class Readiness(BaseModel):
    """The readiness/coverage projection (D7 "Surprise me"): what is known/filled vs planned per
    account, plus the run-level coverage-confidence band (reused from the M6.5 machinery via the
    ObservabilitySurface — never re-derived). ``coverage`` is ``None`` for a run with no discovery
    telemetry (e.g. an import-only campaign), surfaced honestly."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_run_id: ProjectRunId
    workspace_id: str
    coverage: CoverageReport | None = None
    aspects_planned_total: int = 0
    aspects_filled_total: int = 0
    accounts: tuple[AccountReadiness, ...] = ()


class ManifestNode(BaseModel):
    """One node of the A4 run-manifest DAG (REQ-16 A4). A **phase node** (``account_scope is
    None``) is a step of the fixed Recipe-#1 phase spine; an **account node**
    (``account_scope`` set) is one deep-researched account under the DEEP phase. ``depends_on`` is
    the node's upstream node key(s); ``gate`` marks a human-gate node (the tier checkpoint);
    ``est_cost_cents`` is a pre-spend prior (a static tiering-band prior for account nodes, ``None``
    for the setup/gate/output phases that spend nothing meaningful)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    node_key: str
    depends_on: tuple[str, ...] = ()
    status: str
    account_scope: str | None = None
    gate: bool = False
    est_cost_cents: str | None = None


class RunManifest(BaseModel):
    """The A4 run-manifest projection (REQ-16 A4): the run machine (phase spine) + the account
    graphs projected into a node DAG a UI renders and a client steers. Read-only; the mutating ops
    (pause/adjust) are a separate PATCH surface at the ``clue_api`` composition root."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_run_id: ProjectRunId
    workspace_id: str
    current_phase: ProjectPhase
    # The run row's lifecycle status (review F9a): a manifest-only UI must see a paused run —
    # node statuses alone cannot carry it (the current node still reads in_progress).
    run_status: str
    nodes: tuple[ManifestNode, ...] = ()
