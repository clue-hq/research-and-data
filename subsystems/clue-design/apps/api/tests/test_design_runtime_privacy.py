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

    target = SimpleNamespace(run_id=outer, result_json=None, events=emitted)
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
    target = SimpleNamespace(run_id=outer, result_json=None, events=emitted)
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
