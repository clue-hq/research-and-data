"""Conversation compaction for every governed agent (founder rulings 2026-09-29).

Every agent built by :class:`~clue_agents.runtime.DeepAgentTurnRuntime` gets our summariser and the
``compact_conversation`` tool. Two rules keep that true:

* **Ours is a distinct class.** deepagents' own summariser is removed by one harness profile that
  excludes it by *exact class*; exclusion by class never matches a subclass, so ours survives.
  Excluding by the name string ``"SummarizationMiddleware"`` would match ours too (it inherits the
  public alias), so this module never does that.
* **It is sized from the model's real context window** (:mod:`clue_gateway.model_windows`), with a
  fixed fallback when the window is unknown — never an unlimited agent.

Offloaded history and oversized tool arguments are written under ``/work/``: deepagents roots them
at ``/`` for any backend that is not its ``CompositeBackend``, and ``/`` is not a writable prefix of
any profile, while ``work`` is for every role that can write files at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from deepagents.middleware.summarization import (
    SummarizationToolMiddleware,
    _DeepAgentsSummarizationMiddleware,
)
from deepagents.profiles import HarnessProfile, register_harness_profile

__all__ = [
    "GOVERNED_PROVIDER_KEY",
    "ClueSummarizationMiddleware",
    "CompactionSettings",
    "HistoryPathBackend",
    "build_compaction_middleware",
    "register_governed_harness_profile",
]

#: The provider name ``GovernedAgentChatModel`` reports (``_get_ls_params``); the harness profile
#: that removes deepagents' default summariser is registered under exactly this key.
GOVERNED_PROVIDER_KEY = "clue-openrouter-agent"


@dataclass(frozen=True)
class CompactionSettings:
    """When a conversation is compacted, and how much of it is kept whole."""

    trigger_fraction: float
    keep_fraction: float
    trigger_tokens: int
    keep_messages: int
    context_window: int | None

    @classmethod
    def fallback(cls) -> CompactionSettings:
        """The thresholds used when a caller supplies none (and the window is unknown)."""
        return cls(0.90, 0.10, 170_000, 6, None)


class ClueSummarizationMiddleware(_DeepAgentsSummarizationMiddleware):
    """deepagents' summariser under our own class (see the module docstring)."""

    @property
    def name(self) -> str:
        return "ClueSummarizationMiddleware"


class HistoryPathBackend:
    """The agent's backend, with deepagents' root-level offload folders moved under ``/work/``."""

    _MOVED = ("/conversation_history/", "/large_tool_results/")

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    @classmethod
    def remap(cls, path: str) -> str:
        return f"/work{path}" if path.startswith(cls._MOVED) else path

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def download_files(self, paths: list[str]) -> Any:
        return self._inner.download_files([self.remap(path) for path in paths])

    async def adownload_files(self, paths: list[str]) -> Any:
        return await self._inner.adownload_files([self.remap(path) for path in paths])

    def upload_files(self, files: list[tuple[str, bytes]]) -> Any:
        return self._inner.upload_files([(self.remap(path), data) for path, data in files])

    async def aupload_files(self, files: list[tuple[str, bytes]]) -> Any:
        return await self._inner.aupload_files([(self.remap(path), data) for path, data in files])

    def write(self, file_path: str, content: str) -> Any:
        return self._inner.write(self.remap(file_path), content)

    async def awrite(self, file_path: str, content: str) -> Any:
        return await self._inner.awrite(self.remap(file_path), content)

    def edit(self, file_path: str, *args: Any, **kwargs: Any) -> Any:
        return self._inner.edit(self.remap(file_path), *args, **kwargs)

    async def aedit(self, file_path: str, *args: Any, **kwargs: Any) -> Any:
        return await self._inner.aedit(self.remap(file_path), *args, **kwargs)


def build_compaction_middleware(
    model: Any, backend: Any, settings: CompactionSettings, *, history_under_work: bool = True
) -> tuple[ClueSummarizationMiddleware, SummarizationToolMiddleware]:
    """Our summariser and the ``compact_conversation`` tool, sized from ``settings``.

    ``history_under_work=False`` keeps offloaded history at deepagents' own root paths, for a
    backend that already admits them (the design agent's session workspace admits exactly its own
    ``/conversation_history/<session>.md``).
    """
    trigger: tuple[Literal["tokens"], int]
    keep: tuple[Literal["tokens"], int] | tuple[Literal["messages"], int]
    if settings.context_window is not None:
        trigger = ("tokens", int(settings.context_window * settings.trigger_fraction))
        keep = ("tokens", int(settings.context_window * settings.keep_fraction))
    else:
        trigger = ("tokens", settings.trigger_tokens)
        keep = ("messages", settings.keep_messages)
    # ``backend`` arrives untyped (deepagents' backend objects); the wrapper forwards to it.
    history_backend: Any = (
        HistoryPathBackend(backend) if backend is not None and history_under_work else backend
    )
    summariser = ClueSummarizationMiddleware(
        model=model,
        backend=history_backend,
        trigger=trigger,
        keep=keep,
        # The summary is built from the whole evicted part (founder ruling 2026-09-29), not
        # LangChain's default of only its last 4,000 tokens. The evicted part is bounded by the
        # trigger, so it always fits the same model's window.
        trim_tokens_to_summarize=None,
    )
    # ``system_prompt=None``: the tool is registered and callable, but no nudge is appended to the
    # system prompt, so every agent's prompt stays byte-identical (prompt cache, manual size).
    return summariser, SummarizationToolMiddleware(summarization=summariser, system_prompt=None)


def register_governed_harness_profile() -> None:
    """Remove deepagents' default summariser from our governed agents — by exact class only."""
    register_harness_profile(
        GOVERNED_PROVIDER_KEY,
        HarnessProfile(excluded_middleware=frozenset({_DeepAgentsSummarizationMiddleware})),
    )
