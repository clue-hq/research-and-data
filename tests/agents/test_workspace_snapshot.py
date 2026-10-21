"""F3 Phase 1, plan Task 2: the snapshot file list, its tiers and its path rules (spec WS-2, WS-4,
WS-5; AW-14)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from clue_agents.workspace_snapshot import (
    MANIFEST_MEDIA_TYPE,
    SAVED_FOLDERS,
    SnapshotCorrupt,
    SnapshotEntry,
    SnapshotManifest,
    decode_manifest,
    encode_manifest,
    tier_for,
    validate_snapshot_path,
)

WHEN = datetime(2026, 10, 22, 9, 30, tzinfo=UTC)


def entry(path: str, data: bytes = b"x") -> SnapshotEntry:
    return SnapshotEntry(
        path=path,
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
        media_type="text/plain",
        tier=tier_for(path),
        written_at=WHEN,
    )


def test_saved_folders_and_media_type() -> None:
    assert SAVED_FOLDERS == ("scratch", "reads", "work", "outputs")
    assert MANIFEST_MEDIA_TYPE == "application/vnd.clue.agent-workspace-manifest+json"


def test_tiers() -> None:
    assert tier_for("reads/op-1.json") == "raw_input"
    assert tier_for("work/conversation_history/e1.md") == "raw_input"
    assert tier_for("work/large_tool_results/x") == "raw_input"
    assert tier_for("work/deals_clean.csv") == "work_product"
    assert tier_for("scratch/notes.md") == "work_product"
    assert tier_for("outputs/table.csv") == "work_product"


@pytest.mark.parametrize(
    "bad",
    [
        "../x",
        "/etc/passwd",
        "outputs/../../x",
        "inputs/a.md",
        ".deepagent/x",
        "brand/x",
        "",
        "scratch/",
        "scratch//a",
        "scratch/./a",
        "scratch",
    ],
)
def test_validate_snapshot_path_refuses(bad: str) -> None:
    with pytest.raises(SnapshotCorrupt):
        validate_snapshot_path(bad)


def test_validate_snapshot_path_accepts_nested() -> None:
    assert validate_snapshot_path("work/conversation_history/media/a.png") == (
        "work/conversation_history/media/a.png"
    )


def test_manifest_round_trip_is_canonical() -> None:
    manifest = SnapshotManifest(entries=(entry("scratch/b.md"), entry("outputs/a.csv")))
    data = encode_manifest(manifest)
    decoded = decode_manifest(data)
    assert decoded == SnapshotManifest(
        entries=tuple(sorted(manifest.entries, key=lambda item: item.path))
    )
    assert encode_manifest(decoded) == data
    assert decoded.by_path()["scratch/b.md"].written_at == WHEN


def test_same_files_compares_paths_and_hashes_only() -> None:
    first = SnapshotManifest(entries=(entry("scratch/a.md", b"1"),))
    later = SnapshotManifest(
        entries=(
            SnapshotEntry(
                path="scratch/a.md",
                sha256=hashlib.sha256(b"1").hexdigest(),
                size=1,
                media_type="text/markdown",
                tier="work_product",
                written_at=datetime(2027, 1, 1, tzinfo=UTC),
            ),
        )
    )
    assert first.same_files(later)
    assert not first.same_files(SnapshotManifest(entries=(entry("scratch/a.md", b"2"),)))


def test_decode_refuses_bad_sha_and_paths() -> None:
    bad_path = (
        b'{"entries":[{"media_type":"text/plain","path":"../x","sha256":"'
        + b"a" * 64
        + b'","size":1,"tier":"work_product","written_at":"2026-10-22T09:30:00+00:00"}],'
        b'"schema_version":1}'
    )
    with pytest.raises(SnapshotCorrupt):
        decode_manifest(bad_path)
    bad_sha = bad_path.replace(b"../x", b"scratch/x").replace(b"a" * 64, b"zz")
    with pytest.raises(SnapshotCorrupt):
        decode_manifest(bad_sha)
    with pytest.raises(SnapshotCorrupt):
        decode_manifest(b"not json")


def test_decode_refuses_unknown_schema_version() -> None:
    data = encode_manifest(SnapshotManifest(entries=())).replace(
        b'"schema_version":1', b'"schema_version":9'
    )
    with pytest.raises(SnapshotCorrupt):
        decode_manifest(data)
