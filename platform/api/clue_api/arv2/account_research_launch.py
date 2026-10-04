"""Seam 1: what a human authorized, turned into run + job rows and one fleet task per account.

This module is the **only** door into the R2 lane. Everything past it — the driver, the agent, the
twelve tools — runs against the run row this writes, so the run row is the authorization record:
the exact account set, the confirmed ICP artifact and its digest, the product-selection version,
the agent profile and *its* digest. A job that later finds any of those bytes moved refuses and
asks to be relaunched, because moved bytes are a different thing to have approved.

Three properties are deliberate, and each one is a test:

* **Every refusal is typed** (:class:`Arv2LaunchRefused` with a stable ``code``), never a stack
  trace or a silent empty result. The toolbelt tool turns each straight into a
  :class:`~clue_toolbelt.PreconditionFailed`, so the human is told which prerequisite is missing.
* **The run id is the digest of the request.** Relaunching the same signed-off request returns the
  same run, inserts no second job, and buys no second task — the launch is safely retryable by a
  human who clicked twice or by a turn that replayed.
* **It needs only accounts, an ICP artifact ref, and a selection version** (standing rule item 5).
  No ``icp_spec`` row, no ``account_research_directive``, no Stage-0 pin on the project run. The
  old Stage-0 launch machinery is not a dependency of this lane and must never become one.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.manual import tool_manual_link
from clue_api.arv2.account_research_catalog import (
    arv2_account_profile_sha256,
    arv2_person_profile_sha256,
    has_capability,
)
from clue_api.arv2.account_research_claims import (
    PERSONA_FIELD,
    JobScope,
    committee_member_claims,
)
from clue_api.arv2.account_research_store import (
    JobRow,
    RunRow,
    create_job,
    create_run,
    list_jobs,
    read_person_catalog,
    read_run,
)
from clue_api.arv2.claim_writer import LenientClaimWriter
from clue_api.arv2.errors import Arv2Error
from clue_api.arv2.fleet_task import (
    ARV2_ACCOUNT_DEDUP_PREFIX,
    ARV2_ACCOUNT_TASK_PRIORITY,
    arv2_account_work_id,
)
from clue_api.arv2.icp_confirmation import ProjectIcpPin, current_project_icp_pin
from clue_api.arv2.knowledge_frontmatter import parse_front_matter
from clue_api.arv2.quality_generation import attach_to_account_research
from clue_api.arv2.research_context import pin_persona
from clue_api.arv2.structuring_client import FieldCatalog
from clue_config import Settings
from clue_core import EntityId, ExtractionMethod, Persona, ProjectPhase, ProjectRunId
from clue_db import ConnFactory, transaction
from clue_fleet import DbWorkQueue, FleetTaskKind, WorkQueue
from clue_obs import get_logger
from clue_obs.langfuse import tag_entities
from clue_research.claimstore import WorkspaceScope, claims_for
from clue_research.claimstore.run_lineage import record_run_lineage
from clue_research.durable.project_run import ensure_project_run, get_project_run
from clue_research.identity import get_account, get_contact
from clue_research.membership import ensure_project_account
from clue_spine import current_project_product_set, get_project, list_project_product_sets
from clue_storage import StorageBackend, read_verified_artifact
from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
    PreconditionFailed,
    PreconditionFailure,
    ReplayPolicy,
    ReplaySafety,
    Tool,
    ToolContext,
    ToolEffectClass,
    ToolEstimate,
    ToolInput,
    ToolOutput,
    ToolResult,
)

log = get_logger("clue_api.arv2.account_research_launch")

__all__ = [
    "Arv2LaunchReceipt",
    "Arv2LaunchRefused",
    "Arv2LaunchRequest",
    "Arv2LaunchService",
    "Arv2RunView",
    "DbArv2LaunchService",
    "Arv2PersonLaunchRequest",
    "seat_person_on_committee",
    "LaunchArv2AccountResearchInput",
    "LaunchArv2AccountResearchOutput",
    "LaunchArv2AccountResearchTool",
    "LaunchArv2PersonResearchInput",
    "LaunchArv2PersonResearchOutput",
    "LaunchArv2PersonResearchTool",
    "QueuedJob",
    "ReadArv2AccountResearchRunInput",
    "ReadArv2AccountResearchRunOutput",
    "ReadArv2AccountResearchRunTool",
    "arv2_job_id",
    "build_arv2_launch_tools",
    "enqueue_launched_jobs",
    "launch_arv2_account_research",
    "launch_arv2_person_research",
]

#: The document kind and status a launch will research against. Anything else is a refusal: a
#: ``proposed`` ICP is a draft nobody has agreed to, and researching against it would spend money
#: on an audience the client never confirmed.
_ICP_KIND = "icp-definition"
_ICP_STATUS = "confirmed"

#: Deterministic id namespaces. The run id is the digest of the signed-off request, the job id is
#: the run plus the subject — so a relaunch of the same request lands on exactly the same rows.
_RUN_NS = uuid5(NAMESPACE_URL, "arv2-account-research:run")
_JOB_NS = uuid5(NAMESPACE_URL, "arv2-account-research:job")


def arv2_job_id(run_id: UUID, subject_id: UUID) -> UUID:
    """One job's deterministic id: its run plus the entity it researches.

    The three writers of a job row all key it this way — the account launch (run + account), the
    person launch and the committee step (run + contact) — so re-launching a request, or
    re-settling the account job that resolved a committee, lands on the row that is already there
    instead of a second one. An account and a contact are different entities, so an account job and
    a person job under the same run can never collide.
    """
    return uuid5(_JOB_NS, f"{run_id}:{subject_id}")


def quality_person_job_id(run_id: UUID, account_id: UUID, contact_id: UUID) -> UUID:
    return uuid5(_RUN_NS, f"quality-person:{run_id}:{account_id}:{contact_id}")


#: The run row's effort dial. Kept as a closed literal (and CHECK-ed in the migration) so a typo
#: cannot silently become a research posture nobody defined.
Arv2Effort = Literal["full", "reduced", "cheap-pass"]

#: The document a project pinned, read by id — the exact version a human approved, never "the
#: newest row that happens to carry these bytes".
_PINNED_ICP_ROW = text(
    """
    SELECT document_id, brand_id, kind, status, artifact_key, artifact_sha256, path
    FROM brand_knowledge_document
    WHERE workspace_id = :workspace_id AND document_id = :document_id
    """
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Arv2LaunchRequest:
    """One signed-off research request. Every field is part of what the human approved."""

    workspace_id: str
    project_id: str
    account_entity_ids: tuple[UUID, ...]
    icp_artifact_key: str
    icp_artifact_sha256: str
    product_selection_version: int
    requested_by_user_id: str
    effort: Arv2Effort = "full"
    committee_cap: int = 5
    directive_text: str = ""
    project_run_id: UUID | None = None


class Arv2LaunchRefused(Arv2Error):
    """A launch prerequisite is unmet. ``code`` is stable and machine-readable.

    Codes: ``lane_disabled``, ``account_not_found:<id>``, ``account_not_in_workspace:<id>``,
    ``project_icp_not_pinned``, ``icp_artifact_not_found``, ``icp_artifact_not_confirmed``,
    ``icp_digest_mismatch``, ``icp_front_matter_invalid``, ``product_selection_version_unknown``,
    ``project_not_found``. The account launch adds ``icp_artifact_not_project_pin`` (the request
    names an ICP artifact that is not what this project pinned). The person launch adds
    ``no_contacts``, ``contact_not_found:<id>``, ``contact_merged:<id>``,
    ``contact_without_account`` and ``product_set_not_confirmed``.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class QueuedJob:
    """One job the caller must offer to the fleet — **after** the launch transaction commits."""

    job_id: UUID
    run_id: UUID
    workspace_id: str


@dataclass(frozen=True)
class Arv2LaunchReceipt:
    """What the launch did: the run, its jobs, whether this was a replay, and the project run.

    ``to_enqueue`` is the work the *caller* still owes the fleet. The launch deliberately does not
    offer it: ``DbTaskQueue.enqueue`` commits in its own transaction, so an offer made inside the
    launch's transaction is visible to a polling worker **before** the run and job rows it names
    are — and that worker reads "no such job" as "already done" and finishes the task, dropping the
    account's research permanently. Rows first, offer second (the O3 rule, ``onboarding_routes``).
    """

    run_id: UUID
    job_ids: tuple[UUID, ...]
    replayed: bool
    project_run_id: UUID
    to_enqueue: tuple[QueuedJob, ...] = ()


@dataclass(frozen=True)
class Arv2RunView:
    """A run row with its job states — the reverse edge of seam 1."""

    run: RunRow
    jobs: tuple[JobRow, ...]


# =================================================================================================
# the launch
# =================================================================================================


async def launch_arv2_account_research(
    conn: AsyncConnection,
    request: Arv2LaunchRequest,
    *,
    settings: Settings,
    storage: StorageBackend,
    profile_sha256: str,
    now: Callable[[], datetime] = _utcnow,
) -> Arv2LaunchReceipt:
    """Validate the request and write the run and its jobs. **It queues nothing.**

    Checks run in cost order — the free ones first — so a launch that cannot happen refuses before
    it reads an artifact. Nothing is written until every check has passed.

    The fleet offer is the caller's, made through :func:`enqueue_launched_jobs` once this function's
    transaction has committed. See :class:`Arv2LaunchReceipt` for why the ordering is the safety
    property.
    """
    if not settings.arv2_account_research_enabled:
        raise Arv2LaunchRefused(
            "lane_disabled", "CLUE_ARV2_ACCOUNT_RESEARCH_ENABLED is false on this deployment"
        )

    # The project comes first, exactly as it does in the person launch. Every check after this one
    # is a question *about* a project — which ICP it pinned, which product set it confirmed — so a
    # launch naming a project that does not exist must be told THAT, rather than "you have pinned
    # no ICP", which is true of a non-existent project and useless to the human reading it.
    project = await get_project(conn, request.project_id)
    if project is None or project.workspace_id != request.workspace_id:
        raise Arv2LaunchRefused(
            "project_not_found",
            f"project {request.project_id!r} has no row in workspace {request.workspace_id!r}, "
            "so there is no project run to research under",
        )
    await _check_accounts(conn, request)
    icp = await _pinned_icp(conn, storage, request)
    await _check_product_selection(conn, request)

    project_run_id = request.project_run_id or uuid5(
        NAMESPACE_URL,
        f"arv2-project-run:{request.project_id}:{icp.icp_key}:{icp.icp_version}",
    )
    await ensure_project_run(
        conn,
        project_run_id=ProjectRunId(project_run_id),
        project_id=request.project_id,
        workspace_id=request.workspace_id,
        icp_key=icp.icp_key,
        icp_version=icp.icp_version,
        phase=ProjectPhase.DEEP,
    )
    if await get_project_run(conn, ProjectRunId(project_run_id)) is None:  # pragma: no cover
        # Guarded by the project read above; kept because ``ensure_project_run``'s INSERT selects
        # the brand/workspace FROM ``project``, so an unknown project inserts nothing at all and
        # says nothing about it — and a run with no project run would strand every job under it.
        raise Arv2LaunchRefused(
            "project_not_found",
            f"project {request.project_id!r} has no row in workspace {request.workspace_id!r}, "
            "so there is no project run to research under",
        )

    request_sha = _request_sha256(request, profile_sha256=profile_sha256)
    run_id = uuid5(_RUN_NS, request_sha)
    context_id = await _quality_context_for_run(
        conn,
        storage,
        settings=settings,
        workspace_id=request.workspace_id,
        project_id=request.project_id,
        run_id=run_id,
        product_selection_version=request.product_selection_version,
        icp_artifact_key=request.icp_artifact_key,
    )
    inserted = await create_run(
        conn,
        RunRow(
            run_id=run_id,
            workspace_id=request.workspace_id,
            project_id=request.project_id,
            brand_id=icp.brand_id,
            project_run_id=project_run_id,
            icp_artifact_key=request.icp_artifact_key,
            icp_artifact_sha256=request.icp_artifact_sha256,
            icp_key=icp.icp_key,
            icp_version=icp.icp_version,
            product_selection_version=request.product_selection_version,
            effort=request.effort,
            committee_cap=request.committee_cap,
            directive_text=request.directive_text,
            profile_ref=f"agent-profile:arv2-account:{settings.arv2_research_catalog_version}",
            profile_sha256=profile_sha256,
            requested_by_user_id=request.requested_by_user_id,
            request_sha256=request_sha,
            context_id=context_id,
            persona_pin=(
                await pin_persona(
                    conn,
                    storage,
                    workspace_id=request.workspace_id,
                    brand_id=icp.brand_id,
                    project_id=request.project_id,
                    icp_key=icp.icp_key,
                    icp_version=icp.icp_version,
                )
            )
            if context_id is None
            and has_capability(settings.arv2_research_catalog_version, "committee_discovery")
            else None,
            created_at=now(),
        ),
    )
    await record_run_lineage(
        conn,
        run_id=run_id,
        workspace_id=request.workspace_id,
        kind="entity_research",
        project_id=request.project_id,
        project_run_id=project_run_id,
    )

    job_ids: list[UUID] = []
    for account_id in request.account_entity_ids:
        await ensure_project_account(
            conn,
            workspace_id=request.workspace_id,
            project_id=request.project_id,
            account_entity_id=account_id,
            added_via="manual",
        )
        job_id = arv2_job_id(run_id, account_id)
        job_ids.append(job_id)
        await create_job(
            conn,
            job_id=job_id,
            run_id=run_id,
            workspace_id=request.workspace_id,
            account_entity_id=account_id,
            # The launch queues account subjects only; committee members are queued later, by the
            # committee step, once this job has resolved them. The job carries its own copy of the
            # profile pin so replay never has to infer it from the run.
            subject_type="account",
            profile_ref=f"agent-profile:arv2-account:{settings.arv2_research_catalog_version}",
            profile_sha256=profile_sha256,
        )

    log.info(
        "arv2.account_research_launched",
        run_id=str(run_id),
        project_id=request.project_id,
        accounts=len(job_ids),
        replayed=not inserted,
    )
    return Arv2LaunchReceipt(
        run_id=run_id,
        job_ids=tuple(job_ids),
        replayed=not inserted,
        project_run_id=project_run_id,
        # *Every* job of the run is offered, not only the ones this call inserted. The queue's
        # dedup key makes re-offering an already-queued job a no-op, so a relaunch is how a run
        # whose offer failed (or was lost) after the commit is repaired — which it could not be if
        # a replay reported nothing to enqueue. ``replayed`` still means "the run row existed".
        to_enqueue=tuple(
            QueuedJob(job_id=job_id, run_id=run_id, workspace_id=request.workspace_id)
            for job_id in job_ids
        ),
    )


async def _quality_context_for_run(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    settings: Settings,
    workspace_id: str,
    project_id: str,
    run_id: UUID,
    product_selection_version: int,
    icp_artifact_key: str,
) -> UUID | None:
    if not has_capability(settings.arv2_research_catalog_version, "research_quality"):
        return None
    from clue_api.arv2.quality_context import build_context, persist_context, read_context

    # Serialize the first pin with run creation. Retried launches never recalculate persona,
    # catalog or seller context against whatever is newest at retry time.
    await conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": f"research-launch-context:{workspace_id}:{run_id}"},
    )
    existing = await read_run(conn, run_id=run_id)
    if existing is not None:
        if (existing.workspace_id, existing.project_id) != (
            workspace_id,
            project_id,
        ) or existing.context_id is None:
            raise Arv2LaunchRefused(
                "context_pin_missing", "Existing research has no matching context pin"
            )
        context = await read_context(
            conn,
            storage,
            workspace_id=workspace_id,
            project_id=project_id,
            context_id=existing.context_id,
        )
        if context.icp.artifact_key != icp_artifact_key:
            raise Arv2LaunchRefused(
                "context_pin_mismatch", "Existing context names a different ICP"
            )
        return existing.context_id
    context = await build_context(
        conn,
        storage,
        workspace_id=workspace_id,
        project_id=project_id,
        product_selection_version=product_selection_version,
    )
    if context.icp.artifact_key != icp_artifact_key:
        raise Arv2LaunchRefused("context_pin_mismatch", "Project ICP changed during launch")
    return await persist_context(conn, storage, context)


async def enqueue_launched_jobs(queue: WorkQueue, receipt: Arv2LaunchReceipt) -> int:
    """Offer a committed launch's jobs to the fleet; returns how many offers the queue accepted.

    Call this only once the launch's transaction has committed. An offer that fails is logged with
    the job ids nothing is driving and re-raised: the rows exist, so the repair is to call this
    again (or relaunch the same request, which replays to the same run and re-offers every job).
    """
    accepted = 0
    for index, job in enumerate(receipt.to_enqueue):
        try:
            offered = await queue.enqueue(
                kind=FleetTaskKind.ARV2_ACCOUNT_RESEARCH,
                work_id=arv2_account_work_id(job.job_id),
                dedup_key=f"{ARV2_ACCOUNT_DEDUP_PREFIX}{job.job_id}",
                priority=ARV2_ACCOUNT_TASK_PRIORITY,
                payload={
                    "job_id": str(job.job_id),
                    "run_id": str(job.run_id),
                    "workspace_id": job.workspace_id,
                },
                reopen_terminal=False,
            )
        except Exception:
            # Broad on purpose (the O3 shape): a transport error, a pool timeout and a bug in the
            # queue are one fact here — these jobs were not offered — and the log has to name them
            # or nobody can tell which accounts are waiting on a task that was never bought.
            log.exception(
                "arv2.account_research_enqueue_failed",
                run_id=str(receipt.run_id),
                job_ids=[str(pending.job_id) for pending in receipt.to_enqueue[index:]],
            )
            raise
        accepted += 1 if offered else 0
    log.info(
        "arv2.account_research_enqueued",
        run_id=str(receipt.run_id),
        offered=len(receipt.to_enqueue),
        accepted=accepted,
    )
    return accepted


@dataclass(frozen=True)
class _PinnedIcp:
    brand_id: str
    icp_key: str
    icp_version: int


async def _check_accounts(conn: AsyncConnection, request: Arv2LaunchRequest) -> None:
    """Every named account must exist and belong to this workspace — refused by id, not in bulk.

    Naming the offending id matters: a launch of forty accounts that refuses with "one of these is
    wrong" is a refusal a human cannot act on.
    """
    for account_id in request.account_entity_ids:
        account = await get_account(conn, EntityId(account_id))
        if account is None:
            raise Arv2LaunchRefused(
                f"account_not_found:{account_id}",
                f"account {account_id} does not exist; import or discover it before launching",
            )
        if account.workspace_id != request.workspace_id:
            raise Arv2LaunchRefused(
                f"account_not_in_workspace:{account_id}",
                f"account {account_id} belongs to another workspace and cannot be researched here",
            )


async def _project_icp_pin(
    conn: AsyncConnection, *, workspace_id: str, project_id: str
) -> ProjectIcpPin:
    """The ICP this project pinned, or a typed refusal — never a fallback to something else.

    Founder rulings 2026-09-10: a project researches against the one confirmed ICP version a human
    pinned for it. A project that has not pinned one has no ICP, and saying so is the honest
    answer; resolving "the brand's newest confirmed" instead would let a re-synthesis, or another
    project's confirmation, silently repoint what this project spends money researching.
    """
    pin = await current_project_icp_pin(conn, workspace_id=workspace_id, project_id=project_id)
    if pin is None:
        raise Arv2LaunchRefused(
            "project_icp_not_pinned",
            f"project {project_id!r} has not pinned a confirmed {_ICP_KIND}; confirm one at the "
            "ICP gate before researching anything",
        )
    return pin


async def _icp_from_pin(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    pin: ProjectIcpPin,
) -> tuple[Mapping[str, Any], _PinnedIcp]:
    """The pinned document's row and the run's pins, checked to still be what was pinned."""
    found = (
        (
            await conn.execute(
                _PINNED_ICP_ROW,
                {"workspace_id": workspace_id, "document_id": pin.document_id},
            )
        )
        .mappings()
        .first()
    )
    if found is None:
        raise Arv2LaunchRefused(
            "icp_artifact_not_found",
            f"the pinned document {pin.document_id} is not held by workspace {workspace_id!r}",
        )
    row: Mapping[str, Any] = dict(found)
    if row["kind"] != _ICP_KIND or row["status"] != _ICP_STATUS:
        raise Arv2LaunchRefused(
            "icp_artifact_not_confirmed",
            f"document {row['path']!r} is a {row['kind']!r} at status {row['status']!r}; a launch "
            f"researches only against a {_ICP_STATUS} {_ICP_KIND}",
        )
    if row["artifact_sha256"] != pin.artifact_sha256:
        raise Arv2LaunchRefused(
            "icp_digest_mismatch",
            "the pinned ICP document's bytes are not the ones the project pinned: stored "
            f"{row['artifact_sha256']}, pinned {pin.artifact_sha256}",
        )
    return row, await _icp_pins(conn, storage, workspace_id=workspace_id, row=row)


async def _pinned_icp(
    conn: AsyncConnection, storage: StorageBackend, request: Arv2LaunchRequest
) -> _PinnedIcp:
    """Resolve the run's ICP from the project's pin, and read its key/version off the document.

    The request still carries an ICP artifact ref, because a launch is a statement about the exact
    bytes a human signed off on — but it is now checked *against the pin* rather than trusted as
    the selector. A request naming any other artifact is refused by name: it was composed against
    an ICP this project does not research with.
    """
    pin = await _project_icp_pin(
        conn, workspace_id=request.workspace_id, project_id=request.project_id
    )
    if (
        request.icp_artifact_key != pin.artifact_key
        or request.icp_artifact_sha256 != pin.artifact_sha256
    ):
        raise Arv2LaunchRefused(
            "icp_artifact_not_project_pin",
            f"project {request.project_id!r} pins {pin.artifact_key!r} "
            f"({pin.artifact_sha256}); this request names {request.icp_artifact_key!r} "
            f"({request.icp_artifact_sha256})",
        )
    _row, icp = await _icp_from_pin(conn, storage, workspace_id=request.workspace_id, pin=pin)
    return icp


async def _icp_pins(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    row: Mapping[str, Any],
) -> _PinnedIcp:
    """Read one ICP document's body and take the run's pins — its brand, key and version — off it.

    Shared by both launches: the account launch resolves the document from the artifact ref its
    request named, the person launch from the project's brand, and from there the pins are read the
    same way — out of the document itself, never out of a caller's argument.
    """
    _, body = await read_verified_artifact(
        conn,
        storage,
        storage_key=str(row["artifact_key"]),
        workspace_id=workspace_id,
    )
    try:
        front, _ = parse_front_matter(body.decode("utf-8"))
    except ValueError as unreadable:
        raise Arv2LaunchRefused(
            "icp_front_matter_invalid",
            f"document {row['path']!r} carries no readable YAML front matter: {unreadable}",
        ) from unreadable
    # The run pins the ICP by key and version, and both come from the document itself. A document
    # missing either is a malformed pin, and a malformed pin must refuse the launch by name rather
    # than raise a ``KeyError``/``ValueError`` out of the launcher at the operator.
    icp_key = front.get("icp_key")
    version = front.get("version")
    if not isinstance(icp_key, str) or not icp_key.strip():
        raise Arv2LaunchRefused(
            "icp_front_matter_invalid",
            f"document {row['path']!r} names no icp_key; a run is pinned to the ICP's own key",
        )
    if not isinstance(version, int) or isinstance(version, bool):
        raise Arv2LaunchRefused(
            "icp_front_matter_invalid",
            f"document {row['path']!r} has version {version!r}, which is not an integer; a run is "
            "pinned to the ICP version the human confirmed",
        )
    return _PinnedIcp(
        brand_id=str(row["brand_id"]),
        icp_key=icp_key,
        icp_version=version,
    )


async def _check_product_selection(conn: AsyncConnection, request: Arv2LaunchRequest) -> None:
    """The pinned version must be one the project actually confirmed (rulings P1/P2).

    Deliberately *any* confirmed version, not only the current one: a launch pins the version the
    human saw, and a later confirmation must not silently repoint a run that is already authorized.
    """
    versions = {
        product_set.selection_version
        for product_set in await list_project_product_sets(
            conn, workspace_id=request.workspace_id, project_id=request.project_id
        )
    }
    if request.product_selection_version not in versions:
        raise Arv2LaunchRefused(
            "product_selection_version_unknown",
            f"project {request.project_id!r} has no confirmed product set at version "
            f"{request.product_selection_version}"
            + (f" (confirmed: {sorted(versions)})" if versions else " (none confirmed yet)"),
        )


def _request_sha256(request: Arv2LaunchRequest, *, profile_sha256: str) -> str:
    """The digest of what was signed off on — and therefore the run's identity.

    The account ids are sorted, so the same set chosen in a different order is the same run. Every
    other field is included verbatim: a different directive, effort, committee cap, ICP digest,
    product-set version or agent profile is a different thing to have approved, so it is a
    different run rather than a quiet reuse of an existing one.
    """
    payload = {
        "workspace_id": request.workspace_id,
        "project_id": request.project_id,
        "account_entity_ids": sorted(str(value) for value in request.account_entity_ids),
        "icp_artifact_sha256": request.icp_artifact_sha256,
        "product_selection_version": request.product_selection_version,
        "effort": request.effort,
        "committee_cap": request.committee_cap,
        "directive_text": request.directive_text,
        "profile_sha256": profile_sha256,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# =================================================================================================
# the person launch: research these named people, now, because a human asked
# =================================================================================================


@dataclass(frozen=True)
class Arv2PersonLaunchRequest:
    """One human's request to research these named people, whoever resolved them.

    It carries contacts, not candidates: the people are already entities of this workspace — found
    by a committee step, imported, or picked out of the account's contact list — and this launch
    researches them. It never creates a person, because creating one is an identity act with its
    own evidence, and a launch that could invent people would be a launch that could research
    someone who does not exist.
    """

    workspace_id: str
    project_id: str
    contact_entity_ids: tuple[UUID, ...]
    requested_by_user_id: str
    directive_text: str = ""
    project_run_id: UUID | None = None
    #: The seat the requesting human puts every named contact in. It is part of the request
    #: because a person launched on demand is otherwise **nobody**: the account's contact list is
    #: read from the committee claims (``contact_eligibility.Arv2CommitteeReferenceSource``), so a
    #: person with no ``contact.persona`` claim is researched at cost and then invisible on their
    #: own account's screen (walk finding W2, 2026-09-09). ``user`` is the default because it is
    #: the seat that assumes the least — the person who would operate the product — and the
    #: vocabulary is the platform's closed one, so a launch can never invent a role.
    persona: Persona = Persona.USER


async def launch_arv2_person_research(
    conn: AsyncConnection,
    request: Arv2PersonLaunchRequest,
    *,
    settings: Settings,
    storage: StorageBackend,
    profile_sha256: str,
    now: Callable[[], datetime] = _utcnow,
) -> Arv2LaunchReceipt:
    """Validate the request and write a run of its own with one person job per contact.

    A run of its own, rather than a job hung off an existing account run, because a run row *is*
    the authorization record: this research was authorized by a different human act, against
    whatever the project has confirmed at this moment, and pinning it to an older run would claim
    an approval nobody gave. ``effort`` is ``full`` (a human named these people one by one — there
    is no cheap pass to run on them) and the committee cap is simply how many they named.

    **It queues nothing**, for the reason :class:`Arv2LaunchReceipt` gives: rows first, offer
    second, through :func:`enqueue_launched_jobs` once this transaction has committed.
    """
    if not settings.arv2_account_research_enabled:
        raise Arv2LaunchRefused(
            "lane_disabled", "CLUE_ARV2_ACCOUNT_RESEARCH_ENABLED is false on this deployment"
        )
    if not request.contact_entity_ids:
        raise Arv2LaunchRefused("no_contacts", "a person launch must name at least one contact")

    project = await get_project(conn, request.project_id)
    if project is None or project.workspace_id != request.workspace_id:
        raise Arv2LaunchRefused(
            "project_not_found",
            f"project {request.project_id!r} has no row in workspace {request.workspace_id!r}",
        )
    accounts = await _check_contacts(conn, request)
    # The same pin the account launch resolves. An on-demand person launch has no approved
    # artifact ref to be handed, so before the pin existed it resolved "the brand's newest
    # confirmed ICP" — which moved under a project the moment onboarding re-synthesized or another
    # project confirmed. It now reads the project's own pin, like every other consumer.
    icp_pin = await _project_icp_pin(
        conn, workspace_id=request.workspace_id, project_id=request.project_id
    )
    icp_row, icp = await _icp_from_pin(
        conn, storage, workspace_id=request.workspace_id, pin=icp_pin
    )
    product_set = await current_project_product_set(
        conn, workspace_id=request.workspace_id, project_id=request.project_id
    )
    if product_set is None:
        raise Arv2LaunchRefused(
            "product_set_not_confirmed",
            f"project {request.project_id!r} has no confirmed product set; confirm one before "
            "researching anybody",
        )

    project_run_id = request.project_run_id or uuid5(
        NAMESPACE_URL,
        f"arv2-project-run:{request.project_id}:{icp.icp_key}:{icp.icp_version}",
    )
    await ensure_project_run(
        conn,
        project_run_id=ProjectRunId(project_run_id),
        project_id=request.project_id,
        workspace_id=request.workspace_id,
        icp_key=icp.icp_key,
        icp_version=icp.icp_version,
        phase=ProjectPhase.DEEP,
    )
    if await get_project_run(conn, ProjectRunId(project_run_id)) is None:  # pragma: no cover
        # Guarded by the project read above; kept because ``ensure_project_run`` writes nothing at
        # all for an unknown project and says nothing about it, and a run with no project run would
        # strand every job under it.
        raise Arv2LaunchRefused(
            "project_not_found",
            f"project {request.project_id!r} has no project run to research under",
        )

    artifact_key = str(icp_row["artifact_key"])
    artifact_sha256 = str(icp_row["artifact_sha256"])
    request_sha = _person_request_sha256(
        request,
        profile_sha256=profile_sha256,
        icp_artifact_sha256=artifact_sha256,
        product_selection_version=product_set.selection_version,
    )
    run_id = uuid5(_RUN_NS, request_sha)
    context_id = await _quality_context_for_run(
        conn,
        storage,
        settings=settings,
        workspace_id=request.workspace_id,
        project_id=request.project_id,
        run_id=run_id,
        product_selection_version=product_set.selection_version,
        icp_artifact_key=artifact_key,
    )
    inserted = await create_run(
        conn,
        RunRow(
            run_id=run_id,
            workspace_id=request.workspace_id,
            project_id=request.project_id,
            brand_id=icp.brand_id,
            project_run_id=project_run_id,
            icp_artifact_key=artifact_key,
            icp_artifact_sha256=artifact_sha256,
            icp_key=icp.icp_key,
            icp_version=icp.icp_version,
            product_selection_version=product_set.selection_version,
            effort="full",
            committee_cap=len(request.contact_entity_ids),
            directive_text=request.directive_text,
            profile_ref=f"agent-profile:arv2-person:{settings.arv2_research_catalog_version}",
            profile_sha256=profile_sha256,
            requested_by_user_id=request.requested_by_user_id,
            request_sha256=request_sha,
            context_id=context_id,
            persona_pin=(
                await pin_persona(
                    conn,
                    storage,
                    workspace_id=request.workspace_id,
                    brand_id=icp.brand_id,
                    project_id=request.project_id,
                    icp_key=icp.icp_key,
                    icp_version=icp.icp_version,
                )
            )
            if context_id is None
            and has_capability(settings.arv2_research_catalog_version, "committee_discovery")
            else None,
            created_at=now(),
        ),
    )
    await record_run_lineage(
        conn,
        run_id=run_id,
        workspace_id=request.workspace_id,
        kind="entity_research",
        project_id=request.project_id,
        project_run_id=project_run_id,
    )

    catalog = await read_person_catalog(conn, workspace_id=request.workspace_id)
    writer = LenientClaimWriter(lenient=settings.claim_write_lenient)
    job_ids: list[UUID] = []
    seated: list[UUID] = []
    for contact_id in request.contact_entity_ids:
        place = accounts[contact_id]
        await ensure_project_account(
            conn,
            workspace_id=request.workspace_id,
            project_id=request.project_id,
            account_entity_id=place.account_id,
            added_via="manual",
        )
        job_id = (
            quality_person_job_id(run_id, place.account_id, contact_id)
            if context_id
            else arv2_job_id(run_id, contact_id)
        )
        job_ids.append(job_id)
        await create_job(
            conn,
            job_id=job_id,
            run_id=run_id,
            workspace_id=request.workspace_id,
            # The account is the person's own — a person job stays scoped and joined like its
            # account sibling, and the driver composes their employer's context from it.
            account_entity_id=place.account_id,
            subject_type="person",
            profile_ref=f"agent-profile:arv2-person:{settings.arv2_research_catalog_version}",
            subject_entity_id=contact_id,
            profile_sha256=profile_sha256,
            input_refs={"subject_scope": "account", "requested_persona": request.persona.value}
            if context_id
            else None,
        )
        if context_id is not None:
            await conn.execute(
                text("""
              UPDATE arv2_research_job SET input_refs=input_refs || CAST(:refs AS jsonb)
              WHERE job_id=:job AND workspace_id=:ws
            """),
                {
                    "job": job_id,
                    "ws": request.workspace_id,
                    "refs": json.dumps({"requested_persona": request.persona.value}),
                },
            )
            # Join the account's own research (recipe 25+), so this person's result reaches the
            # account's rewrite even though the person runs in a run of their own.
            await attach_to_account_research(
                conn,
                workspace_id=request.workspace_id,
                project_id=request.project_id,
                account_id=place.account_id,
                context_id=context_id,
                job_id=job_id,
            )
        elif await seat_person_on_committee(
            conn,
            scope=JobScope(
                workspace_id=request.workspace_id,
                project_id=request.project_id,
                project_run_id=project_run_id,
                run_id=run_id,
                job_id=job_id,
                account_id=EntityId(place.account_id),
                account_name=place.account_name,
                account_domain=place.account_domain,
                # The prompt half of a scope is honestly empty here: a launch runs no model, and
                # the job's own composition reads the ICP body and the persona map when it runs.
                icp_markdown="",
                persona_markdown="",
                already_established="",
                effort="full",
                committee_cap=len(request.contact_entity_ids),
                today=now().date(),
                subject_kind="person",
                contact_id=EntityId(contact_id),
                person_name=place.person_name,
            ),
            persona=request.persona,
            requested_by_user_id=request.requested_by_user_id,
            writer=writer,
            catalog=catalog,
        ):
            seated.append(contact_id)

    log.info(
        "arv2.person_research_launched",
        run_id=str(run_id),
        project_id=request.project_id,
        people=len(job_ids),
        seated=len(seated),
        persona=str(request.persona),
        replayed=not inserted,
    )
    return Arv2LaunchReceipt(
        run_id=run_id,
        job_ids=tuple(job_ids),
        replayed=not inserted,
        project_run_id=project_run_id,
        to_enqueue=tuple(
            QueuedJob(job_id=job_id, run_id=run_id, workspace_id=request.workspace_id)
            for job_id in job_ids
        ),
    )


async def seat_person_on_committee(
    conn: AsyncConnection,
    *,
    scope: JobScope,
    persona: Persona,
    requested_by_user_id: str,
    writer: LenientClaimWriter,
    catalog: FieldCatalog,
) -> bool:
    """Give one person the committee seat the human who launched them named. True when it wrote.

    The account's contact list is not a table of contacts: it is whoever holds a
    ``contact.persona`` claim under the account (the ARV2 committee source in
    ``contact_eligibility`` — founder ruling 2026-09-09: ARV2's own rows are the only truth for
    the accounts screens). The
    committee step writes that claim when an account job confirms a member; a person launched on
    demand had nobody to write it, so they were researched and then invisible on the very screen
    the research was for (walk finding W2).

    The seat is written through the same helper the committee step uses, from a synthetic
    candidate: the human named this person and this seat, so ``rationale`` says exactly that and
    ``confirmed_by`` is absent — there is no page to cite, and citing the launch as if it were
    evidence would be worse than admitting there is none. Writing no URL is not a refusal and is
    not marked ``source_missing`` either: :attr:`~clue_core.ExtractionMethod.HUMAN` is not one of
    the writer's URL-requiring methods (``claim_writer._URL_REQUIRED``), because a human statement
    is not citing a page — and it is tier 1 rather than the model's tier 4.

    A person who **already** holds a live persona claim is left alone. Re-seating them would let a
    launch overwrite the committee's own assessment ("champion", read off a page that says so) with
    a default nobody chose, and the launch's job is to research the person, not to re-decide who
    they are.
    """
    contact_id = scope.person_subject_id
    if contact_id is None:  # pragma: no cover - JobScope.__post_init__ already refuses this
        raise ValueError("seating a person needs a person scope")
    live = await claims_for(
        conn, contact_id, scope=WorkspaceScope.for_workspace(scope.workspace_id)
    )
    if any(str(claim.field_key) == PERSONA_FIELD for claim in live):
        return False
    candidate = {
        "name": scope.person_name,
        "persona": str(persona),
        "rationale": f"launched on demand by {requested_by_user_id}",
        "confirmed_by": None,
    }
    # The seat is this person's: the launch's trace names them.
    tag_entities([contact_id])
    for draft in committee_member_claims(
        candidate,
        scope=scope,
        contact_id=contact_id,
        catalog=catalog,
        method=ExtractionMethod.HUMAN,
    ):
        await writer.write(conn, draft)
    return True


@dataclass(frozen=True)
class _ContactPlace:
    """Where one named contact sits: their employer, and the two names the seat claim needs."""

    account_id: UUID
    account_name: str
    account_domain: str
    person_name: str


async def _check_contacts(
    conn: AsyncConnection, request: Arv2PersonLaunchRequest
) -> dict[UUID, _ContactPlace]:
    """Every named contact must exist here; returns each one's place. Refused by id, not in bulk.

    A contact of another workspace is ``contact_not_found``, not "forbidden": the caller learns
    nothing about a tenant it may not see, and the fix is the same either way — name a contact this
    workspace holds.
    """
    accounts: dict[UUID, _ContactPlace] = {}
    for contact_id in request.contact_entity_ids:
        contact = await get_contact(conn, EntityId(contact_id))
        if contact is None or contact.workspace_id != request.workspace_id:
            raise Arv2LaunchRefused(
                f"contact_not_found:{contact_id}",
                f"no contact {contact_id} in workspace {request.workspace_id!r}; resolve the "
                "person before researching them",
            )
        if contact.merged_into is not None:
            raise Arv2LaunchRefused(
                f"contact_merged:{contact_id}",
                f"contact {contact_id} was merged into {contact.merged_into}; research the "
                "surviving person instead, or their claims land on a row nothing reads",
            )
        account = await get_account(conn, contact.account_entity_id)
        if account is None or account.workspace_id != request.workspace_id:  # pragma: no cover
            # The composite FK should make this unrepresentable; reading it is cheaper than
            # trusting it, because the job row asserts this account and the driver composes it.
            raise Arv2LaunchRefused(
                "contact_without_account",
                f"contact {contact_id} names account {contact.account_entity_id}, which this "
                "workspace does not hold; a person is researched at their employer",
            )
        accounts[contact_id] = _ContactPlace(
            account_id=UUID(str(contact.account_entity_id)),
            account_name=account.canonical_name,
            account_domain=account.primary_domain or "",
            person_name=contact.full_name or "",
        )
    return accounts


def _person_request_sha256(
    request: Arv2PersonLaunchRequest,
    *,
    profile_sha256: str,
    icp_artifact_sha256: str,
    product_selection_version: int,
) -> str:
    """The digest of what was asked for — and therefore the person run's identity.

    The ``"subject": "person"`` discriminator is what keeps a person run distinct from an account
    run of the same project, and the resolved ICP digest and selection version are inside it
    because they are what this research will be pinned to: asking again after the ICP has moved is
    a different request, and must be a different run rather than a quiet replay of the old one.
    """
    payload = {
        "subject": "person",
        "workspace_id": request.workspace_id,
        "project_id": request.project_id,
        "contact_entity_ids": sorted(str(value) for value in request.contact_entity_ids),
        # The seat is part of what was asked for: the same people at a different persona is a
        # different request, and replaying the old run would silently ignore the correction.
        "persona": str(request.persona),
        "icp_artifact_sha256": icp_artifact_sha256,
        "product_selection_version": product_selection_version,
        "directive_text": request.directive_text,
        "profile_sha256": profile_sha256,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# =================================================================================================
# the service seam + its production implementation
# =================================================================================================


class Arv2LaunchService(Protocol):
    """What the toolbelt tools call. One transaction per call is the implementation's business."""

    async def launch(self, request: Arv2LaunchRequest) -> Arv2LaunchReceipt: ...

    async def launch_person(self, request: Arv2PersonLaunchRequest) -> Arv2LaunchReceipt: ...

    async def read_run(self, *, workspace_id: str, run_id: UUID) -> Arv2RunView | None: ...


class DbArv2LaunchService:
    """The production service: one transaction per call, the real fleet queue, the real catalog."""

    def __init__(
        self,
        settings: Settings,
        storage: StorageBackend,
        *,
        queue: WorkQueue | None = None,
        conn_factory: ConnFactory = transaction,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._settings = settings
        self._storage = storage
        self._queue = queue if queue is not None else DbWorkQueue()
        self._conn_factory = conn_factory
        self._now = now

    async def launch(self, request: Arv2LaunchRequest) -> Arv2LaunchReceipt:
        # The profile digest is read at launch time, so a run records the bytes that existed when
        # the human approved it — the driver re-checks them and refuses if they have since moved.
        profile_sha256 = arv2_account_profile_sha256(
            version=self._settings.arv2_research_catalog_version
        )
        async with self._conn_factory() as conn:
            receipt = await launch_arv2_account_research(
                conn,
                request,
                settings=self._settings,
                storage=self._storage,
                profile_sha256=profile_sha256,
                now=self._now,
            )
        # Outside the block, so the rows are committed: a task that reaches a worker always finds
        # its job row. The reverse — rows with no task — is the recoverable half (relaunch and the
        # jobs are re-offered); a task with no row is not, so it must never happen.
        await enqueue_launched_jobs(self._queue, receipt)
        return receipt

    async def launch_person(self, request: Arv2PersonLaunchRequest) -> Arv2LaunchReceipt:
        # The person profile's digest, read at launch time for the same reason the account launch
        # reads its own: the run records the bytes that existed when the human asked, and the
        # driver refuses a job whose profile has moved since.
        profile_sha256 = arv2_person_profile_sha256(
            version=self._settings.arv2_research_catalog_version
        )
        async with self._conn_factory() as conn:
            receipt = await launch_arv2_person_research(
                conn,
                request,
                settings=self._settings,
                storage=self._storage,
                profile_sha256=profile_sha256,
                now=self._now,
            )
        await enqueue_launched_jobs(self._queue, receipt)
        return receipt

    async def read_run(self, *, workspace_id: str, run_id: UUID) -> Arv2RunView | None:
        async with self._conn_factory() as conn:
            run = await read_run(conn, run_id=run_id)
            if run is None or run.workspace_id != workspace_id:
                # A run of another workspace is *absent*, not forbidden: the caller learns nothing
                # about a tenant it may not see.
                return None
            return Arv2RunView(run=run, jobs=await list_jobs(conn, run_id=run_id))


# =================================================================================================
# the two toolbelt tools
# =================================================================================================


class LaunchArv2AccountResearchInput(ToolInput):
    project_id: str
    account_entity_ids: tuple[str, ...] = Field(min_length=1, max_length=200)
    icp_artifact_key: str
    icp_artifact_sha256: str
    product_selection_version: int = Field(ge=1)
    effort: Arv2Effort = "full"
    committee_cap: int = Field(5, ge=1, le=12)
    directive_text: str = ""


class LaunchArv2AccountResearchOutput(ToolOutput):
    run_id: str
    job_ids: tuple[str, ...]
    replayed: bool


class LaunchArv2PersonResearchInput(ToolInput):
    project_id: str
    contact_entity_ids: tuple[str, ...] = Field(min_length=1, max_length=50)
    directive_text: str = ""
    #: The committee seat every named person is given, from the platform's closed vocabulary. It
    #: is what makes them visible on their account's contact list at all (W2), and it is only
    #: written for a person who does not already hold a seat.
    persona: Persona = Persona.USER


class LaunchArv2PersonResearchOutput(ToolOutput):
    run_id: str
    job_ids: tuple[str, ...]
    replayed: bool


class ReadArv2AccountResearchRunInput(ToolInput):
    run_id: str


class ReadArv2AccountResearchRunOutput(ToolOutput):
    run_id: str
    status: str
    icp_artifact_key: str
    product_selection_version: int
    effort: str
    committee_cap: int
    jobs: tuple[dict[str, str], ...]


def _not_composed() -> tuple[PreconditionFailure, ...]:
    return (
        PreconditionFailure(
            reason_code="arv2_account_research_not_composed",
            message=(
                "the ARV2 account-research lane is not composed on this deployment "
                "(CLUE_ARV2_ACCOUNT_RESEARCH_ENABLED)"
            ),
        ),
    )


def _trusted_action(ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
    if ctx.action_ref is None:
        return (
            PreconditionFailure(
                reason_code="launch_action_ref_missing",
                message=(
                    "launching account research requires the captured user action that approved "
                    "this exact account set"
                ),
            ),
        )
    return ()


def _trusted_person_action(ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
    if ctx.action_ref is None:
        return (
            PreconditionFailure(
                reason_code="launch_action_ref_missing",
                message=(
                    "launching person research requires the captured user action that approved "
                    "researching these exact people"
                ),
            ),
        )
    return ()


class LaunchArv2AccountResearchTool(Tool):
    name = "launch_arv2_account_research"
    version = "1"
    model_description = (
        "Launch (or exactly replay) ARV2 account research: one governed research job per selected "
        "account on the shared fleet, pinned to the confirmed ICP artifact digest and the "
        "project's confirmed product-selection version. Call only when the current user action "
        "explicitly approves this exact account set and ICP. A successful result means the jobs "
        "were enqueued or replayed; it never means research has completed, and it authorizes no "
        "contact research. "
        "Before launching, read .deepagent/skills/account-research-briefing/v3/SKILL.md and "
        "write the project-specific delegation brief it teaches in directive_text, with "
        "account placeholders and references to the complete pinned documents. "
        + tool_manual_link("launch_arv2_account_research")
    )
    input_model = LaunchArv2AccountResearchInput
    output_model = LaunchArv2AccountResearchOutput
    effect_class = ToolEffectClass.SPEND
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity=(
            "workspace + project + account set + ICP digest + product-set version + profile digest"
        ),
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=(
            "project_id",
            "account_entity_ids",
            "icp_artifact_key",
            "product_selection_version",
            "effort",
            "committee_cap",
        )
    )
    #: ``project`` is the spine row the execution is bound to — a replay identity, not a Stage-0
    #: pin (standing rule item 5).
    pin_requirements = ("project",)

    def __init__(self, service: Arv2LaunchService | None) -> None:
        self._service = service

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> tuple[PreconditionFailure, ...]:
        del inputs
        return _not_composed() if self._service is None else _trusted_action(ctx)

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        assert isinstance(inputs, LaunchArv2AccountResearchInput)
        # A research job's spend is governed by the lane's own ceilings and settles in
        # ``provider_call_ledger`` per call; there is no honest per-account prior to quote here, so
        # the estimate carries the *shape* of the spend (how many accounts) rather than a number
        # nobody derived.
        return ToolEstimate(
            cost_cents=Decimal(0),
            detail={
                "basis": "arv2_account_research_per_account_ceilings",
                "accounts": len(inputs.account_entity_ids),
            },
        )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, LaunchArv2AccountResearchInput)
        assert self._service is not None and ctx.action_ref is not None
        request = Arv2LaunchRequest(
            # The tenant and the requesting human are AMBIENT authority, never model-authored.
            workspace_id=ctx.workspace_id,
            project_id=inputs.project_id,
            account_entity_ids=tuple(UUID(value) for value in inputs.account_entity_ids),
            icp_artifact_key=inputs.icp_artifact_key,
            icp_artifact_sha256=inputs.icp_artifact_sha256,
            product_selection_version=inputs.product_selection_version,
            requested_by_user_id=ctx.actor_id or ctx.actor,
            effort=inputs.effort,
            committee_cap=inputs.committee_cap,
            directive_text=inputs.directive_text,
        )
        try:
            receipt = await self._service.launch(request)
        except Arv2LaunchRefused as refused:
            raise PreconditionFailed([PreconditionFailure(refused.code, str(refused))]) from refused
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "run_id": str(receipt.run_id),
                "job_ids": [str(job_id) for job_id in receipt.job_ids],
                "replayed": receipt.replayed,
            },
            replayed=receipt.replayed,
        )


class LaunchArv2PersonResearchTool(Tool):
    name = "launch_arv2_person_research"
    version = "1"
    model_description = (
        "Launch (or exactly replay) ARV2 person research on named contacts of this workspace: one "
        "governed research job per person on the shared fleet, under a run of its own pinned to "
        "the project's currently confirmed ICP and product selection. Call only when the current "
        "user action explicitly approves researching these exact people. It researches existing "
        "contacts and never creates a person; a successful result means the jobs were enqueued or "
        "replayed, never that research has completed. ``persona`` is the committee seat each "
        "named person is given if they do not already hold one — it is what puts them on the "
        "account's contact list — and defaults to ``user``. "
        + tool_manual_link("launch_arv2_person_research")
    )
    input_model = LaunchArv2PersonResearchInput
    output_model = LaunchArv2PersonResearchOutput
    effect_class = ToolEffectClass.SPEND
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity=(
            "workspace + project + contact set + resolved ICP digest + product-set version + "
            "profile digest"
        ),
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=("project_id", "contact_entity_ids", "persona")
    )
    #: No Stage-0 pin, for the same reason the account launch has none (standing rule item 5).
    #: ``project`` is the spine row the execution is bound to — a replay identity, not a Stage-0
    #: pin — and it is what the recipe-safety audit requires of every standing address.
    pin_requirements = ("project",)

    def __init__(self, service: Arv2LaunchService | None) -> None:
        self._service = service

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> tuple[PreconditionFailure, ...]:
        del inputs
        return _not_composed() if self._service is None else _trusted_person_action(ctx)

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        assert isinstance(inputs, LaunchArv2PersonResearchInput)
        return ToolEstimate(
            cost_cents=Decimal(0),
            detail={
                "basis": "arv2_person_research_per_person_ceilings",
                "people": len(inputs.contact_entity_ids),
            },
        )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, LaunchArv2PersonResearchInput)
        assert self._service is not None and ctx.action_ref is not None
        request = Arv2PersonLaunchRequest(
            # The tenant and the requesting human are AMBIENT authority, never model-authored.
            workspace_id=ctx.workspace_id,
            project_id=inputs.project_id,
            contact_entity_ids=tuple(UUID(value) for value in inputs.contact_entity_ids),
            requested_by_user_id=ctx.actor_id or ctx.actor,
            directive_text=inputs.directive_text,
            persona=inputs.persona,
        )
        try:
            receipt = await self._service.launch_person(request)
        except Arv2LaunchRefused as refused:
            raise PreconditionFailed([PreconditionFailure(refused.code, str(refused))]) from refused
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "run_id": str(receipt.run_id),
                "job_ids": [str(job_id) for job_id in receipt.job_ids],
                "replayed": receipt.replayed,
            },
            replayed=receipt.replayed,
        )


class ReadArv2AccountResearchRunTool(Tool):
    name = "read_arv2_account_research_run"
    version = "1"
    model_description = (
        "Read one ARV2 account-research run: what it was pinned to, its status, and the state of "
        "each account's job (including the failure code of anything that needs review). Effect-"
        "free; it never starts, resumes or changes research. "
        + tool_manual_link("read_arv2_account_research_run")
    )
    input_model = ReadArv2AccountResearchRunInput
    output_model = ReadArv2AccountResearchRunOutput
    effect_class = ToolEffectClass.READ
    replay = ReplaySafety(
        policy=ReplayPolicy.EFFECT_FREE,
        durable_identity="current ARV2 account research run + job states",
    )
    parameter_policy = JournalParameterPolicy(safe_display_fields=("run_id",))
    #: ``project`` is the spine row the execution is bound to — a replay identity, not a Stage-0
    #: pin (standing rule item 5).
    pin_requirements = ("project",)

    def __init__(self, service: Arv2LaunchService | None) -> None:
        self._service = service

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> tuple[PreconditionFailure, ...]:
        del inputs, ctx
        return _not_composed() if self._service is None else ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ReadArv2AccountResearchRunInput)
        assert self._service is not None
        view = await self._service.read_run(
            workspace_id=ctx.workspace_id, run_id=UUID(inputs.run_id)
        )
        if view is None:
            # Absent is a typed refusal, not an empty success: "no such run here" is actionable,
            # an empty run projection is a lie about a run that may be running elsewhere.
            raise PreconditionFailed(
                [
                    PreconditionFailure(
                        "arv2_account_research_run_not_found",
                        f"no ARV2 account-research run {inputs.run_id} in this workspace",
                    )
                ]
            )
        references: dict[str, Any] = {
            "run_id": str(view.run.run_id),
            "status": view.run.status,
            "icp_artifact_key": view.run.icp_artifact_key,
            "product_selection_version": view.run.product_selection_version,
            "effort": view.run.effort,
            "committee_cap": view.run.committee_cap,
            "jobs": [
                {
                    "job_id": str(job.job_id),
                    "account_entity_id": str(job.account_entity_id),
                    "status": job.status,
                    "failure_code": job.failure_code or "",
                }
                for job in view.jobs
            ],
        }
        return ToolResult(tool=self.name, version=self.version, references=references)


def build_arv2_launch_tools(service: Arv2LaunchService | None) -> tuple[Tool, ...]:
    """The lane's three toolbelt surfaces. Registered always; composed only behind the flag.

    Registering them uncomposed is deliberate: the platform's write surface stays complete (the
    authority audit sees every tool), and an agent that reaches for a launch on a deployment
    without the lane gets the named ``arv2_account_research_not_composed`` refusal rather than an
    ``UnknownTool`` it cannot explain to the human.
    """
    return (
        LaunchArv2AccountResearchTool(service),
        LaunchArv2PersonResearchTool(service),
        ReadArv2AccountResearchRunTool(service),
    )
