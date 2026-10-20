# Head of ABM continuation, prompt caching and compaction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Head-of-ABM chat turns resume the thread's previous agent state (append-only, cache-friendly, tool history kept), and every governed agent compacts its conversation once, model-aware, with our own summariser that no harness profile can disable.

**Architecture:** Two independent halves joined at the runtime. (1) Compaction: `DeepAgentTurnRuntime` (the single `create_deep_agent` call) adds our `ClueSummarizationMiddleware` + `compact_conversation` to every governed agent, sized from the model's real context window; one harness profile removes deepagents' default by exact class. (2) Continuation: the Head-of-ABM conversation engine finds the thread's last completed turn, passes its checkpoint to the existing `continuation_config` path, and the context assembler emits only gap messages + this turn's cards + the user message.

**Tech Stack:** Python 3.12, deepagents 0.6.12 / LangChain agents middleware, LangGraph Postgres checkpointer, SQLAlchemy async, pydantic-settings, pytest (DB suites on the lane's throwaway DB).

**Spec:** `docs/superpowers/specs/archive/2026-09-29-head-of-abm-continuation-and-compaction-design.md`

## Global Constraints

- Every new setting goes into `.env.example` with its default **when introduced** (parity rule); dubai `.env` kept in parity.
- Compaction defaults: trigger fraction `0.90`, keep fraction `0.10`, window from OpenRouter catalogue, override `CLUE_AGENT_CONTEXT_WINDOW_TOKENS`; unknown window → `170000` tokens trigger, keep `6` messages.
- `CLUE_HEAD_OF_ABM_CONTINUATION_ENABLED` defaults `true`.
- No harness profile may disable or replace our summariser: exclude deepagents' default by **exact class** only; never exclude by the string `"SummarizationMiddleware"`.
- Agent catalog is versioned and hash-pinned: never edit an existing profile/skill/manual version; mint new ones (`make manual` regenerates generated chapters).
- Tests never assert which model a default names (`tests/_model_ids.py` rule).
- Never run broad suites with real keys; run tests via the lane runner that does not load `.env` (DB = `clue_dubai_prov`).
- Commits: local, no AI attribution; push only when the founder asks.

## Review Focus

1. **A harness profile silently removing our summariser** (e.g. a future deepagents built-in profile excluding by name) — expected: the guard test fails the build. Test: Task 2 Step 1 (`test_every_governed_agent_has_exactly_our_summariser`).
2. **A thread whose last Head-of-ABM turn was stopped, failed, or is a design-leg turn** — expected: resume from the last *completed* Head-of-ABM turn; the others arrive as gap messages, in order. Test: Task 4 Step 1.
3. **Profile upgraded between turns (v68 → v69)** — expected: that turn rebuilds (no continuation), next turn continues. Test: Task 6 Step 1.
4. **Crash mid-turn then redelivery** — expected: the retry continues its own half-run state without duplicating history. Test: Task 7 Step 3.
5. **OpenRouter catalogue unreachable or model missing** — expected: fixed 170k / keep-6 fallback, never unlimited, never a start-up failure. Test: Task 1 Step 1.

---

## File Structure

- Create `platform/agents/clue_agents/compaction.py` — `CompactionSettings`, `ClueSummarizationMiddleware`, `HistoryPathBackend`, `build_compaction_middleware`, `register_governed_harness_profile`.
- Create `libs/clue-gateway/clue_gateway/model_windows.py` — `resolve_context_window(model_id, override)` (OpenRouter catalogue, cached).
- Modify `platform/agents/clue_agents/runtime.py` — `_FRAMEWORK_TOOL_NAMES` + `compact_conversation`; `DeepAgentTurnRuntime(compaction=...)`; add our middleware to `create_deep_agent`.
- Modify `libs/clue-config/clue_config/settings.py`, `.env.example`, `.env`.
- Create `platform/api/clue_api/conversation_continuation.py` — `ResumePoint`, `find_resume_point`, `gap_history`.
- Modify `platform/agents/clue_agents/context.py` — `DeterministicAgentContextAssembler.assemble(..., continuation=)`.
- Modify `platform/agents/clue_agents/contracts.py` — `ContinuationRef` on `AssembledAgentContext` manifest payload.
- Modify `platform/api/clue_api/conversation_turns.py`, `platform/api/clue_api/head_of_abm_wiring.py` — pass resume point / `continuation_config`.
- Catalog: `platform/agents/catalog/profiles/head-of-abm/v69/`, `skills/stage0-interview/v42/`, `skills/manual-*/v15/`, `platform/agents/clue_agents/manual/build.py`, `platform/api/clue_api/agent_registry_wiring.py`, `platform/api/clue_api/chat/composer_context.py`.
- Create `scripts/turn_cache_report.py`.
- Tests: `tests/agents/test_compaction.py`, `tests/gateway/test_model_windows.py`, `tests/api/test_conversation_continuation_db.py`, `tests/agents/test_context_continuation.py`, updates in `tests/agents/test_catalog.py`, `tests/api/test_agent_registry_wiring.py`, `tests/agents/test_manual_builder.py`, `tests/api/test_client_knowledge_privacy_s4e.py`, `tests/api/test_comprehensive_research_contract.py`.

Test runner (does not load `.env`): `bash $SCRATCH/tdubai.sh <abs test paths> -q -p no:randomly` (see `_memory/2026-09-29-stuck-design-leg-incident.md`); path-sensitive tests run from the repo root with `.venv/bin/python -m pytest`.

---

### Task 1: Settings and the model context-window resolver

**Files:**
- Create: `libs/clue-gateway/clue_gateway/model_windows.py`
- Modify: `libs/clue-config/clue_config/settings.py` (next to `head_of_abm_max_model_rounds`, ~line 415), `.env.example` (next to `CLUE_HEAD_OF_ABM_MAX_MODEL_ROUNDS`, ~line 189), `.env`
- Test: `tests/gateway/test_model_windows.py`, `tests/test_config_settings.py`

**Interfaces:**
- Produces: `resolve_context_window(model_id: str, *, override: int | None, fetch: Callable[[], Mapping[str, int]] | None = None) -> int | None`; settings fields `agent_context_window_tokens: int | None`, `agent_compact_trigger_fraction: float`, `agent_compact_keep_fraction: float`, `agent_compact_trigger_tokens: int`, `agent_compact_keep_messages: int`, `head_of_abm_continuation_enabled: bool`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/gateway/test_model_windows.py
from clue_gateway.model_windows import resolve_context_window, _reset_cache


def setup_function() -> None:
    _reset_cache()


def test_the_catalogue_names_the_window() -> None:
    assert resolve_context_window("x-ai/grok-4.6", override=None,
                                  fetch=lambda: {"x-ai/grok-4.6": 500_000}) == 500_000


def test_an_override_wins_over_the_catalogue() -> None:
    assert resolve_context_window("x-ai/grok-4.6", override=200_000,
                                  fetch=lambda: {"x-ai/grok-4.6": 500_000}) == 200_000


def test_an_unknown_model_or_unreachable_catalogue_is_none_never_a_failure() -> None:
    assert resolve_context_window("x-ai/none", override=None, fetch=lambda: {}) is None

    def boom() -> dict[str, int]:
        raise OSError("catalogue down")

    _reset_cache()
    assert resolve_context_window("x-ai/grok-4.6", override=None, fetch=boom) is None
```

Append to `tests/test_config_settings.py`:

```python
def test_compaction_and_continuation_defaults() -> None:
    s = Settings(_env_file=None)
    assert s.agent_context_window_tokens is None
    assert s.agent_compact_trigger_fraction == 0.90
    assert s.agent_compact_keep_fraction == 0.10
    assert s.agent_compact_trigger_tokens == 170_000
    assert s.agent_compact_keep_messages == 6
    assert s.head_of_abm_continuation_enabled is True
```

- [ ] **Step 2: Run to verify they fail**

Run: `bash $SCRATCH/tdubai.sh $PWD/tests/gateway/test_model_windows.py "$PWD/tests/test_config_settings.py::test_compaction_and_continuation_defaults" -q`
Expected: FAIL (`ModuleNotFoundError: clue_gateway.model_windows`, `AttributeError`).

- [ ] **Step 3: Implement**

```python
# libs/clue-gateway/clue_gateway/model_windows.py
"""A model's context window, from OpenRouter's public model catalogue (no key needed).

Compaction sizes itself from this number (founder ruling 2026-09-29). It is read once per
process and cached; a missing model or an unreachable catalogue answers ``None`` so the caller
falls back to fixed thresholds — never an unlimited agent, never a start-up failure.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable, Mapping

from clue_obs import get_logger

log = get_logger("clue_gateway.model_windows")

_CATALOGUE_URL = "https://openrouter.ai/api/v1/models"
_cache: Mapping[str, int] | None = None


def _reset_cache() -> None:
    global _cache
    _cache = None


def _fetch_catalogue() -> Mapping[str, int]:
    with urllib.request.urlopen(_CATALOGUE_URL, timeout=10) as response:  # noqa: S310
        body = json.loads(response.read())
    return {
        str(item["id"]): int(item["context_length"])
        for item in body.get("data", [])
        if isinstance(item, dict) and item.get("id") and item.get("context_length")
    }


def resolve_context_window(
    model_id: str,
    *,
    override: int | None,
    fetch: Callable[[], Mapping[str, int]] | None = None,
) -> int | None:
    if override is not None:
        return override
    global _cache
    if _cache is None:
        try:
            _cache = dict((fetch or _fetch_catalogue)())
        except Exception:  # noqa: BLE001 — an unreachable catalogue is a fallback, not a failure
            log.warning("model_windows.catalogue_unavailable", exc_info=True)
            _cache = {}
    window = _cache.get(model_id)
    if window is None:
        log.warning("model_windows.window_unknown", model_id=model_id)
    return window
```

Settings (in `settings.py`, beside `head_of_abm_max_model_rounds`):

```python
    # Conversation compaction for every governed agent (founder ruling 2026-09-29). The model's
    # context window comes from OpenRouter's catalogue unless overridden; compaction starts at
    # TRIGGER_FRACTION of it and keeps the newest KEEP_FRACTION whole. With no known window the
    # fixed pair applies. Env: ``CLUE_AGENT_CONTEXT_WINDOW_TOKENS``,
    # ``CLUE_AGENT_COMPACT_TRIGGER_FRACTION``, ``CLUE_AGENT_COMPACT_KEEP_FRACTION``,
    # ``CLUE_AGENT_COMPACT_TRIGGER_TOKENS``, ``CLUE_AGENT_COMPACT_KEEP_MESSAGES``.
    agent_context_window_tokens: int | None = Field(default=None, ge=1)
    agent_compact_trigger_fraction: float = Field(default=0.90, gt=0, lt=1)
    agent_compact_keep_fraction: float = Field(default=0.10, gt=0, lt=1)
    agent_compact_trigger_tokens: int = Field(default=170_000, ge=1)
    agent_compact_keep_messages: int = Field(default=6, ge=1)
    # Head-of-ABM chat turns resume the thread's last completed turn (append-only prompt).
    # Env: ``CLUE_HEAD_OF_ABM_CONTINUATION_ENABLED``.
    head_of_abm_continuation_enabled: bool = True
```

`.env.example` and `.env` (same values):

```
# Conversation compaction, every governed agent (window from OpenRouter unless overridden).
CLUE_AGENT_CONTEXT_WINDOW_TOKENS=
CLUE_AGENT_COMPACT_TRIGGER_FRACTION=0.90
CLUE_AGENT_COMPACT_KEEP_FRACTION=0.10
CLUE_AGENT_COMPACT_TRIGGER_TOKENS=170000
CLUE_AGENT_COMPACT_KEEP_MESSAGES=6
# Head-of-ABM turns resume the thread's last completed turn (append-only, cache-friendly).
CLUE_HEAD_OF_ABM_CONTINUATION_ENABLED=true
```

Check `CLUE_AGENT_CONTEXT_WINDOW_TOKENS=` (blank) loads as `None` (the parity rule: a documented env line must load). If pydantic rejects the empty string, add a `field_validator(..., mode="before")` mapping `""` → `None`.

- [ ] **Step 4: Run to verify they pass** (same command). Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add libs/clue-gateway/clue_gateway/model_windows.py libs/clue-config/clue_config/settings.py .env.example tests/gateway/test_model_windows.py tests/test_config_settings.py
git commit -m "Resolve each model's context window and add compaction settings"
```

---

### Task 2: Our summariser in every governed agent, protected from harness profiles

**Files:**
- Create: `platform/agents/clue_agents/compaction.py`
- Modify: `platform/agents/clue_agents/runtime.py:45-55` (`_FRAMEWORK_TOOL_NAMES`), `:480-510` (`__init__`), `:601-630` (`create_deep_agent(...)`)
- Test: `tests/agents/test_compaction.py`

**Interfaces:**
- Consumes: Task 1 settings fields, `resolve_context_window`.
- Produces: `CompactionSettings(trigger_fraction, keep_fraction, trigger_tokens, keep_messages, context_window)`; `CompactionSettings.from_settings(settings, *, model_id) -> CompactionSettings`; `build_compaction_middleware(model, backend, settings) -> tuple[AgentMiddleware, AgentMiddleware]`; `register_governed_harness_profile() -> None`; `DeepAgentTurnRuntime(..., compaction: CompactionSettings | None = None)` (None = the fixed fallback thresholds, so every agent always gets our summariser).

- [ ] **Step 1: Write the failing tests**

```python
# tests/agents/test_compaction.py
from typing import Any

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from clue_agents.compaction import (
    ClueSummarizationMiddleware,
    CompactionSettings,
    HistoryPathBackend,
    build_compaction_middleware,
    register_governed_harness_profile,
)


def _settings(window: int | None) -> CompactionSettings:
    return CompactionSettings(
        trigger_fraction=0.90, keep_fraction=0.10,
        trigger_tokens=170_000, keep_messages=6, context_window=window,
    )


def test_a_known_window_compacts_at_the_fraction() -> None:
    model = FakeMessagesListChatModel(responses=[AIMessage(content="ok")])
    summariser, tool = build_compaction_middleware(model, backend=None, settings=_settings(500_000))
    assert isinstance(summariser, ClueSummarizationMiddleware)
    assert summariser.trigger == ("tokens", 450_000)
    assert summariser.keep == ("tokens", 50_000)
    assert type(tool).__name__ == "SummarizationToolMiddleware"


def test_an_unknown_window_uses_the_fixed_fallback_never_unlimited() -> None:
    model = FakeMessagesListChatModel(responses=[AIMessage(content="ok")])
    summariser, _ = build_compaction_middleware(model, backend=None, settings=_settings(None))
    assert summariser.trigger == ("tokens", 170_000)
    assert summariser.keep == ("messages", 6)


def test_history_is_offloaded_under_work() -> None:
    assert HistoryPathBackend.remap("/conversation_history/abc.md") == "/work/conversation_history/abc.md"
    assert HistoryPathBackend.remap("/work/notes.md") == "/work/notes.md"


def test_every_governed_agent_has_exactly_our_summariser() -> None:
    """Founder ruling 2026-09-29: no harness profile may disable or replace our summariser."""
    from deepagents import create_deep_agent
    from clue_gateway.agent_model import GovernedAgentChatModel

    register_governed_harness_profile()
    model = _governed_fake_model()  # GovernedAgentChatModel over a fake transport; see helper below
    summariser, tool = build_compaction_middleware(model, backend=None, settings=_settings(500_000))
    graph = create_deep_agent(model=model, middleware=[summariser, tool])
    stack = _middleware_instances(graph)
    assert [type(m) for m in stack if isinstance(m, SummarizationMiddleware)] == [
        ClueSummarizationMiddleware
    ]
    assert any(type(m).__name__ == "SummarizationToolMiddleware" for m in stack)
```

Helpers in the same file:
- `_governed_fake_model()` builds a `GovernedAgentChatModel` over a fake transport the way `tests/gateway/test_agent_model.py` does (import its helper, don't copy).
- `_middleware_instances(graph)` returns the middleware objects the compiled agent was built with. Find where LangChain's `create_agent` keeps them in 0.6.12 (read `langchain/agents/factory.py`) and read them from there. If they are not reachable from the compiled graph, patch `langchain.agents.factory.create_agent` in the test to capture its `middleware` argument instead.
- Import `SummarizationMiddleware` from `deepagents.middleware.summarization` for the `isinstance` check (the default and ours both subclass it, so the check catches both).

- [ ] **Step 2: Run to verify they fail**

Run: `bash $SCRATCH/tdubai.sh $PWD/tests/agents/test_compaction.py -q`
Expected: FAIL (`ModuleNotFoundError: clue_agents.compaction`).

- [ ] **Step 3: Implement `compaction.py`**

```python
# platform/agents/clue_agents/compaction.py
"""Conversation compaction for every governed agent (founder rulings 2026-09-29).

Our summariser is a distinct class so a harness profile that excludes deepagents' default *by exact
class* can never remove ours; excluding by the name string would match both, so we never do. The
evicted history goes under the already-writable ``work/`` prefix.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from deepagents.middleware.summarization import (
    SummarizationMiddleware,
    SummarizationToolMiddleware,
    _DeepAgentsSummarizationMiddleware,
)
from deepagents.profiles import HarnessProfile, register_harness_profile

GOVERNED_PROVIDER_KEY = "clue-openrouter-agent"


@dataclass(frozen=True)
class CompactionSettings:
    trigger_fraction: float
    keep_fraction: float
    trigger_tokens: int
    keep_messages: int
    context_window: int | None

    @classmethod
    def from_settings(cls, settings: Any, *, model_id: str) -> "CompactionSettings":
        from clue_gateway.model_windows import resolve_context_window

        return cls(
            trigger_fraction=settings.agent_compact_trigger_fraction,
            keep_fraction=settings.agent_compact_keep_fraction,
            trigger_tokens=settings.agent_compact_trigger_tokens,
            keep_messages=settings.agent_compact_keep_messages,
            context_window=resolve_context_window(
                model_id, override=settings.agent_context_window_tokens
            ),
        )

    @classmethod
    def fallback(cls) -> "CompactionSettings":
        return cls(0.90, 0.10, 170_000, 6, None)


class ClueSummarizationMiddleware(_DeepAgentsSummarizationMiddleware):
    """deepagents' summariser, as our own class (see module docstring)."""


class HistoryPathBackend:
    """Delegates to the agent backend, moving ``/conversation_history/`` under ``/work/``."""

    _FROM, _TO = "/conversation_history/", "/work/conversation_history/"

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    @classmethod
    def remap(cls, path: str) -> str:
        return cls._TO + path[len(cls._FROM):] if path.startswith(cls._FROM) else path

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def download_files(self, paths: list[str]) -> Any:
        return self._inner.download_files([self.remap(p) for p in paths])

    async def adownload_files(self, paths: list[str]) -> Any:
        return await self._inner.adownload_files([self.remap(p) for p in paths])

    def write(self, file_path: str, content: str) -> Any:
        return self._inner.write(self.remap(file_path), content)

    async def awrite(self, file_path: str, content: str) -> Any:
        return await self._inner.awrite(self.remap(file_path), content)

    def edit(self, file_path: str, *args: Any, **kwargs: Any) -> Any:
        return self._inner.edit(self.remap(file_path), *args, **kwargs)

    async def aedit(self, file_path: str, *args: Any, **kwargs: Any) -> Any:
        return await self._inner.aedit(self.remap(file_path), *args, **kwargs)


def build_compaction_middleware(
    model: Any, backend: Any, settings: CompactionSettings
) -> tuple[ClueSummarizationMiddleware, SummarizationToolMiddleware]:
    if settings.context_window is not None:
        trigger = ("tokens", int(settings.context_window * settings.trigger_fraction))
        keep = ("tokens", int(settings.context_window * settings.keep_fraction))
    else:
        trigger = ("tokens", settings.trigger_tokens)
        keep = ("messages", settings.keep_messages)
    summariser = ClueSummarizationMiddleware(
        model=model,
        backend=HistoryPathBackend(backend) if backend is not None else backend,
        trigger=trigger,
        keep=keep,
    )
    return summariser, SummarizationToolMiddleware(summarization=summariser)


def register_governed_harness_profile() -> None:
    """Remove deepagents' default summariser for our governed models — by exact class only."""
    register_harness_profile(
        GOVERNED_PROVIDER_KEY,
        HarnessProfile(excluded_middleware=frozenset({_DeepAgentsSummarizationMiddleware})),
    )
```

Verify while implementing (read deepagents 0.6.12 source, don't guess):
- the exact backend methods `_DeepAgentsSummarizationMiddleware._offload_to_backend` calls, and wrap exactly those in `HistoryPathBackend`;
- the provider key `get_model_provider(GovernedAgentChatModel)` returns — set `GOVERNED_PROVIDER_KEY` to it, and if it derives from the class name, override `GovernedAgentChatModel._get_ls_params` to return `ls_provider="clue-openrouter-agent"` explicitly;
- `HarnessProfile(excluded_middleware=...)` accepts classes, and exclusion matches by **exact type**, so the subclass survives (the guard test proves it);
- `SummarizationMiddleware` exposes `trigger`/`keep` attributes, or adapt the first two tests to its real attribute names.

- [ ] **Step 4: Wire into the runtime**

In `runtime.py`:

```python
_FRAMEWORK_TOOL_NAMES = frozenset(
    {"write_todos", "ls", "read_file", "write_file", "edit_file", "glob", "grep",
     # deepagents' manual compaction (founder ruling 2026-09-29): every agent may compact.
     "compact_conversation"}
)
```

`__init__` gains `compaction: CompactionSettings | None = None` → `self._compaction = compaction or CompactionSettings.fallback()`. Module import: `register_governed_harness_profile()` called once at import of `runtime.py`. In `run`, before `create_deep_agent`:

```python
            summariser, compact_tool = build_compaction_middleware(model, backend, self._compaction)
```

and append `summariser, compact_tool` to the `middleware=(...)` tuple after `*self._middleware`.

Every `DeepAgentTurnRuntime(...)` construction site (`account_research_wiring.py:283`, `head_of_abm_wiring.py:291`, `onboarding_synthesis_wiring.py:1201`, `quality_research_wiring.py:1086`, `specialist_wiring.py:459`) passes `compaction=CompactionSettings.from_settings(settings, model_id=<the profile's resolved model id>)` where settings are in scope; where they are not, leave it `None` (fallback thresholds — still our summariser).

- [ ] **Step 5: Run tests** — `tests/agents/test_compaction.py`, `tests/agents/test_runtime.py`, `tests/api/test_agent_registry_wiring.py`. Expected: new tests PASS; the two pre-existing `test_runtime.py` failures (`test_real_deepagent_tool_call_uses_exact_governed_descriptor_wrapper`, `test_stage0_final_response_reports_the_gate_and_does_not_claim_a_confirmed_icp`) unchanged, nothing else newly failing.

- [ ] **Step 6: Commit**

```bash
git add platform/agents/clue_agents/compaction.py platform/agents/clue_agents/runtime.py libs/clue-gateway/clue_gateway/agent_model.py platform/api/clue_api/*_wiring.py tests/agents/test_compaction.py
git commit -m "Compact every governed agent's conversation with our own summariser"
```

---

### Task 3: Head of ABM v69 (4 MB eviction files)

**Files:**
- Create: `platform/agents/catalog/profiles/head-of-abm/v69/profile.yaml`, `platform/agents/catalog/skills/stage0-interview/v42/SKILL.md`, `platform/agents/catalog/skills/manual-*/v15/SKILL.md`
- Modify: `platform/agents/clue_agents/manual/build.py` (`MANUAL_VERSION="v15"`, `PROFILE_VERSION="v69"`), `platform/agents/catalog/manual/tool_notes.yaml` (`stage0-interview v42`), `platform/api/clue_api/agent_registry_wiring.py` (`AgentRole.HEAD_OF_ABM: "v69"` + comment), `platform/api/clue_api/chat/composer_context.py` (`"head-of-abm@v69"`), `platform/api/clue_api/arv2/README.md`
- Test: `tests/agents/test_catalog.py`, `tests/api/test_agent_registry_wiring.py`, `tests/api/test_client_knowledge_privacy_s4e.py`, `tests/api/test_comprehensive_research_contract.py`, `tests/agents/test_manual_builder.py`

**Interfaces:** Produces `profile:head-of-abm@v69` (same tools as v68, `workspace.max_file_bytes: 4194304`).

- [ ] **Step 1:** Copy v68 → v69 changing only `version` and `max_file_bytes: 4194304`; mint `stage0-interview/v42` (= v41 with `manual-*/v14/` → `v15/`); copy `manual-*/v14` → `v15` replacing `/v14/`, `@v14`, `head-of-abm@v68`→`@v69`, `stage0-interview/v41`/`@v41`→`v42`. Follow the exact procedure of commit `1c6a0ed36` (v68).
- [ ] **Step 2:** `set -a; source .env; set +a; .venv/bin/python -m clue_api.manual_build --write`, then recompute every skill `sha256` in v69 from file bytes (same script as v68), then `--check` → "4 manual chapters are current". If the Limits chapter renders file limits, confirm it shows 4 MB.
- [ ] **Step 3:** Update pins exactly as in `1c6a0ed36`: catalog list (`@v15` after each `@v14`, `stage0-interview@v42` after `@v41` — lexicographic: `@v4` < `@v40` < `@v41` < `@v42`), registry test pins (`@v68`→`@v69`, `@v41`→`@v42`, manual `@v14`→`@v15`), s4e, comprehensive contract; run tests, take the new HEAD_OF_ABM digest from the failure message and pin it.
- [ ] **Step 4: Run** `tests/agents/test_catalog.py tests/agents/test_manual_builder.py tests/api/test_agent_registry_wiring.py tests/api/test_chat_composer_context.py tests/api/test_comprehensive_research_contract.py` (runner) and `tests/api/test_client_knowledge_privacy_s4e.py` (repo root). Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "Head of ABM v69: 4 MB workspace files for offloaded history"` (stage by explicit path).

---

### Task 4: Resume point and gap history

**Files:**
- Create: `platform/api/clue_api/conversation_continuation.py`
- Test: `tests/api/test_conversation_continuation_db.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class ResumePoint: turn_id: UUID; execution_id: ExecutionId; last_message_sequence: int`
  - `async def find_resume_point(conn, *, workspace_id: str, thread_id: str, before_turn_id: UUID, profile_name: str, profile_version: str, profile_sha256: str, resource_manifest_sha256: str) -> ResumePoint | None`
  - `async def gap_history(conn, *, workspace_id: str, thread_id: str, after_sequence: int, before_turn_id: UUID) -> tuple[HistoryMessageRef, ...]` (same shape `DbAgentHistoryStore.load` returns)
  - `def continuation_config_for(point: ResumePoint) -> dict` → `{"configurable": {"thread_id": str(point.execution_id), "checkpoint_ns": ""}}`

Rules: resume point = the latest `agent_turn` on the thread with `role='head_of_abm'`, created before `before_turn_id`'s turn, whose `agent_turn_event` terminal status is `completed`, and whose `profile_name/profile_version/profile_sha256/resource_manifest_sha256` equal the current resolved values; `execution_id = ExecutionId(operation_id_from_key(str(turn_id), "project-conversation@1"))` (the key `agent_turn_fleet_wiring.py` uses); `last_message_sequence` = max `agent_thread_message.sequence` of that turn. Gap = thread messages with `sequence > last_message_sequence` and `turn_id <> before_turn_id`, ordered by sequence.

- [ ] **Step 1: Write the failing DB tests** — seed a workspace/project/thread (reuse `tests/api/test_lane_d2_turn_submission_db.py` helpers `_seed`, `_thread`, `_submit`), insert `agent_turn` + `agent_turn_event` + `agent_thread_message` rows for: turn A completed (HoA), turn B cancelled (HoA), turn C design-leg (no `agent_turn` HoA row, messages only), then the current turn D. Assert:

```python
point = await find_resume_point(conn, workspace_id=ws, thread_id=thr, before_turn_id=turn_d, **current_profile)
assert point.turn_id == turn_a
gap = await gap_history(conn, workspace_id=ws, thread_id=thr, after_sequence=point.last_message_sequence, before_turn_id=turn_d)
assert [m.turn_id for m in gap] == [turn_b, turn_b, turn_c, turn_c]  # in sequence order
# a profile mismatch means no resume point
assert await find_resume_point(conn, ..., profile_version="v68", ...) is None
# a thread with no completed HoA turn has no resume point
```

- [ ] **Step 2: Run** — expect FAIL (module missing).
- [ ] **Step 3: Implement** with two SQL statements (resume point; gap via the same SELECT `DbAgentHistoryStore.load` uses, plus `AND m.sequence > :after AND m.turn_id <> :current`); reuse `turn_image_refs` for attachment refs so gap messages carry images exactly like L6 does today. Import `HistoryMessageRef` and helpers from `clue_api.agent_turn_wiring` — do not duplicate the row mapping; extract a shared `_history_rows_to_refs(rows, images, workspace_id)` in `agent_turn_wiring.py` and use it from both.
- [ ] **Step 4: Run** — expect PASS.
- [ ] **Step 5: Commit** — `git commit -m "Find a thread's resume point and the messages since it"`.

---

### Task 5: Continuation mode in the context assembler

**Files:**
- Modify: `platform/agents/clue_agents/context.py` (`DeterministicAgentContextAssembler.assemble`, ~line 864), `platform/agents/clue_agents/contracts.py` (`ContinuationRef`, `AssembledAgentContext`)
- Test: `tests/agents/test_context_continuation.py`

**Interfaces:**
- Consumes: `HistoryMessageRef` (gap), resume point ids from Task 4 (as plain values).
- Produces: `class ContinuationRef(BaseModel): turn_id: UUID; execution_id: ExecutionId; gap_message_ids: tuple[UUID, ...]`; `assemble(..., continuation: ContinuationRef | None = None)`; `AssembledAgentContext.continuation: ContinuationRef | None`.

Behaviour when `continuation` is set:
- L1 emits **no message** (the system prompt is already in the resumed state); its manifest still records the prompt ref and digest (so a profile change is visible in receipts).
- L6 emits only the gap messages (the `history` argument is the gap), same rendering as today (`_message`, interrupted notice, images).
- L2–L5 and L7 emit exactly as today, **after** L6 — order becomes L6 (gap), L2, L3, L4, L5, L7.
- The receipt aggregate payload gains `"continuation": {turn_id, execution_id, gap_message_ids}`.
- The final-message check (L7 last) is unchanged.
When `continuation` is `None`, output is byte-identical to today (regression test).

- [ ] **Step 1: Write the failing tests**

```python
def test_without_continuation_the_opening_context_is_unchanged(assembler, request_, profile, history):
    before = await assembler.assemble(request=request_, profile=profile, history=history)
    after = await assembler.assemble(request=request_, profile=profile, history=history, continuation=None)
    assert [m.content for m in before.messages] == [m.content for m in after.messages]


def test_a_continued_turn_sends_gap_then_cards_then_the_message(assembler, request_, profile, gap):
    ctx = await assembler.assemble(request=request_, profile=profile, history=gap,
                                   continuation=ContinuationRef(turn_id=A, execution_id=EA, gap_message_ids=tuple(m.message_id for m in gap)))
    kinds = [type(m).__name__ for m in ctx.messages]
    assert not any(m.content == PROFILE_PROMPT for m in ctx.messages)  # no L1 message
    assert [m.content for m in ctx.messages[: len(gap)]] == [GAP_BODIES...]
    assert ctx.messages[-1].content == USER_MESSAGE
    assert ctx.continuation.turn_id == A
```

Build the fixtures from `tests/agents/test_context.py`'s existing assembler fixtures (import them; do not copy).

- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement** — iterate layers in `_CONTINUATION_ORDER = (L1, L6, L2, L3, L4, L5, L7)` when continuation is set, skipping message emission (not manifest) for L1; keep `_ORDER` otherwise. Add `continuation` to the aggregate payload and to `AssembledAgentContext`.
- [ ] **Step 4: Run** `tests/agents/test_context_continuation.py tests/agents/test_context.py` — expect PASS.
- [ ] **Step 5: Commit** — `git commit -m "Assemble a continued turn: gap messages, cards and the message, appended"`.

---

### Task 6: Continue Head-of-ABM turns

**Files:**
- Modify: `platform/api/clue_api/conversation_turns.py` (~line 430, where `self._contexts.assemble(` is called), `platform/api/clue_api/head_of_abm_wiring.py` (`HeadOfAbmStage0Runtime.run` signature ~177, `DeepAgentTurnRuntime(` ~291), `platform/api/clue_api/agent_turn_fleet_wiring.py` (pass settings flag + compaction settings into the engine)
- Test: `tests/api/test_conversation_continuation_db.py` (extend)

**Interfaces:**
- Consumes: Task 4 `find_resume_point`, `gap_history`, `continuation_config_for`; Task 5 `continuation=`; Task 2 `compaction=`.
- Produces: `HeadOfAbmStage0Runtime.run(..., continuation_config: Mapping[str, Any] | None = None)`.

Flow in the engine (before assembly):

```python
point = None
if self._continuation_enabled:
    async with self._conn_factory() as conn:
        point = await find_resume_point(conn, workspace_id=..., thread_id=..., before_turn_id=turn_id,
            profile_name=resolved.profile.name, profile_version=resolved.profile.version,
            profile_sha256=resolved.profile_sha256,
            resource_manifest_sha256=resolved.resource_manifest.aggregate_sha256)
if point is not None:
    history = await gap_history(conn, ..., after_sequence=point.last_message_sequence, before_turn_id=turn_id)
    continuation = ContinuationRef(turn_id=point.turn_id, execution_id=point.execution_id,
                                   gap_message_ids=tuple(m.message_id for m in history))
else:
    history = <today's full DbAgentHistoryStore.load>
    continuation = None
context = await self._contexts.assemble(..., history=history, continuation=continuation)
...
outcome = await head.run(..., continuation_config=continuation_config_for(point) if point else None)
```

In `HeadOfAbmStage0Runtime.run`, pass `continuation_config=` and `compaction=` into `DeepAgentTurnRuntime(...)`. If the runtime raises the settled-state `ValueError("Research continuation requires a settled saved conversation")` (rename the message to "Continuation requires a settled saved conversation"), the engine logs `agent_turn.continuation_fallback` and re-runs the turn once without continuation (full history, `continuation=None`). Redelivery needs no new code: `runtime.run` already detects the turn's own state (`current.values`) and continues it.

Verify the checkpoint namespace before relying on `continuation_config_for`: in the Step 1 DB test, after turn A runs, read `graph.aget_state({"configurable": {"thread_id": str(EA), "checkpoint_ns": ""}})` and assert it returns A's messages; if it doesn't, use `f"agent-turn:{turn_id}"` and fix `continuation_config_for` accordingly.

- [ ] **Step 1: Write the failing DB test** — two real turns on one thread with a scripted fake model (reuse the fake-model engine setup in `tests/api/test_lane_d2_turn_submission_db.py::test_a_committed_turn_is_replayed_never_re_executed`): turn A calls a tool and answers; turn B's first model request must start with turn A's full saved messages (system, user A, AI tool call, tool result, AI answer) followed by B's cards and B's message; assert byte-identical prefix. Second test: bump the profile version between A and B (monkeypatch the resolved profile's version) → B gets the rebuilt context (no continuation) and `receipt.continuation is None`. Third: `CLUE_HEAD_OF_ABM_CONTINUATION_ENABLED=false` → rebuilt.
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement** the flow above; thread `continuation_enabled` and `compaction` from `Settings` through `build_agent_turn_work_handler` into the engine (follow how `max_rounds` is threaded today).
- [ ] **Step 4: Run** the new tests plus `tests/api/test_lane_d2_turn_submission_db.py` — expect PASS.
- [ ] **Step 5: Commit** — `git commit -m "Continue Head-of-ABM turns from the thread's last completed turn"`.

---

### Task 7: Compaction across turns, crash and stop

**Files:** Test: `tests/api/test_conversation_continuation_db.py` (extend)

- [ ] **Step 1: Compaction once.** With `CLUE_AGENT_CONTEXT_WINDOW_TOKENS=2000`, run three turns with long user messages; assert after turn 2 the state holds `_summarization_event`, `work/conversation_history/<thread>.md` exists in the thread workspace, and turn 3's first model request contains the summary message and **not** turn 1's original text, with exactly one summarisation model call across turns 2–3 (count calls with the summary prompt).
- [ ] **Step 2: Stopped turn skipped.** Turn A completed, turn B stopped (cancel event), turn C: resume point is A; B's messages appear as gap messages.
- [ ] **Step 3: Crash redelivery.** Run turn B with a fake model that raises after the first tool call (simulated crash), then re-run the same turn: the second run's first request has **no duplicated** history messages (count occurrences of turn A's answer == 1).
- [ ] **Step 4: Run** — expect PASS (fix any gap found in Tasks 4–6; do not weaken the assertions).
- [ ] **Step 5: Commit** — `git commit -m "Prove compaction carries across turns and crash/stop rules"`.

---

### Task 8: Measurement, notes and live proof hand-off

**Files:**
- Create: `scripts/turn_cache_report.py`
- Create: `_memory/2026-09-29-continuation-and-compaction.md`

- [ ] **Step 1: Write the report script** (read-only; prints per Head-of-ABM turn: first-call `input_tokens`, `cache_read_input_tokens`, share, and whether the turn continued):

```python
"""Per-turn prompt-cache share for Head-of-ABM turns. Run: set -a; source .env; set +a;
.venv/bin/python scripts/turn_cache_report.py [--since '2026-09-29']"""
import argparse, asyncio
from sqlalchemy import text
from clue_db import db_lifespan, transaction

SQL = text("""
with c as (select turn_id, input_tokens, coalesce(cache_read_input_tokens,0) cached, started_at,
  row_number() over (partition by turn_id order by sequence) rn
  from agent_model_call where role='head_of_abm' and started_at >= :since)
select turn_id, input_tokens, cached, round(100.0*cached/nullif(input_tokens,0)) pct, started_at
from c where rn=1 order by started_at""")

async def main(since: str) -> None:
    async with db_lifespan():
        async with transaction() as conn:
            for row in (await conn.execute(SQL, {"since": since})).all():
                print(*row, sep="\t")

if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("--since", default="1970-01-01")
    asyncio.run(main(p.parse_args().since))
```

- [ ] **Step 2: Run it** against the dubai DB (read-only). Expected: today's turns show the flat ~41k cached / 0% pattern (baseline recorded in the memory note).
- [ ] **Step 3: Memory note** — what shipped, settings, how to read the report, owed live proof: two turns on one chat within a few minutes → the second turn's first call ≥ ~90% cached; a long thread compacts once.
- [ ] **Step 4: Restart** API + workers via `./scripts/dev_stack_dubai.sh restart-api` / `restart-workers` after checking no fleet task is claimed (see incident note: a worker may need its PID stopped if it ignores SIGTERM).
- [ ] **Step 5: Commit** — `git commit -m "Report per-turn cache share; record continuation and compaction"`.
