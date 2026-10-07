"""Research agents clear processed tool results in batches without breaking the prompt cache.

Production 2026-10-06: research conversations grew from ~16k to ~200k tokens and every call
re-sent all of it (82% of model cost). Clearing one result per round (LangChain's stock edit)
would move the cleared boundary every call and bill the tail uncached; the cut here moves only
in steps, so the prompt prefix is byte-identical between steps.
"""

import asyncio

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from clue_agents.tool_result_clearing import (
    BatchedToolResultClearing,
    plan_clearing,
    strip_read_gutter,
)

TRIGGER, TARGET = 100_000, 50_000


def _round(i, chars, path=None, name="read_file", status="success"):
    args = {"file_path": path or f"/research/operations/{i}/0.json"}
    call = {"id": f"c{i}", "name": name, "args": args}
    return [
        AIMessage("", tool_calls=[call]),
        ToolMessage("x" * chars, tool_call_id=f"c{i}", name=name, status=status),
    ]


def _conversation(rounds, chars=40_000):
    return [HumanMessage("go")] + sum((_round(i, chars) for i in range(rounds)), [])


def test_nothing_clears_under_the_trigger():
    assert plan_clearing(_conversation(2, 4000), trigger=TRIGGER, target=TARGET) == []


def test_crossing_clears_the_oldest_and_never_the_newest_two_rounds():
    cleared = plan_clearing(_conversation(12), trigger=TRIGGER, target=TARGET)  # ~120k tokens
    assert cleared and cleared[0] == "c0"
    assert "c10" not in cleared and "c11" not in cleared
    assert cleared == [f"c{i}" for i in range(len(cleared))]  # oldest first, contiguous


def test_boundary_is_stable_between_crossings():
    messages = _conversation(12)
    first = plan_clearing(messages, trigger=TRIGGER, target=TARGET)
    messages = messages + _round(12, 4_000)  # small growth, same step
    assert plan_clearing(messages, trigger=TRIGGER, target=TARGET) == first


def test_the_next_step_clears_more_and_keeps_the_earlier_set():
    first = plan_clearing(_conversation(12), trigger=TRIGGER, target=TARGET)
    later = plan_clearing(_conversation(18), trigger=TRIGGER, target=TARGET)
    assert later[: len(first)] == first and len(later) > len(first)


def test_skill_reads_and_failed_results_are_never_cleared():
    messages = [HumanMessage("go")]
    for i in range(12):
        messages += _round(i, 40_000, path=f"/.deepagent/skills/a/v{i}/SKILL.md")
    assert plan_clearing(messages, trigger=TRIGGER, target=TARGET) == []
    failed = [HumanMessage("go")] + sum((_round(i, 40_000, status="error") for i in range(12)), [])
    assert plan_clearing(failed, trigger=TRIGGER, target=TARGET) == []


def test_gutter_is_stripped_and_content_kept():
    raw = '     1\t{\n     2\t  "a": 1\n    12.1\tcontinued'
    assert strip_read_gutter(raw) == '{\n  "a": 1\ncontinued'
    assert strip_read_gutter("no gutter here") == "no gutter here"


class _Request:
    def __init__(self, messages):
        self.messages = messages

    def override(self, *, messages):
        return _Request(messages)


def test_the_model_sees_placeholders_naming_the_path_and_state_is_untouched():
    messages = _conversation(12)
    original = [m.content for m in messages]
    seen = {}

    async def handler(request):
        seen["messages"] = request.messages
        return "ok"

    middleware = BatchedToolResultClearing(trigger_tokens=TRIGGER, target_tokens=TARGET)
    asyncio.run(middleware.awrap_model_call(_Request(messages), handler))
    first = next(m for m in seen["messages"] if isinstance(m, ToolMessage))
    assert "/research/operations/0/0.json" in first.content and "x" * 100 not in first.content
    assert [m.content for m in messages] == original  # the checkpointed history is not edited
