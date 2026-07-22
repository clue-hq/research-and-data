"""Read side — run views, the A4 run-manifest, readiness/coverage, and the SSE replay planner.

``clue_projections`` is the platform's **read projection** package (Doc R R2 / PB-B4 slice 3, D7 /
REQ-11 / REQ-16 A4). It composes the existing read surfaces — the M13.4 ``review``
:class:`~clue_research.review.ObservabilitySurface` panels + the durable ``project_run`` /
``account_run`` / ``run_event`` read helpers — into the client-facing projections a UI/tool renders,
and owns the two genuinely-new views this slice adds: the A4 run-manifest DAG and the
readiness/coverage projection.

**Read-only by construction.** Every function here issues *no writes* (the MVCC-only discipline — a
projection read during a driving worker never mutates the domain). The two write surfaces this read
side pairs with — the ``run_event`` **emitter** and the manifest **PATCH ops** — live at the
``clue_api`` composition root (writes belong to the root), never in this package.

**Import posture (machine-enforced).** ``clue_projections`` imports only the ``clue_research`` read
surfaces (``review`` / ``durable`` read helpers / ``discovery_scoring`` config) + the shared base
(``core`` / ``db``) — **never** toolbelt / agents / fleet / api / memory / content / gateway / lock.
The concrete durable-backed readers are built once at the ``clue_api`` root and injected here as an
``ObservabilitySurface`` (reused, not duplicated).
"""

from __future__ import annotations

from clue_projections.dtos import (
    PROJECTIONS_SCHEMA_VERSION,
    AccountProgress,
    AccountReadiness,
    ManifestNode,
    Readiness,
    RunManifest,
    RunOverview,
)
from clue_projections.events import ReplayPlan, plan_replay
from clue_projections.manifest import (
    MANIFEST_OP_TOOLS,
    UNSUPPORTED_OP,
    run_manifest,
    validate_manifest_op,
)
from clue_projections.run_views import account_progress, run_overview, run_readiness

__all__ = [
    # schema version
    "PROJECTIONS_SCHEMA_VERSION",
    # DTOs
    "RunOverview",
    "AccountProgress",
    "AccountReadiness",
    "Readiness",
    "RunManifest",
    "ManifestNode",
    # run views
    "run_overview",
    "account_progress",
    "run_readiness",
    # manifest
    "run_manifest",
    "validate_manifest_op",
    "MANIFEST_OP_TOOLS",
    "UNSUPPORTED_OP",
    # SSE replay planning
    "plan_replay",
    "ReplayPlan",
]
