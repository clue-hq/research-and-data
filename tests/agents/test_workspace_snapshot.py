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


def _phase_1_list(path: str) -> bytes:
    """A one-file list exactly as Phase 1 wrote it: schema 1, every non-raw file a work product."""

    return (
        b'{"entries":[{"media_type":"text/plain","path":"'
        + path.encode()
        + b'","sha256":"'
        + hashlib.sha256(b"x").hexdigest().encode()
        + b'","size":1,"tier":"work_product","written_at":"2026-10-22T09:30:00+00:00"}],'
        b'"schema_version":1}'
    )


def test_a_phase_1_list_re_encodes_with_its_entries_unchanged_but_not_byte_identical() -> None:
    """What omitting the two new keys does and does not buy (review area 2, M4).

    It was claimed that a list with no receipt and no expiry "round-trips to the same bytes" as
    the Phase 1 shape. It does not: the list is re-written as schema 2, and a ``scratch/`` or
    ``work/`` entry's stored ``work_product`` becomes ``working_file`` because the path decides
    the tier. What is true is narrower, and is what this pins: an entry with neither key is
    written with exactly the keys a Phase 1 entry had, and no nulls — so an ``outputs/`` file's
    entry comes back byte for byte and only the schema number moves. (Nothing re-hashes a
    re-encoded list: an unchanged chat is only touched, never re-saved.)
    """

    outputs = _phase_1_list("outputs/a.csv")
    assert encode_manifest(decode_manifest(outputs)) == outputs.replace(
        b'"schema_version":1', b'"schema_version":2'
    )

    scratch = _phase_1_list("scratch/a.md")
    assert encode_manifest(decode_manifest(scratch)) == scratch.replace(
        b'"schema_version":1', b'"schema_version":2'
    ).replace(b'"tier":"work_product"', b'"tier":"working_file"')


def test_same_files_notices_an_expiry() -> None:
    """An expiry is a change: otherwise the save would call it unchanged and never persist it."""

    live = SnapshotManifest(entries=(entry("reads/r.json", b"1"),))
    gone = SnapshotManifest(entries=(replace(entry("reads/r.json", b"1"), expired_at=WHEN),))
    assert not live.same_files(gone)
    assert not gone.same_files(live)
    assert gone.same_files(gone)


# --- One path rule for save and restore (fix pass 1, review A2-I3) --------------------------------


@pytest.mark.parametrize("segment", [".clue-tmp-a", ".clue-tmp-", "..", ".", "", "a\x00b"])
def test_a_segment_the_disk_refuses_is_refused_by_the_file_list(segment: str) -> None:
    """The disk layer's rule is the file list's rule: a path a restore could never write is never
    accepted, so it can never be saved and then refuse every restore on every machine."""

    from clue_agents.tree_sync import check_segment
    from clue_agents.workspace_policy import WorkspaceSecurityError

    with pytest.raises(WorkspaceSecurityError):
        check_segment(segment)
    with pytest.raises(SnapshotCorrupt):
        validate_snapshot_path(f"outputs/{segment}/r.md")


@pytest.mark.parametrize("segment", ["clue-tmp-a", ".clue-tmpa", "a.clue-tmp-", ".hidden"])
def test_a_segment_the_disk_accepts_is_accepted_by_the_file_list(segment: str) -> None:
    from clue_agents.tree_sync import check_segment

    assert check_segment(segment) == segment
    assert validate_snapshot_path(f"outputs/{segment}/r.md") == f"outputs/{segment}/r.md"


def test_a_file_list_naming_a_temporary_folder_is_refused_at_save() -> None:
    """``outputs/.clue-tmp-a/r.md`` used to be saved and then refused on every restore — and,
    under ``outputs/``, it never expired, so the chat could never run again (review A2-I3)."""

    poisoned = SnapshotManifest(entries=(entry("outputs/ok.md"), entry("outputs/.clue-tmp-a/r.md")))
    with pytest.raises(SnapshotCorrupt):
        encode_manifest(poisoned)


def test_a_stored_file_list_naming_a_temporary_folder_drops_only_that_entry() -> None:
    """A file list saved before the save refused it still decodes: the entry no disk can hold is
    dropped, and every other entry is kept. Anything else wrong with a path still refuses."""

    good, bad = entry("outputs/ok.md", b"ok"), entry("outputs/.clue-tmp-a/r.md", b"r")
    body = (
        b'{"entries":['
        + b",".join(
            (
                b'{"media_type":"text/plain","path":"%s","sha256":"%s","size":%d,'
                b'"tier":"work_product","written_at":"2026-10-22T09:30:00+00:00"}'
            )
            % (item.path.encode(), item.sha256.encode(), item.size)
            for item in (bad, good)
        )
        + b'],"schema_version":2}'
    )
    assert [item.path for item in decode_manifest(body).entries] == ["outputs/ok.md"]
    with pytest.raises(SnapshotCorrupt):
        decode_manifest(body.replace(b"outputs/.clue-tmp-a/r.md", b"outputs/../r.md"))
