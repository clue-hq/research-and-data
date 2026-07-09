"""D10 — offline unit tests for the output-token bound + per-role models.

No LLM calls: `init_model` is stubbed to a capturing sentinel and deepagents is
stubbed the same way the harness suite does it, so `create_design_deepagent`
never builds a real model or fires a request.

Covers:
- py_lumen_config env parsing: LUMEN_AGENT_MAX_TOKENS (+ loud failure on junk /
  non-positive), the three per-role model vars, and their defaults.
- AgentRuntimeConfig.from_env threading + resolved role accessors.
- harness builds ONE init_model instance per DISTINCT resolved role id (dedupe),
  wires the right id to each role, and threads max_tokens on every call.
- .env.example documents all four new vars.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from lumen_agent.config import AgentRuntimeConfig


# --- 1. py_lumen_config env parsing ----------------------------------------


def _settings(**overrides):
    from py_lumen_config.config import Settings

    return Settings(**overrides)


def test_max_tokens_defaults_unset():
    assert _settings().lumen_agent_max_tokens is None


def test_max_tokens_blank_is_unset():
    assert _settings(lumen_agent_max_tokens="").lumen_agent_max_tokens is None


def test_max_tokens_valid_parses_to_int():
    assert _settings(lumen_agent_max_tokens="16000").lumen_agent_max_tokens == 16000


@pytest.mark.parametrize("junk", ["abc", "0", "-1", "12.5"])
def test_max_tokens_junk_fails_loudly(junk):
    with pytest.raises(Exception):
        _settings(lumen_agent_max_tokens=junk)


def test_role_models_default_unset():
    s = _settings()
    assert s.lumen_agent_model_orchestrator is None
    assert s.lumen_agent_model_author is None
    assert s.lumen_agent_model_reviewer is None


def test_role_models_blank_is_unset():
    s = _settings(
        lumen_agent_model_orchestrator="",
        lumen_agent_model_author="  ",
        lumen_agent_model_reviewer="",
    )
    assert s.lumen_agent_model_orchestrator is None
    assert s.lumen_agent_model_author is None
    assert s.lumen_agent_model_reviewer is None


def test_role_models_parse_when_set():
    s = _settings(
        lumen_agent_model_orchestrator="openai:a/one",
        lumen_agent_model_author="openai:b/two",
        lumen_agent_model_reviewer="openai:c/three",
    )
    assert s.lumen_agent_model_orchestrator == "openai:a/one"
    assert s.lumen_agent_model_author == "openai:b/two"
    assert s.lumen_agent_model_reviewer == "openai:c/three"


# --- 2. AgentRuntimeConfig resolved accessors ------------------------------


def _config(**overrides) -> AgentRuntimeConfig:
    base = dict(
        repo_root=Path("/tmp/repo"),
        model="openai:default/model",
        max_iterations=3,
        preview_format="svg",
        trace_dir=Path("/tmp/repo/.lumen-runs"),
        agent_base_url="https://openrouter.ai/api/v1",
        agent_api_key="sk-test",
    )
    base.update(overrides)
    return AgentRuntimeConfig(**base)


def test_role_accessors_default_to_model():
    c = _config()
    assert c.orchestrator_model == "openai:default/model"
    assert c.author_model == "openai:default/model"
    assert c.reviewer_model == "openai:default/model"


def test_role_accessors_use_overrides():
    c = _config(
        agent_model_orchestrator="openai:orch/x",
        agent_model_author="openai:auth/y",
        agent_model_reviewer="openai:rev/z",
    )
    assert c.orchestrator_model == "openai:orch/x"
    assert c.author_model == "openai:auth/y"
    assert c.reviewer_model == "openai:rev/z"


# --- 3. harness builds per-role model instances ----------------------------


class _FakeFilesystemBackend:
    def __init__(self, root_dir: str) -> None:
        self.root_dir = root_dir


class _FakeFilesystemPermission:
    def __init__(self, operations, paths, mode="allow") -> None:
        self.operations = operations
        self.paths = paths
        self.mode = mode


class _FakeDeepAgentState(dict):
    pass


def _install_harness_stubs(monkeypatch, capture: dict):
    """Stub deepagents + init_model, capturing create_deep_agent kwargs and every
    init_model call. init_model returns a sentinel keyed by model id so identity
    reveals dedupe."""

    def fake_create_deep_agent(**kwargs):
        capture["create_kwargs"] = kwargs
        return types.SimpleNamespace(invoke=lambda *a, **k: {"messages": []})

    module = types.ModuleType("deepagents")
    module.create_deep_agent = fake_create_deep_agent
    module.FilesystemPermission = _FakeFilesystemPermission
    module.DeepAgentState = _FakeDeepAgentState
    backends_module = types.ModuleType("deepagents.backends")
    filesystem_module = types.ModuleType("deepagents.backends.filesystem")
    filesystem_module.FilesystemBackend = _FakeFilesystemBackend
    monkeypatch.setitem(sys.modules, "deepagents", module)
    monkeypatch.setitem(sys.modules, "deepagents.backends", backends_module)
    monkeypatch.setitem(sys.modules, "deepagents.backends.filesystem", filesystem_module)

    from agent_fixtures import FakeCoreClient

    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)

    calls: list[dict] = []
    capture["init_calls"] = calls

    def fake_init_model(model, **kwargs):
        calls.append({"model": model, **kwargs})
        # Distinct sentinel per model id so dedupe is observable by identity.
        return types.SimpleNamespace(_role_model_id=model, _kwargs=kwargs)

    monkeypatch.setattr("lumen_agent.llm.init_model", fake_init_model, raising=False)
    # Neutralize the multimodal probe (it would try HTTP); the per-role coverage
    # is verified via its own direct test below.
    monkeypatch.setattr(
        "lumen_agent.llm.assert_all_role_models_support_image_input",
        lambda config: None,
        raising=False,
    )


def _subagent(create_kwargs, name):
    return next(s for s in create_kwargs["subagents"] if s["name"] == name)


def test_harness_all_same_model_builds_one_instance(tmp_path, monkeypatch):
    capture: dict = {}
    _install_harness_stubs(monkeypatch, capture)
    from lumen_agent.harness import create_design_deepagent

    config = _config(repo_root=tmp_path, trace_dir=tmp_path / ".lumen-runs")
    create_design_deepagent("Make a poster", config)

    # Exactly one init_model call: all three roles resolve to the same id.
    assert len(capture["init_calls"]) == 1
    assert capture["init_calls"][0]["model"] == "openai:default/model"

    ck = capture["create_kwargs"]
    orch = ck["model"]
    author = _subagent(ck, "lumen-dsl-author")["model"]
    reviewer = _subagent(ck, "lumen-visual-reviewer")["model"]
    # Dedupe: identical resolved ids share ONE instance (same object).
    assert orch is author is reviewer
    assert orch._role_model_id == "openai:default/model"


def test_harness_distinct_role_models(tmp_path, monkeypatch):
    capture: dict = {}
    _install_harness_stubs(monkeypatch, capture)
    from lumen_agent.harness import create_design_deepagent

    config = _config(
        repo_root=tmp_path,
        trace_dir=tmp_path / ".lumen-runs",
        agent_model_orchestrator="openai:orch/x",
        agent_model_author="openai:auth/y",
        agent_model_reviewer="openai:rev/z",
    )
    create_design_deepagent("Make a poster", config)

    ck = capture["create_kwargs"]
    assert ck["model"]._role_model_id == "openai:orch/x"
    assert _subagent(ck, "lumen-dsl-author")["model"]._role_model_id == "openai:auth/y"
    assert _subagent(ck, "lumen-visual-reviewer")["model"]._role_model_id == "openai:rev/z"
    # Three distinct ids → three init_model calls.
    assert {c["model"] for c in capture["init_calls"]} == {
        "openai:orch/x",
        "openai:auth/y",
        "openai:rev/z",
    }


def test_harness_partial_override_dedupes_shared_default(tmp_path, monkeypatch):
    capture: dict = {}
    _install_harness_stubs(monkeypatch, capture)
    from lumen_agent.harness import create_design_deepagent

    # Only the orchestrator differs; author + reviewer fall back to the default.
    config = _config(
        repo_root=tmp_path,
        trace_dir=tmp_path / ".lumen-runs",
        agent_model_orchestrator="openai:orch/x",
    )
    create_design_deepagent("Make a poster", config)

    ck = capture["create_kwargs"]
    author = _subagent(ck, "lumen-dsl-author")["model"]
    reviewer = _subagent(ck, "lumen-visual-reviewer")["model"]
    assert ck["model"]._role_model_id == "openai:orch/x"
    assert author is reviewer  # shared default → one instance
    assert author._role_model_id == "openai:default/model"
    # Two distinct ids → two init_model calls (not three).
    assert len(capture["init_calls"]) == 2


def test_harness_threads_max_tokens_on_every_call(tmp_path, monkeypatch):
    capture: dict = {}
    _install_harness_stubs(monkeypatch, capture)
    from lumen_agent.harness import create_design_deepagent

    config = _config(
        repo_root=tmp_path,
        trace_dir=tmp_path / ".lumen-runs",
        agent_max_tokens=16000,
        agent_model_orchestrator="openai:orch/x",
        agent_model_author="openai:auth/y",
    )
    create_design_deepagent("Make a poster", config)

    assert capture["init_calls"], "expected at least one init_model call"
    for call in capture["init_calls"]:
        assert call["max_tokens"] == 16000


def test_harness_max_tokens_unset_passes_none(tmp_path, monkeypatch):
    capture: dict = {}
    _install_harness_stubs(monkeypatch, capture)
    from lumen_agent.harness import create_design_deepagent

    config = _config(repo_root=tmp_path, trace_dir=tmp_path / ".lumen-runs")
    create_design_deepagent("Make a poster", config)

    for call in capture["init_calls"]:
        assert call["max_tokens"] is None


# --- 4. multimodal validation covers every distinct role -------------------


def test_assert_all_role_models_checks_every_distinct_id(monkeypatch):
    from lumen_agent import llm as llm_mod

    checked: list[str] = []
    monkeypatch.setattr(
        llm_mod,
        "assert_model_supports_image_input",
        lambda model, *, base_url, api_key: checked.append(model),
    )
    config = _config(
        agent_model_orchestrator="openai:orch/x",
        agent_model_author="openai:auth/y",
        agent_model_reviewer="openai:orch/x",  # duplicate of orchestrator
    )
    llm_mod.assert_all_role_models_support_image_input(config)
    # Distinct ids only: the duplicate collapses.
    assert set(checked) == {"openai:orch/x", "openai:auth/y"}


def test_assert_all_role_models_propagates_text_only_raise(monkeypatch):
    from lumen_agent import llm as llm_mod

    def boom(model, *, base_url, api_key):
        raise ValueError(f"{model} is TEXT-ONLY")

    monkeypatch.setattr(llm_mod, "assert_model_supports_image_input", boom)
    with pytest.raises(ValueError, match="TEXT-ONLY"):
        llm_mod.assert_all_role_models_support_image_input(_config())


# --- 5. init_model threads max_tokens to the chat model --------------------


def test_init_model_passes_max_tokens_kwarg(monkeypatch):
    from lumen_agent import llm as llm_mod

    captured: dict = {}

    def fake_init_chat_model(model, **kwargs):
        captured["model"] = model
        captured["kwargs"] = kwargs
        return object()

    fake_lc = types.ModuleType("langchain.chat_models")
    fake_lc.init_chat_model = fake_init_chat_model
    monkeypatch.setitem(sys.modules, "langchain.chat_models", fake_lc)

    llm_mod.init_model(
        "openai:x/y",
        base_url="https://openrouter.ai/api/v1",
        api_key="sk-test",
        max_tokens=16000,
    )
    assert captured["kwargs"]["max_tokens"] == 16000


def test_init_model_omits_max_tokens_when_unset(monkeypatch):
    from lumen_agent import llm as llm_mod

    captured: dict = {}

    def fake_init_chat_model(model, **kwargs):
        captured["kwargs"] = kwargs
        return object()

    fake_lc = types.ModuleType("langchain.chat_models")
    fake_lc.init_chat_model = fake_init_chat_model
    monkeypatch.setitem(sys.modules, "langchain.chat_models", fake_lc)

    llm_mod.init_model(
        "openai:x/y", base_url="https://openrouter.ai/api/v1", api_key="sk-test"
    )
    assert "max_tokens" not in captured["kwargs"]


# --- 6. .env.example documents all four new vars ---------------------------


def test_env_example_documents_new_vars():
    repo_root = Path(__file__).resolve().parents[3]
    text = (repo_root / ".env.example").read_text(encoding="utf-8")
    for var in (
        "LUMEN_AGENT_MAX_TOKENS",
        "LUMEN_AGENT_MODEL_ORCHESTRATOR",
        "LUMEN_AGENT_MODEL_AUTHOR",
        "LUMEN_AGENT_MODEL_REVIEWER",
    ):
        assert var in text, f"{var} missing from .env.example"
