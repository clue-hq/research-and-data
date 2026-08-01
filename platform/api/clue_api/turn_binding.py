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

from clue_agents.contracts import AgentTurnRequest
from clue_agents.ports import AgentArtifactReader
from clue_core import OnboardingInputKind
from clue_db import ConnFactory, transaction
from clue_research.stage0 import get_onboarding_input_for_artifact

__all__ = [
    "TRUSTED_TURN_FIELD",
    "CapturedTurn",
    "CapturedTurnBinder",
    "CapturedTurnSource",
    "CapturedTurnUnavailable",
    "RequestCapturedTurn",
    "trusted_turn_fields",
]

#: ``json_schema_extra`` marker naming one tool-input field as engine-injected turn authority.
#: Declared per *model*, never by bare field name: ``artifact_key`` is legitimately model-authored
#: on ``submit_onboarding_input`` (the model cites a key it was given) and engine-authored on
#: ``record_interview_answer`` (the key *is* this turn), so the declaration has to sit where the
#: field does.
TRUSTED_TURN_FIELD = "clue_trusted_turn_field"


class CapturedTurnUnavailable(ValueError):
    """No trustworthy binding exists for this turn, so nothing may be injected from it."""


def trusted_turn_fields(model: type[BaseModel]) -> tuple[str, ...]:
    """Field names this input model declares as served from the captured turn."""

    return tuple(
        name
        for name, field in model.model_fields.items()
        if isinstance(field.json_schema_extra, dict)
        and field.json_schema_extra.get(TRUSTED_TURN_FIELD) is True
    )


class CapturedTurn(BaseModel):
    """The trusted identity and exact bytes of the user turn the model is answering."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    onboarding_input_id: str
    artifact_key: str
    sha256: str
    byte_count: int
    answer: str

    def value_for(self, field: str) -> str | int:
        """Serve one declared field, or refuse: a binding never invents an authority value."""

        if field not in type(self).model_fields:
            raise CapturedTurnUnavailable(
                f"the captured turn carries no {field!r} to inject; a tool may only bind "
                f"{sorted(type(self).model_fields)}"
            )
        value = getattr(self, field)
        assert isinstance(value, str | int)
        return value


class CapturedTurnSource(Protocol):
    """One turn's binding, resolved lazily so a turn that needs none pays for none."""

    async def captured_turn(self) -> CapturedTurn: ...


class CapturedTurnBinder:
    """Compile the captured-turn binding from the turn's own artifact and its capture record.

    The join is definitional rather than passed in: the captured input *is* the onboarding input
    citing this turn's ``user_message_artifact_ref``. Nothing the model says participates.
    """

    def __init__(
        self,
        *,
        artifacts: AgentArtifactReader,
        conn_factory: ConnFactory = transaction,
        kind: OnboardingInputKind = OnboardingInputKind.USER_TURN,
    ) -> None:
        self._artifacts = artifacts
        self._conn_factory = conn_factory
        self._kind = kind
        self._cache: dict[tuple[str, str], CapturedTurn] = {}

    async def bind(self, request: AgentTurnRequest) -> CapturedTurn:
        """Resolve the binding or refuse; every consistency rule here is fail-closed."""

        ref = request.user_message_artifact_ref
        cache_key = (ref.workspace_id, ref.artifact_key)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        body = await self._artifacts.read(ref)
        digest = hashlib.sha256(body).hexdigest()
        if digest != ref.sha256:
            raise CapturedTurnUnavailable(
                "the captured turn body does not hash to its own artifact digest"
            )
        async with self._conn_factory() as conn:
            captured = await get_onboarding_input_for_artifact(
                conn,
                workspace_id=ref.workspace_id,
                artifact_key=ref.artifact_key,
                kind=self._kind,
            )
        if captured is None:
            raise CapturedTurnUnavailable(
                "this turn's message is not a captured onboarding input in this workspace"
            )
        if captured.content_sha256 != digest:
            raise CapturedTurnUnavailable(
                "the captured onboarding input records a different digest than the turn artifact"
            )
        try:
            answer = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CapturedTurnUnavailable(
                "the captured turn body is not valid UTF-8, so quote offsets are meaningless"
            ) from exc
        binding = CapturedTurn(
            onboarding_input_id=str(captured.id),
            artifact_key=ref.artifact_key,
            sha256=digest,
            byte_count=len(body),
            answer=answer,
        )
        self._cache[cache_key] = binding
        return binding

    async def describe(self, request: AgentTurnRequest) -> CapturedTurn | None:
        """Resolve for context assembly, where an unbound turn is normal, not a failure.

        Most surfaces (an account-research turn, say) capture no onboarding input, and a turn that
        has none must still assemble. Refusal belongs at the tool seam, where a tool actually needs
        the binding; here the honest answer is simply no envelope.
        """

        try:
            return await self.bind(request)
        except CapturedTurnUnavailable:
            return None


@dataclass(frozen=True, slots=True)
class RequestCapturedTurn:
    """Bind one binder to one request so the execution seam needs no turn-shaped arguments."""

    binder: CapturedTurnBinder
    request: AgentTurnRequest

    async def captured_turn(self) -> CapturedTurn:
        return await self.binder.bind(self.request)
