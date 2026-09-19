"""W-isolation backend/normalization/materializer + RIDER 2 (usage capture).

The W-isolation section exercises the REAL deepagents `FilesystemBackend` via our
`AgentWorkspaceBackend` subclass (`virtual_mode=True`) — no stubbing — so the
normalization + containment behavior is proven against the actual resolution logic
it wraps. Importing the backend at module top pins its parent to the real class at
collection time (before any other test's deepagents stub runs). It also unit-tests
the pure `normalize_agent_key`/`to_virtual` helpers and the workspace materializer.

The usage section drives `trace_callbacks.extract_usage` with the `LLMResult`
shapes LangChain emits, and proves the harness hands deepagents models carrying
no design-local usage handler while the turn's invoke config carries the lane-3
`ModelCallCollector`.
"""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from lumen_agent.fs_backend import AgentWorkspaceBackend
from lumen_agent.materialize import materialize_agent_workspace
from lumen_agent.paths import host_to_virtual, normalize_agent_key, to_virtual
from lumen_agent.trace_callbacks import extract_usage


# ============================================================================
# W-isolation — normalization helper (D1, pure function table)
# ============================================================================

_WS = "/ws/.deepagent-workspace"


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        # host-absolute under the workspace root → tail under `/`
        (f"{_WS}/run_x/workspace/brief.md", "/run_x/workspace/brief.md"),
        (_WS, "/"),
        # legacy knowledge_docs — bare, repo-absolute, and `/`-rooted forms
        (
            "apps/agent_runtime/knowledge_docs/skills/create-design/SKILL.md",
            "/knowledge_docs/skills/create-design/SKILL.md",
        ),
        (
            "/Users/x/havana/apps/agent_runtime/knowledge_docs/AGENT.md",
            "/knowledge_docs/AGENT.md",
        ),
        (
            "/apps/agent_runtime/knowledge_docs/knowledge/lumen-dsl/grammar.md",
            "/knowledge_docs/knowledge/lumen-dsl/grammar.md",
        ),
        # gate-R regression: the BARE directory forms (no trailing slash) — an
        # `ls` on the knowledge root was the live failure form of 2026-07-10
        ("/apps/agent_runtime/knowledge_docs", "/knowledge_docs"),
        ("apps/agent_runtime/knowledge_docs/", "/knowledge_docs"),
        ("/Users/x/havana/apps/agent_runtime/knowledge_docs", "/knowledge_docs"),
        ("/.lumen-runs", "/"),
        (".lumen-runs/", "/"),
        # legacy `.lumen-runs/` — bare, `/`-rooted, and host-embedded forms
        (".lumen-runs/run_x/workspace/brief.md", "/run_x/workspace/brief.md"),
        ("/.lumen-runs/run_x/f", "/run_x/f"),
        ("/Users/x/havana/.lumen-runs/run_y/f", "/run_y/f"),
        # plain virtual paths pass through unchanged
        ("/run_x/workspace/rounds/round_1/direction.md", "/run_x/workspace/rounds/round_1/direction.md"),
        ("/knowledge_docs/AGENT.md", "/knowledge_docs/AGENT.md"),
        ("/.deepagent/skills/create-design/SKILL.md", "/.deepagent/skills/create-design/SKILL.md"),
        # relative paths pass through unchanged
        ("rounds/round_1/direction.md", "rounds/round_1/direction.md"),
    ],
)
def test_normalize_agent_key_table(key, expected):
    assert normalize_agent_key(key, _WS) == expected


@pytest.mark.parametrize(
    "key",
    [
        f"{_WS}/../../etc/passwd",  # host-absolute-under-ws with a climb
        f"{_WS}/run_x/../../secret",
        "../../etc/passwd",  # plain relative climb
        "apps/agent_runtime/knowledge_docs/../../../etc/passwd",  # via the legacy marker
    ],
)
def test_normalize_agent_key_never_manufactures_an_escape(key):
    """A `..` climb must SURVIVE normalization (never be collapsed away), so the
    backend's own traversal guard still rejects it."""
    assert ".." in normalize_agent_key(key, _WS)


# ============================================================================
# W-isolation — to_virtual / host_to_virtual (D5)
# ============================================================================


def test_host_to_virtual_under_root(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    assert host_to_virtual(root / "run_1" / "preview.png", root) == "/run_1/preview.png"
    assert host_to_virtual(root, root) == "/"


def test_host_to_virtual_leaves_external_paths_untouched(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    external = tmp_path / "elsewhere" / "x.png"
    assert host_to_virtual(external, root) == str(external)


def test_to_virtual_uses_config_workspace_root(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    config = types.SimpleNamespace(workspace_root=root)
    assert to_virtual(root / "run_9" / "iterations" / "1" / "preview.png", config) == (
        "/run_9/iterations/1/preview.png"
    )


# ============================================================================
# W-isolation — AgentWorkspaceBackend (real deepagents FilesystemBackend, virtual)
# ============================================================================


@pytest.fixture
def ws_backend(tmp_path: Path):
    """A virtual-mode backend rooted at a tmp workspace seeded with a run
    workspace file, a materialized knowledge_docs file, and a skills dir."""
    root = tmp_path
    (root / "run_1" / "workspace").mkdir(parents=True)
    (root / "run_1" / "workspace" / "brief.md").write_text("hello", encoding="utf-8")
    (root / "knowledge_docs").mkdir()
    (root / "knowledge_docs" / "grammar.md").write_text("# grammar", encoding="utf-8")
    (root / ".deepagent" / "skills" / "create-design").mkdir(parents=True)
    return root, AgentWorkspaceBackend(str(root))


def test_backend_is_virtual_mode(ws_backend):
    _root, backend = ws_backend
    assert backend.virtual_mode is True


def test_read_write_edit_via_virtual_paths(ws_backend):
    _root, backend = ws_backend
    result = backend.read("/run_1/workspace/brief.md")
    assert result.error is None
    assert "hello" in (result.file_data or {}).get("content", "")

    write = backend.write("/run_1/workspace/rounds/round_1/direction.md", "do the thing")
    assert write.error is None
    edit = backend.edit(
        "/run_1/workspace/rounds/round_1/direction.md", "do the thing", "do it well"
    )
    assert edit.error is None


def test_host_absolute_under_ws_is_normalized_and_served(ws_backend):
    """A model-emitted HOST-absolute path under the workspace resolves (D1): the
    prefix is stripped and the file is served."""
    root, backend = ws_backend
    result = backend.read(str(root / "run_1" / "workspace" / "brief.md"))
    assert result.error is None
    assert "hello" in (result.file_data or {}).get("content", "")


def test_legacy_knowledge_docs_path_is_normalized_and_served(ws_backend):
    _root, backend = ws_backend
    result = backend.read("apps/agent_runtime/knowledge_docs/grammar.md")
    assert result.error is None
    assert "# grammar" in (result.file_data or {}).get("content", "")


def test_absolute_outside_is_reanchored_not_escaped(ws_backend):
    """`/etc/hosts` is re-anchored under the virtual root (contained), so it is
    simply not-found — never a read of the real host file, never a crash."""
    _root, backend = ws_backend
    result = backend.read("/etc/hosts")
    assert result.error is not None
    assert "not found" in result.error.lower()


def test_dotdot_traversal_surfaces_clean_error(ws_backend):
    """A `..` climb that reaches the backend surfaces a clean teaching error
    (converted to PermissionError so read/write/edit never crash the turn)."""
    _root, backend = ws_backend
    result = backend.read("/run_1/../../secret")
    assert result.error is not None
    assert "workspace root" in result.error


def test_symlink_escape_surfaces_clean_error(ws_backend, tmp_path):
    """A symlink INSIDE the workspace whose target resolves outside it is rejected
    with a clean error (not an uncaught ValueError)."""
    root, backend = ws_backend
    outside = tmp_path.parent / "ws_outside_secret.txt"
    outside.write_text("secret", encoding="utf-8")
    link = root / "run_1" / "link_to_secret.txt"
    link.symlink_to(outside)
    result = backend.read("/run_1/link_to_secret.txt")
    assert result.error is not None
    assert "workspace root" in result.error


def test_write_deny_globs_target_the_readonly_virtual_trees():
    """The harness denies writes to every derived read-only virtual tree."""
    from lumen_agent.harness import _filesystem_permissions

    perms = _filesystem_permissions()
    assert len(perms) == 1
    perm = perms[0]
    assert set(perm.paths) == {
        "/.materialize.lock",
        "/.deepagent/**",
        "/knowledge_docs/**",
        "/custom_components",
        "/custom_components/**",
    }
    assert perm.operations == ["write"]
    assert perm.mode == "deny"


@pytest.mark.parametrize("alias", ["virtual", "relative", "host", "legacy", "dot"])
@pytest.mark.parametrize("operation", ["write", "edit"])
def test_backend_denies_materialization_lock_writes_through_aliases(ws_backend, alias, operation):
    root, backend = ws_backend
    lock = root / ".materialize.lock"
    key = {
        "virtual": "/.materialize.lock",
        "relative": ".materialize.lock",
        "host": str(lock),
        "legacy": "/.lumen-runs/.materialize.lock",
        "dot": "/./.materialize.lock",
    }[alias]
    if operation == "write":
        denied = backend.write(key, "agent-written")
        assert denied.error is not None
        assert not lock.exists()
    else:
        lock.touch()
        inode = lock.stat().st_ino
        denied_edit = backend.edit(key, "", "agent-written")
        assert denied_edit.error is not None
        assert lock.read_bytes() == b""
        assert lock.stat().st_ino == inode


def test_custom_component_projection_has_public_paths_and_typed_writes_only(
    tmp_path: Path,
):
    root = tmp_path / "workspace"
    projection = root / "run_1" / "custom_components"
    component = projection / "pricing-card"
    component.mkdir(parents=True)
    entry = component / "pricing-card.tsx"
    entry.write_text("export default function Card() { return null; }")
    backend = AgentWorkspaceBackend(
        str(root), custom_components_root=projection
    )

    read = backend.read(
        "/custom_components/pricing-card/pricing-card.tsx"
    )
    assert read.error is None
    assert "function Card" in (read.file_data or {}).get("content", "")
    listed = backend.ls("/custom_components/pricing-card")
    assert listed.error is None
    assert [item["path"] for item in listed.entries or []] == [
        "/custom_components/pricing-card/pricing-card.tsx"
    ]

    denied = backend.edit(
        "/custom_components/pricing-card/pricing-card.tsx",
        "return null",
        "return <div />",
    )
    assert denied.error is not None
    assert "write_custom_component_source" in denied.error
    internal_alias = backend.write(
        "/run_1/custom_components/pricing-card/helper.ts",
        "export const value = 1;",
    )
    assert internal_alias.error is not None
    assert "read-only projection" in internal_alias.error
    assert entry.read_text() == "export default function Card() { return null; }"


# ============================================================================
# W-isolation — materializer (D2)
# ============================================================================


def _source_tree(tmp_path: Path) -> Path:
    src = tmp_path / "src_knowledge_docs"
    (src / "skills" / "create-design").mkdir(parents=True)
    (src / "skills" / "create-design" / "SKILL.md").write_text("skill", encoding="utf-8")
    (src / "knowledge" / "lumen-dsl").mkdir(parents=True)
    (src / "knowledge" / "lumen-dsl" / "grammar.md").write_text("g", encoding="utf-8")
    (src / "AGENT.md").write_text("# agent doc", encoding="utf-8")
    return src


def test_materialize_syncs_skills_knowledge_and_agent_doc(tmp_path):
    src = _source_tree(tmp_path)
    ws = tmp_path / "ws"
    config = types.SimpleNamespace(workspace_root=ws)

    materialize_agent_workspace(config, source_knowledge_docs=src)

    assert (ws / ".deepagent" / "AGENTS.md").read_text(encoding="utf-8") == "# agent doc"
    assert (ws / ".deepagent" / "skills" / "create-design" / "SKILL.md").exists()
    assert (ws / "knowledge_docs" / "knowledge" / "lumen-dsl" / "grammar.md").exists()
    # The knowledge copy includes the skills subtree (intra-doc refs resolve).
    assert (ws / "knowledge_docs" / "skills" / "create-design" / "SKILL.md").exists()
    assert (ws / ".deepagent" / ".sync-stamp").exists()


def test_materialize_is_idempotent_on_matching_stamp(tmp_path):
    src = _source_tree(tmp_path)
    ws = tmp_path / "ws"
    config = types.SimpleNamespace(workspace_root=ws)

    materialize_agent_workspace(config, source_knowledge_docs=src)
    # A sentinel that would be wiped by a re-sync (which rebuilds `.deepagent`).
    sentinel = ws / ".deepagent" / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")

    materialize_agent_workspace(config, source_knowledge_docs=src)
    assert sentinel.exists(), "matching stamp must skip the re-sync"


def test_materialize_resyncs_when_source_changes(tmp_path):
    src = _source_tree(tmp_path)
    ws = tmp_path / "ws"
    config = types.SimpleNamespace(workspace_root=ws)

    materialize_agent_workspace(config, source_knowledge_docs=src)
    sentinel = ws / ".deepagent" / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")

    # Change the source: the stamp no longer matches → full re-sync (wipes sentinel).
    (src / "skills" / "effects").mkdir(parents=True)
    (src / "skills" / "effects" / "SKILL.md").write_text("fx", encoding="utf-8")

    materialize_agent_workspace(config, source_knowledge_docs=src)
    assert not sentinel.exists(), "changed source must trigger a full re-sync"
    assert (ws / ".deepagent" / "skills" / "effects" / "SKILL.md").exists()


def test_materialize_loud_failure_on_missing_source(tmp_path):
    ws = tmp_path / "ws"
    config = types.SimpleNamespace(workspace_root=ws)
    with pytest.raises(RuntimeError, match="knowledge source tree missing"):
        materialize_agent_workspace(
            config, source_knowledge_docs=tmp_path / "does_not_exist"
        )


# ============================================================================
# Usage extraction (lives in `trace_callbacks` since the collector landed)
# ============================================================================
#
# Lane 3 slice 5 retired `lumen_agent.usage_capture` outright: per-call usage,
# cost and role attribution are the governed gateway's, and the design side now
# only COPIES those stamps onto a receipt (`lumen_agent.usage_collector`, tested
# in test_usage_collector.py). What survived the retirement is the LLMResult
# shape-tolerance below, which moved verbatim into `trace_callbacks`.


class _FakeUsageResult:
    """A minimal LLMResult-shaped object with a message whose usage_metadata
    OMITS total_tokens — proves the extractor computes the total itself. (A real
    `AIMessage` cannot omit it: pydantic requires the field.)"""

    class _Gen:
        def __init__(self, message):
            self.message = message

    class _Msg:
        def __init__(self, usage):
            self.usage_metadata = usage

    def __init__(self, usage):
        self.generations = [[self._Gen(self._Msg(usage))]]
        self.llm_output = None


def _llm_result_with_usage(input_tokens=120, output_tokens=48, total_tokens=168):
    """A real `LLMResult` carrying a valid `usage_metadata` (pydantic's
    `UsageMetadata` requires `total_tokens`, which real providers always set)."""
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, LLMResult

    usage = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }
    message = AIMessage(content="ok", usage_metadata=usage)
    return LLMResult(generations=[[ChatGeneration(message=message)]])


def test_extract_usage_from_llm_output_fallback():
    from langchain_core.outputs import LLMResult

    result = LLMResult(
        generations=[[]],
        llm_output={"token_usage": {"prompt_tokens": 7, "completion_tokens": 3}},
    )
    usage = extract_usage(result)
    assert usage == {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}


def test_extract_usage_reads_cached_and_reasoning_from_usage_metadata():
    """usage_metadata's provider-normalized detail sub-dicts surface as
    `cached_input_tokens` (input_token_details.cache_read) and
    `reasoning_output_tokens` (output_token_details.reasoning). Lane 3 slice 5
    publishes the cached count under the ledger's name too."""
    usage = {
        "input_tokens": 100,
        "output_tokens": 40,
        "total_tokens": 140,
        "input_token_details": {"cache_read": 80},
        "output_token_details": {"reasoning": 12},
    }
    result = extract_usage(_FakeUsageResult(usage))
    assert result["cached_input_tokens"] == 80
    assert result["cache_read_input_tokens"] == 80
    assert result["reasoning_output_tokens"] == 12
    assert result["input_tokens"] == 100


def test_extract_usage_reads_cached_and_reasoning_from_llm_output_raw():
    """OpenRouter/OpenAI raw usage nests the breakdowns under `*_tokens_details`
    (`prompt_tokens_details.cached_tokens`, `completion_tokens_details.
    reasoning_tokens`)."""
    from langchain_core.outputs import LLMResult

    result = LLMResult(
        generations=[[]],
        llm_output={
            "token_usage": {
                "prompt_tokens": 200,
                "completion_tokens": 60,
                "total_tokens": 260,
                "prompt_tokens_details": {"cached_tokens": 150},
                "completion_tokens_details": {"reasoning_tokens": 25},
            }
        },
    )
    usage = extract_usage(result)
    assert usage["cached_input_tokens"] == 150
    assert usage["cache_read_input_tokens"] == 150
    assert usage["reasoning_output_tokens"] == 25


def test_extract_usage_omits_cached_and_reasoning_when_absent():
    """No detail sub-dicts ⇒ the keys are OMITTED, never null/zero — preserving the
    payload's 'omit rather than null' convention."""
    usage = extract_usage(_llm_result_with_usage())
    assert "cached_input_tokens" not in usage
    assert "cache_read_input_tokens" not in usage
    assert "reasoning_output_tokens" not in usage


def test_no_usage_metadata_extracts_nothing():
    """A run must never fabricate zeros: no usage anywhere ⇒ None."""
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, LLMResult

    result = LLMResult(generations=[[ChatGeneration(message=AIMessage(content="hi"))]])
    assert extract_usage(result) is None


def test_instance_level_callbacks_fire_on_a_real_invoke():
    """langchain_core passes a model's own `.callbacks` into
    CallbackManager.configure as local_callbacks, so a handler appended to the
    instance fires without any wrapper — the mechanism `attach_trace_callback`
    and the ingestion brief agent both rely on (probe-r9: `.with_config` would
    return a RunnableBinding that deepagents' resolve_model kills construction
    on)."""
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    fired: list[str] = []

    class _Flag(BaseCallbackHandler):
        def on_llm_end(self, *a, **k):
            fired.append("end")

    model = FakeListChatModel(responses=["hi"])
    model.callbacks = [_Flag()]
    model.invoke("hello")
    assert fired == ["end"]


# ============================================================================
# Harness wiring (what the models carry, and what the invoke config carries)
# ============================================================================


def test_harness_retires_local_usage_capture_and_role_labels_at_the_gateway(
    tmp_path, monkeypatch
):
    """P3.2 (PD-part3 delta 6): the design-local usage-capture handler is RETIRED —
    the governed gateway's role-labelled ``model_call_usage`` record is the ONE
    usage authority, and attaching both would double count. The harness must hand
    deepagents models that carry no usage handler at all, thread the per-role
    gateway label through init_model instead, keep trace capture design-local,
    and still build three SEPARATE instances (gateway attribution is
    per-instance too).

    Lane 3 slice 5 adds the other half: the turn's ``ModelCallCollector`` rides the
    INVOKE CONFIG, not a model instance, so one handler sees every model, tool and
    sub-agent event in the graph. It only COPIES the gateway's stamps, so it is not
    a second usage authority."""
    import sys
    import types

    from agent_fixtures import FakeCoreClient, runtime_config

    captured: dict = {}

    def fake_create_deep_agent(**kwargs):
        captured["kwargs"] = kwargs

        def _invoke(*a, **k):
            captured["invoke_kwargs"] = k
            return {"messages": []}

        return types.SimpleNamespace(invoke=_invoke)

    class _FakeFilesystemPermission:
        def __init__(self, operations, paths, mode="allow"):
            self.operations, self.paths, self.mode = operations, paths, mode

    class _FakeFilesystemBackend:
        def __init__(self, root_dir, virtual_mode=None, max_file_size_mb=10):
            self.root_dir = root_dir

    module = types.ModuleType("deepagents")
    module.create_deep_agent = fake_create_deep_agent
    module.FilesystemPermission = _FakeFilesystemPermission
    module.DeepAgentState = type("_S", (dict,), {})
    backends = types.ModuleType("deepagents.backends")
    fsmod = types.ModuleType("deepagents.backends.filesystem")
    fsmod.FilesystemBackend = _FakeFilesystemBackend
    monkeypatch.setitem(sys.modules, "deepagents", module)
    monkeypatch.setitem(sys.modules, "deepagents.backends", backends)
    monkeypatch.setitem(sys.modules, "deepagents.backends.filesystem", fsmod)
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)

    # A REAL BaseChatModel per call (fresh instance per call mirrors the harness
    # contract), capturing every init_model kwarg so the gateway role label is
    # observable.
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    init_calls: list[dict] = []

    def fake_init_model(*args, **kwargs):
        init_calls.append(kwargs)
        return FakeListChatModel(responses=["ok"])

    monkeypatch.setattr("lumen_agent.llm.init_model", fake_init_model, raising=False)
    monkeypatch.setattr(
        "lumen_agent.llm.assert_all_role_models_support_image_input",
        lambda config: None,
        raising=False,
    )

    from lumen_agent.harness import run_deepagent_turn

    # The whole turn, not just construction: the collector attaches at the invoke
    # config, which only exists once the graph is actually invoked.
    run_deepagent_turn("Make a poster", runtime_config(tmp_path))
    kwargs = captured["kwargs"]

    from lumen_agent.trace_callbacks import TraceCallbackHandler
    from lumen_agent.usage_collector import ModelCallCollector

    def _usage_handlers(model):
        callbacks = getattr(model, "callbacks", None) or []
        return [cb for cb in callbacks if isinstance(cb, ModelCallCollector)]

    def _has_trace(model):
        callbacks = getattr(model, "callbacks", None) or []
        return any(isinstance(cb, TraceCallbackHandler) for cb in callbacks)

    subs = {s["name"]: s for s in kwargs["subagents"]}
    for model in (
        kwargs["model"],
        subs["lumen-dsl-author"]["model"],
        subs["lumen-visual-reviewer"]["model"],
    ):
        assert _usage_handlers(model) == []  # retired — the gateway is the authority
        assert _has_trace(model)  # non-usage trace capture stays design-local
    # The per-role label rides the GATEWAY build instead of a local callback.
    assert [call.get("role") for call in init_calls] == [
        "design_orchestrator",
        "design_author",
        "design_reviewer",
    ]
    # Three SEPARATE instances (no dedupe) — the orchestrator instance is not the
    # author instance even though ids match, so their handlers never cross-fire.
    assert kwargs["model"] is not subs["lumen-dsl-author"]["model"]
    assert subs["lumen-dsl-author"]["model"] is not subs["lumen-visual-reviewer"]["model"]
    # Lane 3 slice 5: the receipt collector is on the INVOKE CONFIG (see the docstring),
    # exactly once, and the turn publishes what it collected on the tools object.
    config_callbacks = captured["invoke_kwargs"]["config"]["callbacks"]
    assert len([cb for cb in config_callbacks if isinstance(cb, ModelCallCollector)]) == 1


# ============================================================================
# INTEGRATION-REGRESSION GUARD — probe-r9 CONSTRUCTION FAILURE
# ============================================================================
#
# This is the test that WOULD HAVE CAUGHT the incident and must never regress.
#
# The bug: the (now retired) usage-capture attach wrapped each role model via
# `.with_config(...)`,
# producing a RunnableBinding. deepagents' `resolve_model` passes through only
# `isinstance(model, BaseChatModel)`; a RunnableBinding is not one, so it fell to
# the string-spec path where `get_provider_profile(spec)` does `spec.count(":")`
# → `AttributeError('ChatOpenAI' object has no attribute 'count')`, killing EVERY
# turn at construction in <20s. The other harness tests all STUB create_deep_agent,
# so the wrapped object never met the real resolve_model — they were blind to it.
#
# This test runs the REAL deepagents (create_deep_agent + resolve_model), stubbing
# ONLY init_model (to a real ChatOpenAI that opens no socket at construction) and
# the multimodal probe (which would hit the network). If an attach helper ever
# returns a non-BaseChatModel again, resolve_model raises here and this fails.


def test_real_deepagents_construction_does_not_raise(tmp_path, monkeypatch):
    """Exercises the REAL deepagents resolve_model on exactly the model objects the
    harness passes it. NO deepagents stub. Regression guard for the probe-r9
    construction failure (RunnableBinding wrapper crashing get_provider_profile)."""
    from langchain_openai import ChatOpenAI

    from agent_fixtures import FakeCoreClient, runtime_config

    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)

    # A REAL ChatOpenAI per call: it is a BaseChatModel (what resolve_model demands)
    # and opens NO socket at construction, so this stays fully offline. A fresh
    # instance per call mirrors the harness's three-instances contract.
    def _real_chat_model(*a, **k):
        return ChatOpenAI(model="x", api_key="sk-test", base_url="http://localhost:1")

    monkeypatch.setattr(
        "lumen_agent.llm.init_model", _real_chat_model, raising=False
    )
    # The multimodal probe would hit OpenRouter over the network; no-op it. The
    # regression under test is resolve_model, not the probe.
    monkeypatch.setattr(
        "lumen_agent.llm.assert_all_role_models_support_image_input",
        lambda config: None,
        raising=False,
    )

    from lumen_agent.harness import create_design_deepagent

    # Must construct without raising — the whole point. Pre-fix this raised
    # AttributeError('ChatOpenAI' object has no attribute 'count') inside
    # deepagents.resolve_model.
    agent, tools = create_design_deepagent("Make a poster", runtime_config(tmp_path))
    assert agent is not None
    assert tools is not None
