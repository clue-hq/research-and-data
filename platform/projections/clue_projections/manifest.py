"""The A4 run-manifest projection + manifest-op validation (PB-B4 slice 3, D7 / REQ-16 A4).

The manifest projects the run machine (the fixed Recipe-#1 phase spine) **and** the per-account
deep graphs into one node DAG a UI renders and a client steers:

* **phase nodes** — one per :class:`~clue_core.ProjectPhase` in canonical order, chained
  ``depends_on`` the previous phase; ``status`` from the durable checkpoint (or ``in_progress`` for
  the run's current phase, ``pending`` otherwise); ``gate=True`` on the human ``tier_checkpoint``.
* **account nodes** — one per ``account_run`` under the DEEP phase; ``status`` from the account run
  row; ``est_cost_cents`` a static tiering-band prior for the account's tier.

Read-only (MVCC). The **mutating** side — ``PATCH …/manifest`` ops — is a separate surface at the
``clue_api`` composition root; this module only owns the *projection* and the pure **op-validation**
(:func:`validate_manifest_op`): the run machine has real semantics today only for pause / resume /
adjust, so any other op is rejected ``422`` with a machine-readable reason (pre-mortem #2 — never a
silent no-op accept). The accepted-op → capability map (:data:`MANIFEST_OP_TOOLS`) is the single
source of truth both the validator and the ``clue_api`` executor read, so they cannot drift.
"""

from __future__ import annotations

from clue_core import ProjectPhase, ProjectRunId
from clue_db import ConnFactory
from clue_projections.dtos import ManifestNode, RunManifest
from clue_research.discovery_scoring.tiering import DEFAULT_TIERING_CONFIG
from clue_research.durable import get_checkpoint, get_project_run, list_account_runs

# The accepted manifest ops with real run-machine semantics today, mapped to the slice-2 toolbelt
# capability the ``clue_api`` executor invokes. Everything NOT in this map is rejected 422 by
# :func:`validate_manifest_op` (D7 — ops accepted only where the current machine has real
# semantics: pause / adjust). One source of truth so the validator and the executor never drift.
MANIFEST_OP_TOOLS: dict[str, str] = {
    "pause": "pause_run",
    "resume": "resume_run",
    "adjust": "adjust_budget",
}

# The machine-readable rejection code for an op with no real semantics on the current machine.
UNSUPPORTED_OP = "unsupported_op"


def validate_manifest_op(op: str) -> str | None:
    """Return ``None`` if ``op`` is an accepted manifest op (has real run-machine semantics today),
    else the machine-readable reason code (:data:`UNSUPPORTED_OP`) — the assertion surface for the
    ``PATCH …/manifest`` 422 body. Pure; no I/O."""
    return None if op in MANIFEST_OP_TOOLS else UNSUPPORTED_OP


def _phase_node(
    phase: ProjectPhase,
    prev: ProjectPhase | None,
    *,
    status: str,
) -> ManifestNode:
    return ManifestNode(
        node_key=f"phase:{phase.value}",
        depends_on=(f"phase:{prev.value}",) if prev is not None else (),
        status=status,
        account_scope=None,
        gate=phase == ProjectPhase.TIER_CHECKPOINT,
        est_cost_cents=None,
    )


async def run_manifest(
    *,
    conn_factory: ConnFactory,
    project_run_id: ProjectRunId,
    workspace_id: str,
) -> RunManifest | None:
    """The A4 run-manifest projection, or ``None`` for a missing / cross-tenant run (fail-closed —
    a cross-tenant id is indistinguishable from absent). Read-only (MVCC)."""
    async with conn_factory() as conn:
        run = await get_project_run(conn, project_run_id)
        if run is None or run.workspace_id != workspace_id:
            return None
        checkpoints = {
            phase: await get_checkpoint(conn, project_run_id, phase) for phase in ProjectPhase
        }
        account_runs = await list_account_runs(conn, project_run_id)

    nodes: list[ManifestNode] = []
    prev: ProjectPhase | None = None
    for phase in ProjectPhase:
        cp = checkpoints[phase]
        if cp is not None:
            status = cp.status.value
        elif phase == run.phase:
            status = "in_progress"
        else:
            status = "pending"
        nodes.append(_phase_node(phase, prev, status=status))
        prev = phase

    for row in account_runs:
        nodes.append(
            ManifestNode(
                node_key=f"account:{row.entity_id}",
                depends_on=(f"phase:{ProjectPhase.DEEP.value}",),
                status=row.status.value,
                account_scope=str(row.entity_id),
                gate=False,
                est_cost_cents=str(DEFAULT_TIERING_CONFIG.band_cents(row.tier)),
            )
        )

    return RunManifest(
        project_run_id=project_run_id,
        workspace_id=workspace_id,
        current_phase=run.phase,
        nodes=tuple(nodes),
    )
