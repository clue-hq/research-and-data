"""Engine-side binding of the captured user turn (PC-C8 §6).

The model classifies a turn; it never authors the turn's identity or its bytes. A tool that needs
either declares the field and marks it :data:`TRUSTED_TURN_FIELD`; the field is then stripped from
the model-visible schema (``agent_runtime_wiring._with_trusted_runtime``) and served at the
execution seam from the trusted binding compiled here
(``agent_execution_wiring._trusted_tool_arguments``). This is the same two-part mechanism that
already serves ``project_id`` from the :class:`~clue_agents.contracts.AgentConstitution` — the
constitution carries *project* authority, which is stable for a whole execution, while a turn's
captured input is per-turn, so it gets its own binding rather than a fabricated constitution field.

What that removes: the byte-identical ``answer`` round-trip (the model retyping the user's message
and failing a sha check on a normalized character), and a forged or foreign ``onboarding_input_id``
— which can no longer *originate* from the model at all, because the model is never shown the
field.

The bytes are the artifact's own bytes, so the sha semantics that used to run in
``RecordInterviewAnswerTool.preconditions`` (``sha256(answer) == content_sha256``) move here and
stay fail-closed: a turn whose artifact bytes, artifact digest, and captured input do not agree
produces no binding, and a tool that needs one is refused with typed model-visible feedback rather
than executing against unverified bytes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.contracts import AgentTurnRequest
from clue_agents.ports import AgentArtifactReader
from clue_api.turn_action import derive_turn_action_ref
from clue_core import OnboardingInputKind
from clue_db import ConnFactory, transaction
from clue_obs import get_logger
from clue_research.stage0 import OnboardingInputRow, get_onboarding_input_for_artifact

log = get_logger(__name__)

__all__ = [
    "CAPTURE_DIGEST_MISMATCH",
    "CAPTURE_NOT_FOUND",
    "TRUSTED_TURN_FIELD",
    "CapturedTurn",
    "CapturedTurnBinder",
    "CapturedTurnSource",
    "CapturedTurnUnavailable",
    "RequestCapturedTurn",
    "load_human_capture",
    "trusted_turn_fields",
]

#: ``json_schema_extra`` marker naming one tool-input field as engine-injected turn authority.
#: Declared per *model*, never by bare field name: ``artifact_key`` is legitimately model-authored
#: on ``submit_onboarding_input`` (the model cites a key it was given) and engine-authored on
#: ``record_interview_answer`` (the key *is* this turn), so the declaration has to sit where the
#: field does.
TRUSTED_TURN_FIELD = "clue_trusted_turn_field"


#: The one reason that is *ordinary*: this surface's turn is simply not a captured onboarding
#: input. Every other reason is a disagreement between things that should agree, and is logged.
CAPTURE_NOT_FOUND = "capture_not_found"

#: The capture record and the turn's own artifact disagree about the bytes — an integrity alarm.
CAPTURE_DIGEST_MISMATCH = "capture_digest_mismatch"


class CapturedTurnUnavailable(ValueError):
    """No trustworthy binding exists for this turn, so nothing may be injected from it.

    ``reason_code`` separates "there is nothing to bind here" (normal on any surface that does not
    capture onboarding inputs) from an integrity disagreement, so a caller that fails soft can
    still be loud about the second kind.
    """

    def __init__(self, message: str, *, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


async def load_human_capture(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    artifact_key: str,
    digest: str,
    kind: OnboardingInputKind = OnboardingInputKind.USER_TURN,
    actor: str = "human",
) -> OnboardingInputRow:
    """The one human-capture integrity join, fail-closed, shared by every consumer of a turn.

    "This artifact really is a human capture of this project, and the two records agree about the
    bytes" is asserted in exactly one place: here. :class:`CapturedTurnBinder` calls it while
    compiling a turn's binding (after it has re-hashed the body), and
    :func:`clue_api.turn_action.resolve_turn_action` calls it while verifying an action receipt
    (where the digest comes from the turn's durable artifact ref, and there are no bytes to load).
    Two copies of this join would be two chances for one of them to relax.
    """

    captured = await get_onboarding_input_for_artifact(
        conn,
        workspace_id=workspace_id,
        project_id=project_id,
        artifact_key=artifact_key,
        actor=actor,
        kind=kind,
    )
    if captured is None:
        raise CapturedTurnUnavailable(
            "this turn's message is not a captured onboarding input of this project",
            reason_code=CAPTURE_NOT_FOUND,
        )
    if captured.content_sha256 != digest:
        raise CapturedTurnUnavailable(
            "the captured onboarding input records a different digest than the turn artifact",
            reason_code=CAPTURE_DIGEST_MISMATCH,
        )
    return captured


def trusted_turn_fields(model: type[BaseModel]) -> tuple[str, ...]:
    """Field names this input model declares as served from the captured turn."""

    return tuple(
        name
        for name, field in model.model_fields.items()
        if isinstance(field.json_schema_extra, dict)
        and field.json_schema_extra.get(TRUSTED_TURN_FIELD) is True
    )


class CapturedTurn(BaseModel):
    """The trusted identity and exact bytes of the user turn the model is answering.

    Three of these fields exist so a *tool* can name what it needs in its own vocabulary; none of
    them is a second source of truth:

    * ``turn_id`` — the turn's durable identity, so a tool (or a receipt) can cite the act itself
      rather than only its captured bytes.
    * ``user_instruction`` — byte-identical to ``answer``. A binding never invents a value, so a
      tool that declares ``user_instruction`` (the research-directive tools do — the field carries
      the user's own words into the drafted directive) can only be served if the *field name* it
      declares is servable. Renaming either field on the tools would rewrite frozen tool input
      schemas and their pinned profile digests; carrying the same bytes under both names does not.
    * ``source_turn_ref`` — the canonical :func:`~clue_api.turn_action.derive_turn_action_ref`
      value for this turn. It is derived here, at the same fail-closed seam that proved the turn,
      so a tool receiving it is receiving a ref the engine has already verified — not a string a
      caller or the model chose.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    onboarding_input_id: str
    artifact_key: str
    sha256: str
    byte_count: int
    answer: str
    turn_id: str
    user_instruction: str
    source_turn_ref: str

    def value_for(self, field: str) -> str | int:
        """Serve one declared field, or refuse: a binding never invents an authority value."""

        if field not in type(self).model_fields:
            raise CapturedTurnUnavailable(
                f"the captured turn carries no {field!r} to inject; a tool may only bind "
                f"{sorted(type(self).model_fields)}",
                reason_code="unbindable_field",
            )
        value = getattr(self, field)
        assert isinstance(value, str | int)
        return value


class CapturedTurnSource(Protocol):
    """One turn's binding, resolved lazily so a turn that needs none pays for none."""

    async def captured_turn(self) -> CapturedTurn: ...


class CapturedTurnBinder:
    """Compile the captured-turn binding from the turn's own artifact and its capture record.

    The join is definitional rather than passed in: the captured input *is* the human-captured
    onboarding input of this turn's project citing this turn's ``user_message_artifact_ref``.
    Nothing the model says participates — and, because ``submit_onboarding_input`` is itself a
    writable tool over a *content-addressed* key, nothing the model *writes* may participate
    either. Hence ``actor='human'`` and the project scope in the lookup: without them the model
    could insert a newer ``user_turn`` row citing this turn's artifact (whose key and digest it
    can see in the L7 envelope) and make itself the selected capture record, and two projects in
    one workspace whose users both answer "confirm" would cross-select each other's turns.

    **Lifetime the cache must survive.** One binder is built per *trial* and shared by every turn
    it runs (``stage0_trial``), so the cache exists only to spare the second read of a turn L7
    already described — it is not a memo of "this project's binding". Its key is therefore the
    **turn**, never the turn's content: an artifact key is content-addressed, so a user who answers
    "confirm" twice sends byte-identical bytes under the same key while the capture record — the
    thing actually being bound — is a new row each time. Keyed on content, turn 2 would silently
    inherit turn 1's ``onboarding_input_id``: preconditions still pass (same artifact, same
    digest), the statements land under the *previous* turn's input, and the routing-receipt guard
    counts zero for this turn and drives an unrepairable repair loop.
    """

    def __init__(
        self,
        *,
        artifacts: AgentArtifactReader,
        conn_factory: ConnFactory = transaction,
        kind: OnboardingInputKind = OnboardingInputKind.USER_TURN,
        actor: str = "human",
    ) -> None:
        self._artifacts = artifacts
        self._conn_factory = conn_factory
        self._kind = kind
        self._actor = actor
        self._cache: dict[tuple[str, str, str, str], CapturedTurn] = {}

    async def bind(self, request: AgentTurnRequest) -> CapturedTurn:
        """Resolve the binding or refuse; every consistency rule here is fail-closed."""

        ref = request.user_message_artifact_ref
        project_id = request.constitution.project_id
        # The turn is the cached thing's identity (see the class docstring); the artifact key stays
        # in the key so a request whose ref moved under a reused turn id misses rather than being
        # served the previous ref's bytes.
        cache_key = (ref.workspace_id, project_id, str(request.turn_id), ref.artifact_key)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        body = await self._artifacts.read(ref)
        digest = hashlib.sha256(body).hexdigest()
        if digest != ref.sha256:
            raise CapturedTurnUnavailable(
                "the captured turn body does not hash to its own artifact digest",
                reason_code="artifact_digest_mismatch",
            )
        async with self._conn_factory() as conn:
            captured = await load_human_capture(
                conn,
                workspace_id=ref.workspace_id,
                project_id=project_id,
                artifact_key=ref.artifact_key,
                digest=digest,
                kind=self._kind,
                actor=self._actor,
            )
        try:
            answer = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CapturedTurnUnavailable(
                "the captured turn body is not valid UTF-8, so quote offsets are meaningless",
                reason_code="capture_not_utf8",
            ) from exc
        binding = CapturedTurn(
            onboarding_input_id=str(captured.id),
            artifact_key=ref.artifact_key,
            sha256=digest,
            byte_count=len(body),
            answer=answer,
            turn_id=str(request.turn_id),
            # The same decoded bytes under the name a tool declares, and the canonical action ref
            # for this turn — both derived here, from the request the binder just proved, so no
            # caller and no model ever authors either.
            user_instruction=answer,
            source_turn_ref=derive_turn_action_ref(request.turn_id),
        )
        self._cache[cache_key] = binding
        return binding

    async def describe(self, request: AgentTurnRequest) -> CapturedTurn | None:
        """Resolve for context assembly, where an unbound turn is normal, not a failure.

        Most surfaces (an account-research turn, say) capture no onboarding input, and a turn that
        has none must still assemble. Refusal belongs at the tool seam, where a tool actually needs
        the binding; here the honest answer is simply no envelope.

        Failing *soft* is not the same as failing *silently*. Only ``capture_not_found`` is
        ordinary; a digest disagreement or an undecodable body means two records that must agree
        do not, so it is logged as an integrity warning rather than disappearing into a missing
        envelope.
        """

        try:
            return await self.bind(request)
        except CapturedTurnUnavailable as exc:
            if exc.reason_code != CAPTURE_NOT_FOUND:
                log.warning(
                    "stage0.captured_turn.unavailable",
                    reason_code=exc.reason_code,
                    workspace_id=request.constitution.workspace_id,
                    project_id=request.constitution.project_id,
                    artifact_key=request.user_message_artifact_ref.artifact_key,
                    detail=str(exc),
                )
            return None


@dataclass(frozen=True, slots=True)
class RequestCapturedTurn:
    """Bind one binder to one request so the execution seam needs no turn-shaped arguments."""

    binder: CapturedTurnBinder
    request: AgentTurnRequest

    async def captured_turn(self) -> CapturedTurn:
        return await self.binder.bind(self.request)
