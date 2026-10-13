"""Research turns send the identity prompt once.

Production 2026-10-06: every research call carried the profile prompt and resource map twice:
as the system message (runtime.py) and again as SystemMessage messages[0] from the L1
identity layer; a reconciliation continuation appended a third copy after the history.
"""

from langchain_core.messages import HumanMessage, SystemMessage

from clue_agents.ports import AssembledAgentContext
from clue_api.quality_research_wiring import drop_identity_echo


def _ctx(messages):
    return AssembledAgentContext.model_construct(
        manifest=None, messages=tuple(messages), materializations=(), continuation=None
    )


def test_the_identity_system_message_is_removed_and_only_it():
    identity = "PROMPT\n\nRESOURCE MAP"
    ctx = _ctx([SystemMessage(identity), SystemMessage("Pinned context card"), HumanMessage("go")])
    out = drop_identity_echo(ctx, identity)
    assert [m.content for m in out.messages] == ["Pinned context card", "go"]


def test_no_identity_message_is_a_no_op():
    ctx = _ctx([HumanMessage("go")])
    assert drop_identity_echo(ctx, "PROMPT") is ctx


def test_a_human_message_with_the_same_text_is_kept():
    identity = "PROMPT"
    ctx = _ctx([HumanMessage(identity)])
    assert drop_identity_echo(ctx, identity).messages == ctx.messages
