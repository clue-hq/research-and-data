"""Model ids in tests: well-formed, never a particular model.

Which model a role, a judge or a synthesis step uses is a deployment setting (the
``<ROLE>_AGENT_MODEL`` / ``CLUE_*_MODEL`` env lines), so no test asserts that a default or a
catalog pin names one model or another (founder ruling 2026-09-17). What a test may check is the
SHAPE of the id, because a malformed pin is a real defect: the design profile once carried
``openai/x-ai/grok-4.6``, a doubled vendor prefix no provider knows, and only the env override
kept the design leg's exit judge building.
"""

from __future__ import annotations

import re

#: An OpenRouter-routed id: exactly one vendor segment, then the model name.
ROUTED_MODEL_ID = re.compile(r"^[a-z0-9-]+/[A-Za-z0-9][A-Za-z0-9._:-]*$")
#: A provider-native id (e.g. a Gemini transcription model addressed without a vendor).
NATIVE_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


def assert_well_formed_model_id(value: object, *, routed: bool = True) -> None:
    """``value`` is a non-empty id of the expected shape; a doubled vendor prefix fails."""

    assert isinstance(value, str) and value.strip() == value and value, repr(value)
    pattern = ROUTED_MODEL_ID if routed else NATIVE_MODEL_ID
    assert pattern.fullmatch(value), f"malformed model id: {value!r}"
