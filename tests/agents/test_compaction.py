"""Conversation compaction for every governed agent (founder rulings 2026-09-29)."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from clue_agents.compaction import (
    GOVERNED_PROVIDER_KEY,
    ClueSummarizationMiddleware,
    CompactionSettings,
    HistoryPathBackend,
    build_compaction_middleware,
    register_governed_harness_profile,
)
from clue_config.gateway import GatewayConfig
from clue_gateway.agent_model import GovernedAgentChatModel


def _settings(window: int | None) -> CompactionSettings:
    return CompactionSettings(
        trigger_fraction=0.90,
        keep_fraction=0.10,
        trigger_tokens=170_000,
        keep_messages=6,
        context_window=window,
    )


def _fake() -> FakeMessagesListChatModel:
    return FakeMessagesListChatModel(responses=[AIMessage(content="ok")])


def _governed() -> GovernedAgentChatModel:
    return GovernedAgentChatModel(
        models=(_fake(),),
        model_ids=("x-ai/grok-4.6",),
        requested_model="x-ai/grok-4.6",
        gateway_config=GatewayConfig(),
    )


def test_a_known_window_compacts_at_the_fraction() -> None:
    summariser, tool = build_compaction_middleware(_fake(), None, _settings(500_000))
    assert isinstance(summariser, ClueSummarizationMiddleware)
    assert summariser._lc_helper.trigger == ("tokens", 450_000)
    assert summariser._lc_helper.keep == ("tokens", 50_000)
    assert type(tool).__name__ == "SummarizationToolMiddleware"


def test_the_summary_is_built_from_the_whole_evicted_part() -> None:
    """Founder ruling 2026-09-29: not just its last 4,000 tokens (LangChain's hidden default)."""
    for window in (500_000, None):
        summariser, _ = build_compaction_middleware(_fake(), None, _settings(window))
        assert summariser._lc_helper.trim_tokens_to_summarize is None


def test_an_unknown_window_uses_the_fixed_fallback_never_unlimited() -> None:
    summariser, _ = build_compaction_middleware(_fake(), None, _settings(None))
    assert summariser._lc_helper.trigger == ("tokens", 170_000)
    assert summariser._lc_helper.keep == ("messages", 6)


def test_offloaded_files_go_under_work() -> None:
    assert (
        HistoryPathBackend.remap("/conversation_history/abc.md")
        == "/work/conversation_history/abc.md"
    )
    assert HistoryPathBackend.remap("/large_tool_results/t1") == "/work/large_tool_results/t1"
    assert HistoryPathBackend.remap("/work/notes.md") == "/work/notes.md"


def test_the_governed_model_names_its_provider_explicitly() -> None:
    from deepagents._models import get_model_provider

    assert get_model_provider(_governed()) == GOVERNED_PROVIDER_KEY


def _stack_of(model: Any, middleware: list[Any]) -> list[Any]:
    """The final middleware stack ``create_deep_agent`` hands LangChain's ``create_agent``."""
    import deepagents.graph as graph

    captured: dict[str, Any] = {}
    real = graph.create_agent

    def spy(*args: Any, **kwargs: Any) -> Any:
        captured["middleware"] = list(kwargs["middleware"])
        return real(*args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(graph, "create_agent", spy)
        graph.create_deep_agent(model=model, middleware=middleware)
    return captured["middleware"]


def test_every_governed_agent_has_exactly_our_summariser() -> None:
    """Founder ruling 2026-09-29: no harness profile may disable or replace our summariser."""
    from deepagents.middleware.summarization import SummarizationMiddleware

    register_governed_harness_profile()
    model = _governed()
    summariser, tool = build_compaction_middleware(model, None, _settings(500_000))
    stack = _stack_of(model, [summariser, tool])
    assert [type(m) for m in stack if isinstance(m, SummarizationMiddleware)] == [
        ClueSummarizationMiddleware
    ]
    assert any(type(m).__name__ == "SummarizationToolMiddleware" for m in stack)


class _RecordingBackend:
    """Records where bytes land; nothing exists before the first write."""

    def __init__(self) -> None:
        self.written: dict[str, str] = {}

    def download_files(self, paths: list[str]) -> list[Any]:
        raise FileNotFoundError(paths[0])

    def write(self, file_path: str, content: str) -> Any:
        self.written[file_path] = content

        class _Ok:
            error = None

        return _Ok()


def test_the_summary_names_the_path_the_history_was_written_to() -> None:
    """Spec §12 / WS-4: the summary tells the agent where its history is, so that path must be
    the one the bytes sit at — under ``/work/``, which the agent can read and the snapshot saves.
    """
    from langchain_core.messages import HumanMessage

    backend = _RecordingBackend()
    summariser, _ = build_compaction_middleware(_fake(), backend, _settings(500_000))
    named = summariser._offload_to_backend(summariser._backend, [HumanMessage(content="hi")])
    assert named is not None
    assert named.startswith("/work/conversation_history/")
    assert list(backend.written) == [named]
    summary = summariser._build_new_messages_with_path("s", named)[0]
    assert named in str(summary.content)
