"""PC-C8 §7 — the two bounded governed inspection tools the project card's omissions point at.

The card is hard-bounded (§3.1), so history is *durable and reachable*, never resident in the
opening prompt. These two read-only tools are that reachability:

* ``inspect_statement_history`` — interview statements with their supersession/correction lineage
  and their words, resolved through the **shared** evidence reader
  (:func:`~clue_api.statement_evidence.resolve_statement_quotes`, behind the projection's
  ``StatementEvidenceReader`` port). An erased or mismatched quote surfaces as *excluded* with its
  reason; the tool never fabricates the words it could not read, exactly as the card does not.
* ``inspect_readiness_history`` — the readiness ledger, override-annotated through the **shared**
  ``readiness_override_refs`` / ``effective_readiness_verdict`` helpers the card and the C4
  ``stage0_readiness`` view already share, so a third notion of "overridden" is never created.

Three properties both tools hold, and one thing they deliberately are not:

**Bounded.** A page is at most :data:`MAX_INSPECTION_PAGE` rows and carries the cursor for the
next. Prompt bloat must not migrate out of the opening context and into tool results, so the same
discipline that bounds the card bounds these: quotes are resolved for the *page*, and a ledger
row's ``metrics``/``reason_codes`` go through the card's own
:func:`~clue_projections.stage0.bounded_gate_evidence`.

**Cursors are the card's cursors.** They are encoded and decoded with
:func:`~clue_projections.stage0.encode_card_cursor` /
:func:`~clue_projections.stage0.decode_card_cursor`, so an ``omissions`` entry the card emitted is
handed to the tool verbatim. The card names no tool (the resource manifest owns the effective tool
surface); it names a typed *kind*, and the kind is what selects the view here.

**Workspace/project-scoped, fail-closed.** The B3/B4 guard family: a project in another workspace
refuses ``stage0_project_not_found`` — the same refusal a truly absent id gets, so a cross-tenant
id is indistinguishable from a non-existent one (no existence leak) — and the refusal is
WARNING-logged. Cross-*project* access is refused the same way rather than filtered to empty,
because a silent empty page reads as "no history" instead of "not yours".

**Not writers.** ``effect_class=READ`` / ``ReplayPolicy.EFFECT_FREE``: they append nothing to the
statement table and nothing to the readiness ledger. The only record of a call is the standard
runner journaling every tool gets.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar
from uuid import UUID

from pydantic import Field, JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.tool_outputs import (
    ReadinessHistoryOutput,
    StatementHistoryOutput,
)
from clue_core import ReadinessGate
from clue_db import ConnFactory, transaction
from clue_obs import get_logger
from clue_projections.stage0 import (
    ExcludedEvidence,
    ResolvedQuote,
    StatementEvidenceReader,
    bounded_gate_evidence,
    decode_card_cursor,
    effective_readiness_verdict,
    encode_card_cursor,
    readiness_override_refs,
)
from clue_research.stage0 import (
    ReadinessDecisionRow,
    StatementRoute,
    VolunteeredStatementRow,
    read_readiness_decisions,
    read_statements,
)
from clue_spine import get_project
from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
    PreconditionFailure,
    ReplayPolicy,
    ReplaySafety,
    Tool,
    ToolContext,
    ToolEffectClass,
    ToolInput,
    ToolOutput,
    ToolResult,
)

log = get_logger("clue_api.stage0_inspection_tools")

#: The hard page bound (spec §7: "page size ≤ 20"). Not an input: a caller cannot ask for more, so
#: the bound is a property of the contract rather than of the caller's restraint.
MAX_INSPECTION_PAGE = 20

#: How many statements one ``excluded_statement_evidence`` page may *examine* before returning what
#: it found so far with a resume cursor. The response stays ≤ :data:`MAX_INSPECTION_PAGE` either
#: way; this additionally bounds the evidence reads behind a page whose matches are sparse.
MAX_EXCLUSION_SCAN = 200

#: Cursor kinds ``inspect_statement_history`` accepts — both are kinds the card itself emits
#: (``statements_over_cap`` carries the first, ``excluded_statement_evidence_missing`` the second).
STATEMENT_CURSOR_KINDS = ("statements", "excluded_statement_evidence")

#: The cursor kind ``inspect_readiness_history`` accepts (the card's ``readiness_history``
#: omission).
READINESS_CURSOR_KIND = "readiness_history"


class Stage0InspectionInput(ToolInput):
    """Shared scope + position. ``project_id`` is engine-injected trusted authority, not model
    input; ``cursor`` is opaque and only ever came from a card omission or a previous page."""

    project_id: str = Field(min_length=1)
    cursor: str | None = Field(default=None, min_length=1)


class InspectStatementHistoryInput(Stage0InspectionInput):
    """``statement_id`` **or** ``route_key``, or neither for the whole history.

    Supplying both is refused rather than silently intersected: two selectors that disagree is a
    caller bug, and an intersection would quietly return a narrower answer than either asked for.
    """

    statement_id: UUID | None = None
    route_key: str | None = Field(default=None, min_length=1)


class InspectReadinessHistoryInput(Stage0InspectionInput):
    gate: ReadinessGate | None = None


def _fail(reason_code: str, message: str) -> tuple[PreconditionFailure, ...]:
    return (PreconditionFailure(reason_code=reason_code, message=message),)


class _Stage0InspectionTool(Tool):
    """Shared fail-closed workspace/project scoping and cursor decoding."""

    version = "1"
    output_model: ClassVar[type[ToolOutput]]
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.EFFECT_FREE,
        durable_identity="exact workspace/project read of durable Stage-0 history",
        operation_id_required=False,
        external_boundary=ExternalReplayBoundary.NONE,
        notes="read-only: the tool appends to neither the statement table nor the readiness ledger",
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.READ
    pin_requirements: ClassVar[tuple[str, ...]] = ()

    #: Cursor kinds this tool can resolve. A cursor from the *other* tool is a typed refusal, never
    #: a silently-ignored position (which would serve page one and look like the end of history).
    cursor_kinds: ClassVar[tuple[str, ...]] = ()

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def _project_failure(
        self, project_id: str, ctx: ToolContext
    ) -> tuple[PreconditionFailure, ...]:
        """B3/B4 guard: a foreign or absent project gets the identical refusal (no leak)."""

        async with ctx.conn_factory() as conn:
            project = await get_project(conn, project_id)
        if project is None or project.workspace_id != ctx.workspace_id:
            log.warning(
                "stage0_inspection.project_scope_refused",
                tool=self.name,
                actor=ctx.actor,
                workspace_id=ctx.workspace_id,
                project_id=project_id,
            )
            return _fail(
                "stage0_project_not_found",
                "no such Stage-0 project in this workspace",
            )
        return ()

    def _cursor_failure(self, cursor: str | None) -> tuple[PreconditionFailure, ...]:
        if cursor is None:
            return ()
        try:
            payload = decode_card_cursor(cursor)
        except (ValueError, TypeError, UnicodeDecodeError):
            return _fail("cursor_invalid", "the supplied cursor is not a readable card cursor")
        if payload.get("kind") not in self.cursor_kinds:
            return _fail(
                "cursor_kind_unsupported",
                f"this tool resolves cursor kinds {list(self.cursor_kinds)}",
            )
        return ()

    @staticmethod
    def _cursor_payload(cursor: str | None) -> dict[str, JsonValue]:
        return decode_card_cursor(cursor) if cursor is not None else {}

    @staticmethod
    def _position(payload: dict[str, JsonValue], key: str) -> str | None:
        value = payload.get(key)
        return str(value) if isinstance(value, str) else None


def _resume_index(ordered_ids: Sequence[str], after: str | None) -> int:
    """Where a keyset cursor resumes: strictly after ``after``, or 0 when it is unset.

    A position that no longer exists — the row it named was corrected away, or the cursor came from
    a card compiled against a different route filter — resumes past the end rather than silently at
    the beginning. An empty page is the honest answer to "nothing after here"; replaying page one
    under a stale cursor would look like new history.
    """

    if after is None:
        return 0
    try:
        return ordered_ids.index(after) + 1
    except ValueError:
        return len(ordered_ids)


class InspectStatementHistoryTool(_Stage0InspectionTool):
    """Interview statements with lineage + words. Read-only, bounded, workspace/project fail-closed.

    Reason codes: ``stage0_project_not_found``, ``statement_selector_ambiguous``,
    ``cursor_invalid``, ``cursor_kind_unsupported``, ``statement_evidence_not_configured``.
    """

    name = "inspect_statement_history"
    input_model: ClassVar[type[ToolInput]] = InspectStatementHistoryInput
    output_model: ClassVar[type[ToolOutput]] = StatementHistoryOutput
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("project_id", "statement_id", "route_key", "cursor")
    )
    cursor_kinds: ClassVar[tuple[str, ...]] = STATEMENT_CURSOR_KINDS

    def __init__(
        self,
        evidence: StatementEvidenceReader | None,
        *,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        super().__init__(conn_factory=conn_factory)
        self._evidence = evidence

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, InspectStatementHistoryInput)
        if inputs.statement_id is not None and inputs.route_key is not None:
            return _fail(
                "statement_selector_ambiguous",
                "supply statement_id or route_key, not both",
            )
        if failure := self._cursor_failure(inputs.cursor):
            return failure
        if self._evidence is None:
            # Fail-closed rather than returning rows with every quote blank: "no evidence reader"
            # and "the words were erased" must never look the same to a reader.
            return _fail(
                "statement_evidence_not_configured",
                "no statement evidence reader is configured in this process",
            )
        return await self._project_failure(inputs.project_id, ctx)

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, InspectStatementHistoryInput)
        assert self._evidence is not None  # narrowed by preconditions
        payload = self._cursor_payload(inputs.cursor)
        view = str(payload.get("kind", STATEMENT_CURSOR_KINDS[0]))
        after = self._position(payload, "before_statement_id")

        async with self._conn_factory() as conn:
            rows = await _statement_history(
                conn, workspace_id=ctx.workspace_id, project_id=inputs.project_id
            )
        superseded_by = {
            str(row.correction_of_id): str(row.id)
            for row in rows
            if row.correction_of_id is not None
        }
        candidates = _selected_statements(
            rows, statement_id=inputs.statement_id, route_key=inputs.route_key
        )
        start = _resume_index([str(row.id) for row in candidates], after)

        if view == "excluded_statement_evidence":
            page, resolutions, scanned_to = await self._excluded_page(
                candidates, start=start, workspace_id=ctx.workspace_id
            )
        else:
            page = list(candidates[start : start + MAX_INSPECTION_PAGE])
            resolutions = list(
                await self._evidence.resolve_quotes(workspace_id=ctx.workspace_id, statements=page)
            )
            scanned_to = start + len(page)

        has_more = scanned_to < len(candidates)
        next_cursor = (
            encode_card_cursor(
                {"kind": view, "before_statement_id": str(candidates[scanned_to - 1].id)}
            )
            if has_more and scanned_to
            else None
        )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references=StatementHistoryOutput(
                project_id=inputs.project_id,
                view=view,
                page_size=MAX_INSPECTION_PAGE,
                returned=len(page),
                total_matching=len(candidates),
                has_more=has_more,
                next_cursor=next_cursor,
                statements=[
                    _statement_payload(row, resolution, superseded_by=superseded_by)
                    for row, resolution in zip(page, resolutions, strict=True)
                ],
            ).model_dump(mode="json"),
        )

    async def _excluded_page(
        self,
        candidates: Sequence[VolunteeredStatementRow],
        *,
        start: int,
        workspace_id: str,
    ) -> tuple[
        list[VolunteeredStatementRow],
        list[ResolvedQuote | ExcludedEvidence],
        int,
    ]:
        """The ``excluded_statement_evidence_missing`` omission, resolved.

        Scanned in page-sized chunks so both the response *and* the evidence reads stay bounded
        when matches are sparse; the returned scan position is what the next cursor resumes from,
        so a sparse region costs several cheap calls rather than one unbounded one.
        """

        assert self._evidence is not None
        page: list[VolunteeredStatementRow] = []
        resolutions: list[ResolvedQuote | ExcludedEvidence] = []
        index = start
        scanned = 0
        while (
            index < len(candidates)
            and len(page) < MAX_INSPECTION_PAGE
            and scanned < MAX_EXCLUSION_SCAN
        ):
            chunk = list(candidates[index : index + MAX_INSPECTION_PAGE])
            resolved = await self._evidence.resolve_quotes(
                workspace_id=workspace_id, statements=chunk
            )
            for row, resolution in zip(chunk, resolved, strict=True):
                if isinstance(resolution, ExcludedEvidence) and len(page) < MAX_INSPECTION_PAGE:
                    page.append(row)
                    resolutions.append(resolution)
            index += len(chunk)
            scanned += len(chunk)
        return page, resolutions, index


class InspectReadinessHistoryTool(_Stage0InspectionTool):
    """The readiness ledger, paginated and override-annotated. Read-only, workspace fail-closed.

    Reason codes: ``stage0_project_not_found``, ``cursor_invalid``, ``cursor_kind_unsupported``.
    """

    name = "inspect_readiness_history"
    input_model: ClassVar[type[ToolInput]] = InspectReadinessHistoryInput
    output_model: ClassVar[type[ToolOutput]] = ReadinessHistoryOutput
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("project_id", "gate", "cursor")
    )
    cursor_kinds: ClassVar[tuple[str, ...]] = (READINESS_CURSOR_KIND,)

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, InspectReadinessHistoryInput)
        if failure := self._cursor_failure(inputs.cursor):
            return failure
        return await self._project_failure(inputs.project_id, ctx)

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, InspectReadinessHistoryInput)
        payload = self._cursor_payload(inputs.cursor)
        after = self._position(payload, "before_decision_id")

        async with self._conn_factory() as conn:
            ledger = await read_readiness_decisions(
                conn, workspace_id=ctx.workspace_id, project_id=inputs.project_id
            )
            # Newest-first, matching how the card names "latest": the reader that opened the tool
            # from a card omission is looking for what came *before* what the card showed.
            candidates = [
                row for row in reversed(ledger) if inputs.gate is None or row.gate is inputs.gate
            ]
            start = _resume_index([str(row.id) for row in candidates], after)
            page = candidates[start : start + MAX_INSPECTION_PAGE]
            overrides = await readiness_override_refs(
                conn,
                workspace_id=ctx.workspace_id,
                decision_ids=[row.id for row in page],
            )

        end = start + len(page)
        has_more = end < len(candidates)
        next_cursor = (
            encode_card_cursor(
                {
                    "kind": READINESS_CURSOR_KIND,
                    "before_decision_id": str(page[-1].id),
                }
            )
            if has_more and page
            else None
        )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references=ReadinessHistoryOutput(
                project_id=inputs.project_id,
                gate=inputs.gate.value if inputs.gate is not None else None,
                page_size=MAX_INSPECTION_PAGE,
                returned=len(page),
                total_matching=len(candidates),
                ledger_length=len(ledger),
                has_more=has_more,
                next_cursor=next_cursor,
                decisions=[_decision_payload(row, overrides) for row in page],
            ).model_dump(mode="json"),
        )


async def _statement_history(
    conn: AsyncConnection, *, workspace_id: str, project_id: str
) -> tuple[VolunteeredStatementRow, ...]:
    """Every route kind's statements, superseded rows included, newest first.

    History means *all* of it: the card shows current-effective ``project_state`` rows, but a
    reader asking why something changed needs the correction that superseded it, and a reader
    chasing an ``unmapped`` escape needs that route kind too. Composed from ``read_statements``
    once per route kind rather than a second copy of its SQL, so the supersession rule stays
    defined in exactly one place.
    """

    rows: list[VolunteeredStatementRow] = []
    for route_kind in StatementRoute:
        rows.extend(
            await read_statements(
                conn,
                workspace_id=workspace_id,
                project_id=project_id,
                route_kind=route_kind,
                include_superseded=True,
            )
        )
    # `read_statements` orders (created_at, id) ascending; newest-first is the card's order, so a
    # card cursor and a tool page speak the same sequence.
    rows.sort(key=lambda row: (row.created_at, str(row.id)), reverse=True)
    return tuple(rows)


def _selected_statements(
    rows: Sequence[VolunteeredStatementRow],
    *,
    statement_id: UUID | None,
    route_key: str | None,
) -> tuple[VolunteeredStatementRow, ...]:
    """Apply the selector. ``statement_id`` selects that statement's whole correction lineage.

    A single row answers "what does this say" but never "what did it replace, and what replaced
    it" — which is the question a supersession id in the card raises. The chain is walked in both
    directions over ``correction_of_id`` and returned in the shared newest-first order.
    """

    if statement_id is not None:
        return _lineage(rows, statement_id=statement_id)
    if route_key is not None:
        return tuple(row for row in rows if row.route_key == route_key)
    return tuple(rows)


def _lineage(
    rows: Sequence[VolunteeredStatementRow], *, statement_id: UUID
) -> tuple[VolunteeredStatementRow, ...]:
    by_id = {str(row.id): row for row in rows}
    corrects: dict[str, str] = {}
    for row in rows:
        if row.correction_of_id is not None:
            corrects[str(row.correction_of_id)] = str(row.id)
    chain: set[str] = set()
    root = str(statement_id)
    if root not in by_id:
        return ()
    # Backwards along `correction_of_id`, then forwards along its inverse. `chain` membership is
    # the cycle guard: the table is append-only, but a malformed lineage must not hang a read.
    cursor: str | None = root
    while cursor is not None and cursor not in chain:
        chain.add(cursor)
        parent = by_id[cursor].correction_of_id if cursor in by_id else None
        cursor = str(parent) if parent is not None else None
    cursor = corrects.get(root)
    while cursor is not None and cursor not in chain:
        chain.add(cursor)
        cursor = corrects.get(cursor)
    return tuple(row for row in rows if str(row.id) in chain)


def _statement_payload(
    row: VolunteeredStatementRow,
    resolution: ResolvedQuote | ExcludedEvidence,
    *,
    superseded_by: dict[str, str],
) -> dict[str, object]:
    """One history row. The words are present, or their absence is named — never both silent."""

    excluded = isinstance(resolution, ExcludedEvidence)
    return {
        "statement_id": str(row.id),
        "onboarding_input_id": str(row.onboarding_input_id),
        "route_kind": row.route_kind.value,
        "route_key": row.route_key,
        "route_ref": row.route_ref,
        "supersedes": (str(row.correction_of_id) if row.correction_of_id is not None else None),
        "superseded_by": superseded_by.get(str(row.id)),
        "superseded": str(row.id) in superseded_by,
        "quote_start": row.quote_start,
        "quote_end": row.quote_end,
        "quoted_text": None if excluded else resolution.quote,  # type: ignore[union-attr]
        "quote_excluded_reason": (
            resolution.reason.value  # type: ignore[union-attr]
            if excluded
            else None
        ),
        "created_at": row.created_at.isoformat(),
    }


def _decision_payload(row: ReadinessDecisionRow, overrides: dict[str, str]) -> dict[str, object]:
    """One ledger row, override-annotated and evidence-bounded exactly as the card bounds a gate."""

    override_ref = overrides.get(str(row.id))
    metrics, reason_codes, evidence_truncated = bounded_gate_evidence(row.metrics, row.reason_codes)
    return {
        "decision_id": str(row.id),
        "gate": row.gate.value,
        "verdict": row.verdict.value,
        "effective_verdict": effective_readiness_verdict(
            row.verdict.value, override_ref=override_ref
        ),
        "override_ref": override_ref,
        "created_by_actor": row.created_by_actor,
        "decision_lineage": {
            "client_kb_version": row.client_kb_version,
            "product_id": row.product_id,
            "icp_key": row.icp_key,
            "icp_version": row.icp_version,
            "spec_version": row.spec_version,
        },
        "metrics": metrics,
        "reason_codes": list(reason_codes),
        "evidence_truncated": evidence_truncated,
        "agent_sufficiency_status": row.agent_sufficiency_status,
        "created_at": row.created_at.isoformat(),
    }


def build_stage0_inspection_tools(
    *,
    evidence: StatementEvidenceReader | None,
    conn_factory: ConnFactory = transaction,
) -> tuple[Tool, ...]:
    """The two PC-C8 §7 inspection contracts.

    ``evidence`` is the injected ``StatementEvidenceReader`` (the api root builds the artifact-
    backed one); without it the statement tool refuses ``statement_evidence_not_configured``
    instead of serving quote-less rows.
    """

    return (
        InspectStatementHistoryTool(evidence, conn_factory=conn_factory),
        InspectReadinessHistoryTool(conn_factory=conn_factory),
    )


__all__ = [
    "MAX_EXCLUSION_SCAN",
    "MAX_INSPECTION_PAGE",
    "READINESS_CURSOR_KIND",
    "STATEMENT_CURSOR_KINDS",
    "InspectReadinessHistoryInput",
    "InspectReadinessHistoryTool",
    "InspectStatementHistoryInput",
    "InspectStatementHistoryTool",
    "build_stage0_inspection_tools",
]
