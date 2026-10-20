"""The durable submission record for one human turn, and the per-thread single-flight dispatcher.

FI Lane D slice **D2** (charter §3-P3 / §3.5). Two responsibilities, both about the seam between
the HTTP process that *accepts* a turn and the fleet worker that *executes* it:

**1. ``agent_turn_submission`` — identity before enqueue.** The route writes it before it enqueues
anything; the worker reads it as the authority for who is acting. It exists because an
``agent_turn`` row cannot: that row references an ``execution``, and its constitution pins a
resolved profile, a resource manifest, a project card and a budget envelope — the whole agent
plane, model provider included, which the HTTP process must never compose (§3-P3). So a turn's
identity lands in two halves keyed on the same ``turn_id``: the submission (who, which thread,
which captured bytes) written by the route, and the ``agent_turn`` row (which execution, which
profile) written by the worker, which copies the submitter across. Neither half is ever taken from
a queue payload — Lane B §7 lets the queue carry internal ids, but a *message* is not evidence.

**2. Per-thread single-flight, by construction.** The invariant charter §3.5 asks for — one active
turn per thread, later turns durably queued in submission order, no cross-thread blocking — is not
enforced by a lock held during execution. It falls out of one rule: **at most one non-terminal
``agent_turn`` fleet task exists per thread at any moment.** :func:`dispatch_next_thread_turn`
offers the thread's *earliest* not-yet-executed submission and nothing else; the next one is
offered only once the previous task is terminal (by the worker, after it finishes). Because every
queued row is therefore immediately runnable, a busy thread never blocks another thread's turn at
the head of the shared queue — which a "claim it then bounce off a lock" design would.

Three mechanisms fence it, cheapest first:

* a Postgres **advisory transaction lock** on the thread makes read-then-enqueue atomic, so two
  concurrent submissions (or a submission racing the worker's post-turn dispatch) cannot both
  decide the thread is free;
* the queue's own ``ON CONFLICT (kind, work_id, dedup_key) DO NOTHING`` means a repeated offer of
  the same turn is a no-op even if the lock were bypassed;
* the fleet **driver lease**, which the worker takes on ``work_id`` before running a handler, is
  keyed here on the *thread* — so even two workers holding two tasks of one thread could not
  execute them concurrently.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import ArtifactRef, DomainObjectRef
from clue_core import OnboardingInputId, ProjectRunId, UtcDatetime
from clue_fleet import FleetTaskKind, WorkId, enqueue_task
from clue_obs import get_logger
from clue_obs.otel import bind_and_annotate

if TYPE_CHECKING:  # pragma: no cover - the chat package imports this module, so the edge is typed
    from clue_api.chat.attachments import ValidatedAttachment

__all__ = [
    "AGENT_TURN_DEDUP_PREFIX",
    "DERIVATION_CRM_CONNECTED",
    "DERIVATION_DESIGN_LEG_FIRST_TURN",
    "DERIVATION_DESIGN_LEG_REDELIVERY",
    "DERIVATION_DISCOVERY_FINISHED",
    "AgentTurnSubmissionRow",
    "SubmissionAttachmentRow",
    "SubmissionContextRefRow",
    "SubmissionConflict",
    "agent_turn_dedup_key",
    "dispatch_next_thread_turn",
    "get_submission",
    "submission_attachment_refs",
    "submission_attachment_refs_for_turns",
    "submission_context_refs",
    "submission_context_refs_for_turns",
    "message_artifact_ref",
    "insert_submission",
    "submissions_for_thread",
    "thread_work_id",
    "turn_id_for_submission",
]

#: One task per turn, named by the turn (the brief's contract). ``work_id`` carries the thread, so
#: the pair ``(work_id, dedup_key)`` reads as "this thread, this turn".
AGENT_TURN_DEDUP_PREFIX = "agent-turn:"

log = get_logger(__name__)

_TURN_NAMESPACE = uuid5(NAMESPACE_URL, "clue-agent-turn-submission")
_THREAD_WORK_NAMESPACE = uuid5(NAMESPACE_URL, "clue-agent-turn-thread-work")

#: A submission the SERVER made from a user's own message bytes says which kind it is (spec
#: 2026-09-20 §2.1). Readers treat any non-NULL value the same way: no second user row, no
#: second user bubble.
DERIVATION_DESIGN_LEG_REDELIVERY = "design_leg_redelivery"
DERIVATION_DESIGN_LEG_FIRST_TURN = "design_leg_first_turn"
#: Spec 2026-09-30 §4 "The wake": the Head of ABM's turn at the end of a discovery run, in the
#: thread that launched it. Its message is the run's summary, which the platform wrote.
DERIVATION_DISCOVERY_FINISHED = "discovery_finished"
#: The workspace's CRM connection became active: the chat that showed the connect card resumes
#: by itself (CRM integration, R-3.10). Same shape as ``discovery_finished``.
DERIVATION_CRM_CONNECTED = "crm_connected"

_COLUMNS = (
    "turn_id, workspace_id, project_id, thread_id, submitted_by_user_id, "
    "submitted_via_membership_id, onboarding_input_id, message_artifact_key, message_sha256, "
    "idempotency_key, agent_profile_id, previous_turn_outcome, requested_at, "
    "derivation, derived_from_turn_id"
)


class SubmissionConflict(ValueError):
    """This idempotency identity already named a *different* message.

    A retry replays; a new message under a used key is a client bug, and answering it with the
    first message's turn would silently drop what the user typed.
    """


def _framed(*parts: str) -> str:
    """Length-frame the parts so no two different tuples can hash to one key."""

    return "".join(f"{len(part)}:{part}" for part in parts)


def turn_id_for_submission(
    *,
    workspace_id: str,
    thread_id: str,
    idempotency_key: str,
) -> UUID:
    """Derive the turn id one submission identity names.

    Derived, not minted: a duplicate POST under one idempotency identity must land on the *same*
    turn — the same durable row, the same fleet task dedup key, the same replayed answer — rather
    than a second turn that runs the same message twice.
    """

    if not idempotency_key.strip():
        raise ValueError("a turn submission requires a non-empty idempotency identity")
    return uuid5(_TURN_NAMESPACE, _framed(workspace_id, thread_id, idempotency_key))


def thread_work_id(*, workspace_id: str, thread_id: str) -> WorkId:
    """The fleet ``work_id`` for a thread — the unit the driver lease makes exclusive.

    Turns are not the unit of exclusion; threads are. Keying the lease on the turn would let two
    turns of one thread run at once, which is precisely what §3.5 forbids.
    """

    return WorkId(uuid5(_THREAD_WORK_NAMESPACE, _framed(workspace_id, thread_id)))


def agent_turn_dedup_key(turn_id: UUID) -> str:
    return f"{AGENT_TURN_DEDUP_PREFIX}{turn_id}"


class AgentTurnSubmissionRow(BaseModel):
    """One ``agent_turn_submission`` row — immutable by trigger."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    turn_id: UUID
    workspace_id: str
    project_id: str
    thread_id: str
    submitted_by_user_id: str
    submitted_via_membership_id: str
    onboarding_input_id: OnboardingInputId
    message_artifact_key: str
    message_sha256: str
    idempotency_key: str | None
    agent_profile_id: str | None
    previous_turn_outcome: str | None
    requested_at: UtcDatetime
    #: Spec 2026-09-20 §2.1: set when the server made this submission from a user's own bytes.
    derivation: str | None = None
    derived_from_turn_id: UUID | None = None


class SubmissionContextRefRow(BaseModel):
    """One ordered ref captured with a human submission, and the note the human left on it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    turn_id: UUID
    workspace_id: str
    ordinal: int
    object_type: str
    object_id: str
    object_version: int | None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class SubmissionAttachmentRow:
    """One file the human attached to a submission, in the order they attached it."""

    turn_id: UUID
    ordinal: int
    upload_id: UUID
    ref: ArtifactRef
    filename: str


async def insert_submission(
    conn: AsyncConnection,
    *,
    turn_id: UUID,
    workspace_id: str,
    project_id: str,
    thread_id: str,
    submitted_by_user_id: str,
    submitted_via_membership_id: str,
    onboarding_input_id: OnboardingInputId,
    message_artifact_key: str,
    message_sha256: str,
    idempotency_key: str | None,
    context_refs: Sequence[DomainObjectRef] = (),
    attachment_refs: Sequence[ValidatedAttachment] = (),
    agent_profile_id: str | None = None,
    previous_turn_outcome: str | None = None,
    derivation: str | None = None,
    derived_from_turn_id: UUID | None = None,
) -> tuple[AgentTurnSubmissionRow, bool]:
    """Insert one submission, or replay it. Returns ``(row, created)``.

    Replay is decided by the durable row, not by an in-memory guess: a second POST under the same
    idempotency identity derives the same ``turn_id``, conflicts, and reads back the row it
    conflicted with. If that row records a different message digest the identity was reused for new
    content and this raises :class:`SubmissionConflict` — the 409 case — rather than answering with
    somebody else's turn.
    """

    if any(ref.workspace_id != workspace_id for ref in context_refs):
        raise ValueError("submission context refs cross the workspace boundary")
    # The attachment table's composite upload FK would refuse this too, but the loud early raise
    # names the boundary that was crossed instead of surfacing an opaque IntegrityError.
    if any(item.ref.workspace_id != workspace_id for item in attachment_refs):
        raise ValueError("submission attachment refs cross the workspace boundary")
    if (derivation is None) != (derived_from_turn_id is None):
        raise ValueError("a derived submission names both its derivation and its source turn")

    await lock_thread_queue(conn, workspace_id=workspace_id, thread_id=thread_id)
    # Acceptance order, not transaction-start time, defines FIFO. This also serializes
    # a new submission against Stop's empty-hold cleanup and explicit Resume.
    inserted = (
        (
            await conn.execute(
                text(
                    "INSERT INTO agent_turn_submission "
                    "(turn_id, workspace_id, project_id, thread_id, submitted_by_user_id, "
                    " submitted_via_membership_id, onboarding_input_id, message_artifact_key, "
                    " message_sha256, idempotency_key, agent_profile_id, previous_turn_outcome, "
                    " requested_at, derivation, derived_from_turn_id) "
                    "VALUES (:turn_id, :workspace_id, :project_id, :thread_id, :user_id, "
                    " :membership_id, :onboarding_input_id, :artifact_key, :sha256, :key, "
                    " :agent_profile_id, :previous_turn_outcome, GREATEST(clock_timestamp(), "
                    " (SELECT max(requested_at) + interval '1 microsecond' "
                    " FROM agent_turn_submission WHERE workspace_id=:workspace_id "
                    " AND thread_id=:thread_id)), "
                    " :derivation, :derived_from_turn_id) "
                    f"ON CONFLICT (turn_id) DO NOTHING RETURNING {_COLUMNS}"
                ),
                {
                    "turn_id": turn_id,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "thread_id": thread_id,
                    "user_id": submitted_by_user_id,
                    "membership_id": submitted_via_membership_id,
                    "onboarding_input_id": onboarding_input_id,
                    "artifact_key": message_artifact_key,
                    "sha256": message_sha256,
                    "key": idempotency_key,
                    "agent_profile_id": agent_profile_id,
                    "previous_turn_outcome": previous_turn_outcome,
                    "derivation": derivation,
                    "derived_from_turn_id": derived_from_turn_id,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    if inserted is not None:
        row = AgentTurnSubmissionRow.model_validate(dict(inserted))
        for ordinal, ref in enumerate(context_refs):
            await conn.execute(
                text(
                    "INSERT INTO agent_turn_submission_context_ref "
                    "(turn_id, workspace_id, ordinal, object_type, object_id, object_version, "
                    " note) "
                    "VALUES (:turn_id, :workspace_id, :ordinal, :object_type, :object_id, "
                    " :object_version, :note)"
                ),
                {
                    "turn_id": turn_id,
                    "workspace_id": workspace_id,
                    "ordinal": ordinal,
                    "object_type": ref.object_type,
                    "object_id": ref.object_id,
                    "object_version": ref.version,
                    "note": ref.note,
                },
            )
        for ordinal, item in enumerate(attachment_refs):
            await conn.execute(
                text(
                    "INSERT INTO agent_turn_submission_attachment "
                    "(turn_id, workspace_id, ordinal, upload_id, artifact_key, sha256, "
                    " media_type, byte_count, filename) "
                    "VALUES (:turn, :ws, :ordinal, :upload, :key, :sha, :media, :bytes, :name)"
                ),
                {
                    "turn": turn_id,
                    "ws": workspace_id,
                    "ordinal": ordinal,
                    "upload": item.upload_id,
                    "key": item.ref.artifact_key,
                    "sha": item.ref.sha256,
                    "media": item.ref.media_type,
                    "bytes": item.ref.byte_count,
                    "name": item.filename,
                },
            )
        return row, True
    existing = await get_submission(conn, workspace_id=workspace_id, turn_id=turn_id)
    if existing is None:
        # The id exists outside this workspace. Deriving the id from the workspace makes this
        # practically unreachable; refusing beats leaking that another tenant holds it.
        raise SubmissionConflict("this turn identity exists outside the requested workspace")
    existing_refs = await submission_context_refs(
        conn,
        workspace_id=workspace_id,
        turn_id=turn_id,
    )
    existing_attachments = await submission_attachment_refs(
        conn,
        workspace_id=workspace_id,
        turn_id=turn_id,
    )
    if (
        existing.message_sha256 != message_sha256
        or existing.thread_id != thread_id
        or existing.agent_profile_id != agent_profile_id
        or tuple(context_refs) != existing_refs
        or tuple(item.upload_id for item in existing_attachments)
        != tuple(item.upload_id for item in attachment_refs)
    ):
        raise SubmissionConflict(
            "this idempotency identity was already used for a different submission"
        )
    return existing, False


async def get_submission(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    turn_id: UUID,
) -> AgentTurnSubmissionRow | None:
    """Read one submission **inside one workspace**; a cross-workspace read is a miss."""

    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_COLUMNS} FROM agent_turn_submission "
                    "WHERE turn_id = :turn_id AND workspace_id = :workspace_id"
                ),
                {"turn_id": turn_id, "workspace_id": workspace_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return AgentTurnSubmissionRow.model_validate(dict(row)) if row is not None else None


async def submission_context_refs(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    turn_id: UUID,
) -> tuple[DomainObjectRef, ...]:
    """Rehydrate context refs in the exact order the user supplied."""

    rows = (
        (
            await conn.execute(
                text(
                    "SELECT turn_id, workspace_id, ordinal, object_type, object_id, "
                    "object_version, note FROM agent_turn_submission_context_ref "
                    "WHERE turn_id=:turn_id AND workspace_id=:workspace_id ORDER BY ordinal"
                ),
                {"turn_id": turn_id, "workspace_id": workspace_id},
            )
        )
        .mappings()
        .all()
    )
    receipts = tuple(SubmissionContextRefRow.model_validate(dict(row)) for row in rows)
    return tuple(
        DomainObjectRef(
            workspace_id=item.workspace_id,
            object_type=item.object_type,
            object_id=item.object_id,
            version=item.object_version,
            note=item.note,
        )
        for item in receipts
    )


async def submission_attachment_refs(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    turn_id: UUID,
) -> tuple[SubmissionAttachmentRow, ...]:
    """Rehydrate a submission's attachments in the exact order the human attached them."""

    rows = (
        await conn.execute(
            text(
                "SELECT turn_id, ordinal, upload_id, artifact_key, sha256, media_type, "
                "byte_count, filename FROM agent_turn_submission_attachment "
                "WHERE workspace_id = :ws AND turn_id = :turn ORDER BY ordinal"
            ),
            {"ws": workspace_id, "turn": turn_id},
        )
    ).mappings()
    return tuple(
        SubmissionAttachmentRow(
            turn_id=row["turn_id"],
            ordinal=int(row["ordinal"]),
            upload_id=row["upload_id"],
            ref=ArtifactRef(
                workspace_id=workspace_id,
                artifact_key=row["artifact_key"],
                sha256=row["sha256"],
                media_type=row["media_type"],
                byte_count=int(row["byte_count"]),
            ),
            filename=row["filename"],
        )
        for row in rows
    )


async def submission_context_refs_for_turns(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    turn_ids: Sequence[UUID],
) -> dict[UUID, tuple[DomainObjectRef, ...]]:
    """Batch ordered submission context for transcript/turn-list hydration."""

    if not turn_ids:
        return {}
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT turn_id, ordinal, object_type, object_id, object_version, note "
                    "FROM agent_turn_submission_context_ref "
                    "WHERE workspace_id=:workspace_id "
                    "AND turn_id=ANY(CAST(:turn_ids AS uuid[])) "
                    "ORDER BY turn_id, ordinal"
                ),
                {
                    "workspace_id": workspace_id,
                    "turn_ids": [str(turn_id) for turn_id in turn_ids],
                },
            )
        )
        .mappings()
        .all()
    )
    grouped: dict[UUID, list[DomainObjectRef]] = {}
    for row in rows:
        turn_id = UUID(str(row["turn_id"]))
        grouped.setdefault(turn_id, []).append(
            DomainObjectRef(
                workspace_id=workspace_id,
                object_type=str(row["object_type"]),
                object_id=str(row["object_id"]),
                version=(None if row["object_version"] is None else int(row["object_version"])),
                note=(None if row["note"] is None else str(row["note"])),
            )
        )
    return {turn_id: tuple(refs) for turn_id, refs in grouped.items()}


async def submission_attachment_refs_for_turns(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    turn_ids: Sequence[UUID],
) -> dict[UUID, tuple[SubmissionAttachmentRow, ...]]:
    """Batch ordered submission attachments for transcript/turn-list hydration.

    The single-turn sibling's shape, read in one query, so a page of pending turns costs one
    round trip rather than one per turn.
    """

    if not turn_ids:
        return {}
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT turn_id, ordinal, upload_id, artifact_key, sha256, media_type, "
                    "byte_count, filename FROM agent_turn_submission_attachment "
                    "WHERE workspace_id = :workspace_id "
                    "AND turn_id = ANY(CAST(:turn_ids AS uuid[])) "
                    "ORDER BY turn_id, ordinal"
                ),
                {
                    "workspace_id": workspace_id,
                    "turn_ids": [str(turn_id) for turn_id in turn_ids],
                },
            )
        )
        .mappings()
        .all()
    )
    grouped: dict[UUID, list[SubmissionAttachmentRow]] = {}
    for row in rows:
        turn_id = UUID(str(row["turn_id"]))
        grouped.setdefault(turn_id, []).append(
            SubmissionAttachmentRow(
                turn_id=turn_id,
                ordinal=int(row["ordinal"]),
                upload_id=row["upload_id"],
                ref=ArtifactRef(
                    workspace_id=workspace_id,
                    artifact_key=row["artifact_key"],
                    sha256=row["sha256"],
                    media_type=row["media_type"],
                    byte_count=int(row["byte_count"]),
                ),
                filename=row["filename"],
            )
        )
    return {turn_id: tuple(items) for turn_id, items in grouped.items()}


async def message_artifact_ref(
    conn: AsyncConnection,
    submission: AgentTurnSubmissionRow,
) -> ArtifactRef:
    """Rehydrate the exact artifact reference for a submission's captured message.

    The submission stores the address (key + digest) rather than the full reference because the
    address is what identity depends on; media type and size are the artifact row's own facts and
    are read back from it. The digest is re-checked here, so an artifact row that no longer matches
    the submission fails loudly instead of feeding the model different bytes than the human sent.
    """

    row = (
        (
            await conn.execute(
                text(
                    "SELECT content_sha256, media_type, size_bytes FROM artifact "
                    "WHERE storage_key = :key AND workspace_id = :workspace_id "
                    "AND erased_at IS NULL AND purged_at IS NULL"
                ),
                {
                    "key": submission.message_artifact_key,
                    "workspace_id": submission.workspace_id,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["content_sha256"] != submission.message_sha256:
        raise SubmissionConflict(
            "the captured message artifact for this turn is missing or no longer matches"
        )
    return ArtifactRef(
        workspace_id=submission.workspace_id,
        artifact_key=submission.message_artifact_key,
        sha256=submission.message_sha256,
        media_type=row["media_type"],
        byte_count=int(row["size_bytes"]),
    )


async def submissions_for_thread(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    thread_id: str,
) -> tuple[AgentTurnSubmissionRow, ...]:
    """Every submission of one thread in submission order — the visible queue."""

    rows = (
        (
            await conn.execute(
                text(
                    f"SELECT {_COLUMNS} FROM agent_turn_submission "
                    "WHERE workspace_id = :workspace_id AND thread_id = :thread_id "
                    "ORDER BY requested_at, turn_id"
                ),
                {"workspace_id": workspace_id, "thread_id": thread_id},
            )
        )
        .mappings()
        .all()
    )
    return tuple(AgentTurnSubmissionRow.model_validate(dict(row)) for row in rows)


_THREAD_INFLIGHT_SQL = text(
    """
    SELECT 1 FROM fleet_task
    WHERE kind = CAST('agent_turn' AS fleet_task_kind)
      AND work_id = :work_id
      AND status IN ('queued', 'claimed')
    LIMIT 1
    """
)

# The next turn this thread owes: the earliest submission whose task has not reached a terminal
# state. A DONE task is an executed turn; a FAILED task is an honest failure that the fleet's own
# doctrine says is retried only by an explicit requeue, never silently — so both are skipped and
# the thread moves on instead of looping on a turn that cannot succeed.
_NEXT_PENDING_SQL = text(
    """
    SELECT s.turn_id, s.project_id
    FROM agent_turn_submission s
    WHERE s.workspace_id = :workspace_id
      AND s.thread_id = :thread_id
      AND NOT EXISTS (
            SELECT 1 FROM fleet_task f
            WHERE f.kind = CAST('agent_turn' AS fleet_task_kind)
              AND f.work_id = :work_id
              AND f.dedup_key = :prefix || s.turn_id::text
              AND f.status IN ('done', 'failed')
          )
    ORDER BY s.requested_at, s.turn_id
    LIMIT 1
    """
)

# The unreleased discovery run this thread launched, if any, and its wake turn (NULL while the run
# is still going). Raw SQL rather than the ARV2 store: ``clue_api.arv2`` must never import this
# module, and reading the one table keeps the edge one-way.
_THREAD_DISCOVERY_SQL = text(
    "SELECT wake_turn_id FROM arv2_discovery_run WHERE workspace_id = :w "
    "AND launched_thread_id = :t AND released_at IS NULL LIMIT 1"
)

# Whether the wake turn's task has reached a terminal state.
_WAKE_TASK_TERMINAL_SQL = text(
    "SELECT EXISTS (SELECT 1 FROM fleet_task WHERE kind = CAST('agent_turn' AS fleet_task_kind) "
    "AND work_id = :work_id AND dedup_key = :dedup_key AND status IN ('done', 'failed'))"
)

# Release the run whose wake has already run (the repair path in dispatch_next_thread_turn).
_RELEASE_FINISHED_WAKE_SQL = text(
    "UPDATE arv2_discovery_run SET released_at = now() WHERE workspace_id = :w "
    "AND wake_turn_id = :t AND released_at IS NULL RETURNING run_id"
)

# The wake turn, while its task is not terminal. Once it is, the handler that finished it releases
# the run (or, failing that, dispatch repairs the release itself).
_WAKE_PENDING_SQL = text(
    """
    SELECT s.turn_id, s.project_id
    FROM agent_turn_submission s
    WHERE s.workspace_id = :workspace_id
      AND s.thread_id = :thread_id
      AND s.turn_id = :wake_turn_id
      AND NOT EXISTS (
            SELECT 1 FROM fleet_task f
            WHERE f.kind = CAST('agent_turn' AS fleet_task_kind)
              AND f.work_id = :work_id
              AND f.dedup_key = :prefix || s.turn_id::text
              AND f.status IN ('done', 'failed')
          )
    """
)


def _thread_lock_scope(workspace_id: str, thread_id: str) -> str:
    framed = _framed(workspace_id, thread_id).encode()
    return "agent-turn-dispatch:" + hashlib.sha256(framed).hexdigest()


async def lock_thread_queue(conn: AsyncConnection, *, workspace_id: str, thread_id: str) -> None:
    await conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
        {"scope": _thread_lock_scope(workspace_id, thread_id)},
    )


async def dispatch_next_thread_turn(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    thread_id: str,
    priority: int = 0,
) -> UUID | None:
    """Offer this thread's next turn to the fleet, or nothing. Returns the enqueued turn id.

    Called from exactly two places, and it must be safe to call from either at any time: the turn
    route (having just recorded a submission) and the ``AGENT_TURN`` handler (having just made its
    own task terminal). Both run it inside their own transaction so the advisory lock, the
    in-flight check, the ordering read and the enqueue are one atomic decision — the lock is a
    *transaction* lock precisely so no caller can forget to release it.

    Returning ``None`` is the common, correct outcome: the thread already has a task in flight, or
    it has no un-executed submission left.
    """

    work_id = thread_work_id(workspace_id=workspace_id, thread_id=thread_id)
    await lock_thread_queue(conn, workspace_id=workspace_id, thread_id=thread_id)
    held = await conn.scalar(
        text(
            "SELECT queue_hold_control_id FROM agent_thread "
            "WHERE workspace_id=:workspace AND id=:thread"
        ),
        {"workspace": workspace_id, "thread": thread_id},
    )
    if held is not None:
        return None
    # Spec 2026-09-30 §5: a thread whose discovery run is unreleased is busy. Until the run's wake
    # turn exists nothing is offered — user messages are accepted and held, never refused — and
    # once it exists the wake goes first, ahead of messages accepted earlier. The run is released
    # when the wake's task finishes (the AGENT_TURN handler), and the queue then moves on.
    discovery = (
        await conn.execute(_THREAD_DISCOVERY_SQL, {"w": workspace_id, "t": thread_id})
    ).first()
    if discovery is not None and discovery[0] is None:
        return None
    in_flight = (await conn.execute(_THREAD_INFLIGHT_SQL, {"work_id": work_id})).first()
    if in_flight is not None:
        return None
    params: dict[str, object] = {
        "workspace_id": workspace_id,
        "thread_id": thread_id,
        "work_id": work_id,
        "prefix": AGENT_TURN_DEDUP_PREFIX,
    }
    statement = _NEXT_PENDING_SQL
    if discovery is not None:
        wake_turn_id = discovery[0]
        wake_finished = await conn.scalar(
            _WAKE_TASK_TERMINAL_SQL,
            {"work_id": work_id, "dedup_key": agent_turn_dedup_key(UUID(str(wake_turn_id)))},
        )
        if wake_finished:
            # The repair path. The AGENT_TURN handler normally releases the run when the wake's task
            # finishes; if it never got there (a crash between finishing the task and its release,
            # say) the thread and its project would stay held forever. The wake has run, so the
            # run is released here and the queue moves on to the first held message.
            released = await conn.scalar(
                _RELEASE_FINISHED_WAKE_SQL, {"w": workspace_id, "t": wake_turn_id}
            )
            log.warning(
                "discovery.wake_release_repaired",
                run_id=None if released is None else str(released),
                workspace_id=workspace_id,
                thread_id=thread_id,
                wake_turn_id=str(wake_turn_id),
            )
        else:
            statement, params = _WAKE_PENDING_SQL, {**params, "wake_turn_id": wake_turn_id}
    row = (await conn.execute(statement, params)).mappings().one_or_none()
    if row is None:
        return None
    turn_id = UUID(str(row["turn_id"]))
    # Lane 3 slice 2: the turn this dispatch is about, bound for the rest of this request (its log
    # lines and the enqueue span) and written onto the span that is already open.
    bind_and_annotate(
        project_id=str(row["project_id"]),
        thread_id=thread_id,
        turn_id=str(turn_id),
    )
    payload: dict[str, JsonValue] = {
        # References only, never a token and never a message body (substrate §5b, Lane B §7).
        "turn_id": str(turn_id),
        "workspace_id": workspace_id,
        "project_id": str(row["project_id"]),
        "thread_id": thread_id,
    }
    await enqueue_task(
        conn,
        kind=FleetTaskKind.AGENT_TURN,
        project_run_id=ProjectRunId(work_id),
        dedup_key=agent_turn_dedup_key(turn_id),
        priority=priority,
        payload=payload,
    )
    return turn_id
