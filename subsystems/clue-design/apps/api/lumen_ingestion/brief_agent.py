"""The ingestion design-brief agent (slice 3) — tier 2 of the design-brief plan.

One `langchain.agents.create_agent`-style stage inside the existing website
ingestion job (founder's explicit instruction: a plain tool-calling agent, not a
deepagent — no leg, no HITL, no separate run). It sits after normalize and before
the kit is published, reads what the pipeline already captured, and writes the
`BrandBrief@1` object that rides the draft kit.

**Its evidence is handed to it; it browses nothing.** `TOOLS` is empty by
construction, so there is no mechanism by which the agent can fetch a second page
and then write about it — the brief can only be as wide as the capture was. That
is the structural half of the prompt's "evidence or silence" law (the prose half
is the controller-authored system prompt in `brief_agent_prompt.md`, which this
module loads verbatim and must never rewrite).

**Nothing here may fail an ingestion** (plan constraint 6). A refusal, an invalid
brief, a hung gateway and an agent that throws all land as a diagnostic on the
kit and a briefless publish. With no agent configured the stage is *silent* — no
call, no diagnostic, no `brief` key — so an un-keyed deployment publishes exactly
the kit it publishes today.

Diagnostic codes:

* ``LUMI0901`` — the agent refused (it could not ground a brief). Honest empty.
* ``LUMI0902`` — the agent answered, but the answer failed `BrandBrief@1`
  validation or the token law. Never trusted, never partially kept.
* ``LUMI0903`` — the stage errored entirely (gateway, import, anything else).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Protocol, Sequence, runtime_checkable

from py_lumen_config import settings

from .brief import BriefRefused, kit_token_names, validate_brief

logger = logging.getLogger(__name__)

#: The controller-authored system prompt. Its TEXT is owned outside this module —
#: the harness exists to make its promises true, never to edit them.
BRIEF_PROMPT_PATH = Path(__file__).resolve().parent / "brief_agent_prompt.md"

#: Bound on the agent loop. With an empty tool set a well-behaved run is one
#: model call plus the structured-output call; the remainder is headroom for the
#: structured-output strategy to re-ask once on a malformed emission. A runaway
#: loop hits this and becomes a diagnostic, not a stuck ingestion.
MAX_AGENT_STEPS = 6

#: How many captured screenshots ride the request. The capture takes full-page
#: shots; three is the brand's own evidence without turning one ingestion into a
#: multi-megabyte prompt.
MAX_SCREENSHOTS = 3

#: How much narrative text rides along. The brief is about design, not copy.
_MAX_EXCERPT = 1500


@dataclass
class BriefRequest:
    """Everything the agent is allowed to know, assembled before the call.

    Deliberately a plain value object: it is built and asserted on in tests
    without a gateway, a browser, or a database.
    """

    brand_name: str | None
    url: str | None
    #: `{name, group, value, provenance, confidence}` per emitted kit token.
    #: Provenance rides so the agent can tell a MEASURED fact (`website:`) from a
    #: platform fallback (`derived:`) — the prompt forbids presenting the latter
    #: as a brand fact.
    tokens: list[dict[str, Any]] = field(default_factory=list)
    #: Slice-2 `SurfaceShape` records — the source for component recipes.
    shapes: list[dict[str, Any]] = field(default_factory=list)
    #: Slice-2 `SectionBackground` sequence, in DOM order.
    background_sequence: list[dict[str, Any]] = field(default_factory=list)
    #: The measured spacing ladder (`space.*` tokens), smallest first.
    spacing_ladder: list[dict[str, Any]] = field(default_factory=list)
    #: `(base64, mime)` per captured screenshot.
    screenshots: list[tuple[str, str]] = field(default_factory=list)
    #: The kit's own token dictionary — the token law's resolution set.
    token_names: set[str] = field(default_factory=set)
    text_excerpt: str | None = None

    def evidence_json(self) -> str:
        """The evidence payload as the model receives it."""
        return json.dumps(
            {
                "brand_name": self.brand_name,
                "url": self.url,
                "kit_tokens": self.tokens,
                "component_shape_records": self.shapes,
                "section_background_sequence": self.background_sequence,
                "spacing_ladder": self.spacing_ladder,
                "page_text_excerpt": self.text_excerpt,
            },
            ensure_ascii=False,
            sort_keys=True,
        )


@runtime_checkable
class BriefAgent(Protocol):
    """The stage's model seam.

    `active` gates the call the way `AssetDescriber.active` gates description:
    an unconfigured agent is OFF, not a failure to report.
    """

    active: bool

    def write_brief(self, request: BriefRequest) -> dict[str, Any]: ...


class NullBriefAgent:
    """Deterministic no-op. The default everywhere; every test uses this unless
    it is testing the model path."""

    active = False

    def write_brief(self, request: BriefRequest) -> dict[str, Any]:
        raise BriefRefused("no brief agent is configured")


def load_brief_prompt() -> str:
    """The committed, controller-authored system prompt, verbatim."""
    return BRIEF_PROMPT_PATH.read_text()


class OpenRouterBriefAgent:
    """The real stage: `create_agent` over the governed OpenRouter gateway.

    Enabled only when ``LUMEN_INGESTION_BRIEF=1`` and an OpenRouter key exists —
    the same env-gate shape `assist.py` / `describe.py` use, so an ingestion
    deployment turns the brief on the way it turns vision on.

    The model build goes through `lumen_agent.llm.init_model`, the platform's
    governed gateway seam (bounded output, truthful answering-model attribution,
    usage accounting) rather than a second hand-rolled httpx client. It is
    imported lazily so this module stays importable — and the whole ingestion
    suite stays runnable — without langchain or the platform gateway present.

    Structured output goes through `ToolStrategy`, not the provider's native
    JSON mode: the design runtime already recorded (deepagent decision D11) that
    grok-family models emit malformed JSON under native structured output, and
    `ToolStrategy` re-asks on a validation failure instead of dying.
    """

    #: Empty, deliberately: the agent's evidence is handed to it (plan §4). A
    #: browsing or fetching tool here would let the brief describe a page the
    #: capture never recorded, and no downstream reader could tell.
    TOOLS: ClassVar[tuple] = ()

    def __init__(self) -> None:
        self.enabled = settings.lumen_ingestion_brief
        self.model = settings.lumen_ingestion_brief_model
        self.reasoning = settings.lumen_ingestion_brief_reasoning
        self.base_url = settings.openrouter_base_url
        self.api_key = settings.openrouter_api_key

    @property
    def active(self) -> bool:
        return bool(self.enabled and self.api_key)

    def write_brief(self, request: BriefRequest) -> dict[str, Any]:
        from langchain.agents import create_agent
        from langchain.agents.structured_output import ToolStrategy
        from lumen_agent.llm import init_model
        from lumen_agent.usage_collector import ModelCallCollector

        from .brief import BrandBrief

        model = init_model(
            self.model,
            base_url=self.base_url,
            api_key=self.api_key,
            reasoning=self.reasoning,
            role="ingestion-brief",
        )
        # Lane 3 slice 5: this stage's model calls are real money and had no row behind them.
        # The collector is attached INSTANCE-level — the same `.callbacks` append
        # `lumen_agent.trace_callbacks.attach_trace_callback` uses, and for the same reason:
        # `.with_config` returns a RunnableBinding the agent factory mishandles. There is one
        # model and no sub-agents here, so `on_llm_*` on this instance IS every call the stage
        # makes.
        collector = ModelCallCollector()
        _append_callback(model, collector)
        agent = create_agent(
            model=model,
            tools=list(self.TOOLS),
            system_prompt=load_brief_prompt(),
            response_format=ToolStrategy(BrandBrief),
            name="lumen-ingestion-brief-agent",
        )
        try:
            result = agent.invoke(
                {"messages": [{"role": "user", "content": _message_content(request)}]},
                config={"recursion_limit": MAX_AGENT_STEPS},
            )
        finally:
            # On EVERY exit path: a refusal and a hung gateway still spent the calls they made.
            _record_spend(collector)
        structured = result.get("structured_response")
        if structured is None:
            raise BriefRefused("the brief agent returned no BrandBrief@1 object")
        return structured.model_dump(mode="json")


def _append_callback(model: Any, handler: Any) -> None:
    """Append a handler to a model's own declared ``callbacks`` field, in place.

    Mirrors ``lumen_agent.trace_callbacks.attach_trace_callback``: append, never replace, and a
    model with no writable ``callbacks`` field (a test sentinel) is left untouched — a receipt is
    never worth failing an ingestion over.
    """
    if not hasattr(model, "callbacks"):
        return
    try:
        existing = model.callbacks
        if existing is None:
            model.callbacks = [handler]
        elif isinstance(existing, list):
            existing.append(handler)
        else:
            add_handler = getattr(existing, "add_handler", None)
            if callable(add_handler):
                add_handler(handler)
            else:
                model.callbacks = [existing, handler]
    except Exception:  # noqa: BLE001 - never block the stage on wiring
        logger.warning("brief agent usage collection not wired", exc_info=True)


def _record_spend(collector: Any) -> None:
    """Land the stage's collected calls on the ingestion job's open spend scope.

    No scope open (a direct call, a test) means the rows have nowhere to go; the calls still
    happened and are still on the gateway's own record, so this is a skip and not an error.
    Plan constraint 6 holds here too: nothing in the brief stage may fail an ingestion, so a
    ledger failure is logged and swallowed.
    """
    try:
        from lumen_api import spend

        scope = spend.current_scope()
        if scope is None:
            return
        for call in collector.calls:
            spend.record_collected_model_call(
                scope, call, operation="design.ingestion.brief", label="brief"
            )
    except Exception:  # noqa: BLE001 - the ledger may never fail an ingestion
        logger.warning("brief agent spend rows not recorded", exc_info=True)


def _message_content(request: BriefRequest) -> list[dict[str, Any]]:
    """The user turn: the evidence bundle, then the screenshots themselves.

    Image blocks use the LangChain-v1 shape the design runtime's own vision
    callers use (`imagery_judge._png_base64`), so one gateway serves both.
    """
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "Write this brand's BrandBrief@1 from the evidence below and the "
                "screenshots that follow. Every token name you use must be one of "
                "the kit token names in `kit_tokens`.\n\n" + request.evidence_json()
            ),
        }
    ]
    for image_b64, mime in request.screenshots:
        content.append(
            {
                "type": "image",
                "source_type": "base64",
                "mime_type": mime or "image/png",
                "data": image_b64,
            }
        )
    return content


def resolve_brief_agent() -> BriefAgent:
    """The configured brief agent — `NullBriefAgent` unless the stage is on."""
    agent = OpenRouterBriefAgent()
    return agent if agent.active else NullBriefAgent()


def build_brief_request(
    evidence: Any,
    brand_kit: dict[str, Any],
    *,
    screenshots: Sequence[tuple[str, str]] = (),
) -> BriefRequest:
    """Assemble the agent's whole world from the job's own evidence and kit."""
    narrative = getattr(evidence, "narrative", None)
    geometry = getattr(evidence, "geometry", None)
    tokens = _token_rows(brand_kit)
    excerpt = getattr(narrative, "text_excerpt", None)
    return BriefRequest(
        brand_name=getattr(narrative, "brand_name", None),
        url=getattr(narrative, "url", None),
        tokens=tokens,
        shapes=[_dump(shape) for shape in getattr(geometry, "surfaces", []) or []],
        background_sequence=[
            _dump(band) for band in getattr(geometry, "background_sequence", []) or []
        ],
        spacing_ladder=[row for row in tokens if row["group"] == "spacing"],
        screenshots=list(screenshots)[:MAX_SCREENSHOTS],
        token_names=kit_token_names(brand_kit),
        text_excerpt=excerpt[:_MAX_EXCERPT] if excerpt else None,
    )


def _dump(model: Any) -> dict[str, Any]:
    return model.model_dump() if hasattr(model, "model_dump") else dict(model)


def _token_rows(brand_kit: dict[str, Any]) -> list[dict[str, Any]]:
    """Every emitted token, flattened with its provenance and confidence.

    An alias is emitted as its own row pointing at its target — the agent may
    speak either name, and hiding aliases would make a kit-legal name look
    unresolvable.
    """
    tokens = brand_kit.get("tokens") or {}
    rows: list[dict[str, Any]] = []
    for group, entries in tokens.items():
        if not isinstance(entries, dict):
            continue
        for name, token in entries.items():
            if not isinstance(token, dict):
                continue
            provenance = token.get("provenance") or {}
            rows.append(
                {
                    "name": name,
                    "group": group,
                    "value": token.get("value", {}).get("default")
                    if isinstance(token.get("value"), dict)
                    else token.get("token"),
                    "provenance": str(provenance.get("source") or "unknown"),
                    "confidence": provenance.get("confidence"),
                }
            )
    rows.sort(key=lambda row: (row["group"], row["name"]))
    return rows


def generate_brief(
    request: BriefRequest,
    *,
    agent: BriefAgent | None = None,
    diagnostics: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Run the brief stage. Returns the brief payload, or `None` — never raises.

    `None` means "this kit publishes briefless", which is a valid, honest state.
    Every non-silent `None` leaves a diagnostic naming the reason on the kit.
    """
    resolved = agent if agent is not None else resolve_brief_agent()
    if not getattr(resolved, "active", False):
        # OFF is not a failure: no call, no diagnostic, no brief key.
        return None

    try:
        payload = resolved.write_brief(request)
    except BriefRefused as refusal:
        _record(diagnostics, "LUMI0901", f"the brief agent refused: {refusal.reason}")
        return None
    except Exception as error:  # noqa: BLE001 - the stage may never fail an ingest
        logger.warning("the brief stage failed; publishing briefless", exc_info=True)
        _record(
            diagnostics,
            "LUMI0903",
            f"the brief stage failed entirely ({type(error).__name__}): {error}",
        )
        return None

    try:
        brief = validate_brief(payload, token_names=request.token_names)
    except BriefRefused as refusal:
        _record(diagnostics, "LUMI0902", f"the brief was not trustworthy: {refusal.reason}")
        return None
    return brief.model_dump(mode="json")


def _record(diagnostics: list[dict[str, Any]] | None, code: str, message: str) -> None:
    if diagnostics is None:
        return
    diagnostics.append({"code": code, "severity": "warning", "message": message})
