"""Conversation naming — one cheap call names a chat and, on the Home path, its project.

Spec: docs/superpowers/specs/2026-09-18-conversation-naming-design.md. The namer is a service
step with no agent authority: it is not a tool, appears in no profile, and never raises into the
turn that started it. It fills only placeholders — ``agent_thread.title IS NULL`` and
``project.name = UNTITLED_PROJECT_NAME`` — so a human rename always wins (§4.5).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from clue_obs import get_logger

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
