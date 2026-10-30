"""A design session survives a worker change: its folder is synced to storage and restored.

Design session continuity (2026-09-18). The session folder lives on ONE worker's disk, so a
turn that lands on a different worker would otherwise open a continued thread over an empty
workspace. At turn end the agent-visible ``workspace/`` tree and the deepagents conversation
history are registered as content-addressed blobs and described by a manifest; at turn start a
missing session folder is rebuilt from the newest succeeded run's manifest.

What does NOT travel: ``turns/<run_id>/`` (observability, not continuity), files over
``MAX_FILE_BYTES``, and symlinks.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from lumen_agent.session_sync import MAX_FILE_BYTES, restore_session, snapshot_session


class _Blobs:
    """The design blob store's two shapes, in miniature: register for custody, read by digest."""

    def __init__(self) -> None:
        self.store: dict[str, tuple[str, bytes]] = {}

    def register(self, data: bytes, media_type: str, source_key: str) -> str:
        sha = hashlib.sha256(data).hexdigest()
        self.store[sha] = (media_type, data)
        return sha

    def read_blob(self, sha: str) -> tuple[str, bytes]:
        return self.store[sha]


def test_snapshot_covers_workspace_and_history_and_skips_turn_outputs(tmp_path: Path) -> None:
    session = tmp_path / "sessions" / "dsess_a"
    (session / "workspace" / "rounds").mkdir(parents=True)
    (session / "workspace" / "brief.md").write_text("brief", encoding="utf-8")
    (session / "workspace" / "rounds" / "round_1.png").write_bytes(b"\x89PNG")
    (session / "turns" / "run_1").mkdir(parents=True)
    (session / "turns" / "run_1" / "trace.jsonl").write_text("x", encoding="utf-8")
    history = tmp_path / "conversation_history" / "dsess_a.md"
    history.parent.mkdir()
    history.write_text("summary", encoding="utf-8")
    blobs = _Blobs()
    manifest = snapshot_session(session, register=blobs.register, history_file=history)
    assert set(manifest["files"]) == {
        "workspace/brief.md",
        "workspace/rounds/round_1.png",
        "conversation_history/dsess_a.md",
    }
    assert manifest["files"]["workspace/rounds/round_1.png"]["media_type"] == "image/png"


def test_restore_rebuilds_a_missing_session_folder(tmp_path: Path) -> None:
    session = tmp_path / "sessions" / "dsess_b"
    (session / "workspace").mkdir(parents=True)
    (session / "workspace" / "brief.md").write_text("brief", encoding="utf-8")
    history = tmp_path / "conversation_history" / "dsess_b.md"
    history.parent.mkdir()
    history.write_text("summary", encoding="utf-8")
    blobs = _Blobs()
    manifest = snapshot_session(session, register=blobs.register, history_file=history)
    import shutil

    shutil.rmtree(session)
    history.unlink()
    restored = restore_session(session, manifest, read_blob=blobs.read_blob, history_file=history)
    assert restored == 2
    assert (session / "workspace" / "brief.md").read_text() == "brief"
    assert history.read_text() == "summary"


def test_the_manifest_digest_is_the_files_own_sha256(tmp_path: Path) -> None:
    """The manifest keys on the DIGEST, never on whatever ``register`` hands back — the
    production store returns a storage KEY (``{ws}/design/{sha}``) and ``read_blob`` takes a
    digest, so a manifest built from the return value could not be read back."""

    session = tmp_path / "sessions" / "dsess_c"
    (session / "workspace").mkdir(parents=True)
    (session / "workspace" / "brief.md").write_text("brief", encoding="utf-8")
    keys: list[str] = []

    def register(data: bytes, media_type: str, source_key: str) -> str:
        keys.append(source_key)
        return "ws/design/" + hashlib.sha256(data).hexdigest()

    manifest = snapshot_session(session, register=register, history_file=None)
    entry = manifest["files"]["workspace/brief.md"]
    assert entry["sha256"] == hashlib.sha256(b"brief").hexdigest()
    assert entry["size"] == len(b"brief")
    assert keys == ["design-session/workspace/brief.md"]


def test_symlinks_and_oversize_files_never_travel(tmp_path: Path) -> None:
    """A symlink is a pointer into a host filesystem the next worker does not have, and an
    oversize file is a turn's own scratch output — neither is session memory."""

    session = tmp_path / "sessions" / "dsess_d"
    workspace = session / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "brief.md").write_text("brief", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("elsewhere", encoding="utf-8")
    (workspace / "link.txt").symlink_to(outside)
    # Sparse: the size is what is checked, and a real file one byte over the cap would be 500 MB.
    with (workspace / "huge.bin").open("wb") as huge:
        huge.truncate(MAX_FILE_BYTES + 1)
    manifest = snapshot_session(session, register=_Blobs().register, history_file=None)
    assert set(manifest["files"]) == {"workspace/brief.md"}


def test_a_tampered_blob_is_refused_rather_than_written(tmp_path: Path) -> None:
    """Restore verifies what it writes: a session folder rebuilt from bytes that do not hash to
    the manifest's digest is not this session's memory, and writing it would be a silent lie."""

    session = tmp_path / "sessions" / "dsess_e"
    (session / "workspace").mkdir(parents=True)
    (session / "workspace" / "brief.md").write_text("brief", encoding="utf-8")
    blobs = _Blobs()
    manifest = snapshot_session(session, register=blobs.register, history_file=None)
    import shutil

    shutil.rmtree(session)
    with pytest.raises(RuntimeError, match="digest mismatch"):
        restore_session(
            session,
            manifest,
            read_blob=lambda _sha: ("text/markdown", b"tampered"),
            history_file=None,
        )
    assert not (session / "workspace" / "brief.md").exists()


def test_a_snapshot_can_leave_out_regenerated_folders(tmp_path: Path) -> None:
    session = tmp_path / "sessions" / "dsess_site"
    workspace = session / "workspace"
    (workspace / "research").mkdir(parents=True)
    (workspace / "fetched").mkdir()
    (workspace / "plan.md").write_text("plan", encoding="utf-8")
    (workspace / "page.json").write_text("{}", encoding="utf-8")
    (workspace / "research" / "overview.md").write_text("old research", encoding="utf-8")
    (workspace / "fetched" / "story.md").write_text("evidence", encoding="utf-8")
    manifest = snapshot_session(session, register=_Blobs().register, history_file=None,
                                exclude=frozenset({"research", "page.json"}))
    assert set(manifest["files"]) == {"workspace/plan.md", "workspace/fetched/story.md"}
    # The default leaves out nothing, byte-identical to the web and scene lanes.
    everything = snapshot_session(session, register=_Blobs().register, history_file=None)
    assert "workspace/research/overview.md" in everything["files"]


def test_the_chats_files_never_travel_in_a_session_snapshot(tmp_path: Path) -> None:
    """Review I-2 (2026-10-30): attachments/ is rebuilt from the platform every turn, so a copy in
    the session's memory is churn, and a second copy of a file the person may later erase."""

    session = tmp_path / "sessions" / "dsess_b"
    (session / "workspace" / "attachments").mkdir(parents=True)
    (session / "workspace" / "attachments" / "brief.pdf").write_bytes(b"%PDF-1.4")
    (session / "workspace" / "outputs").mkdir()
    (session / "workspace" / "outputs" / "chart.png").write_bytes(b"\x89PNG")
    manifest = snapshot_session(session, register=_Blobs().register, history_file=None)
    assert set(manifest["files"]) == {"workspace/outputs/chart.png"}
