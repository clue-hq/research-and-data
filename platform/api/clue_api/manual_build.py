"""The entry point for the operating-manual builder.

The rendering lives in :mod:`clue_agents.manual.build`; this module is the half that needs the
composition root. It composes the toolbelt with every capability absent (a descriptor is a static
contract, so a chapter is rendered from the declared shape and never from a live service) and
collects the handful of constants the chapters quote, reading each off its real definition rather
than retyping the number.

``python -m clue_api.manual_build --write`` regenerates the four chapters; ``--check`` exits 1 on
drift. ``make manual`` / ``make manual-check``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import get_args

from clue_agents.manual.build import CodeFacts, run
from clue_api.agent_execution_wiring import _FAILURE_MESSAGE_LIMIT
from clue_api.agent_runtime_wiring import (
    _GOVERNED_TOOL_REPAIR_HELP,
    GovernedToolFailure,
    ModelFinalizeRequest,
)
from clue_api.agent_turn_fleet_wiring import PROJECT_CONVERSATION_BUDGET_LIMIT_MILLICENTS
from clue_api.arv2.read_tools import READ_REFERENCES_BUDGET_BYTES
from clue_api.toolbelt_wiring import build_toolbelt
from clue_api.turn_binding import TRUSTED_TURN_FIELD
from clue_config import Settings
from clue_toolbelt.registry import ToolRegistry

__all__ = ["build_facts", "load_toolbelt", "main"]

#: One line per field of the refusal object the model reads. The shapes are the code's; the words
#: are what the field means to the agent holding it.
_GOVERNED_FAILURE_FIELD_NOTES = {
    "governed_repair_budgeted": "Whether this refusal spends a repair round. False only for a "
    "precondition refusal from an effect-free read.",
    "error": "`plan_rejected` (nothing ran) or `operation_failed` (it ran and did not complete).",
    "address": "The exact `name@version` you called.",
    "node_key": "The call's identity. The same provider call id addresses the same operation.",
    "recorded": "Always false. No durable state changed and this operation did not happen.",
    "reasons": "One line per issue. This is the half you repair.",
    "guidance": "Fixed text, the same on every refusal.",
}

_FINALIZE_FIELD_NOTES = {
    "user_message": "the only thing the human reads",
    "assumptions": "stored as artifacts, never shown to the human",
    "next_actions": "one line per thing you are waiting for",
    "failure_code": "lowercase, and only on a failed status",
}


def load_toolbelt() -> ToolRegistry:
    """The registry with no capability composed: descriptors only, which is all a chapter needs."""

    return build_toolbelt(storage=None, gateway=None)


def build_facts(settings: Settings | None = None) -> CodeFacts:
    """Collect the composition-root facts the chapters quote, off their real definitions."""

    return CodeFacts(
        settings=settings or Settings(),
        trusted_turn_field_key=TRUSTED_TURN_FIELD,
        failure_message_limit=_FAILURE_MESSAGE_LIMIT,
        governed_tool_repair_help=_GOVERNED_TOOL_REPAIR_HELP,
        governed_failure_fields=tuple(
            (name, _GOVERNED_FAILURE_FIELD_NOTES[name]) for name in GovernedToolFailure.model_fields
        ),
        finalize_fields=tuple(
            (name, f"{_finalize_bound(name)}; {note}")
            for name, note in _FINALIZE_FIELD_NOTES.items()
        ),
        read_references_budget_bytes=READ_REFERENCES_BUDGET_BYTES,
        budget_limit_millicents=PROJECT_CONVERSATION_BUDGET_LIMIT_MILLICENTS,
    )


def _constraints(annotation: object) -> list[object]:
    """Every constraint object on a field, including the ones inside an aliased annotation.

    ``failure_code`` carries the envelope's own ``ReasonCode`` alias rather than a hand-copied
    pattern, so its bounds live in the annotation tree and not in ``FieldInfo.metadata``.
    """

    found: list[object] = []
    metadata = getattr(annotation, "__metadata__", ())
    found.extend(metadata)
    for argument in get_args(annotation):
        if argument not in (None, type(None)):
            found.extend(_constraints(argument))
    return found


def _finalize_bound(name: str) -> str:
    """The declared bound on one model-supplied finalize field, read off the contract."""

    field = ModelFinalizeRequest.model_fields[name]
    unit = "characters" if name in {"user_message", "failure_code"} else "items"
    parts: list[str] = []
    for item in [*field.metadata, *_constraints(field.annotation)]:
        value = getattr(item, "max_length", None)
        if value is not None:
            parts.append(f"at most {value:,} {unit}")
        pattern = getattr(item, "pattern", None)
        if pattern is not None:
            parts.append(f"matches `{pattern}`")
    return "; ".join(dict.fromkeys(parts)) if parts else "no declared bound"


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv, toolbelt=load_toolbelt(), facts=build_facts())


if __name__ == "__main__":  # pragma: no cover - console entry point
    raise SystemExit(main())
