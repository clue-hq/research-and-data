"""``exa_search_evidence@1`` — the onboarding synthesis agent's one governed provider call
(ARV2-ONBOARDING-PLAN.md §4.5).

The model authors only a query, an optional domain list and a result count. Everything that
shapes the request — the ``deep-reasoning`` type, the system prompt, the output schema — is fixed
here from O2's templates, so there is exactly one request shape to review. The tool writes no
domain state; its only durable trace is the raw body in the artifact store and the row on
``provider_call_ledger``. It refuses before any spend when the feature flag is off, when Exa is not
configured, or when no artifact store is composed, and it registers unconditionally so the C6
authority audit sees the same registry shape in every process.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, ClassVar, Protocol

from pydantic import Field, SecretStr

from clue_api.arv2.calls import ProviderCaller
from clue_api.arv2.exa_client import ExaClient, ExaDeepResult
from clue_api.arv2.onboarding_documents import sources_by_field
from clue_api.arv2.onboarding_requests import (
    PERSONA_EVIDENCE_SYSTEM_PROMPT,
    persona_evidence_output_schema,
)
from clue_api.arv2.provider_ledger import (
    ArtifactSink,
    BufferedLedger,
    BufferedRawSink,
    LedgerStamp,
    drain_provider_calls,
)
from clue_api.arv2.sinks import LedgerSink, RawSink
from clue_api.arv2.transport import HttpxTransport
from clue_config import Secrets, Settings
from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
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

__all__ = [
    "EXA_SEARCH_EVIDENCE_TOOL_NAME",
    "EvidencePassage",
    "ExaSearchEvidenceInput",
    "ExaSearchEvidenceOutput",
    "ExaSearchEvidenceTool",
    "build_onboarding_evidence_tools",
]

EXA_SEARCH_EVIDENCE_TOOL_NAME = "exa_search_evidence"
_ESTIMATE_CENTS = Decimal("2")


class ExaAgentSurface(Protocol):
    def deep_reasoning(
        self,
        *,
        system_prompt: str,
        query: str,
        output_schema: Any,
        num_results: int = 20,
        additional_queries: Sequence[str] | None = None,
        include_domains: Sequence[str] | None = None,
        text_max_chars: int = 10000,
        highlights_query: str | None = None,
        highlights_max_chars: int = 2000,
        label: str = "exa-deep",
        timeout_s: float = 1200.0,
    ) -> ExaDeepResult: ...


class ExaSearchEvidenceInput(ToolInput):
    query: str = Field(min_length=1, max_length=400)
    include_domains: list[str] = Field(default_factory=list, max_length=5)
    num_results: int = Field(default=6, ge=1, le=10)


class EvidencePassage(ToolOutput):
    quote: str
    speaker_role: str
    org_type: str | None
    topic: str | None
    url: str | None
    title: str | None


class ExaSearchEvidenceOutput(ToolOutput):
    passages: list[EvidencePassage]
    cost_usd: str
    request_id: str | None


def _fail(code: str, message: str) -> tuple[PreconditionFailure, ...]:
    return (PreconditionFailure(reason_code=code, message=message),)


class ExaSearchEvidenceTool(Tool):
    name = EXA_SEARCH_EVIDENCE_TOOL_NAME
    version = "1"
    model_description = (
        "Find first-person evidence of how people in a named role describe a problem: verbatim "
        "quotes with the speaker's role and a source URL. One deep-reasoning web search; returns "
        "an empty list rather than a weak match. Use at most once per persona role."
    )
    input_model: ClassVar[type[ToolInput]] = ExaSearchEvidenceInput
    output_model: ClassVar[type[ToolOutput]] = ExaSearchEvidenceOutput
    effect_class = ToolEffectClass.SPEND
    replay = ReplaySafety(
        policy=ReplayPolicy.AT_LEAST_ONCE,
        durable_identity=(
            "ARV2 ledger row on provider_call_ledger keyed on the call; the tool writes no "
            "domain state"
        ),
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.AT_LEAST_ONCE,
        notes=(
            "A retry may repeat one Exa deep-reasoning search and land a second ledger row for "
            "it — money spent twice is recorded twice; no domain row is written, so nothing "
            "converges."
        ),
    )
    parameter_policy = JournalParameterPolicy(safe_display_fields=("query", "num_results"))
    # Satisfied by the `onboarding-synthesis-unit@1` recipe's static pin on the
    # `audience-persona` skill: the model may spend only inside a slot that pinned the skill
    # telling it what evidence is for.
    pin_requirements = ("skill",)

    def __init__(
        self,
        *,
        enabled: bool,
        client_factory: Callable[[str, RawSink, LedgerSink], ExaAgentSurface] | None,
        artifacts: ArtifactSink | None = None,
    ) -> None:
        self._enabled = enabled
        self._client_factory = client_factory
        # Slice 1b, D3: the call's raw body becomes an artifact and its rows land on the ledger;
        # without an artifact store the tool refuses before spending rather than keeping half.
        self._artifacts = artifacts

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        del inputs, ctx
        if not self._enabled:
            return _fail(
                "persona_evidence_disabled",
                "CLUE_ONBOARDING_PERSONA_EVIDENCE_ENABLED is off in this deployment",
            )
        if self._client_factory is None:
            return _fail("exa_not_configured", "CLUE_EXA_API_KEY is not configured in this process")
        if self._artifacts is None:
            return _fail(
                "artifacts_not_configured",
                "no artifact store is composed in this process, so the call's raw body could "
                "not be kept; refusing before spend",
            )
        return ()

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        del inputs
        return ToolEstimate(
            cost_cents=_ESTIMATE_CENTS, detail={"basis": "exa_deep_reasoning_single_call"}
        )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ExaSearchEvidenceInput)
        assert self._client_factory is not None and self._artifacts is not None
        label = f"{self.name}:{ctx.operation_id}"
        raw, ledger = BufferedRawSink(), BufferedLedger()
        client = self._client_factory(label, raw, ledger)
        try:
            result = await asyncio.to_thread(
                lambda: client.deep_reasoning(
                    system_prompt=PERSONA_EVIDENCE_SYSTEM_PROMPT,
                    query=inputs.query,
                    output_schema=persona_evidence_output_schema(),
                    num_results=inputs.num_results,
                    include_domains=list(inputs.include_domains) or None,
                    label=label,
                )
            )
        finally:
            # Slice 1b: the call's rows are money whatever its outcome; they land under the
            # turn's own connection factory. The context carries no project, so this is
            # workspace spend.
            async with ctx.conn_factory() as conn:
                await drain_provider_calls(
                    conn,
                    raw=raw,
                    ledger=ledger,
                    artifacts=self._artifacts,
                    stamp=LedgerStamp(workspace_id=ctx.workspace_id),
                )
        output = ExaSearchEvidenceOutput(
            passages=_passages(result),
            cost_usd=str(result.cost_usd) if result.cost_usd is not None else "0",
            request_id=result.request_id,
        )
        return ToolResult(
            tool=self.name, version=self.version, references=output.model_dump(mode="json")
        )


def _passages(result: ExaDeepResult) -> list[EvidencePassage]:
    parsed = result.output_object if isinstance(result.output_object, dict) else {}
    raw = [item for item in (parsed.get("passages") or []) if isinstance(item, dict)]
    sources = sources_by_field(result.grounding if isinstance(result.grounding, list) else [])
    passages: list[EvidencePassage] = []
    for index, item in enumerate(raw):
        quote, role = item.get("quote"), item.get("speaker_role")
        if not (
            isinstance(quote, str) and quote.strip() and isinstance(role, str) and role.strip()
        ):
            continue
        prefix = f"passages[{index}]"
        citations = [
            citation
            for field, entry in sources.items()
            if field == prefix or field.startswith(prefix + ".")
            for citation in entry["citations"]
        ]
        first = citations[0] if citations else {}
        org_type, topic = item.get("org_type"), item.get("topic")
        url, title = first.get("url"), first.get("title")
        passages.append(
            EvidencePassage(
                quote=quote.strip(),
                speaker_role=role.strip(),
                org_type=org_type if isinstance(org_type, str) else None,
                topic=topic if isinstance(topic, str) else None,
                url=url if isinstance(url, str) else None,
                title=title if isinstance(title, str) else None,
            )
        )
    return passages


def build_onboarding_evidence_tools(
    *, settings: Settings, secrets: Secrets | None, artifacts: ArtifactSink | None = None
) -> tuple[Tool, ...]:
    """Compose the evidence tool. ``secrets=None`` means *no provider credentials*.

    The default is fail-closed on purpose: a composition that did not explicitly hand over
    credentials gets a tool with no client factory, which refuses ``exa_not_configured`` before any
    spend. Reading the environment here instead would make every test that builds a toolbelt
    compose a live, billable Exa client on any machine that has a key in its ``.env``. Production
    composition roots pass a real :class:`Secrets` deliberately.

    ``artifacts`` is the store the call's raw body lands in; without one the tool refuses
    ``artifacts_not_configured`` before any spend (slice 1b, D3).
    """
    key = secrets.exa_api_key if secrets is not None else None
    factory: Callable[[str, RawSink, LedgerSink], ExaAgentSurface] | None = None
    if key is not None and key.get_secret_value().strip():
        secret = SecretStr(key.get_secret_value())

        def build_client(label: str, raw: RawSink, ledger: LedgerSink) -> ExaAgentSurface:
            # One caller per invocation: ProviderCaller's totals/latch are unlocked mutable state.
            del label  # the label rides the rows; the sinks are the invocation's
            caller = ProviderCaller(
                transport=HttpxTransport(),
                raw_sink=raw,
                ledger=ledger,
                now=lambda: datetime.now(UTC),
            )
            return ExaClient(caller, secret)

        factory = build_client

    return (
        ExaSearchEvidenceTool(
            enabled=settings.onboarding_persona_evidence_enabled,
            client_factory=factory,
            artifacts=artifacts,
        ),
    )
