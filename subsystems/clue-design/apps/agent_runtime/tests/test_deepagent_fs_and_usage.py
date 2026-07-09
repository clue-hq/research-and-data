"""RIDER 1 (filesystem escape hardening) + RIDER 2 (per-call token usage capture).

RIDER 1 exercises the REAL deepagents `FilesystemBackend` via our
`RepoRootedFilesystemBackend` subclass — no stubbing — so the containment guard is
proven against the actual resolution logic it wraps. Importing the backend at
module top pins its parent to the real class at collection time (before any other
test's deepagents stub runs).

RIDER 2 drives `UsageCaptureHandler.on_llm_end` with a stubbed `LLMResult` and a
minimal fake tools object to prove one trace event is recorded per usage-bearing
call, that role attribution rides through, and that a callback exception never
propagates.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lumen_agent.fs_backend import RepoRootedFilesystemBackend
from lumen_agent.usage_capture import (
    UsageCaptureHandler,
    _extract_usage,
    attach_usage_capture,
)


# ============================================================================
# RIDER 1 — FilesystemBackend escape hardening
# ============================================================================


@pytest.fixture
def rooted(tmp_path: Path):
    """A repo-rooted backend over a tmp workspace seeded with one readable file
    and a knowledge_docs subtree."""
    (tmp_path / "workspace").mkdir()
    (tmp_path / "workspace" / "brief.md").write_text("hello", encoding="utf-8")
    kd = tmp_path / "apps" / "agent_runtime" / "knowledge_docs"
    kd.mkdir(parents=True)
    (kd / "skill.md").write_text("# skill", encoding="utf-8")
    return tmp_path, RepoRootedFilesystemBackend(str(tmp_path))


def test_workspace_read_and_write_still_work(rooted):
    root, backend = rooted
    # read an existing workspace file
    result = backend.read(str(root / "workspace" / "brief.md"))
    assert result.error is None
    assert "hello" in (result.file_data or {}).get("content", "")

    # write a new workspace file
    target = root / "workspace" / "rounds" / "round-0" / "direction.md"
    write = backend.write(str(target), "do the thing")
    assert write.error is None
    assert target.read_text(encoding="utf-8") == "do the thing"

    # edit it back
    edit = backend.edit(str(target), "do the thing", "do it well")
    assert edit.error is None
    assert target.read_text(encoding="utf-8") == "do it well"


def test_knowledge_docs_read_still_works(rooted):
    root, backend = rooted
    result = backend.read(
        str(root / "apps" / "agent_runtime" / "knowledge_docs" / "skill.md")
    )
    assert result.error is None
    assert "# skill" in (result.file_data or {}).get("content", "")


def test_relative_dotdot_escape_rejected(rooted):
    root, backend = rooted
    result = backend.read("../../etc/hosts")
    assert result.error is not None
    assert "outside the permitted repository root" in result.error


def test_absolute_escape_read_rejected(rooted):
    root, backend = rooted
    result = backend.read("/etc/hosts")
    assert result.error is not None
    assert "outside the permitted repository root" in result.error


def test_absolute_escape_write_rejected_and_no_file_created(rooted, tmp_path):
    root, backend = rooted
    victim = tmp_path.parent / "escape_victim_should_not_exist.txt"
    result = backend.write(str(victim), "pwned")
    assert result.error is not None
    assert "outside the permitted repository root" in result.error
    assert not victim.exists()


def test_dotdot_climb_then_back_in_is_allowed(rooted):
    """`workspace/../workspace/brief.md` resolves back INSIDE root — it must be
    allowed (the guard rejects on the RESOLVED location, not on literal `..`)."""
    root, backend = rooted
    weird = str(root / "workspace" / ".." / "workspace" / "brief.md")
    result = backend.read(weird)
    assert result.error is None
    assert "hello" in (result.file_data or {}).get("content", "")


def test_symlink_pointing_outside_root_rejected(rooted, tmp_path):
    """A traversal-free path (no `..`, absolute-under-root) whose target is a
    symlink resolving OUTSIDE root must still be rejected."""
    root, backend = rooted
    outside = tmp_path.parent / "outside_secret.txt"
    outside.write_text("secret", encoding="utf-8")
    link = root / "workspace" / "link_to_secret.txt"
    link.symlink_to(outside)
    result = backend.read(str(link))
    assert result.error is not None
    assert "outside the permitted repository root" in result.error


def test_ls_escape_rejected_but_inside_works(rooted):
    root, backend = rooted
    outside = backend.ls("/etc")
    assert outside.error is not None
    assert "outside the permitted repository root" in outside.error

    inside = backend.ls(str(root / "workspace"))
    assert inside.error is None
    names = {Path(e["path"]).name for e in (inside.entries or [])}
    assert "brief.md" in names


def test_download_escape_rejected_inside_ok(rooted):
    root, backend = rooted
    responses = backend.download_files(
        ["/etc/hosts", str(root / "workspace" / "brief.md")]
    )
    by_name = {Path(r.path).name: r for r in responses}
    assert by_name["hosts"].error is not None
    assert by_name["hosts"].content is None
    assert by_name["brief.md"].error is None
    assert by_name["brief.md"].content == b"hello"


def test_upload_escape_rejected_inside_ok(rooted, tmp_path):
    root, backend = rooted
    victim = tmp_path.parent / "upload_escape_victim.txt"
    ok = root / "workspace" / "uploaded.txt"
    responses = backend.upload_files(
        [(str(victim), b"pwned"), (str(ok), b"legit")]
    )
    by_name = {Path(r.path).name: r for r in responses}
    assert by_name["upload_escape_victim.txt"].error is not None
    assert by_name["uploaded.txt"].error is None
    assert not victim.exists()
    assert ok.read_text(encoding="utf-8") == "legit"


def test_knowledge_docs_write_deny_still_expressible(rooted):
    """The guard does not interfere with the harness's write-deny permission:
    a write to a path UNDER root (knowledge_docs) is not rejected by the escape
    guard itself — the deny is enforced by deepagents' permission layer, which is
    orthogonal. Here we only confirm the guard permits the in-root path so the
    permission layer can then adjudicate it."""
    root, backend = rooted
    target = root / "apps" / "agent_runtime" / "knowledge_docs" / "new_skill.md"
    write = backend.write(str(target), "x")
    # The backend itself allows it (in-root); the write-deny is a separate layer.
    assert write.error is None


# ============================================================================
# RIDER 2 — per-model-call token usage capture
# ============================================================================


class _FakeTools:
    """Minimal stand-in for LumenDesignTools.record — accumulates events."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    def record(self, actor, event, input_summary=None, output_summary=None, diagnostics=None, payload=None):
        self.events.append(
            {
                "actor": actor,
                "event": event,
                "output_summary": output_summary,
                "payload": payload or {},
            }
        )


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


class _FakeUsageResult:
    """A minimal LLMResult-shaped object with a message whose usage_metadata
    OMITS total_tokens — proves the handler computes the total itself. (A real
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


def test_on_llm_end_records_one_usage_event_with_role():
    tools = _FakeTools()
    handler = UsageCaptureHandler(tools, role="author")
    handler.on_llm_end(_llm_result_with_usage())

    assert len(tools.events) == 1
    event = tools.events[0]
    assert event["event"] == "model_call_usage"
    assert event["payload"] == {
        "input_tokens": 120,
        "output_tokens": 48,
        "total_tokens": 168,
        "role": "author",
    }


def test_total_tokens_computed_when_absent():
    tools = _FakeTools()
    handler = UsageCaptureHandler(tools, role=None)
    handler.on_llm_end(_FakeUsageResult({"input_tokens": 10, "output_tokens": 5}))

    event = tools.events[0]
    assert event["payload"]["total_tokens"] == 15
    # No role recorded when attribution is not attempted.
    assert "role" not in event["payload"]


def test_no_usage_metadata_records_nothing():
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, LLMResult

    tools = _FakeTools()
    handler = UsageCaptureHandler(tools)
    result = LLMResult(generations=[[ChatGeneration(message=AIMessage(content="hi"))]])
    handler.on_llm_end(result)
    assert tools.events == []


def test_callback_exception_does_not_propagate_and_warns_once():
    class _BoomTools:
        def __init__(self):
            self.calls = []

        def record(self, actor, event, **kwargs):
            self.calls.append(event)
            if event == "model_call_usage":
                raise RuntimeError("record blew up")
            # the warning record itself succeeds

    tools = _BoomTools()
    handler = UsageCaptureHandler(tools, role="reviewer")
    # Must NOT raise.
    handler.on_llm_end(_llm_result_with_usage())
    handler.on_llm_end(_llm_result_with_usage())

    # A warning was recorded exactly once (warned flag), after the failed usage.
    assert tools.calls.count("model_call_usage_warning") == 1


def test_extract_usage_from_llm_output_fallback():
    from langchain_core.outputs import LLMResult

    result = LLMResult(
        generations=[[]],
        llm_output={"token_usage": {"prompt_tokens": 7, "completion_tokens": 3}},
    )
    usage = _extract_usage(result)
    assert usage == {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}


def test_attach_usage_capture_binds_callback_on_real_runnable():
    """A runnable with `.with_config` gets the handler bound; the returned object
    carries the handler in its config callbacks."""
    from langchain_core.runnables import RunnableLambda

    tools = _FakeTools()
    runnable = RunnableLambda(lambda x: x)
    wrapped = attach_usage_capture(runnable, tools, role="orchestrator")
    callbacks = (wrapped.config or {}).get("callbacks") or []
    assert any(isinstance(cb, UsageCaptureHandler) for cb in callbacks)


def test_attach_usage_capture_passes_through_object_without_with_config():
    """A plain object (test sentinel) without `.with_config` is returned as-is so
    assembly and dedupe-by-identity are never disturbed."""
    tools = _FakeTools()
    sentinel = object()
    assert attach_usage_capture(sentinel, tools, role="author") is sentinel


def test_wired_handler_records_role_when_invoked_through_config():
    """End-to-end within the callback machinery: invoking a RunnableLambda that
    is a chat-model stand-in won't emit usage, so drive the handler through
    LangChain's config-callback path with a manual on_llm_end to confirm the
    attach wiring produces a usable handler carrying the role."""
    tools = _FakeTools()
    from langchain_core.runnables import RunnableLambda

    wrapped = attach_usage_capture(RunnableLambda(lambda x: x), tools, role="reviewer")
    handler = next(
        cb
        for cb in (wrapped.config or {}).get("callbacks", [])
        if isinstance(cb, UsageCaptureHandler)
    )
    handler.on_llm_end(_llm_result_with_usage(total_tokens=200))
    assert tools.events[0]["payload"]["role"] == "reviewer"
    assert tools.events[0]["payload"]["total_tokens"] == 200


# ============================================================================
# RIDER 2 — harness wiring (models handed to deepagents carry the capture handler)
# ============================================================================


def test_harness_attaches_usage_capture_to_all_three_role_models(tmp_path, monkeypatch):
    """create_design_deepagent must hand deepagents models whose config carries a
    UsageCaptureHandler — one per role, with the role label — when the underlying
    model supports `.with_config` (real chat models do)."""
    import sys
    import types

    from agent_fixtures import FakeCoreClient, runtime_config

    captured: dict = {}

    def fake_create_deep_agent(**kwargs):
        captured["kwargs"] = kwargs
        return types.SimpleNamespace(invoke=lambda *a, **k: {"messages": []})

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

    # A model stand-in that DOES support .with_config, like a real chat model, so
    # attach_usage_capture actually binds the handler.
    from langchain_core.runnables import RunnableLambda

    monkeypatch.setattr(
        "lumen_agent.llm.init_model",
        lambda *a, **k: RunnableLambda(lambda x: x),
        raising=False,
    )
    monkeypatch.setattr(
        "lumen_agent.llm.assert_all_role_models_support_image_input",
        lambda config: None,
        raising=False,
    )

    from lumen_agent.harness import create_design_deepagent

    create_design_deepagent("Make a poster", runtime_config(tmp_path))
    kwargs = captured["kwargs"]

    def _roles_on(model):
        callbacks = (getattr(model, "config", {}) or {}).get("callbacks") or []
        return {cb._role for cb in callbacks if isinstance(cb, UsageCaptureHandler)}

    assert _roles_on(kwargs["model"]) == {"orchestrator"}
    subs = {s["name"]: s for s in kwargs["subagents"]}
    assert _roles_on(subs["lumen-dsl-author"]["model"]) == {"author"}
    assert _roles_on(subs["lumen-visual-reviewer"]["model"]) == {"reviewer"}
