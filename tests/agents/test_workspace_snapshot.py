"""F3 Phase 1, plan Task 2: the snapshot file list, its tiers and its path rules (spec WS-2, WS-4,
WS-5; AW-14). Phase 2, Task 3 adds the third tier, per-file receipts and expired entries
(rulings AW-2, AW-22, AW-24)."""

from __future__ import annotations

import hashlib
import json
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


def _stored_list(*items: SnapshotEntry) -> bytes:
    """A file list as a version saved before fix pass 1 stored it: entries in the order given,
    and no path check, so an entry may name a ``.clue-tmp-*`` folder or file."""

    def raw(item: SnapshotEntry) -> dict[str, object]:
        document: dict[str, object] = {
            "path": item.path,
            "sha256": item.sha256,
            "size": item.size,
            "media_type": item.media_type,
            "tier": item.tier,
            "written_at": item.written_at.isoformat(),
        }
        if item.receipt is not None:
            document["receipt"] = {
                "source": item.receipt.source,
                "operation_id": item.receipt.operation_id,
                "produced_at": None,
                "details": dict(item.receipt.details),
                "read_again": item.receipt.read_again,
            }
        if item.expired_at is not None:
            document["expired_at"] = item.expired_at.isoformat()
        return document

    return json.dumps({"schema_version": 2, "entries": [raw(item) for item in items]}).encode()


def test_a_stored_entry_under_a_temporary_folder_is_renamed_not_dropped() -> None:
    """Founder ruling 2026-10-24: a list saved before the save refused ``.clue-tmp-*`` still
    decodes, and the entry is **renamed**, not dropped — dropping it made the next save release
    its bytes and erase them, and ``outputs/`` is never deleted. Only the path changes: the hash,
    size, media type, times and receipt are the stored ones, so it names the same stored file."""

    receipt = Receipt(source="run_python", operation_id="op-7", read_again="Run it again.")
    bad = replace(entry("outputs/.clue-tmp-a/r.md", b"the report"), receipt=receipt)
    good = entry("outputs/ok.md", b"ok")
    decoded = decode_manifest(_stored_list(bad, good)).by_path()

    assert sorted(decoded) == ["outputs/clue-tmp-a/r.md", "outputs/ok.md"]
    renamed = decoded["outputs/clue-tmp-a/r.md"]
    assert renamed == replace(bad, path="outputs/clue-tmp-a/r.md")
    assert (renamed.sha256, renamed.size, renamed.receipt) == (bad.sha256, bad.size, receipt)
    assert renamed.tier == "work_product"
    assert decoded["outputs/ok.md"] == good
    # The renamed list is one the disk can hold: it saves, and decodes to itself.
    again = encode_manifest(SnapshotManifest(entries=tuple(decoded.values())))
    assert decode_manifest(again).by_path() == decoded


def test_a_temporary_file_name_is_renamed_the_same_way() -> None:
    """A ``.clue-tmp-*`` FILE (an atomic write's leftover, not a folder) loses its leading dot
    too. An expired entry keeps its expiry, and its tier is still the one its path gives."""

    gone = datetime(2026, 10, 23, tzinfo=UTC)
    leftover = replace(entry("scratch/.clue-tmp-9f.md", b"half"), expired_at=gone)
    decoded = decode_manifest(_stored_list(leftover)).by_path()

    assert decoded == {"scratch/clue-tmp-9f.md": replace(leftover, path="scratch/clue-tmp-9f.md")}
    assert decoded["scratch/clue-tmp-9f.md"].tier == "working_file"


def test_a_renamed_path_already_in_the_list_is_numbered_deterministically() -> None:
    """A legal entry keeps its path; a renamed one that lands on a taken path is numbered before
    its extension until it is free (``r.md`` and ``r-1.md`` taken → ``r-2.md``). Two reserved
    entries that strip to the same path are numbered in the order of their stored paths, so the
    same list gives the same answer whatever order its entries were stored in."""

    held = entry("outputs/clue-tmp-a/r.md", b"already here")
    held_too = entry("outputs/clue-tmp-a/r-1.md", b"also here")
    moved = entry("outputs/.clue-tmp-a/r.md", b"moved")
    twin_one = entry("outputs/.clue-tmp-a/.clue-tmp-b.md", b"twin one")
    twin_two = entry("outputs/clue-tmp-a/.clue-tmp-b.md", b"twin two")
    items = (twin_two, held, moved, twin_one, held_too)

    decoded = decode_manifest(_stored_list(*items))
    assert decode_manifest(_stored_list(*reversed(items))) == decoded
    assert {item.path: item.sha256 for item in decoded.entries} == {
        "outputs/clue-tmp-a/r.md": held.sha256,
        "outputs/clue-tmp-a/r-1.md": held_too.sha256,
        "outputs/clue-tmp-a/r-2.md": moved.sha256,
        "outputs/clue-tmp-a/clue-tmp-b.md": twin_one.sha256,
        "outputs/clue-tmp-a/clue-tmp-b-1.md": twin_two.sha256,
    }


def test_a_renamed_path_never_clashes_a_file_with_a_folder() -> None:
    """A restore cannot write a file and a folder of the same name. When a renamed folder is a
    file the list holds, that folder is numbered; when a renamed file is a folder the list holds,
    the file is numbered."""

    file_there = entry("outputs/clue-tmp-z", b"a file")
    under = entry("outputs/.clue-tmp-z/r.md", b"under it")
    folder_there = entry("outputs/clue-tmp-q/x.md", b"in a folder")
    leftover = entry("outputs/.clue-tmp-q", b"a leftover")

    decoded = decode_manifest(_stored_list(file_there, under, folder_there, leftover))
    assert {item.path: item.sha256 for item in decoded.entries} == {
        "outputs/clue-tmp-z": file_there.sha256,
        "outputs/clue-tmp-z-1/r.md": under.sha256,
        "outputs/clue-tmp-q/x.md": folder_there.sha256,
        "outputs/clue-tmp-q-1": leftover.sha256,
    }


@pytest.mark.parametrize(
    "path",
    ["outputs/.clue-tmp-a/../r.md", "outputs/../r.md", ".clue-tmp-a/r.md", "inputs/.clue-tmp-a/r"],
)
def test_every_other_bad_path_still_refuses_the_list(path: str) -> None:
    with pytest.raises(SnapshotCorrupt):
        decode_manifest(_stored_list(entry("outputs/ok.md"), entry(path)))


def test_a_reserved_path_stored_twice_still_refuses_the_list() -> None:
    twice = entry("outputs/.clue-tmp-a/r.md")
    with pytest.raises(SnapshotCorrupt):
        decode_manifest(_stored_list(twice, twice))
