"""R4 seam 1: what a human asked to discover, turned into one replayable run and one fleet task.

This is the only door into the discovery lane, and the run row it writes is the authorization
record — the exact ICP document version the long list is built from, how many companies were
asked for, and which of the document's hard gates become webset criteria. Everything the driver
later spends is spent against that row, so a run whose pinned bytes have moved is a different
request and gets a different run.

The three properties R2's launch pins, pinned again here because they are the same three:

* **Every refusal is typed** (:class:`Arv2DiscoveryRefused` with a stable ``code``), never a stack
  trace. The toolbelt tool turns each straight into a
  :class:`~clue_toolbelt.PreconditionFailed`, so the human is told which prerequisite is missing.
* **The run id is the digest of the request, and the request includes the human's ask.** Every
  time a human asks for accounts is a new run — "find me 10 more" is never answered by replaying
  a finished run (founder ruling 2026-09-28) — while the same ask retried (a turn that replayed, a
  task redelivered) is the same run, one set of websets and one bill.
* **Rows first, offer second.** The launch takes no queue and cannot reach one; the caller offers
  the task through :func:`enqueue_discovery_run` once the transaction has committed. See
  :class:`Arv2DiscoveryReceipt` for why that ordering is the safety property.

The brief is the Head of ABM's own (spec 2026-09-30 §3): the query, the criteria and the gates
arrive on the request, are stored whole on the run, and nothing is compiled out of the ICP
document — the pinned ICP version is recorded as the context the agent was reading. A project runs
**one** discovery at a time: a second ask while one is active is refused by name
(``discovery_in_progress``), and the partial unique index ``arv2_discovery_run_project_active`` is
what makes that structural when two asks race.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, ClassVar, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.manual import tool_manual_link
from clue_api.arv2.discovery_request import BriefGate, DiscoveryBrief2, DiscoverySource
from clue_api.arv2.discovery_store import (
    DiscoveryRunRow,
    active_discovery_for_project,
    create_discovery_run,
    read_discovery_run,
    release_discovery_for_turn,
)
from clue_api.arv2.errors import Arv2Error
from clue_api.arv2.fleet_task import (
    ARV2_DISCOVERY_DEDUP_PREFIX,
    ARV2_DISCOVERY_TASK_PRIORITY,
    arv2_discovery_work_id,
)
from clue_api.arv2.icp_confirmation import current_project_icp_pin
from clue_api.arv2.knowledge_frontmatter import parse_front_matter
from clue_config import Settings
from clue_core import ProjectPhase, ProjectRunId
from clue_db import ConnFactory, transaction
from clue_fleet import DbWorkQueue, FleetTaskKind, WorkQueue
from clue_obs import get_logger
from clue_research.claimstore.run_lineage import record_run_lineage
from clue_research.durable.project_run import ensure_project_run
from clue_spine import get_project
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

log = get_logger("clue_api.arv2.discovery_launch")

__all__ = [
    "ARV2_DISCOVERY_DEDUP_PREFIX",
    "ARV2_DISCOVERY_TASK_PRIORITY",
    "Arv2DiscoveryReceipt",
    "Arv2DiscoveryRefused",
    "Arv2DiscoveryRequest",
    "Arv2DiscoveryService",
    "DbArv2DiscoveryService",
    "LaunchArv2DiscoveryInput",
    "LaunchArv2DiscoveryOutput",
    "LaunchArv2DiscoveryTool",
    "LaunchArv2DiscoveryV2Input",
    "LaunchArv2DiscoveryV2Tool",
    "PinnedIcpDocument",
    "arv2_discovery_work_id",
    "build_arv2_discovery_tools",
    "enqueue_discovery_run",
    "launch_arv2_discovery",
    "read_icp_document",
    "read_pinned_icp",
]

#: The document kind and status a discovery run will build a long list from. Anything else is a
#: refusal, for the reason the account launch gives: a ``proposed`` ICP is a draft nobody agreed
#: to, and spending on it would search for an audience the client never confirmed.
_ICP_KIND = "icp-definition"
_ICP_STATUS = "confirmed"

#: The run id is the digest of the request, under this lane's own namespace — so an R4 run id can
#: never collide with an R2 run id derived from the same bytes.
_DISCOVERY_RUN_NS = uuid5(NAMESPACE_URL, "arv2-discovery:run")

#: The document a project pinned, read by id — the exact version a human approved, never "the
#: newest row that happens to carry these bytes". The account launch reads it with the same
#: statement; the two are deliberately identical reads of the same contract.
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
class Arv2DiscoveryRequest:
    """One ask: find me companies with the brief the Head of ABM wrote for this project.

    ``brief`` is required by the launch (``None`` refuses ``brief_required``); it is optional on the
    dataclass only so a caller that has not been rewritten yet gets that named refusal rather than
    a ``TypeError``.
    """

    workspace_id: str
    project_id: str
    requested_by_user_id: str
    #: The human's ask this run answers — the captured user action for a tool call, a key the
    #: operator chooses for the CLI. It is part of the run id, so every new ask is a new run and
    #: the same ask retried is the same run.
    request_key: str
    #: The ``turn-action:`` ref of the turn a fleet-driven launch acts for; when set, the human
    #: who submitted that turn becomes the run's requester (and every discovered account's
    #: creator and owner) in place of the service principal that invoked the tool.
    launching_turn_ref: str | None = None
    target_count: int = 20
    project_run_id: UUID | None = None
    #: The search the Head of ABM wrote: source, query, criteria and role-bearing gates.
    brief: DiscoveryBrief2 | None = None


class Arv2DiscoveryRefused(Arv2Error):
    """A discovery prerequisite is unmet. ``code`` is stable and machine-readable.

    Codes: ``lane_disabled``, ``target_count_invalid``, ``brief_required``,
    ``project_not_found``, ``project_icp_not_pinned``, ``icp_artifact_not_found``,
    ``icp_artifact_not_confirmed``, ``icp_digest_mismatch``, ``icp_front_matter_invalid``,
    ``discovery_in_progress``. (The v2 tool adds ``brief_invalid`` before a request exists.)

    The ICP codes are deliberately spelled the same as the account launch's: they are the same
    prerequisite failing on the same document, and a human who has learned what
    ``icp_digest_mismatch`` means should not have to learn a second word for it.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Arv2DiscoveryReceipt:
    """What the launch did, and what the caller still owes the fleet.

    ``to_enqueue`` is that debt. The launch deliberately does not pay it: ``DbTaskQueue.enqueue``
    commits in its own transaction, so an offer made inside the launch's transaction is visible to
    a polling worker **before** the run row it names is — and that worker reads "no such run" as
    "already done" and finishes the task, dropping the discovery permanently. Rows first, offer
    second (the O3 rule, ``onboarding_routes``).

    It is ``True`` only while the run is ``not_started``: a run another worker is already driving
    has its task, and a finished one is never re-offered — asking for more is a new run.
    """

    run_id: UUID
    replayed: bool
    project_run_id: UUID
    workspace_id: str
    to_enqueue: bool


@dataclass(frozen=True)
class PinnedIcpDocument:
    """The confirmed ICP document a project pinned, whole: its front matter, its body, its pins.

    The launch needs the *document*, not a summary of it, because the brief the run executes — the
    long-list query, the webset criteria, the gates the verifier asks — is compiled out of these
    exact bytes (spec §2: the ICP document is the program). The driver reads it again at the start
    of every attempt — by the run's OWN pinned key, through :func:`read_icp_document` — so a
    resumed run recompiles the same brief even when the project has since repinned.

    ``brand_id`` is the brand that owns the document *row*, and only the pin path
    (:func:`read_pinned_icp`) resolves one: it is read off ``brand_knowledge_document`` while the
    pin is being resolved. :func:`read_icp_document` is handed an artifact key and nothing else,
    and an artifact key is content-addressed rather than brand-keyed, so it leaves this empty
    rather than guessing — its one caller (the driver) already carries the brand on its run row.
    """

    front: Mapping[str, Any]
    body: str
    artifact_key: str
    artifact_sha256: str
    icp_key: str
    icp_version: int
    #: The owning brand, or ``""`` when the document was read by artifact key. See the class
    #: docstring: never a guess, and never read by the run-pinned path.
    brand_id: str = ""


async def read_pinned_icp(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    project_id: str,
) -> PinnedIcpDocument:
    """The ICP document this project pinned, or a typed refusal — never a fallback to another.

    Founder rulings 2026-09-10: a project works against the one confirmed ICP version a human
    pinned for it. Resolving "the brand's newest confirmed" instead would let a re-synthesis, or
    another project's confirmation, silently repoint what this project spends money discovering.
    """
    pin = await current_project_icp_pin(conn, workspace_id=workspace_id, project_id=project_id)
    if pin is None:
        raise Arv2DiscoveryRefused(
            "project_icp_not_pinned",
            f"project {project_id!r} has not pinned a confirmed {_ICP_KIND}; confirm one at the "
            "ICP gate before discovering anything",
        )
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
        raise Arv2DiscoveryRefused(
            "icp_artifact_not_found",
            f"the pinned document {pin.document_id} is not held by workspace {workspace_id!r}",
        )
    row: Mapping[str, Any] = dict(found)
    if row["kind"] != _ICP_KIND or row["status"] != _ICP_STATUS:
        raise Arv2DiscoveryRefused(
            "icp_artifact_not_confirmed",
            f"document {row['path']!r} is a {row['kind']!r} at status {row['status']!r}; a "
            f"discovery run searches only against a {_ICP_STATUS} {_ICP_KIND}",
        )
    if row["artifact_sha256"] != pin.artifact_sha256:
        raise Arv2DiscoveryRefused(
            "icp_digest_mismatch",
            "the pinned ICP document's bytes are not the ones the project pinned: stored "
            f"{row['artifact_sha256']}, pinned {pin.artifact_sha256}",
        )
    return await _icp_document(
        conn,
        storage,
        workspace_id=workspace_id,
        artifact_key=str(row["artifact_key"]),
        artifact_sha256=str(row["artifact_sha256"]),
        brand_id=str(row["brand_id"]),
        label=str(row["path"]),
    )


async def read_icp_document(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    artifact_key: str,
    artifact_sha256: str,
) -> PinnedIcpDocument:
    """The ICP document *one run* was pinned to, read by its own key and checked against its sha.

    This is the driver's read, and it is deliberately NOT :func:`read_pinned_icp`. The launch
    resolves what the project points at **now**; a run resolves what it was authorized against,
    which is the pair of columns the run row carries (``icp_artifact_key`` /
    ``icp_artifact_sha256``). Reading the current pin instead would let a human who repinned the
    project while a run was queued or suspended silently move the gates mid-run: the candidates
    already landed would have been graded against one document and the rest against another, under
    one run id whose row still names the first. A digest that has moved refuses by name
    (``icp_digest_mismatch``) so the driver contains it as ``needs_review`` and a human relaunches.

    The R2 sibling reads its pin exactly this way (``account_research_driver._pinned_icp``).
    """
    return await _icp_document(
        conn,
        storage,
        workspace_id=workspace_id,
        artifact_key=artifact_key,
        artifact_sha256=artifact_sha256,
        brand_id="",
        label=artifact_key,
    )


async def _icp_document(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    artifact_key: str,
    artifact_sha256: str,
    brand_id: str,
    label: str,
) -> PinnedIcpDocument:
    """The bytes at ``artifact_key``, checked against ``artifact_sha256`` and parsed.

    The half both readers share: read the artifact, refuse when its content digest is not the one
    the caller pinned, parse the front matter, and refuse by name when the document names no
    ``icp_key``/``version``. ``label`` is what a refusal calls the document — its path when the
    caller resolved a row, its artifact key when it did not.
    """
    record, blob = await read_verified_artifact(
        conn,
        storage,
        storage_key=artifact_key,
        workspace_id=workspace_id,
    )
    if record.content_sha256 != artifact_sha256:
        raise Arv2DiscoveryRefused(
            "icp_digest_mismatch",
            f"document {label!r} does not hold the bytes it was pinned to: stored "
            f"{record.content_sha256}, pinned {artifact_sha256}",
        )
    try:
        front, body = parse_front_matter(blob.decode("utf-8"))
    except ValueError as unreadable:
        raise Arv2DiscoveryRefused(
            "icp_front_matter_invalid",
            f"document {label!r} carries no readable YAML front matter: {unreadable}",
        ) from unreadable
    # The run pins the ICP by key and version, and both come from the document itself. A document
    # missing either is a malformed pin, and a malformed pin must refuse by name rather than raise
    # a ``KeyError``/``ValueError`` out of the launcher at the operator.
    icp_key = front.get("icp_key")
    version = front.get("version")
    if not isinstance(icp_key, str) or not icp_key.strip():
        raise Arv2DiscoveryRefused(
            "icp_front_matter_invalid",
            f"document {label!r} names no icp_key; a run is pinned to the ICP's own key",
        )
    if not isinstance(version, int) or isinstance(version, bool):
        raise Arv2DiscoveryRefused(
            "icp_front_matter_invalid",
            f"document {label!r} has version {version!r}, which is not an integer; a run is "
            "pinned to the ICP version the human confirmed",
        )
    return PinnedIcpDocument(
        front=front,
        body=body,
        artifact_key=artifact_key,
        artifact_sha256=artifact_sha256,
        icp_key=icp_key,
        icp_version=version,
        brand_id=brand_id,
    )


#: The human who submitted a turn, by the turn's own durable submission row — the same row the
#: gate tools address a gate to. Read here with the lane's own statement: ``clue_api.arv2`` may
#: not import ``clue_api.turn_action`` (Global Constraint 7), and the read is two columns.
_TURN_SUBMITTER = text(
    """
    SELECT submitted_by_user_id FROM agent_turn_submission
    WHERE turn_id = :turn_id AND workspace_id = :workspace_id
    """
)
_TURN_ACTION_PREFIX = "turn-action:"

#: The conversation a turn was submitted to — the thread a discovery run holds busy and wakes.
_TURN_THREAD = text(
    "SELECT thread_id FROM agent_turn_submission WHERE turn_id = :turn_id AND workspace_id = :w"
)


async def _requesting_human(conn: AsyncConnection, request: Arv2DiscoveryRequest) -> str:
    """Who requested this run, as the accounts table can name them (ruling 10′, 2026-09-11).

    A human invoker is the requester. A fleet-driven launch names the service principal and
    carries ``launching_turn_ref`` (``turn-action:<uuid>``); then the human who submitted that
    turn is the requester — the same rule the gate tools use to address a gate. If the ref does
    not resolve to a turn of this workspace with a human submitter, the invoker's id stands, and
    the driver (which checks the id against ``platform_user``) creates the accounts unowned
    rather than failing the run.
    """
    ref = request.launching_turn_ref
    if ref is None or not ref.startswith(_TURN_ACTION_PREFIX):
        return request.requested_by_user_id
    try:
        turn_id = UUID(ref[len(_TURN_ACTION_PREFIX) :])
    except ValueError:
        return request.requested_by_user_id
    row = (
        await conn.execute(
            _TURN_SUBMITTER, {"turn_id": turn_id, "workspace_id": request.workspace_id}
        )
    ).first()
    submitter = None if row is None else row[0]
    return str(submitter) if submitter else request.requested_by_user_id


async def _launching_turn(
    conn: AsyncConnection, request: Arv2DiscoveryRequest
) -> tuple[UUID | None, str | None]:
    """The turn this launch acts for and its thread, or ``(None, None)`` outside a chat turn.

    A fleet-driven launch names its turn in ``launching_turn_ref``; a human invoker's ask is its own
    turn's action ref (``request_key``). Either way the same ``turn-action:<uuid>`` parse as
    :func:`_requesting_human`, and a ref that does not resolve to a turn of this workspace is no
    thread at all rather than a guess.
    """
    ref = request.launching_turn_ref or request.request_key
    if not ref or not ref.startswith(_TURN_ACTION_PREFIX):
        return None, None
    try:
        turn_id = UUID(ref[len(_TURN_ACTION_PREFIX) :])
    except ValueError:
        return None, None
    thread = await conn.scalar(_TURN_THREAD, {"turn_id": turn_id, "w": request.workspace_id})
    return (turn_id, str(thread)) if thread else (None, None)


def _request_sha256(
    request: Arv2DiscoveryRequest, *, brief: DiscoveryBrief2, icp_artifact_sha256: str
) -> str:
    """The digest of what was asked for — and therefore the run's identity.

    Every field is what the ask carried: a different ask, a different target, a different brief or
    a moved ICP is a different question, so it is a different run rather than a quiet reuse of one
    that answered something else. The brief is dumped whole, in its own order, because the order
    of its criteria and gates is the order they are sent and asked in.
    """
    payload = {
        "workspace_id": request.workspace_id,
        "project_id": request.project_id,
        "request_key": request.request_key,
        "icp_artifact_sha256": icp_artifact_sha256,
        "target_count": request.target_count,
        "brief": brief.model_dump(mode="json"),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _in_progress(active: DiscoveryRunRow | None) -> Arv2DiscoveryRefused:
    """The refusal a second ask gets while the project's discovery is active, naming that run."""
    if active is None:
        # The rival released between the index violation and the re-read: it still held the
        # project when this insert raced it, so the ask is refused the same way, unnamed.
        return Arv2DiscoveryRefused(
            "discovery_in_progress",
            "another discovery run held this project when this one was launched; ask again",
        )
    return Arv2DiscoveryRefused(
        "discovery_in_progress",
        f"discovery run {active.run_id} is already running in conversation "
        f"{active.launched_thread_id or 'outside chat'} of this project",
    )


async def launch_arv2_discovery(
    conn: AsyncConnection,
    request: Arv2DiscoveryRequest,
    *,
    settings: Settings,
    storage: StorageBackend,
    now: Callable[[], datetime] = _utcnow,
) -> Arv2DiscoveryReceipt:
    """Validate the request and write the discovery run. **It queues nothing.**

    Checks run in cost order — the free ones first — so a launch that cannot happen refuses before
    it reads an artifact. Nothing is written until every check has passed, and the project lock is
    checked before the first write: the only way past it is to be the same ask replayed.
    """
    if not settings.arv2_discovery_enabled:
        raise Arv2DiscoveryRefused(
            "lane_disabled", "CLUE_ARV2_DISCOVERY_ENABLED is false on this deployment"
        )
    # The tool's input model bounds this 1–500; the CLI and direct callers do not, and a run for
    # zero companies would buy a webset nobody can use.
    if request.target_count < 1:
        raise Arv2DiscoveryRefused(
            "target_count_invalid",
            f"a discovery run must ask for at least one company, not {request.target_count}",
        )
    brief = request.brief
    if brief is None:
        raise Arv2DiscoveryRefused(
            "brief_required", "a discovery run is launched with the brief the Head of ABM wrote"
        )

    # The project comes first: every check after this one is a question *about* a project — which
    # ICP it pinned — so a request naming a project that does not exist must be told THAT, rather
    # than "you have pinned no ICP", which is true of a non-existent project and useless.
    project = await get_project(conn, request.project_id)
    if project is None or project.workspace_id != request.workspace_id:
        raise Arv2DiscoveryRefused(
            "project_not_found",
            f"project {request.project_id!r} has no row in workspace {request.workspace_id!r}, "
            "so there is no project run to discover under",
        )
    icp = await read_pinned_icp(
        conn, storage, workspace_id=request.workspace_id, project_id=request.project_id
    )
    requested_by = await _requesting_human(conn, request)

    launching_turn_id, launched_thread_id = await _launching_turn(conn, request)

    request_sha = _request_sha256(request, brief=brief, icp_artifact_sha256=icp.artifact_sha256)
    run_id = uuid5(_DISCOVERY_RUN_NS, request_sha)
    # Checked before the first write, so a refused ask writes nothing — not even the project run.
    # A replay of this very ask while its own run is active is not a rival; it replays below.
    active = await active_discovery_for_project(
        conn, workspace_id=request.workspace_id, project_id=request.project_id
    )
    # The one exception is the run's own wake turn: it holds the lock until it finishes, and it is
    # the only turn that may search again on the agent's own judgement (Ruling 11). Its launch
    # takes the lock over — the ended run is released inside the insert's savepoint below, so the
    # thread passes straight from the old run to the new one and nothing else can get in between.
    takes_over = (
        active is not None
        and active.request_sha256 != request_sha
        and launching_turn_id is not None
        and active.wake_turn_id == launching_turn_id
    )
    if active is not None and active.request_sha256 != request_sha and not takes_over:
        raise _in_progress(active)

    project_run_id = request.project_run_id or uuid5(
        NAMESPACE_URL,
        f"arv2-project-run:{request.project_id}:{icp.icp_key}:{icp.icp_version}",
    )
    # The same deterministic project run the account launch joins, so a project's discovery and
    # the research it feeds hang off one row rather than two that nothing relates.
    await ensure_project_run(
        conn,
        project_run_id=ProjectRunId(project_run_id),
        project_id=request.project_id,
        workspace_id=request.workspace_id,
        icp_key=icp.icp_key,
        icp_version=icp.icp_version,
        phase=ProjectPhase.DEEP,
    )

    row = DiscoveryRunRow(
        run_id=run_id,
        workspace_id=request.workspace_id,
        project_id=request.project_id,
        brand_id=icp.brand_id,
        project_run_id=project_run_id,
        icp_artifact_key=icp.artifact_key,
        icp_artifact_sha256=icp.artifact_sha256,
        icp_key=icp.icp_key,
        icp_version=icp.icp_version,
        requested_by_user_id=requested_by,
        request_sha256=request_sha,
        target_count=request.target_count,
        # No relaxed pass and no compiled criteria: the brief carries the search (spec §3).
        relaxed_enabled=False,
        criteria_gate_keys=(),
        created_at=now(),
        source=brief.source,
        brief=brief.model_dump(mode="json"),
        launched_thread_id=launched_thread_id,
        launching_turn_id=launching_turn_id,
    )
    try:
        # A savepoint, so the race's loser can be refused by name without poisoning the caller's
        # transaction: two asks that both passed the check above (neither saw the other's
        # uncommitted row) meet at the partial unique index, and only one of them holds the
        # project.
        async with conn.begin_nested():
            if takes_over and active is not None and launching_turn_id is not None:
                await release_discovery_for_turn(
                    conn, workspace_id=request.workspace_id, turn_id=launching_turn_id
                )
                log.info(
                    "arv2.discovery_lock_taken_over",
                    released_run_id=str(active.run_id),
                    run_id=str(run_id),
                    turn_id=str(launching_turn_id),
                )
            inserted = await create_discovery_run(conn, row)
    except IntegrityError as collided:
        if "arv2_discovery_run_project_active" not in str(collided):
            raise
        raise _in_progress(
            await active_discovery_for_project(
                conn, workspace_id=request.workspace_id, project_id=request.project_id
            )
        ) from collided
    await record_run_lineage(
        conn,
        run_id=run_id,
        workspace_id=request.workspace_id,
        kind="discovery",
        project_id=request.project_id,
        project_run_id=project_run_id,
    )

    # Read back rather than assume: on a replay the row's status is whatever the run has since
    # become, and that status is exactly what decides whether the fleet still owes it a task.
    run = await read_discovery_run(conn, run_id=run_id)
    log.info(
        "arv2.discovery_launched",
        run_id=str(run_id),
        project_id=request.project_id,
        target_count=request.target_count,
        replayed=not inserted,
        status=run.status if run is not None else "unknown",
    )
    return Arv2DiscoveryReceipt(
        run_id=run_id,
        replayed=not inserted,
        project_run_id=project_run_id,
        workspace_id=request.workspace_id,
        to_enqueue=run is not None and run.status == "not_started",
    )


async def enqueue_discovery_run(queue: WorkQueue, receipt: Arv2DiscoveryReceipt) -> bool:
    """Offer a committed run to the fleet; returns whether the queue accepted the offer.

    Call this only once the transaction has committed. A receipt that owes nothing
    (``to_enqueue`` false — the run is already being driven, or finished and nobody asked for the
    relaxed pass) offers nothing and returns ``False``.

    ``reopen_terminal`` stays ``True`` so a relaunch of a run whose offer was lost after the
    commit re-offers it; the dedup key still makes re-offering a *live* task a no-op, and a
    finished run is never offered at all (``to_enqueue`` is false).
    """
    if not receipt.to_enqueue:
        log.info("arv2.discovery_enqueue_skipped", run_id=str(receipt.run_id))
        return False
    try:
        offered = await queue.enqueue(
            kind=FleetTaskKind.ARV2_DISCOVERY,
            work_id=arv2_discovery_work_id(receipt.run_id),
            dedup_key=f"{ARV2_DISCOVERY_DEDUP_PREFIX}{receipt.run_id}",
            priority=ARV2_DISCOVERY_TASK_PRIORITY,
            payload={"run_id": str(receipt.run_id), "workspace_id": receipt.workspace_id},
            reopen_terminal=True,
        )
    except Exception:
        # Broad on purpose (the O3 shape): a transport error, a pool timeout and a bug in the queue
        # are one fact here — this run was not offered — and the log has to name it or nobody can
        # tell which run is waiting on a task that was never bought.
        log.exception("arv2.discovery_enqueue_failed", run_id=str(receipt.run_id))
        raise
    log.info("arv2.discovery_enqueued", run_id=str(receipt.run_id), offered=offered)
    return offered


# =================================================================================================
# the service seam + its production implementation
# =================================================================================================


class Arv2DiscoveryService(Protocol):
    """What the toolbelt tool calls. One transaction per call is the implementation's business."""

    async def launch(self, request: Arv2DiscoveryRequest) -> Arv2DiscoveryReceipt: ...


class DbArv2DiscoveryService:
    """The production service: one transaction per call, then the real fleet queue."""

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

    async def launch(self, request: Arv2DiscoveryRequest) -> Arv2DiscoveryReceipt:
        async with self._conn_factory() as conn:
            receipt = await launch_arv2_discovery(
                conn,
                request,
                settings=self._settings,
                storage=self._storage,
                now=self._now,
            )
        # Outside the block, so the row is committed: a task that reaches a worker always finds its
        # run. The reverse — a row with no task — is the recoverable half (relaunch and it is
        # re-offered); a task with no row is not, so it must never happen.
        await enqueue_discovery_run(self._queue, receipt)
        return receipt


# =================================================================================================
# the toolbelt tool
# =================================================================================================


class LaunchArv2DiscoveryInput(ToolInput):
    project_id: str
    target_count: int = Field(default=20, ge=1, le=500)
    relaxed_enabled: bool = True


class LaunchArv2DiscoveryOutput(ToolOutput):
    run_id: str
    replayed: bool


def _not_composed() -> tuple[PreconditionFailure, ...]:
    return (
        PreconditionFailure(
            reason_code="arv2_discovery_not_composed",
            message=(
                "the ARV2 discovery lane is not composed on this deployment "
                "(CLUE_ARV2_DISCOVERY_ENABLED)"
            ),
        ),
    )


def _retired() -> PreconditionFailure:
    return PreconditionFailure(
        reason_code="discovery_tool_retired",
        message=(
            "launch_arv2_discovery@1 is retired; call launch_arv2_discovery@2 with the brief you "
            "wrote"
        ),
    )


def _trusted_action(ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
    if ctx.action_ref is None:
        return (
            PreconditionFailure(
                reason_code="launch_action_ref_missing",
                message=(
                    "launching discovery requires the captured user action that approved "
                    "searching for accounts against this project's pinned ICP"
                ),
            ),
        )
    return ()


class LaunchArv2DiscoveryTool(Tool):
    """``@1``, retired (spec 2026-09-30 §3): registered so its journaled calls stay readable, and
    every new call is refused by name toward ``@2``, which takes the brief the agent wrote."""

    name = "launch_arv2_discovery"
    version = "1"
    model_description = (
        "Launch ARV2 verified account discovery for one project: search for exactly target_count "
        "companies that match the confirmed ICP document version the project pinned, verify each "
        "one against that document's hard gates, and add it to this project's accounts. Every "
        "call a human's action approves is a new discovery, and it never finds a company this "
        "project's earlier discoveries found; the same action retried replays its own run. Call "
        "only when the current user action explicitly approves searching for new accounts for "
        "this project. The ICP and the gates come from the pinned document, never from this call, "
        "and a successful result means the run was created or replayed, never that companies "
        "have been found. It researches nothing. " + tool_manual_link("launch_arv2_discovery")
    )
    input_model: ClassVar[type[ToolInput]] = LaunchArv2DiscoveryInput
    output_model = LaunchArv2DiscoveryOutput
    effect_class = ToolEffectClass.SPEND
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity=(
            "workspace + project + the approving user action + pinned ICP digest + target count "
            "+ relaxed flag + criteria gate keys"
        ),
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=("project_id", "target_count", "relaxed_enabled")
    )
    #: ``project`` is the spine row the execution is bound to — a replay identity, not a Stage-0
    #: pin (standing rule item 5).
    pin_requirements = ("project",)

    def __init__(self, service: Arv2DiscoveryService | None) -> None:
        self._service = service

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> tuple[PreconditionFailure, ...]:
        del inputs, ctx
        return (_retired(),)

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        assert isinstance(inputs, LaunchArv2DiscoveryInput | LaunchArv2DiscoveryV2Input)
        # A discovery run's spend is governed by the lane's own ceilings and settles in
        # ``provider_call_ledger`` per call; the webset's credit price and the number of Answer
        # calls are not knowable from this call, so the estimate carries the *shape* of the spend
        # (how many companies were asked for) rather than a number nobody derived.
        return ToolEstimate(
            cost_cents=Decimal(0),
            detail={
                "basis": "arv2_discovery_websets_plus_answer_ceilings",
                "target_count": inputs.target_count,
            },
        )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        del inputs, ctx
        raise PreconditionFailed([_retired()])


class LaunchArv2DiscoveryV2Input(ToolInput):
    project_id: str
    target_count: int = Field(default=20, ge=1, le=500)
    source: DiscoverySource
    query: str
    criteria: list[str]
    gates: list[BriefGate]


class LaunchArv2DiscoveryV2Tool(LaunchArv2DiscoveryTool):
    version = "2"
    model_description = (
        "Launch account discovery for one project with the search you write: what kind of company "
        "to find (query), what every company must satisfy (criteria), and the checks run on every "
        "company found (gates, each with a role: must, must_not or prefer). Read section 7b of the "
        "stage0-interview skill before calling. The project needs a confirmed ICP and product set. "
        "A successful result means the run was created or replayed, never that companies were "
        "found; this conversation stays busy until the run ends and you get a turn with its "
        "summary. " + tool_manual_link("launch_arv2_discovery")
    )
    input_model: ClassVar[type[ToolInput]] = LaunchArv2DiscoveryV2Input
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity=(
            "workspace + project + the approving user action + the brief + target count"
        ),
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=("project_id", "target_count", "source")
    )

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> tuple[PreconditionFailure, ...]:
        del inputs
        return _not_composed() if self._service is None else _trusted_action(ctx)

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, LaunchArv2DiscoveryV2Input)
        assert self._service is not None and ctx.action_ref is not None
        try:
            # Structural only (counts, unique keys); the wording is the agent's.
            brief = DiscoveryBrief2.model_validate(
                inputs.model_dump(include={"source", "query", "criteria", "gates"})
            )
        except ValidationError as bad:
            raise PreconditionFailed([PreconditionFailure("brief_invalid", str(bad))]) from bad
        request = Arv2DiscoveryRequest(
            # The tenant and the requesting human are AMBIENT authority, never model-authored.
            workspace_id=ctx.workspace_id,
            project_id=inputs.project_id,
            requested_by_user_id=ctx.actor_id or ctx.actor,
            # The turn this launch is an act of. When the deepagent launches from the fleet the
            # invoker is a *service* principal (``svc_execution_worker``), which is nobody's owner
            # (ruling 10′: creator is owner) — the launch resolves the turn's human from this.
            launching_turn_ref=ctx.action_ref if ctx.principal_kind == "service" else None,
            # The approving user action is this ask's identity: a new action is a new discovery,
            # the same action retried is the same one (the precondition guarantees it is set).
            request_key=ctx.action_ref,
            target_count=inputs.target_count,
            brief=brief,
        )
        try:
            receipt = await self._service.launch(request)
        except Arv2DiscoveryRefused as refused:
            raise PreconditionFailed([PreconditionFailure(refused.code, str(refused))]) from refused
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={"run_id": str(receipt.run_id), "replayed": receipt.replayed},
            replayed=receipt.replayed,
        )


def build_arv2_discovery_tools(service: Arv2DiscoveryService | None) -> tuple[Tool, ...]:
    """The lane's toolbelt surface. Registered always; composed only behind the flag.

    Registering it uncomposed is deliberate, for the reason ``build_arv2_launch_tools`` gives: the
    platform's write surface stays complete (the authority audit sees every tool), and an agent
    that reaches for discovery on a deployment without the lane gets the named
    ``arv2_discovery_not_composed`` refusal rather than an ``UnknownTool`` it cannot explain.
    ``@1`` stays registered beside ``@2`` so a call journaled against it still resolves, and is
    refused by name (``discovery_tool_retired``).
    """
    return (LaunchArv2DiscoveryTool(service), LaunchArv2DiscoveryV2Tool(service))
