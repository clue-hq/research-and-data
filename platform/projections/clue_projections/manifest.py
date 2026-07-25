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

from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.engine import RowMapping

from clue_core import ProjectPhase, ProjectRunId
from clue_db import ConnFactory
from clue_projections.dtos import ManifestNode, ManifestPin, RunManifest
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
        owner = (
            (
                await conn.execute(
                    text(
                        """
                        SELECT o.execution_id, e.recipe_revision_id
                        FROM project_run_execution_owner o
                        JOIN execution e ON e.id = o.execution_id
                        WHERE o.project_run_id = :run_id
                          AND o.workspace_id = :workspace_id
                        """
                    ),
                    {"run_id": project_run_id, "workspace_id": workspace_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        execution_nodes: Sequence[RowMapping] = ()
        execution_edges: Sequence[RowMapping] = ()
        execution_events: Sequence[RowMapping] = ()
        execution_pins: Sequence[RowMapping] = ()
        if owner is not None:
            execution_nodes = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT id, node_key, kind
                            FROM execution_node
                            WHERE execution_id = :execution_id
                            ORDER BY ordinal, node_key
                            """
                        ),
                        {"execution_id": owner["execution_id"]},
                    )
                )
                .mappings()
                .all()
            )
            execution_edges = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT from_node_id, to_node_id
                            FROM execution_edge
                            WHERE execution_id = :execution_id AND edge_kind = 'dependency'
                            ORDER BY from_node_id, to_node_id
                            """
                        ),
                        {"execution_id": owner["execution_id"]},
                    )
                )
                .mappings()
                .all()
            )
            execution_events = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT node_id, event_type
                            FROM execution_event
                            WHERE execution_id = :execution_id AND node_id IS NOT NULL
                            ORDER BY seq
                            """
                        ),
                        {"execution_id": owner["execution_id"]},
                    )
                )
                .mappings()
                .all()
            )
            execution_pins = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT p.node_id, p.kind, p.key, p.version, p.digest,
                                   p.resolved_status
                            FROM execution_pin p
                            WHERE p.execution_id = :execution_id
                            ORDER BY p.node_id NULLS FIRST, p.kind, p.key
                            """
                        ),
                        {"execution_id": owner["execution_id"]},
                    )
                )
                .mappings()
                .all()
            )

    nodes: list[ManifestNode] = []
    pins: list[ManifestPin] = []
    if owner is None:
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
    else:
        node_key_by_id = {str(row["id"]): str(row["node_key"]) for row in execution_nodes}
        dependencies: dict[str, list[str]] = defaultdict(list)
        for edge in execution_edges:
            dependencies[str(edge["to_node_id"])].append(node_key_by_id[str(edge["from_node_id"])])
        event_types: dict[str, list[str]] = defaultdict(list)
        for event in execution_events:
            event_types[str(event["node_id"])].append(str(event["event_type"]))

        def display_key(key: str) -> str:
            phase_keys = {phase.value for phase in ProjectPhase}
            return f"phase:{key}" if key in phase_keys else f"execution:{key}"

        for row in execution_nodes:
            node_id = str(row["id"])
            key = str(row["node_key"])
            history = event_types[node_id]
            if "node.completed" in history:
                status = "completed"
            elif "node.failed" in history:
                status = "failed"
            elif "node.blocked" in history or "gate.opened" in history:
                status = "awaiting_input"
            elif history and history[-1] == "node.started":
                status = "in_progress"
            elif "node.abandoned" in history:
                status = "paused"
            else:
                status = "pending"
            nodes.append(
                ManifestNode(
                    node_key=display_key(key),
                    depends_on=tuple(
                        display_key(dep) for dep in sorted(dependencies.get(node_id, ()))
                    ),
                    status=status,
                    account_scope=None,
                    gate=str(row["kind"]) == "gate" or "gate.opened" in history,
                    est_cost_cents=None,
                )
            )
        for row in execution_pins:
            raw_node_id = row["node_id"]
            pins.append(
                ManifestPin(
                    node_key=(
                        display_key(node_key_by_id[str(raw_node_id)])
                        if raw_node_id is not None
                        else None
                    ),
                    kind=str(row["kind"]),
                    key=str(row["key"]),
                    version=str(row["version"]) if row["version"] is not None else None,
                    digest=str(row["digest"]),
                    resolved_status=str(row["resolved_status"]),
                )
            )

    for account_row in account_runs:
        nodes.append(
            ManifestNode(
                node_key=f"account:{account_row.entity_id}",
                depends_on=(f"phase:{ProjectPhase.DEEP.value}",),
                status=account_row.status.value,
                account_scope=str(account_row.entity_id),
                gate=False,
                # DEFAULT_TIERING_CONFIG is the process default; per-workspace policy-as-data
                # est-cost bands are the follow-up (review F9c).
                est_cost_cents=str(DEFAULT_TIERING_CONFIG.band_cents(account_row.tier)),
            )
        )

    return RunManifest(
        project_run_id=project_run_id,
        workspace_id=workspace_id,
        current_phase=run.phase,
        run_status=run.status.value,
        execution_id=owner["execution_id"] if owner is not None else None,
        recipe_revision_id=owner["recipe_revision_id"] if owner is not None else None,
        nodes=tuple(nodes),
        pins=tuple(pins),
    )
