"""Conversation naming — one cheap call names a chat and, on the Home path, its project.

Spec: docs/superpowers/specs/2026-09-18-conversation-naming-design.md. The namer is a service
step with no agent authority: it is not a tool, appears in no profile, and never raises into the
turn that started it. It fills only placeholders — ``agent_thread.title IS NULL`` and
``project.name = UNTITLED_PROJECT_NAME`` — so a human rename always wins (§4.5).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from clue_api.arv2.errors import RawParseError
from clue_api.arv2.openrouter import (
    openrouter_chat_request,
    openrouter_cost_reader,
    openrouter_halt_rule,
    openrouter_message_text,
)
from clue_api.thread_store import get_thread, set_thread_title_if_unset
from clue_config import Secrets, Settings
from clue_config.gateway import GatewayConfig
from clue_db import ConnFactory, transaction
from clue_obs import get_logger, observation
from clue_spend.calls import CallResult, CallSpec, ProviderCaller, SpendEstimate
from clue_spend.ledger import (
    ArtifactSink,
    BufferedLedger,
    BufferedRawSink,
    LedgerStamp,
    drain_provider_calls,
)
from clue_spend.transport import HttpxTransport, Transport
from clue_spine import (
    UNTITLED_PROJECT_NAME,
    get_brand,
    get_product,
    get_project_for_workspace,
    set_project_name_if_untitled,
)

log = get_logger("clue_api.conversation_naming")

#: How long the engine waits for the namer before emitting the terminal turn event (§4.1). NOT
#: the call timeout: a slower call keeps running detached and writes its names when it lands.
NAMING_GRACE_S = 3.0
#: Prefix of the user message and of the reply the prompt sees (§4.2).
NAMING_INPUT_CHARS = 2_000
NAMING_MAX_TOKENS = 60
NAMING_MAX_CODE_POINTS = 60
NAMING_MAX_WORDS = 8
NAMING_LABEL = "conversation_naming"
NAMING_ESTIMATE_USD = Decimal("0.001")
#: Names the model may not hand back (case-folded).
PLACEHOLDER_NAMES = frozenset({"untitled project", "new chat", "untitled"})

NAMING_SYSTEM_PROMPT = """You name conversations for a B2B account-based-marketing workspace.
You are given the first exchange of a chat and asked for one or two names.

chat_title: 2 to 5 words naming the task the user is doing in this chat.
project_name: 2 to 5 words naming the overall marketing motion this project
is about — who is being targeted, for what, or with what product. Only when asked.

Rules:
- Write in the language the user wrote in.
- Sentence case. No trailing punctuation, no quotes, no emoji, no hashtags.
- Never repeat the project name inside the chat title.
- Never invent company, product or segment names that do not appear in the exchange;
  when the exchange names an account or a segment, prefer it.
- If a field is not listed under Needed, return an empty string for it.
- Return only the JSON object."""

NAMING_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "conversation_names",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "chat_title": {"type": "string"},
                "project_name": {"type": "string"},
            },
            "required": ["chat_title", "project_name"],
            "additionalProperties": False,
        },
    },
}

_WRAPPING = "\"'`“”‘’"
_TRAILING = ".!?:;,…"


def normalize_generated_name(raw: object) -> str | None:
    """One generated name, cleaned — or ``None`` when it must be dropped (§4.4).

    Dropped, never truncated: a bad output leaves the placeholder rather than a mangled title.
    """
    if not isinstance(raw, str):
        return None
    text = " ".join(raw.split())
    text = text.strip(_WRAPPING).strip()
    text = text.rstrip(_TRAILING).strip()
    if not text:
        return None
    if len(text) > NAMING_MAX_CODE_POINTS or len(text.split()) > NAMING_MAX_WORDS:
        return None
    if text.casefold() in PLACEHOLDER_NAMES:
        return None
    return text


def build_naming_messages(
    *,
    brand_name: str,
    product_name: str | None,
    project_name: str | None,
    needs_chat_title: bool,
    needs_project_name: bool,
    user_message: str,
    assistant_message: str,
) -> list[dict[str, str]]:
    """The two chat messages of one naming call (§4.2, §4.3)."""
    needed = [
        field
        for field, wanted in (
            ("chat_title", needs_chat_title),
            ("project_name", needs_project_name),
        )
        if wanted
    ]
    lines = [f"Brand: {brand_name}"]
    if product_name:
        lines.append(f"Product: {product_name}")
    if project_name:
        lines.append(f"Project: {project_name}")
    lines.append(f"Needed: {', '.join(needed)}")
    lines.append("")
    lines.append("User wrote:")
    lines.append(user_message[:NAMING_INPUT_CHARS])
    lines.append("")
    lines.append("Assistant replied:")
    lines.append(assistant_message[:NAMING_INPUT_CHARS])
    return [
        {"role": "system", "content": NAMING_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(lines)},
    ]


@dataclass(frozen=True, slots=True)
class NamingRequest:
    """What the engine hands the namer: the turn's scope and its opening exchange."""

    workspace_id: str
    project_id: str
    thread_id: str
    turn_id: UUID
    user_message: str
    assistant_message: str


@dataclass(frozen=True, slots=True)
class NamingOutcome:
    """What landed. ``skipped_reason`` is set when nothing was written (§4.10)."""

    chat_title: str | None
    project_name: str | None
    skipped_reason: str | None


class ConversationNamer(Protocol):
    async def name(self, request: NamingRequest) -> NamingOutcome: ...


class _NamesReply(BaseModel):
    model_config = ConfigDict(extra="ignore")

    chat_title: str = ""
    project_name: str = ""


def _read_names(result: CallResult) -> _NamesReply | None:
    """The reply as the two names, or ``None`` when the model did not answer in shape."""
    try:
        return _NamesReply.model_validate(json.loads(openrouter_message_text(result.json())))
    except (RawParseError, ValueError, ValidationError):
        return None


class OpenRouterConversationNamer:
    """The production namer: one OpenRouter call through the spend-ledger caller (§4.2, §4.9)."""

    def __init__(
        self,
        *,
        api_key: SecretStr,
        base_url: str,
        model: str,
        timeout_s: float,
        artifacts: ArtifactSink | None,
        conn_factory: ConnFactory = transaction,
        transport_factory: Callable[[], Transport] = HttpxTransport,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._timeout_s = timeout_s
        self._artifacts = artifacts
        self._conn_factory = conn_factory
        self._transport_factory = transport_factory

    async def name(self, request: NamingRequest) -> NamingOutcome:
        """Never raises: every failure is one ``conversation_naming.skipped`` event (§4.10)."""
        try:
            return await self._name(request)
        except Exception:  # noqa: BLE001 — a naming failure must never reach the turn
            log.warning(
                "conversation_naming.skipped",
                reason="unexpected_error",
                turn_id=str(request.turn_id),
                thread_id=request.thread_id,
                project_id=request.project_id,
                exc_info=True,
            )
            return NamingOutcome(
                chat_title=None, project_name=None, skipped_reason="unexpected_error"
            )

    async def _name(self, request: NamingRequest) -> NamingOutcome:
        async with self._conn_factory() as conn:
            thread = await get_thread(
                conn, workspace_id=request.workspace_id, thread_id=request.thread_id
            )
            project = await get_project_for_workspace(
                conn, workspace_id=request.workspace_id, project_id=request.project_id
            )
            if thread is None or project is None:
                return self._skip(request, "scope_missing")
            needs_chat_title = thread.title is None
            needs_project_name = project.name == UNTITLED_PROJECT_NAME
            if not (needs_chat_title or needs_project_name):
                return self._skip(request, "already_named", level="info")
            brand = await get_brand(
                conn, workspace_id=request.workspace_id, brand_id=project.brand_id
            )
            product = (
                await get_product(conn, project.product_id)
                if project.product_id is not None
                else None
            )

        messages = build_naming_messages(
            brand_name=brand.name if brand is not None else "",
            product_name=product.name if product is not None else None,
            project_name=None if needs_project_name else project.name,
            needs_chat_title=needs_chat_title,
            needs_project_name=needs_project_name,
            user_message=request.user_message,
            assistant_message=request.assistant_message,
        )
        spec = CallSpec(
            provider="openrouter",
            operation="chat/completions",
            label=NAMING_LABEL,
            request=openrouter_chat_request(
                base_url=self._base_url,
                api_key=self._api_key,
                model=self._model,
                messages=messages,
                response_format=NAMING_RESPONSE_FORMAT,
                reasoning={"effort": "none"},
                max_tokens=NAMING_MAX_TOKENS,
                temperature=0.2,
                timeout_s=self._timeout_s,
            ),
            estimate=SpendEstimate(usd=NAMING_ESTIMATE_USD),
            max_attempts=1,
            cost_reader=openrouter_cost_reader,
            halt_rule=openrouter_halt_rule,
            extras={
                "thread_id": request.thread_id,
                "project_id": request.project_id,
                "turn_id": str(request.turn_id),
            },
        )
        raw, ledger = BufferedRawSink(), BufferedLedger()
        caller = ProviderCaller(
            transport=self._transport_factory(),
            raw_sink=raw,
            ledger=ledger,
            now=lambda: datetime.now(UTC),
        )
        reason: str | None = None
        chat_title: str | None = None
        project_name: str | None = None
        try:
            with observation(
                "conversation.naming",
                as_type="generation",
                model=self._model,
                input={
                    "needs_chat_title": needs_chat_title,
                    "needs_project_name": needs_project_name,
                },
            ) as current:
                try:
                    # ``ProviderCaller.call`` is synchronous (httpx); keep the worker loop free.
                    result = await asyncio.to_thread(caller.call, spec)
                except Exception:  # noqa: BLE001 — recorded as a skip, never raised
                    log.warning(
                        "conversation_naming.call_failed",
                        turn_id=str(request.turn_id),
                        exc_info=True,
                    )
                    reason = "provider_error"
                else:
                    if result.response.status >= 400:
                        reason = "provider_error"
                    else:
                        reply = _read_names(result)
                        if reply is None:
                            reason = "invalid_reply"
                        else:
                            chat_title = (
                                normalize_generated_name(reply.chat_title)
                                if needs_chat_title
                                else None
                            )
                            project_name = (
                                normalize_generated_name(reply.project_name)
                                if needs_project_name
                                else None
                            )
                            if chat_title is None and project_name is None:
                                reason = "names_rejected"
                current.update(
                    output={"chat_title": chat_title, "project_name": project_name},
                    level="DEFAULT" if reason is None else "WARNING",
                    status_message=reason,
                )
        finally:
            async with self._conn_factory() as conn:
                await drain_provider_calls(
                    conn,
                    raw=raw,
                    ledger=ledger,
                    artifacts=self._artifacts,
                    stamp=LedgerStamp(
                        workspace_id=request.workspace_id,
                        project_id=request.project_id,
                        job_id=request.turn_id,
                    ),
                )
        if reason is not None:
            return self._skip(request, reason)

        applied_chat: str | None = None
        applied_project: str | None = None
        async with self._conn_factory() as conn:
            if chat_title is not None:
                row = await set_thread_title_if_unset(
                    conn,
                    workspace_id=request.workspace_id,
                    thread_id=request.thread_id,
                    title=chat_title,
                )
                if row is None:
                    log.info(
                        "conversation_naming.skipped",
                        reason="lost_to_manual_rename",
                        slot="chat_title",
                        turn_id=str(request.turn_id),
                        thread_id=request.thread_id,
                    )
                else:
                    applied_chat = chat_title
            if project_name is not None:
                project_row = await set_project_name_if_untitled(
                    conn,
                    workspace_id=request.workspace_id,
                    project_id=request.project_id,
                    name=project_name,
                )
                if project_row is None:
                    log.info(
                        "conversation_naming.skipped",
                        reason="lost_to_manual_rename",
                        slot="project_name",
                        turn_id=str(request.turn_id),
                        project_id=request.project_id,
                    )
                else:
                    applied_project = project_name
        log.info(
            "conversation_naming.applied",
            turn_id=str(request.turn_id),
            thread_id=request.thread_id,
            project_id=request.project_id,
            chat_title=applied_chat,
            project_name=applied_project,
        )
        return NamingOutcome(
            chat_title=applied_chat, project_name=applied_project, skipped_reason=None
        )

    @staticmethod
    def _skip(request: NamingRequest, reason: str, *, level: str = "warning") -> NamingOutcome:
        getattr(log, level)(
            "conversation_naming.skipped",
            reason=reason,
            turn_id=str(request.turn_id),
            thread_id=request.thread_id,
            project_id=request.project_id,
        )
        return NamingOutcome(chat_title=None, project_name=None, skipped_reason=reason)


def build_conversation_namer(
    *,
    settings: Settings,
    secrets: Secrets,
    artifacts: ArtifactSink | None,
    conn_factory: ConnFactory = transaction,
) -> ConversationNamer | None:
    """The fleet worker's namer, or ``None`` (stated once at boot) when off or keyless."""
    if not settings.conversation_naming_enabled:
        log.info(
            "conversation_naming.not_composed", reason="CLUE_CONVERSATION_NAMING_ENABLED is off"
        )
        return None
    key = secrets.openrouter_api_key
    if key is None or not key.get_secret_value().strip():
        log.warning(
            "conversation_naming.not_composed",
            reason="CLUE_OPENROUTER_API_KEY is not configured",
            detail="chats and projects keep their placeholder names on this worker",
        )
        return None
    return OpenRouterConversationNamer(
        api_key=key,
        base_url=GatewayConfig().base_url,
        model=settings.conversation_naming_model,
        timeout_s=settings.conversation_naming_timeout_s,
        artifacts=artifacts,
        conn_factory=conn_factory,
    )


class TurnNamingLauncher:
    """Starts the namer beside the turn's close projection and bounds how long the turn waits.

    §4.1: the terminal turn event waits at most ``grace_s``; a slower call keeps running as a
    task this launcher holds a reference to (so it is neither garbage-collected nor awaited by
    the fleet handler) and writes its names when it lands. Worker shutdown cancels it — the
    placeholder stays and the next completed turn retries.
    """

    def __init__(self, *, namer: ConversationNamer | None, grace_s: float = NAMING_GRACE_S) -> None:
        self._namer = namer
        self._grace_s = grace_s
        self._pending: set[asyncio.Task[NamingOutcome]] = set()

    @property
    def pending(self) -> int:
        return len(self._pending)

    def start(self, request: NamingRequest) -> asyncio.Task[NamingOutcome] | None:
        if self._namer is None:
            return None
        namer = self._namer

        async def _run() -> NamingOutcome:
            try:
                return await namer.name(request)
            except Exception:  # noqa: BLE001 — a namer that raises is a skip, never a turn error
                log.warning(
                    "conversation_naming.skipped",
                    reason="unexpected_error",
                    turn_id=str(request.turn_id),
                    thread_id=request.thread_id,
                    exc_info=True,
                )
                return NamingOutcome(
                    chat_title=None, project_name=None, skipped_reason="unexpected_error"
                )

        task = asyncio.create_task(_run(), name=f"conversation-naming:{request.turn_id}")
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)
        return task

    async def wait_grace(self, task: asyncio.Task[NamingOutcome] | None) -> bool:
        """``True`` when there was nothing to wait for or the namer finished inside the grace."""
        if task is None:
            return True
        done, _ = await asyncio.wait({task}, timeout=self._grace_s)
        if task in done:
            return True
        log.info("conversation_naming.detached", task=task.get_name(), grace_s=self._grace_s)
        return False
