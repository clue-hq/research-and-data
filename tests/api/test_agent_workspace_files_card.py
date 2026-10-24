"""The turn-start card of a chat's own files (F3 Phase 2, WS-28, spec D-23).

Pure function over the restored file list: no disk, no database, no clock of its own. The ages
the tests pin are exact because ``now`` is passed in.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from clue_agents.workspace_snapshot import (
    UNKNOWN_RECEIPT,
    Receipt,
    SnapshotEntry,
    SnapshotManifest,
    tier_for,
)
from clue_api.agent_workspace_files_card import (
    WORKSPACE_FILES_MAX_EXPIRED,
    WORKSPACE_FILES_MAX_LISTED,
    WORKSPACE_FILES_MEDIA_TYPE,
    build_workspace_files_card,
)

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


def _entry(
    path: str,
    *,
    written_at: datetime,
    size: int = 3,
    receipt: Receipt | None = None,
    expired_at: datetime | None = None,
) -> SnapshotEntry:
    return SnapshotEntry(
        path=path,
        sha256="a" * 64,
        size=size,
        media_type="text/plain",
        tier=tier_for(path),
        written_at=written_at,
        receipt=receipt,
        expired_at=expired_at,
    )


def test_card_lists_live_files_with_age_and_expired_files_with_receipts() -> None:
    """What the agent still has, how old it is, and what is gone with the way to get it again."""

    manifest = SnapshotManifest(
        entries=(
            _entry("scratch/a", written_at=NOW - timedelta(days=2)),
            _entry(
                "reads/r.json",
                written_at=NOW - timedelta(days=5),
                receipt=Receipt(
                    source="run_crm_action",
                    operation_id="op-1",
                    produced_at=NOW - timedelta(days=5),
                    details={"tool": "run_crm_action"},
                    read_again="Call run_crm_action again with the same parameters.",
                ),
                expired_at=NOW - timedelta(days=3),
            ),
        )
    )

    card = build_workspace_files_card(manifest, now=NOW)

    assert card["schema_version"] == "1"
    assert card["generated_at"] == NOW.isoformat()
    assert card["live"] == [
        {
            "path": "scratch/a",
            "folder": "scratch",
            "size": 3,
            "age_hours": 48,
            "tier": "working_file",
        }
    ]
    assert card["omitted"] == {}
    expired = card["expired"]
    assert isinstance(expired, list)
    assert len(expired) == 1
    assert expired[0]["path"] == "reads/r.json"
    assert expired[0]["tier"] == "raw_input"
    assert expired[0]["expired_at"] == (NOW - timedelta(days=3)).isoformat()
    assert expired[0]["receipt"]["source"] == "run_crm_action"
    assert expired[0]["receipt"]["operation_id"] == "op-1"
    assert expired[0]["receipt"]["details"] == {"tool": "run_crm_action"}
    assert expired[0]["receipt"]["read_again"] == (
        "Call run_crm_action again with the same parameters."
    )
    # The founder-approved sentence of 2026-10-23, verbatim: agent-facing text is reviewed, so a
    # careless edit must fail the build rather than reach an agent.
    assert card["note"] == (
        "Files are deleted by age: what a tool pulled down after 48 hours, your own working "
        "files after 7 days. outputs/ is kept for the life of the chat."
    )


def test_card_bounds_the_live_list_and_says_what_was_left_out() -> None:
    """A long list is cut, and the agent is told how many it was not shown, by folder."""

    manifest = SnapshotManifest(
        entries=tuple(
            _entry(f"work/f{index:04d}.txt", written_at=NOW - timedelta(hours=1))
            for index in range(250)
        )
    )

    card = build_workspace_files_card(manifest, now=NOW)

    live = card["live"]
    assert isinstance(live, list)
    assert len(live) == WORKSPACE_FILES_MAX_LISTED == 200
    assert [item["path"] for item in live[:2]] == ["work/f0000.txt", "work/f0001.txt"]
    assert card["omitted"] == {"work": 50}


def test_card_bounds_the_expired_list_newest_first_and_says_what_was_left_out() -> None:
    """Review I6: the expired half grows for the chat's life, so it is bounded like the live one.

    Expired entries are never dropped from the file list (WS-25) and a CRM-heavy chat spills
    ``reads/`` every turn, so after a few months the unbounded list was thousands of entries —
    each with its whole receipt — re-sent in every turn's context. Newest first, because the
    file the agent just lost is the one it is about to ask about.
    """

    manifest = SnapshotManifest(
        entries=tuple(
            _entry(
                f"reads/r{index:04d}.json",
                written_at=NOW - timedelta(days=30),
                expired_at=NOW - timedelta(hours=index + 1),
            )
            for index in range(250)
        )
    )

    card = build_workspace_files_card(manifest, now=NOW)

    expired = card["expired"]
    assert isinstance(expired, list)
    assert len(expired) == WORKSPACE_FILES_MAX_EXPIRED == 200
    # The two most recently expired, not the two alphabetically first.
    assert [item["path"] for item in expired[:2]] == ["reads/r0000.json", "reads/r0001.json"]
    assert expired[-1]["path"] == "reads/r0199.json"
    assert card["omitted_expired"] == {"reads": 50}


def test_an_empty_or_missing_manifest_gives_an_empty_card() -> None:
    """A brand-new chat, or snapshots switched off: the card is honest rather than absent."""

    for manifest in (None, SnapshotManifest(entries=())):
        card = build_workspace_files_card(manifest, now=NOW)
        assert card["live"] == []
        assert card["expired"] == []
        assert card["omitted"] == {}


def test_an_expired_entry_with_no_receipt_still_reads_as_a_receipt() -> None:
    """Task 5 stamps one on every expiry; the card does not depend on that to hold its shape."""

    manifest = SnapshotManifest(
        entries=(
            _entry(
                "work/large_tool_results/clip.txt",
                written_at=NOW - timedelta(days=9),
                expired_at=NOW - timedelta(days=1),
            ),
        )
    )

    card = build_workspace_files_card(manifest, now=NOW)

    expired = card["expired"]
    assert isinstance(expired, list)
    assert expired[0]["receipt"] == {
        "source": "unknown",
        "operation_id": None,
        "produced_at": None,
        "details": {},
        "read_again": UNKNOWN_RECEIPT.read_again,
    }


def test_the_card_counts_whole_hours_and_never_a_negative_age() -> None:
    """``age_hours`` is floored, and a file written after ``now`` is zero rather than nonsense."""

    manifest = SnapshotManifest(
        entries=(
            _entry("outputs/done.md", written_at=NOW - timedelta(hours=3, minutes=59)),
            _entry("scratch/ahead.md", written_at=NOW + timedelta(minutes=5)),
        )
    )

    card = build_workspace_files_card(manifest, now=NOW)

    live = card["live"]
    assert isinstance(live, list)
    assert {item["path"]: item["age_hours"] for item in live} == {
        "outputs/done.md": 3,
        "scratch/ahead.md": 0,
    }
    assert {item["path"]: item["tier"] for item in live} == {
        "outputs/done.md": "work_product",
        "scratch/ahead.md": "working_file",
    }


def test_the_media_type_names_this_card() -> None:
    assert WORKSPACE_FILES_MEDIA_TYPE == "application/vnd.clue.agent-workspace-files+json"


def test_an_expired_entry_says_how_much_it_held() -> None:
    """Fix pass 1: the founder-approved manual (Task 8, text (b)) tells the agent a deleted file
    keeps a receipt saying "how much it held". Only a CRM read's receipt counted records; every
    other expired entry said nothing about its size. The file list has it, so the card says it."""

    manifest = SnapshotManifest(
        entries=(
            _entry(
                "work/large_tool_results/clip.txt",
                written_at=NOW - timedelta(days=9),
                size=48_213,
                expired_at=NOW - timedelta(days=1),
            ),
            _entry(
                "scratch/model.py",
                written_at=NOW - timedelta(days=9),
                size=7,
                receipt=UNKNOWN_RECEIPT,
                expired_at=NOW - timedelta(days=2),
            ),
        )
    )

    card = build_workspace_files_card(manifest, now=NOW)

    expired = card["expired"]
    assert isinstance(expired, list)
    assert {item["path"]: item["size"] for item in expired} == {
        "work/large_tool_results/clip.txt": 48_213,
        "scratch/model.py": 7,
    }
