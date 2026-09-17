"""``request_persona_synthesis@1`` — the Head of ABM asks for this project's personas.

A project's ICP is confirmed and pinned by a human at the gate. The buying committee that profile
sells to is a *separate* document, written by the audience-persona turn, and after a newly authored
ICP nothing has written it yet. This tool is how the agent asks for it: it opens a **personas-only
onboarding run** — one governed persona turn for the exact document version the project pinned,
driven on the fleet — and returns its run id.

What it does not do is as important. It writes no persona itself, it never confirms or repoints
anything, and it cannot ask for a profile the project did not pin: the ICP is resolved from
``project_icp_pin``, and the model's ``icp_key`` is only *checked against* it. The document lands
in the ICP's own scope on a later turn (a project-local variant's personas are that project's), so
this call's successful result means "the work is queued", never "the personas exist".

The turn binding is why this module sits at the ``clue_api`` root rather than inside
``clue_api.arv2``: the lane may not import ``clue_api.turn_action`` / ``turn_binding`` (Global
Constraint 7), and the platform — not the model — must say which turn, which project, which brand
and which human this request belongs to.

Rows first, offer second (the O3 rule): the run row is committed before the fleet is told, because
a task that reaches a worker must always find its run. The reverse failure — a row nobody will
drive — is contained here the way ``POST /onboarding`` contains it: a failed offer fails the run
and the caller is told to try again, rather than being handed a run id that is already dead.

**Retired from the profile (2026-09-14, plan 3).** ``head-of-abm@v55`` no longer grants this tool,
and ``recipe0-stage0-v27.json`` no longer admits its address: personas are now *written* by the Head
of ABM with the ordinary ``write_file`` at ``project/audience/persona-<key>.md``, through the
``persona-authoring`` skill and the versioned project root (:mod:`clue_api.project_root_writer`
over :func:`clue_api.arv2.project_documents.write_project_document`, which since 2026-09-14 takes
any path under ``project/``).
Asking a fleet run to synthesize a document the agent can simply write was the indirection this
retires. Nothing here is deleted: the tool stays registered so a receipt pinned to recipe ≤ 26 can
still be replayed against its own immutable revision. Outside replay it is uncomposed — no current
profile grants it, so no new turn can call it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, ClassVar, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, StringConstraints
from sqlalchemy import text

from clue_api.arv2.icp_authoring import ICP_KEY_MAX_LENGTH, ICP_KEY_PATTERN
from clue_api.arv2.icp_confirmation import current_project_icp_pin
from clue_api.arv2.onboarding_driver import IcpRef
from clue_api.arv2.onboarding_store import (
    create_persona_run,
    fail_run,
    open_persona_run,
    read_run_status,
)
from clue_api.onboarding_routes import DbOnboardingEnqueuer
from clue_api.turn_action import (
    TurnActionUnresolvable,
    load_turn_identity,
    parse_turn_action_ref,
)
from clue_api.turn_binding import TRUSTED_TURN_FIELD
from clue_db import ConnFactory, transaction
from clue_fleet import WorkQueue
from clue_obs import get_logger
from clue_spine import get_brand, get_project
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

log = get_logger("clue_api.persona_request_tools")

__all__ = [
    "DbPersonaRequestService",
    "PersonaRequestService",
    "PersonaSynthesisReceipt",
    "PersonaSynthesisRefused",
    "PersonaSynthesisRequest",
    "RequestPersonaSynthesisInput",
    "RequestPersonaSynthesisOutput",
    "RequestPersonaSynthesisTool",
    "build_persona_request_tools",
]

#: The brand's own domain, as the completed onboarding walk recorded it. The personas turn names
#: the company in its card, and this is the only place that fact honestly exists — a brand with no
#: finished walk has no domain to name, which is what ``brand_not_onboarded`` says.
_ONBOARDED_DOMAIN = text(
    """
    SELECT company_domain FROM onboarding_run
    WHERE workspace_id = :workspace_id AND brand_id = :brand_id AND kind = 'full'
      AND status IN ('completed', 'completed_with_gaps')
    ORDER BY requested_at DESC LIMIT 1
    """
)


@dataclass(frozen=True)
class PersonaSynthesisRequest:
    """One ask: write the personas of this project's pinned ICP.

    Every field but ``icp_key`` is platform-derived — the workspace is ambient, and the project,
    brand, turn and human come from the presenting turn's own rows.
    """

    workspace_id: str
    project_id: str
    brand_id: str
    turn_id: UUID
    user_id: str
    icp_key: str


@dataclass(frozen=True)
class PersonaSynthesisReceipt:
    """The run that will write them. ``replayed`` means this turn had already opened it."""

    run_id: UUID
    icp_key: str
    replayed: bool


class PersonaSynthesisRefused(Exception):
    """A prerequisite is unmet. ``code`` is stable and machine-readable.

    Codes: ``icp_not_pinned_for_project`` (the named key is not this project's current pin — or it
    has none), ``persona_run_already_open`` (that document's personas are already being written),
    ``brand_not_onboarded`` (no completed whole-brand walk to take the company domain from), and
    ``enqueue_failed`` (the run was recorded but could not be offered, so it was failed).
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class PersonaRequestService(Protocol):
    async def request(self, request: PersonaSynthesisRequest) -> PersonaSynthesisReceipt: ...


def persona_run_id(*, workspace_id: str, document_id: UUID, turn_id: UUID) -> UUID:
    """The run's identity: this workspace, this ICP document version, this turn.

    The turn is part of it deliberately. A replayed tool call inside one turn re-derives the same
    id and finds its own run (``replayed=True``) rather than opening a second; a *different* turn
    asking while that run is still open is a different act, and is refused by name instead of
    quietly racing the first at the same document path.
    """

    return uuid5(NAMESPACE_URL, f"arv2-persona-run:{workspace_id}:{document_id}:{turn_id}")


class DbPersonaRequestService:
    """The production service: one transaction, then the real fleet queue."""

    def __init__(
        self,
        *,
        queue: WorkQueue | None = None,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        # The offer goes through the onboarding lane's own enqueuer: one place knows what an
        # ``onboarding_run`` task looks like, and a personas run is one of those tasks.
        self._enqueuer = DbOnboardingEnqueuer(queue)
        self._conn_factory = conn_factory

    async def request(self, request: PersonaSynthesisRequest) -> PersonaSynthesisReceipt:
        async with self._conn_factory() as conn:
            pin = await current_project_icp_pin(
                conn, workspace_id=request.workspace_id, project_id=request.project_id
            )
            if pin is None or pin.icp_key != request.icp_key:
                # One refusal for both, because they are one fact from the agent's side: the
                # profile it named is not the one this project works against. Naming the pin (or
                # its absence) tells it what to do next without it having to guess.
                raise PersonaSynthesisRefused(
                    "icp_not_pinned_for_project",
                    f"project {request.project_id!r} has not pinned an ICP called "
                    f"{request.icp_key!r}"
                    + ("" if pin is None else f"; its pinned ICP is {pin.icp_key!r}"),
                )
            run_id = persona_run_id(
                workspace_id=request.workspace_id,
                document_id=pin.document_id,
                turn_id=request.turn_id,
            )
            open_run = await open_persona_run(conn, persona_icp_document_id=pin.document_id)
            if open_run is not None:
                if open_run != run_id:
                    raise PersonaSynthesisRefused(
                        "persona_run_already_open",
                        f"personas for {pin.icp_key!r} are already being written by run "
                        f"{open_run}; wait for it rather than writing that document twice",
                    )
                # This turn's own run, still open — so its offer succeeded (a failed offer fails
                # the run below, which is no longer open). Nothing left to do but say so.
                return PersonaSynthesisReceipt(run_id=run_id, icp_key=pin.icp_key, replayed=True)
            # No *open* run — which is two different facts, and telling them apart is the whole
            # point of this read. A run at this turn's own derived id that has already **settled**
            # must not fall through to the offer path below: ``create_persona_run`` is a no-op on
            # its own id, and ``enqueue_personas`` on a terminal work row is refused
            # (``reopen_terminal=False``), so the agent would be told the job "could not be queued;
            # ask again" — the opposite of the truth, forever, because the run can never leave a
            # terminal state.
            settled = await read_run_status(conn, run_id=run_id)
            if settled in ("completed", "completed_with_gaps"):
                # This turn did open that run and the work is done. ``replayed`` is the honest
                # word: the request is this turn's, and it has already been served.
                return PersonaSynthesisReceipt(run_id=run_id, icp_key=pin.icp_key, replayed=True)
            if settled == "failed":
                raise PersonaSynthesisRefused(
                    "persona_run_settled",
                    "that request already failed; ask again on a new turn",
                )
            company_domain = (
                await conn.execute(
                    _ONBOARDED_DOMAIN,
                    {"workspace_id": request.workspace_id, "brand_id": request.brand_id},
                )
            ).scalar_one_or_none()
            if company_domain is None:
                raise PersonaSynthesisRefused(
                    "brand_not_onboarded",
                    f"brand {request.brand_id!r} has no completed onboarding run, so there is no "
                    "company for a persona turn to write about",
                )
            brand = await get_brand(
                conn, workspace_id=request.workspace_id, brand_id=request.brand_id
            )
            company_name = brand.name if brand is not None and brand.name else str(company_domain)
            await create_persona_run(
                conn,
                run_id=run_id,
                workspace_id=request.workspace_id,
                brand_id=request.brand_id,
                project_id=request.project_id,
                persona_icp_document_id=pin.document_id,
                company_domain=str(company_domain),
                requested_by_user_id=request.user_id,
            )
        # Outside the block, so the row is committed: a task that reaches a worker always finds
        # its run.
        offer_error: Exception | None = None
        try:
            offered = await self._enqueuer.enqueue_personas(
                run_id=run_id,
                workspace_id=request.workspace_id,
                brand_id=request.brand_id,
                project_id=request.project_id,
                company_domain=str(company_domain),
                company_name=company_name,
                icp=IcpRef(
                    document_id=pin.document_id,
                    icp_key=pin.icp_key,
                    version=pin.version,
                    path=pin.path,
                    project_id=pin.project_id,
                ),
            )
        except Exception as error:
            # Broad on purpose, as the onboarding route's is: a transport error, a pool timeout
            # and a programming error in the queue are the same fact here — the run was not
            # offered — and all must be contained. Logged inside the handler because ``exception``
            # reads ``sys.exc_info()``, which is already empty below.
            log.exception(
                "persona_synthesis.enqueue_failed",
                run_id=str(run_id),
                workspace_id=request.workspace_id,
            )
            offered, offer_error = False, error
        if not offered:
            if offer_error is None:
                log.error(
                    "persona_synthesis.enqueue_refused",
                    run_id=str(run_id),
                    workspace_id=request.workspace_id,
                )
            # A row nothing will drive would hold this document's one open slot forever, so the
            # run is failed and the document is free for the next attempt.
            async with self._conn_factory() as conn:
                await fail_run(conn, run_id=run_id)
            raise PersonaSynthesisRefused(
                "enqueue_failed",
                "the persona synthesis job could not be queued; ask again",
            ) from offer_error
        return PersonaSynthesisReceipt(run_id=run_id, icp_key=pin.icp_key, replayed=False)


# =================================================================================================
# the toolbelt tool
# =================================================================================================


class RequestPersonaSynthesisInput(ToolInput):
    """Which profile's personas. Scope, authorship and the document itself are platform-derived."""

    icp_key: str = Field(min_length=1, max_length=ICP_KEY_MAX_LENGTH, pattern=ICP_KEY_PATTERN)
    source_turn_ref: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
    ] = Field(json_schema_extra={TRUSTED_TURN_FIELD: True})


class RequestPersonaSynthesisOutput(ToolOutput):
    run_id: str
    icp_key: str
    replayed: bool


class _RequestRefused(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RequestPersonaSynthesisTool(Tool):
    """Open one personas-only onboarding run for this project's pinned ICP."""

    name = "request_persona_synthesis"
    version = "1"
    model_description = (
        "Ask the platform to write (or rewrite) the persona document for this project's confirmed "
        "ICP. Runs the audience-persona synthesis turn in the background; the document lands under "
        "the same scope as the ICP on a later turn. Call only when the human wants personas for a "
        "newly confirmed profile, or asks for a redraft. Refused when the ICP named is not this "
        "project's pinned ICP, or when a persona run for it is already open."
    )
    input_model: ClassVar[type[ToolInput]] = RequestPersonaSynthesisInput
    output_model: ClassVar[type[ToolOutput]] = RequestPersonaSynthesisOutput
    effect_class = ToolEffectClass.SPEND
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="project + pinned ICP document; one open personas run per document",
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(safe_display_fields=("icp_key",))
    #: ``project`` is the spine row the execution is bound to — a replay identity, not a Stage-0
    #: pin (standing rule item 5).
    pin_requirements = ("project",)

    def __init__(
        self,
        service: PersonaRequestService | None,
        *,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._service = service
        self._conn_factory = conn_factory

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, RequestPersonaSynthesisInput)
        if self._service is None:
            return (
                PreconditionFailure(
                    reason_code="persona_synthesis_not_composed",
                    message="persona synthesis is not composed on this deployment",
                ),
            )
        try:
            await self._resolve(inputs, ctx)
        except _RequestRefused as exc:
            return (PreconditionFailure(reason_code=exc.code, message=str(exc)),)
        return ()

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        del inputs
        # The call itself buys nothing; the spend is one governed persona turn, settled against
        # that run's own step and the deployment's turn budget. So the estimate carries the
        # *shape* of the spend rather than a number nobody derived (the discovery launch's idiom).
        return ToolEstimate(
            cost_cents=Decimal(0), detail={"basis": "one_onboarding_persona_synthesis_turn"}
        )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, RequestPersonaSynthesisInput)
        assert self._service is not None
        request = await self._resolve(inputs, ctx)
        try:
            receipt = await self._service.request(request)
        except PersonaSynthesisRefused as refused:
            # A domain refusal is feedback the agent can act on — a typed precondition failure,
            # never a stack trace the model has to guess at.
            raise PreconditionFailed([PreconditionFailure(refused.code, str(refused))]) from refused
        output = RequestPersonaSynthesisOutput(
            run_id=str(receipt.run_id), icp_key=receipt.icp_key, replayed=receipt.replayed
        )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references=output.model_dump(),
            replayed=receipt.replayed,
        )

    async def _resolve(
        self, inputs: RequestPersonaSynthesisInput, ctx: ToolContext
    ) -> PersonaSynthesisRequest:
        """Everything the model may not author, read from the rows that own it."""

        try:
            turn_id = parse_turn_action_ref(inputs.source_turn_ref)
        except TurnActionUnresolvable as exc:
            raise _RequestRefused("persona_turn_ref_malformed", str(exc)) from exc
        async with self._conn_factory() as conn:
            turn = await load_turn_identity(conn, workspace_id=ctx.workspace_id, turn_id=turn_id)
            if turn is None:
                raise _RequestRefused(
                    "persona_turn_not_found",
                    "the presenting turn is not part of this workspace",
                )
            if turn.submitted_by_user_id is None:
                raise _RequestRefused(
                    "persona_addressee_missing",
                    "the presenting turn records no human to credit this request to",
                )
            project = await get_project(conn, turn.project_id)
            if project is None or project.workspace_id != ctx.workspace_id:
                # Fail-closed and indistinguishable from an unresolvable turn: a turn whose project
                # this workspace cannot see is not a turn this workspace may spend in.
                raise _RequestRefused(
                    "persona_turn_not_found",
                    "the presenting turn's project is not part of this workspace",
                )
        return PersonaSynthesisRequest(
            workspace_id=ctx.workspace_id,
            project_id=turn.project_id,
            brand_id=project.brand_id,
            turn_id=turn.turn_id,
            user_id=turn.submitted_by_user_id,
            icp_key=inputs.icp_key,
        )


def build_persona_request_tools(
    service: PersonaRequestService | None,
    *,
    conn_factory: ConnFactory = transaction,
) -> tuple[Tool, ...]:
    """The request surface. Registered on every deployment; composed where the fleet lane is.

    Registering it uncomposed is deliberate, for the reason its ARV2 neighbours give: the
    platform's write surface stays complete (the authority audit sees every tool), and an agent
    that reaches for personas on a deployment without the lane gets the named
    ``persona_synthesis_not_composed`` refusal rather than an ``UnknownTool`` it cannot explain.
    """

    return (RequestPersonaSynthesisTool(service, conn_factory=conn_factory),)
