"""Row transitions of the onboarding substrate (O1 tables; ARV2-ONBOARDING-PLAN.md §3).

One function per transition, each honouring the CHECKs the migration installed:
``*_finished_when_terminal`` is biconditional (status and ``finished_at`` move together),
``onboarding_step_failure_pair`` allows a ``failure_code`` only on ``failed`` — and *requires* one
there, so a caller that fails a step without naming a reason gets ``unspecified`` rather than an
IntegrityError on the containment path — and the step ↔ document FK cycle is written
step → document → UPDATE step. Nothing here calls a provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

__all__ = [
    "DocumentRow",
    "RunStatus",
    "StepStatus",
    "create_persona_run",
    "create_run",
    "fail_document",
    "fail_run",
    "finish_run",
    "finish_step",
    "list_documents",
    "mark_run_running",
    "open_document",
    "open_persona_run",
    "publish_document",
    "read_current_run",
    "read_run_status",
    "start_step",
]

TerminalStep = Literal["completed", "empty", "failed"]

#: What a ``failed`` step records when its caller named no reason. The CHECK is biconditional, so
#: "failed with no code" is not a row the database will take; an honest placeholder beats a crash
#: on the one path that exists to contain a failure.
UNSPECIFIED_FAILURE = "unspecified"

#: The document statuses that mean bytes are being served, so a new version must supersede them.
_SERVED_STATUSES = ("ready", "proposed", "confirmed")


@dataclass(frozen=True)
class StepStatus:
    kind: str
    subject_ref: str | None
    phase: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    cost_usd: Decimal
    failure_code: str | None


@dataclass(frozen=True)
class RunStatus:
    run_id: UUID
    status: str
    cost_usd: Decimal
    steps: tuple[StepStatus, ...]


@dataclass(frozen=True)
class DocumentRow:
    document_id: UUID
    folder: str
    path: str
    kind: str
    version: int
    status: str
    artifact_key: str | None
    artifact_sha256: str | None


async def create_run(
    conn: AsyncConnection,
    *,
    run_id: UUID,
    workspace_id: str,
    brand_id: str,
    company_domain: str,
    requested_by_user_id: str,
) -> None:
    """Insert the ``queued`` run. Re-inserting the same id is a no-op, never a duplicate run."""
    await conn.execute(
        text(
            "INSERT INTO onboarding_run (run_id, workspace_id, brand_id, company_domain, "
            " requested_by_user_id) VALUES (:run_id, :workspace_id, :brand_id, :domain, :user_id) "
            "ON CONFLICT (run_id) DO NOTHING"
        ),
        {
            "run_id": run_id,
            "workspace_id": workspace_id,
            "brand_id": brand_id,
            "domain": company_domain.strip(),
            "user_id": requested_by_user_id,
        },
    )


async def create_persona_run(
    conn: AsyncConnection,
    *,
    run_id: UUID,
    workspace_id: str,
    brand_id: str,
    project_id: str,
    persona_icp_document_id: UUID,
    company_domain: str,
    requested_by_user_id: str,
) -> None:
    """Insert the ``queued`` **personas** run: one persona turn for one ICP document.

    The narrow sibling of :func:`create_run`. It researches nothing and syncs no catalog — it is
    the row behind "write the personas for the profile this project just confirmed" — so it names
    the project that asked and the document it writes about. ``onboarding_run_persona_shape``
    welds those two halves: a personas run without its ICP document, or a full run with one, is
    not a row the database will take.

    ``company_domain`` is copied from the brand's completed onboarding walk rather than re-derived:
    the synthesis card names the company, and the only honest source for that here is the walk that
    already established it.

    Re-inserting the same id is a no-op, exactly as :func:`create_run`'s is: a replayed request
    finds its own run instead of opening a second one for the same document.
    """
    await conn.execute(
        text(
            "INSERT INTO onboarding_run (run_id, workspace_id, brand_id, kind, project_id, "
            " persona_icp_document_id, company_domain, requested_by_user_id) "
            "VALUES (:run_id, :workspace_id, :brand_id, 'personas', :project_id, :document_id, "
            " :domain, :user_id) "
            "ON CONFLICT (run_id) DO NOTHING"
        ),
        {
            "run_id": run_id,
            "workspace_id": workspace_id,
            "brand_id": brand_id,
            "project_id": project_id,
            "document_id": persona_icp_document_id,
            "domain": company_domain.strip(),
            "user_id": requested_by_user_id,
        },
    )


async def open_persona_run(conn: AsyncConnection, *, persona_icp_document_id: UUID) -> UUID | None:
    """The open personas run for one ICP document, or ``None``.

    Keyed on the document rather than on the workspace or the project, because that is what the
    run is *about*: two projects pinning the same brand ICP are asking for the same personas at the
    same path, and two turns racing there would version over each other. A document id is globally
    unique, so no tenancy predicate is needed to make this read precise.

    The partial index ``onboarding_run_persona_open`` is exactly this query's shape.
    """
    return (
        await conn.execute(
            text(
                "SELECT run_id FROM onboarding_run WHERE kind = 'personas' "
                "AND persona_icp_document_id = :document_id "
                "AND status IN ('queued', 'running') LIMIT 1"
            ),
            {"document_id": persona_icp_document_id},
        )
    ).scalar_one_or_none()


async def read_run_status(conn: AsyncConnection, *, run_id: UUID) -> str | None:
    """The status of one run by id, or ``None`` when no such run exists.

    The companion to :func:`open_persona_run`, which by design only matches an *open* run. A caller
    whose run id is derived (a personas request derives one per turn) needs to tell "this turn has
    not opened its run yet" from "this turn's run has already settled" — and without this read the
    two are the same ``None``, so a same-turn retry after a completed run would re-offer a terminal
    row and report the failure as if the queue were broken.
    """
    return (
        await conn.execute(
            text("SELECT status FROM onboarding_run WHERE run_id = :run_id"),
            {"run_id": run_id},
        )
    ).scalar_one_or_none()


async def mark_run_running(conn: AsyncConnection, *, run_id: UUID) -> None:
    """``queued`` → ``running``. Guarded on ``queued`` so a re-delivered task cannot revive a run
    that already reached a terminal status (which would then violate the biconditional CHECK)."""
    await conn.execute(
        text(
            "UPDATE onboarding_run SET status = 'running' "
            "WHERE run_id = :run_id AND status = 'queued'"
        ),
        {"run_id": run_id},
    )


async def start_step(
    conn: AsyncConnection,
    *,
    step_id: UUID,
    run_id: UUID,
    workspace_id: str,
    kind: str,
    phase: str,
    subject_ref: str | None = None,
) -> None:
    """Open a step as ``running``.

    A plain INSERT on purpose: ``onboarding_step_identity`` is unique on
    ``(run_id, kind, COALESCE(subject_ref, ''))``, so starting the same step twice in one run is a
    programming error the database should say out loud, not something to swallow.
    """
    await conn.execute(
        text(
            "INSERT INTO onboarding_step (step_id, run_id, workspace_id, kind, subject_ref, "
            " phase, status, started_at) VALUES (:step_id, :run_id, :workspace_id, :kind, "
            " :subject_ref, :phase, 'running', now())"
        ),
        {
            "step_id": step_id,
            "run_id": run_id,
            "workspace_id": workspace_id,
            "kind": kind,
            "subject_ref": subject_ref,
            "phase": phase,
        },
    )


async def open_document(
    conn: AsyncConnection,
    *,
    document_id: UUID,
    workspace_id: str,
    brand_id: str,
    folder: str,
    path: str,
    kind: str,
    step_id: UUID,
) -> int:
    """Insert the next version of ``path`` as ``running`` and link it back onto its step.

    Both FKs in the step ↔ document cycle are NOT DEFERRABLE, so the write order is fixed:
    the step already exists, the document names it, and only then does the step name the document.

    The onboarding walk writes the **brand's** knowledge, so the version chain it continues is the
    brand-level one: a project's own variant at the same path has its own history and must not
    push the brand's next version along.
    """
    version = int(
        (
            await conn.execute(
                text(
                    "SELECT COALESCE(MAX(version), 0) + 1 FROM brand_knowledge_document "
                    "WHERE workspace_id = :ws AND brand_id = :brand AND path = :path "
                    "  AND project_id IS NULL"
                ),
                {"ws": workspace_id, "brand": brand_id, "path": path},
            )
        ).scalar_one()
    )
    await conn.execute(
        text(
            "INSERT INTO brand_knowledge_document (document_id, workspace_id, brand_id, folder, "
            " path, kind, version, status, produced_by_step_id) VALUES (:id, :ws, :brand, "
            " :folder, :path, :kind, :version, 'running', :step_id)"
        ),
        {
            "id": document_id,
            "ws": workspace_id,
            "brand": brand_id,
            "folder": folder,
            "path": path,
            "kind": kind,
            "version": version,
            "step_id": step_id,
        },
    )
    await conn.execute(
        text("UPDATE onboarding_step SET output_document_id = :doc WHERE step_id = :step_id"),
        {"doc": document_id, "step_id": step_id},
    )
    return version


async def publish_document(
    conn: AsyncConnection,
    *,
    document_id: UUID,
    artifact_key: str,
    artifact_sha256: str,
    status: str = "ready",
) -> None:
    """Attach the stored bytes and retire whichever earlier version was being served.

    ``status`` is a parameter because a document can be published with a body and still not be a
    served fact — the driver writes an ``empty`` catalog document with its rendered "nothing found"
    body, which ``brand_knowledge_document_body_when_served`` permits (that CHECK binds only the
    served statuses).

    Brand-level only, on both reads: this publishes what the brand walk opened, and it retires the
    brand's previous version of that path. A project-scoped document id has no row here and raises
    rather than being published through a walk that never opened it.
    """
    row = (
        (
            await conn.execute(
                text(
                    "SELECT workspace_id, brand_id, path, version FROM brand_knowledge_document "
                    "WHERE document_id = :id AND project_id IS NULL"
                ),
                {"id": document_id},
            )
        )
        .mappings()
        .one()
    )
    previous = (
        (
            await conn.execute(
                text(
                    "SELECT document_id FROM brand_knowledge_document WHERE workspace_id = :ws "
                    "AND brand_id = :brand AND path = :path AND version < :version "
                    "AND status IN :served AND project_id IS NULL "
                    "ORDER BY version DESC LIMIT 1"
                ).bindparams(bindparam("served", expanding=True)),
                {
                    "ws": row["workspace_id"],
                    "brand": row["brand_id"],
                    "path": row["path"],
                    "version": row["version"],
                    "served": list(_SERVED_STATUSES),
                },
            )
        )
        .scalars()
        .first()
    )
    await conn.execute(
        text(
            "UPDATE brand_knowledge_document SET status = :status, artifact_key = :key, "
            " artifact_sha256 = :sha, supersedes_document_id = :prev, updated_at = now() "
            "WHERE document_id = :id"
        ),
        {
            "status": status,
            "key": artifact_key,
            "sha": artifact_sha256,
            "prev": previous,
            "id": document_id,
        },
    )
    if previous is not None:
        await conn.execute(
            text(
                "UPDATE brand_knowledge_document SET status = 'superseded', updated_at = now() "
                "WHERE document_id = :id"
            ),
            {"id": previous},
        )


async def fail_document(
    conn: AsyncConnection, *, document_id: UUID, status: Literal["empty", "failed"]
) -> None:
    """Close an opened document with no body. Neither status is served, so no bytes are required."""
    await conn.execute(
        text(
            "UPDATE brand_knowledge_document SET status = :status, updated_at = now() "
            "WHERE document_id = :id"
        ),
        {"status": status, "id": document_id},
    )


async def finish_step(
    conn: AsyncConnection,
    *,
    step_id: UUID,
    status: TerminalStep,
    provider_run_id: str | None = None,
    raw_artifact_key: str | None = None,
    cost_usd: Decimal = Decimal(0),
    searches: int = 0,
    failure_code: str | None = None,
    failure_message: str | None = None,
) -> None:
    """Land a step on a terminal status, with ``finished_at`` and the failure pair kept legal.

    ``onboarding_step_failure_pair`` is a biconditional, so the code is derived from the status
    rather than trusted from the caller: a non-``failed`` step drops any code it was handed (an
    ``empty`` step's reason rides ``failure_message`` alone), and a ``failed`` step that named none
    records :data:`UNSPECIFIED_FAILURE`.
    """
    code = (failure_code or UNSPECIFIED_FAILURE) if status == "failed" else None
    await conn.execute(
        text(
            "UPDATE onboarding_step SET status = :status, finished_at = now(), "
            " provider_run_id = :provider_run_id, raw_artifact_key = :raw, cost_usd = :cost, "
            " searches = :searches, failure_code = :code, failure_message = :message "
            "WHERE step_id = :step_id"
        ),
        {
            "status": status,
            "provider_run_id": provider_run_id,
            "raw": raw_artifact_key,
            "cost": cost_usd,
            "searches": int(searches),
            "code": code,
            "message": failure_message,
            "step_id": step_id,
        },
    )


async def finish_run(conn: AsyncConnection, *, run_id: UUID) -> str:
    """Close the run from its own steps: any ``empty``/``failed`` step means gaps, and the run's
    cost is the sum of theirs.

    Guarded on an open run, exactly as :func:`fail_run` is, so the normal close-out can never walk
    a contained run back off ``failed``. It therefore returns the status the row *holds* rather
    than the one it attempted — a driver whose containment path already ran is told ``failed``,
    not a status the run never received.
    """
    row = (
        (
            await conn.execute(
                text(
                    "SELECT COALESCE(SUM(cost_usd), 0) AS cost, "
                    " bool_or(status IN ('empty', 'failed')) AS gaps "
                    "FROM onboarding_step WHERE run_id = :run_id"
                ),
                {"run_id": run_id},
            )
        )
        .mappings()
        .one()
    )
    status = "completed_with_gaps" if row["gaps"] else "completed"
    await conn.execute(
        text(
            "UPDATE onboarding_run SET status = :status, cost_usd = :cost, finished_at = now() "
            "WHERE run_id = :run_id AND finished_at IS NULL"
        ),
        {"status": status, "cost": row["cost"], "run_id": run_id},
    )
    stored = (
        await conn.execute(
            text("SELECT status FROM onboarding_run WHERE run_id = :run_id"), {"run_id": run_id}
        )
    ).scalar_one()
    return str(stored)


async def fail_run(conn: AsyncConnection, *, run_id: UUID) -> None:
    """The containment terminal. Guarded on an open run so it can never re-stamp a finished one."""
    await conn.execute(
        text(
            "UPDATE onboarding_run SET status = 'failed', finished_at = now() "
            "WHERE run_id = :run_id AND finished_at IS NULL"
        ),
        {"run_id": run_id},
    )


async def read_current_run(conn: AsyncConnection, *, workspace_id: str) -> RunStatus | None:
    """The workspace's newest **full** run by ``requested_at``, with its steps. ``None`` when it
    has none.

    ``cost_usd`` is summed from the steps rather than read off the run, so it is the **live** burn
    while the run is still open — the run's own column is only written at close-out. The two agree
    once :func:`finish_run` has run, because it writes that same sum.

    ``kind = 'full'`` because this is what the setting-up screen watches: the whole-brand walk and
    its documents. A ``personas`` run is one project's narrow turn for one ICP, with none of the
    steps that screen renders, and letting it become "the workspace's current run" would replace a
    completed onboarding with a progress bar for work the screen cannot describe.
    """
    run = (
        (
            await conn.execute(
                text(
                    "SELECT run_id, status, (SELECT COALESCE(SUM(step.cost_usd), 0) "
                    " FROM onboarding_step step WHERE step.run_id = run.run_id) AS cost_usd "
                    "FROM onboarding_run run WHERE workspace_id = :ws AND kind = 'full' "
                    "ORDER BY requested_at DESC LIMIT 1"
                ),
                {"ws": workspace_id},
            )
        )
        .mappings()
        .first()
    )
    if run is None:
        return None
    steps = (
        (
            await conn.execute(
                text(
                    "SELECT kind, subject_ref, phase, status, started_at, finished_at, cost_usd, "
                    " failure_code FROM onboarding_step WHERE run_id = :run_id "
                    "ORDER BY started_at NULLS LAST, kind, subject_ref"
                ),
                {"run_id": run["run_id"]},
            )
        )
        .mappings()
        .all()
    )
    return RunStatus(
        run_id=run["run_id"],
        status=str(run["status"]),
        cost_usd=Decimal(run["cost_usd"]),
        steps=tuple(
            StepStatus(
                kind=step["kind"],
                subject_ref=step["subject_ref"],
                phase=step["phase"],
                status=step["status"],
                started_at=step["started_at"],
                finished_at=step["finished_at"],
                cost_usd=Decimal(step["cost_usd"]),
                failure_code=step["failure_code"],
            )
            for step in steps
        ),
    )


async def list_documents(
    conn: AsyncConnection, *, workspace_id: str, brand_id: str, all_versions: bool = False
) -> tuple[DocumentRow, ...]:
    """The brand's knowledge documents — the current version of each path, or every version.

    O5's read endpoint and O4's materialization both take the default (current) view; the history
    is only for callers that need to see what a path used to be. Brand-level rows only, in both
    views: a project's own documents are that project's, and are read through the project reader.
    """
    current_only = (
        " AND version = (SELECT MAX(d2.version) FROM brand_knowledge_document d2 "
        " WHERE d2.workspace_id = d.workspace_id AND d2.brand_id = d.brand_id "
        " AND d2.path = d.path AND d2.project_id IS NULL)"
    )
    where = "" if all_versions else current_only
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT document_id, folder, path, kind, version, status, artifact_key, "
                    " artifact_sha256 FROM brand_knowledge_document d "
                    f"WHERE workspace_id = :ws AND brand_id = :brand AND project_id IS NULL{where} "
                    "ORDER BY folder, path, version"
                ),
                {"ws": workspace_id, "brand": brand_id},
            )
        )
        .mappings()
        .all()
    )
    return tuple(
        DocumentRow(
            document_id=row["document_id"],
            folder=row["folder"],
            path=row["path"],
            kind=row["kind"],
            version=int(row["version"]),
            status=row["status"],
            artifact_key=row["artifact_key"],
            artifact_sha256=row["artifact_sha256"],
        )
        for row in rows
    )
