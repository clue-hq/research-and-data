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


#: The real-token rate (provider input tokens / character estimate) one run-6 agent measured on
#: its successive calls: it drifts from ~1.08 to ~0.93 as tool output fills the conversation.
_RUN6_RATES = [
    1.0823, 1.0844, 1.0812, 1.0815, 1.1404, 1.1193, 1.1012, 1.099, 1.098, 1.0947,
    1.0874, 1.0605, 1.0606, 1.0506, 1.047, 1.0494, 1.0462, 1.0377, 1.037, 1.0355,
    1.0318, 1.0296, 0.9821, 0.9751, 0.9679, 0.9635, 0.9611, 0.9586, 0.949, 0.9453,
    0.9408, 0.9338, 0.9339, 0.9299, 0.93, 0.931, 0.9525, 0.9482, 0.9538, 0.9521,
]  # fmt: skip


def test_the_cut_never_moves_back_while_the_measured_rate_drifts():
    """Run 6 (2026-10-13): clearing re-scaled every message by the newest reply's rate, so as
    the rate drifted the result at the cut was cleared on one call and restored on the next.
    Each flip changed a message ~90 places back, beyond GPT-5.6's cache lookup points, and Sol
    re-wrote ~130k tokens for it (11 such misses, ~$3.70). The cleared set may only grow."""
    import random

    from clue_agents.context_tokens import PROMPT_ESTIMATE_KEY

    for seed in range(40):
        rng = random.Random(seed)
        messages = [HumanMessage("go " + "s" * 40_000)]
        previous: list[str] = []
        for i, rate in enumerate(_RUN6_RATES):
            reply = AIMessage("", tool_calls=[{"id": f"c{i}", "name": "read_file", "args": {}}])
            reply.response_metadata[PROMPT_ESTIMATE_KEY] = 100_000
            reply.usage_metadata = {
                "input_tokens": int(100_000 * rate),
                "output_tokens": 1,
                "total_tokens": 1,
            }
            content = "x" * rng.randint(4_000, 40_000)
            messages += [reply, ToolMessage(content, tool_call_id=f"c{i}", name="read_file")]
            cleared = plan_clearing(messages, trigger=160_000, target=110_000)
            assert cleared[: len(previous)] == previous, f"seed {seed}: call {i} restored a result"
            previous = cleared
