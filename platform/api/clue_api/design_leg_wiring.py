"""The design-leg turn engine (Part III P3.4 — PD-part3 §1-D1/D3, §2.4).

The worker-side half of ruling D1's routing rule. When the ``AGENT_TURN`` worker claims a turn
whose thread holds an **open** ``design_leg``, the message does not wake head-of-abm — it becomes
a **design turn on that leg**, and this module is what runs it:

* **Attribution on the shared thread (D3).** The turn lands as a real ``agent_turn`` row —
  role=``design``, its execution parented under the delegating platform execution
  (``design_leg.parent_execution_id``) — with the submitting human copied from the durable
  submission, exactly as every other turn. The §2.5 one-thread/attribution contract holds
  without the design runtime learning anything about platform journals.
* **Execution on the design lane (D3).** The turn's body is a ``DesignTurnEnvelope`` driven
  through the :class:`DesignLegLaneDriver` seam. Production drives the design fleet handler
  *inline under a real work lease* (see ``clue_api.design_fleet.build_design_leg_lane_driver``)
  rather than enqueueing a second fleet task: the platform fleet drains one task at a time per
  worker, so an ``AGENT_TURN`` handler that queued a ``design_job`` and waited for it would
  deadlock a single-worker deployment against itself. Same handler, same claim CAS, same
  generation fences — only the queue hop is skipped. The run row is stamped with
  ``leg_id`` + ``execution_id`` (the P3.1 linkage), and its id is **derived from the turn id**,
  so a re-claimed task converges on the same run instead of dispatching a second one.
* **An honest terminal shape (D1).** A design turn that produced a proposal ends
  ``AWAITING_INPUT`` with a committed :class:`~clue_agents.AgentFinalizeEnvelope` whose
  ``open_gate_refs`` name the leg — the leg *is* the open interaction — which also buys the
  committed-outcome replay short-circuit for free. A failed design run fails the turn with no
  manufactured finalization, and the leg stays open: the user answers, the leg goes on.
* **Leg-scoped history (§2.4).** :func:`load_design_leg_history` returns exactly this leg's
  user↔design exchanges (joined through the turns' execution parentage, which survives even a
  turn whose design run never got created); :func:`load_head_of_abm_history` is the other half —
  the conversation surface's load that **excludes** every design-role turn, so head-of-abm never
  ingests the leg transcript. Leg summaries enter head-of-abm's view at leg close (P3.5).

What deliberately does **not** happen here: no platform model wake (the trio runs inside the
design runtime, P3.2's gateway move already governs its spend per role), no platform workspace
lease (the design runtime's virtual workspace is keyed to its run — ``workspace_root_id`` records
the leg address honestly), and no leg close (``finish_design_leg`` is P3.5's engine-validated
exit; a turn ending keeps the leg ``open_awaiting_user``).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import (
    AgentConstitution,
    AgentExecutionStatus,
    AgentFinalizeEnvelope,
    AgentHistoryStore,
    AgentProfileRegistry,
    AgentRole,
    AgentTurnOutcome,
    AgentTurnRequest,
    ArtifactRef,
    DomainObjectRef,
    FinalizeStatus,
    HistoryMessageRef,
    ProjectContextArtifact,
)
from clue_api.agent_turn_submission import AgentTurnSubmissionRow
from clue_api.agent_turn_wiring import (
    DbAgentTurnJournal,
    DurableAgentArtifactStore,
)
from clue_api.chat.turn_events import TurnEventType, emit_turn_event
from clue_api.chat.turn_stream import TurnStreamEmitter
from clue_api.design_turn_targets import resolve_scene_targets
from clue_api.turn_action import derive_turn_action_ref
from clue_core import ExecutionId, operation_id_from_key
from clue_db import ConnFactory, transaction
from clue_design import accounts as design_accounts
from clue_design import legs as design_legs
from clue_design import runs as design_runs
from clue_design.documents import get_document, is_finalized_document
from clue_design.enums import DesignRunKind
from clue_design.envelopes import DesignTurnEnvelope
from clue_design.errors import DesignNotFoundError
from clue_design.exit_judgment import (
    ExitDecision,
    ExitJudgment,
    decide_exit,
)
from clue_obs import get_logger
from clue_spine import get_project
from clue_toolbelt import ToolInvoker

log = get_logger("clue_api.design_leg")

__all__ = [
    "DESIGN_LEG_ACCOUNT_UNRESOLVED",
    "DESIGN_LEG_BUDGET_LIMIT_MILLICENTS",
    "DESIGN_LEG_DOCUMENT_FINALIZED",
    "DESIGN_LEG_TURN_CRASHED",
    "DESIGN_LEG_TURN_FAILED",
    "DesignLegLaneDriver",
    "DesignLegTurnResult",
    "DesignLegTurnRunner",
    "design_leg_execution_id",
    "design_leg_run_id",
    "design_legs_for_threads",
    "load_design_leg_history",
    "load_head_of_abm_history",
    "project_design_documents",
]

#: The leg turn's platform-side spend envelope. Model spend happens inside the design runtime and
#: is measured at the gateway per role (P3.2's single-authority attribution); this envelope is the
#: constitutional bound the ``agent_turn`` row records, sized like the conversation's.
DESIGN_LEG_BUDGET_LIMIT_MILLICENTS = 1_000_000

#: The one stable failure code a failed design run surfaces on the platform turn.
DESIGN_LEG_TURN_FAILED = "design_leg_turn_failed"

#: G1 (founder ruling, 2026-08-19): the pinned document is finalized, so this turn would be a
#: mutation of a frozen artifact. Revising one means a new draft revision plus a governed move
#: of the leg onto it — machinery that does not exist yet — so the turn refuses instead.
DESIGN_LEG_DOCUMENT_FINALIZED = "design_leg_document_finalized"

#: G2 (founder ruling, 2026-08-19): the pinned document names an account this workspace cannot
#: resolve. Fail-closed by ruling: a personalized document must never quietly generate a generic
#: page, so an unresolvable stamp fails the turn rather than dropping the card.
DESIGN_LEG_ACCOUNT_UNRESOLVED = "design_leg_account_unresolved"

#: The containment code for a turn body that RAISED (vs a design run that honestly
#: failed): lane unavailable, join timeout, bundle fault, finisher fault. Marked
#: abandoned so the turn is terminal, streamed, and prunable instead of a zombie.
DESIGN_LEG_TURN_CRASHED = "design_leg_turn_crashed"

_EXECUTION_NAMESPACE = uuid5(NAMESPACE_URL, "clue-design-leg-execution")
_RUN_NAMESPACE = uuid5(NAMESPACE_URL, "clue-design-leg-run")
_FINALIZATION_NAMESPACE = uuid5(NAMESPACE_URL, "clue-design-leg-finalization")

_TERMINAL_RUN_STATUSES = frozenset({"succeeded", "failed"})


def design_leg_execution_id(turn_id: UUID) -> ExecutionId:
    """The design turn's execution identity — one per turn, derived, crash-stable."""

    return ExecutionId(uuid5(_EXECUTION_NAMESPACE, str(turn_id)))


def design_leg_run_id(turn_id: UUID) -> str:
    """The design run this turn dispatches — derived so a retried task re-joins, never re-runs."""

    return f"run_{uuid5(_RUN_NAMESPACE, str(turn_id)).hex}"


class DesignLegLaneDriver(Protocol):
    """Drive one leg-turn envelope on the design lane to a terminal design-run row.

    Implementations own claim/fencing/execution; the runner owns everything durable around it.
    ``drive`` returns when the run row is terminal (or raises); it must never fabricate a result.
    """

    async def drive(self, *, envelope: DesignTurnEnvelope) -> None: ...


@dataclass(frozen=True, slots=True)
class DesignLegTurnResult:
    """Field-compatible with ``ConversationTurnResult`` — the work handler reads these three."""

    outcome: AgentTurnOutcome
    assistant_message: str | None
    replayed: bool


class DesignLegExitJudge(Protocol):
    """The §2.2 exit judgment — the single LLM judgment in the routing path (P3.6's core).

    Returns the model's verdict, or ``None`` for unparseable output; the runner passes it
    through :func:`clue_design.exit_judgment.decide_exit`, whose fail-safe means a broken or
    absent judge can only ever CONTINUE the leg. Implementations must not raise for model
    misbehavior — and the runner guards with the same fail-safe anyway.
    """

    async def __call__(
        self,
        *,
        brief: str,
        history: tuple[tuple[str, str], ...],
        message: str,
    ) -> ExitJudgment | None: ...


class DesignLegFinisher(Protocol):
    """Invoke the governed ``finish_design_leg`` tool for one exiting design turn.

    The bridge's engine half: the judgment is model-authored, but the exit is executed as
    the same validated tool call the design orchestrator would make — journal, summary
    message, out-of-scope re-delivery, ``leg.closed`` frame and all. Returns the tool's
    references (a replayed close returns the ORIGINAL decision's references).
    """

    async def __call__(
        self,
        *,
        workspace_id: str,
        turn_id: UUID,
        reason: str,
        summary: str,
    ) -> dict[str, Any]: ...


#: Engine-derived exit summaries — deliberately deterministic. The judge decides WHETHER to
#: exit; it does not author prose, so the durable summary is the engine's honest sentence,
#: never a fabricated model quote. (A richer model-authored summary is a Part-IV concern.)
DESIGN_LEG_EXIT_SUMMARIES: dict[str, str] = {
    "locked": "Design locked in: the user accepted the current design.",
    "out_of_scope": (
        "The design session ended: the request is outside the design scope and has been "
        "returned to the strategy conversation."
    ),
    "abandoned": "The design session was abandoned at the user's request.",
}


def build_design_leg_finisher(
    *,
    invoker: ToolInvoker,
    conn_factory: ConnFactory = transaction,
) -> DesignLegFinisher:
    """The production finisher: ``finish_design_leg`` through the MANDATORY journaled
    invoker (adversarial-review fix — the first cut built a private registry and called
    ``invoke_tool`` bare, which the C5.1 guard rightly refuses from a production root).

    The invoker is the worker's shared production ``ToolInvoker`` over the shared
    registry that already holds the tool, so the exit gets what every governed write
    gets: the invocation journal, the parameter snapshot, and A9 idempotency keyed on
    the journal identity. The operation id is derived from the turn, so a crash-retried
    exit replays the recorded invocation (``JournalDisposition.COMPLETED``) — and even
    past the journal, the tool's own closing-turn replay converges.
    """

    from clue_toolbelt import ToolContext

    async def finish(
        *, workspace_id: str, turn_id: UUID, reason: str, summary: str
    ) -> dict[str, Any]:
        result = await invoker.invoke(
            "finish_design_leg",
            {
                "source_turn_ref": derive_turn_action_ref(turn_id),
                "reason": reason,
                "summary": summary,
            },
            ToolContext(
                workspace_id=workspace_id,
                actor="agent",
                conn_factory=conn_factory,
                operation_id=operation_id_from_key(str(turn_id), "design-leg-exit@1"),
            ),
        )
        return dict(result.references)

    return finish


# The LIVE judge builder deliberately does NOT live here: it needs the model plane
# (``AgentModelProvider``), and this module is reachable from the HTTP turn route, whose
# lane-D2 isolation guard forbids any model-plane name. See
# ``agent_turn_fleet_wiring.build_design_leg_exit_judge`` — the worker composition root.


async def load_design_leg_history(
    conn_factory: ConnFactory,
    *,
    workspace_id: str,
    thread_id: str,
    leg_parent_execution_id: UUID | str,
    exclude_turn_id: UUID | None = None,
) -> tuple[HistoryMessageRef, ...]:
    """§2.4's design-side assembly: THIS leg's user↔design exchanges, in thread order.

    The join is through turn parentage — every design turn's execution is parented under the
    leg's delegating execution — rather than through ``design_agent_run.leg_id``, so a turn
    whose run was never created (a crash before dispatch) still belongs to its leg's history.
    A reopened leg keeps its parent execution, so its history resumes where it was (§2.2).

    ``exclude_turn_id`` is the runner's replay stability (adversarial-review MED-4): "prior"
    means prior to THIS turn, and on a retry this turn's own user message is already durable
    — without the exclusion the rebuilt envelope drifts from the frozen run payload, the
    agent sees the message in both HISTORY and MESSAGE, and the exit judge's input changes
    across attempts.
    """

    async with conn_factory() as conn:
        result = await conn.execute(
            text(
                "SELECT m.id, m.turn_id, m.sequence, m.role, m.body_artifact_key, "
                "m.body_sha256, a.media_type, a.size_bytes "
                "FROM agent_thread_message m "
                "JOIN agent_turn t ON t.id = m.turn_id AND t.workspace_id = m.workspace_id "
                "JOIN artifact a ON a.storage_key = m.body_artifact_key "
                "WHERE m.workspace_id = :workspace AND m.thread_id = :thread "
                "AND t.role = 'design' AND t.parent_execution_id = :parent "
                "AND (CAST(:exclude_turn AS uuid) IS NULL "
                "     OR m.turn_id <> CAST(:exclude_turn AS uuid)) "
                "ORDER BY m.sequence"
            ),
            {
                "workspace": workspace_id,
                "thread": thread_id,
                "parent": str(leg_parent_execution_id),
                "exclude_turn": None if exclude_turn_id is None else str(exclude_turn_id),
            },
        )
        return tuple(
            HistoryMessageRef(
                message_id=row["id"],
                turn_id=row["turn_id"],
                sequence=int(row["sequence"]),
                role=row["role"],
                body_ref=ArtifactRef(
                    workspace_id=workspace_id,
                    artifact_key=row["body_artifact_key"],
                    sha256=row["body_sha256"],
                    media_type=row["media_type"],
                    byte_count=int(row["size_bytes"]),
                ),
            )
            for row in result.mappings()
        )


async def load_head_of_abm_history(
    conn_factory: ConnFactory,
    *,
    workspace_id: str,
    thread_id: str,
) -> tuple[HistoryMessageRef, ...]:
    """§2.4's other half: the conversation surface's thread history **without** leg transcripts.

    Filtered by turn role rather than by leg id, deliberately: head-of-abm never ingests *any*
    design exchange, whichever leg produced it. What it *does* see of a leg is exactly the
    exit summary ``finish_design_leg`` journaled at close (P3.5) — the one design-turn message
    whose id the append-only exit journal names. The journal is the authority for what crosses
    the §2.4 boundary: a summary, never a transcript.
    """

    async with conn_factory() as conn:
        result = await conn.execute(
            text(
                "SELECT m.id, m.turn_id, m.sequence, m.role, m.body_artifact_key, "
                "m.body_sha256, a.media_type, a.size_bytes "
                "FROM agent_thread_message m "
                "JOIN agent_turn t ON t.id = m.turn_id AND t.workspace_id = m.workspace_id "
                "JOIN artifact a ON a.storage_key = m.body_artifact_key "
                "WHERE m.workspace_id = :workspace AND m.thread_id = :thread "
                "AND (t.role <> 'design' OR m.id IN ("
                "    SELECT CAST(j.summary_refs->>'summary_message_id' AS uuid) "
                "    FROM design_leg_exit_journal j "
                "    WHERE j.workspace_id = m.workspace_id "
                "      AND j.summary_refs ? 'summary_message_id'"
                ")) "
                "ORDER BY m.sequence"
            ),
            {"workspace": workspace_id, "thread": thread_id},
        )
        return tuple(
            HistoryMessageRef(
                message_id=row["id"],
                turn_id=row["turn_id"],
                sequence=int(row["sequence"]),
                role=row["role"],
                body_ref=ArtifactRef(
                    workspace_id=workspace_id,
                    artifact_key=row["body_artifact_key"],
                    sha256=row["body_sha256"],
                    media_type=row["media_type"],
                    byte_count=int(row["size_bytes"]),
                ),
            )
            for row in result.mappings()
        )


async def design_legs_for_threads(
    conn_factory: ConnFactory,
    *,
    workspace_id: str,
    thread_ids: Sequence[str],
) -> dict[str, dict[str, Any]]:
    """The speaker-state anti-join: each thread's open leg (id + state), one statement.

    The read behind the P3.4 speaker projection — the sidebar chip's "who owns this thread
    now" — shaped like ``open_gate_kinds_for_threads``: one query for the whole page, absent
    means head-of-abm speaks. The partial-unique index guarantees at most one row per thread.
    """

    if not thread_ids:
        return {}
    async with conn_factory() as conn:
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT thread_id, id, state FROM design_leg "
                        "WHERE workspace_id = :ws AND state <> 'closed' "
                        "AND thread_id = ANY(CAST(:threads AS text[]))"
                    ),
                    {"ws": workspace_id, "threads": list(thread_ids)},
                )
            )
            .mappings()
            .all()
        )
    return {
        str(row["thread_id"]): {"id": str(row["id"]), "state": str(row["state"])} for row in rows
    }


async def project_design_documents(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
) -> tuple[Mapping[str, Any], ...]:
    """The project's design documents, derived from its threads' legs (gallery feed v1).

    A design document carries a workspace, not a project, so the leg is what binds it to
    one: a document belongs to the project whose threads hold the legs that name it. One
    statement, driven from the selective side — the legs of *this project's* threads →
    their non-null ``document_id``s, one row per document (``DISTINCT ON``, the document's
    **latest** leg winning, leg id breaking a tie, so each document reports one origin
    thread) → the documents behind them.

    Fail-closed tenancy like every other design read: ``workspace_id`` is pinned on both
    the leg and the document (``design_leg.document_id`` carries no foreign key, so a leg
    naming another tenant's document resolves to nothing). A document no leg names belongs
    to no project and is listed nowhere.

    Kind-aware since AD2.1: **every** doc kind a leg names is served — ``web`` documents
    and ``scene`` (ad) documents alike — and ``doc_kind`` rides along so the caller can
    map it onto the wire's ``kind``. The earlier ``WHERE d.doc_kind = 'web'`` filter made
    the rail structurally unable to reach an ad artifact (audit finding F1).
    """

    rows = (
        (
            await conn.execute(
                text(
                    "SELECT d.id, d.title, d.status, d.doc_kind, d.current_version,"
                    " d.created_at, d.updated_at, origin.thread_id AS origin_thread_id,"
                    # G-H: the card's own facts, read from the document instead of
                    # guessed downstream. Both are NULL when the document does not
                    # record them — the caller states nothing rather than inventing.
                    " d.current_scene_json #>> '{meta,artifact_type}' AS artifact_type,"
                    " d.current_scene_json #>> '{pages}' AS pages_json"
                    " FROM ("
                    "   SELECT DISTINCT ON (leg.document_id)"
                    "          leg.document_id, leg.thread_id"
                    "   FROM design_leg leg"
                    "   JOIN agent_thread t"
                    "     ON t.id = leg.thread_id AND t.workspace_id = leg.workspace_id"
                    "   WHERE leg.workspace_id = :ws"
                    "     AND t.project_id = :project"
                    "     AND leg.document_id IS NOT NULL"
                    "   ORDER BY leg.document_id, leg.created_at DESC, leg.id DESC"
                    " ) origin"
                    " JOIN design_document d"
                    "   ON d.id = origin.document_id AND d.workspace_id = :ws"
                    " ORDER BY d.updated_at DESC, d.id"
                ),
                {"ws": workspace_id, "project": project_id},
            )
        )
        .mappings()
        .all()
    )
    return tuple(dict(row) for row in rows)


def document_page_pixels(pages_json: str | None) -> tuple[int, int] | None:
    """The document's own page size in PIXELS, or ``None`` when it has none.

    G-H: the gallery card used to state a hardcoded ``1080x1080`` for every
    design artifact. The document knows its real size, so the feed carries it
    and a card with no page states nothing at all.

    The engine stores a page canonically (``unit`` may be ``pt`` after an
    authored ``px`` page is normalized), so the pixel truth is read in the same
    precedence the editor's own resolver uses: the raster output it would
    export, else the authored source when that was already px, else the
    canonical box. A malformed scene yields ``None`` — never a guess.
    """

    if not pages_json:
        return None
    try:
        pages = json.loads(pages_json)
    except (TypeError, ValueError):
        return None
    if not isinstance(pages, dict):
        return None
    # Insertion order is the scene's own page order; v1 ads are single-page and
    # the rail shows one size, so the first page is the document's size.
    page = next((value for value in pages.values() if isinstance(value, dict)), None)
    size = page.get("size") if page else None
    if not isinstance(size, dict):
        return None

    output = size.get("output")
    raster = output.get("raster") if isinstance(output, dict) else None
    if isinstance(raster, dict):
        width, height = raster.get("width_px"), raster.get("height_px")
        if isinstance(width, (int, float)) and isinstance(height, (int, float)):
            return int(width), int(height)

    source = size.get("source")
    if isinstance(source, dict) and source.get("unit") == "px":
        width, height = source.get("width"), source.get("height")
        if isinstance(width, (int, float)) and isinstance(height, (int, float)):
            return int(width), int(height)

    if size.get("unit") == "px":
        width, height = size.get("width"), size.get("height")
        if isinstance(width, (int, float)) and isinstance(height, (int, float)):
            return int(width), int(height)
    return None


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _assistant_summary(run: dict[str, Any]) -> str:
    """A truthful one-paragraph thread record of what the design turn did.

    Derived from the run's terminal result — never invented. Part IV owns the rich rendering
    (the canvas preview, the proposal card); the durable message is the honest minimum.

    The two turn kinds carry their reason under different keys, so the text is derived per
    kind: a scene turn's ``stop_reason`` (the reviewer's verdict), a web turn's ``summary``
    (the orchestrator's own note — the web result shape has no ``stop_reason``). A web turn
    edits a durable artifact rather than proposing a scene, so its sentence names the
    document it changed and the version it landed.
    """

    result = run.get("result") or {}
    if str(result.get("doc_kind") or "") == "web":
        return _web_turn_summary(run, result)
    status = str(result.get("status") or run.get("status") or "unknown")
    reason = result.get("stop_reason")
    if isinstance(reason, str) and reason.strip():
        return f"Design turn {status}: {reason.strip()}"
    return f"Design turn {status}."


def _web_turn_summary(run: dict[str, Any], result: dict[str, Any]) -> str:
    """The web half of :func:`_assistant_summary` — names the artifact, invents nothing."""

    status = str(result.get("status") or run.get("status") or "unknown")
    document_id = run.get("document_id")
    subject = f"website document {document_id}" if document_id else "the website document"
    version = result.get("current_version")
    if isinstance(version, int):
        subject = f"{subject} (now version {version})"
    note = result.get("summary")
    if isinstance(note, str) and note.strip():
        return f"Design turn {status} on {subject}: {note.strip()}"
    return f"Design turn {status} on {subject}."


def _account_card(account: dict[str, Any]) -> dict[str, JsonValue]:
    """The compact by-value account context a personalized web turn runs against.

    Key-for-key the card the design API's own web-turn route freezes into the envelope
    (``lumen_api.main.start_web_turn``), because the executor reads exactly one place —
    ``envelope.config['account_card']`` — and nothing downstream re-reads the account row. A
    platform-frozen card therefore needs no design-side change; a card with different keys
    would silently drop context.
    """

    return {
        "name": account["name"],
        "domain": account["domain"],
        "logo_asset_id": account["logo_asset_id"],
        "data": account["data"],
        "notes": account["notes"],
    }


class DesignLegTurnRunner:
    """Run one user message as one design turn on its open leg."""

    def __init__(
        self,
        *,
        profiles: AgentProfileRegistry,
        artifacts: DurableAgentArtifactStore,
        turns: DbAgentTurnJournal,
        history: AgentHistoryStore,
        lane: DesignLegLaneDriver,
        exit_judge: DesignLegExitJudge | None = None,
        finisher: DesignLegFinisher | None = None,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._profiles = profiles
        self._artifacts = artifacts
        self._turns = turns
        self._history = history
        self._lane = lane
        # The P3.7 §2.2 bridge. Both seams optional and fail-safe: a deployment without a
        # judge (or without a finisher to execute its verdicts) simply never exits a leg
        # from inside a turn — every message designs, and the leg closes only through a
        # direct ``finish_design_leg`` invocation.
        self._exit_judge = exit_judge
        self._finisher = finisher
        self._conn_factory = conn_factory

    async def run_leg_turn(
        self,
        *,
        submission: AgentTurnSubmissionRow,
        leg: dict[str, Any],
        user_message_ref: ArtifactRef,
        focus_refs: tuple[DomainObjectRef, ...],
        card_payload: dict[str, JsonValue],
        stream: TurnStreamEmitter | None,
    ) -> DesignLegTurnResult:
        workspace_id = submission.workspace_id
        leg_id = str(leg["id"])
        parent_execution_id = UUID(str(leg["parent_execution_id"]))
        turn_id = submission.turn_id
        execution_id = design_leg_execution_id(turn_id)
        resolved = self._profiles.resolve(AgentRole.DESIGN)

        async with self._conn_factory() as conn:
            project = await get_project(conn, submission.project_id)
            if project is None or project.workspace_id != workspace_id:
                raise ValueError("the design-leg submission names no project in its workspace")
            # §2.4: the leg history the envelope carries is everything BEFORE this turn.
            prior_history = await load_design_leg_history(
                self._conn_factory,
                workspace_id=workspace_id,
                thread_id=submission.thread_id,
                leg_parent_execution_id=parent_execution_id,
                # "Prior" means prior to THIS turn: on a retry the first attempt's own user
                # message is already durable and must not re-enter as history (MED-4).
                exclude_turn_id=turn_id,
            )
            bundle_ref = await self._bundle_ref(conn, leg=leg, workspace_id=workspace_id)
            # The whole row, not just its scene: the envelope branches on ``doc_kind`` and a
            # web turn is defined against the document's CURRENT version (its CAS base).
            pinned_document: dict[str, Any] | None = None
            if leg.get("document_id") is not None:
                try:
                    pinned_document = await get_document(
                        conn,
                        workspace_id=workspace_id,
                        document_id=str(leg["document_id"]),
                    )
                except DesignNotFoundError:
                    # The pinned document vanished between delegation and this turn: dispatch
                    # with an empty scene and let the design runtime's own gates speak — a
                    # platform guess here would design against fabricated state.
                    log.warning(
                        "design_leg.pinned_document_missing",
                        leg_id=leg_id,
                        document_id=str(leg["document_id"]),
                    )
            await self._ensure_execution(
                conn,
                execution_id=execution_id,
                workspace_id=workspace_id,
                project_id=submission.project_id,
                parent_execution_id=parent_execution_id,
                user_message_ref=user_message_ref,
                manifest_sha256=resolved.resource_manifest.aggregate_sha256,
            )

        card_ref = await self._artifact(
            workspace_id,
            "application/vnd.clue.project-conversation-card+json",
            card_payload,
            project_id=submission.project_id,
        )
        budget_ref = await self._artifact(
            workspace_id,
            "application/vnd.clue.agent-budget-envelope+json",
            {
                "schema_version": "1",
                "limit_millicents": DESIGN_LEG_BUDGET_LIMIT_MILLICENTS,
                "external_research_budget_cents": "0",
                "scope": (
                    "one design-leg turn; model spend is measured at the gateway per design "
                    "role (P3.2 single-authority attribution)"
                ),
            },
            project_id=submission.project_id,
        )
        manifest_ref = await self._artifact(
            workspace_id,
            "application/vnd.clue.agent-resource-manifest+json",
            resolved.resource_manifest.model_dump(mode="json"),
            project_id=submission.project_id,
        )
        bundle_context = (
            ProjectContextArtifact(
                name="design-delegation-bundle",
                artifact_ref=bundle_ref,
                domain_ref=DomainObjectRef(
                    workspace_id=workspace_id,
                    object_type="design_delegation_bundle",
                    object_id=leg_id,
                    # Bundle schema v1; one immutable bundle per leg.
                    version=1,
                ),
            ),
        )
        leg_ref = DomainObjectRef(
            workspace_id=workspace_id,
            object_type="design_leg",
            object_id=leg_id,
            version=None,
        )
        request = AgentTurnRequest(
            turn_id=turn_id,
            thread_id=submission.thread_id,
            constitution=AgentConstitution(
                workspace_id=workspace_id,
                project_id=submission.project_id,
                execution_id=execution_id,
                # The one identity rule, unchanged on the design path: the acting human,
                # from the durable submission row.
                actor_id=submission.submitted_by_user_id,
                role=AgentRole.DESIGN,
                brand_id=project.brand_id,
                product_id=project.product_id,
                # No platform workspace lease: the design runtime's virtual workspace is keyed
                # to its run. The root records the leg address honestly instead.
                workspace_root_id=f"design-leg:{leg_id}",
                project_card_ref=card_ref,
                budget_envelope_ref=budget_ref,
                profile_ref=resolved.profile_ref,
                resource_manifest_ref=manifest_ref,
                resource_manifest_sha256=resolved.resource_manifest.aggregate_sha256,
                focus_refs=(leg_ref, *focus_refs),
                project_context_artifacts=bundle_context,
            ),
            user_message_artifact_ref=user_message_ref,
            focus_refs=focus_refs,
            requested_at=submission.requested_at,
        )
        await self._turns.create(
            request=request,
            profile=resolved.profile,
            submitted_by_user_id=submission.submitted_by_user_id,
            submitted_via_membership_id=submission.submitted_via_membership_id,
        )
        await self._history.append(
            message_id=uuid5(turn_id, "user"),
            turn_id=turn_id,
            workspace_id=workspace_id,
            thread_id=submission.thread_id,
            role="user",
            body_ref=user_message_ref,
        )
        committed = await self._turns.load_committed_outcome(
            turn_id=turn_id,
            workspace_id=workspace_id,
        )
        if stream is not None:
            await stream.turn_started()
        if committed is not None:
            assistant_message = await self._project_committed(
                committed=committed,
                submission=submission,
            )
            if stream is not None:
                await stream.rehydrate(reason="turn_replayed")
                await stream.turn_finished(
                    status=committed.status.value,
                    failure_code=committed.failure_code,
                    replayed=True,
                )
            return DesignLegTurnResult(
                outcome=committed,
                assistant_message=assistant_message,
                replayed=True,
            )

        await self._turns.mark_running(turn_id=turn_id, workspace_id=workspace_id)
        # Failure containment (adversarial-review fix): once the turn is RUNNING, any
        # raise below — the unavailable lane, a join timeout, a bundle read, a finisher
        # fault — used to leave the agent_turn 'running' forever with no terminal frame:
        # an endless spinner and an unprunable stream. The head-of-abm runner's armor,
        # ported (DurableDeepAgentTurnRunner): mark abandoned with an honest reason,
        # land the terminal frame, re-raise so the fleet task still fails loudly. True
        # process death still skips this — that is what the derived-id retry
        # convergence is for.
        try:
            if leg["state"] == "closed":
                # P3.7 crash-window re-entry: the ONLY way a closed leg reaches this runner is
                # the routing rule's closed-by-turn fallback — this very turn closed the leg and
                # died before finalizing. The close (journal, summary message, re-delivery,
                # ``leg.closed`` frame) committed atomically in the tool's transaction; what
                # remains is the finalization, which converges below.
                return await self._exit_leg(
                    submission=submission,
                    leg_id=leg_id,
                    execution_id=execution_id,
                    reason=str(leg["close_reason"]),
                    stream=stream,
                )

            # --- the §2.2 exit bridge (P3.7): judge BEFORE designing ---------------------------
            # Every exit category is a judgment about the INCOMING message (lock-in, out-of-scope,
            # abandon), so the judgment runs pre-dispatch: an exiting turn spends nothing on the
            # design lane. The fail-safe envelope (P3.6) means a broken judge can only continue.
            exit_decision = await self._judge_exit(
                leg=leg,
                prior_history=prior_history,
                user_message_ref=user_message_ref,
            )
            if exit_decision is not None and exit_decision.action == "finish":
                assert exit_decision.reason is not None  # decide_exit forbids reasonless finish
                return await self._exit_leg(
                    submission=submission,
                    leg_id=leg_id,
                    execution_id=execution_id,
                    reason=exit_decision.reason,
                    stream=stream,
                )

            # --- G1: the finalized-document gate (founder ruling, 2026-08-19) ------------------
            # A leg may edit a DRAFT document — even one whose older version is published — but
            # may never mutate a FINALIZED one. The refusal happens here, AFTER the exit
            # judgment (closing a leg is not a mutation, so "lock it in" still works on a
            # finalized document) and BEFORE dispatch: no design run row, no envelope, no
            # assistant sentence, and the leg is never marked running, so it stays open.
            if pinned_document is not None and is_finalized_document(pinned_document):
                log.warning(
                    "design_leg.document_finalized",
                    leg_id=leg_id,
                    turn_id=str(turn_id),
                    document_id=str(pinned_document.get("id")),
                )
                return await self._fail_turn(
                    submission=submission,
                    execution_id=execution_id,
                    failure_code=DESIGN_LEG_DOCUMENT_FINALIZED,
                    stream=stream,
                )

            # --- G2: resolve and freeze the account card (founder ruling, 2026-08-19) ---------
            # A web document that carries an account_id is a 1:1 page: every chat-driven turn
            # resolves that account IN THIS WORKSPACE and freezes the card by value, exactly as
            # the design API's own route does before enqueue. Fail-closed — an unresolvable
            # stamp refuses the turn rather than generating an un-personalized page in silence.
            account_card: dict[str, JsonValue] | None = None
            account_id = (
                pinned_document.get("account_id")
                if pinned_document is not None and pinned_document.get("doc_kind") == "web"
                else None
            )
            if account_id:
                async with self._conn_factory() as conn:
                    account = await design_accounts.get_web_account(
                        conn, workspace_id=workspace_id, account_id=str(account_id)
                    )
                if account is None:
                    # Workspace-scoped read, so this is both "no such account" and
                    # "another workspace's account" — one refusal for both.
                    log.warning(
                        "design_leg.account_unresolved",
                        leg_id=leg_id,
                        turn_id=str(turn_id),
                        document_id=str(pinned_document.get("id") if pinned_document else None),
                        account_id=str(account_id),
                    )
                    return await self._fail_turn(
                        submission=submission,
                        execution_id=execution_id,
                        failure_code=DESIGN_LEG_ACCOUNT_UNRESOLVED,
                        stream=stream,
                    )
                account_card = _account_card(account)

            run = await self._dispatch(
                submission=submission,
                leg=leg,
                leg_id=leg_id,
                execution_id=execution_id,
                user_message_ref=user_message_ref,
                prior_history=prior_history,
                pinned_document=pinned_document,
                account_card=account_card,
                focus_refs=focus_refs,
                workspace_id=workspace_id,
            )
            await self._leg_back_to_awaiting(
                workspace_id=workspace_id,
                leg_id=leg_id,
                submission=submission,
            )

            if run["status"] != "succeeded":
                log.warning(
                    "design_leg.turn_failed",
                    leg_id=leg_id,
                    turn_id=str(turn_id),
                    run_id=str(run.get("run_id")),
                )
                return await self._fail_turn(
                    submission=submission,
                    execution_id=execution_id,
                    failure_code=DESIGN_LEG_TURN_FAILED,
                    stream=stream,
                )

            assistant_message = _assistant_summary(run)
            assistant_ref = await self._artifact_text(
                workspace_id,
                assistant_message,
                project_id=submission.project_id,
            )
            envelope = AgentFinalizeEnvelope(
                finalization_id=uuid5(_FINALIZATION_NAMESPACE, str(turn_id)),
                execution_id=execution_id,
                status=FinalizeStatus.AWAITING_INPUT,
                user_message_artifact_ref=assistant_ref,
                domain_refs=(
                    DomainObjectRef(
                        workspace_id=workspace_id,
                        object_type="design_agent_run",
                        object_id=str(run["run_id"]),
                        version=None,
                    ),
                ),
                # The leg IS the open interaction: the turn is done, the leg awaits the user.
                open_gate_refs=(leg_ref,),
                # Replay-stable on purpose (adversarial-review fix): the finalization id is
                # derived, so every immutable envelope field must be too — a wall-clock
                # stamp made a crash-retry's envelope differ and record_finalization refuse
                # forever. The submission's accept time is the durable moment this turn
                # already owns (the head-of-abm runner's requested_at precedent).
                finalized_at=submission.requested_at,
            )
            await self._turns.record_finalization(
                turn_id=turn_id,
                workspace_id=workspace_id,
                envelope=envelope,
            )
            envelope_ref = await self._artifact(
                workspace_id,
                "application/vnd.clue.agent-finalize-envelope+json",
                json.loads(envelope.model_dump_json()),
                project_id=submission.project_id,
            )
            await self._turns.commit_finalization_authority(
                turn_id=turn_id,
                workspace_id=workspace_id,
                envelope=envelope,
                envelope_ref=envelope_ref,
            )
            await self._history.append(
                message_id=uuid5(turn_id, "assistant"),
                turn_id=turn_id,
                workspace_id=workspace_id,
                thread_id=submission.thread_id,
                role="assistant",
                body_ref=assistant_ref,
            )
            if stream is not None:
                # No platform text was streamed (design progress rides the design_run subject,
                # D3); the honest instruction is to fetch the canonical message.
                await stream.rehydrate(reason="design_turn_summary")
                await stream.turn_finished(status="awaiting_input")
            return DesignLegTurnResult(
                outcome=AgentTurnOutcome(
                    turn_id=turn_id,
                    execution_id=execution_id,
                    status=AgentExecutionStatus.AWAITING_INPUT,
                    finalization_ref=envelope_ref,
                ),
                assistant_message=assistant_message,
                replayed=False,
            )
        except BaseException:
            await self._contain_crash(turn_id=turn_id, workspace_id=workspace_id, stream=stream)
            raise

    async def _fail_turn(
        self,
        *,
        submission: AgentTurnSubmissionRow,
        execution_id: ExecutionId,
        failure_code: str,
        stream: TurnStreamEmitter | None,
    ) -> DesignLegTurnResult:
        """The one honest failed-turn shape, shared by every non-crash failure.

        The turn is marked unfinalized with its typed code and the stream lands a terminal
        failed frame; nothing is finalized and no assistant message is manufactured. The two
        pre-dispatch refusals (G1, G2) reach it before the leg is ever marked running, so the
        leg stays ``open_awaiting_user`` and the user can say something else on it; the failed
        design run reaches it after ``_leg_back_to_awaiting`` has already put it back there.
        """

        await self._turns.mark_unfinalized(
            turn_id=submission.turn_id,
            workspace_id=submission.workspace_id,
            reason_code=failure_code,
            abandoned=False,
        )
        if stream is not None:
            await stream.turn_finished(status="failed", failure_code=failure_code)
        return DesignLegTurnResult(
            outcome=AgentTurnOutcome(
                turn_id=submission.turn_id,
                execution_id=execution_id,
                status=AgentExecutionStatus.FAILED,
                failure_code=failure_code,
            ),
            assistant_message=None,
            replayed=False,
        )

    async def _contain_crash(
        self,
        *,
        turn_id: UUID,
        workspace_id: str,
        stream: TurnStreamEmitter | None,
    ) -> None:
        """Best-effort terminalization of a crashed turn body (never masks the raise).

        Both writes are suppressed on their own failure: containment must never turn one
        crash into two, and ``mark_unfinalized`` already refuses to touch a turn whose
        finalization committed — so a crash after the commit leaves the committed truth.
        """

        try:
            await self._turns.mark_unfinalized(
                turn_id=turn_id,
                workspace_id=workspace_id,
                reason_code=DESIGN_LEG_TURN_CRASHED,
                abandoned=True,
            )
        except Exception:
            log.warning("design_leg.containment_mark_failed", turn_id=str(turn_id))
        if stream is not None:
            try:
                await stream.turn_finished(
                    status="failed",
                    failure_code=DESIGN_LEG_TURN_CRASHED,
                )
            except Exception:
                log.warning("design_leg.containment_stream_failed", turn_id=str(turn_id))

    # -- the §2.2 exit bridge ------------------------------------------------------------------

    async def _judge_exit(
        self,
        *,
        leg: dict[str, Any],
        prior_history: Sequence[HistoryMessageRef],
        user_message_ref: ArtifactRef,
    ) -> ExitDecision | None:
        """Run the exit judgment for this turn, or ``None`` when the bridge is not composed.

        Fail-safe end to end: a judge that raises, returns garbage, or asks for a reasonless
        finish yields CONTINUE (P3.6's ``decide_exit``), and a judge without a finisher to
        execute its verdicts is treated as absent — loudly, once per turn.
        """

        if self._exit_judge is None:
            return None
        if self._finisher is None:
            log.warning("design_leg.exit_judge_without_finisher")
            return None
        workspace_id = str(leg["workspace_id"])
        bundle = await self._bundle_body(leg=leg, workspace_id=workspace_id)
        history: list[tuple[str, str]] = []
        for item in prior_history:
            history.append((item.role, (await self._artifacts.read(item.body_ref)).decode()))
        message = (await self._artifacts.read(user_message_ref)).decode()
        try:
            judgment: ExitJudgment | None = await self._exit_judge(
                brief=str(bundle.get("brief") or ""),
                history=tuple(history),
                message=message,
            )
        except Exception:
            log.warning("design_leg.exit_judge_raised", exc_info=True)
            judgment = None
        decision = decide_exit(judgment)
        if decision.fail_safe:
            log.info("design_leg.exit_judgment_fail_safe", leg_id=str(leg["id"]))
        return decision

    async def _exit_leg(
        self,
        *,
        submission: AgentTurnSubmissionRow,
        leg_id: str,
        execution_id: ExecutionId,
        reason: str,
        stream: TurnStreamEmitter | None,
    ) -> DesignLegTurnResult:
        """Close the leg through the governed tool and finalize this turn ``COMPLETED``.

        The bridge-time finalize shape: the leg is closed, so the envelope claims COMPLETED
        with NO open gate refs, and the runner appends no assistant message of its own — the
        finish tool's leg-summary message is the turn's one durable assistant record.
        """

        workspace_id = submission.workspace_id
        turn_id = submission.turn_id
        summary = DESIGN_LEG_EXIT_SUMMARIES.get(reason, DESIGN_LEG_EXIT_SUMMARIES["abandoned"])
        if self._finisher is not None:
            # A crash-retried exit replays the same governed invocation (derived operation
            # id + the tool's own closing-turn journal replay) and returns the ORIGINAL
            # decision's references.
            references = await self._finisher(
                workspace_id=workspace_id,
                turn_id=turn_id,
                reason=reason,
                summary=summary,
            )
            closed_reason = str(references.get("reason") or reason)
            summary = DESIGN_LEG_EXIT_SUMMARIES.get(closed_reason, summary)
        # else: closed-leg re-entry on a worker without the bridge — the close itself
        # committed atomically with the tool's transaction, so only the finalize remains.

        summary_ref = await self._artifact_text(
            workspace_id,
            summary,
            project_id=submission.project_id,
        )
        envelope = AgentFinalizeEnvelope(
            finalization_id=uuid5(_FINALIZATION_NAMESPACE, str(turn_id)),
            execution_id=execution_id,
            status=FinalizeStatus.COMPLETED,
            user_message_artifact_ref=summary_ref,
            domain_refs=(
                DomainObjectRef(
                    workspace_id=workspace_id,
                    object_type="design_leg",
                    object_id=leg_id,
                    version=None,
                ),
            ),
            open_gate_refs=(),
            # Replay-stable on purpose (adversarial-review fix): the finalization id is
            # derived, so every immutable envelope field must be too — a wall-clock
            # stamp made a crash-retry's envelope differ and record_finalization refuse
            # forever. The submission's accept time is the durable moment this turn
            # already owns (the head-of-abm runner's requested_at precedent).
            finalized_at=submission.requested_at,
        )
        await self._turns.record_finalization(
            turn_id=turn_id,
            workspace_id=workspace_id,
            envelope=envelope,
        )
        envelope_ref = await self._artifact(
            workspace_id,
            "application/vnd.clue.agent-finalize-envelope+json",
            json.loads(envelope.model_dump_json()),
            project_id=submission.project_id,
        )
        await self._turns.commit_finalization_authority(
            turn_id=turn_id,
            workspace_id=workspace_id,
            envelope=envelope,
            envelope_ref=envelope_ref,
        )
        if stream is not None:
            await stream.rehydrate(reason="design_leg_closed")
            await stream.turn_finished(status="completed")
        log.info(
            "design_leg.exited",
            leg_id=leg_id,
            turn_id=str(turn_id),
            reason=reason,
        )
        return DesignLegTurnResult(
            outcome=AgentTurnOutcome(
                turn_id=turn_id,
                execution_id=execution_id,
                status=AgentExecutionStatus.COMPLETED,
                finalization_ref=envelope_ref,
            ),
            assistant_message=summary,
            replayed=False,
        )

    # -- dispatch ------------------------------------------------------------------------------

    async def _dispatch(
        self,
        *,
        submission: AgentTurnSubmissionRow,
        leg: dict[str, Any],
        leg_id: str,
        execution_id: ExecutionId,
        user_message_ref: ArtifactRef,
        prior_history: Sequence[HistoryMessageRef],
        pinned_document: dict[str, Any] | None,
        account_card: dict[str, JsonValue] | None,
        focus_refs: tuple[DomainObjectRef, ...],
        workspace_id: str,
    ) -> dict[str, Any]:
        """Create (or re-join) the derived design run and drive it terminal."""

        run_id = design_leg_run_id(submission.turn_id)
        async with self._conn_factory() as conn:
            run = await design_runs.get_run(conn, workspace_id=workspace_id, run_id=run_id)
        if run is not None and run["status"] in _TERMINAL_RUN_STATUSES:
            return run  # a crashed attempt already finished the design work; re-join it

        envelope = await self._envelope(
            submission=submission,
            leg=leg,
            leg_id=leg_id,
            execution_id=execution_id,
            run_id=run_id,
            user_message_ref=user_message_ref,
            prior_history=prior_history,
            pinned_document=pinned_document,
            account_card=account_card,
            focus_refs=focus_refs,
            workspace_id=workspace_id,
        )
        if run is None:
            async with self._conn_factory() as conn:
                if leg["state"] == "open_awaiting_user":
                    await design_legs.mark_leg_running(
                        conn, workspace_id=workspace_id, leg_id=leg_id
                    )
                await design_runs.create_run(
                    conn,
                    workspace_id=workspace_id,
                    run_id=run_id,
                    document_id=leg.get("document_id"),
                    # The row's kind mirrors the envelope's discriminant (the fleet dispatches
                    # on the envelope; the column is what an operator and the projections read).
                    kind=DesignRunKind(envelope.kind),
                    # The row payload IS the frozen envelope — the design substrate's
                    # re-offer contract (the reaper re-enqueues the row's own payload
                    # verbatim), so a stranded leg run replays as a valid design_job and
                    # strand repair becomes a working second-chance completion path.
                    payload=envelope.model_dump(mode="json"),
                    work_id=envelope.work_id,
                    leg_id=leg_id,
                    execution_id=UUID(str(execution_id)),
                )
        await self._lane.drive(envelope=envelope)
        async with self._conn_factory() as conn:
            run = await design_runs.get_run(conn, workspace_id=workspace_id, run_id=run_id)
        if run is None or run["status"] not in _TERMINAL_RUN_STATUSES:
            raise RuntimeError("the design lane returned without a terminal design run")
        return run

    async def _envelope(
        self,
        *,
        submission: AgentTurnSubmissionRow,
        leg: dict[str, Any],
        leg_id: str,
        execution_id: ExecutionId,
        run_id: str,
        user_message_ref: ArtifactRef,
        prior_history: Sequence[HistoryMessageRef],
        pinned_document: dict[str, Any] | None,
        account_card: dict[str, JsonValue] | None,
        focus_refs: tuple[DomainObjectRef, ...],
        workspace_id: str,
    ) -> DesignTurnEnvelope:
        bundle = await self._bundle_body(leg=leg, workspace_id=workspace_id)
        message_text = (await self._artifacts.read(user_message_ref)).decode()
        history_texts: list[dict[str, JsonValue]] = []
        for item in prior_history:
            history_texts.append(
                {
                    "role": item.role,
                    "text": (await self._artifacts.read(item.body_ref)).decode(),
                }
            )
        document = pinned_document or {}
        target_node_ids = tuple(
            ref.object_id for ref in focus_refs if ref.object_type == "design_node"
        )
        resolved_targets = (
            resolve_scene_targets(document.get("scene") or {}, target_node_ids)
            if target_node_ids
            else None
        )
        # B1: the leg document's kind decides which design runtime executes the turn. A web
        # document takes the ``web_turn`` path with a ``WebTurnRequest``-shaped request; a
        # scene document (or no pinned document at all — nothing to read a kind from) keeps
        # the shipped ``agent_turn`` request byte-for-byte.
        kind: Literal["agent_turn", "web_turn"] = (
            "web_turn" if document.get("doc_kind") == "web" else "agent_turn"
        )
        request: dict[str, JsonValue]
        if kind == "web_turn":
            request = {
                "prompt": message_text,
                # Read once, HERE, because the envelope is frozen as the run row's payload and
                # a re-offer replays it verbatim. The executor's CAS re-check against the
                # stored document stays the authority on staleness: a turn that lost the race
                # comes back conflicted rather than clobbering a newer human edit.
                "base_version": int(document.get("current_version") or 0),
                # v1 (plan F4): no scoped targets, no model override, no account — the design
                # request model defaults each of them, and a fabricated value here would be a
                # platform guess. ``previous_turn_outcome`` has no WebTurnRequest field at all;
                # the clarification echo is a scene-path contract.
            }
        else:
            request = {
                "prompt": message_text,
                "scene": document.get("scene") or {},
                "document_id": leg.get("document_id"),
                "previous_turn_outcome": submission.previous_turn_outcome,
                **(
                    {
                        "active_page_id": resolved_targets.active_page_id,
                        "target_node_ids": list(resolved_targets.target_node_ids),
                    }
                    if resolved_targets is not None
                    else {}
                ),
            }
        # ``ConfigPayload`` — deliberately opaque at the substrate (clue_design.envelopes).
        config: dict[str, Any] = {
            "request": request,
            "delegation_bundle": bundle,
            "history": history_texts,
            "leg": {
                "leg_id": leg_id,
                "thread_id": submission.thread_id,
                "agent_turn_id": str(submission.turn_id),
                "execution_id": str(execution_id),
                "brand_kit_id": leg.get("brand_kit_id"),
                "brand_kit_version": leg.get("brand_kit_version"),
                "document_version_guard": leg.get("document_version_guard"),
                # genad Task 5: the SCENE executor owns its persist (the genweb ruling extended
                # to ads), so a scene-pinned leg turn needs a CAS base. Read ONCE, here, because
                # the envelope is frozen as the run row's payload and a re-offer replays it
                # verbatim; the executor's own re-check against the stored document stays the
                # authority on staleness. The key is deliberately ABSENT for a web-pinned leg
                # (``request.base_version`` already pins that turn — two copies of one CAS base
                # is exactly the drift this freeze exists to prevent) and for a document-less
                # legacy leg (nothing to persist into; the executor reads a missing key as
                # "preview-only" rather than a fabricated version zero).
                **(
                    {"document_base_version": int(document.get("current_version") or 0)}
                    if kind == "agent_turn" and leg.get("document_id") and document
                    else {}
                ),
                "focus_refs": [
                    {
                        "object_type": ref.object_type,
                        "object_id": ref.object_id,
                        "version": ref.version,
                    }
                    for ref in focus_refs
                ],
            },
        }
        if account_card is not None:
            # G2: frozen by value, and only when the document actually named an account — an
            # un-personalized turn's envelope carries no such key at all (the design route's
            # own shape, and the executor treats a missing card exactly as it treats a null).
            config["account_card"] = account_card
        return DesignTurnEnvelope(
            kind=kind,
            work_id=design_runs.work_id_for_run(run_id),
            workspace_id=workspace_id,
            run_id=run_id,
            checkpoint_thread_id=run_id,
            document_id=leg.get("document_id"),
            config=config,
        )

    # -- helpers -------------------------------------------------------------------------------

    async def _bundle_ref(
        self,
        conn: Any,
        *,
        leg: dict[str, Any],
        workspace_id: str,
    ) -> ArtifactRef:
        key = leg.get("bundle_artifact_ref")
        if not key:
            raise ValueError("this design leg records no delegation bundle artifact")
        row = (
            (
                await conn.execute(
                    text(
                        "SELECT content_sha256, media_type, size_bytes FROM artifact "
                        "WHERE storage_key = :key AND workspace_id = :ws "
                        "AND erased_at IS NULL AND purged_at IS NULL"
                    ),
                    {"key": key, "ws": workspace_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ValueError("the design leg's delegation bundle artifact is missing")
        return ArtifactRef(
            workspace_id=workspace_id,
            artifact_key=str(key),
            sha256=row["content_sha256"],
            media_type=row["media_type"],
            byte_count=int(row["size_bytes"]),
        )

    async def _bundle_body(self, *, leg: dict[str, Any], workspace_id: str) -> dict[str, JsonValue]:
        async with self._conn_factory() as conn:
            ref = await self._bundle_ref(conn, leg=leg, workspace_id=workspace_id)
        body = json.loads(await self._artifacts.read(ref))
        if not isinstance(body, dict):
            raise ValueError("the delegation bundle artifact is not a JSON object")
        return body

    async def _ensure_execution(
        self,
        conn: Any,
        *,
        execution_id: ExecutionId,
        workspace_id: str,
        project_id: str,
        parent_execution_id: UUID,
        user_message_ref: ArtifactRef,
        manifest_sha256: str,
    ) -> None:
        inserted = await conn.execute(
            text(
                "INSERT INTO execution "
                "(id, workspace_id, project_id, parent_execution_id, started_by, "
                " parameter_artifact_key, parameter_manifest_hash, pin_manifest_hash) "
                "VALUES (:id, :workspace, :project, :parent, 'human', :key, :sha, :manifest) "
                "ON CONFLICT (id) DO NOTHING RETURNING id"
            ),
            {
                "id": execution_id,
                "workspace": workspace_id,
                "project": project_id,
                "parent": parent_execution_id,
                "key": user_message_ref.artifact_key,
                "sha": user_message_ref.sha256,
                "manifest": manifest_sha256,
            },
        )
        if inserted.first() is not None:
            return
        row = (
            (
                await conn.execute(
                    text(
                        "SELECT workspace_id, project_id, parent_execution_id "
                        "FROM execution WHERE id = :id"
                    ),
                    {"id": execution_id},
                )
            )
            .mappings()
            .one()
        )
        if (
            row["workspace_id"] != workspace_id
            or row["project_id"] != project_id
            or row["parent_execution_id"] != parent_execution_id
        ):
            raise ValueError("design-leg execution id already has different immutable inputs")

    async def _leg_back_to_awaiting(
        self,
        *,
        workspace_id: str,
        leg_id: str,
        submission: AgentTurnSubmissionRow,
    ) -> None:
        async with self._conn_factory() as conn:
            current = await design_legs.get_leg(conn, workspace_id=workspace_id, leg_id=leg_id)
            if current["state"] == "running":
                await design_legs.mark_leg_awaiting_user(
                    conn, workspace_id=workspace_id, leg_id=leg_id
                )
                # Delta 8: the lifecycle frame rides the same transaction as the transition it
                # announces. A converging retry finds the leg already awaiting and emits nothing
                # — a frame is a transition's announcement, not a turn's.
                await emit_turn_event(
                    conn,
                    workspace_id=workspace_id,
                    project_id=submission.project_id,
                    thread_id=submission.thread_id,
                    turn_id=submission.turn_id,
                    event_type=TurnEventType.LEG_AWAITING_USER,
                    payload={"leg_id": leg_id},
                )

    async def _project_committed(
        self,
        *,
        committed: AgentTurnOutcome,
        submission: AgentTurnSubmissionRow,
    ) -> str | None:
        if committed.finalization_ref is None:
            return None
        envelope = AgentFinalizeEnvelope.model_validate_json(
            await self._artifacts.read(committed.finalization_ref)
        )
        if envelope.user_message_artifact_ref is None:
            return None
        assistant_message = (
            await self._artifacts.read(envelope.user_message_artifact_ref)
        ).decode()
        await self._history.append(
            message_id=uuid5(submission.turn_id, "assistant"),
            turn_id=submission.turn_id,
            workspace_id=submission.workspace_id,
            thread_id=submission.thread_id,
            role="assistant",
            body_ref=envelope.user_message_artifact_ref,
        )
        return assistant_message

    async def _artifact(
        self,
        workspace_id: str,
        media_type: str,
        payload: object,
        *,
        project_id: str,
    ) -> ArtifactRef:
        return await self._artifacts.persist_body(
            workspace_id=workspace_id,
            data=_canonical_json(payload),
            media_type=media_type,
            project_bindings=((project_id, "design_leg_context"),),
        )

    async def _artifact_text(
        self,
        workspace_id: str,
        body: str,
        *,
        project_id: str,
    ) -> ArtifactRef:
        return await self._artifacts.persist_body(
            workspace_id=workspace_id,
            data=body.encode(),
            media_type="text/plain",
            project_bindings=((project_id, "design_leg_context"),),
        )
