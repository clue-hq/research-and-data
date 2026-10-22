"""F3 Phase 1, plan Task 2: the snapshot file list, its tiers and its path rules (spec WS-2, WS-4,
WS-5; AW-14). Phase 2, Task 3 adds the third tier, per-file receipts and expired entries
(rulings AW-2, AW-22, AW-24)."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from clue_agents.workspace_snapshot import (
    MANIFEST_MEDIA_TYPE,
    MANIFEST_SCHEMA_VERSION,
    SAVED_FOLDERS,
    Receipt,
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


def test_tier_for_three_tiers() -> None:
    """AW-2/AW-22: raw inputs, the agent's own working files, and the finished work it keeps."""

    assert tier_for("reads/op-1.json") == "raw_input"
    assert tier_for("work/conversation_history/e1.md") == "raw_input"
    assert tier_for("work/large_tool_results/x") == "raw_input"
    assert tier_for("work/deals_clean.csv") == "working_file"
    assert tier_for("scratch/notes.md") == "working_file"
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
                tier="working_file",
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
        b'"schema_version":2', b'"schema_version":9'
    )
    with pytest.raises(SnapshotCorrupt):
        decode_manifest(data)


def test_schema_1_file_list_still_decodes_with_tiers_from_the_path() -> None:
    """A Phase 1 list called every non-raw file a work product; the path decides now."""

    old = (
        b'{"entries":[{"media_type":"text/plain","path":"scratch/a.md","sha256":"'
        + hashlib.sha256(b"x").hexdigest().encode()
        + b'","size":1,"tier":"work_product","written_at":"2026-10-22T09:30:00+00:00"}],'
        b'"schema_version":1}'
    )
    decoded = decode_manifest(old)
    only = decoded.entries[0]
    assert only.tier == "working_file"
    assert only.receipt is None and only.expired_at is None
    assert decoded.schema_version == MANIFEST_SCHEMA_VERSION


def test_round_trip_keeps_receipt_and_expired_at() -> None:
    receipt = Receipt(
        source="run_crm_action",
        operation_id="op-7",
        produced_at=datetime(2026, 10, 21, 8, tzinfo=UTC),
        details={"tool": "hubspot", "records": 120},
        read_again="run_crm_action(action='deals.list', page=1)",
    )
    gone = replace(entry("reads/op-7.json"), receipt=receipt, expired_at=WHEN)
    manifest = SnapshotManifest(entries=(gone, entry("outputs/a.csv")))
    data = encode_manifest(manifest)
    decoded = decode_manifest(data)
    assert decoded.by_path()["reads/op-7.json"].receipt == receipt
    assert decoded.by_path()["reads/op-7.json"].expired_at == WHEN
    assert decoded.by_path()["outputs/a.csv"].receipt is None
    assert encode_manifest(decoded) == data
    assert [e.path for e in decoded.live()] == ["outputs/a.csv"]
    assert [e.path for e in decoded.expired()] == ["reads/op-7.json"]


def test_a_file_list_with_no_receipts_writes_neither_key() -> None:
    """A Phase 1-shaped list round-trips to the same bytes: no nulls are written."""

    data = encode_manifest(SnapshotManifest(entries=(entry("outputs/a.csv"),)))
    assert b"receipt" not in data and b"expired_at" not in data


def test_same_files_notices_an_expiry() -> None:
    """An expiry is a change: otherwise the save would call it unchanged and never persist it."""

    live = SnapshotManifest(entries=(entry("reads/r.json", b"1"),))
    gone = SnapshotManifest(entries=(replace(entry("reads/r.json", b"1"), expired_at=WHEN),))
    assert not live.same_files(gone)
    assert not gone.same_files(live)
    assert gone.same_files(gone)
