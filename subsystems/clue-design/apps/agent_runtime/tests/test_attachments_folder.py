"""The chat thread's files in a design agent's workspace (spec 2026-10-30 §3.3, §3.7).

Every design agent (ad, site, web) gets ``attachments/``: the files sent in its chat thread, rebuilt
every turn from what the platform hands over, and read-only — a person's file is never changed.
The turn's message names the files this message sent, so the agent knows what is new.

Nothing here imports the platform: a file is duck-typed, with the fields the platform's
``AttachedFile`` carries.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from lumen_agent.platform_reads import (
    ATTACHMENTS_DIR,
    DESIGN_ATTACHMENTS_MAX_BYTES,
    write_thread_attachments,
)


@dataclass(frozen=True)
class _File:
    filename: str
    data: bytes
    current: bool = True
    media_type: str = "application/octet-stream"
    sha256: str = "0" * 64
    viewable: tuple[bytes, str] | None = None
    unavailable: str | None = None


def _names(workspace: Path) -> list[str]:
    return sorted(path.name for path in (workspace / ATTACHMENTS_DIR).iterdir())


def test_the_folder_holds_exactly_this_turns_files(tmp_path: Path) -> None:
    write_thread_attachments(tmp_path, [_File("old.png", b"o")])
    note = write_thread_attachments(
        tmp_path,
        [_File("logo.png", b"\x89PNG", current=False), _File("brief.md", b"# Brief")],
    )
    assert _names(tmp_path) == ["brief.md", "logo.png"]
    assert (tmp_path / ATTACHMENTS_DIR / "brief.md").read_bytes() == b"# Brief"
    # This message's files are named first, then the rest of the chat's.
    assert note.index("brief.md") < note.index("logo.png")
    assert "attachments/" in note


def test_no_files_means_no_folder_and_no_note(tmp_path: Path) -> None:
    (tmp_path / ATTACHMENTS_DIR).mkdir()
    (tmp_path / ATTACHMENTS_DIR / "stale.png").write_bytes(b"x")
    assert write_thread_attachments(tmp_path, []) == ""
    assert not (tmp_path / ATTACHMENTS_DIR).exists()


def test_an_unavailable_file_is_named_with_its_reason_and_not_written(tmp_path: Path) -> None:
    note = write_thread_attachments(
        tmp_path,
        [_File("kept.pdf", b"%PDF"), _File("gone.png", b"", unavailable="erased")],
    )
    assert _names(tmp_path) == ["kept.pdf"]
    assert "gone.png" in note and "erased" in note


def test_a_name_that_climbs_lands_inside_the_folder(tmp_path: Path) -> None:
    write_thread_attachments(
        tmp_path,
        [_File("../escape.png", b"a"), _File("..\\win.png", b"b"), _File("ünï code.md", b"c")],
    )
    assert _names(tmp_path) == ["escape.png", "win.png", "ünï code.md"]
    assert not (tmp_path / "escape.png").exists()


def test_files_past_the_budget_are_named_not_dropped_silently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lumen_agent import platform_reads

    assert DESIGN_ATTACHMENTS_MAX_BYTES == 157_286_400
    monkeypatch.setattr(platform_reads, "DESIGN_ATTACHMENTS_MAX_BYTES", 10)
    note = write_thread_attachments(
        tmp_path,
        [_File("older.pdf", b"o" * 6, current=False), _File("this.pdf", b"t" * 6)],
    )
    # The current message's file is written first; the older one no longer fits.
    assert _names(tmp_path) == ["this.pdf"]
    assert "older.pdf" in note and "not included" in note.lower() and "150 MB" in note


def test_the_scene_and_web_agents_cannot_write_into_attachments(tmp_path: Path) -> None:
    from lumen_agent.fs_backend import AgentWorkspaceBackend

    workspace = tmp_path / "run_x" / "workspace"
    write_thread_attachments(workspace, [_File("brief.md", b"# Brief")])
    backend = AgentWorkspaceBackend(tmp_path, active_run_id="run_x")
    assert "read-only" in backend.write("/run_x/workspace/attachments/new.md", "x").error
    edited = backend.edit("/run_x/workspace/attachments/brief.md", "Brief", "Changed")
    assert "read-only" in edited.error
    assert (workspace / ATTACHMENTS_DIR / "brief.md").read_bytes() == b"# Brief"


def test_the_site_agent_cannot_write_into_attachments() -> None:
    from lumen_agent.site.harness import READ_ONLY
    from lumen_agent.site.workspace import REGENERATED

    assert "/attachments/**" in READ_ONLY
    assert "attachments" in REGENERATED


def test_a_kept_scene_session_folder_gets_the_new_set(tmp_path: Path, monkeypatch) -> None:
    from agent_fixtures import FakeCoreClient, runtime_config

    from lumen_agent.tools.substrate import LumenDesignTools
    from lumen_agent.workspace import scaffold_workspace, workspace_root

    class _Reads:
        files: tuple[_File, ...] = ()

        def seller_knowledge(self):
            raise RuntimeError("not_pinned")

        def thread_attachments(self):
            return self.files

    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    reads = _Reads()
    tools = LumenDesignTools(replace(runtime_config(tmp_path), platform_reads=reads), "Ad")
    reads.files = (_File("first.png", b"1"),)
    scaffold_workspace(tools, "Ad")
    reads.files = (_File("second.png", b"2"),)
    scaffold_workspace(tools, "Again")
    assert _names(workspace_root(tools)) == ["second.png"]
    assert "second.png" in tools.attachments_note


def test_the_site_workspace_writes_the_threads_files(tmp_path: Path) -> None:
    from site_fixtures import garner_site, inputs_for

    from lumen_agent.site.workspace import materialize_workspace

    class _Reads:
        def seller_knowledge(self):
            raise RuntimeError("not_pinned")

        def thread_attachments(self):
            return (_File("brief.md", b"# Hero brief"),)

    inputs = inputs_for(platform_reads=_Reads())
    summary = materialize_workspace(tmp_path, inputs, site=garner_site())
    assert (tmp_path / ATTACHMENTS_DIR / "brief.md").read_bytes() == b"# Hero brief"
    assert "brief.md" in summary["attachments_note"]
