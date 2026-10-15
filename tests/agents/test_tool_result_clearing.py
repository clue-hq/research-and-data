"""Research agents clear processed tool results in batches without breaking the prompt cache.

Production 2026-10-06: research conversations grew from ~16k to ~200k tokens and every call
re-sent all of it (82% of model cost). Clearing one result per round (LangChain's stock edit)
would move the cleared boundary every call and bill the tail uncached; the cut here moves only
in steps, so the prompt prefix is byte-identical between steps.
"""

import asyncio
from types import SimpleNamespace

import pytest
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


def test_boundary_holds_when_the_protected_rounds_slide_forward():
    """Review I5: uneven rounds. The newest two rounds sliding past an older result must not
    clear it before the next crossing; that would bill everything after it uncached."""
    messages = [HumanMessage("go")]
    for i, tokens in enumerate((5_000, 20_000, 20_000, 80_000)):
        messages += _round(i, tokens * 4)
    first = plan_clearing(messages, trigger=TRIGGER, target=TARGET)
    messages += _round(4, 1_000 * 4)  # a small round: no threshold crossing
    assert plan_clearing(messages, trigger=TRIGGER, target=TARGET) == first


def _counted(messages, ratio):
    """Mark the newest reply as the provider having counted its request at ``ratio`` real tokens
    per estimated token (what the summariser records on every reply)."""
    from clue_agents.context_tokens import PROMPT_ESTIMATE_KEY

    reply = next(m for m in reversed(messages) if isinstance(m, AIMessage))
    reply.response_metadata[PROMPT_ESTIMATE_KEY] = 100_000
    reply.usage_metadata = {
        "input_tokens": int(100_000 * ratio),
        "output_tokens": 1,
        "total_tokens": int(100_000 * ratio) + 1,
    }
    return messages


def test_clearing_counts_the_models_real_tokens():
    """~120k estimated tokens is only ~60k real for a model the estimate overcounts 2x."""
    assert plan_clearing(_conversation(12), trigger=TRIGGER, target=TARGET)
    overcounted = _counted(_conversation(12), 0.5)
    assert plan_clearing(overcounted, trigger=TRIGGER, target=TARGET) == []
    undercounted = _counted(_conversation(8), 1.5)  # ~80k estimated, ~120k real
    assert plan_clearing(undercounted, trigger=TRIGGER, target=TARGET)


def test_the_system_prompt_and_tool_schemas_count_toward_the_trigger():
    """The provider is sent them on every call, so they are part of the conversation's size."""
    from langchain_core.messages import SystemMessage

    messages = _conversation(9)  # ~90k tokens of messages: under the trigger alone
    assert plan_clearing(messages, trigger=TRIGGER, target=TARGET) == []
    system = SystemMessage("s" * 60_000)  # ~15k
    tools = [{"name": "read_file", "description": "d" * 40_000, "parameters": {}}]  # ~10k
    assert plan_clearing(
        messages, trigger=TRIGGER, target=TARGET, system_message=system, tools=tools
    )

    seen = {}

    async def handler(request):
        seen["messages"] = request.messages
        return "ok"

    request = _Request(messages)
    request.system_message, request.tools = system, tools
    middleware = BatchedToolResultClearing(trigger_tokens=TRIGGER, target_tokens=TARGET)
    asyncio.run(middleware.awrap_model_call(request, handler))
    assert any(
        isinstance(m, ToolMessage) and m.content.startswith("[Earlier result removed")
        for m in seen["messages"]
    )


#: One run-6 agent's model calls (2026-10-13, GPT-6.1-Sol): our estimate of each request and the
#: provider's real input tokens for it. The rate starts near 0.79 (system prompt and task only),
#: settles near 0.98 once tool output dominates, and drifts to ~0.91 after clearing.
_RUN6_CALLS = [
    (14650, 11577), (14745, 11635), (30072, 24613), (40197, 35641), (40444, 35803),
    (40911, 36317), (50062, 48731), (58918, 57740), (63237, 61561), (70439, 69354),
    (73910, 73101), (74775, 73833), (79640, 78627), (93129, 90993), (93268, 91149),
    (104866, 102469), (112707, 110331), (124076, 122507), (132979, 131447), (138553, 136171),
    (138802, 136333), (150084, 147824), (150769, 148004), (158262, 155396), (141720, 131988),
    (146848, 136040), (148126, 136275), (149029, 136527), (152871, 139884), (157510, 143967),
    (162288, 147059), (166182, 150160), (170127, 153159), (172755, 154474), (173502, 155187),
    (174404, 155353), (176756, 157569), (177078, 158041), (183438, 167749), (186469, 169856),
    (188237, 172546), (190032, 173957),
]  # fmt: skip


def _replay(seed: int):
    """Grow a conversation one round per real call, each reply carrying that call's real counts;
    yield (call index, messages, newest real rate) after every round."""
    import random

    from clue_agents.context_tokens import PROMPT_ESTIMATE_KEY

    rng = random.Random(seed)
    messages = [HumanMessage("go " + "s" * 40_000)]
    for i, (estimate, real) in enumerate(_RUN6_CALLS):
        reply = AIMessage("", tool_calls=[{"id": f"c{i}", "name": "read_file", "args": {}}])
        reply.response_metadata[PROMPT_ESTIMATE_KEY] = estimate
        reply.usage_metadata = {"input_tokens": real, "output_tokens": 1, "total_tokens": real + 1}
        content = "x" * rng.randint(4_000, 40_000)
        messages += [reply, ToolMessage(content, tool_call_id=f"c{i}", name="read_file")]
        yield i, messages, real / estimate


def test_the_cut_never_moves_back_while_the_measured_rate_drifts():
    """Run 6 (2026-10-13): clearing re-scaled every message by the newest reply's rate, so as
    the rate drifted the result at the cut was cleared on one call and restored on the next.
    Each flip changed a message ~90 places back, beyond GPT-5.6's cache lookup points, and Sol
    re-wrote ~130k tokens for it (11 such misses, ~$3.70). The cleared set may only grow."""
    for seed in range(40):
        previous: list[str] = []
        for i, messages, _rate in _replay(seed):
            cleared = plan_clearing(messages, trigger=160_000, target=110_000)
            assert cleared[: len(previous)] == previous, f"seed {seed}: call {i} restored a result"
            previous = cleared


def test_clearing_starts_within_ten_percent_of_the_real_trigger():
    """The anchored rate keeps the trigger in real tokens: the first cut happens when the history
    really is about 160k tokens, not 13% later (the first reply's 0.79 rate) or earlier."""
    from clue_agents.context_tokens import estimate_tokens

    for seed in range(40):
        for _i, messages, rate in _replay(seed):
            if plan_clearing(messages, trigger=160_000, target=110_000):
                real_total = estimate_tokens(messages) * rate
                assert 0.9 * 160_000 <= real_total <= 1.1 * 160_000, (seed, round(real_total))
                break
        else:
            raise AssertionError(f"seed {seed}: clearing never started")


def test_trigger_zero_turns_clearing_off_and_keeps_the_gutter_strip():
    """Clearing off (Sol pricing: a cut re-write costs more than re-reading ever saves): the
    model sees every result, and read results still lose their line-number gutter."""
    messages = _conversation(12)  # far past any trigger
    seen = {}

    async def handler(request):
        seen["messages"] = request.messages
        return "ok"

    middleware = BatchedToolResultClearing(trigger_tokens=0, target_tokens=TARGET)
    assert not middleware.clearing_enabled
    asyncio.run(middleware.awrap_model_call(_Request(messages), handler))
    assert seen["messages"] is messages

    async def read(request):
        return ToolMessage(content="     1\tline one\n     2\tline two", tool_call_id="r")

    request = SimpleNamespace(
        tool_call={"name": "read_file", "id": "r", "args": {"file_path": "/research/a.json"}}
    )
    assert asyncio.run(middleware.awrap_tool_call(request, read)).content == "line one\nline two"
    with pytest.raises(ValueError, match="0 \\(off\\) or positive"):
        BatchedToolResultClearing(trigger_tokens=-1, target_tokens=TARGET)
    with pytest.raises(ValueError, match="must exceed"):
        BatchedToolResultClearing(trigger_tokens=TARGET, target_tokens=TARGET)
