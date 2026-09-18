"""D10 — offline unit tests for the output-token bound + per-role models.

No LLM calls: `init_model` is stubbed to a capturing sentinel and deepagents is
stubbed the same way the harness suite does it, so `create_design_deepagent`
never builds a real model or fires a request.

Covers:
- py_lumen_config env parsing: LUMEN_AGENT_MAX_TOKENS (+ loud failure on junk /
  non-positive), the three per-role model vars, and their defaults.
- AgentRuntimeConfig.from_env threading + resolved role accessors.
- harness builds EXACTLY THREE init_model instances — one per role, NEVER deduped
  (per-role usage attribution rides instance-level callbacks, so a shared
  instance would cross-attribute; see trace_callbacks.attach_trace_callback) — wires
  the right id to each role, tags each role's model with a role-labelled
  the role-tagged trace handler on `.callbacks`, and threads max_tokens on every call.
- .env.example documents all four new vars.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from lumen_agent.config import AgentRuntimeConfig


# --- 1. py_lumen_config env parsing ----------------------------------------


_D10_FIELDS = (
    "lumen_agent_max_tokens",
    "lumen_agent_model_orchestrator",
    "lumen_agent_model_author",
    "lumen_agent_model_reviewer",
)


def _settings(**overrides):
    """Settings isolated from the developer's real environment/.env: the D10
    fields under test default to blank (= unset) unless the test overrides
    them. Without this, setting the knobs in the workspace .env (a normal,
    supported thing to do) makes the defaults-unset tests fail — proven live
    2026-07-10."""
    from py_lumen_config.config import Settings

    isolated = {field: "" for field in _D10_FIELDS}
    isolated.update(overrides)
    return Settings(**isolated)


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
        trace_dir=Path("/tmp/repo/.deepagent-workspace"),
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
    # Accept the RIDER-1 kwargs (RepoRootedFilesystemBackend subclasses this stub
    # when deepagents is monkeypatched and forwards them to super().__init__).
    def __init__(self, root_dir: str, virtual_mode=None, max_file_size_mb: int = 10) -> None:
        self.root_dir = root_dir
        self.virtual_mode = virtual_mode
        self.max_file_size_mb = max_file_size_mb


class _FakeFilesystemPermission:
    def __init__(self, operations, paths, mode="allow") -> None:
        self.operations = operations
        self.paths = paths
        self.mode = mode


class _FakeDeepAgentState(dict):
    pass


def _install_harness_stubs(monkeypatch, capture: dict):
    """Stub deepagents + init_model, capturing create_deep_agent kwargs and every
    init_model call. init_model returns a FRESH sentinel per call carrying a
    writable `callbacks` field (like a real BaseChatModel), so per-instance role
    tagging by attach_trace_callback is observable and per-call identity is
    distinct (there is no dedupe to observe anymore — three roles → three
    instances, always)."""

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
        # FRESH sentinel per call with a `callbacks` field (declared on real
        # BaseChatModel) so attach_trace_callback appends its role-tagged handler.
        return types.SimpleNamespace(
            _role_model_id=model, _kwargs=kwargs, callbacks=None
        )

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


def _role_labels(capture):
    """The gateway role label of every init_model call, in build order. P3.2: the
    design-local usage-capture handler is retired — per-role attribution rides
    provider.build(role=...) on each instance (the ONE usage authority)."""
    return [call.get("role") for call in capture["init_calls"]]


def test_harness_all_same_model_builds_three_instances(tmp_path, monkeypatch):
    """All three roles resolve to the same id, yet the harness builds THREE
    distinct instances (no dedupe) — one per role — because per-role usage
    attribution rides instance-level callbacks."""
    capture: dict = {}
    _install_harness_stubs(monkeypatch, capture)
    from lumen_agent.harness import create_design_deepagent

    config = _config(repo_root=tmp_path, trace_dir=tmp_path / ".deepagent-workspace")
    create_design_deepagent("Make a poster", config)

    # THREE init_model calls, all for the same id (one per role, never deduped).
    assert len(capture["init_calls"]) == 3
    assert [c["model"] for c in capture["init_calls"]] == [
        "openai:default/model",
        "openai:default/model",
        "openai:default/model",
    ]

    ck = capture["create_kwargs"]
    orch = ck["model"]
    author = _subagent(ck, "lumen-dsl-author")["model"]
    reviewer = _subagent(ck, "lumen-visual-reviewer")["model"]
    # No dedupe: three DISTINCT objects even though the id is identical.
    assert orch is not author
    assert author is not reviewer
    assert orch is not reviewer
    assert orch._role_model_id == author._role_model_id == reviewer._role_model_id == "openai:default/model"
    # Each instance is role-labelled AT THE GATEWAY — cleanly attributed, once.
    assert _role_labels(capture) == [
        "design_orchestrator",
        "design_author",
        "design_reviewer",
    ]


def test_harness_distinct_role_models(tmp_path, monkeypatch):
    capture: dict = {}
    _install_harness_stubs(monkeypatch, capture)
    from lumen_agent.harness import create_design_deepagent

    config = _config(
        repo_root=tmp_path,
        trace_dir=tmp_path / ".deepagent-workspace",
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
    assert _role_labels(capture) == [
        "design_orchestrator",
        "design_author",
        "design_reviewer",
    ]


def test_harness_partial_override_still_builds_three_instances(tmp_path, monkeypatch):
    """Only the orchestrator differs; author + reviewer share the default id — but
    they still get SEPARATE instances (no dedupe), so their usage never
    cross-attributes."""
    capture: dict = {}
    _install_harness_stubs(monkeypatch, capture)
    from lumen_agent.harness import create_design_deepagent

    config = _config(
        repo_root=tmp_path,
        trace_dir=tmp_path / ".deepagent-workspace",
        agent_model_orchestrator="openai:orch/x",
    )
    create_design_deepagent("Make a poster", config)

    ck = capture["create_kwargs"]
    author = _subagent(ck, "lumen-dsl-author")["model"]
    reviewer = _subagent(ck, "lumen-visual-reviewer")["model"]
    assert ck["model"]._role_model_id == "openai:orch/x"
    # Same resolved id, but DISTINCT instances (no dedupe).
    assert author is not reviewer
    assert author._role_model_id == reviewer._role_model_id == "openai:default/model"
    # THREE init_model calls (one per role), never two.
    assert len(capture["init_calls"]) == 3
    assert _role_labels(capture) == [
        "design_orchestrator",
        "design_author",
        "design_reviewer",
    ]


def test_harness_threads_max_tokens_on_every_call(tmp_path, monkeypatch):
    capture: dict = {}
    _install_harness_stubs(monkeypatch, capture)
    from lumen_agent.harness import create_design_deepagent

    config = _config(
        repo_root=tmp_path,
        trace_dir=tmp_path / ".deepagent-workspace",
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

    config = _config(repo_root=tmp_path, trace_dir=tmp_path / ".deepagent-workspace")
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


# --- 6. init_model requests OpenRouter usage accounting (L0) ----------------


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


# --- 7. L1/L3 latency: provider sort + per-call watchdog -------------------


def test_env_example_documents_l1_l3_vars():
    repo_root = Path(__file__).resolve().parents[3]
    text = (repo_root / ".env.example").read_text(encoding="utf-8")
    for var in ("LUMEN_AGENT_PROVIDER_SORT", "LUMEN_AGENT_LLM_TIMEOUT_S"):
        assert var in text, f"{var} missing from .env.example"


def test_provider_sort_and_timeout_defaults_are_ratified():
    """The ratified defaults live on the field declarations (env-independent):
    provider_sort='latency' (cache locality on) and llm_timeout_s=60.0 (watchdog
    on). Read from model_fields so a developer's .env can't perturb the assertion."""
    from py_lumen_config.config import Settings

    fields = Settings.model_fields
    assert fields["lumen_agent_provider_sort"].default == "latency"
    assert fields["lumen_agent_llm_timeout_s"].default == 60.0


def test_provider_sort_blank_is_unset():
    assert _settings(lumen_agent_provider_sort="").lumen_agent_provider_sort is None


def test_provider_sort_parses_when_set():
    assert (
        _settings(lumen_agent_provider_sort="throughput").lumen_agent_provider_sort
        == "throughput"
    )


def test_llm_timeout_blank_is_unset():
    assert _settings(lumen_agent_llm_timeout_s="").lumen_agent_llm_timeout_s is None


def test_llm_timeout_valid_parses_to_float():
    assert _settings(lumen_agent_llm_timeout_s="90").lumen_agent_llm_timeout_s == 90.0


@pytest.mark.parametrize("junk", ["abc", "0", "-5"])
def test_llm_timeout_junk_fails_loudly(junk):
    with pytest.raises(Exception):
        _settings(lumen_agent_llm_timeout_s=junk)


def test_config_defaults_carry_provider_sort_and_timeout():
    """AgentRuntimeConfig's own dataclass defaults mirror the ratified settings so
    a config built without overrides is L1/L3-on (env-independent)."""
    c = _config()
    assert c.agent_provider_sort == "latency"
    assert c.agent_llm_timeout_s == 60.0


def test_harness_threads_provider_sort_and_timeout_on_every_call(tmp_path, monkeypatch):
    """The harness passes agent_provider_sort + agent_llm_timeout_s into init_model
    for all three role instances."""
    capture: dict = {}
    _install_harness_stubs(monkeypatch, capture)
    from lumen_agent.harness import create_design_deepagent

    config = _config(
        repo_root=tmp_path,
        trace_dir=tmp_path / ".deepagent-workspace",
        agent_provider_sort="latency",
        agent_llm_timeout_s=45.0,
    )
    create_design_deepagent("Make a poster", config)

    assert len(capture["init_calls"]) == 3
    for call in capture["init_calls"]:
        assert call["provider_sort"] == "latency"
        assert call["timeout_s"] == 45.0


def test_harness_threads_disabled_l1_l3_as_none(tmp_path, monkeypatch):
    """provider_sort=None / llm_timeout_s=None flow through as None (disabled)."""
    capture: dict = {}
    _install_harness_stubs(monkeypatch, capture)
    from lumen_agent.harness import create_design_deepagent

    config = _config(
        repo_root=tmp_path,
        trace_dir=tmp_path / ".deepagent-workspace",
        agent_provider_sort=None,
        agent_llm_timeout_s=None,
    )
    create_design_deepagent("Make a poster", config)

    for call in capture["init_calls"]:
        assert call["provider_sort"] is None
        assert call["timeout_s"] is None


# --- 8. init_model: provider field (L1) + watchdog kwargs (L3) --------------


def _capture_init_chat_model(monkeypatch) -> dict:
    """Stub init_chat_model and return a dict that fills with the captured
    (model, kwargs) on the next init_model call."""
    from lumen_agent import llm as llm_mod  # noqa: F401 (import side: patch target)

    captured: dict = {}

    def fake_init_chat_model(model, **kwargs):
        captured["model"] = model
        captured["kwargs"] = kwargs
        return object()

    fake_lc = types.ModuleType("langchain.chat_models")
    fake_lc.init_chat_model = fake_init_chat_model
    monkeypatch.setitem(sys.modules, "langchain.chat_models", fake_lc)
    return captured

# --- P3.2: init_model builds through the platform's governed gateway ---------
# The wire mechanics (extra_body shapes, timeout kwargs) are pinned at the
# gateway itself (tests/gateway/test_agent_model.py); these pin the ADAPTER
# contract this module now owns. Construction is offline — no network happens
# until invoke.


def _governed(model: str = "openai:x/y", **kwargs):
    from lumen_agent import llm as llm_mod

    llm_mod._PROVIDER_CACHE.clear()
    return llm_mod.init_model(
        model, base_url="https://openrouter.ai/api/v1", api_key="sk-test", **kwargs
    )


def test_init_model_returns_role_labelled_governed_model():
    from clue_gateway.agent_model import GovernedAgentChatModel

    model = _governed(role="design_author")
    assert isinstance(model, GovernedAgentChatModel)
    assert model.requested_model == "x/y"  # "openai:" env prefix stripped
    assert model.attribution_role == "design_author"
    # Bare OpenRouter ids are accepted too (the prefix is back-compat only).
    assert _governed(model="x/y").requested_model == "x/y"


def test_init_model_economics_ride_gateway_config():
    pinned = _governed(provider_sort="latency").models[0]
    assert pinned.extra_body == {"provider": {"sort": "latency"}, "usage": {"include": True}}
    unpinned = _governed(provider_sort=None).models[0]
    assert unpinned.extra_body == {"usage": {"include": True}}


def test_init_model_reasoning_maps_to_gateway_policy():
    assert _governed(reasoning="medium").gateway_config.agent_reasoning.effort == "medium"
    assert _governed().gateway_config.agent_reasoning is None
    with pytest.raises(ValueError, match="low|medium|high"):
        _governed(reasoning="maximal")


def test_init_model_output_is_bounded_by_default():
    """P3.2 ruling: the governed build refuses unbounded generation — unset
    max_tokens now means the damage-limiting default, not 'no bound'."""
    from lumen_agent import llm as llm_mod

    assert _governed(max_tokens=16000).models[0].max_tokens == 16000
    assert _governed().models[0].max_tokens == llm_mod._DEFAULT_MAX_OUTPUT_TOKENS


def test_init_model_timeout_and_retries_are_always_bounded():
    from lumen_agent import llm as llm_mod

    bounded = _governed(timeout_s=45.0).models[0]
    assert bounded.request_timeout == 45.0
    assert bounded.max_retries == 2
    assert _governed().models[0].request_timeout == llm_mod._DEFAULT_TIMEOUT_S


def test_governed_provider_is_cached_per_policy_fingerprint():
    """Three role builds under one policy share ONE provider (and its capability
    catalog fetch); a different policy fingerprint gets its own."""
    from lumen_agent import llm as llm_mod

    llm_mod._PROVIDER_CACHE.clear()
    common = {"base_url": "https://openrouter.ai/api/v1", "api_key": "sk-test"}
    llm_mod.init_model("x/y", role="design_orchestrator", **common)
    llm_mod.init_model("a/b", role="design_reviewer", **common)
    assert len(llm_mod._PROVIDER_CACHE) == 1
    llm_mod.init_model("x/y", reasoning="high", **common)
    assert len(llm_mod._PROVIDER_CACHE) == 2
