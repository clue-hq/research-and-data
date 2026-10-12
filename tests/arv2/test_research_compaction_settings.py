"""Recipe 26 research compacts at a fixed 150k backstop; earlier recipes keep the shared rule.

Production 2026-10-06: the shared rule (90% of Grok 4.6's 500k window = 450k) never fired on
research conversations, which peaked around 205k tokens.
"""

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from clue_agents.compaction import build_compaction_middleware
from clue_api.agent_compaction import compaction_for
from clue_api.quality_research_wiring import research_compaction_for
from clue_config import Settings


class _Scope:
    def __init__(self, version):
        self.input_refs = {"quality_recipe_version": version}


def test_recipe_26_research_compacts_at_the_research_backstop():
    settings = Settings(_env_file=None)
    chosen = research_compaction_for(_Scope(26), settings)("x-ai/grok-4.6")
    assert chosen.context_window is None
    assert chosen.trigger_tokens == settings.arv2_research_compact_trigger_tokens == 240_000
    summariser, _ = build_compaction_middleware(
        FakeMessagesListChatModel(responses=[AIMessage("s")]), None, chosen
    )
    assert summariser._lc_helper.trigger == ("tokens", 240_000)
    assert summariser._lc_helper.keep == ("messages", 40)


def test_recipe_25_research_keeps_the_shared_rule():
    assert research_compaction_for(_Scope(25), Settings(_env_file=None)) is compaction_for
