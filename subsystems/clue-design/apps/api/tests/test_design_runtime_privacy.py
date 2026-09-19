"""Actual per-run filesystem cleanup; never erase a sibling or an active run."""

from types import SimpleNamespace

import pytest


def test_bound_workspace_is_not_purgeable_until_runtime_exits(tmp_path):
    from lumen_api.runtime_privacy import bind_runtime_workspace, purge_runtime_workspaces

    inner = "run_" + "1" * 32
    outer = "run_" + "2" * 32
    root = tmp_path / "runtime"
    path = root / "scene-candidate" / inner
    path.mkdir(parents=True)
    emitted = []

    def record(event, data):
        emitted.append({"event_type": event, "data": data})

    # A document-less turn threads on its own run id; it owns no session folder.
    target = SimpleNamespace(
        run_id=outer, checkpoint_thread_id=outer, result_json=None, events=emitted
    )
    with bind_runtime_workspace(
        workspace_id="ws_a",
        outer_run_id=outer,
        inner_run_id=inner,
        trace_dir=path,
        emit=record,
    ):
        (path / "echo.txt").write_text("An actual model echo of a preference")
        with pytest.raises(RuntimeError, match="active"):
            purge_runtime_workspaces(workspace_id="ws_a", runs=[target], roots=[root])
        assert path.exists()
    sibling = root / "scene-candidate" / ("run_" + "3" * 32)
    sibling.mkdir()
    (sibling / "echo.txt").write_text("unrelated")
    purge_runtime_workspaces(workspace_id="ws_a", runs=[target], roots=[root])
    assert not path.exists() and sibling.exists()
    purge_runtime_workspaces(workspace_id="ws_a", runs=[target], roots=[root])


@pytest.mark.parametrize("tamper", ["workspace", "path", "symlink"])
def test_purger_refuses_wrong_ownership_or_path(tmp_path, tamper):
    from lumen_api.runtime_privacy import bind_runtime_workspace, purge_runtime_workspaces

    root = tmp_path / "runtime"
    inner, outer = "run_" + "4" * 32, "run_" + "5" * 32
    path = root / inner
    path.mkdir(parents=True)
    emitted = []
    with bind_runtime_workspace(
        workspace_id="ws_a",
        outer_run_id=outer,
        inner_run_id=inner,
        trace_dir=path,
        emit=lambda event, data: emitted.append({"event_type": event, "data": data}),
    ):
        (path / "echo.txt").write_text("keep this on refusal")
    # A document-less turn threads on its own run id; it owns no session folder.
    target = SimpleNamespace(
        run_id=outer, checkpoint_thread_id=outer, result_json=None, events=emitted
    )
    roots = [tmp_path / "another-root"] if tamper == "path" else [root]
    if tamper == "symlink":
        moved = tmp_path / "elsewhere"
        path.rename(moved)
        path.symlink_to(moved, target_is_directory=True)
    with pytest.raises(RuntimeError):
        purge_runtime_workspaces(
            workspace_id="ws_b" if tamper == "workspace" else "ws_a",
            runs=[target],
            roots=roots,
        )
    assert (path / "echo.txt").exists()


def test_binding_failure_prevents_body_work(tmp_path):
    from lumen_api.runtime_privacy import bind_runtime_workspace

    path = tmp_path / ("run_" + "6" * 32)
    path.mkdir()

    def fail(*args):
        raise RuntimeError("durable event unavailable")

    with (
        pytest.raises(RuntimeError, match="durable event"),
        bind_runtime_workspace(
            workspace_id="ws_a",
            outer_run_id="run_" + "7" * 32,
            inner_run_id=path.name,
            trace_dir=path,
            emit=fail,
        ),
    ):
        pytest.fail("must bind durably before any private body work")


@pytest.mark.parametrize("name", [".runtime-active.lock", "run_binding.json"])
def test_binder_refuses_symlinked_custody_files_without_touching_target(tmp_path, name):
    from lumen_api.runtime_privacy import bind_runtime_workspace

    path = tmp_path / ("run_" + "8" * 32)
    path.mkdir()
    target = tmp_path / "protected"
    target.write_text("protected content")
    (path / name).symlink_to(target)
    with (
        pytest.raises(RuntimeError, match="runtime_owner_mismatch"),
        bind_runtime_workspace(
            workspace_id="ws_a",
            outer_run_id="run_" + "9" * 32,
            inner_run_id=path.name,
            trace_dir=path,
            emit=lambda *_: None,
        ),
    ):
        pytest.fail("a symlink must not establish runtime custody")
    assert target.read_text() == "protected content"


def _session_target(thread_id):
    """A run whose files are already gone: only its session folder is left to erase."""
    return SimpleNamespace(
        run_id="run_" + "a" * 32,
        checkpoint_thread_id=thread_id,
        result_json=None,
        events=(),
    )


def _plant_session(root, session_id):
    (root / "sessions" / session_id / "workspace").mkdir(parents=True)
    (root / "sessions" / session_id / "workspace" / "note.md").write_text("a model echo")
    (root / "conversation_history" / "media").mkdir(parents=True, exist_ok=True)
    (root / "conversation_history" / "media" / "sha256-abc.png").write_bytes(b"shared")
    (root / "conversation_history" / f"{session_id}.md").write_text("the conversation")


def test_session_folder_and_history_go_with_the_runs_under_every_root(tmp_path):
    from lumen_api.runtime_privacy import purge_runtime_workspaces

    session_id = "dsess_" + "b" * 32
    sibling = "dsess_" + "c" * 32
    roots = [tmp_path / "runtime", tmp_path / "runtime" / "scene-candidate"]
    for root in roots:
        _plant_session(root, session_id)
        _plant_session(root, sibling)

    purge_runtime_workspaces(workspace_id="ws_a", runs=[_session_target(session_id)], roots=roots)

    for root in roots:
        assert not (root / "sessions" / session_id).exists()
        assert not (root / "conversation_history" / f"{session_id}.md").exists()
        # Compaction media is shared and hash-named; another session still cites it.
        assert (root / "conversation_history" / "media" / "sha256-abc.png").exists()
        assert (root / "sessions" / sibling / "workspace" / "note.md").exists()
        assert (root / "conversation_history" / f"{sibling}.md").exists()


def test_a_run_keyed_thread_leaves_every_session_alone(tmp_path):
    from lumen_api.runtime_privacy import purge_runtime_workspaces

    session_id = "dsess_" + "d" * 32
    root = tmp_path / "runtime"
    _plant_session(root, session_id)
    # A document-less turn still threads on its own run id; it owns no session.
    legacy = "run_" + "e" * 32

    purge_runtime_workspaces(workspace_id="ws_a", runs=[_session_target(legacy)], roots=[root])

    assert (root / "sessions" / session_id / "workspace" / "note.md").exists()
    assert (root / "conversation_history" / f"{session_id}.md").exists()
    assert not (root / "sessions" / legacy).exists()


@pytest.mark.parametrize("link", ["folder", "sessions", "conversation_history"])
def test_a_symlinked_session_path_is_refused_not_followed(tmp_path, link):
    from lumen_api.runtime_privacy import purge_runtime_workspaces

    session_id = "dsess_" + "f" * 32
    root = tmp_path / "runtime"
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "workspace").mkdir(parents=True)
    (elsewhere / "workspace" / "note.md").write_text("not this host's to erase")
    root.mkdir(parents=True)
    if link == "folder":
        (root / "sessions").mkdir()
        (root / "sessions" / session_id).symlink_to(elsewhere, target_is_directory=True)
    else:
        # A symlinked CONTAINER is the same danger one level up: refuse the whole root rather
        # than erase the one real path beside it and call the erasure done.
        (root / link).symlink_to(elsewhere, target_is_directory=True)
        if link == "conversation_history":
            (root / "sessions" / session_id).mkdir(parents=True)

    with pytest.raises(RuntimeError, match="session_path"):
        purge_runtime_workspaces(
            workspace_id="ws_a", runs=[_session_target(session_id)], roots=[root]
        )

    assert (elsewhere / "workspace" / "note.md").exists()
    if link == "conversation_history":
        assert (root / "sessions" / session_id).exists()
