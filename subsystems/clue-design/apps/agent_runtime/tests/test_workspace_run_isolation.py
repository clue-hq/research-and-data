"""Real SDK filesystem boundaries for independent scene runs; no providers."""

from dataclasses import replace

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from lumen_agent import harness
from lumen_agent.fs_backend import AgentWorkspaceBackend
from lumen_agent.workspace import initial_turn_state
from test_scene_catalog_runtime import call
from test_scene_solo_runtime import offline_models, solo_config


@pytest.mark.parametrize("solo", [True, False])
def test_scene_factory_read_file_cannot_read_previous_brand_run(tmp_path, monkeypatch, solo):
    responses = [
        call("read_file", {"file_path": "/run_previous/workspace/critique.json"}, "sibling"),
        AIMessage(content="Finished filesystem check."),
    ]
    offline_models(monkeypatch, responses)
    config = replace(solo_config(tmp_path), scene_solo=solo)
    graph, tools = harness.create_design_deepagent("Make a square ad", config)
    sibling = tools.config.workspace_root / "run_previous/workspace/critique.json"
    sibling.parent.mkdir(parents=True)
    sibling.write_text("PRIVATE_PREVIOUS_BRAND_CRITIQUE")

    result = graph.invoke(initial_turn_state(tools, "Make a square ad"))
    output = next(
        message.content
        for message in result["messages"]
        if isinstance(message, ToolMessage) and message.tool_call_id == "sibling"
    )
    assert "PRIVATE_PREVIOUS_BRAND_CRITIQUE" not in str(output)
    assert "current run" in str(output).lower()


@pytest.fixture
def scoped_workspace(tmp_path):
    for name, content in {
        "run_active/workspace/brief.md": "CURRENT shared-token",
        "run_sibling/workspace/critique.md": "PRIVATE_SIBLING shared-token",
        "knowledge_docs/guide.md": "GUIDE shared-token",
        ".deepagent/skills/example/SKILL.md": "SKILL shared-token",
        "custom_components/example.md": "COMPONENT shared-token",
        "unrelated.md": "PRIVATE_ROOT shared-token",
    }.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    (tmp_path / "run_active/link").symlink_to(tmp_path / "run_sibling", target_is_directory=True)
    (tmp_path / "knowledge_docs/link").symlink_to(
        tmp_path / "run_sibling", target_is_directory=True
    )
    (tmp_path / "knowledge_docs/leak.md").symlink_to(tmp_path / "run_sibling/workspace/critique.md")
    (tmp_path / "run_active/shared").symlink_to(
        tmp_path / "knowledge_docs", target_is_directory=True
    )
    return tmp_path, AgentWorkspaceBackend(tmp_path, active_run_id="run_active")


def _alias(root, path, alias):
    if alias == "host":
        return str(root / path)
    if alias == "legacy":
        return ".lumen-runs/" + path
    if alias == "relative":
        return path
    return "/" + path


@pytest.mark.parametrize("alias", ["virtual", "relative", "host", "legacy"])
@pytest.mark.parametrize(
    "path",
    [
        "run_sibling/workspace/critique.md",
        "run_active/link/workspace/critique.md",
        "knowledge_docs/link/workspace/critique.md",
        "knowledge_docs/leak.md",
        "unrelated.md",
    ],
)
def test_read_and_download_reject_siblings_and_symlink_aliases(scoped_workspace, alias, path):
    root, backend = scoped_workspace
    key = _alias(root, path, alias)
    read = backend.read(key)
    download = backend.download_files([key])[0]
    assert read.error and not read.file_data
    assert download.error and download.content is None


@pytest.mark.parametrize("operation", ["write", "edit", "upload"])
@pytest.mark.parametrize("alias", ["virtual", "relative", "host", "legacy"])
@pytest.mark.parametrize(
    "path",
    [
        "run_sibling/workspace/critique.md",
        "run_active/link/workspace/critique.md",
        "knowledge_docs/guide.md",
        ".deepagent/skills/example/SKILL.md",
        "custom_components/example.md",
        "run_active/shared/guide.md",
    ],
)
def test_mutation_cannot_change_siblings_or_shared_documents(
    scoped_workspace, operation, alias, path
):
    root, backend = scoped_workspace
    target = root / path
    original = target.read_bytes()
    # write() creates new files; edit/upload exercise replacement of existing ones.
    key = _alias(root, path + ".new" if operation == "write" else path, alias)
    if operation == "write":
        result = backend.write(key, "MUTATED")
    elif operation == "edit":
        result = backend.edit(key, "shared-token", "MUTATED")
    else:
        result = backend.upload_files([(key, b"MUTATED")])[0]
    assert result.error
    assert target.read_bytes() == original
    assert not (root / (path + ".new")).exists()


@pytest.mark.parametrize("alias", ["virtual", "relative", "host", "legacy"])
def test_current_run_aliases_and_shared_reads_remain_usable(scoped_workspace, alias):
    root, backend = scoped_workspace
    key = _alias(root, "run_active/workspace/new.md", alias)
    assert backend.write(key, "FIRST").error is None
    assert backend.edit(key, "FIRST", "SECOND").error is None
    assert backend.upload_files([(key, b"THIRD")])[0].error is None
    assert backend.read(key).file_data["content"] == "THIRD"
    assert backend.download_files([key])[0].content == b"THIRD"
    for shared in [
        "knowledge_docs/guide.md",
        ".deepagent/skills/example/SKILL.md",
        "custom_components/example.md",
    ]:
        assert backend.read(_alias(root, shared, alias)).error is None


@pytest.mark.parametrize("path", [None, "/", ".", "host", ".lumen-runs/"])
@pytest.mark.parametrize("python_fallback", [False, True])
def test_root_discovery_never_searches_sibling_tree(
    scoped_workspace, monkeypatch, path, python_fallback
):
    from deepagents.backends.filesystem import FilesystemBackend

    root, backend = scoped_workspace
    path = str(root) if path == "host" else path
    traversed = []
    for operation in ("ls", "glob", "grep"):
        original = getattr(FilesystemBackend, operation)

        def traced(self, *args, _operation=operation, _original=original, **kwargs):
            base = (
                args[0]
                if _operation == "ls"
                else kwargs.get("path", args[1] if len(args) > 1 else None)
            )
            traversed.append(self._resolve_path(base or "."))
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(FilesystemBackend, operation, traced)
    if python_fallback:
        monkeypatch.setattr(backend, "_ripgrep_search", lambda *args: None)

    listing = backend.ls(path or "/")
    files = backend.glob("**/*.md", path=path)
    matches = backend.grep("shared-token", path=path, glob="**/*.md")
    assert not listing.error and not files.error and not matches.error
    assert "run_sibling" not in str(listing.entries)
    expected = {
        "/run_active/workspace/brief.md",
        "/knowledge_docs/guide.md",
        "/.deepagent/skills/example/SKILL.md",
        "/custom_components/example.md",
    }
    assert {entry["path"] for entry in files.matches} == expected
    assert {match["path"] for match in matches.matches} == expected
    assert "PRIVATE" not in str(matches.matches)
    assert traversed and all(
        path != root and not path.is_relative_to(root / "run_sibling") for path in traversed
    )


def test_root_glob_filters_preserve_root_qualified_patterns(scoped_workspace):
    _, backend = scoped_workspace
    for pattern in ["knowledge_docs/*.md", "knowledge*/*.md", "/knowledge_docs/*.md"]:
        result = backend.glob(pattern)
        assert [entry["path"] for entry in result.matches] == ["/knowledge_docs/guide.md"]
    result = backend.grep("shared-token", glob="knowledge_docs/*.md")
    assert [entry["path"] for entry in result.matches] == ["/knowledge_docs/guide.md"]


def test_legacy_knowledge_alias_cannot_bypass_backend_readonly(scoped_workspace):
    root, backend = scoped_workspace
    key = "/repo/apps/agent_runtime/knowledge_docs/guide.md"
    assert backend.read(key).error is None
    assert backend.edit(key, "GUIDE", "MUTATED").error
    assert backend.upload_files([(key, b"MUTATED")])[0].error
    assert (root / "knowledge_docs/guide.md").read_text().startswith("GUIDE")


def test_unscoped_backend_retains_website_workspace_contract(scoped_workspace):
    root, _ = scoped_workspace
    backend = AgentWorkspaceBackend(root)
    assert backend.read("/run_sibling/workspace/critique.md").error is None
    assert backend.write("/scratch.md", "website scratch").error is None


@pytest.mark.parametrize(
    "path", ["/run_sibling", "/run_active/link", "/knowledge_docs/link", "/run_active/root_link"]
)
def test_explicit_recursive_paths_cannot_resolve_to_sibling_or_workspace_root(
    scoped_workspace, path
):
    root, backend = scoped_workspace
    (root / "run_active/root_link").symlink_to(root, target_is_directory=True)
    for result in [backend.ls(path), backend.glob("**/*.md", path), backend.grep("PRIVATE", path)]:
        assert result.error
        assert "PRIVATE" not in str(result)


def test_custom_projection_stays_readonly_inside_current_run(scoped_workspace):
    root, _ = scoped_workspace
    projection = root / "run_active/registry"
    projection.mkdir()
    (projection / "example.md").write_text("COMPONENT")
    backend = AgentWorkspaceBackend(
        root, active_run_id="run_active", custom_components_root=projection
    )
    for key in [
        "/custom_components/example.md",
        "custom_components/example.md",
        str(projection / "example.md"),
    ]:
        assert backend.read(key).file_data["content"] == "COMPONENT"
        assert backend.edit(key, "COMPONENT", "MUTATED").error
        assert backend.upload_files([(key, b"MUTATED")])[0].error


def test_custom_projection_cannot_grant_a_sibling_run(scoped_workspace):
    root, _ = scoped_workspace
    with pytest.raises(ValueError, match="current run"):
        AgentWorkspaceBackend(
            root, active_run_id="run_active", custom_components_root=root / "run_sibling"
        )


def test_scoped_grep_does_not_read_symlink_targets_via_host_ripgrep_config(
    scoped_workspace, monkeypatch, tmp_path
):
    import subprocess

    root, backend = scoped_workspace
    rg_config = tmp_path / "rg-config"
    rg_config.write_text("--follow\n")
    monkeypatch.setenv("RIPGREP_CONFIG_PATH", str(rg_config))
    original_run = subprocess.run
    scanned = []

    def capture(*args, **kwargs):
        result = original_run(*args, **kwargs)
        scanned.append(result.stdout)
        return result

    monkeypatch.setattr(subprocess, "run", capture)
    result = backend.grep("shared-token", path="/knowledge_docs")
    assert not result.error
    assert [entry["path"] for entry in result.matches] == ["/knowledge_docs/guide.md"]
    assert "PRIVATE_SIBLING" not in str(scanned)


def test_root_grep_accepts_filename_globs(scoped_workspace):
    _, backend = scoped_workspace
    result = backend.grep("shared-token", glob="*.{md,json}")
    assert {entry["path"] for entry in result.matches} == {
        "/run_active/workspace/brief.md",
        "/knowledge_docs/guide.md",
        "/.deepagent/skills/example/SKILL.md",
        "/custom_components/example.md",
    }


def test_unscoped_relative_alias_cannot_modify_website_projection(tmp_path):
    projection = tmp_path / "run_web/registry"
    projection.mkdir(parents=True)
    source = projection / "component.md"
    source.write_text("ORIGINAL")
    backend = AgentWorkspaceBackend(tmp_path, custom_components_root=projection)
    result = backend.edit("custom_components/component.md", "ORIGINAL", "MUTATED")
    assert result.error
    assert source.read_text() == "ORIGINAL"


# --- design session continuity: a session folder is the scope --------------
# One design document = one persistent design-agent session, so a leg turn is
# scoped to `sessions/<session_id>` rather than to its own run folder. The
# deepagents summarization middleware compacts that thread into
# `/conversation_history/<thread_id>.md` (media under
# `/conversation_history/media/`) through THIS backend, so the fence has to
# admit the ACTIVE session's history file — and only that one: a sibling
# session's history is another tenant's conversation.
def test_a_session_scope_admits_its_own_history_file_and_nothing_else(tmp_path):
    root = tmp_path
    (root / "sessions/dsess_a/workspace").mkdir(parents=True)
    (root / "conversation_history").mkdir()
    (root / "conversation_history/dsess_b.md").write_text("PRIVATE_OTHER_SESSION")
    backend = AgentWorkspaceBackend(
        root, active_run_id="sessions/dsess_a", history_thread_id="dsess_a"
    )

    assert backend.write("/conversation_history/dsess_a.md", "mine").error is None
    assert (root / "conversation_history/dsess_a.md").read_text() == "mine"
    assert backend.read("/conversation_history/dsess_a.md").file_data["content"] == "mine"
    assert backend.edit("/conversation_history/dsess_a.md", "mine", "mine and more").error is None
    assert backend.upload_files([("/conversation_history/media/a.png", b"bytes")])[0].error is None
    assert (root / "conversation_history/media/a.png").read_bytes() == b"bytes"

    sibling = backend.read("/conversation_history/dsess_b.md")
    assert sibling.error and not sibling.file_data
    assert "PRIVATE_OTHER_SESSION" not in str(sibling)
    assert backend.download_files(["/conversation_history/dsess_b.md"])[0].error
    assert backend.write("/conversation_history/dsess_b.md", "x").error
    assert backend.edit("/conversation_history/dsess_b.md", "PRIVATE", "x").error
    assert backend.upload_files([("/conversation_history/dsess_b.md", b"x")])[0].error
    assert (root / "conversation_history/dsess_b.md").read_text() == "PRIVATE_OTHER_SESSION"


def test_a_session_scope_still_fences_sibling_sessions(tmp_path):
    root = tmp_path
    for name in ("dsess_a", "dsess_b"):
        (root / "sessions" / name / "workspace").mkdir(parents=True)
    (root / "sessions/dsess_b/workspace/brief.md").write_text("PRIVATE_SIBLING_SESSION")
    backend = AgentWorkspaceBackend(root, active_run_id="sessions/dsess_a")

    read = backend.read("/sessions/dsess_b/workspace/brief.md")
    assert read.error and not read.file_data
    assert "PRIVATE_SIBLING_SESSION" not in str(read)
    assert backend.write("/sessions/dsess_b/workspace/note.md", "x").error
    assert not (root / "sessions/dsess_b/workspace/note.md").exists()
    # `sessions/` itself is a container, never a scope root.
    assert backend.ls("/sessions").error
    # Its own session folder stays read-write, and the error names the real path.
    assert backend.write("/sessions/dsess_a/workspace/note.md", "ok").error is None
    assert "/sessions/dsess_a/" in str(backend.write("/unrelated.md", "x").error)


def test_without_a_thread_id_a_session_reaches_no_conversation_history(tmp_path):
    root = tmp_path
    (root / "sessions/dsess_a/workspace").mkdir(parents=True)
    (root / "conversation_history").mkdir()
    (root / "conversation_history/dsess_a.md").write_text("PRIVATE_HISTORY")
    backend = AgentWorkspaceBackend(root, active_run_id="sessions/dsess_a")

    assert backend.read("/conversation_history/dsess_a.md").error
    assert backend.write("/conversation_history/dsess_a.md", "x").error
    assert backend.write("/conversation_history/media/a.png", "x").error
    assert (root / "conversation_history/dsess_a.md").read_text() == "PRIVATE_HISTORY"


@pytest.mark.parametrize(
    "scope",
    [
        "sessions",
        "sessions/",
        "sessions/../run_other",
        "sessions/a/b",
        "/sessions/dsess_a",
        "other/dsess_a",
        "dsess_a",
        "sessions\\dsess_a",
    ],
)
def test_only_a_run_folder_or_a_session_folder_can_scope_the_backend(tmp_path, scope):
    with pytest.raises(ValueError):
        AgentWorkspaceBackend(tmp_path, active_run_id=scope)


@pytest.mark.parametrize("thread", ["", ".", "..", "../dsess_a", "a/b", "sub\\a"])
def test_a_history_thread_id_is_one_file_name_segment(tmp_path, thread):
    with pytest.raises(ValueError):
        AgentWorkspaceBackend(tmp_path, active_run_id="sessions/dsess_a", history_thread_id=thread)


# --- the seller's pinned knowledge is READ-ONLY to the agent (2026-09-19) ---
# `workspace/seller/` is written once per session by the runtime from the platform's pinned
# reads. It is the seller's own knowledge, not the agent's scratch space: an agent that could
# edit it could rewrite what the brand says about itself and then design against its own words.
def test_a_session_scope_reads_seller_knowledge_but_cannot_write_it(tmp_path):
    root = tmp_path
    seller = root / "sessions/dsess_a/workspace/seller"
    seller.mkdir(parents=True)
    (seller / "x.md").write_text("PINNED_SELLER_TRUTH")
    backend = AgentWorkspaceBackend(root, active_run_id="sessions/dsess_a")

    read = backend.read("/sessions/dsess_a/workspace/seller/x.md")
    assert read.error is None
    assert "PINNED_SELLER_TRUTH" in read.file_data["content"]

    edit = backend.edit("/sessions/dsess_a/workspace/seller/x.md", "PINNED", "REWRITTEN")
    assert edit.error and "read-only" in str(edit.error).lower()
    new_file = backend.write("/sessions/dsess_a/workspace/seller/new/note.md", "x")
    assert new_file.error and "read-only" in str(new_file.error).lower()
    assert not (seller / "new").exists()
    assert backend.upload_files([("/sessions/dsess_a/workspace/seller/logo.png", b"x")])[0].error
    assert (seller / "x.md").read_text() == "PINNED_SELLER_TRUTH"
    # The rest of the session workspace stays read-write.
    assert backend.write("/sessions/dsess_a/workspace/note.md", "ok").error is None


def test_a_run_scope_fences_seller_knowledge_the_same_way(tmp_path):
    root = tmp_path
    seller = root / "run_active/workspace/seller"
    seller.mkdir(parents=True)
    (seller / "index.md").write_text("PINNED_SELLER_INDEX")
    backend = AgentWorkspaceBackend(root, active_run_id="run_active")

    assert backend.read("/run_active/workspace/seller/index.md").error is None
    assert backend.edit("/run_active/workspace/seller/index.md", "PINNED", "x").error
    assert backend.write("/run_active/workspace/seller/note.md", "x").error
    assert (seller / "index.md").read_text() == "PINNED_SELLER_INDEX"
    assert backend.write("/run_active/workspace/note.md", "ok").error is None


def test_an_unscoped_backend_still_fences_seller_knowledge(tmp_path):
    """Website mode keeps an unscoped workspace contract, and the seller tree lives there too."""
    root = tmp_path
    seller = root / "run_web/workspace/seller"
    seller.mkdir(parents=True)
    (seller / "index.md").write_text("PINNED_SELLER_INDEX")
    backend = AgentWorkspaceBackend(root)

    assert backend.read("/run_web/workspace/seller/index.md").error is None
    write = backend.write("/run_web/workspace/seller/note.md", "x")
    assert write.error and "read-only" in str(write.error).lower()
    assert backend.edit("/run_web/workspace/seller/index.md", "PINNED", "x").error
    assert (seller / "index.md").read_text() == "PINNED_SELLER_INDEX"
    assert backend.write("/run_web/workspace/note.md", "ok").error is None
